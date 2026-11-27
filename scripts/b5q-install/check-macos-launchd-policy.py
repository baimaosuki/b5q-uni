#!/usr/bin/env python3
"""Execute 26C5035r launchd's real file reader, lookup and SIP override gate.

Filesystem/libxpc calls are modelled at their import boundaries. PAC prologues
and authenticated returns are control-flow shims, not PAC validation. This is
an offline policy test and makes no claim about a device's launchd state.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "UniXNU/kits/XnuPrelink"))
from kc_image import Image
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as registers

SHA = "33cb5981d59aa60db3c27fd309a9aa95bf77ae1bef8369beffa3e9ba37f926bc"
MEM = 0x200000000
DICT, BOOL, TRUE, FALSE = [MEM + i for i in (0x10, 0x20, 0x30, 0x40)]
STACK, STOP = MEM + 0x3F000, MEM + 0xF00


class Machine:
    def __init__(self, raw, overrides, uid=0, mode=0o100644, gid=0, stat_rc=0):
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.raw, self.image = raw, Image(raw)
        for s in self.image.segments:
            if s["name"] == "__PAGEZERO" or not s["size"]:
                continue
            self.u.mem_map(s["va"], (s["size"] + 4095) & ~4095)
            self.u.mem_write(s["va"], raw[s["fileoff"]:s["fileoff"] + s["filesize"]])
        self.u.mem_map(MEM, 0x40000)
        self.objects, self.events, self.next_object = {}, [], MEM + 0x100
        self.uid, self.gid, self.mode, self.stat_rc = uid, gid, mode, stat_rc
        self.data = plistlib.dumps(overrides)
        self.object(overrides)
        self.q(0x100086D68, TRUE)
        self.q(0x100086D78, BOOL)
        self.q(0x100086D98, DICT)
        self.reg("sp", STACK)
        self.reg("lr", STOP)
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def reg(self, name, value=None):
        r = getattr(registers, "UC_ARM64_REG_" + name.upper())
        if value is not None:
            self.u.reg_write(r, value)
        return self.u.reg_read(r)

    def q(self, address, value):
        self.u.mem_write(address, struct.pack("<Q", value))

    def object(self, value):
        if value is None:
            return 0
        if value is True:
            return TRUE
        if value is False:
            return FALSE
        self.next_object += 0x10
        self.objects[self.next_object] = value
        return self.next_object

    def string(self, address):
        data = bytes(self.u.mem_read(address, 512))
        return data.split(b"\0", 1)[0].decode()

    def ret(self, result=0):
        self.reg("x0", result & ((1 << 64) - 1))
        self.reg("pc", self.reg("lr"))

    def hook(self, uc, pc, size, _):
        word = int.from_bytes(uc.mem_read(pc, 4), "little")
        if pc == 0x10005E6A4:  # open
            self.events.append(["open", self.string(self.reg("x0"))])
            self.ret(7)
        elif pc == 0x10005E054:  # fstat
            data = bytearray(144)
            struct.pack_into("<H", data, 4, self.mode)
            struct.pack_into("<II", data, 16, self.uid, self.gid)
            struct.pack_into("<Q", data, 96, len(self.data))
            uc.mem_write(self.reg("x1"), bytes(data))
            self.ret(self.stat_rc)
        elif pc == 0x100013FB0:  # allocation wrapper
            assert self.reg("x0") == len(self.data)
            self.ret(MEM + 0x8000)
        elif pc == 0x10005EBF4:  # read
            assert self.reg("x0") == 7 and self.reg("x2") == len(self.data)
            uc.mem_write(self.reg("x1"), self.data)
            self.ret(len(self.data))
        elif pc == 0x10005F484:  # xpc_create_from_plist_with_string_cache
            data = bytes(uc.mem_read(self.reg("x0"), self.reg("x1")))
            self.ret(self.object(plistlib.loads(data)))
        elif pc == 0x10005F724:  # xpc_get_type
            obj = self.reg("x0")
            self.ret(BOOL if obj in (TRUE, FALSE) else DICT if isinstance(self.objects.get(obj), dict) else 0)
        elif pc in (0x10005F624, 0x10005F594):  # xpc_dictionary_get_value/bool
            value = self.objects[self.reg("x0")].get(self.string(self.reg("x1")))
            self.ret(int(value is True) if pc == 0x10005F594 else self.object(value))
        elif pc == 0x10005F3A4:  # xpc_bool_get_value
            assert self.reg("x0") in (TRUE, FALSE)
            self.ret(int(self.reg("x0") == TRUE))
        elif pc == 0x10005F644:  # xpc_dictionary_set_bool
            self.objects[self.reg("x0")][self.string(self.reg("x1"))] = bool(self.reg("x2"))
            self.ret()
        elif pc in (0x10005E024, 0x10003D380):  # free, close wrapper
            self.ret()
        elif pc == 0x10002EDE0:  # override removal when SIP ignores the file
            self.events.append(["ignored override", self.string(self.reg("x1"))])
            self.ret()
        elif pc == 0x100015120:  # diagnostic logger
            self.events.append(["log", self.string(self.reg("x2"))])
            self.ret()
        elif pc == 0x10005CFB4:  # per-UID override record, filesystem already validated
            assert self.reg("w0") == 501
            self.ret(MEM + 0x17000)
        elif word in (0xD503237F, 0xD50323FF):  # PACIBSP/AUTIBSP: PAC tested separately.
            self.reg("pc", pc + 4)
        elif word == 0xD65F0FFF:  # RETAB
            self.reg("pc", self.reg("lr"))
        elif 0x10005D000 <= pc < 0x100060000:
            raise AssertionError(f"Unmodelled import at {pc:#x}")

    def run(self, start, end=STOP):
        self.u.emu_start(start, end, count=5000)
        assert self.reg("pc") == end, hex(self.reg("pc"))

    def load(self, path):
        self.u.mem_write(MEM + 0x1000, path.encode() + b"\0")
        self.reg("x0", MEM + 0x1000)
        self.run(0x10005BCF8)
        return self.reg("x0")

    def gate(self, loaded, label, sip, system, removable, default=False, protected=False, flags=None):
        self.reg("sp", STACK)
        self.reg("lr", STOP)
        self.q(MEM + 0x103A0, loaded)
        self.u.mem_write(MEM + 0x11000, label.encode() + b"\0")
        self.reg("x0", MEM + 0x10000)
        self.reg("x1", MEM + 0x11000)
        self.run(0x10002ED68)
        override = self.reg("x0")
        self.reg("x28", override)
        self.reg("x22", MEM + 0x10000)
        self.reg("x24", MEM + 0x11000)
        self.reg("x20", int(default))
        self.reg("x25", (0x100 if system else 0) if flags is None else flags)
        self.u.mem_write(STACK + 0x24, struct.pack("<II", 0, int(protected)))
        self.u.mem_write(0x100089AB8, bytes([sip]))
        self.q(0x10008AFA8, self.object(removable))
        self.run(0x100003E60, 0x100003F74)
        return bool(struct.unpack("<I", bytes(self.u.mem_read(STACK + 0x2C, 4)))[0])

    def uid_domain(self, loaded):
        """Execute the real UID-domain override assignment, not a guessed offset."""
        self.q(MEM + 0x10068, MEM + 0x18000)
        self.u.mem_write(MEM + 0x18080, b"\2")  # real type supports per-UID overrides
        self.q(MEM + 0x17018, loaded)
        self.reg("x19", MEM + 0x10000)
        self.reg("x21", 501)
        self.run(0x10002D74C, 0x10002D774)
        assert struct.unpack("<Q", bytes(self.u.mem_read(MEM + 0x103A0, 8)))[0] == loaded

    def disabled_rejection(self):
        # Default DisableAllowed bit is set by native object construction.
        self.reg("x22", MEM + 0x24000)
        self.run(0x1000052EC, 0x1000052F8)
        flags = self.u.mem_read(MEM + 0x24588, 4)
        assert int.from_bytes(flags, "little") & 2
        self.reg("x23", MEM + 0x24000)
        self.reg("w20", 1)
        self.run(0x1000043B0, 0x10000449C)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--launchd", type=Path, required=True)
    p.add_argument("--rootless", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--policy", type=Path, help="Validate all actual final board labels, including nested bundles")
    a = p.parse_args()
    fat = a.launchd.read_bytes()
    assert hashlib.sha256(fat).hexdigest() == SHA, "Requires actual macOS 26C5035r launchd"
    assert fat[:4] == bytes.fromhex("cafebabe")
    cpu, sub, offset, size, _ = struct.unpack_from(">IIIII", fat, 8)
    assert (cpu, sub) == (0x100000C, 0x80000002)
    raw = fat[offset:offset + size]
    removable = plistlib.loads(a.rootless.read_bytes())["RemovableServices"]
    cases = []
    for path in ("disabled.plist", "disabled.501.plist"):
        for uid, mode, gid, rc, accepted in ((0, 0o100644, 0, 0, True),
                                          (501, 0o100644, 0, 0, False),
                                          (0, 0o100664, 0, 0, False),
                                          (0, 0o100646, 0, 0, False),
                                          (0, 0o100600, 501, 0, True),
                                          (0, 0o100644, 0, -1, False)):
            m = Machine(raw, {"com.apple.watchdogd": True}, uid, mode, gid, rc)
            loaded = m.load("/private/var/db/com.apple.xpc.launchd/" + path)
            assert bool(loaded) == accepted
            cases.append(dict(case="secure reader", path=path, uid=uid, gid=gid, mode=oct(mode), fstat=rc, accepted=accepted))
    for sip, system, label, expected in ((1, True, "com.apple.watchdogd", False),
                                         (0, True, "com.apple.watchdogd", True),
                                         (1, True, "com.apple.ReportCrash", True),
                                         (1, False, "com.apple.watchdogd", True),
                                         (0, True, "com.apple.untargeted", False)):
        m = Machine(raw, {"com.apple.watchdogd": True, "com.apple.ReportCrash": True})
        loaded = m.load("/private/var/db/com.apple.xpc.launchd/disabled.plist")
        disabled = m.gate(loaded, label, sip, system, removable)
        assert disabled == expected, (sip, system, label, disabled, m.events)
        cases.append(dict(case="job gate", sip=sip, system_import=system, label=label, disabled=disabled, events=m.events))
    for rc, end in ((0, 0x100048B10), (-1, 0x1000488D8)):
        m = Machine(raw, {})
        m.reg("w0", rc & 0xFFFFFFFF)
        m.run(0x1000488D4, end)
        cases.append(dict(case="migration marker stat branch", stat=rc, next_pc=hex(end), current_policy_still_loaded=True))
    if a.policy:
        policy = json.loads(a.policy.read_text())
        for group in ("system", "gui", "bundled"):
            for label in policy[group]:
                m = Machine(raw, {label: True})
                filename = "disabled.plist" if group == "system" else "disabled.501.plist"
                loaded = m.load("/private/var/db/com.apple.xpc.launchd/" + filename)
                if group != "system":
                    m.uid_domain(loaded)
                flags = 0x100 if group == "system" else 0x280
                assert m.gate(loaded, label, 0, group == "system", removable, flags=flags)
                m.disabled_rejection()
                cases.append(dict(case="actual board policy", group=group, label=label, file=filename,
                    import_flags=hex(flags), disabled=True, DisableAllowed_default=True,
                    native_disabled_rejection="0x10000449c", uid_domain_assignment=group != "system"))
        for label in policy.get("system_enabled", []):
            m = Machine(raw, {label: False})
            loaded = m.load("/private/var/db/com.apple.xpc.launchd/disabled.plist")
            assert not m.gate(loaded,label,0,True,removable,default=True,flags=0x100)
            cases.append(dict(case="explicit enabled system override",label=label,disabled=False,plist_default_disabled=True))
        for label in ("com.apple.WindowServer", "com.apple.loginwindow", "com.apple.Dock.agent", "com.apple.Finder"):
            merged = dict.fromkeys(sum([v for k,v in policy.items() if k != "system_enabled"], []), True)
            merged.update(dict.fromkeys(policy.get("system_enabled", []), False))
            m = Machine(raw, merged)
            loaded = m.load("/private/var/db/com.apple.xpc.launchd/disabled.plist")
            assert not m.gate(loaded, label, 0, True, removable)
            cases.append(dict(case="protected desktop exclusion", label=label, disabled=False))
        root = a.launchd.parent.parent
        for domain, label in [("LaunchDaemons", "com.apple.mobileactivationd"), ("LaunchDaemons", "com.apple.security.cryptexd"),
                              ("LaunchDaemons", "com.apple.AirPlayXPCHelper"), ("LaunchDaemons", "com.apple.rtcreportingd"),
                              ("LaunchAgents", "com.apple.talagent")]:
            job = plistlib.loads((root / "System/Library" / domain / (label + ".plist")).read_bytes())
            m = Machine(raw, {})
            obj = m.object(job.copy())
            m.reg("x19", obj); m.reg("x24", obj); m.reg("w21", 0)
            m.run(0x100005A18, 0x100005B74)
            assert m.objects[obj]["EnablePressuredExit"] is True and m.reg("w2") == 1
            cases.append(dict(case="real job transaction normalization", label=label,
                input_EnableTransactions=job.get("EnableTransactions"), effective_EnableTransactions=True,
                effective_EnablePressuredExit=True, native_function="0x100005a18..0x100005b74"))
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(dict(launchd_sha256=SHA, thin_sha256=hashlib.sha256(raw).hexdigest(),
        rootless_sha256=hashlib.sha256(a.rootless.read_bytes()).hexdigest(), cases=cases,
        substituted="Filesystem, allocator and libxpc import APIs; PAC prologues/returns are control-flow shims",
        hardware_verified=False), indent=2) + "\n")
    print(f"PASS: {len(cases)} real macOS launchd instruction cases; explicit OS API/PAC shims; no device claim")


if __name__ == "__main__":
    main()
