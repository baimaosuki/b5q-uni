#!/usr/bin/env python3
"""Compare original compiler-rt audio 128-bit division with Python integer truth."""
from pathlib import Path
import json,hashlib,random,subprocess,tempfile
R=Path(__file__).resolve().parents[2];source=R/'UniXNU-b5q/package/B5qAudioMath';r=json.loads((source/'source.json').read_text())
for name,sha in r['unchanged_sources'].items():assert hashlib.sha256((source/name).read_bytes()).hexdigest()==sha
randomizer=random.Random(8550);values=[0,1,2,3,(1<<32)-1,1<<32,(1<<64)-1,1<<64,(1<<127)-1,1<<127,(1<<128)-1]
pairs=[(a,b)for a in values for b in values if b]+[(randomizer.getrandbits(128),randomizer.getrandbits(128)or 1)for _ in range(4096)]
def limbs(n):return str(n>>64)+'ULL,'+str(n&((1<<64)-1))+'ULL'
rows=['{'+','.join([limbs(a),limbs(b),limbs(a//b),limbs(a%b)])+'}'for a,b in pairs]
code=r'''
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
typedef unsigned __int128 wide;
extern wide __udivti3(wide,wide);
extern wide __udivmodti4(wide,wide,wide*);
struct Case{uint64_t ah,al,bh,bl,qh,ql,rh,rl;};
static struct Case cases[]={ROWS};
int main(void){for(unsigned i=0;i<sizeof(cases)/sizeof(cases[0]);i++){
 struct Case c=cases[i];wide a=(wide)c.ah<<64|c.al,b=(wide)c.bh<<64|c.bl,q=(wide)c.qh<<64|c.ql,r=(wide)c.rh<<64|c.rl,out=0;
 assert(__udivti3(a,b)==q&&__udivmodti4(a,b,&out)==q&&out==r);
}printf("PASS original compiler-rt unsigned128 division/remainder: %zu independent Python edge/randomvectors underASanUBSan\n",sizeof(cases)/sizeof(cases[0]));}
'''.replace('ROWS',','.join(rows))
with tempfile.TemporaryDirectory(prefix='b5q-audio-math-')as td:
 td=Path(td);(td/'test.c').write_text(code)
 subprocess.run(['cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(td/'test.c'),str(source/'udivti3.c'),str(source/'udivmodti4.c'),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test')],check=True)
