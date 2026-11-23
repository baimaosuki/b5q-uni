#!/usr/bin/env python3
"""Retain the installed ADTs after proving only generated entropy differs."""
import argparse,hashlib,importlib.util,json,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ['esp','baseline','out']:p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();s=importlib.util.spec_from_file_location('fat',R/'scripts/b5q-install/package-usb-dma-esp.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 before=sha(a.esp);changes={}
 with tempfile.TemporaryDirectory(prefix='b5q-retain-ADT-')as td:
  t=Path(td)
  for profile in ('','RAM/'):
   old,new=t/'old.adt',t/'new.adt';member='::/EFI/UniXNU/Payloads/'+profile+'kernel.macho.adt'
   for esp,dest in ((a.baseline,old),(a.esp,new)):subprocess.run(['mcopy','-o','-i',str(esp),member,str(dest)],check=True)
   x,y=m.adt_nodes(old.read_bytes()),m.adt_nodes(new.read_bytes());assert set(x)==set(y)
   diff=[]
   for node in x:
    left,right=x[node][2],y[node][2];assert set(left)==set(right)
    for prop in left:
     if left[prop]!=right[prop]:
      assert node=='/chosen'and prop in ('random-seed','unique-chip-id')
      assert len(left[prop])==len(right[prop])==(256 if prop=='random-seed'else 8)
      diff.append(prop)
   changes[profile or'normal']=dict(generated_properties_replaced=diff,retained_ADT_SHA256=sha(old))
   subprocess.run(['mcopy','-o','-i',str(a.esp),str(old),member],check=True)
  result=dict(CI_ESP_SHA256=before,final_ESP_SHA256=sha(a.esp),operation='Restore byte-identical previous ADTs after validating only generated entropy differed; no recompilation',profiles=changes)
 a.out.write_text(json.dumps(result,indent=2)+'\n');print('Retained original normal/RAM ADTs; no hardware/argument changes')
if __name__=='__main__':main()
