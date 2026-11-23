#!/usr/bin/env python3
"""Extract original ADSP pieces and reconstruct their signed ELF containers offline."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def rebuild(directory, name):
    header = (directory / (name + '.b00')).read_bytes()
    if header[:6] != b'\x7fELF\x01\x01' or len(header) < 52:
        raise ValueError('Expected original little-endian ELF32 header: ' + name)
    offset = struct.unpack_from('<I', header, 28)[0]
    stride, count = struct.unpack_from('<HH', header, 42)
    end = offset + stride * count
    if stride != 32 or not 1 <= count <= 256 or offset < 52 or end > len(header):
        raise ValueError('Invalid original program table: ' + name)
    segments = [struct.unpack_from('<8I', header, offset + i * stride) for i in range(count)]
    total = max(at + size for _, at, _, _, size, _, _, _ in segments)
    if total < len(header) or total > 256 << 20:
        raise ValueError('Unbounded original firmware size: ' + name)
    body = bytearray(total)
    body[:len(header)] = header
    hashes = bytearray()
    ranges = []
    inputs = {}
    for i, (_, at, _, _, size, _, flags, _) in enumerate(segments):
        if not size:
            continue
        piece = directory / (name + f'.b{i:02d}')
        data = piece.read_bytes()
        if len(data) != size or at > total - size:
            raise ValueError('Original segment size mismatch: ' + piece.name)
        if any(at < hi and lo < at + size for lo, hi in ranges):
            raise ValueError('Overlapping original segments: ' + piece.name)
        ranges.append((at, at + size))
        body[at:at + size] = data
        inputs[piece.name] = dict(bytes=size, sha256=digest(piece), elf_offset=at)
        if (flags >> 24) & 7 == 2:
            hashes.extend(data)
    metadata = directory / (name + '.mdt')
    if metadata.read_bytes() != header[:end] + hashes:
        raise ValueError('Original MDT differs from header plus signed hash segment: ' + name)
    target = directory / (name + '.mbn')
    target.write_bytes(body)
    return dict(bytes=total, sha256=digest(target), segment_count=count,
                derivation='Exact original ELF offsets and unchanged split segments; MDT header/hash identity verified',
                metadata_sha256=digest(metadata), inputs=inputs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--non-hlos', type=Path, required=True, help='Offline original firmware image, never a block device')
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if not a.non_hlos.is_file() or a.non_hlos.is_block_device():
        raise ValueError('Only an existing offline regular image is accepted')
    a.out.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(['mdir', '-b', '-i', str(a.non_hlos), '::/image/adsp*'], text=True).splitlines()
    selected = []
    for path in names:
        leaf = path.rsplit('/', 1)[-1]
        base, _, suffix = leaf.partition('.')
        if base not in ('adsp', 'adsp_dtb') or not (suffix == 'mdt' or (len(suffix) == 3 and suffix[0] == 'b' and suffix[1:].isdigit())):
            continue
        subprocess.run(['mcopy', '-o', '-i', str(a.non_hlos), path, str(a.out / leaf)], check=True)
        selected.append(leaf)
    result = dict(source='Offline original Samsung NON-HLOS FAT; no phone/partition access',
                  parent=str(a.non_hlos.resolve()), parent_sha256=digest(a.non_hlos),
                  extracted_files=sorted(selected),
                  containers={name: rebuild(a.out, name) for name in ('adsp', 'adsp_dtb')},
                  hardware_verified=False, firmware_signature_execution_verified=False)
    (a.out / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
    print('PASS original ADSP/DTB split bounds, MDT hash segments and reconstructed ELF containers')


if __name__ == '__main__':
    main()
