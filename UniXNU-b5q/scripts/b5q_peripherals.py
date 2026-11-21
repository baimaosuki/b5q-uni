"""Shared board-object recipe for full builds and cached-core relinks.

Only board objects are compiled. HID/XHCI original addresses are reviewed
inputs, checked locally against actual objects and again after download.
"""
import json
import shutil
import subprocess
from pathlib import Path

SOURCES = ['B5qSpmi.cpp', 'CpuFreqProbe.cpp', 'ThermalProbe.cpp',
           'ThermalLevel.cpp', 'BoardClock.cpp', 'ButtonProbe.cpp',
           'DisplayTimingProbe.cpp', 'NativeHidInput.cpp', 'HidInputProbe.cpp',
           'B5qTouch.cpp', 'GeniI2c.c']


def prepare_headers(sdk, include, hid):
    header = sdk / 'System/Library/Frameworks/Kernel.framework/Headers'
    (include / 'libkern/c++').mkdir(parents=True, exist_ok=True)
    text = (header / 'libkern/c++/OSMetaClass.h').read_text()
    text = text.replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR', '#if !XNU_TARGET_OS_OSX')
    text = text.replace('#if TARGET_OS_OSX && defined(__arm64__)', '#if XNU_TARGET_OS_OSX && defined(__arm64__)')
    (include / 'libkern/c++/OSMetaClass.h').write_text(text)
    for source, relative in [(hid / 'IOHIDFamily', 'IOKit/hid'),
                             (hid / 'IOHIDSystem/IOKit/hidsystem', 'IOKit/hidsystem')]:
        target = include / relative
        target.mkdir(parents=True, exist_ok=True)
        for path in source.glob('*.h'):
            shutil.copyfile(path, target / path.name)
    parser = include / 'IOKit/hidsystem/IOHIDDescriptorParser.h'
    parser.write_text(parser.read_text().replace('#if __has_include(<MacTypes.h>)',
                      '#if __has_include(<MacTypes.h>) && !defined(KERNEL)'))
    return header


def flags(sdk, include, header, package, tree, xnu, have_idle=False):
    result = ['-target', 'arm64e-apple-ios27.0', '-isysroot', str(sdk), '-O2',
              '-fptrauth-calls', '-fptrauth-returns', '-fptrauth-intrinsics',
              '-fptrauth-function-pointer-type-discrimination',
              '-std=gnu++17', '-fno-c++-static-destructors', '-fno-exceptions',
              '-fno-rtti', '-fno-common', '-fapple-kext', '-ffreestanding',
              '-mgeneral-regs-only', '-nostdinc++', '-D__PTRAUTH_INTRINSICS__=1',
              '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter',
              '-Wno-incompatible-sysroot', '-Wno-deprecated-declarations',
              '-Wno-unknown-warning-option', '-Wno-unused-private-field',
              '-Wno-c++11-narrowing', '-Wno-deprecated-enum-enum-conversion',
              '-DB5Q_HAVE_CPU_IDLE_MACH=' + str(int(have_idle))]
    result += ['-D' + key + '=1' for key in ['KERNEL', 'KERNEL_PRIVATE', 'DRIVER_PRIVATE',
               'XNU_KERNEL_PRIVATE', 'XNU_TARGET_OS_OSX', 'PRIVATE', 'MACH_KERNEL_PRIVATE',
               '__arm64__', '__LP64__', '__DARWIN_UNIX03']]
    for path in [include, package, header, xnu / 'pexpert', tree / 'drivers/Adreno740',
                 tree / 'kits/AdrenoFirmware', package / 'B5qUfs', package / 'Sm8550Inputs',
                 tree / 'kits/Sm8550Platform', tree / 'kits/ArmSmmu4K',
                 tree / 'kits/AdrenoPM4', xnu / 'libkern', xnu / 'EXTERNAL_HEADERS']:
        result += ['-I', str(path)]
    return result


def compile_object(cxx, cflags, source, target, llvm):
    options = list(cflags)
    if source.suffix == '.c':
        options = [v for v in options if v not in ['-std=gnu++17', '-fno-c++-static-destructors',
                   '-fno-exceptions', '-fno-rtti', '-fapple-kext', '-nostdinc++']]
        options += ['-x', 'c', '-std=gnu11', '-mkernel', '-fptrauth-function-pointer-type-discrimination']
    if source.name == 'NativeHidInput.cpp':
        options += ['-DNATIVE_HID_SOURCE_API=1']
    command = [str(cxx), *options, '-c', str(source), '-o', str(target)]
    target.with_suffix('.command.json').write_text(json.dumps(command, indent=2) + '\n')
    subprocess.run(command, check=True)
    if source.name in ['NativeHidInput.cpp', 'ThermalLevel.cpp', 'B5qUsbHost.cpp']:
        late = target.with_suffix('.late.o')
        subprocess.run([str(llvm / 'llvm-objcopy'), '--remove-section=__DATA,__mod_init_func',
                       '--globalize-symbol=__GLOBAL__sub_I_' + source.name, str(target), str(late)], check=True)
        return late
    return target


def build_added(package, out, cxx, cflags, llvm, scripts, selected=None):
    from b5q_hid import assembly
    out.mkdir(parents=True, exist_ok=True)
    sources = SOURCES if selected is None else [n for n in SOURCES if n in selected]
    objects = [compile_object(cxx, cflags, package / name, out / (Path(name).stem + '.o'), llvm)
               for name in sources]
    if selected is not None and 'NativeHidInput.cpp' not in selected:
        return objects
    bound = json.loads((scripts / 'hid-bindings-26C5035r.json').read_text())['bindings']
    text, addresses = assembly({n: int(v, 16) for n, v in bound.items()})
    for name, body in [('hid-bindings', text), ('hid-addresses', addresses)]:
        source = out / (name + '.S')
        source.write_text(body)
        target = source.with_suffix('.o')
        subprocess.run([str(cxx), '-target', 'arm64e-apple-ios27.0', '-c', str(source), '-o', str(target)], check=True)
        objects.append(target)
    return objects


def full_build(tree, package, out, scripts):
    """The same SDK-based module recipe from the normal Format 2 builder."""
    cxx = subprocess.check_output(['xcrun', '--find', 'clang++'], text=True).strip()
    sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    llvm = Path(subprocess.check_output(['brew', '--prefix', 'llvm'], text=True).strip()) / 'bin'
    include = out / 'board-include'
    hid = tree / 'refer/IOHIDFamily'
    header = prepare_headers(sdk, include, hid)
    cflags = flags(sdk, include, header, package, tree, tree / '.cache/xnu-work')
    return build_added(package, out / 'board-input', cxx, cflags, llvm, scripts)
