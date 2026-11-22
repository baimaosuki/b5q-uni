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
V29_SEED_HASH = "f1f6afe508b4c7c57254780c82018f039ae2b3cd691222a287d9d3a37bb3749b"
V31_SEED_HASH = "10223429847dd0a2d2db4a080cea37847db9d92a0499d9c998f53458ae1d6603"
V32_SEED_HASH = "f84207df2076b9eec9f1ba5bec3e2a4e97e8eff1f10ee460967c2dcb91288e2f"
POLICY = Path(__file__).resolve().parents[1] / "package/b5q-launchd-lite.json"
DIRECTORY = "private/var/db/com.apple.xpc.launchd"


def policies():
    policy = json.loads(POLICY.read_text())
    assert all(re.fullmatch(r"com\.apple\.[\w.-]+", job) for group in policy.values() for job in group)
    return {
        "disabled.plist": sorted(set(policy["sheng_lite"] + policy["system"] + policy["gui"])),
        "disabled.501.plist": sorted(set(policy["sheng_lite"] + policy["gui"])),
    }


def merge(original, disabled):
    options = plistlib.loads(original) if original else {}
    if not isinstance(options, dict):
        raise ValueError("Launchd overrides must be a plist dictionary")
    # These are board-owned files in the hash-qualified RAM seed. Replace the
    # old policy completely so wrong/iOS-only Labels and EndpointSecurity do
    # not survive a merge. Account and all other seed files are unchanged.
    return plistlib.dumps(dict.fromkeys(disabled, True), sort_keys=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("darwinboot", "seed", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--baseline", choices=("v27", "v29", "v31", "v32"), default="v27")
    p.add_argument("--stand-in", type=Path, help="Ad hoc signed board absentd, installed under its own name")
    args = p.parse_args()
    sys.path.insert(0, str(args.darwinboot.resolve() / "Test"))
    import packed_ramdisk

    seed = args.seed.resolve()
    out = args.out.resolve()
    metadata = json.loads(seed.with_name("data-seed.json").read_text())
    body = seed.read_bytes()
    expected = {"v27": SEED_HASH, "v29": V29_SEED_HASH, "v31": V31_SEED_HASH, "v32": V32_SEED_HASH}[args.baseline]
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest() == expected
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
            user = plistlib.loads(subprocess.check_output(["sudo", "cat", str(account)]))
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
                assert target.stat().st_mode & 0o7777 == 0o644
            if args.stand_in:
                target = mount / "private/var/ngpu/bin/b5q-absentd"
                assert target.parent.resolve() == target.parent and not target.is_symlink()
                subprocess.run(["sudo", "install", "-d", "-o", "root", "-g", "wheel", "-m", "0755",
                                str(target.parent)], check=True)
                assert target.parent.is_dir() and target.parent.resolve() == target.parent
                subprocess.run(["sudo", "install", "-o", "root", "-g", "wheel", "-m", "0755",
                                str(args.stand_in.resolve()), str(target)], check=True)
                assert target.read_bytes() == args.stand_in.read_bytes()
                assert target.stat().st_uid == target.stat().st_gid == 0
        finally:
            subprocess.run(["hdiutil", "detach", device], check=True)
        result = packed_ramdisk.pack(raw, out / "data.dbr")
    assert result["bytes"] == logical
    metadata.update(bytes=result["encoded_bytes"], sha256=result["encoded_sha256"],
                    launchd_policy=updates, launchd_policy_source_seed_sha256=expected,
                    launchd_policy_migrated=True)
    if args.stand_in:
        metadata["board_stand_in"] = {
            "path": "/private/var/ngpu/bin/b5q-absentd",
            "sha256": hashlib.sha256(args.stand_in.read_bytes()).hexdigest(),
        }
    (out / "data-seed.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Updated {len(updates['disabled.plist'])} system overrides and {len(updates['disabled.501.plist'])} GUI overrides")


if __name__ == "__main__":
    main()
