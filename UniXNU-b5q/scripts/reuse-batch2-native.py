#!/usr/bin/env python3
"""Reuse the completed six-object Batch2 link when all compiler inputs match."""
import argparse,hashlib,json,sys
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True);p.add_argument('--source-run',type=int,required=True);a=p.parse_args()
sys.path.insert(0,str(a.unixnu.resolve()/'scripts'));sys.path.insert(0,str(a.device.resolve()/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from importlib.machinery import SourceFileLoader
relink=SourceFileLoader('batch2_relink',str(a.device/'scripts/relink-b5q-peripherals.py')).load_module()
ctx=Context(parser().parse_args(['build','payload','--device',str(a.device),'--os','macos-27.3-26C5035r']))
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
try:
 record=ctx.work/'kernel/incremental-relink.json';r=json.loads(record.read_text())
 assert r['relink_version']=='batch2' and r['board_translation_units_compiled']==6 and r['core_translation_units_compiled']==0
 current={str(p.relative_to(a.device/'package')):sha(p)for p in (a.device/'package').rglob('*')if p.is_file()and p.suffix in ('.c','.cpp','.h')}
 assert current==r['source_sha256']
 for n,v in r['recipe_sha256'].items():assert sha(a.device/'scripts'/n)==v
 for n,v in r['archive_outputs'].items():assert sha(ctx.tree/n)==v
 assert sha(ctx.tree/relink.NATIVE)==r['native_output_sha256']
 k=json.loads((ctx.work/'kernel/kernel.json').read_text());assert k['inputs']['native_sha256']==r['native_output_sha256']
 assert sha(ctx.work/'kernel/kernel.macho')==k['candidate_sha256']
 for n,v in r['returned_objects'].items():assert sha(ctx.work/'kernel/incremental-objects'/n)==v['sha256']
 r['completed_relink_reused_from_CI']=a.source_run;r['board_objects_compiled_this_run']=0
 record.write_text(json.dumps(r,indent=2)+'\n')
 print('Reused completed Batch2 native+prelink; 0 board/core/GPU objects recompiled; source and all archive hashes match')
except (OSError,KeyError,ValueError,AssertionError)as e:
 print('Completed native cache unavailable/mismatched:',type(e).__name__);raise SystemExit(1)
