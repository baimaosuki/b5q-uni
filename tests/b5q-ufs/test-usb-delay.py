"""Ensure USB is started by the display-ready peripheral flow without an artificial timer."""
from pathlib import Path
root=Path(__file__).resolve().parents[2];s=(root/'UniXNU-b5q/package/UsbProbe.cpp').read_text();worker=s[s.index('static void worker('):]
prefix=worker[:worker.index('qcom_dwc3_bring_up(')]
assert 'IOSleep(' not in prefix and 'b5q-usb-delay' not in s and 'delaySec' not in s
s=(root/'UniXNU-b5q/package/LegacyDisplayProbe.cpp').read_text();worker=s[s.index('void b5qPeripheralWorker('):s.index('void startB5qPeripherals(')]
assert worker.index('sheng_dpu_probe();')<worker.index('sheng_usb_probe();')
late=s[s.index('void native_legacy_display_late_probe(void) {'):];assert 'sheng_usb_probe();' not in late
assert 'startB5qPeripherals();return;' in late
print('PASS USB starts in successful post-display peripheral flow after DPU;no35s artificialworker delay or early late_probe USB call')
