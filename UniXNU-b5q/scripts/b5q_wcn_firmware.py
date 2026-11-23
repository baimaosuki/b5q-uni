"""Hash-locked original Samsung WCN inputs; no reference-board substitution."""
import hashlib,json,os,shutil
from pathlib import Path
DEVICE=Path(os.environ.get('UNIXNU_DEVICE',Path(__file__).resolve().parents[1])).resolve()
def stage(radio,out):
    if radio not in ('bluetooth','wifi'):raise ValueError('Unknown radio')
    manifest=json.loads((DEVICE/'reports/wcn-stock-firmware.json').read_text())
    source=Path(os.environ.get('B5Q_STOCK_WCN_FIRMWARE',DEVICE.parent/'artifacts/firmware-b5q/F7310ZCS7EYF3'))
    out=Path(out);out.mkdir(parents=True,exist_ok=True);files={}
    for key,entry in manifest['files'].items():
        group,name=key.split('/',1)
        if group!=radio:continue
        path=source/entry['source']
        if not path.is_file():raise FileNotFoundError('NEEDS_STOCK_FIRMWARE: '+str(path))
        data=path.read_bytes()
        if len(data)!=entry['bytes']or hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Original Samsung firmware identity mismatch: '+name)
        target=out/name;target.write_bytes(data);target.chmod(0o644);files[name]=entry
    if not files:raise ValueError('No original radio firmware in manifest')
    return files
