#!/usr/bin/env python3
"""Check v33's real ESP, incremental objects and RAM Data before packaging boot."""
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
MEMBERS = {"B5qBootPolicy.o", "B5qProcTop.o"}
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
    p.add_argument("--esp", type=Path, help="Final physical ESP after the v30 loader is restored")
    a = p.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    esp = a.esp or a.ci / "esp.img"
    filesystem = load(Path(__file__).with_name("package-usb-dma-esp.py"))
    filesystem.image_format(esp)
    run("fsck.fat", "-n", esp)
    run(sys.executable, Path(__file__).with_name("verify-esp-log.py"),
        "--esp", esp, "--out", a.out / "log-allocation.json")

    link = json.loads((a.ci / "kernel/incremental-relink.json").read_text())
    assert link["core_translation_units_compiled"] == 0 and link["board_translation_units_compiled"] == 2
    assert not link["gpu_recompiled"] and not link["binder_objects_compiled"]
    for archive, before in link["input_archive_members"].items():
        assert digest(a.cache / "tree" / archive) == link["input_archives"][archive]
        if archive != DISPLAY:
            assert link["archive_outputs"][archive] == link["input_archives"][archive]
        if archive in link["output_archive_members"]:
            after = link["output_archive_members"][archive]
            assert set(after) == set(before) | ({"B5qProcTop.o"} if archive == DISPLAY else set())
            assert ({key for key in before if before[key] != after[key]} | (after.keys() - before.keys())) == (MEMBERS if archive == DISPLAY else set())
    for name, info in link["returned_objects"].items():
        obj = a.ci / "kernel/incremental-objects" / name
        assert digest(obj) == info["sha256"] == link["output_archive_members"][DISPLAY][info["archive_member"]]

    old = json.loads((ROOT / "artifacts/b5q-esp-runtime-v32/package.manifest.json").read_text())
    payload = json.loads((a.ci / "payload/payload.json").read_text())
    with tempfile.TemporaryDirectory(prefix="b5q-v33-verify-") as td:
        temp = Path(td)
        files = temp / "efi"
        members = filesystem.members(esp, files)
        new = {k: v for k, v in members.items() if k.startswith("EFI/")}
        assert set(new) == {name for name in old["esp_files"] if name.startswith("EFI/")}
        expected_changes = {filesystem.ADT,
                            "EFI/UniXNU/Payloads/kernel.macho", "EFI/UniXNU/Payloads/scratch-data.img",
                            "EFI/UniXNU/Payloads/kernel.macho.crypto-hmac.json", "EFI/UniXNU/Payloads/kernel.macho.trustcache"}
        assert {k for k, v in new.items() if v != old["esp_files"][k]} == expected_changes
        adt = filesystem.adt_nodes((files / filesystem.ADT).read_bytes())["/chosen"][2]
        assert all(adt[key] == bytes(size) for key, size in filesystem.PLACEHOLDERS.items())
        nodes = filesystem.adt_nodes((files / filesystem.ADT).read_bytes())
        assert nodes["/chosen/asmb"][2]["lp-sip0"] == struct.pack("<Q", 2)
        baseline_adt = subprocess.check_output(["mtype", "-i", str(ROOT / "artifacts/b5q-esp-runtime-v32/esp.img"), "::/" + filesystem.ADT])
        baseline_asmb = filesystem.adt_nodes(baseline_adt)["/chosen/asmb"][2]
        assert set(nodes["/chosen/asmb"][2]) == set(baseline_asmb)
        assert {k for k, v in nodes["/chosen/asmb"][2].items() if baseline_asmb[k] != v} == {"lp-sip0"}
        menu = tomllib.loads((files / "EFI/UniXNU/unixnu.toml").read_text())
        entry = next(item for item in menu["entry"] if item["type"] == "xnu")
        assert entry["args"] == " ".join(tomllib.loads((ROOT/"UniXNU-b5q/board.toml").read_text())["payload"]["kernel_args"])
        assert len(entry["args"].encode()) <= 950 and "offline-mobile-graphics-client=" not in entry["args"]
        assert adt["text-fixups"] == (b"dyld_shared_cache_arm64e.03,5de1134,08060037,1f2003d5\0"
                                     b"dyld_shared_cache_arm64e.03,5de63cc,1811981a,f803082a\0")
        assert (files / filesystem.DRIVER).read_bytes() == loader_pe(a.fd.read_bytes(), filesystem.LOADER)
        kernel = files / "EFI/UniXNU/Payloads/kernel.macho"
        kernel_sha = digest(kernel)
        assert kernel_sha == payload["payload_kernel_sha256"]
        for marker in (b"disabled11=%u selected=%02x", b"touch-mouse", b"HID mode=%s", b"DRP opcode=%02x", b"B5qProcTop: window=30s"):
            assert marker in kernel.read_bytes(), marker
        sys.path.insert(0, str(ROOT / "sources/UniXNU/kits/XnuPrelink"))
        from kc_image import Image
        outer = Image(kernel.read_bytes())
        core = Image(outer.data, outer.entries["com.apple.kernel"][1])
        names = {name: addr for addr, labels in core.symbols().items() for name in labels}
        builtin_policy = json.loads((ROOT/"UniXNU-b5q/package/B5qBootPolicy.c").read_text().splitlines()[-1].rstrip(";"))
        assert core.read(names["_PE_builtin_boot_args"], len(builtin_policy)+1) == builtin_policy.encode()+bytes(1)
        assert len(builtin_policy.split("deny-exec=")[1]) < 256
        assert "/usr/libexec/endpointsecurityd" not in builtin_policy

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
        requested = list(dict.fromkeys([*account.PATHS, *policy_paths, "private/var/ngpu/bin/b5q-absentd"]))
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
            assert overrides == (dict(labels) if isinstance(labels,dict) else dict.fromkeys(labels,True))
        assert (extracted / prefix / "disabled.migrated").stat().st_size == 0

        # Reuse the production signature verifier's functions without its CLI.
        import ast
        source = (ROOT/"scripts/b5q-install/verify-mount-runtime.py").read_text()
        funcs = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name in ("modules","codesign")]
        helpers = dict(struct=struct, hashlib=hashlib)
        exec(compile(ast.Module(body=funcs, type_ignores=[]), source, "exec"), helpers)
        stand_in = (extracted/"private/var/ngpu/bin/b5q-absentd").read_bytes()
        trust = helpers["modules"]((files/"EFI/UniXNU/Payloads/kernel.macho.trustcache").read_bytes())
        trusted = {m[i:i+20] for m in trust for i in range(24,len(m),24)}
        hashes = helpers["codesign"](stand_in)
        assert all(h in trusted for h in hashes)
        assert b"LaunchAgents" in stand_in and b"LaunchDaemons" in stand_in
        assert "com.apple.endpointsecurity.endpointsecurityd" not in policy.policies()["disabled.plist"]
        assert stats["private/var/ngpu/bin/b5q-absentd"]["mode"] == 0o100755
        original = subprocess.check_output(["mtype","-i",str(ROOT/"artifacts/b5q-esp-runtime-v32/esp.img"),
                                            "::/EFI/UniXNU/Payloads/kernel.macho.trustcache"])
        originals = helpers["modules"](original)
        assert trust[:-1] == originals and len(trust[-1]) == 48
        assert trust[-1][24:44] in hashes

        geometry = {"bytes": esp.stat().st_size, "sha256": digest(esp)}
        verification = {"kernel_sha256": kernel_sha, "seed_sha256": digest(seed),
                        "data_bytes": logical, "ESP": geometry, "members": new,
                        "launchd_overrides": {key: len(value) for key, value in policy.policies().items()},
                        "changed_archive_members": sorted(MEMBERS), "board_builtin_policy":builtin_policy,
                        "board_stand_in_cdhashes":[h.hex() for h in hashes], "hardware_tested": False,
                        "checks": ["FAT32 4Kn", "XNU2LOG allocation", "v30 physical ESP loader", "USB DMA ADT placeholders",
                                   "4 GiB APFS Data and launchd policy", "unchanged boot args and GPU addon", "native stand-in page signatures and trust", "POST seal"]}
    (a.out / "v33-verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps({k: v for k, v in verification.items() if k != "members"}, indent=2))


if __name__ == "__main__":
    main()
