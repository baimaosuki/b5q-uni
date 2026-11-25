#!/usr/bin/env python3
"""Causal QMP bounds, WCN cold start and production DMA handoff regressions."""
from pathlib import Path
import subprocess,tempfile,sys,json,hashlib,re
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
ns={'__file__':str(R/'tests/b5q-ufs/test-v33d-review2.py')};s=(R/'tests/b5q-ufs/test-v33d-review2.py').read_text();exec(compile(s[:s.index("run('BCM-ARC'")],'<runner>','exec'),ns)
f,run,base=ns['function'],ns['run'],ns['base']
run('QMP-mailbox-physical-boundary',base+r'''
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#include "QcomQmp.c"
#pragma GCC diagnostic pop
uint32_t ram[256];unsigned kicks=0,expected=0;QcomQmp q;
void kick(void*){++kicks;assert(ram[q.box/4]==expected);assert(expected+4<=q.box_size);}
void reset(unsigned boxSize){for(auto &v:ram)v=0xdeadbeef;ram[0]=0x4d41494c;ram[1]=1;ram[3]=ram[4]=ram[5]=ram[6]=ram[9]=ram[10]=ram[11]=ram[12]=0xffff;ram[13]=boxSize;ram[14]=0x100;ram[64]=0;qcom_qmp_init(&q,ram,sizeof(ram),kick,nullptr);assert(qcom_qmp_step(&q)==QcomQmpOpen);}
int main(){
 reset(0x64);expected=64;assert(qcom_qmp_send_padded(&q,"{class: wlan_pdc, ss: rf, res: s2g.v, upval: 1012}",64)==QcomQmpSending);assert(ram[81]==0xdeadbeef);for(unsigned i=sizeof("{class: wlan_pdc, ss: rf, res: s2g.v, upval: 1012}");i<64;i++)assert(reinterpret_cast<uint8_t*>(ram+65)[i]==0);assert(ram[89]==0xdeadbeef);
 ram[64]=0;assert(qcom_qmp_step(&q)==QcomQmpOpen);expected=96;assert(qcom_qmp_send(&q,"{class: image, res: load_state, name: adsp, val: on}")==QcomQmpSending);assert(ram[89]==0xdeadbeef);ram[64]=0;assert(qcom_qmp_step(&q)==QcomQmpOpen);
 auto before=std::vector<uint32_t>(ram,ram+256);assert(qcom_qmp_send_padded(&q,"x",100)==QcomQmpTooLong);assert(before==std::vector<uint32_t>(ram,ram+256));
 char tooLong[97];memset(tooLong,'a',96);tooLong[96]=0;assert(qcom_qmp_send(&q,tooLong)==QcomQmpTooLong);assert(before==std::vector<uint32_t>(ram,ram+256));
 reset(0x44);expected=64;assert(qcom_qmp_send(&q,"audio")==QcomQmpSending&&ram[81]==0xdeadbeef);
 reset(0x64);ram[64]=64;before.assign(ram,ram+256);assert(qcom_qmp_send(&q,"busy")==QcomQmpBusy&&before==std::vector<uint32_t>(ram,ram+256));
 puts("PASS actualQMP:AOPbox100=header4+max96;WCN64+zero-padding;ADSP96;sentinelsneveroverwritten;overlength/busy zerowrites");}
''')
w=(P/'B5qWcnPower.cpp').read_text()
run('WCN-VRM-modes-XO-coldstart',base+r'''
#include "QcomRpmh.h"
#include "B5qWcnPowerCore.h"
void IOLog(const char*,...){}struct{uint32_t words[1]={};uint32_t *va=words;}rsc;
QcomRpmhResource resources[5];std::vector<std::pair<unsigned,unsigned>> sent;
QcomRscLayout qcom_rsc_layout(uint32_t){return {};}
bool send(const QcomRscLayout&,uint32_t a,uint32_t v){sent.push_back({a,v});return true;}
VOTE
uint32_t wifiProbeState;unsigned elapsed=0,finishAt=20;bool wifiOn=true;
bool PE_parse_boot_argn(const char*,unsigned *v,unsigned){*v=wifiOn;return true;}
constexpr int ETIMEDOUT=60;void IOSleep(unsigned ms){elapsed+=ms;if(finishAt&&elapsed>=finishAt)__atomic_store_n(&wifiProbeState,2u,__ATOMIC_RELEASE);}
WAIT
int main(){for(unsigned i=0;i<5;i++){resources[i].address=0x100+16*i;sent.clear();assert(vote(i,B5qWcn::rails[i]));assert(sent.size()==((i==0||i==3)?3:2));for(auto v:sent)if(v.first==resources[i].address+8)assert((i==0||i==3)&&v.second==7);}
 bool pins[205]={};unsigned ownWrites=0;auto read=[&](unsigned p){return pins[p];};auto pin=[&](unsigned p,bool on){if(p==204)return;pins[p]=on;if(on)ownWrites++;};auto delay=[](unsigned){};
 assert(!B5qWcn::enable(0,true,read,pin,delay)&&!ownWrites); // XO204 stuck low: never raise WLAN_EN.
 wifiProbeState=1;assert(!b5q_wcn_wait_wifi_probe()&&elapsed==20);finishAt=0;elapsed=0;wifiProbeState=1;assert(b5q_wcn_wait_wifi_probe()==60&&elapsed==70000);wifiOn=false;elapsed=0;assert(!b5q_wcn_wait_wifi_probe()&&!elapsed);
 puts("PASS production5rail votes:onlyDTmode-capableLDO15/SMPG4mode7;XOstucklowfailsbeforeEN;BTwaitsforWiFicompletion/nopowermutex/70stimeout");}
'''.replace('VOTE',f(w,'bool vote(')).replace('WAIT',f(w,'extern "C" int b5q_wcn_wait_wifi_probe(')))
run('WCN-read-only-observer',base+r'''
#include "BootResetCore.h"
#include "B5qWcnPowerCore.h"
unsigned observerReads=0,channelOpens=0;
unsigned ppids[]={0x14e,0x4a4,0x6aa,0x6a4,0x69e};
struct Window{std::vector<uint32_t> words;uint32_t*va=nullptr;bool open(uint64_t pa,unsigned n){
 if(pa>=0xc500000)channelOpens++;words.resize(n/4);va=words.data();
 if(pa==0xc400000){va[0]=BR_VERSION_V7_MIN;va[BR_FEATURES/4]=5;for(unsigned i=0;i<5;i++)va[(BR_APID_MAP+4*i)/4]=ppids[i]<<8;}return true;}};
void barrier(){}void IOLog(const char*,...){}
int modelWait(volatile uint32_t*p){unsigned cmd=p[BR_CMD/4];assert((cmd>>27)==BR_OP_EXT_READL);unsigned reg=(cmd>>4)&255;assert(reg==4||reg==5||reg==8||reg==0x46||reg==0x40||reg==0x41||reg==0x45);p[BR_RDATA0/4]=reg==0x46?0x80:reg==0x40?0x08:reg==0x41?0x07:0;observerReads++;return 0;}
#define br_wait modelWait
SURVEY
int main(){railSurvey("before");railSurvey("after");assert(observerReads==70&&!channelOpens);puts("PASS actual5rail pre/post observer:70EXT_READL,zero writablechannel orPMICwrites,actualvoltage/statusreadpaths");}
'''.replace('SURVEY',f(w,'void railSurvey(')))
# Actual ABI, final map position, required pointer and no regression boundaries.
D=R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe'
for name in ['UsbDma.c','PcieDma.c','MediaDma.c']:
 text=(D/name).read_text();assert 'HAL_FLUSH FlushDomain'in text and ('==40'in text or '== 40'in text)
 assert '!Hal->FlushDomain'in text or '(Hal->FlushDomain == NULL)'in text
 assert text.count('Hal->FlushDomain(')+text.count('Hal->FlushDomain (')>0
 for constant in ['0x00c01027','0x00803510','0x0003c071']:assert constant in text
loader=(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_text();last=loader[loader.index('  for (Attempt = 0; Attempt < 3; Attempt++)'):]
assert last.index('GetMemoryMap')<last.index('DarwinOutsideRanges')<last.index('DescribeWindow')<last.index('WriteUsbDmaResult')<last.index('gBS->ExitBootServices')
assert 'OutsideOffset == MAX_UINTN ? 0 : OutsideCount'in last
print('PASS productionfirmware:slot5@40,pointerchecks,allHALflushcalls;finalEBSmap/exclusions/outside precedecoverage;0014constants retained')
