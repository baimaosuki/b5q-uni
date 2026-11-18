#!/usr/bin/env python3
"""Build the b5q UniXNU firmware/menu using the pinned upstream build helpers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tomllib
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def command(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def sha(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def patch_source(repo, patch):
    check = subprocess.run(['git', '-C', str(repo), 'apply', '--reverse', '--check', str(patch)], capture_output=True)
    if check.returncode:
        command('git', '-C', repo, 'apply', '--check', patch)
        command('git', '-C', repo, 'apply', patch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jobs', type=int, default=min(os.cpu_count() or 2, 12))
    parser.add_argument('--clang-bin', default='/usr/lib/llvm-17/bin')
    parser.add_argument('--target', choices=['DEBUG', 'RELEASE'], default='DEBUG')
    parser.add_argument('--firmware-only', action='store_true')
    parser.add_argument('--package-only', action='store_true')
    args = parser.parse_args()
    if args.firmware_only and args.package_only:
        parser.error('choose at most one partial build mode')
    tree = ROOT / 'sources/UniXNU'
    uefi = ROOT / 'sources/Mu-Silicium'
    edk2 = uefi / 'Mu_Basecore'
    out = ROOT / 'artifacts/unixnu-b5q'
    work = ROOT / 'artifacts/unixnu-work'
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(tree / 'scripts'))
    from unixnu import firmware, bootimg
    config_path = ROOT / 'configs/unixnu-b5q.toml'
    board = tomllib.loads(config_path.read_text())
    os.environ['PATH'] = args.clang_bin + os.pathsep + os.environ['PATH']
    ctx = SimpleNamespace(tree=tree, board=board, work=work, logs=ROOT / 'logs/unixnu', jobs=args.jobs,
                          args=SimpleNamespace(skip_preflight=True))
    ctx.option = lambda name, env: args.clang_bin if name == 'clang_bin' else None
    for patch in sorted((ROOT / 'patches/mu-silicium').glob('*.patch')):
        patch_source(uefi, patch)
    firmware.preflight_toolchain(ctx)
    if not args.package_only:
        firmware.build(ctx, [], uefi, edk2, args.target)
    fd = firmware.fd_path(ctx, uefi, args.target)
    shutil.copyfile(fd, out / 'SILICIUM_UEFI.fd')
    binary_dir = uefi / f'Build/b5qPkg/{args.target}_CLANGPDB/AARCH64'
    modules = ['UniXNU', 'UniXNUDxe', 'UniXNURamDiskDxe', 'DarwinBoot', 'HelloPayload']
    for name in modules:
        shutil.copyfile(binary_dir / f'{name}.efi', out / f'{name}.efi')
    qemu_record = out / 'qemu-report.json'
    previous = json.loads(qemu_record.read_text()).get('efi_sha256', {}) if qemu_record.exists() else {}
    if not previous or any(previous.get(name) != sha(out / f'{name}.efi') for name in ['UniXNU', 'HelloPayload']):
        for name in ['qemu-report.json', 'menu-qemu.log', 'payload-qemu.log', 'menu-qemu.png', 'menu-preview.png']:
            (out / name).unlink(missing_ok=True)
    if args.firmware_only:
        return
    stage = out / 'esp'
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(ROOT / 'esp', stage)
    for source, dest in [('UniXNU', 'EFI/BOOT/BOOTAA64.EFI'),
                         ('DarwinBoot', 'EFI/UniXNU/Drivers/DarwinBoot.efi'),
                         ('HelloPayload', 'EFI/UniXNU/Payloads/HelloPayload.efi')]:
        target = stage / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / f'{source}.efi', target)
    payload = out / 'menu-payload.fat'
    payload.unlink(missing_ok=True)
    env = dict(os.environ, MTOOLS_SKIP_CHECK='1', TZ='UTC')
    command('mformat', '-C', '-T', '32768', '-v', 'B5QUNIXNU', '-N', '42355155', '-i', payload, '::', env=env)
    command('mcopy', '-i', payload, '-s', '-m', stage / 'EFI', '::/', env=env)
    command('fsck.fat', '-n', payload)
    # Use the board's original Qualcomm/Samsung firmware DT, not an Apple DT.
    dtb = out / 'b5q.dtb'
    command('dtc', '-q', '-I', 'dts', '-O', 'dtb', '-o', dtb, uefi / 'Resources/DTBs/b5q.dts')
    bootimg.build(ctx, uefi, out / 'SILICIUM_UEFI.fd', dtb, payload, out / 'boot.img')
    with tarfile.open(out / 'unixnu-b5q-odin.tar', 'w', format=tarfile.USTAR_FORMAT) as tar:
        info = tar.gettarinfo(out / 'boot.img', arcname='boot.img')
        info.uid = info.gid = info.mtime = 0
        info.uname = info.gname = ''
        with (out / 'boot.img').open('rb') as stream:
            tar.addfile(info, stream)
    with tarfile.open(out / 'unixnu-b5q-esp.tar', 'w', format=tarfile.USTAR_FORMAT) as tar:
        for path in sorted(stage.rglob('*')):
            if path.is_file():
                info = tar.gettarinfo(path, arcname=path.relative_to(stage))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                with path.open('rb') as stream:
                    tar.addfile(info, stream)
    report = {'board': 'b5q', 'target': args.target, 'hardware_tested': False,
              'scope': 'UEFI menu and DarwinBoot loader; no XNU kernel/macOS payload',
              'config_sha256': sha(config_path), 'sources': {}, 'modules': {}, 'files': {}}
    for name, path in [('UniXNU', tree), ('Mu-Silicium', uefi), ('Mu_Basecore', edk2),
                       ('Binaries', uefi / 'Binaries'), ('DarwinBoot', tree / 'drivers/DarwinBoot')]:
        report['sources'][name] = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    for name in modules:
        report['modules'][name] = {'sha256': sha(out / f'{name}.efi'), 'bytes': (out / f'{name}.efi').stat().st_size}
    for name in ['SILICIUM_UEFI.fd', 'boot.img', 'menu-payload.fat', 'b5q.dtb',
                 'unixnu-b5q-odin.tar', 'unixnu-b5q-esp.tar']:
        path = out / name
        report['files'][name] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    report['patches'] = {p.name: sha(p) for p in sorted((ROOT / 'patches/mu-silicium').glob('*.patch'))}
    report['toolchain'] = subprocess.check_output([str(Path(args.clang_bin) / 'clang'), '--version'], text=True).splitlines()[0]
    (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    command(sys.executable, ROOT / 'scripts/verify-unixnu.py', '--out', out)
    files = sorted(p for p in out.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    (out / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in files))
    print(f'Artifacts: {out}')


if __name__ == '__main__':
    main()
