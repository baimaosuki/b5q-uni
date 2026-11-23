// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "B5qWcnPowerCore.h"
#include "B5qBtFirmwareName.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
int main(){
    for(unsigned first=0;first<2;first++)for(unsigned fail=0;fail<6;fail++) {
        B5qWcn::Power p;unsigned calls=0;
        auto vote=[&](unsigned i,const B5qWcn::Rail &r){assert(i<5 && r.mv>=966);calls++;return i!=fail;};
        bool ok=p.get(first,vote);
        bool expected=fail==5 || (first==1 && fail==4);
        assert(ok==expected);
        if(!ok){assert(!p.owners);for(auto n:p.refs)assert(!n);}
        auto success=[](unsigned,const B5qWcn::Rail&){return true;};
        assert(p.get(first,success));assert(p.get(first^1,success));assert(p.owners==3);
        for(unsigned i=0;i<4;i++)assert(p.refs[i]==2);assert(p.refs[4]==1);
        assert(p.get(first,vote)); // Already owned: idempotent, including a failing callback.
        assert(p.put(first));for(unsigned i=0;i<4;i++)assert(p.refs[i]==1);
        assert(p.put(first));assert(p.put(first^1));for(auto n:p.refs)assert(!n);
        assert(!p.owners && p.retained==31);assert(!p.get(2,vote) && !p.put(2));
    }
    for(unsigned radio=0;radio<2;radio++)for(unsigned peer=0;peer<2;peer++) {
        std::array<bool,205> pins{};pins[radio?80:81]=peer;
        std::vector<std::string> events;
        auto read=[&](unsigned p){return pins[p];};
        auto pin=[&](unsigned p,bool v){assert(p==204 || p==(radio?81:80));pins[p]=v;events.push_back(std::to_string(p)+"="+std::to_string(v));};
        auto delay=[&](unsigned us){events.push_back("d"+std::to_string(us));};
        assert(B5qWcn::enable(radio,true,read,pin,delay));
        assert(pins[radio?81:80] && pins[radio?80:81]==bool(peer) && !pins[204]);
        std::vector<std::string> expected={std::to_string(radio?81:80)+"=0","d50000"};
        if(!peer)expected.push_back("d500000");
        for(const auto &e:{"204=1","d200",radio?"81=1":"80=1","d5000","204=0","d50000"})expected.push_back(e);
        assert(events==expected);assert(B5qWcn::enable(radio,false,read,pin,delay));assert(!pins[radio?81:80]);
    }
    for(const char *name:{"qca/hpbtfw21.tlv","qca/wcnhpbtfw21.tlv","qca/hpnv21.bin","qca/hpnv21g.bin","qca/hpnv21.b9a","qca/wcnhpnv21g.b1234"})assert(b5q_bt_firmware_name(name));
    for(const char *name:{"qca/../hpbtfw21.tlv","/hpbtfw21.tlv","qca/hpbtfw21.tlv/","qca/hmtbtfw20.tlv","qca/hpnv2g.bin","qca/hpnv21.b1","qca/hpnv21.b12345","qca/hpnv21.bin/../../x"})assert(!b5q_bt_firmware_name(name));
    assert(!b5q_bt_firmware_name(nullptr));
    puts("PASS WCN: all acquire-failure/coexistence/release orders, idempotent votes, exact Samsung XO/reset timing and firmware allowlist");
}
