// Exact raw boot-argument parsing; tokens beginning with digits stay text.
#pragma once
#include "B5qLogFormat.h"
static inline int b5qLogArgs(const char *args,uint8_t token[16]) {
 unsigned enabled=0,found=0;
 if(!args)return 0;
 for(const char *p=args;*p;) {
  while(*p==' ' || *p=='\t')++p;
  const char *start=p;while(*p && *p!=' ' && *p!='\t')++p;
  unsigned n=(unsigned)(p-start);
  if(n>=8 && nb_equal(start,"b5q-log=",8)) {
   if(n!=9 || start[8]!='1' || ++enabled!=1)return 0;
  }
  if(n>=14 && nb_equal(start,"b5q-log-token=",14)) {
   if(n!=46 || ++found!=1)return 0;
   unsigned nonzero=0;
   for(unsigned i=0;i<16;++i) {
    unsigned v=0;
    for(unsigned j=0;j<2;++j) {
     char c=start[14+2*i+j];unsigned x;
     if(c>='0'&&c<='9')x=c-'0';else if(c>='a'&&c<='f')x=c-'a'+10;
     else if(c>='A'&&c<='F')x=c-'A'+10;else return 0;
     v=v*16+x;
    }
    token[i]=(uint8_t)v;nonzero|=v;
   }
   if(!nonzero)return 0;
  }
 }
 return enabled==1 && found==1;
}
