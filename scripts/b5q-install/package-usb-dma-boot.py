#!/usr/bin/env python3
"""Pack the verified USB DMA firmware and an official packed RAM FAT into b5q boot.img."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "UniXNU/scripts"))
from unixnu import ramdisk
from unixnu.boot_template import loader_pe

PAGE = 4096
BOOT_CAPACITY = 96 << 20
FD_BYTES = 0x300000
V8_SHA = "e400f4d63a4baff1845ca336ba87612be44ab2b2113758d290e9840f21f0cfa1"
RAM_DISK_GUID = "75ca63ad-fbae-4a06-92a0-f937c671251d"
DARWIN_BOOT_GUID = "1b64af87-8415-4b57-9b16-680d70913b9f"
DARWIN_BOOT_EFI = "EFI/UniXNU/Drivers/DarwinBoot.efi"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record(path):
    with path.open("rb") as stream:
        return {"bytes": path.stat().st_size, "sha256": hashlib.file_digest(stream, "sha256").hexdigest()}


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def pad(size):
    return -size % PAGE


def split(image):
    assert image[:8] == b"ANDROID!" and struct.unpack_from("<I", image, 40)[0] == 4
    assert struct.unpack_from("<I", image, 1580)[0] == 0
    kernel_size, ramdisk_size = struct.unpack_from("<II", image, 8)
    end = PAGE + kernel_size
    reader = zlib.decompressobj(31)
    combined = reader.decompress(image[PAGE:end])
    dtb = reader.unused_data
    assert reader.eof and dtb[:4] == b"\xd0\x0d\xfe\xed"
    assert struct.unpack_from(">I", dtb, 4)[0] == len(dtb)
    start = end + pad(kernel_size)
    finish = start + ramdisk_size
    assert len(image) == finish + pad(ramdisk_size)
    assert not any(image[end:start]) and not any(image[finish:])
    return combined[:-FD_BYTES], combined[-FD_BYTES:], dtb, image[start:finish]


def tree_files(path):
    return {p.relative_to(path).as_posix(): record(p) for p in path.rglob("*") if p.is_file()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("fd", "esp", "baseline", "out", "basetools"):
        p.add_argument("--" + option, type=Path, required=True)
    a = p.parse_args()

    original = a.baseline.read_bytes()
    assert sha(original) == V8_SHA
    shim, _, dtb, bootstrap = split(original)
    assert len(shim) == 112 and bootstrap[:8] != ramdisk.MAGIC
    fd = a.fd.read_bytes()
    assert len(fd) == FD_BYTES
    ram_driver = loader_pe(fd, RAM_DISK_GUID)
    assert ramdisk.MAGIC in ram_driver and b"UNIXNURAMDISK: packed" in ram_driver
    pe = loader_pe(fd, DARWIN_BOOT_GUID)

    with tempfile.TemporaryDirectory(prefix="b5q-boot-ram-") as tmp:
        d = Path(tmp)
        source = d / "source"
        source.mkdir()
        run("mcopy", "-s", "-i", a.esp, "::/EFI", source)
        assert (source / DARWIN_BOOT_EFI).read_bytes() == pe
        expected_files = tree_files(source)
        fat = d / "payload.fat"
        with fat.open("wb") as f:
            f.truncate(256 << 20)
        run("mkfs.fat", "--invariant", "-F", 32, "-S", 512, "-s", 4, "-n", "B5QUNIXNU", fat)
        run("mcopy", "-s", "-i", fat, source / "EFI", "::/")
        run("fsck.fat", "-n", fat)
        packed = d / "payload.packed"
        ramdisk.encode(fat, packed, a.basetools)
        compressed = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0, compresslevel=9) as stream:
            stream.write(shim + fd)
        kernel = compressed.getvalue() + dtb
        header = bytearray(original[:PAGE])
        struct.pack_into("<II", header, 8, len(kernel), packed.stat().st_size)
        image = bytes(header) + kernel + bytes(pad(len(kernel))) + packed.read_bytes()
        image += bytes(pad(packed.stat().st_size))
        assert len(image) <= BOOT_CAPACITY
        new_shim, new_fd, new_dtb, new_ramdisk = split(image)
        assert (new_shim, new_fd, new_dtb) == (shim, fd, dtb)
        assert new_ramdisk[:8] == ramdisk.MAGIC and sha(new_ramdisk) == record(packed)["sha256"]
        decoded = d / "decoded.fat"
        ramdisk.decode(packed, decoded, a.basetools)
        assert record(fat) == record(decoded)
        readback = d / "readback"
        readback.mkdir()
        run("mcopy", "-s", "-i", decoded, "::/EFI", readback)
        assert expected_files == tree_files(readback)
        a.out.mkdir(parents=True, exist_ok=True)
        boot = a.out / "boot.img"
        with boot.open("xb") as dest:
            dest.write(image)
        details = {
            "boot": record(boot), "source_boot": record(a.baseline),
            "firmware": record(a.fd), "esp": record(a.esp),
            "boot_partition_bytes": BOOT_CAPACITY,
            "ram_fat_logical_bytes": fat.stat().st_size,
            "ram_fat_packed_bytes": packed.stat().st_size,
            "ram_fat_packed_sha256": sha(new_ramdisk),
            "samsung_dtb_sha256": sha(dtb), "bootshim_sha256": sha(shim),
            "bootshim_and_dtb_match_v8": True,
            "all_efi_files_match_esp": True,
            "hardware_tested": False,
        }
        (a.out / "boot-verification.json").write_text(json.dumps(details, indent=2) + "\n")
        print(json.dumps(details, indent=2))


if __name__ == "__main__":
    main()
