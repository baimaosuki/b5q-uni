#!/usr/bin/env python3
"""Merge launchd overrides into the existing 4 GiB APFS Data seed."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tempfile

SEED_HASH = "aa624655fd41db6af03ddf0bcb46ed0b5a333f307912f74ac471c7b1b3bfa82b"
POLICY = Path(__file__).resolve().parents[1] / "package/b5q-launchd-lite.json"
DIRECTORY = "private/var/db/com.apple.xpc.launchd"


def policies():
    policy = json.loads(POLICY.read_text())
    assert all(re.fullmatch(r"com\.apple\.[\w.-]+", job) for group in policy.values() for job in group)
    return {
        "disabled.plist": sorted(set(policy["sheng_lite"] + policy["system"] + policy["gui"])),
        "disabled.501.plist": sorted(set(policy["gui"])),
    }


def merge(original, disabled):
    options = plistlib.loads(original) if original else {}
    if not isinstance(options, dict):
        raise ValueError("Launchd overrides must be a plist dictionary")
    options.update(dict.fromkeys(disabled, True))
    return plistlib.dumps(options, sort_keys=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("darwinboot", "seed", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    args = p.parse_args()
    sys.path.insert(0, str(args.darwinboot.resolve() / "Test"))
    import packed_ramdisk

    seed = args.seed.resolve()
    out = args.out.resolve()
    metadata = json.loads(seed.with_name("data-seed.json").read_text())
    body = seed.read_bytes()
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest() == SEED_HASH
    logical, extents = packed_ramdisk.regions(body)
    assert logical == metadata["logical_bytes"] == 4 * 2**30
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b5q-launchd-seed-") as temp:
        temp = Path(temp).resolve()
        raw = temp / "Data.raw"
        mount = temp / "mount"
        mount.mkdir()
        with raw.open("wb") as f:
            f.truncate(logical)
            for offset, data in extents:
                f.seek(offset)
                f.write(data)
        attached = plistlib.loads(subprocess.check_output([
            "hdiutil", "attach", "-imagekey", "diskimage-class=CRawDiskImage", "-nobrowse",
            "-owners", "on", "-mountpoint", str(mount), "-plist", str(raw)]))
        device = attached["system-entities"][0]["dev-entry"]
        try:
            assert re.fullmatch(r"/dev/disk\d+(?:s\d+)?", device)
            info = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", str(mount)]))
            assert info["VolumeUUID"].upper() == metadata["volume_uuid"]
            account = mount / "private/var/db/dslocal/nodes/Default/users/baimao.plist"
            user = plistlib.loads(account.read_bytes())
            assert user["uid"] == ["501"]
            directory = mount / DIRECTORY
            assert directory.is_dir() and directory.resolve() == directory
            updates = policies()
            for name in (*updates, "disabled.migrated"):
                target = directory / name
                assert not target.is_symlink()
                original = target.read_bytes() if target.is_file() else b""
                payload = merge(original, updates[name]) if name in updates else b""
                stage = temp / name
                stage.write_bytes(payload)
                subprocess.run(["sudo", "install", "-o", "root", "-g", "wheel", "-m", "0644",
                                str(stage), str(target)], check=True)
                assert target.read_bytes() == payload and target.stat().st_uid == target.stat().st_gid == 0
        finally:
            subprocess.run(["hdiutil", "detach", device], check=True)
        result = packed_ramdisk.pack(raw, out / "data.dbr")
    assert result["bytes"] == logical
    metadata.update(bytes=result["encoded_bytes"], sha256=result["encoded_sha256"],
                    launchd_policy=updates, launchd_policy_source_seed_sha256=SEED_HASH,
                    launchd_policy_migrated=True)
    (out / "data-seed.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Updated {len(updates['disabled.plist'])} system overrides and {len(updates['disabled.501.plist'])} GUI overrides")


if __name__ == "__main__":
    main()
