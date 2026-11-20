#!/usr/bin/env python3

"""OS-only Mach-O/arm64e ABI helpers shared with the existing GOP binder."""

import struct

def require(v, why):
    if not v:
        raise SystemExit(why)

def discriminator(name):
    """clang ptrauth_string_discriminator: SipHash-2-4 with the fixed key, modulo 0xffff, plus one."""
    mask = (1 << 64) - 1
    rotl = lambda x, b: ((x << b) | (x >> (64 - b))) & mask  # noqa: E731
    key = bytes([0xb5, 0xd4, 0xc9, 0xeb, 0x79, 0x10, 0x4a, 0x79, 0x6f, 0xec, 0x8b, 0x1b, 0x42, 0x87, 0x81, 0xd4])
    k0, k1 = struct.unpack('<2Q', key)
    v = [0x736f6d6570736575 ^ k0, 0x646f72616e646f6d ^ k1, 0x6c7967656e657261 ^ k0, 0x7465646279746573 ^ k1]

    def rounds(n):
        for _ in range(n):
            v[0] = (v[0] + v[1]) & mask; v[1] = rotl(v[1], 13) ^ v[0]; v[0] = rotl(v[0], 32)
            v[2] = (v[2] + v[3]) & mask; v[3] = rotl(v[3], 16) ^ v[2]
            v[0] = (v[0] + v[3]) & mask; v[3] = rotl(v[3], 21) ^ v[0]
            v[2] = (v[2] + v[1]) & mask; v[1] = rotl(v[1], 17) ^ v[2]; v[2] = rotl(v[2], 32)
    data = name.encode()
    full = len(data) & ~7
    for i in range(0, full, 8):
        m = struct.unpack_from('<Q', data, i)[0]
        v[3] ^= m; rounds(2); v[0] ^= m
    b = len(data) << 56 & mask
    for i, c in enumerate(data[full:]):
        b |= c << (8 * i)
    v[3] ^= b; rounds(2); v[0] ^= b; v[2] ^= 0xff; rounds(4)
    return (v[0] ^ v[1] ^ v[2] ^ v[3]) % 0xffff + 1

def macho(data):
    """Load commands, segments and sections of an arm64e relocatable object."""
    magic, cpu, _, _, count = struct.unpack_from('<5I', data)
    require(magic == 0xfeedfacf and cpu == 0x100000c, 'arm64 Mach-O object')
    commands, segments, offset = [], [], 32
    for _ in range(count):
        command, size = struct.unpack_from('<2I', data, offset)
        commands.append((command, offset, size))
        if command == 0x19:
            nsects = struct.unpack_from('<I', data, offset + 64)[0]
            sections = []
            for i in range(nsects):
                at = offset + 72 + 80 * i
                va, length, fileoff = struct.unpack_from('<QQI', data, at + 32)
                sections.append({'name': data[at:at + 16].rstrip(b'\0').decode(), 'va': va, 'size': length,
                                 'fileoff': fileoff, 'command_offset': at})
            segments.append({'sections': sections})
        offset += size
    return {'commands': commands, 'segments': segments}

def object_symbols(data):
    commands = macho(data)['commands']
    st = next(p for c, p, _ in commands if c == 2)
    sy, count, strings, _ = struct.unpack_from('<4I', data, st + 8)
    found = []
    for i in range(count):
        ix, kind, _, _, va = struct.unpack_from('<IBBHQ', data, sy + i * 16)
        found.append((data[strings + ix:data.index(b'\0', strings + ix)].decode(), va, kind))
    return found

def object_vtable(data, found, name, count):
    """[(symbol, signed word)] of the first count entries of vtable name (authenticated pointer relocations)."""
    va = next(v for n, v, _ in found if n == name)
    entries = {}
    for segment in macho(data)['segments']:
        for sec in segment['sections']:
            if sec['va'] <= va < sec['va'] + sec['size']:
                ro, rc = struct.unpack_from('<2I', data, sec['command_offset'] + 56)
                for i in range(rc):
                    offset, bits = struct.unpack_from('<2I', data, ro + i * 8)
                    if bits >> 27 & 1 and bits >> 25 & 3 == 3 and bits >> 28 == 11:
                        entries[sec['va'] + offset] = (found[bits & 0xffffff][0],
                                                       struct.unpack_from('<Q', data, sec['fileoff'] + offset)[0])
    return [entries.get(va + 16 + i * 8) for i in range(count)]
