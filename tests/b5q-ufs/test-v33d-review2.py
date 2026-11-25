#!/usr/bin/env python3
"""Production-path regressions for the second v33d review; ASan/UBSan."""
from pathlib import Path
import ast,hashlib,json,re,subprocess,tempfile,os,sys
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
def function(s,sig):
 a=s.index(sig);b=s.index('{',a);end=b+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[a:end]
def run(name,body):
 with tempfile.TemporaryDirectory(prefix='b5q-review2-'+name+'-')as td:
  t=Path(td);src=t/'test.cpp';src.write_text(body)
  subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-misleading-indentation','-Wno-missing-field-initializers','-fsanitize=address,undefined','-pthread','-I'+str(P),'-I'+str(R/'sources/UniXNU-sheng/package'),str(src),'-o',str(t/'test')],check=True)
  subprocess.run([str(t/'test')],check=True)
base='#include <cassert>\n#include <cstdint>\n#include <cstdio>\n#include <cstring>\n#include <vector>\n#include <map>\n#include <deque>\n'
run('BCM-ARC',base+r'''
#include "QcomRpmh.c"
int main(){uint8_t db[512]={};auto p16=[&](unsigned at,unsigned n){db[at]=n;db[at+1]=n>>8;};
 auto p32=[&](unsigned at,unsigned n){p16(at,n);p16(at+2,n>>16);};
 p32(4,QCOM_CMD_DB_MAGIC);p16(8,5);p16(10,0);p16(12,24);p16(14,1);memcpy(db+144,"SN7",3);
 p32(160,0x50100);p16(164,8);p16(168,1000);p16(170,0);p16(172,16);p16(174,0);
 QcomRpmhResource r{};assert(!qcom_cmd_db_find(db,sizeof(db),"SN7",&r));assert(r.level_count==4&&r.levels[0]==1000&&r.levels[1]==0&&r.levels[2]==16);
 p16(8,3);assert(!qcom_cmd_db_find(db,sizeof(db),"SN7",&r)&&r.level_count==1);
 puts("PASS actual cmd-db:BCM unit1000/highword0 preserves width16 and4words; ARC padding still truncates");}
''')
run('GENI-errors',base+r'''
#include "GeniI2c.c"
struct Bus{std::map<unsigned,unsigned>reg;std::deque<unsigned>fifo;unsigned drains=0;
 static uint32_t read(void*c,uint32_t r){auto &b=*(Bus*)c;if(r==GENI_RX_FIFO_STATUS)return b.fifo.size();if(r==GENI_RX_FIFO){assert(!b.fifo.empty());auto v=b.fifo.front();b.fifo.pop_front();b.drains++;return v;}return b.reg[r];}
 static void write(void*c,uint32_t r,uint32_t v){auto &b=*(Bus*)c;b.reg[r]=v;}
};
int main(){for(unsigned timeout:{0u,1u}){
 Bus b;GeniI2c g{};g.io={Bus::read,Bus::write,&b};g.phase=GeniReadDone;g.rx_fifo_words=16;g.reading=1;b.fifo={1,2,3};
 assert(!g.rx_buffer);
 if(!timeout){assert(geni_i2c_event(&g,GENI_M_GP_IRQ)==GeniPending&&g.phase==GeniReadDone&&!b.drains);assert(geni_i2c_event(&g,GENI_M_CMD_DONE)==GeniFailed&&g.error==GeniErrBus);}
 else{geni_i2c_timeout(&g);assert(g.phase==GeniCancelling&&!b.drains);assert(geni_i2c_event(&g,GENI_M_CMD_CANCEL)==GeniFailed);}
 assert(b.fifo.empty()&&b.drains==3&&g.phase==GeniIdle);
 }
 Bus b;GeniI2c g{};g.io={Bus::read,Bus::write,&b};g.rx_fifo_words=16;uint8_t bytes[8];assert(!geni_i2c_start_read_only(&g,bytes,8));assert(b.reg[GENI_RX_RFR_WATERMARK]==14);
 puts("PASS actual GENI:scalar NACK latches untilDONE; error/timeout drains RX withnullbuffer; RFRdepth-2");}
''')
run('Touch-protocol-identify',base+r'''
#include "B5qTouchProtocol.h"
using namespace B5qTouch;
int terminated=0,reportsSeen=0;uint8_t message[4096],config[512];size_t configBytes;unsigned maxObjects;
struct TouchBus{std::deque<unsigned>codes;bool write(uint8_t*,unsigned){return true;}int error(){return 0;}int stopError(){return 0;}};
namespace B5qTouchBus{const char*name(int){return "ok";}}
void IOLog(const char*,...){}void IOSleep(unsigned){}bool lowAttention(){return true;}
bool packet(TouchBus &b,uint8_t &code,unsigned &n){if(b.codes.empty())return false;code=b.codes.front();b.codes.pop_front();message[1]=1;n=2;return true;}
void report(uint8_t,unsigned){reportsSeen++;}
COMMAND
int main(){TouchBus bus;bus.codes={0x10};assert(command(bus,2,nullptr,0)&&bus.codes.empty());bus.codes={1};assert(command(bus,2,nullptr,0)&&bus.codes.empty());assert(!reportsSeen);
 Point points[12]={};points[2]={100,200,1};uint8_t record[16]={};
 for(unsigned eid=1;eid<4;eid++){record[0]=uint8_t((15<<2)|eid);assert(sec(record,16,points)&&points[2].kind==1&&points[2].x==100);}
 record[0]=uint8_t(2<<2);assert(sec(record,16,points)&&!points[2].kind);
 puts("PASS actual TouchComm:10or01identify accepted; C1eid1/2/3 skipwithoutclearinglivecontacts");}
'''.replace('COMMAND',function((P/'B5qTouch.cpp').read_text(),'bool command(')))
# No SMC executes on the host: retain and execute the production return expression.
psci=function((P/'B5qPower.cpp').read_text(),'static int64_t b5qPsci(')
expr=re.search(r'return (.*?);',psci)[1]
run('SMC32',base+'int64_t decode(uint64_t x0){return '+expr+';}\nint main(){assert(decode(0x00000000ffffffffULL)==-1);assert(decode(0xfffffffffffffffeULL)==-2);assert(decode(0x10000)==0x10000);puts("PASS actual PSCI SMC32return:zero-extendedffffffff becomes-1");}\n')
# Parse the actual HID global items, including Push/Pop, rather than compare bytes.
header=(P/'B5qMouseReport.h').read_text();items=header[header.index('mouseDescriptor[]={')+len('mouseDescriptor[]={'):header.index('};')];items=re.sub(r'//[^\n]*','',items);data=bytes(int(n,0)for n in re.findall(r'0x[0-9a-fA-F]+|\b\d+\b',items));g={};stack=[];local=[];xy=False;wheel=False
forbidden=[];i=0
while i<len(data):
 key=data[i];i+=1;n=key&3;n=4 if n==3 else n;v=int.from_bytes(data[i:i+n],'little');signed=int.from_bytes(data[i:i+n],'little',signed=True)if n else 0;i+=n;tag=key&0xfc
 if tag==0xa4:stack.append(dict(g))
 elif tag==0xb4:g=stack.pop()
 elif tag in [0x04,0x14,0x24,0x34,0x44,0x54,0x64,0x74,0x84,0x94]:g[tag]=signed if tag in [0x14,0x34,0x44]else v
 elif tag==0x08:local.append(v)
 elif tag==0x80:
  if 0x30 in local and 0x31 in local:
   exp=g[0x54]&15;exp=exp-16 if exp&8 else exp;cpi=32767/(g[0x44]*10**exp);assert abs(cpi/900-1)<0.02 and g[0x34]==-g[0x44];xy=True
  if 0x38 in local:assert g.get(0x64,0)==0 and g.get(0x54,0)==0;wheel=True
  local=[]
 elif tag==0xa0:local=[]
