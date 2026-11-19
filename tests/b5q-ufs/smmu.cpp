#include "B5qSmmu.h"
#include <assert.h>
#include <map>
#include <vector>
#include <utility>
#include <stdio.h>
struct Mock {
 std::map<unsigned,uint32_t> reg;std::vector<std::pair<unsigned,uint32_t>> writes;
 Mock(){reg[0x20]=(1U<<30)|8;reg[0x24]=8;reg[0x28]=(1U<<12)|0x222;reg[0x800]=0x80000060;reg[0xc00]=2;reg[0x800+4]=0x80001c00;reg[0xc00+4]=3;reg[(2+2)*4096]=1;reg[(2+3)*4096]=1;}
 bool run(uint64_t dma=0x100000000ULL){return b5qConfigureUfsStream(dma,0x25000,[&](unsigned off){return reg[off];},[&](unsigned off,uint32_t v){writes.push_back({off,v});reg[off]=v;});}
};
int main(){
 Mock ok;assert(ok.run());assert(ok.reg[0x800]==0x80000060&&ok.reg[0xc00]==7);assert(ok.reg[0x804]==0x80001c00&&ok.reg[0xc04]==3&&ok.reg[5*4096]==1);assert(ok.writes.size()==5);
 Mock masked;masked.reg[0x800]|=1U<<16;assert(!masked.run()&&masked.writes.empty());
 Mock duplicate;duplicate.reg[0x808]=0x80000060;assert(!duplicate.run()&&duplicate.writes.empty());
 Mock noBank;for(unsigned i=0;i<8;++i)noBank.reg[(2+i)*4096]=1;assert(!noBank.run()&&noBank.writes.empty());
 Mock width;assert(!width.run(1ULL<<40)&&width.writes.empty());
 Mock huge;huge.reg[0x24]=0x80000008;assert(!huge.run()&&huge.writes.empty());
 Mock otherBank;otherBank.reg[0x808]=0x80001920;otherBank.reg[0xc08]=7;assert(otherBank.run()&&otherBank.reg[0xc00]==6&&otherBank.reg[0xc08]==7);
 puts("PASS: real SMMU configuration preserves display/other streams; rejects masks, duplicates, busy banks and DMA width overflow");
}
