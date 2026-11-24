#!/usr/bin/env python3
"""Pack the verified USB DMA firmware into b5q boot.img."""
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


def repack(original, shim, fd, dtb, ramdisk_bytes):
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=compressed, mtime=0, compresslevel=9) as stream:
        stream.write(shim + fd)
    kernel = compressed.getvalue() + dtb
    header = bytearray(original[:PAGE])
    struct.pack_into("<II", header, 8, len(kernel), len(ramdisk_bytes))
    image = bytes(header) + kernel + bytes(pad(len(kernel))) + ramdisk_bytes
    image += bytes(pad(len(ramdisk_bytes)))
    assert len(image) <= BOOT_CAPACITY
    assert split(image) == (shim, fd, dtb, ramdisk_bytes)
    return image


def publish(args, image, details):
    args.out.mkdir(parents=True, exist_ok=True)
    boot = args.out / "boot.img"
    with boot.open("xb") as dest:
        dest.write(image)
    details.update(boot=record(boot), source_boot=record(args.baseline),
                   firmware=record(args.fd), esp=record(args.esp),
                   boot_partition_bytes=BOOT_CAPACITY, hardware_tested=False)
    (args.out / "boot-verification.json").write_text(json.dumps(details, indent=2) + "\n")
    print(json.dumps(details, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for option in ("fd", "esp", "baseline", "out"):
        p.add_argument("--" + option, type=Path, required=True)
    p.add_argument("--basetools", type=Path)
    p.add_argument("--physical-esp", action="store_true", help="retain v8's plain FAT16 bootstrap and load the payload from the physical ESP")
    a = p.parse_args()
    if not a.physical_esp and not a.basetools:
        p.error("--basetools is required when building a packed RAM FAT")

    original = a.baseline.read_bytes()
    assert sha(original) == V8_SHA
    shim, _, dtb, bootstrap = split(original)
    assert len(shim) == 112 and bootstrap[:8] != ramdisk.MAGIC
    fd = a.fd.read_bytes()
    assert len(fd) == FD_BYTES
    ram_driver = loader_pe(fd, RAM_DISK_GUID)
    assert ramdisk.MAGIC in ram_driver and b"UNIXNURAMDISK: packed" in ram_driver
    pe = loader_pe(fd, DARWIN_BOOT_GUID)

    if a.physical_esp:
        assert len(bootstrap) == 16 << 20 and bootstrap[54:62] == b"FAT16   "
        assert bootstrap[510:512] == b"\x55\xaa"
        esp_loader = subprocess.check_output(["mtype", "-i", str(a.esp), "::/" + DARWIN_BOOT_EFI])
        assert esp_loader == pe
        image = repack(original, shim, fd, dtb, bootstrap)
        publish(a, image, {"boot_source": "physical 4Kn UFS ESP",
                           "bootstrap_fat16_bytes": len(bootstrap), "bootstrap_fat16_sha256": sha(bootstrap),
                           "darwinboot_sha256": sha(pe), "samsung_dtb_sha256": sha(dtb), "bootshim_sha256": sha(shim)})
        return

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
        new_ramdisk = packed.read_bytes()
        assert new_ramdisk[:8] == ramdisk.MAGIC
        image = repack(original, shim, fd, dtb, new_ramdisk)
        decoded = d / "decoded.fat"
        ramdisk.decode(packed, decoded, a.basetools)
        assert record(fat) == record(decoded)
        readback = d / "readback"
        readback.mkdir()
        run("mcopy", "-s", "-i", decoded, "::/EFI", readback)
        assert expected_files == tree_files(readback)
        details = {
            "ram_fat_logical_bytes": fat.stat().st_size,
            "ram_fat_packed_bytes": packed.stat().st_size,
            "ram_fat_packed_sha256": sha(new_ramdisk),
            "samsung_dtb_sha256": sha(dtb), "bootshim_sha256": sha(shim),
            "bootshim_and_dtb_match_v8": True,
            "all_efi_files_match_esp": True,
        }
        publish(a, image, details)


if __name__ == "__main__":
    main()
