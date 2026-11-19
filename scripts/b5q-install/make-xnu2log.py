#!/usr/bin/env python3
"""Create a blank, format-compatible XNU2LOG.BIN allocation for b5q.

The NABUCFG2/NABULOG2 magic identifies the existing portable journal format.
No partition geometry, LUN, boot argument or device driver is imported.
This creates an immutable config plus two UNCOMMITTED empty slots. It contains
no captured kernel log and does not enable a writer in an existing kernel.
"""
import argparse
import hashlib
from pathlib import Path
import secrets
import struct
import zlib

BLOCK = 4096
CAPACITY = 4 * 1024 * 1024
SLOT_BYTES = BLOCK + CAPACITY
FILE_BYTES = BLOCK + 2 * SLOT_BYTES


def config_block(identity):
    if len(identity) != 16 or not any(identity):
        raise ValueError('Allocation identity must contain 16 bytes and be nonzero')
    data = bytearray(BLOCK)
    struct.pack_into('<8s6I', data, 0, b'NABUCFG2', 2, BLOCK, CAPACITY,
                     SLOT_BYTES, FILE_BYTES, 0)
    data[32:48] = identity
    struct.pack_into('<I', data, 48, BLOCK)
    struct.pack_into('<I', data, 56, zlib.crc32(data) & 0xffffffff)
    return bytes(data)


def verify(path, identity=None):
    if path.stat().st_size != FILE_BYTES:
        raise ValueError('Unexpected journal size')
    with path.open('rb') as stream:
        data = bytearray(stream.read(BLOCK))
        actual = bytes(data[32:48])
        if data[:8] != b'NABUCFG2' or not any(actual):
            raise ValueError('Invalid journal config')
        if identity is not None and actual != identity:
            raise ValueError('Allocation identity mismatch')
        if bytes(data) != config_block(actual):
            raise ValueError('Config layout, reserved fields or CRC mismatch')
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            if any(block):
                raise ValueError('Expected untouched, uncommitted slots')
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--token', help='Explicit 32 hex digit allocation identity')
    args = parser.parse_args()
    identity = bytes.fromhex(args.token) if args.token else secrets.token_bytes(16)
    while not any(identity):
        identity = secrets.token_bytes(16)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('xb') as stream:
        stream.write(config_block(identity))
        stream.truncate(FILE_BYTES)
    verify(args.out, identity)
    with args.out.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    print(f'Created blank journal allocation: {args.out.resolve()}')
    print(f'{FILE_BYTES} bytes, {FILE_BYTES // BLOCK} blocks, SHA256 {digest}')
    print('Both slots are uncommitted; existing b5q kernels require logger integration.')


if __name__ == '__main__':
    main()
