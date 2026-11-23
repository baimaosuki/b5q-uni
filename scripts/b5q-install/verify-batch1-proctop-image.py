#!/usr/bin/env python3
"""Read back the one-image Batch1 ProcTop rebuild against its verified base."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--esp", type=Path, required=True)
    parser.add_argument("--baseline-esp", type=Path,
                        default=ROOT / "artifacts/b5q-esp-batch1-final/esp.img")
    parser.add_argument("--readback-dir", type=Path,
                        default=ROOT / "artifacts/b5q-batch1-final-work/final-verification")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    fs = load(ROOT / "scripts/b5q-install/package-usb-dma-esp.py")
    fs.image_format(args.esp)
    fs.image_format(args.baseline_esp)
    subprocess.run(["fsck.fat", "-n", str(args.esp)], check=True, stdout=subprocess.DEVNULL)
    args.out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="b5q-batch1-image-") as td:
        temp = Path(td)
        current_dir, baseline_dir = temp / "current", temp / "baseline"
        current = fs.members(args.esp, current_dir)
        baseline = fs.members(args.baseline_esp, baseline_dir)
        current_efi = {key: value for key, value in current.items() if key.startswith("EFI/")}
        baseline_efi = {key: value for key, value in baseline.items() if key.startswith("EFI/")}
        assert set(current) == set(baseline) and set(current_efi) == set(baseline_efi)

        kernel_rel = "EFI/UniXNU/Payloads/kernel.macho"
        trust_rel = "EFI/UniXNU/Payloads/kernel.macho.trustcache"
        hmac_rel = "EFI/UniXNU/Payloads/kernel.macho.crypto-hmac.json"
        changes = {key for key, value in current.items() if value != baseline[key]}
        assert kernel_rel in changes
        assert changes <= {fs.ADT, kernel_rel, trust_rel, hmac_rel}, changes

        adt_rel = fs.ADT
        adt_data = (current_dir / adt_rel).read_bytes()
        adt_nodes = fs.adt_nodes(adt_data)
        chosen = adt_nodes["/chosen"][2]
        asmb = adt_nodes["/chosen/asmb"][2]
        assert len(asmb["lp-sip0"]) == 8
        assert asmb["lp-sip0"] == bytes.fromhex("0200000000000000")
        baseline_nodes = fs.adt_nodes((baseline_dir / adt_rel).read_bytes())
        assert asmb == baseline_nodes["/chosen/asmb"][2]
        previous_chosen = baseline_nodes["/chosen"][2]
        assert chosen.keys() == previous_chosen.keys()
        assert all(chosen[key] == previous_chosen[key] for key in chosen if key != "random-seed")
        assert chosen["text-fixups"] == (
            b"dyld_shared_cache_arm64e.03,5de1134,08060037,1f2003d5\0"
            b"dyld_shared_cache_arm64e.03,5de63cc,1811981a,f803082a\0")

        menu = tomllib.loads((current_dir / "EFI/UniXNU/unixnu.toml").read_text())
        board = tomllib.loads((ROOT / "UniXNU-b5q/board.toml").read_text())
        entry = next(item for item in menu["entry"] if item["type"] == "xnu")
        args_bytes = entry["args"].encode()
        assert entry["args"] == " ".join(board["payload"]["kernel_args"])
        assert len(args_bytes) <= 950 and b"offline-mobile-graphics-client=" not in args_bytes

        kernel = current_dir / kernel_rel
        kernel_bytes = kernel.read_bytes()
        for marker in (b"B5qProcTop: window=30s",
                       b"B5qProcTop: %s TOP%u %s:%u(exit=%u/sig=%u)",
                       b"TOP1..5", b"TOP6..10", b"TOP6..10 end rows=%u overflow=%llu"):
            assert marker in kernel_bytes, marker
        assert b"B5qProcTop: window=30s spawns=%llu exits=%llu top=" not in kernel_bytes

        data_rel = "EFI/UniXNU/Payloads/scratch-data.img"
        data_sha = digest(current_dir / data_rel)
        previous = json.loads((args.readback_dir / "batch1-final-verification.json").read_text())
        plist_report = json.loads((args.readback_dir / "disabled-plists-readback.json").read_text())
        assert data_sha == digest(baseline_dir / data_rel) == previous["seed_sha256"]
        policies = {
            "private/var/db/com.apple.xpc.launchd/disabled.plist": 59,
            "private/var/db/com.apple.xpc.launchd/disabled.501.plist": 26,
        }
        for path, expected_count in policies.items():
            item = plist_report[path]
            assert item["uid"] == item["gid"] == 0 and item["mode"] == 0o100644
            assert item["format"] == "bplist00" and len(item["contents"]) == expected_count
            assert all(value is True for value in item["contents"].values())
        disabled_all = plist_report[next(iter(policies))]["contents"]
        assert not set(disabled_all) & {
            "com.apple.WindowServer", "com.apple.loginwindow", "com.apple.Dock.agent",
            "com.apple.Finder", "com.apple.endpointsecurity.endpointsecurityd"}
        source_verifier = (ROOT / "scripts/b5q-install/verify-batch1-final.py").read_text()
        assert 'assert (extracted / prefix / "disabled.migrated").stat().st_size == 0' in source_verifier
        assert 'for name in policy_paths:' in source_verifier and 'stats[name]["mode"] == 0o100644' in source_verifier

        postseal = temp / "post-seal.json"
        subprocess.run([sys.executable, ROOT / "tests/b5q-ufs/test-post-seal.py",
                        "--kernel", kernel, "--out", postseal], check=True)
        log_report = temp / "log-allocation.json"
        subprocess.run([sys.executable, ROOT / "scripts/b5q-install/verify-esp-log.py",
                        "--esp", args.esp, "--out", log_report], check=True)

        result = {
            "esp_bytes": args.esp.stat().st_size,
            "esp_sha256": digest(args.esp),
            "kernel_sha256": digest(kernel),
            "data_seed_sha256": data_sha,
            "data_seed_reused_byte_identically": True,
            "changed_esp_members": sorted(changes),
            "lp_sip0": {"bytes": 8, "hex": asmb["lp-sip0"].hex(), "u64": 2},
            "boot_args_bytes": len(args_bytes),
            "disabled_plists": {path: {"entries": count, "uid": 0, "gid": 0, "mode": "0644"}
                                for path, count in policies.items()},
            "disabled_migrated": "unchanged zero-byte root:wheel 0644 file in byte-identical verified Data seed",
            "proc_top": "30-second reporter; split TOP1-TOP10; old single-line format absent",
            "hardware_tested": False,
        }
        args.out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
