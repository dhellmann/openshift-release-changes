#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import ssl
import subprocess
import urllib.request

CACHE_DIR=pathlib.Path('data_cache')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--series', default='4.12',
                        help='Release series. (%(default)s)')
    args = parser.parse_args()

    try:
        CACHE_DIR.mkdir()
    except FileExistsError:
        pass
    download_release_data(args.series)

    return 0


def download_release_data(series):
    image_spec_template = 'quay.io/openshift-release-dev/ocp-release:{full_version}-x86_64'
    series_dir = CACHE_DIR / series
    try:
        series_dir.mkdir()
    except FileExistsError:
        pass

    z_version = -1
    while True:
        z_version += 1
        full_version = f'{series}.{z_version}'
        z_dir = series_dir / full_version
        info_file = z_dir / 'release_info.json'

        image_spec = image_spec_template.format(full_version=full_version)
        print(image_spec, end='', flush=True)

        if info_file.is_file():
            print(' image metadata cached')
            info_content = info_file.read_text()
        else:
            print(' downloading image metadata...', end='', flush=True)

            complete = subprocess.run(
                ['oc', 'adm', 'release', 'info', '-o', 'json', image_spec],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if complete.returncode != 0:
                print(' no such release')
                break
            info_content = complete.stdout

            if not z_dir.is_dir():
                z_dir.mkdir()
            with info_file.open('wb') as f:
                f.write(info_content)
            print()

        release_info = json.loads(info_content)
        rhcos_version = get_rhcos_version(release_info)
        get_rhcos_data(rhcos_version)


def get_rhcos_data(version):
    print(version, end='', flush=True)

    rhcos_dir = CACHE_DIR / 'rhcos'
    if not rhcos_dir.is_dir():
        rhcos_dir.mkdir()
    version_dir = rhcos_dir / version
    if not version_dir.is_dir():
        version_dir.mkdir()
    metadata_file = version_dir / 'commitmeta.json'
    if metadata_file.is_file():
        print(' data is cached')
        return
    print(' downloading RHCOS metadata...', end='', flush=True)

    url_template = 'https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/storage/prod/streams/{stream}/builds/{version}/x86_64/commitmeta.json'
    version_parts = version.split('.')
    # 412 -> 4.12
    stream = version_parts[0][0] + '.' + version_parts[0][1:]
    if version_parts[1] != '86':
        stream = stream + '-' + version_parts[1][0] + '.' + version_parts[1][1:]
    url = url_template.format(stream=stream, version=version)

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    response = urllib.request.urlopen(url, context=context)
    metadata_content = response.read()
    with metadata_file.open('wb') as f:
        f.write(metadata_content)

    print()


def get_rhcos_version(release_info):
    for image in release_info['references']['spec']['tags']:
        if image['name'] != 'machine-os-content':
            continue
        long_version = image['annotations']['io.openshift.build.versions']
        short_version = long_version.partition('=')[-1]
        return short_version
    raise ValueError('Did not find "machine-os-content" image')


if __name__ == '__main__':
    main()
