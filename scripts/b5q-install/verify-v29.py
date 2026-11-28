#!/usr/bin/env python3
"""Check v29's real ESP, incremental objects and RAM Data before packaging boot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
DISPLAY = "build/native-legacy-display/libNativeLegacyDisplay.late.a"
MEMBERS = {"B5qTouch.o", "NativeHidInput.late.o", "HidInputProbe.o"}
sys.path[:0] = [str(ROOT / "UniXNU/drivers/DarwinBoot/Test"), str(ROOT / "UniXNU/scripts")]
from packed_ramdisk import regions
from unixnu.boot_template import loader_pe


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(*command):
    subprocess.run([str(part) for part in command], check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("ci", "cache", "fd", "out", "apfs-tools"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    esp = a.ci / "esp.img"
    filesystem = load(Path(__file__).with_name("package-usb-dma-esp.py"))
    filesystem.image_format(esp)
    run("fsck.fat", "-n", esp)
    run(sys.executable, Path(__file__).with_name("verify-esp-log.py"),
        "--esp", esp, "--out", a.out / "log-allocation.json")

    link = json.loads((a.ci / "kernel/incremental-relink.json").read_text())
    assert link["core_translation_units_compiled"] == 0 and link["board_translation_units_compiled"] == 3
    assert not link["gpu_recompiled"] and not link["binder_objects_compiled"]
    for archive, before in link["input_archive_members"].items():
        assert digest(a.cache / "tree" / archive) == link["input_archives"][archive]
        if archive != DISPLAY:
            assert link["archive_outputs"][archive] == link["input_archives"][archive]
        if archive in link["output_archive_members"]:
            after = link["output_archive_members"][archive]
            assert before.keys() == after.keys()
            assert {key for key in before if before[key] != after[key]} == (MEMBERS if archive == DISPLAY else set())
    for name, info in link["returned_objects"].items():
        obj = a.ci / "kernel/incremental-objects" / name
        assert digest(obj) == info["sha256"] == link["output_archive_members"][DISPLAY][info["archive_member"]]

    old = json.loads((ROOT / "artifacts/b5q-esp-runtime-v27/package.manifest.json").read_text())
    payload = json.loads((a.ci / "payload/payload.json").read_text())
    with tempfile.TemporaryDirectory(prefix="b5q-v29-verify-") as td:
        temp = Path(td)
        files = temp / "efi"
        members = filesystem.members(esp, files)
        new = {k: v for k, v in members.items() if k.startswith("EFI/")}
        assert set(new) == set(old["esp_files"])
        expected_changes = {filesystem.ADT, filesystem.DRIVER,
                            "EFI/UniXNU/Payloads/kernel.macho", "EFI/UniXNU/Payloads/scratch-data.img",
                            "EFI/UniXNU/Payloads/kernel.macho.crypto-hmac.json"}
        assert {k for k, v in new.items() if v != old["esp_files"][k]} == expected_changes
        adt = filesystem.adt_nodes((files / filesystem.ADT).read_bytes())["/chosen"][2]
        assert all(adt[key] == bytes(size) for key, size in filesystem.PLACEHOLDERS.items())
        menu = tomllib.loads((files / "EFI/UniXNU/unixnu.toml").read_text())
        entry = next(item for item in menu["entry"] if item["type"] == "xnu")
        assert entry["args"] == old["kernel_command_line"] and len(entry["args"].encode()) <= 950
        assert adt["text-fixups"] == (b"dyld_shared_cache_arm64e.03,5de1134,08060037,1f2003d5\0"
                                     b"dyld_shared_cache_arm64e.03,5de63cc,1811981a,f803082a\0")
        assert (files / filesystem.DRIVER).read_bytes() == loader_pe(a.fd.read_bytes(), filesystem.LOADER)
        kernel = files / "EFI/UniXNU/Payloads/kernel.macho"
        kernel_sha = digest(kernel)
        assert kernel_sha == payload["payload_kernel_sha256"]
        for marker in (b"disabled11=%u selected=%02x", b"touch-mouse", b"displayUUID"):
            assert marker in kernel.read_bytes(), marker
        run(sys.executable, ROOT / "tests/b5q-ufs/test-post-seal.py", "--kernel", kernel, "--out", a.out / "post-seal.json")

        seed = files / "EFI/UniXNU/Payloads/scratch-data.img"
        assert digest(seed) == payload["data_ramdisk_sha256"] == digest(a.ci / "runtime/data.dbr")
        logical, extents = regions(seed.read_bytes())
        assert logical == 4 * 2**30
        raw = temp / "data.raw"
        with raw.open("wb") as stream:
            stream.truncate(logical)
            for offset, data in extents:
                stream.seek(offset)
                stream.write(data)
        account = load(Path(__file__).with_name("verify-data-account.py"))
        policy = load(ROOT / "UniXNU-b5q/scripts/update-b5q-launchd-seed.py")
        prefix = policy.DIRECTORY
        policy_paths = [prefix + "/" + name for name in (*policy.policies(), "disabled.migrated")]
        requested = list(dict.fromkeys([*account.PATHS, *policy_paths]))
        tool = temp / "read-apfs"
        build = a.apfs_tools / "build"
        run("c++", "-std=c++17", "-O2", "-I", a.apfs_tools, Path(__file__).with_name("read-seed-apfs.cpp"),
            build / "libapfs.a", "-lz", "-lbz2", build / "liblzfse.a", build / "libcrypto.a", "-o", tool)
        extracted = temp / "apfs"
        stats = {}
        for line in subprocess.check_output([str(tool), str(raw), str(extracted), *requested], text=True).splitlines():
            path, uid, gid, mode, size = line.split("\t")
            stats[path] = dict(uid=int(uid), gid=int(gid), mode=int(mode, 8), bytes=int(size))
        account.verify_files(extracted, stats)
        for name in policy_paths:
            assert stats[name]["uid"] == stats[name]["gid"] == 0
            assert stats[name]["mode"] == 0o100644
        for name, labels in policy.policies().items():
            overrides = plistlib.loads((extracted / prefix / name).read_bytes())
            assert all(overrides.get(label) is value for label,value in labels.items())
        assert (extracted / prefix / "disabled.migrated").stat().st_size == 0

        geometry = {"bytes": esp.stat().st_size, "sha256": digest(esp)}
        verification = {"kernel_sha256": kernel_sha, "seed_sha256": digest(seed),
                        "data_bytes": logical, "ESP": geometry, "members": new,
                        "launchd_overrides": {key: len(value) for key, value in policy.policies().items()},
                        "changed_archive_members": sorted(MEMBERS), "hardware_tested": False,
                        "checks": ["FAT32 4Kn", "XNU2LOG allocation", "v28 loader", "USB DMA ADT placeholders",
                                   "4 GiB APFS Data and launchd policy", "unchanged boot args and GPU addon", "POST seal"]}
    (a.out / "v29-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({k: v for k, v in verification.items() if k != "members"}, indent=2))


if __name__ == "__main__":
    main()
