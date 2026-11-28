#!/usr/bin/env python3
"""Repack a verified b5q ESP with the DarwinBoot PE from the new firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "UniXNU/scripts"))
from unixnu.boot_template import loader_pe

LOADER = "1b64af87-8415-4b57-9b16-680d70913b9f"
V27_SHA = "f7cacbc026f765514262d62d634a49af6526167350e16a15bcf966f7604c446a"
V29_SHA = "441607e5f864935e2000ba5dea04e90c9b2fbdb11c4df10bd6ba672cef191134"
EFI = "EFI/UniXNU"
ADT = EFI + "/Payloads/kernel.macho.adt"
DRIVER = EFI + "/Drivers/DarwinBoot.efi"
PLACEHOLDERS = {"b5q-usb-dma-ready": 4, "b5q-usb-dma-state": 48, "b5q-usb-dma-diagnostics": 48}


def record(path):
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def adt_nodes(data):
    nodes = {}
    def visit(at, parent, depth):
        assert depth <= 64
        start = at
        count, children = struct.unpack_from("<II", data, at)
        at += 8
        properties = {}
        for _ in range(count):
            raw, length = struct.unpack_from("<32sI", data, at)
            name = raw.rstrip(b"\0").decode()
            at += 36
            assert name not in properties and length <= len(data) - at
            properties[name] = data[at:at + length]
            at += (length + 3) & ~3
        name = properties["name"].rstrip(b"\0").decode()
        path = "/" if parent is None else parent.rstrip("/") + "/" + name
        assert path not in nodes
        nodes[path] = (start, at, properties)
        for _ in range(children):
            at = visit(at, path, depth + 1)
        return at
    assert visit(0, None, 0) == len(data)
    return nodes


def add_placeholders(data):
    before = adt_nodes(data)
    start, end, chosen = before["/chosen"]
    assert not (chosen.keys() & PLACEHOLDERS.keys())
    added = b"".join(struct.pack("<32sI", name.encode(), length) + bytes(length)
                     for name, length in PLACEHOLDERS.items())
    updated = data[:start] + struct.pack("<I", len(chosen) + len(PLACEHOLDERS))
    updated += data[start + 4:end] + added + data[end:]
    after = adt_nodes(updated)
    assert before.keys() == after.keys()
    for name in before:
        expected = before[name][2].copy()
        if name == "/chosen":
            expected.update({key: bytes(length) for key, length in PLACEHOLDERS.items()})
        assert after[name][2] == expected
    return updated


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def members(image, destination):
    destination.mkdir()
    run("mcopy", "-s", "-i", image, "::/*", destination)
    return {p.relative_to(destination).as_posix(): record(p)
            for p in destination.rglob("*") if p.is_file()}


def image_format(image):
    with image.open("rb") as stream:
        bpb = stream.read(4096)
    assert image.stat().st_size == 800 * 2**20 and bpb[82:90] == b"FAT32   "
    assert struct.unpack_from("<H", bpb, 11)[0] == 4096 and bpb[13] == 1 and bpb[16] == 2
    assert struct.unpack_from("<I", bpb, 32)[0] * 4096 == image.stat().st_size
    assert struct.unpack_from("<I", bpb, 36)[0] <= 256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esp", type=Path, required=True, help="verified input ESP updated in place")
    parser.add_argument("--fd", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--baseline", choices=("v27", "v29"), default="v27")
    args = parser.parse_args()
    original = record(args.esp)
    from_v29 = args.baseline == "v29"
    assert original["sha256"] == (V29_SHA if from_v29 else V27_SHA)
    image_format(args.esp)
    loader = loader_pe(args.fd.read_bytes(), LOADER)
    assert b"b5q-usb-dma-diagnostics" in loader
    with tempfile.TemporaryDirectory(prefix="b5q-dma-esp-") as name:
        temp = Path(name)
        before = members(args.esp, temp / "before")
        adt = (temp / "before" / ADT).read_bytes()
        updated = {}
        if from_v29:
            chosen = adt_nodes(adt)["/chosen"][2]
            assert all(chosen.get(name) == bytes(size) for name, size in PLACEHOLDERS.items())
        else:
            patched = temp / "kernel.macho.adt"
            patched.write_bytes(add_placeholders(adt))
            updated[ADT] = patched
        pe = temp / "DarwinBoot.efi"
        pe.write_bytes(loader)
        if before[DRIVER] != record(pe):
            updated[DRIVER] = pe
        for name, path in updated.items():
            run("mcopy", "-o", "-i", args.esp, path, "::/" + name)
        after = members(args.esp, temp / "after")
        assert before.keys() == after.keys()
        assert {item for item in before if before[item] != after[item]} == updated.keys()
        assert all(after[name] == record(path) for name, path in updated.items())
        assert after[DRIVER] == record(pe)
        menu = tomllib.loads((temp / "after" / EFI / "unixnu.toml").read_text())
        entry = next(e for e in menu["entry"] if e.get("type") == "xnu")
        assert menu["boot"]["default"] == entry["id"] == "xnu"
        assert "usb=1" in entry["args"].split() and len(entry["args"].encode()) <= 950
    image_format(args.esp)
    run("fsck.fat", "-n", args.esp)
    report = {"baseline_run": 44985774704 if from_v29 else 44980608285,
              "baseline_esp": original, "updated_esp": record(args.esp),
              "firmware": record(args.fd), "darwinboot": after[DRIVER], "boot_args_bytes": len(entry["args"].encode()),
              "changed_esp_files": list(updated), "members": after, "real_device_verified": False}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"esp": report["updated_esp"], "darwinboot": report["darwinboot"]}))


if __name__ == "__main__":
    main()
