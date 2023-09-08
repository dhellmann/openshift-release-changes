#!/usr/bin/env python3

import argparse
import collections
import datetime
import difflib
import json
import logging
import os
import pathlib
import ssl
import subprocess
import sys
import urllib.request

CACHE_DIR=pathlib.Path('data_cache')
INCLUDE_REBUILDS=False
ADVISORY_SEVERITIES = {}


def main():
    global INCLUDE_REBUILDS

    parser = argparse.ArgumentParser()
    parser.add_argument('--series', default=None,
                        help='Release series. (%(default)s)')
    parser.add_argument('--include-rebuilds',
                        default=False,
                        action='store_true',
                        help='show package changes that are rebuilds of the same version',
                        )
    parser.add_argument('-v', '--verbose',
                        dest='log_level',
                        default=logging.INFO,
                        action='store_const',
                        const=logging.DEBUG,
                        help='Verbose mode',
                        )
    args = parser.parse_args()

    INCLUDE_REBUILDS = args.include_rebuilds

    logging.basicConfig(
        level=args.log_level,
        stream=sys.stderr,
    )

    if args.series:
        all_series = [args.series]
    else:
        all_series = ['4.13', '4.12', '4.11', '4.10', '4.9', '4.8']

    if not CACHE_DIR.is_dir():
        CACHE_DIR.mkdir()
    for series in all_series:
        download_release_data(series)
    for series in all_series:
        show_series(series)

    return 0


