"""Pinned shared Bluetooth sources with a board-only WCN6855 selection.

Never edit the locked Linux sources or compile the upstream DMA backend.
The full kernel recipe and local target check consume this same source list.
"""
import hashlib,json,subprocess,sys
from pathlib import Path

REVISION='effe4ec5c57cd400a5f818b21c9903fef237edbc'

def prepare(component,package,soc,out,reference):
    component,package,soc,out,reference=map(Path,(component,package,soc,out,reference))
    out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','-C',str(component),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION:raise ValueError('QcaBluetooth component revision changed: '+revision)
    subprocess.run([sys.executable,str(component/'tools/prepare-linux.py')],check=True)
    upstream=component/'src/qbt_linux.c';text=upstream.read_text()
    if text.count('QCA_WCN7850')!=2:raise ValueError('Shared QCA startup selection ABI changed')
    selected=out/'qbt_linux.c';selected.write_text(text.replace('QCA_WCN7850','QCA_WCN6855'))
    sources=[package/n for n in ('B5qBluetooth.cpp','B5qBtFifo.c','B5qWcnPower.cpp','BluetoothFirmware.c')]
    sources += [component/n for n in ('src/qbt_core.c','src/qbt_tty.c','out/linux/btqca.c')]
    sources += [selected,soc/'Sm8550GeniUart.c']
    report=dict(status='SOURCE_PREPARED',hardware_verified=False,component_revision=revision,
        original_adapter_sha256=hashlib.sha256(upstream.read_bytes()).hexdigest(),selection='QCA_WCN6855',
        transport='Samsung GENI FIFO; no DMA backend',
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (out/'sources.json').write_text(json.dumps(report,indent=2)+'\n')
    return sources,[component/n for n in ('include','src','shim','out/linux')]+[reference/'package']
