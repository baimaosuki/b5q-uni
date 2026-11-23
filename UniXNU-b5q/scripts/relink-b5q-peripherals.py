#!/usr/bin/env python3
"""Relink a completed native cache with the selected release's board objects.

The v26 recipe uses v25 inputs and compiles four sources. The v27 recipe uses
v26 inputs and retains GeniI2c. Use --prepare-only to inspect inputs locally.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

CORE_SHA256 = '88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b'
XNU_OBJECT = 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
CORE_ARCHIVE = XNU_OBJECT + '/mach.development.bcm2837.link/mach.development.bcm2837.a'
NATIVE = XNU_OBJECT + '/mach.development.bcm2837.unstripped.noctf'
DISPLAY = 'build/native-legacy-display/libNativeLegacyDisplay.late.a'
USB = 'build/qcom-dwc3/libQcomDwc3.a'
STORAGE = 'build/ram-block/libRamBlock.a'
# build-xnu-4k-baseline.sh + the resolved b5q defconfig. The repeated RAM
# force_load in EXTRA_LD_ARCHIVES contributes the same members only once.
LINK_INPUTS = [
    CORE_ARCHIVE,
    'build/firehose/sym/Release-iphoneos/liblibfirehose_kernel.a',
    'build/corecrypto-2023/libcorecrypto_kernel_noasm-namespaced.a',
    'build/armdt-platform/libArmDTPlatform.a',
    'build/armcpu/libArmCpu.a',
    'build/adreno740/libAdreno740.a',
    DISPLAY,
    'build/ram-block/libRamBlock.a',
    'build/libpthread-kernel/libpthread_kernel.a',
    'build/software-aes/libSoftwareAES.a',
]
# The v24 GOP recipe embeds these USB members in DISPLAY as well as USB.
# Update both archives, but force_load only DISPLAY to avoid duplicate symbols.
REPLACEMENTS = {
    'QcomDwc3.cpp': ('QcomDwc3.late.o', (USB, DISPLAY)),
    'B5qTouch.cpp': ('B5qTouch.o', (DISPLAY,)),
    'B5qUsbBoard.cpp': ('B5qUsbBoard.o', (DISPLAY,)),
    'GeniI2c.c': ('GeniI2c.o', (DISPLAY,)),
    'NativeHidInput.cpp': ('NativeHidInput.late.o', (DISPLAY,)),
    'HidInputProbe.cpp': ('HidInputProbe.o', (DISPLAY,)),
    'B5qBootPolicy.c': ('B5qBootPolicy.o', (DISPLAY,)),
    'B5qProcTop.c': ('B5qProcTop.o', (DISPLAY,)),
    'B5qRamStorage.cpp': ('B5qRamStorage.o', (STORAGE,)),
    'B5qPower.cpp': ('B5qPower.o', (STORAGE,)),
    'B5qUfs/B5qUfs.cpp': ('B5qUfs.late.o', (STORAGE,)),
}
RECIPES = {
    'userdata': (45108577992, 'e66beea40e2a887e177c762804206d21ba983ef2',
                 ('B5qRamStorage.cpp','B5qUfs/B5qUfs.cpp')),
    'v26': (44930613230, '697902ef16648c0aeacbc2b1e7efe9ee19def41e', ('QcomDwc3.cpp', 'B5qTouch.cpp', 'B5qUsbBoard.cpp', 'GeniI2c.c')),
    'v27': (44937931538, '85a328d1956a7216892569a034decf049f889d16',
            ('QcomDwc3.cpp', 'B5qTouch.cpp', 'B5qUsbBoard.cpp')),
    'v29': (44980608285, '0fdff5f7cbb3af37dbee56119c482c766083b7d9',
            ('B5qTouch.cpp', 'NativeHidInput.cpp', 'HidInputProbe.cpp')),
    'v31': (44985774704, 'e94593ae5aa7e6111a20a0515dcef33c0cc316cc',
            ('B5qUsbBoard.cpp', 'NativeHidInput.cpp', 'B5qBootPolicy.c')),
    'v32': (45010859513, '3044fe6e9bceadc0c3d5bbc63f4cd63d64535731',
            ('B5qUsbBoard.cpp', 'B5qBootPolicy.c')),
    'v33': (45016691051, '2f74ab3b3850711cd4f2bc61c75bdbe187a1f586',
            ('B5qBootPolicy.c', 'B5qProcTop.c')),
    'batch2': (45047962341, '5d7c4eadaa5344e1b96edc593b26d6d18d2bc6d0',
               ('NativeHidInput.cpp','HidInputProbe.cpp','B5qProcTop.c',
                'B5qRamStorage.cpp','B5qPower.cpp','B5qUfs/B5qUfs.cpp')),
}


def object_path(out, source):
    # Match the full build's board-input ownership, keeping QcomDwc3 separate.
    directory = out if source == 'QcomDwc3.cpp' else out / 'board-input'
    return directory / (Path(source).stem + '.o')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run(args, **kwargs):
    print('+ ' + shlex.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def members(path):
    """Read the Mach-O members of an actual BSD/Darwin ar archive portably."""
    data = path.read_bytes()
    if data[:8] != b'!<arch>\n':
        raise ValueError(f'Not an ar archive: {path}')
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:] != b'`\n':
            raise ValueError(f'Truncated ar header in {path} at {offset}')
        size = int(header[48:58])
        body = data[offset + 60:offset + 60 + size]
        if len(body) != size:
            raise ValueError(f'Truncated ar member in {path} at {offset}')
        name = header[:16].strip().decode()
        offset += 60 + size + size % 2
        if name.startswith('#1/'):
            length = int(name[3:])
            name, body = body[:length].rstrip(b'\0').decode(), body[length:]
        else:
            name = name.rstrip('/')
        if body[:4] == b'\xcf\xfa\xed\xfe':
            yield name, body


def linker_flags(xnu):
    source = (xnu / 'makedefs/MakeInc.def').read_text()
    substitutions = {'ARM64_PLKSEG_ADDR': '0xfffffff004004000',
                     'ARM64_LINK_ADDR': '0xfffffff007004000'}

    def group(name):
        match = re.search(r'^' + name + r'\s*=\s*\\\n((?:[^\n]*\\\n)*[^\n]*)', source, re.M)
        if not match:
            raise RuntimeError('Missing XNU linker flag group ' + name)
        text = match[1].replace('\\\n', ' ')
        for key, value in substitutions.items():
            text = text.replace('$(' + key + ')', value)
        if '$(' in text:
            raise RuntimeError('Unresolved XNU linker flags: ' + name)
        return shlex.split(text)

    substitutions['LDFLAGS_KERNEL_SEGARM64_SEG_ORDER'] = ''.join(group('LDFLAGS_KERNEL_SEGARM64_SEG_ORDER'))
    return sum((group(name) for name in ['LDFLAGS_KERNEL_GEN', 'LDFLAGS_KERNEL_GENARM64',
                                       'LDFLAGS_KERNEL_SEGARM64']), [])


def dependency(core, name, required):
    candidates = [path for path in (core / 'out/feeds').glob(name + '-*') if (path / required).is_file()]
    if len(candidates) != 1:
        raise RuntimeError(f'Expected one pinned {name} checkout; run unixnu fetch xnu IOHIDFamily')
    return candidates[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['unixnu', 'device', 'cached-tree', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--reference-image', type=Path, help='Preparation only: native or fileset reference')
    parser.add_argument('--reused-data', type=Path, help='Existing staged data.dbr and paired addon/trust metadata')
    parser.add_argument('--version', choices=RECIPES, default='v26')
    parser.add_argument('--changed', help='Comma-separated sources matching the selected recipe')
    parser.add_argument('--source-run', type=int)
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    default_run, default_commit, selected = RECIPES[args.version]
    if args.changed is not None:
        requested = args.changed.split(',')
        if len(requested) != len(selected) or set(requested) != set(selected):
            parser.error(f'--changed for {args.version} must select ' + ','.join(selected))
    replacements = {name: REPLACEMENTS[name] for name in selected}
    source_run = args.source_run if args.source_run is not None else default_run
    source_commit = args.source_commit if args.source_commit is not None else default_commit
    if args.reference_image and not args.prepare_only:
        parser.error('--reference-image is only available with --prepare-only')
    core, device, cached, out = map(Path.resolve, [args.unixnu, args.device, args.cached_tree, args.out])
    out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(device / 'scripts'), str(core / 'scripts'), str(core / 'kits/XnuPrelink')]
    from b5q_abi import object_symbols
    from kc_image import Image

    xnu = dependency(core, 'xnu', 'makedefs/MakeInc.def')
    hid = dependency(core, 'IOHIDFamily', 'IOHIDFamily/IOHIDDevice.h')
    native = args.reference_image.resolve() if args.reference_image else cached / NATIVE
    original = Image(native.read_bytes())
    if original.kind == 12:
        original = Image(original.data, original.entries['com.apple.kernel'][1])
    originals = {name: va for va, names in original.symbols().items() for name in names}
    defined = set()
    archive_members = {}
    for relative in [*LINK_INPUTS, USB]:
        objects = list(members(cached / relative))
        archive_members[relative] = {name: hashlib.sha256(body).hexdigest() for name, body in objects}
        if relative in LINK_INPUTS:
            for _, body in objects:
                defined.update(name for name, value, kind in object_symbols(body)
                               if kind & 1 and (kind & 0xe or value))
    aliases = {}
    for exports in sorted((xnu / 'config').glob('*.exports')):
        for line in exports.read_text().splitlines():
            match = re.fullmatch(r'\s*([^#\s:]+)\s*:\s*([^#\s:]+)\s*(?:#.*)?', line)
            if match:
                name, target = match.groups()
                if name in originals and target in originals and target in defined and originals[name] == originals[target]:
                    aliases[name] = target
    alias = out / 'all-alias.exp'
    alias.write_text(''.join(f'{target} {name}\n' for name, target in sorted(aliases.items())))
    section = next(s for s in original.sections if s['segment'] == '__LINKINFO' and s['name'] == '__symbolsets')
    symbolsets = out / 'symbolsets.plist'
    symbolsets.write_bytes(original.read(section['va'], section['size']))
    # Keep every binder, including HID/PMGR/storage/AES/network and USB. Copies
    # come from their owning archive, not from a potentially stale loose object.
    binders = {}
    for relative in [*LINK_INPUTS[3:], USB]:
        for name, body in members(cached / relative):
            if 'bindings' in name or 'addresses' in name:
                target = out / 'retained' / Path(relative).parent / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
                binders[str(target.relative_to(out))] = hashlib.sha256(body).hexdigest()
    retained = ['CpuFreqProbe.o']
    if 'QcomDwc3.cpp' not in replacements:
        retained.append('QcomDwc3.late.o')
    if 'GeniI2c.c' not in replacements:
        retained.append('GeniI2c.o')
    record = dict(relink_version=args.version, source_run=source_run, source_commit=source_commit,
                  expected_core_sha256=CORE_SHA256,
                  input_archives={rel: sha(cached / rel) for rel in [*LINK_INPUTS, USB]},
                  input_archive_members=archive_members, retained_binders=binders,
                  native_reference_sha256=sha(native), reference_fileset=original.at != 0,
                  changed_board_sources=list(replacements),
                  compiled_object_paths={name: str(object_path(out, name).relative_to(out))
                                         for name in replacements},
                  retained_board_objects={DISPLAY: {member: archive_members[DISPLAY][member]
                                                    for member in retained}},
                  source_sha256={str(p.relative_to(device / 'package')): sha(p) for p in sorted((device / 'package').rglob('*'))
                                 if p.is_file() and p.suffix in ('.cpp', '.c', '.h')},
                  recipe_sha256={name: sha(device / 'scripts' / name) for name in
                                 ['b5q_peripherals.py', 'build-b5q-usb.py', 'relink-b5q-peripherals.py']},
                  dependency_commits={name: subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
                                      for name, path in [('xnu', xnu), ('IOHIDFamily', hid), ('XnuPrelink', core / 'kits/XnuPrelink')]},
                  core_translation_units_compiled=0, board_translation_units_compiled=0,
                  gpu_recompiled=False, data_regenerated=False, binder_objects_compiled=0,
                  aliases_from_source_native=aliases, linkflags=linker_flags(xnu),
                  usb_archive_embedded_in=DISPLAY, hardware_tested=False)
    record['optional_cpu_idle_helper_present'] = '_sheng_cpu_idle_mach' in defined
    if args.reused_data:
        runtime = args.reused_data.resolve().parent
        record['reused_runtime_sha256'] = {name: sha(runtime / name) for name in
                                          ['data.dbr', 'data-seed.json', 'gpu-addon.bin', 'owner-trust.bundle']}
    # Source inputs are records for local pre-CI / returned-byte auditing; no new
    # integrity acceptance step is inserted into the upstream CI build.
    for member, archives in replacements.values():
        for relative in archives:
            if member not in archive_members[relative] and member not in ('B5qBootPolicy.o', 'B5qProcTop.o','B5qPower.o'):
                raise RuntimeError(f'{relative} has no cached replacement member {member}')
    (out / 'incremental-inputs.json').write_text(json.dumps(record, indent=2) + '\n')
    if args.prepare_only:
        print(f'Prepared {args.version} relink from run {source_run}: {", ".join(replacements)}')
        return
    if sys.platform != 'darwin':
        raise SystemExit('Build requires Xcode; use --prepare-only on other hosts')
    from unixnu.cli import parser as unixnu_parser
    from unixnu.config import Context
    from unixnu import kernel
    from b5q_peripherals import prepare_headers, flags, compile_object
    ctx = Context(unixnu_parser().parse_args(['build', 'payload', '--device', str(device), '--os', 'macos-27.3-26C5035r']))
    for relative in [*LINK_INPUTS, USB]:
        target = ctx.tree / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cached / relative, target)
    llvm = Path(subprocess.check_output(['brew', '--prefix', 'llvm'], text=True).strip()) / 'bin'
    cxx = subprocess.check_output(['xcrun', '--find', 'clang++'], text=True).strip()
    sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    include = out / 'include'
    header = prepare_headers(sdk, include, hid)
    if args.version in ('batch2','userdata'):
        storage=dependency(core,'IOStorageFamily','IOBlockStorageDevice.h')
        dest=include/'IOKit/storage';dest.mkdir(parents=True,exist_ok=True)
        for path in storage.glob('*.h'):shutil.copyfile(path,dest/path.name)
        (include/'macos-target.h').write_text('#include <TargetConditionals.h>\n#undef TARGET_OS_OSX\n#define TARGET_OS_OSX 1\n')
    spec = importlib.util.spec_from_file_location('usb_builder', device / 'scripts/build-b5q-usb.py')
    usb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usb)
    for kind, generate in [('xhci', usb.header), ('xdci', usb.xdci_header)]:
        (include / ('OriginalUsb' + kind.capitalize() + 'ABI.h')).write_text(generate(
            json.loads((device / f'scripts/usb-{kind}-26C5035r.json').read_text())))
    cflags = flags(sdk, include, header, device / 'package', ctx.tree, xnu,
                   '_sheng_cpu_idle_mach' in defined)
    returned = ctx.work / 'kernel/incremental-objects'
    returned.mkdir(parents=True, exist_ok=True)
    objects = {}
    object_metadata = {}
    for name, (_, archives) in replacements.items():
        compiled = object_path(out, name)
        compiled.parent.mkdir(parents=True, exist_ok=True)
        # compile_object selects C/gnu11/-mkernel and removes C++ codegen flags
        # for GeniI2c.c. Do not pass C++-only diagnostic options to that recipe.
        options = [flag for flag in cflags if not name.endswith('.c') or flag not in
                   ('-Wno-unused-private-field', '-Wno-c++11-narrowing',
                    '-Wno-deprecated-enum-enum-conversion')]
        if name in ('B5qRamStorage.cpp','B5qUfs/B5qUfs.cpp','B5qPower.cpp'):
            options+=['-include',str(include/'macos-target.h'),'-I',str(xnu/'osfmk'),
                      '-I',str(ctx.tree/'kits/VerifiedRoot/include')]
        obj = compile_object(cxx, options, device / 'package' / name, compiled, llvm)
        objects[obj.name] = sha(obj)
        # Return exactly one object per source, containing the bytes inserted
        # into the archives. QcomDwc3's late transform is recorded explicitly.
        canonical = Path(name).stem + '.o'
        shutil.copyfile(obj, returned / canonical)
        shutil.copyfile(compiled.with_suffix('.command.json'),
                        returned / (Path(name).stem + '.command.json'))
        object_metadata[canonical] = dict(source=name, sha256=sha(obj), archive_member=obj.name,
                                         archives=list(archives),
                                         compiled_object=str(compiled.relative_to(out)),
                                         compiled_sha256=sha(compiled),
                                         late_transform=obj.name != canonical)
        for relative in archives:
            run(['xcrun', 'ar', 'r', ctx.tree / relative, obj])
        record['board_translation_units_compiled'] += 1
    (returned / 'objects.json').write_text(json.dumps(object_metadata, indent=2) + '\n')
    record['returned_objects'] = object_metadata
    target = ctx.work / 'kernel/incremental-relink.json'
    target.write_text(json.dumps(record, indent=2) + '\n')
    native_out = ctx.tree / NATIVE
    native_out.parent.mkdir(parents=True, exist_ok=True)
    command = ['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', 'arm64e-apple-ios27.0',
               *record['linkflags'], '-Wl,-add_split_seg_info', '-Wl,-kernel',
               '-Wl,-alias_list,' + str(alias), '-Wl,-sectcreate,__LINKINFO,__symbolsets,' + str(symbolsets),
               '-Wl,-segprot,__LINKINFO,r--,r--', '-Wl,-force_load,' + str(ctx.tree / LINK_INPUTS[0]),
               '-lcc_kext', str(ctx.tree / LINK_INPUTS[1]), str(ctx.tree / LINK_INPUTS[2])]
    command += ['-Wl,-force_load,' + str(ctx.tree / relative) for relative in LINK_INPUTS[3:]]
    command += ['-o', str(native_out)]
    (out / 'link-command.json').write_text(json.dumps(command, indent=2) + '\n')
    run(command)
    os.environ.update(UNIXNU_XNU_ARCH='arm64e', UNIXNU_IOS_VERSION='27.0', UNIXNU_XNU_TARGET='macosx')
    run([sys.executable, ctx.tree / 'scripts/seal-source-crypto-kernel.py', native_out])
    record.update(added_objects=objects,
                  compiled_objects={Path(name).stem + '.o': sha(object_path(out, name))
                                    for name in replacements},
                  unchanged_core_after_link_sha256=sha(ctx.tree / CORE_ARCHIVE),
                  native_output_sha256=sha(native_out),
                  archive_outputs={rel: sha(ctx.tree / rel) for rel in [*LINK_INPUTS, USB]})
    record['output_archive_members'] = {rel: {name: hashlib.sha256(body).hexdigest()
                                             for name, body in members(ctx.tree / rel)} for rel in [DISPLAY, USB, STORAGE]}
    # Save the completed native link before prelink/payload, including on failure.
    for path in [target, out / 'incremental-inputs.json']:
        path.write_text(json.dumps(record, indent=2) + '\n')
    reuse_path = ctx.work / 'kernel-reuse.json'
    reuse = json.loads(reuse_path.read_text()) if reuse_path.is_file() else {}
    reuse.update(source_run=source_run, source_commit=source_commit,
                 kernel_recompiled=False, kernel_core_recompiled=False, kernel_relinked=True,
                 source_payload_reused=False, board_objects_recompiled=len(replacements),
                 incremental_record='kernel/incremental-relink.json')
    reuse_path.write_text(json.dumps(reuse, indent=2) + '\n')
    kernel.prelink(ctx)


if __name__ == '__main__':
    main()
