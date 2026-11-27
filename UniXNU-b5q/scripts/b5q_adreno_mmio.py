"""Explicit cache selection for the shared register-only GMU service."""
from pathlib import Path
def prepare(source,destination):
 source,destination=map(Path,(source,destination));text=source.read_text()
 old='memory->map(kIOMapAnywhere)';assert text.count(old)==1,'Pinned GMU source changed'
 destination.parent.mkdir(parents=True,exist_ok=True)
 destination.write_text(text.replace(old,'memory->map(kIOMapAnywhere|kIOMapInhibitCache)'))
 return destination

def source_identity(root):
 """All upstream GPU translation units and headers, including shared ABI kits."""
 import hashlib
 root=Path(root);digest=hashlib.sha256()
 for folder in ['drivers/Adreno740','kits/AdrenoPM4','kits/ArmSmmu4K','kits/AdrenoFirmware','kits/Sm8550Platform']:
  for p in sorted((root/folder).rglob('*')):
   if p.is_file() and '.git' not in p.parts and p.suffix in ('.c','.cpp','.h','.inc'):
    digest.update(str(p.relative_to(root)).encode());digest.update(p.read_bytes())
 return digest.hexdigest()
