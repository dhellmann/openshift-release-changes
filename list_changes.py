#!/usr/bin/env python3

import argparse
import json
import os
import pathlib
import subprocess

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

            try:
                z_dir.mkdir()
            except FileExistsError:
                pass
            with info_file.open('wb') as f:
                f.write(info_content)
            print()

        release_info = json.loads(info_content)
        rhcos_version = get_rhcos_version(release_info)
        print(rhcos_version)


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
