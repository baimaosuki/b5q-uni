#!/usr/bin/env python3
"""Exercise the exact two emitted FAT disk images with real AArch64 EFI code."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory',type=Path,required=True)
p.add_argument('--logs',type=Path,required=True)
a=p.parse_args();directory=a.directory.resolve();logs=a.logs.resolve();logs.mkdir(parents=True,exist_ok=True)
log=logs/'v2-exact-fat-images.log'
with tempfile.TemporaryDirectory(prefix='b5q-esp-regression-') as temp:
    variables=Path(temp)/'vars.fd';shutil.copyfile('/usr/share/AAVMF/AAVMF_VARS.fd',variables)
    command=['qemu-system-aarch64','-M','virt','-cpu','cortex-a72','-m','1024','-smp','2',
             '-drive','if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd',
             '-drive',f'if=pflash,format=raw,file={variables}',
             '-drive',f'if=none,id=bootstrap,format=raw,readonly=on,file={directory/"bootstrap.fat"}',
             '-device','virtio-blk-pci,drive=bootstrap',
             '-drive',f'if=none,id=macos,format=raw,readonly=on,file={directory/"esp.img"}',
             '-device','virtio-blk-pci,drive=macos','-device','qemu-xhci','-device','usb-kbd',
             '-nic','none','-display','none','-no-reboot','-serial',f'file:{log}']
    proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    expected=['config: loaded \\EFI\\UniXNU\\unixnu.toml','4 entries, 1 drivers','DARWINBOOT: loader v2 installed',
              'driver \\EFI\\UniXNU\\Drivers\\DarwinBoot.efi (config): started',
              'b5q macOS - ESP v2',"boot: entry 'xnu'",'xnu: handing off']
    try:
        deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            text=log.read_text(errors='replace') if log.exists() else ''
            if all(term in text for term in expected):
                time.sleep(1);break
            if proc.poll() is not None:break
            time.sleep(.25)
    finally:
        if proc.poll() is None:proc.terminate()
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
    text=log.read_text(errors='replace')
    for term in expected:assert term in text,term
    for term in ['Hello from the UniXNU test payload','no loader protocol installed','ASSERT']:assert term not in text,term
report={'result':'PASS','scope':'Menu discovery and explicit loader protocol only; NOT Samsung/XNU boot',
        'real_exact_images':{name:{'bytes':(directory/name).stat().st_size,'sha256':hashlib.file_digest((directory/name).open('rb'),'sha256').hexdigest()} for name in ['bootstrap.fat','esp.img']},
        'checks':expected,'hello_executed':False,'missing_loader':False,'qemu_memory_bytes':1073741824,
        'xnu_owned_window_bytes':2147483648,'expected_environment_refusal':'QEMU has1GiB RAM, loader2GiB window cannot be allocated; kernel not executed',
        'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'hardware_verified':False}
(logs/'v2-exact-fat-images.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
