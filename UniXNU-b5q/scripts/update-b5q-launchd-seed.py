#!/usr/bin/env python3
"""Merge launchd overrides into the existing 4 GiB APFS Data seed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

SEED_HASH = "aa624655fd41db6af03ddf0bcb46ed0b5a333f307912f74ac471c7b1b3bfa82b"
V29_SEED_HASH = "f1f6afe508b4c7c57254780c82018f039ae2b3cd691222a287d9d3a37bb3749b"
V31_SEED_HASH = "10223429847dd0a2d2db4a080cea37847db9d92a0499d9c998f53458ae1d6603"
V32_SEED_HASH = "f84207df2076b9eec9f1ba5bec3e2a4e97e8eff1f10ee460967c2dcb91288e2f"
V33_SEED_HASH = "3c375836fac6170e005ad164d41b05e275114246cd25657c944fa8c97b6b8c5e"
CURRENT_SEED_HASH = "d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70"
# CI 45540221549: digest-verified artifact, APFS policy/account/inode readback
# passed. This is the current seed after its 58/25 policy migration, not a
# different baseline or a newly generated Data volume.
MIGRATED_SEED_HASH = "bb959aea0c4ece46fc7903053786825dba44184ee010c9a722e1b8811387d4d2"
ABSENTD_HASH = "29c52a1b79e53b71022c973a071e1e5dc96830445f742263d68276cee3cb9b72"
POLICY = Path(os.environ.get("UNIXNU_DEVICE", Path(__file__).resolve().parents[1])) / "package/b5q-launchd-lite.json"
DIRECTORY = "private/var/db/com.apple.xpc.launchd"


def policies():
    policy = json.loads(POLICY.read_text())
    assert all(re.fullmatch(r"com\.apple\.[\w.-]+", job) for group in policy.values() for job in group)
    return {
        "disabled.plist": sorted(set(policy["sheng_lite"] + policy["system"] + policy["gui"] + policy.get("bundled", []))),
        "disabled.501.plist": sorted(set(policy["sheng_lite"] + policy["gui"] + policy.get("bundled", []))),
    }


def merge(original, disabled):
    options = plistlib.loads(original) if original else {}
    if not isinstance(options, dict):
        raise ValueError("Launchd overrides must be a plist dictionary")
    # These are board-owned files in the hash-qualified RAM seed. Replace the
    # old policy completely so wrong/iOS-only Labels and EndpointSecurity do
    # not survive a merge. Account and all other seed files are unchanged.
    return plistlib.dumps(dict.fromkeys(disabled, True), fmt=plistlib.FMT_BINARY, sort_keys=True)


def checked_seed(body, metadata, baseline, stand_in=None):
    expected = {"v27": SEED_HASH, "v29": V29_SEED_HASH, "v31": V31_SEED_HASH,
                "v32": V32_SEED_HASH, "v33": V33_SEED_HASH, "current": CURRENT_SEED_HASH}[baseline]
    digest = hashlib.sha256(body).hexdigest()
    allowed = {expected, MIGRATED_SEED_HASH} if baseline == "current" else {expected}
    if digest not in allowed or metadata.get("sha256") != digest:
        raise ValueError("Data seed does not match a pinned baseline SHA256")
    if metadata.get("logical_bytes") != 4 * 2**30 or metadata.get("volume_uuid") != "1552CFEE-78FF-48D8-8A6C-694B867D61AC":
        raise ValueError("Data seed size or volume UUID mismatch")
    # Only the exact APFS image already read back is eligible for a no-op.
    # Self-declared policy metadata must never qualify an arbitrary seed.
    reusable = (digest == MIGRATED_SEED_HASH
                and metadata.get("launchd_policy") == {
                    name: sorted(set(labels + ["com.apple.wallpaper.agent"]))
                    for name, labels in policies().items()}
                and metadata.get("launchd_policy_migrated") is True
                and metadata.get("board_stand_in") == {
                    "path": "/private/var/ngpu/bin/b5q-absentd", "sha256": ABSENTD_HASH}
                and (stand_in is None or hashlib.sha256(stand_in.read_bytes()).hexdigest() == ABSENTD_HASH))
    return digest, reusable


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("darwinboot", "seed", "out"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--baseline", choices=("v27", "v29", "v31", "v32", "v33", "current"), default="v27")
    p.add_argument("--stand-in", type=Path, help="Ad hoc signed board absentd, installed under its own name")
    args = p.parse_args()
    sys.path.insert(0, str(args.darwinboot.resolve() / "Test"))
    import packed_ramdisk

    seed = args.seed.resolve()
    out = args.out.resolve()
    metadata = json.loads(seed.with_name("data-seed.json").read_text())
    body = seed.read_bytes()
    expected, reusable = checked_seed(body, metadata, args.baseline, args.stand_in)
    logical, extents = packed_ramdisk.regions(body)
    assert logical == metadata["logical_bytes"] == 4 * 2**30
    out.mkdir(parents=True, exist_ok=True)
    if reusable:
        shutil.copyfile(seed, out / "data.dbr")
        (out / "data-seed.json").write_text(json.dumps(metadata, indent=2) + "\n")
        print("Reused SHA256-pinned, APFS-verified qualified 58/25 Data seed unchanged; pre-launchd applies current57/24 policy")
        return
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
