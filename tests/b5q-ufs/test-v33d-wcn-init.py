#!/usr/bin/env python3
"""Execute the new PMK/PDC hardware initialization with causal SPMI/AOP peers."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
ns={'__file__':str(R/'tests/b5q-ufs/test-v33d-review2.py')};s=(R/'tests/b5q-ufs/test-v33d-review2.py').read_text();exec(compile(s[:s.index("run('BCM-ARC'")],'<host-runner>','exec'),ns)
w=(P/'B5qWcnPower.cpp').read_text();f=ns['function'];run=ns['run'];base=ns['base']
body=base+r'''
#include "BootResetCore.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#define barrier qmpBarrier
#include "QcomQmp.c"
#undef barrier
#pragma GCC diagnostic pop
#include "QcomScm.h"
unsigned pmicOwner=0,channelOpens=0;bool reservedBits=false;
struct Window{std::vector<uint32_t> data;uint32_t *va=nullptr;bool open(uint64_t base,unsigned bytes){
 data.resize(bytes/4);va=data.data();if(base==0xc42d000)va[0]=pmicOwner;if(base==0xc500000)channelOpens++;if(base==0xc400000){va[0]=BR_VERSION_V7_MIN;va[1]=1;va[BR_APID_MAP/4]=0x0ba<<8;}
 return true;}};
Window aoss,ipcc;QcomQmp pdcQmp;bool sleepReady=false,pdcReady=false;
uint8_t pmic[256]={};unsigned writes=0,ticks=0;bool aopAck=true;std::vector<std::string> messages;
struct B5qAossQmpLock{bool ready()const{return true;}};
void barrier(){}void IOLog(const char*,...){}
int modelWait(volatile uint32_t *p){unsigned cmd=p[BR_CMD/4],reg=(cmd>>4)&255;
 if((cmd>>27)==BR_OP_EXT_READL)p[BR_RDATA0/4]=pmic[reg];else{pmic[reg]=uint8_t(p[BR_WDATA0/4]);if(reservedBits){if(reg==0x40)pmic[reg]|=0x80;if(reg==0x44)pmic[reg]|=0xf0;if(reg==0x46)pmic[reg]|=1;if(reg==0x42)pmic[reg]|=0xa0;if(reg==0x41)pmic[reg]|=0x30;}writes++;}return 0;}
#define br_wait modelWait
SLEEP
KICK
void IOSleep(unsigned ms){ticks+=ms;if(!aopAck)return;auto *r=aoss.va;
 r[4]=r[3];r[10]=r[9];r[5]=r[11];r[12]=r[6];
 if(pdcQmp.box&&r[pdcQmp.box/4]){messages.emplace_back(reinterpret_cast<char*>(r+pdcQmp.box/4+1));r[pdcQmp.box/4]=0;}}
WAIT
PDC
void resetAop(){aoss.data.assign(1024,0);aoss.va=aoss.data.data();ipcc.data.assign(1024,0);ipcc.va=ipcc.data.data();
 auto*r=aoss.va;r[0]=0x4d41494c;r[1]=1;r[3]=r[4]=r[5]=r[6]=r[9]=r[10]=r[11]=r[12]=0xffff;r[13]=0x80;r[14]=0x100;}
int main(){pmic[4]=0x10;pmic[5]=0x10;assert(sleepClock()&&writes==5);assert(pmic[0x42]==5&&pmic[0x41]==0&&pmic[0x44]==2&&pmic[0x40]==1&&pmic[0x46]==0x80);
 assert(sleepClock()&&writes==5);sleepReady=false;pmic[5]=0xff;pmic[0x46]=0;assert(!sleepClock()&&writes==5);
 pmic[5]=0x10;pmic[0x40]=0x81;pmic[0x44]=0xf2;pmic[0x46]=0x81;pmicOwner=3;sleepReady=false;unsigned opened=channelOpens;assert(sleepClock()&&writes==5&&channelOpens==opened);
 pmic[0x46]=0;sleepReady=false;assert(!sleepClock()&&writes==5&&channelOpens==opened);
 pmicOwner=0;reservedBits=true;sleepReady=false;assert(sleepClock()&&writes==10&&channelOpens==opened+1);
 resetAop();assert(pdcInit()&&messages.size()==11);assert(messages[8]=="{class: wlan_pdc, ss: rf, res: s2g.v, upval: 1012}");
 assert(pdcInit()&&messages.size()==11);pdcReady=false;resetAop();aopAck=false;ticks=0;assert(!pdcInit()&&ticks==1000&&aoss.va[pdcQmp.box/4]==100);
 puts("PASS actual PMKgpio3 fivewrites/bitfield-readback/idempotence/subtype rejection; nonAPPS-owned enabled pin retained withoutchannel; reservedbits accepted; AOSSrealQMP11messages+1012mV,AOPack,1sboundedtimeout retainsunacknowledgedmailbox");}
'''
# The synthetic map's open must preserve the AOP descriptor initialized by reset.
body=body.replace('data.resize(bytes/4);va=data.data();','if(va)return true;data.resize(bytes/4);va=data.data();')
body=body.replace('#include "QcomScm.h"','#include "QcomScm.h"\n#include <string>')
run('WCN-PMK-PDC',body.replace('SLEEP',f(w,'bool sleepClock(')).replace('KICK',f(w,'void kickPdc(')).replace('WAIT',f(w,'bool waitPdc(')).replace('PDC\n',f(w,'bool pdcInit(')+'\n'))
# Exact required eleven strings are taken from the board's original DT.
import re
stock=(R/'uefi-b5q/Resources/DTBs/b5q.dts').read_text();at=stock.index('cnss-qca6490');at=stock.index('qcom,pdc_init_table',at);line=stock[at:stock.index(';',at)]
strings=re.findall(r'"([^"\n]+)"',line);production=re.findall(r'"(\{class: wlan_pdc[^"\n]+)"',f(w,'bool pdcInit('));assert production==strings and len(strings)==11
assert 'layout.status' in f(w,'bool send(')
send=f(w,'bool send(');assert send.index('if(us==20000)')<send.index('qcom_rpmh_finish(')
print('PASS PDC production strings exactlymatchoriginalb5qDT; TCSbusy/status checkedbeforewrite,timeout cannotfinishliveTCS')
body=base+r'''
#include "QcomRpmh.c"
#define IOLog(...) ((void)0)
void barrier(){}void IODelay(unsigned){}
struct Model;
struct Reg{Model *m;unsigned at;uint32_t value=0;operator uint32_t()const{return value;}void operator=(uint32_t);void operator|=(uint32_t v){*this=value|v;}};
struct Model{Reg regs[0x10000/4];Reg *va=regs;QcomRscLayout layout=qcom_rsc_layout(3u<<16);bool ack=true;unsigned writes=0;
 Model(){for(unsigned i=0;i<0x10000/4;i++){regs[i].m=this;regs[i].at=i*4;}regs[(0xd00+layout.status)/4].value=1;}
};
void Reg::operator=(uint32_t v){m->writes++;value=v;auto &l=m->layout;
 if(at==0xd00+l.irq_clear)m->regs[(0xd00+l.irq_status)/4].value&=~v;
 if(at==0xd00+l.control&&(v&(1u<<24))){m->regs[(0xd00+l.status)/4].value=m->ack?1:0;if(m->ack)m->regs[(0xd00+l.irq_status)/4].value|=1;}
}
Model rsc;
SEND
int main(){auto l=rsc.layout;rsc.regs[(0xd00+l.irq_status)/4].value=1;assert(send(l,0x50100,100));assert(!rsc.regs[(0xd00+l.irq_status)/4].value&&!rsc.regs[(0xd00+l.control)/4].value);
 rsc.ack=false;assert(!send(l,0x50100,200));assert(rsc.regs[(0xd00+l.control)/4].value&(1u<<24));unsigned before=rsc.writes;
 assert(!send(l,0x50100,300)&&rsc.writes==before);
 puts("PASS actual RPMh:TCSidle gate,staleirq W1C,trigger/completion/finish; timeout retainsrunningTCS and busyretry performszerowrites");}
'''
run('WCN-RPMh',body.replace('SEND',f(w,'bool send(')))
