#!/usr/bin/env python3
"""Fetch the pinned b5q porting workspace without building or flashing a device."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, env=None):
    print('+', ' '.join(str(arg) for arg in args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, env=env, check=True)


def git_output(path, *args):
    return subprocess.check_output(
        ['git', '-C', str(path), *args], text=True
    ).strip()


def ensure_repo(path, entry):
    if not (path / '.git').exists():
        if path.exists() and any(path.iterdir()):
            raise RuntimeError(f'Refusing to replace a nonempty directory: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        options = ['--depth', '1', '--no-tags']
        if entry.get('sparse'):
            options += ['--filter=blob:none', '--sparse']
        run('git', 'clone', *options, entry['url'], path)
    current = git_output(path, 'rev-parse', 'HEAD')
    if current != entry['commit']:
        if git_output(path, 'status', '--porcelain'):
            raise RuntimeError(f'Refusing to change a dirty checkout: {path}')
        run('git', '-C', path, 'fetch', '--depth', '1', 'origin', entry['commit'])
        run('git', '-C', path, 'checkout', '--detach', entry['commit'])
    if entry.get('sparse'):
        run('git', '-C', path, 'sparse-checkout', 'set', *entry['sparse'])


def check_sources(lock):
    failures = []
    for entry in lock['sources']:
        path = ROOT / 'sources' / entry['name']
        try:
            actual = git_output(path, 'rev-parse', 'HEAD')
        except subprocess.CalledProcessError:
            failures.append(f"missing checkout: {entry['name']}")
            continue
        if actual != entry['commit']:
            failures.append(f"revision mismatch: {entry['name']}")
        else:
            print(f"OK {entry['name']}: {actual[:12]}")
    required = [
        'sources/Mu-Silicium/Resources/DTBs/b5q.dts',
        'sources/Mu-Silicium/Resources/DTBs/b5q.dtb',
        'sources/Mu-Silicium/Resources/Configs/b5q.toml',
        'sources/Mu-Silicium/Platforms/Samsung/b5qPkg/b5q.dsc',
        'sources/Mu-Silicium/Platforms/Samsung/b5qPkg/b5q.fdf',
        'sources/Device-Binaries/b5q/README.md',
        'sources/UniXNU-sm8550-common/dts/sm8550.dtsi',
        'sources/UniXNU-sheng/dts/sheng.dts',
    ]
    for relative in required:
        if not (ROOT / relative).is_file():
            failures.append(f'missing input: {relative}')
    if failures:
        raise RuntimeError('\n'.join(failures))
    print('Pinned source check passed. This is not a b5q build or boot test.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='verify sources without network access')
    parser.add_argument('--sources-only', action='store_true', help='skip nested build dependencies')
    parser.add_argument('--with-ipsw-inputs', action='store_true', help='also extract the profile-selected IPSW components')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error('--jobs must be positive')
    lock = json.loads((ROOT / 'sources.lock.json').read_text())
    if args.check:
        check_sources(lock)
        return
    for entry in lock['sources']:
        ensure_repo(ROOT / 'sources' / entry['name'], entry)
    if not args.sources_only:
        mu = ROOT / 'sources/Mu-Silicium'
        vendor = next(entry for entry in lock['sources'] if entry['name'] == 'Device-Binaries')
        if git_output(mu, 'rev-parse', 'HEAD:Binaries') != vendor['commit']:
            raise RuntimeError('Device-Binaries must match the Mu-Silicium Binaries gitlink')
        run('git', '-C', mu, 'submodule', 'init', 'Binaries')
        ensure_repo(mu / 'Binaries', vendor)
        if (mu / 'Binaries/.git').is_dir():
            run('git', '-C', mu, 'submodule', 'absorbgitdirs', 'Binaries')
        run('git', '-C', mu, 'submodule', 'update', '--init',
            '--depth', '1', '--jobs', str(args.jobs), '--', *lock['mu_submodules'])
        run('git', '-C', mu / 'Mu_Basecore', 'submodule', 'update', '--init',
            '--depth', '1', '--jobs', str(args.jobs), '--', *lock['mu_basecore_submodules'])
        unixnu = ROOT / 'sources/UniXNU'
        device = ROOT / 'sources' / lock['reference_device']
        options = ['--device', str(device), '--os', lock['os_profile']]
        print('Resolving dependencies with the sheng reference only; not building a b5q image.', flush=True)
        run('./unixnu', 'defconfig', lock['reference_defconfig'], *options, cwd=unixnu)
        run('./unixnu', 'fetch', *options, cwd=unixnu)
    if args.with_ipsw_inputs:
        unixnu = ROOT / 'sources/UniXNU'
        tool_build = ROOT / 'artifacts/lzfse-build'
        run('cmake', '-S', ROOT / 'sources/lzfse', '-B', tool_build, '-DCMAKE_BUILD_TYPE=Release')
        run('cmake', '--build', tool_build, '--parallel', str(args.jobs))
        env = dict(os.environ)
        env['PATH'] = str(tool_build) + os.pathsep + env.get('PATH', '')
        run('./unixnu', 'ipsw', 'fetch', '--device',
            ROOT / 'sources' / lock['reference_device'], '--os', lock['os_profile'], cwd=unixnu, env=env)
    check_sources(lock)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f'fetch-sources: {error}', file=sys.stderr)
        sys.exit(1)