def download_release_data(series):
    logging.info('downloading data for %s', series)
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

        if info_file.is_file():
            logging.debug('%s image metadata cached', image_spec)
            info_content = info_file.read_text()
        else:
            logging.debug('%s downloading image metadata', image_spec)

            complete = subprocess.run(
                ['oc', 'adm', 'release', 'info', '-o', 'json', image_spec],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if complete.returncode != 0:
                logging.debug('%s no such release', image_spec)
                break
            info_content = complete.stdout

            if not z_dir.is_dir():
                z_dir.mkdir()
            with info_file.open('wb') as f:
                f.write(info_content)

        release_info = json.loads(info_content)
        rhcos_version = get_rhcos_version(release_info)
        download_rhcos_data(rhcos_version)


def download_rhcos_data(version):
    rhcos_dir = CACHE_DIR / 'rhcos'
    if not rhcos_dir.is_dir():
        rhcos_dir.mkdir()
    version_dir = rhcos_dir / version
    if not version_dir.is_dir():
        version_dir.mkdir()
    metadata_file = version_dir / 'commitmeta.json'
    if metadata_file.is_file():
        logging.debug('%s RHCOS data is cached', version)
        return

    urls = []

    url_template = 'https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/storage/prod/streams/{stream}/builds/{version}/x86_64/commitmeta.json'
    # Some older series have the RHCOS metadata in a different place
    url_template_old = 'https://releases-rhcos-art.apps.ocp-virt.prod.psi.redhat.com/storage/releases/{stream}/{version}/x86_64/commitmeta.json'

    version_parts = version.split('.')
    # 412 -> 4.12
    stream = version_parts[0][0] + '.' + version_parts[0][1:]
    # RHEL 9.x images include the RHEL version in the stream part of the URL
    if version_parts[1][0] != '8':
        stream = stream + '-' + version_parts[1][0] + '.' + version_parts[1][1:]

    urls.append(url_template.format(stream=stream, version=version))
    urls.append(url_template_old.format(stream='rhcos-' + stream, version=version))

    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    logging.debug('downloading RHCOS metadata for %s', version)
    for url in urls:
        logging.debug('trying %s', url)
        try:
            response = urllib.request.urlopen(url, context=context)
        except urllib.error.HTTPError:
            pass
        else:
            metadata_content = response.read()
            with metadata_file.open('wb') as f:
                f.write(metadata_content)
            break
    else:
        logging.warning('Unable to find metadata for RHCOS %s', version)


def get_rhcos_version(release_info):
    for image in release_info['references']['spec']['tags']:
        if image['name'] != 'machine-os-content':
            continue
        long_version = image['annotations']['io.openshift.build.versions']
        short_version = long_version.partition('=')[-1]
        return short_version
    raise ValueError('Did not find "machine-os-content" image')


def show_series(series):
    print(f'\n{series}')
    show_rhcos_changes(series)


def show_rhcos_changes(series):
    # Prime the loop so that the first thing we do is move "to" to "from".
    to_series_ver = series + '.0'
    try:
        to_info = json.loads((CACHE_DIR / series / to_series_ver / 'release_info.json').read_text())
    except FileNotFoundError:
        logging.warning('no series data for %s', series)
        return
    z_version = 0

    while True:
        # Step forward through the series taking the "from" values
        # from the last "to" values.
        from_series_ver = to_series_ver
        from_info = to_info

        z_version += 1
        to_series_ver = series + '.' + str(z_version)
        to_info_file = CACHE_DIR / series / to_series_ver / 'release_info.json'
        if not to_info_file.is_file():
            break
        to_info = json.loads(to_info_file.read_text())

        from_rhcos_ver = get_rhcos_version(from_info)
        to_rhcos_ver = get_rhcos_version(to_info)

        def parse_datetime(dt):
            # 2023-05-16T10:09:04Z
            return datetime.datetime.strptime(dt, '%Y-%m-%dT%H:%M:%SZ')

        from_created = parse_datetime(from_info['config']['created'])
        to_created = parse_datetime(to_info['config']['created'])
        age = to_created - from_created

        print(f'\n{from_series_ver} ({from_rhcos_ver}) -> {to_series_ver} ({to_rhcos_ver})')
        print(f'\n  Created {to_created} (age: {age})')

        if from_rhcos_ver == to_rhcos_ver:
            print('  Same RHCOS version')
            continue

        try:
            from_rhcos_data = json.loads((CACHE_DIR / 'rhcos' / from_rhcos_ver / 'commitmeta.json').read_text())
            to_rhcos_data = json.loads((CACHE_DIR / 'rhcos' / to_rhcos_ver / 'commitmeta.json').read_text())
        except FileNotFoundError as err:
            print(f'  unable to load RHCOS metadata: {err}')
            continue

        advisories_by_packages = get_advisories_by_package(to_rhcos_data)

        from_packages = sorted([tuple(p) for p in from_rhcos_data['rpmostree.rpmdb.pkglist']])
        to_packages = sorted([tuple(p) for p in to_rhcos_data['rpmostree.rpmdb.pkglist']])

        matcher = difflib.SequenceMatcher(None, from_packages, to_packages)
        changes = matcher.get_opcodes()
        print('\n  Package updates:')
        if not changes:
            print('    No changes to packages')
            continue
        found_changes = 0
        rebuilds = 0
        for tag, i1, i2, j1, j2 in changes:
            if tag == 'equal':
                continue
            from_pkg = from_packages[i1]
            to_pkg = to_packages[j1]
            name = from_pkg[0]
            from_pkg_ver = from_pkg[2] + '-' + from_pkg[3]
            to_pkg_ver = to_pkg[2] + '-' + to_pkg[3]
            if tag == 'replace':
                # ignore rebuilds
                is_rebuild = from_pkg[2] == to_pkg[2]
                if is_rebuild:
                    rebuilds += 1
                if (not is_rebuild) or INCLUDE_REBUILDS:
                    found_changes += 1
                    print(f'    {name} {from_pkg_ver} -> {to_pkg_ver}')
                    adv_key = name + '-' + '-'.join(to_pkg[2:-1]) + '.' + to_pkg[-1]
                    for adv in advisories_by_packages.get(adv_key, []):
                        sev = get_advisory_severity_from_message(adv)
                        print(f'      {sev} {adv}')
            elif tag == 'delete':
                found_changes += 1
                print(f'    {name} no longer included')
            elif tag == 'insert':
                found_changes += 1
                print(f'    {name} {to_pkg_ver} added')
            else:
                found_changes += 1
                print(tag, i1, i2, j1, j2)
        if not found_changes:
            print('    Same versions of all packages')
        else:
            print(f'\n  {found_changes} packages upgraded')
        if rebuilds:
            print(f'\n  {rebuilds} packages rebuilt')


def get_advisories_by_package(rhcos_data):
    advisories = collections.defaultdict(list)
    for advisory in rhcos_data['rpmostree.advisories']:
        for pkg in advisory[3]:
            for ref in advisory[4]['cve_references']:
                advisories[pkg].append(ref[1])
    return advisories


def get_advisory_severity_from_message(message):
    cve_cache = CACHE_DIR / 'cve'
    if not cve_cache.is_dir():
        cve_cache.mkdir()
    cve = message.split(' ')[0]
    if not cve.startswith('CVE'):
        return ''
    if cve not in ADVISORY_SEVERITIES:
        cve_file = cve_cache / f'{cve}.json'
        if cve_file.is_file():
            content = cve_file.read_text()
        else:
            # For some reason, curl can access these URLs but Python
            # cannot. Just use curl in this hacky script.
            url = f'https://access.redhat.com/hydra/rest/securitydata/cve/{cve}.json'
            complete = subprocess.run(
                ['curl', url],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            content = complete.stdout
            with cve_file.open('wb') as f:
                f.write(content)
        data = json.loads(content)
        ADVISORY_SEVERITIES[cve] = data['threat_severity']
    return ADVISORY_SEVERITIES[cve]


if __name__ == '__main__':
    main()
