#!/usr/bin/env python3
"""Exercise production EDID bounds,DTD timing and link bandwidth decisions."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstring>
#include <cstdio>
#include <random>
#include "B5qDpModes.h"
static void checksum(uint8_t *e){e[127]=0;uint8_t n=0;for(unsigned i=0;i<127;i++)n+=e[i];e[127]=uint8_t(-n);}
int main(){uint8_t e[256]={0};const uint8_t header[]={0,255,255,255,255,255,255,0};memcpy(e,header,8);e[18]=1;e[19]=4;e[20]=128;
 const uint8_t fullhd[]={0x02,0x3a,0x80,0x18,0x71,0x38,0x2d,0x40,0x58,0x2c,0x45,0x00,0xfd,0x1e,0x11,0,0,0x1e};memcpy(e+54,fullhd,18);checksum(e);
 B5qDp::Modes m;assert(m.parse(e,128)&&m.count==1);const auto &v=m.values[0];assert(v.width==1920&&v.height==1080&&v.hBlank==280&&v.vBlank==45&&v.hFront==88&&v.hSync==44&&v.vFront==4&&v.vSync==5&&v.pixelKHz==148500&&v.refreshMilliHz()==60000);
 assert(v.fits(4,6)&&!v.fits(2,6)&&v.fits(2,10)&&!v.fits(3,10)&&!v.fits(2,9));assert(m.best(4,6)&&!m.best(2,6));
 for(unsigned n=0;n<128;n++){e[n]^=1;B5qDp::Modes bad;assert(!bad.parse(e,128));e[n]^=1;}
 for(size_t n=0;n<128;n++){B5qDp::Modes bad;assert(!bad.parse(e,n));}
 e[126]=1;checksum(e);e[128]=2;e[129]=3;e[130]=4;memcpy(e+132,fullhd,18);checksum(e+128);assert(m.parse(e,256)&&m.count==1);
 e[130]=3;checksum(e+128);assert(!m.parse(e,256));e[130]=8;e[132]=0x1f;checksum(e+128);assert(!m.parse(e,256));e[130]=4;e[132]=0;checksum(e+128);
 assert(!m.parse(e,128)&&!m.parse(nullptr,256));
 std::mt19937 rng(0x8550);for(unsigned trial=0;trial<100000;trial++){uint8_t bytes[1024];for(auto &b:bytes)b=uint8_t(rng());B5qDp::Modes f;bool ok=f.parse(bytes,rng()%1025);if(ok)for(unsigned i=0;i<f.count;i++)assert(f.values[i].valid());}
 puts("PASS productionDPmodes:128checksumfaults/alltruncations/CTAoverrun/1080p60DTDandbandwidth/100000randomEDIDbounds ASanUBSan");}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-modes-')as td:
 t=Path(td);(t/'test.cpp').write_text(h);subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
