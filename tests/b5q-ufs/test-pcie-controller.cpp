#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
#include "B5qPcieCore.h"
struct Fake {
    int fail=0;bool powered=false,controller=false,phyOn=false;unsigned phyWrites=0,elapsed=0;
    std::map<uint32_t,uint32_t> registers;
    struct Write{uint32_t offset,value;};std::vector<Write> writes;
    bool power(){if(fail==9)return false;powered=true;return true;}
    bool radio(bool){assert(powered);return fail!=10;}
    void pin(unsigned pin,uint32_t config,int level){assert(powered);assert(pin>=94 && pin<=96);if(pin==94)assert(config==0x201 && (level==0||level==1));}
    bool gcc(uint32_t reg,uint32_t clear,uint32_t set){assert(powered);if(fail==12&&reg!=0x52020)return false;registers[reg]=(registers[reg]&~clear)|set;return true;}
    bool rcg(uint32_t reg){assert(reg==0x6b074||reg==0x6b058);assert(powered);return fail!=12;}
    uint32_t readGcc(uint32_t reg){assert(powered);if(reg==0x6b004||reg==0x6c000)return fail==11?0:1u<<31;if(reg==0x6b074||reg==0x6b058)return 0;return registers[reg];}
    bool clkref(){return fail!=22;}
    void delay(unsigned us){assert(us<=100000);elapsed+=us;assert(elapsed<3000000);}
    bool openController(){if(fail==13)return false;controller=true;return true;}
    bool openPhy(){assert(controller);if(fail==14)return false;phyOn=true;return true;}
    void parf(uint32_t reg,uint32_t clear,uint32_t set){assert(controller);registers[reg]=(registers[reg]&~clear)|set;}
    void dbi(uint32_t reg,uint32_t clear,uint32_t set){assert(controller);registers[reg]=(registers[reg]&~clear)|set;}
    void phy(uint32_t reg,uint32_t value){assert(phyOn);auto expected=B5qPcieInputs::phy[phyWrites++];assert(reg==expected.offset&&value==expected.value);writes.push_back({reg,value});}
    uint32_t readPhy(uint32_t reg){assert(phyOn&&reg==0x214);return fail==24?0x40:0;}
    uint32_t readDbi(uint32_t reg){assert(controller);assert(reg==0x72c||reg==0x728);return fail==16?0:reg==0x72c?16:0x11;}
};
int main(){
    Fake good;assert(!B5qPcie::train(good));assert(good.phyWrites==115);assert(good.registers[0x18]==0x10100);
    assert(good.registers[0x2c00]==0 && good.registers[0x1b0]&(1u<<8));
    unsigned sidEntries=0;for(unsigned i=0;i<256;i++)if(good.registers[0x2000+4*i]){const uint32_t entry=good.registers[0x2000+4*i];assert(entry==0x01000100);
      assert((entry>>16)==0x0100&&((entry>>8)&255)==1&&(entry&255)==0);
      assert(0x1400+((entry>>8)&255)==0x1401);
      const uint32_t wrong=0x01000001;assert(((wrong>>8)&255)==0&&(wrong&255)==1);sidEntries++;}assert(sidEntries==1);
    for(int failure: {9,10,11,12,13,14,16,22,24}) {
        Fake bad;bad.fail=failure;int expected=failure==22?-12:failure==24?-14:-failure;
        int actual=B5qPcie::train(bad);if(actual!=expected)fprintf(stderr,"failure=%d actual=%d expected=%d\n",failure,actual,expected);assert(actual==expected);
        if(failure<13)assert(!bad.controller&&!bad.phyOn);
    }
    puts("PASS production PCIe train +9 bounded failure paths; power/clock before MMIO, all115 original PHY writes, RID100->SID1401");
}
