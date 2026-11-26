#!/usr/bin/env python3
"""Version-locked macOS 27.3 bluetoothd third-party LE event mask patch.

Only the single-architecture arm64e MobileBluetooth daemon from 26C5035r is
accepted. The two sites are checked byte-for-byte before either is written;
site 1 is normally already 0x101f after native_macos27.py enabled extended
advertising. The original 0x001f value is accepted only through an explicit
test-only switch.
"""
from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Any

B5Q_LE_EVENT_MASK = 0x000000000000187F
B5Q_UUID = "01204E5C-F295-35D8-9ED6-62ECF79D62DF"
B5Q_CPU_TYPE = 0x0100000C
B5Q_CPU_SUBTYPE = 0x80000002
SITE1_OFFSET = 0x95D54B
SITE1_OLD = bytes.fromhex("1f10000000000000")
SITE1_ORIGINAL = bytes.fromhex("1f00000000000000")
SITE1_NEW = bytes.fromhex("7f18000000000000")
SITE2_OFFSET = 0x193648
SITE2_ANCHOR_BEFORE = (0x193644, 0x7100001F, 0x528003E8, 0x19364C, 0xD29F4FE9)
SITE2_NEW = 0x52830FE8
MACHO_MAGIC_64 = 0xFEEDFACF
LC_UUID = 0x1B


class BluetoothdPatchError(ValueError):
    pass


def _u32(data: bytes, offset: int) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise BluetoothdPatchError(f"truncated Mach-O at {offset:#x}")
    return struct.unpack_from("<I", data, offset)[0]


def _uuid_text(raw: bytes) -> str:
    if len(raw) != 16:
        raise BluetoothdPatchError("LC_UUID is not 16 bytes")
    value = raw.hex().upper()
    return f"{value[:8]}-{value[8:12]}-{value[12:16]}-{value[16:20]}-{value[20:]}"


def _validate_macho(data: bytes) -> str:
    if len(data) < 32 or _u32(data, 0) != MACHO_MAGIC_64:
        raise BluetoothdPatchError("expected a thin 64-bit Mach-O image")
    cputype = struct.unpack_from("<i", data, 4)[0] & 0xFFFFFFFF
    subtype = struct.unpack_from("<i", data, 8)[0] & 0xFFFFFFFF
    if cputype != B5Q_CPU_TYPE:
        raise BluetoothdPatchError(f"cputype mismatch: {cputype:#x}")
    if subtype != B5Q_CPU_SUBTYPE:
        raise BluetoothdPatchError(f"cpusubtype mismatch: {subtype:#x}")
    ncmds = _u32(data, 16)
    at = 32
    seen_uuid = None
    for _ in range(ncmds):
        cmd = _u32(data, at)
        size = _u32(data, at + 4)
        if size < 8 or at + size > len(data):
            raise BluetoothdPatchError("invalid Mach-O load command")
        if cmd == LC_UUID:
            if size < 24 or seen_uuid is not None:
                raise BluetoothdPatchError("invalid LC_UUID")
            seen_uuid = _uuid_text(data[at + 8:at + 24])
        at += size
    if seen_uuid is None:
        raise BluetoothdPatchError("LC_UUID is absent")
    if seen_uuid != B5Q_UUID:
        raise BluetoothdPatchError(f"bluetoothd UUID mismatch: {seen_uuid}")
    return seen_uuid


def _site1(data: bytes, allow_original: bool) -> dict[str, Any]:
    old = data[SITE1_OFFSET:SITE1_OFFSET + 8]
    if old == SITE1_OLD:
        source = "native_macos27_extended_advertising"
    elif old == SITE1_ORIGINAL and allow_original:
        source = "explicit_test_only_original"
    elif old == SITE1_ORIGINAL:
        raise BluetoothdPatchError("site 1 is still the original 0x001f mask; native_macos27 patch is required")
    else:
        raise BluetoothdPatchError(f"site 1 bytes differ: {old.hex()}")
    return {"offset": SITE1_OFFSET, "old": old.hex(), "new": SITE1_NEW.hex(),
            "old_value": int.from_bytes(old, "little"), "new_value": B5Q_LE_EVENT_MASK,
            "source": source}


def _site2(data: bytes) -> dict[str, Any]:
    at_anchor, before, old, after_at, after = SITE2_ANCHOR_BEFORE
    if _u32(data, at_anchor) != before:
        raise BluetoothdPatchError(f"site 2 pre-anchor differs: {_u32(data, at_anchor):#x}")
    if _u32(data, SITE2_OFFSET) != old:
        raise BluetoothdPatchError(f"site 2 old instruction differs: {_u32(data, SITE2_OFFSET):#x}")
    if _u32(data, after_at) != after:
        raise BluetoothdPatchError(f"site 2 post-anchor differs: {_u32(data, after_at):#x}")
    return {"offset": SITE2_OFFSET, "old": f"{old:08x}", "new": f"{SITE2_NEW:08x}",
            "old_value": old, "new_value": SITE2_NEW,
            "anchors": [f"{at_anchor:#x}={before:#010x}",
                        f"{after_at:#x}={after:#010x}"]}


def patch_macos27_bluetoothd_bytes(data: bytes, *, allow_original_site1: bool = False
                                    ) -> tuple[bytes, dict[str, Any]]:
    """Validate and patch a thin arm64e bluetoothd image in memory."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("data must be bytes")
    raw = bytes(data)
    uuid = _validate_macho(raw)
    site1 = _site1(raw, allow_original_site1)
    site2 = _site2(raw)
    before = hashlib.sha256(raw).hexdigest()
    out = bytearray(raw)
    out[SITE1_OFFSET:SITE1_OFFSET + 8] = SITE1_NEW
    struct.pack_into("<I", out, SITE2_OFFSET, SITE2_NEW)
    after = hashlib.sha256(out).hexdigest()
    report = {
        "uuid": uuid,
        "site_count": 2,
        "patched_sites": [site1, site2],
        "old_mask": 0x101F,
        "new_mask": B5Q_LE_EVENT_MASK,
        "sha256_before": before,
        "sha256_after": after,
        "size": len(out),
        "original_site1_accepted": bool(allow_original_site1 and site1["source"] != "native_macos27_extended_advertising"),
    }
    return bytes(out), report


def patch_macos27_bluetoothd_file(path: Path, *, allow_original_site1: bool = False
                                  ) -> dict[str, Any]:
    """Patch a thin arm64e bluetoothd file atomically and return its audit."""
    path = Path(path)
    original = path.read_bytes()
    patched, report = patch_macos27_bluetoothd_bytes(original, allow_original_site1=allow_original_site1)
    temporary = path.with_name(path.name + ".b5q-le-mask.tmp")
    temporary.write_bytes(patched)
    temporary.chmod(path.stat().st_mode & 0o7777)
    temporary.replace(path)
    report["path"] = str(path)
    report["bytes"] = len(patched)
    return report
