#!/usr/bin/env python3
"""Verify the selected USB ownership and retained platform modules in the actual FD."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "UniXNU/scripts"))
from unixnu.boot_template import compressed_volume, fv_files, loader_pe, sections

BANNED = {
    "UsbConfigDxe", "UsbInitDxe", "UsbDeviceDxe", "UsbfnDwc3Dxe", "UsbPwrCtrlDxe",
    "XhciPciEmulation", "XhciDxe", "UsbBusDxe", "UsbKbDxe", "UsbMassStorageDxe",
    "UFSDxe", "SdccDxe", "UsbMsdDxe", "PILDxe", "PILProxyDxe", "SPSSDxe",
}
REQUIRED = {"B5qHandoffDxe", "DarwinBoot", "HALIOMMU", "DisplayDxe", "ButtonsDxe",
            "RpmhDxe", "CmdDbDxe", "RamManagerDxe"}
REMOVED_PROTOCOLS = {UUID(x).bytes_le for x in (
    "e722b03f-b250-42ce-8ebd-5bd51812d037",  # UsbConfigDxe InstallMultipleProtocolInterfaces
    "d9d9ce48-44b8-4f49-8e3a-2a3b92d17dc1",  # UsbDevice
    "32d2963a-fe5d-4f30-b633-6e5dc55803cc",  # UsbfnIo
)}


def inventory(fd):
    result = {}
    for _, guid, ffs in fv_files(compressed_volume(fd)[4], 8)[2]:
        if ffs[18] in (1, 0xf0):
            continue
        name = None
        deps = []
        for _, kind, data in sections(ffs, 24, len(ffs)):
            if kind == 0x15:
                name = data[4:].decode("utf-16le").rstrip("\0")
            elif kind == 0x13:
                opcodes = data[4:]
                at = 0
                while at < len(opcodes):
                    opcode = opcodes[at]
                    at += 1
                    assert opcode <= 9, (guid, opcode)
                    if opcode in (0, 1, 2):
                        value = opcodes[at:at + 16]
                        assert len(value) == 16
                        deps.append(value)
                        at += 16
                    if opcode == 8:
                        break
                assert at == len(opcodes)
        result[guid] = (name, deps)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fd", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    fd = a.fd.read_bytes()
    modules = inventory(fd)
    names = {name for name, _ in modules.values() if name}
    assert REQUIRED <= names and not BANNED & names, (REQUIRED - names, BANNED & names)
    assert all(not (REMOVED_PROTOCOLS & set(deps)) for _, deps in modules.values())
    handoff = loader_pe(fd, "f8a45ce9-92de-48cc-8e19-e97c28b724a0")
    darwin = loader_pe(fd, "1b64af87-8415-4b57-9b16-680d70913b9f")
    hal = loader_pe(fd, "9a00771f-36d4-4dd5-8916-c48ed9b16b86")
    assert b"B5Q-USBDMA: locate=" in handoff
    assert b"b5q-usb-dma-diagnostics" in darwin
    assert hashlib.sha256(hal).hexdigest() == "a6020ff87c4526baf9f8cb39870e618691a83cf5ecb8ae4cd1e9e1d42ed9c2ef"
    result = {"result": "PASS", "firmware_sha256": hashlib.sha256(fd).hexdigest(),
              "handoff_sha256": hashlib.sha256(handoff).hexdigest(), "darwinboot_sha256": hashlib.sha256(darwin).hexdigest(),
              "retained": sorted(REQUIRED), "excluded": sorted(BANNED), "firmware_module_count": len(modules),
              "compiled_depex_checked": sum(bool(deps) for _, deps in modules.values())}
    a.out.write_text(json.dumps(result, indent=2) + "\n")
    print("PASS actual FV modules, retained DEPEX, and firmware USB DMA markers")


if __name__ == "__main__":
    main()
