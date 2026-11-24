#!/usr/bin/env python3
"""Plan bounded APFS initialization from validated allocation bitmaps.

Free blocks need no source contents. Allocated zero blocks and the complete
internal pool are included, even when the host image represents them as holes.
The union also retains checkpoint metadata and all host data extents.
"""
import errno,hashlib,json,os,struct
from pathlib import Path
from b5q_data_format import fletcher

def validate_source_receipt(image,manifest,receipt):
 p=Path(image);r=json.loads(Path(receipt).read_text());s=p.stat()
 assert r['path']==str(p.resolve()) and r['sha256']==manifest['sha256'] and r['full_image_SHA256_calculated']is True
 assert r['stat']=={k:getattr(s,k)for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')},'source changed since full hash'

def allocation_plan(image):
 p=Path(image);ranges=[]
 with p.open('rb')as f:
  N=p.stat().st_size//4096
  u32=lambda b,o:struct.unpack_from('<I',b,o)[0]
  u64=lambda b,o:struct.unpack_from('<Q',b,o)[0]
  def add(b,c=1):
   assert 0<=b<N and 0<c<=N-b,(b,c);ranges.append((b,b+c))
  def read(b,c=1,verify=False):
   assert 0<=b<N and c>0 and b+c<=N
   f.seek(b*4096);data=f.read(c*4096);assert len(data)==c*4096
   if verify:
    assert c==1 and fletcher(data),('checksum',b,c)
   return data
  nx=read(0,verify=True);assert nx[32:36]==b'NXSB'and u32(nx,36)==4096 and u64(nx,40)==N
  base,count=u64(nx,112),u32(nx,104);assert count<65536
  candidates=[nx]
  for block in range(base,base+count):
   b=read(block)
   if b[32:36]==b'NXSB'and fletcher(b):candidates.append(b)
  nx=max(candidates,key=lambda b:u64(b,16));assert u64(nx,40)==N

  add(0);add(u64(nx,112),u32(nx,104));add(u64(nx,120),u32(nx,108))
  smid=u64(nx,152);found=[]
  for block in range(u64(nx,112)+u32(nx,136),u64(nx,112)+u32(nx,136)+u32(nx,140)-1):
   b=read(block,verify=True);assert u32(b,24)&0xffff==12
   entries=u32(b,36);assert entries<=101
   for i in range(entries):
    size=u32(b,40+i*40+8);oid=u64(b,40+i*40+24);addr=u64(b,40+i*40+32)
    assert size and size%4096==0;add(addr,size//4096)
    if oid==smid:found.append((addr,size))
  assert len(found)==1
  addr,size=found[0];assert size==4096;sm=read(addr,verify=True)

  assert u32(sm,24)&0xffff==5 and u32(sm,32)==4096
  blocks_per_chunk=u32(sm,36);chunks_per_cib=u32(sm,40)
  blocks,chunks,cibs,cabs,free,addr_off=struct.unpack_from('<QQIIQI',sm,48)

  assert blocks==N and 0<blocks_per_chunk<=32768 and 0<chunks_per_cib<=126 and struct.unpack_from("<QQIIQ",sm,96)==(0,0,0,0,0)
  # Internal pool bitmap storage and the pool itself must include allocated zero blocks.
  ipcount=u64(sm,152);bm_size=u32(sm,160);bm_count=u32(sm,164);bm_base=u64(sm,168);ipbase=u64(sm,176)

  if ipcount:add(ipbase,ipcount)
  if bm_count:add(bm_base,bm_count)
  addresses=[u64(sm,addr_off+i*8)for i in range(cabs or cibs)]
  if cabs:
   cibrows=[]
   for b in addresses:
    cab=read(b,verify=True);add(b);assert u32(cab,24)&0xffff==6
    n=u32(cab,36);assert n<=507;cibrows += [u64(cab,40+i*8)for i in range(n)]
  else:cibrows=addresses
  assert len(cibrows)==cibs
  allocated=free_seen=chunk_seen=0;position=0
  for index,block in enumerate(cibrows):
   cib=read(block,verify=True);add(block);assert u32(cib,24)&0xffff==7 and u32(cib,32)==index
   n=u32(cib,36);assert 0<n<=chunks_per_cib
   for i in range(n):
    xid,start,length,available,bitmap=struct.unpack_from('<QQIIQ',cib,40+i*32)
    assert start==position and 0<length<=blocks_per_chunk and length<=N-start and available<=length
    position+=length;free_seen+=available;chunk_seen+=1
    if bitmap:
     bits=read(bitmap);add(bitmap);bitsval=int.from_bytes(bits,'little');assert bitsval>>length==0
     assert bitsval.bit_count()==length-available,(start,length,available,bitsval.bit_count())
     run=None
     for bit in range(length):
      used=bits[bit//8]>>(bit%8)&1
      if used and run is None:run=start+bit
      if not used and run is not None:add(run,start+bit-run);run=None
     if run is not None:add(run,start+length-run)
     allocated+=length-available
    else:assert available==length
  assert position==N and chunk_seen==chunks and free_seen==free
  add(N-1)
  at=0
  while at<p.stat().st_size:
   try:start=os.lseek(f.fileno(),at,os.SEEK_DATA)
   except OSError as e:
    if e.errno==errno.ENXIO:break
    raise
   end=os.lseek(f.fileno(),start,os.SEEK_HOLE)
   assert start%4096==end%4096==0
   add(start//4096,(end-start)//4096);at=end
  merged=[]
  for start,end in sorted(ranges):
   if merged and start<=merged[-1][1]+16:merged[-1][1]=max(merged[-1][1],end)
   else:merged.append([start,end])
  segments=[]
  for start,end in merged:
   while start<end:
    count=min(4096,end-start);f.seek(start*4096);body=f.read(count*4096)
    assert len(body)==count*4096
    segments.append(dict(block=start,blocks=count,sha256=hashlib.sha256(body).hexdigest()));start+=count
  written=sum(s['blocks']*4096 for s in segments)
  assert 0<written<1<<30,'sparse initialization may not write >=1GiB'
  return dict(schema_version=1,APFS_bytes=p.stat().st_size,APFS_blocks=N,checkpoint_xid=u64(nx,16),allocated_blocks=allocated,free_blocks=free,allocated_blocks_including_zeroes=True,internal_pool_included=True,segments=segments,write_bytes=written)
