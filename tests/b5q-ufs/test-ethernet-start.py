#!/usr/bin/env python3
"""Run actual controller start/stop on allocation/property/attach failures."""
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'UniXNU-b5q/package/B5qEthernet.cpp').read_text()
start = re.search(r'bool B5qEthernet::start\(IOService \*provider\).*?\n\}',source,re.S)[0].replace('bool B5qEthernet::start','bool start')
stop = re.search(r'void B5qEthernet::stop\(IOService \*provider\).*?\n\}',source,re.S)[0].replace('void B5qEthernet::stop','void stop')
harness = r'''
#include <cassert>
#include <cstdint>
using UInt32=unsigned;
static int fail,live,pm,baseStarts,baseStops,registered,detached;
static bool radioAddress(uint8_t*){return fail!=1;}
struct IOService {virtual bool start(IOService*){return true;}virtual void stop(IOService*){}};
struct IONetworkInterface {bool setProperty(const char*,const char*){return fail!=11;}void registerService(){++registered;}void release(){--live;delete this;}};
struct IONetworkMedium {
 unsigned getType(){return 0;}
 static IONetworkMedium*medium(unsigned,uint64_t){if(fail==4)return nullptr;++live;return new IONetworkMedium;}
 static bool addMedium(void*,IONetworkMedium*){return fail!=5;}
 static const IONetworkMedium*getMediumWithType(void*,unsigned){static IONetworkMedium m;return fail==7?nullptr:&m;}
 void release(){--live;delete this;}
};
struct OSDictionary {
 static OSDictionary*withCapacity(unsigned){if(fail==3)return nullptr;++live;return new OSDictionary;}
 void release(){--live;delete this;}
};
using IOMediumType=unsigned; constexpr unsigned kIOMediumIEEE80211Auto=0; using IOEthernetInterface=IONetworkInterface;
#define OSSafeReleaseNULL(p) do{if(p)(p)->release();p=nullptr;}while(0)
struct IOEthernetController:IOService {
 bool start(IOService*)override{++baseStarts;if(fail==2)return false;++pm;return true;}
 void stop(IOService*)override{++baseStops;--pm;assert(pm==0);}
 bool publishMediumDictionary(void*){return fail!=6;}void*getMediumDictionary(){return this;}
 bool setProperty(const char*name,bool){return !(fail==8&&name[0]=='I')&&!(fail==9&&name[0]=='U');}
 bool setProperty(const char*,const char*){return fail!=9;}
 bool attachInterface(IONetworkInterface**p,bool){if(fail==10)return false;++live;*p=new IONetworkInterface;return true;}
 void detachInterface(IONetworkInterface*){++detached;}
};
struct Controller:IOEthernetController {
 IONetworkInterface *interface=nullptr;const IONetworkMedium *medium=nullptr;uint8_t address[6]={};
 START
 STOP
};
int main(){IOService parent;
 for(fail=1;fail<=11;++fail){Controller c;live=pm=baseStarts=baseStops=registered=detached=0;
  assert(!c.start(&parent));assert(!live&&pm==0&&registered==0&&detached==(fail==11));
  assert(baseStarts==(fail!=1));assert(baseStops==(fail>=3));
 }
 fail=0;Controller c;live=pm=baseStarts=baseStops=registered=detached=0;
 assert(c.start(&parent));assert(pm==1&&live==1&&registered==1&&baseStops==0);
 c.stop(&parent);assert(!pm&&!live&&baseStops==1&&detached==1);
}
'''.replace('START', start).replace('STOP', stop)
with tempfile.TemporaryDirectory(prefix='b5q-ethernet-start-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(tmp / 'test.cpp'),
                    '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
print('PASS actual Ethernet start/stop: 10 failures plus success, balanced PM and allocations')
