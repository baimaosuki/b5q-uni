#!/usr/bin/env python3
"""Validate and adjust the signed b5q Bluetooth runtime metadata."""
import hashlib
import struct
from pathlib import Path

LC_CODE_SIGNATURE = 0x1D
CSMAGIC_EMBEDDED_SIGNATURE = 0xFADE0CC0
CSMAGIC_CODEDIRECTORY = 0xFADE0C02


def _code_directories(data):
    if len(data) < 32 or struct.unpack_from('<I', data)[0] != 0xFEEDFACF:
        raise ValueError('expected a thin 64-bit Mach-O image')
    commands, at = struct.unpack_from('<I', data, 16)[0], 32
    signature = None
    for _ in range(commands):
        if at + 8 > len(data):
            raise ValueError('truncated Mach-O load commands')
        command, size = struct.unpack_from('<II', data, at)
        if size < 8 or at + size > len(data):
            raise ValueError('invalid Mach-O load command')
        if command == LC_CODE_SIGNATURE:
            if signature is not None or size < 16:
                raise ValueError('invalid LC_CODE_SIGNATURE count')
            signature = struct.unpack_from('<II', data, at + 8)
        at += size
    if signature is None:
        raise ValueError('LC_CODE_SIGNATURE is absent')
    start, size = signature
    if start + size > len(data) or size < 12:
        raise ValueError('invalid embedded signature range')
    magic, length, count = struct.unpack_from('>III', data, start)
    if magic != CSMAGIC_EMBEDDED_SIGNATURE or length > size or 12 + count * 8 > length:
        raise ValueError('invalid embedded signature superblob')
    found = []
    for index in range(count):
        slot, relative = struct.unpack_from('>II', data, start + 12 + index * 8)
        if relative + 8 > length:
            raise ValueError('invalid signature blob offset')
        blob_magic, blob_length = struct.unpack_from('>II', data, start + relative)
        if blob_length < 8 or relative + blob_length > length:
            raise ValueError('invalid signature blob length')
        if blob_magic == CSMAGIC_CODEDIRECTORY:
            if blob_length < 44:
                raise ValueError('short CodeDirectory')
            found.append(dict(slot=slot, offset=start + relative, length=blob_length))
    if not found:
        raise ValueError('CodeDirectory is absent')
    return found


def inspect_code_directories(data, verify_pages=True):
    result = []
    for item in _code_directories(data):
        at, length = item['offset'], item['length']
        cd = data[at:at + length]
        version, flags, hash_offset, _, special, slots, code_limit = struct.unpack_from('>7I', cd, 8)
        hash_size, hash_type, platform, page_shift = cd[36:40]
        if hash_type != 2 or hash_size != 32 or page_shift > 30:
            raise ValueError('b5q requires a SHA-256 CodeDirectory')
        if hash_offset < special * hash_size or hash_offset + slots * hash_size > length:
            raise ValueError('invalid CodeDirectory hash table')
        if verify_pages:
            page = 1 << page_shift
            if code_limit > len(data) or slots != (code_limit + page - 1) // page:
                raise ValueError('invalid CodeDirectory code slot count')
            for index in range(slots):
                body = data[index * page:min((index + 1) * page, code_limit)]
                expected = cd[hash_offset + index * hash_size:hash_offset + (index + 1) * hash_size]
                if hashlib.sha256(body).digest() != expected:
                    raise ValueError(f'CodeDirectory page hash {index} differs')
        result.append(dict(item, version=version, flags=flags, platform=platform,
                           code_limit=code_limit, code_slots=slots,
                           cdhash=hashlib.sha256(cd).digest()[:20].hex(), page_hashes_valid=True))
    return result


def set_platform(path, platform):
    path = Path(path)
    data = bytearray(path.read_bytes())
    before = inspect_code_directories(data)
    for item in before:
        data[item['offset'] + 38] = platform
    after = inspect_code_directories(data)
    if any(item['platform'] != platform for item in after):
        raise ValueError('CodeDirectory platform update failed')
    path.write_bytes(data)
    return dict(platform=platform, before_cdhashes=[item['cdhash'] for item in before],
                cdhashes=[item['cdhash'] for item in after], code_directories=len(after),
                code_pages=sum(item['code_slots'] for item in after), page_hashes_valid=True)


def inspect_trust_entry(data, cdhash):
    wanted = bytes.fromhex(cdhash)
    if len(wanted) != 20 or len(data) < 8:
        raise ValueError('invalid trust bundle or CDHash')
    count = struct.unpack_from('<I', data)[0]
    if not 0 < count <= 128 or len(data) < 4 + count * 4:
        raise ValueError('invalid trust module count')
    starts = list(struct.unpack_from(f'<{count}I', data, 4)) + [len(data)]
    found = []
    for module in range(count):
        start, end = starts[module:module + 2]
        if start < 4 + count * 4 or start & 3 or end > len(data) or end - start < 24:
            raise ValueError('invalid trust module range')
        version, _, entries = struct.unpack_from('<I16sI', data, start)
        stride = {0: 20, 1: 22, 2: 24}.get(version)
        if stride is None or end - start != 24 + entries * stride:
            raise ValueError('invalid trust module layout')
        for entry in range(entries):
            at = start + 24 + entry * stride
            if data[at:at + 20] == wanted:
                if version != 2:
                    raise ValueError('Bluetooth CDHash must use a version-2 trust entry')
                found.append(dict(module=module, entry=entry, offset=at, hash_type=data[at + 20],
                                  flags=data[at + 21], constraint_category=data[at + 22], reserved=data[at + 23]))
    if len(found) != 1:
        raise ValueError(f'expected one trust entry for {cdhash}, found {len(found)}')
    return found[0]


def set_trust_category(source, destination, cdhash, category):
    source, destination = Path(source), Path(destination)
    data = bytearray(source.read_bytes())
    before = inspect_trust_entry(data, cdhash)
    if before['hash_type'] != 2 or before['flags'] != 0 or before['reserved'] != 0:
        raise ValueError('unexpected Bluetooth trust entry metadata')
    data[before['offset'] + 22] = category
    after = inspect_trust_entry(data, cdhash)
    if after['constraint_category'] != category:
        raise ValueError('trust constraint category update failed')
    destination.write_bytes(data)
    return dict(cdhash=cdhash, module=after['module'], entry=after['entry'], hash_type=2,
                flags=0, constraint_category=category, reserved=0,
                input_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                output_sha256=hashlib.sha256(data).hexdigest())
