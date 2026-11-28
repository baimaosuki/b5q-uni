#!/usr/bin/env python3
"""Read Samsung ACDB tag tables and retain the exact primary stereo TDM payload."""
import argparse,hashlib,json,struct
from pathlib import Path
R=Path(__file__).resolve().parents[2]
DEFAULT=R/'artifacts/firmware-b5q/F7310ZCS7EYF3/vendor/etc/audconf/OPEN/acdb_cal.acdb'
class Acdb:
    def __init__(self,data):
        self.data=data;self.chunks={}
        if len(data)<12 or data[:8]!=b'ACDB\0\0\0\0' or self.u32(8)!=len(data)-12:raise ValueError('ACDB header/size')
        at=12
        while at<len(data):
            if len(data)-at<8:raise ValueError('Truncated chunk header')
            name=data[at:at+4].decode('ascii');size=self.u32(at+4);at+=8
            if name in self.chunks or size>len(data)-at:raise ValueError('Duplicate/oversized chunk')
            self.chunks[name]=(at,size);at+=size
    def u32(self,at):
        if at<0 or at>len(self.data)-4:raise ValueError('u32 bounds')
        return struct.unpack_from('<I',self.data,at)[0]
    def span(self,name,off,size):
        base,length=self.chunks[name]
        if off<0 or size<0 or off>length or size>length-off:raise ValueError(name+' bounds')
        return base+off
    def tdm(self):
        key=self.span('MTKT',0,4);count=self.u32(key)
        if self.chunks['MTKT'][1]!=4+12*count:raise ValueError('MTKT count')
        found=[]
        for i in range(count):
            sg,tag,offset=struct.unpack_from('<III',self.data,key+4+i*12)
            lut=self.span('MTLU',offset,8);nk,ne=struct.unpack_from('<II',self.data,lut)
            if nk>32:raise ValueError('TKV key count')
            self.span('MTLU',offset+8,ne*(nk+2)*4)
            for j in range(ne):
                row=struct.unpack_from('<'+'I'*(nk+2),self.data,lut+8+j*(nk+2)*4)
                definition=self.span('MTDE',row[-2],4);dot=self.span('MTDO',row[-1],4)
                entries=self.u32(definition)
                if entries!=self.u32(dot):raise ValueError('DEF/DOT count mismatch')
                self.span('MTDE',row[-2]+4,entries*8);self.span('MTDO',row[-1]+4,entries*4)
                for k in range(entries):
                    iid,pid=struct.unpack_from('<II',self.data,definition+4+k*8)
                    if pid!=0x0800101b:continue
                    offset_data=self.u32(dot+4+k*4);param=self.span('POOL',offset_data,4);size=self.u32(param)
                    start=self.span('POOL',offset_data+4,size)
                    if size!=28:raise ValueError('TDM struct size changed')
                    raw=self.data[start:start+size]
                    names=['lpaif_type','intf_idx','sync_src','ctrl_data_out_enable','slot_mask','nslots_per_frame','slot_width','sync_mode','ctrl_invert_sync_pulse','ctrl_sync_data_delay','reserved']
                    fields=dict(zip(names,struct.unpack('<IIHHIHHHHHH',raw)))
                    found.append(dict(subgraph=sg,tag=tag,keys=list(row[:-2]),iid=iid,parameter=pid,file_payload_offset=start,payload_hex=raw.hex(),fields=fields))
        return found

def extract(path):
    if not path.is_file()or path.is_symlink():raise ValueError('Regular offline file required')
    data=path.read_bytes();allrows=Acdb(data).tdm()
    candidates=[x for x in allrows if x['subgraph']==0xb0000002 and x['tag']==0xc0000004 and x['keys']==[2]]
    if len(candidates)!=1:raise ValueError('Unique stereo RX graph missing')
    row=candidates[0]
    if row['fields']!=dict(lpaif_type=0,intf_idx=0,sync_src=1,ctrl_data_out_enable=0,slot_mask=3,nslots_per_frame=4,slot_width=32,sync_mode=0,ctrl_invert_sync_pulse=0,ctrl_sync_data_delay=1,reserved=0):raise ValueError('Original stereo TDM parameters changed')
    return dict(input=dict(path=str(path),bytes=len(data),sha256=hashlib.sha256(data).hexdigest()),selected=row,all_TDM_rows=allrows,hardware_verified=False)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=DEFAULT);p.add_argument('--out',type=Path,required=True);p.add_argument('--header',type=Path);a=p.parse_args()
    r=extract(a.input);a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(r,indent=2)+'\n')
    if a.header:
        fields=r['selected']['fields'];rbytes=bytes.fromhex(r['selected']['payload_hex'])
        text='''/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
/* Numeric interface settings from Samsung F7310ZCS7EYF3 ACDB tagged RX
 * stereo configuration. Sources/hashes/offsets: reports/p4-audio-tdm-source.json.
 * Wire layout: Qualcomm pcm_tdm_api.h param_id_tdm_intf_cfg_t, 28 bytes. */
static const uint8_t b5q_tdm_stereo_config[28] = {'''+','.join('0x%02x'%v for v in rbytes)+'''};
#define B5Q_AUDIO_RATE 48000u
#define B5Q_AUDIO_CHANNELS 2u
#define B5Q_AUDIO_ENDPOINT_BITS 24u
#define B5Q_AUDIO_TDM_BITCLOCK 6144000u
'''
        a.header.write_text(text)
    print('PASS original ACDB tables:',len(r['all_TDM_rows']),'TDM rows; unique primary RX stereo at',hex(r['selected']['file_payload_offset']))
if __name__=='__main__':main()
