#!/usr/bin/env python3
"""Validate every production CTA translation against the pinned source table."""
from pathlib import Path
import hashlib,json,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2];rec=json.loads((R/'UniXNU-b5q/reports/p5-cta-source.json').read_text())
src=R/'artifacts/b5q-p5-work/source-extra/drivers/gpu/drm/drm_edid.c'
assert hashlib.sha256(src.read_bytes()).hexdigest()==rec['source_sha256']
source=src.read_text().split('static const struct drm_display_mode edid_cea_modes_1[] = {',1)[1].split('\n};',1)[0]
rows=[]
for i,m in enumerate(re.finditer(r'DRM_MODE\("[^"]*",\s*DRM_MODE_TYPE_DRIVER,\s*(.*?)\)',source,re.S),1):
 a=[x.strip()for x in m[1].split(',')];nums=list(map(int,a[:11]));clock,w,hs,he,ht,_,h,vs,ve,vt,_=nums;flags=a[11]
 if any(x in flags for x in ['INTERLACE','DBLCLK','DBLSCAN'])or clock>675000 or w>7680 or h>4320:continue
 rows.append('{'+','.join(map(str,[i,clock,w,h,ht-w,vt-h,hs-w,he-hs,vs-h,ve-vs,int('PHSYNC'in flags),int('PVSYNC'in flags)]))+'}')
h=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include "B5qDpModes.h"
using namespace B5qDp;
const CtaTiming expected[]={ROWS};
void checksum(uint8_t *e){e[127]=0;unsigned n=0;for(unsigned i=0;i<127;i++)n+=e[i];e[127]=uint8_t(0-n);}
void base(uint8_t *e){memset(e,0,256);const uint8_t magic[]={0,255,255,255,255,255,255,0};memcpy(e,magic,8);e[18]=1;e[19]=4;e[20]=128;e[126]=1;checksum(e);e[128]=2;e[129]=3;e[130]=6;e[132]=(2<<5)|1;}
int main(){unsigned count=0;
 for(const auto &v:expected){
  uint8_t e[256];base(e);e[133]=v.vic;checksum(e+128);Modes m;assert(m.parse(e,256)&&m.count==1);
  const auto &a=m.values[0];assert(a.valid()&&a.pixelKHz==v.pixelKHz&&a.width==v.width&&a.height==v.height&&a.hBlank==v.hBlank&&a.vBlank==v.vBlank&&a.hFront==v.hFront&&a.hSync==v.hSync&&a.vFront==v.vFront&&a.vSync==v.vSync&&a.hPositive==v.hPositive&&a.vPositive==v.vPositive);count++;
 }
 for(unsigned v=1;v<128;v++){bool supported=false;for(const auto &m:expected)if(m.vic==v)supported=true;
  uint8_t e[256];base(e);e[133]=v;checksum(e+128);Modes m;assert(m.parse(e,256)==supported);
 }
 {uint8_t e[256];base(e);e[130]=7;e[132]=(7<<5)|2;e[133]=0x0e;e[134]=97;checksum(e+128);Modes m;assert(!m.parse(e,256));}
 {uint8_t e[256];base(e);e[133]=97;checksum(e+128);Modes m;assert(m.parse(e,256));const auto &a=m.values[0];assert(a.width==3840&&a.height==2160&&a.pixelKHz==594000&&a.refreshMilliHz()==60000);assert(a.fits(4,20)&&!a.fits(2,20));}
 printf("PASS CTA94originaltimings/127VICs/4K60advertisement/RGB-YUV420isolation ASanUBSan count=%u\n",count);
}
'''.replace('ROWS',','.join(rows))
with tempfile.TemporaryDirectory(prefix='b5q-dp-cta-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
