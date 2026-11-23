#!/usr/bin/env python3
"""Install the hash-locked upstream ipsw CLI without Homebrew's cask resolver."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import struct
import tarfile
import tempfile
import urllib.request

VERSION='3.1.750'
ARCHIVES={
    'x86_64':('0c75b8130657cf3098f837e4f93caa87206e4efd74868ba98003463ea78f09cf',0x01000007),
    'arm64':('03c0701b136a9ea49318cbd8ddd7357ed9d7a2041d7b3ce93969bd2b2505aeb0',0x0100000c),
}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--arch',choices=ARCHIVES,default=platform.machine())
    p.add_argument('--verify-only',action='store_true',help='Inspect original macOS executable on a non-macOS verification host')
    a=p.parse_args()
    if not a.verify_only and platform.system()!='Darwin':raise ValueError('macOS host required for installation')
    expected,cpu=ARCHIVES[a.arch]
    url=f'https://github.com/blacktop/ipsw/releases/download/v{VERSION}/ipsw_{VERSION}_macOS_{a.arch}_extras.tar.gz'
    a.out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='b5q-ci-ipsw-')as td:
        archive=Path(td)/'ipsw.tar.gz'
        with urllib.request.urlopen(url,timeout=90)as response,archive.open('wb')as output:
            size=0
            while block:=response.read(1024*1024):
                size+=len(block)
                if size>512<<20:raise ValueError('Unexpected CLI archive size')
                output.write(block)
        with archive.open('rb')as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=expected:raise ValueError('Original ipsw release archive SHA256 mismatch')
        with tarfile.open(archive)as source:
            member=source.getmember('ipsw')
            if not member.isfile() or not 4096<=member.size<=512<<20:raise ValueError('Unexpected original ipsw executable')
            executable=source.extractfile(member).read()
        if struct.unpack_from('<II',executable)!=(0xfeedfacf,cpu):raise ValueError('Original CLI architecture mismatch')
        if not a.verify_only:
            path=a.out/'ipsw';path.write_bytes(executable);path.chmod(0o755)
        receipt=dict(version=VERSION,arch=a.arch,url=url,archive_sha256=digest,
            executable_sha256=hashlib.sha256(executable).hexdigest(),bytes=len(executable),verified_only=a.verify_only)
        (a.out/'ipsw-input.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('PASS hash-locked upstream ipsw CLI',VERSION,a.arch)


if __name__=='__main__':main()
