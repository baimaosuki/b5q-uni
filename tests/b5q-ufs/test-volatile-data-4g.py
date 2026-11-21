"""Exercise the same sparse RAM operations selected by the b5q4GiB storage patch."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q4g-')as td:
 td=Path(td);source=td/'NativeRamBlock.cpp';source.write_bytes((root/'UniXNU/drivers/RamBlock/NativeRamBlock.cpp').read_bytes())
 subprocess.run(['patch','--batch','--fuzz=0',str(source)],input=(root/'UniXNU-b5q/scripts/b5q-volatile-data-4g.patch').read_bytes(),check=True)
 text=source.read_text();assert 'wantsStore ? 0x80000000ULL : 0x100000000ULL' in text
 code=r'''
#include "SparseDisk.h"
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <vector>
struct Ops{
 unsigned allocations=0;bool fail=false;std::vector<uint8_t*> held;std::vector<uint8_t> buffer;
 uint8_t *allocate(){if(fail)return nullptr;++allocations;auto p=(uint8_t*)calloc(4096,1);held.push_back(p);return p;}
 uint64_t read(uint64_t at,void *p,uint64_t n){memcpy(p,buffer.data()+at,n);return n;}
 uint64_t copy(uint64_t at,const void *p,uint64_t n){memcpy(buffer.data()+at,p,n);return n;}
 ~Ops(){for(auto p:held)free(p);}
};
int main(){
 const uint64_t size=0x100000000ull;std::vector<uint8_t*> pages(size/4096);RamSparseDisk d={pages.data(),size,0};Ops ops;
 std::vector<uint8_t> seed(32+16+4096,0);memcpy(seed.data(),"DBRDISK1",8);
 uint32_t v=1;memcpy(seed.data()+8,&v,4);v=4096;memcpy(seed.data()+12,&v,4);
 memcpy(seed.data()+16,&size,8);uint64_t n=1;memcpy(seed.data()+24,&n,8);
 uint64_t offset=size-4096,len=4096;memcpy(seed.data()+32,&offset,8);memcpy(seed.data()+40,&len,8);seed[48]=0x5a;
 assert(ramSparseImport(d,seed.data(),seed.size(),ops)&&d.resident==4096&&ops.allocations==1);
 for(uint64_t at:{0ull,0x80000000ull,0xfffff000ull}){
  bool noMem=false;ops.buffer.assign(4096,0x98);assert(ramSparseIO(d,true,at,4096,ops,noMem)==4096&&!noMem);
  ops.buffer.assign(4096,0);assert(ramSparseIO(d,false,at,4096,ops,noMem)==4096&&!noMem);
  for(auto v:ops.buffer)assert(v==0x98);
 }
 assert(ops.allocations==3&&d.resident==12288);
 bool noMem=false;ops.fail=true;assert(!ramSparseIO(d,true,4096,4096,ops,noMem)&&noMem);
 assert(!ramSparseIO(d,true,size,1,ops,noMem));assert(!ramSparseIO(d,true,size-1,2,ops,noMem));
 assert(!ramSparseIO(d,true,~0ull-1,4,ops,noMem));
 puts("PASS production sparse RAM4GiB: seed atlastpage, reads/writes below/above2GiB andlastblock,zero-filled allocation,bounds/OOM;3residentpages only");
}
'''
 p=td/'test.cpp';p.write_text(code);exe=td/'test'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(root/'UniXNU/drivers/RamBlock'),str(p),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