assert xy and wheel and not stack
print('PASS actual HID physical dimensions:899.945CPI(<2%error),XYunits isolated fromwheel')
# Required immutable source contracts, tied to exact production functions.
q=(P/'QcomDwc3.cpp').read_text();usb=(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/UsbDma.c').read_text();loader=(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_text()
assert 'OSData::withBytes(kConfigString,sizeof(kConfigString))'in q and 'setProperty("configuration-string",config)'in q
assert not re.search(r'setProperty\("configuration-string",\s*"',q)
assert 'AllocatePool'not in function(usb,'BuildUsbTables (')and 'FreePool'not in function(usb,'BuildUsbTables (')
assert loader.index('GetUsbDmaResult (')>max(loader.index(x)for x in ['GetPcieDmaResult (','GetMediaDmaResult(','GetDpDmaResult('])
assert loader.index('GetUsbDmaResult (')>loader.index('Status = GetMap (',loader.index('GetDpDmaResult('))
assert '(UsbAdt.Ready == MAX_UINTN)'in loader
before=R/'artifacts/b5q-v33d-review2/before';import tomllib
current=tomllib.loads((P.parent/'board.toml').read_text());prior=tomllib.loads((before/'UniXNU-b5q/board.toml').read_text())
assert current['adt']['chosen']['bytes'].pop('b5q-usb-dma-diagnostics')=='00'*64
prior['adt']['chosen']['bytes'].pop('b5q-usb-dma-diagnostics');assert current==prior
assert (R/'patches/uefi-b5q/0014-b5q-dma-unprivileged-wbis.patch').read_bytes()==(before/'patches/uefi-b5q/0014-b5q-dma-unprivileged-wbis.patch').read_bytes()
print('PASS sourcecontracts:OSData NUL,staticUSBmap,allDMApools/finalmapbuffer beforeUSB,noinputpagerelease,boardargs and0014unchanged')

# Configuration-space callbacks reject a dropped link and use byte/halfword
# stores, retaining PCI_STATUS when only PCI_COMMAND is requested.
wifi=(P/'B5qWifiBoard.cpp').read_text()
run('PCIe-config-width',base+r'''
#include <cerrno>
uint32_t configWords[1024]={},dbiWords[1024]={};
struct {uint32_t *va;}config={configWords},dbi={dbiWords};unsigned pcieCap=0x70;
void barrier(){}
CFG
int main(){uint32_t out=0;assert(cfgWrite(4,2,6)==-ENXIO&&cfgRead(4,2,&out)==-ENXIO);
 dbiWords[0x72c/4]=16;configWords[1]=0xffff0000;assert(!cfgWrite(4,2,6)&&configWords[1]==0xffff0006);
 assert(!cfgWrite(5,1,1)&&configWords[1]==0xffff0106);assert(!cfgRead(4,2,&out)&&out==0x106);
 assert(cfgWrite(5,2,0)==-EINVAL);dbiWords[0x72c/4]=0;assert(cfgWrite(4,4,0)==-ENXIO&&configWords[1]==0xffff0106);
 puts("PASS actual configcallbacks:native1/2/4width,COMMAND retainsSTATUS,alignmentreject,linkdown zeroconfigaccess");}
'''.replace('CFG','\n'.join(function(wifi,n)for n in ['bool cfgOffset(','int cfgRead(','int cfgWrite('])))
