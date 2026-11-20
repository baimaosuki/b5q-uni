// Dedicated bounded journal request builder; root allowlist remains read-only.
#pragma once
#include "B5qUfsProtocol.h"
#include "B5qLogVolume.h"
static inline bool b5qLogRequest(uint32_t *utrd,uint8_t *ucd,uint64_t dma,
 uint8_t lun,uint64_t capacity,const nb_log_volume *vol,bool write,bool sync,
 uint64_t lba,uint32_t blocks) {
 using namespace B5qUfsProtocol;
 if(lun>7 || !capacity || capacity>UINT32_MAX || lba>=capacity || blocks>capacity-lba)return false;
 if(sync) {if(write || blocks>0xffff || !nb_volume_write_allowed(vol,lba,blocks))return false;}
 else if(!blocks || blocks>32 || lba>UINT32_MAX || uint64_t(blocks)-1>UINT32_MAX-lba)return false;
 if(write && !nb_volume_write_allowed(vol,lba,blocks))return false;
 if(!write && !sync && !((lba>=1 && lba<=264 && blocks<=265-lba) ||
    (lba>=3162880 && lba<3367680 && blocks<=3367680-lba)))return false;
 uint8_t cdb[16]={};uint32_t bytes=sync?0:blocks*4096;
 if(sync) {cdb[0]=0x35;} // Whole-LUN cache flush; authorization above still requires a validated log-slot extent.
 else {cdb[0]=write?0x2a:0x28;cdb[1]=write?8:0;putBe32(cdb+2,(uint32_t)lba);cdb[7]=blocks>>8;cdb[8]=blocks;}
 descriptor(utrd,dma,bytes);
 if(write)utrd[0]=(utrd[0]&~(3U<<25))|(1U<<25);
 ucd[0]=1;ucd[1]=bytes?(write?0x20:0x40):0;ucd[2]=lun;ucd[3]=0;
 putBe32(ucd+12,bytes);for(unsigned i=0;i<16;++i)ucd[16+i]=cdb[i];
 if(bytes){auto *prd=reinterpret_cast<uint32_t*>(ucd+prdOffset);prd[0]=uint32_t(dma+dataOffset);prd[1]=uint32_t((dma+dataOffset)>>32);prd[3]=bytes-1;}
 return true;
}
