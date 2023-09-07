#!/usr/bin/env python3

import argparse
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
            print(' cached')
            continue
        else:
            print(' downloading...', end='', flush=True)

        complete = subprocess.run(
            ['oc', 'adm', 'release', 'info', '-o', 'json', image_spec],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if complete.returncode != 0:
            print(' no such release')
            break
        release_info = complete.stdout

        try:
            z_dir.mkdir()
        except FileExistsError:
            pass
        with info_file.open('wb') as f:
            f.write(release_info)
        print()


if __name__ == '__main__':
    main()
