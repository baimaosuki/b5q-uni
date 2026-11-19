#include "B5qRootFormat.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <vector>
using namespace B5qFormat;
static void put32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i)p[i]=n>>(8*i);}
static void put64(uint8_t *p,uint64_t n){put32(p,uint32_t(n));put32(p+4,uint32_t(n>>32));}
static void seal(uint8_t *h){put32(h+16,0);put32(h+16,crc32(h,92));}
int main(int argc,char **argv){assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);uint8_t manifest[4096];assert(fread(manifest,1,4096,f)==4096);fclose(f);Entry entries[6];uint64_t total=0;
 assert(manifestEntries(manifest,entries,total));assert(total==17603493888ULL);assert(crc32(reinterpret_cast<const uint8_t*>("123456789"),9)==0xcbf43926);
 for(unsigned i=0;i<6;++i){auto copy=entries[i];assert(inside(copy.offset,copy.bytes,total));}
 uint8_t corrupt[4096];memcpy(corrupt,manifest,4096);put64(corrupt+24+32,UINT64_MAX);assert(!manifestEntries(corrupt,entries,total));
 memcpy(corrupt,manifest,4096);put32(corrupt+24+52,3);assert(!manifestEntries(corrupt,entries,total));
 memcpy(corrupt,manifest,4096);corrupt[24+128+1]='x';assert(!manifestEntries(corrupt,entries,total));
 memcpy(corrupt,manifest,4096);put64(corrupt+16,partitionBytes+1);assert(!manifestEntries(corrupt,entries,total));
 uint8_t h[4096]={},table[4096]={};memcpy(h,"EFI PART",8);put32(h+8,0x10000);put32(h+12,92);put64(h+24,1);put64(h+32,70000000-1);put64(h+40,265);put64(h+48,69999900);put64(h+72,2);put32(h+80,32);put32(h+84,128);
 table[0]=1;put64(table+32,firstLba);put64(table+40,lastLba);const char name[]="macosroot";for(unsigned i=0;i<sizeof(name);++i)table[56+2*i]=name[i];put32(h+88,crc32(table,4096));seal(h);Gpt g={};assert(header(h,70000000,g));assert(target(table,g));
 put64(h+72,9996);seal(h);assert(!header(h,70000000,g));put64(h+72,2);seal(h);assert(header(h,70000000,g));
 put64(table+32,firstLba-1);g.crc=crc32(table,4096);assert(!target(table,g));put64(table+32,firstLba);
 memcpy(table+128,table,128);g.crc=crc32(table,4096);assert(!target(table,g));memset(table+128,0,128);
 table[128]=1;put64(table+128+32,firstLba+5);put64(table+128+40,lastLba-5);g.crc=crc32(table,4096);assert(!target(table,g));
 // Real Samsung-sized metadata envelopes: 8192 x 128 B fits the existing
 // authorized 1 MiB/GPT-LBA1..264 reader; the old arbitrary 4096 cap did not.
 std::vector<uint8_t> large(1024*1024);uint8_t *e=large.data()+36*128;e[0]=1;put64(e+32,firstLba);put64(e+40,lastLba);for(unsigned i=0;i<sizeof(name);++i)e[56+2*i]=name[i];
 put32(h+80,8192);put32(h+88,crc32(large.data(),large.size()));seal(h);const char *why=nullptr;assert(header(h,70000000,g,&why));assert(target(large.data(),g,&why)&&strcmp(why,"matched")==0);
 put64(h+32,69999998);seal(h);assert(!header(h,70000000,g,&why)&&strcmp(why,"gpt-backup-lba")==0);put64(h+32,69999999);seal(h);
 h[90]^=1;assert(!header(h,70000000,g,&why)&&strcmp(why,"gpt-header-crc")==0);h[90]^=1;
 put64(h+72,10);seal(h);assert(!header(h,70000000,g,&why)&&strcmp(why,"gpt-table-bounds")==0);put64(h+72,2);seal(h);
 put32(h+80,8193);seal(h);assert(!header(h,70000000,g,&why)&&strcmp(why,"gpt-entry-shape")==0);put32(h+80,8192);seal(h);assert(header(h,70000000,g));
 large[80]^=1;assert(!target(large.data(),g,&why)&&strcmp(why,"gpt-table-crc")==0);large[80]^=1;
 put64(e+32,firstLba-1);g.crc=crc32(large.data(),large.size());assert(!target(large.data(),g,&why)&&strcmp(why,"macosroot-bounds")==0);put64(e+32,firstLba);
 memcpy(large.data()+37*128,e,128);g.crc=crc32(large.data(),large.size());assert(!target(large.data(),g,&why)&&strcmp(why,"macosroot-duplicate")==0);
 assert(!inside(UINT64_MAX,4096,partitionBytes));assert(!inside(0,0,partitionBytes));puts("PASS: actual root manifest, GPT CRC/identity/bounds, metadata confinement, duplicate and overlap rejection");
}
