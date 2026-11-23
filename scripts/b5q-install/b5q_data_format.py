"""Pure b5q Data envelope/GPT validation, shared by seed creation and installer."""
import hashlib,struct,uuid,zlib
SECTOR=4096
ROOT_FIRST,ROOT_LAST=49692663,62275574
ROOT_TOTAL=17603493888
ROOT_HEADER_SHA='d93a00b589d64b7e0757aa40288aaa927a5364382ec5a0dd08faa3629d9a7d8b'
GUARD=256<<20
TAIL_FIRST=ROOT_LAST+1-(30<<30)//SECTOR
ENVELOPE_BLOCKS=256
DATA_UUID='1552CFEE-78FF-48D8-8A6C-694B867D61AC'
def inside(first,last,start,end):
 return first<=start<=end<=last

def parse_gpt(header,table,capacity):
 if len(header)!=SECTOR or header[:8]!=b'EFI PART':raise ValueError('GPT signature/sector size')
 revision,length,crc,reserved=struct.unpack_from('<4I',header,8)
 if revision!=0x10000 or not 92<=length<=4096 or reserved:raise ValueError('GPT header format')
 copy=bytearray(header[:length]);copy[16:20]=bytes(4)
 if zlib.crc32(copy)!=crc:raise ValueError('GPT header CRC')
 current,backup,usable_first,usable_last=struct.unpack_from('<4Q',header,24)
 entries,count,stride,table_crc=struct.unpack_from('<QIII',header,72)
 if current!=1 or backup!=capacity-1 or usable_first>ROOT_FIRST or usable_last<ROOT_LAST:raise ValueError('GPT geometry')
 if entries<2 or entries>64 or not 0<count<=8192 or not 128<=stride<=1024 or stride%8 or count*stride>1<<20 or (count*stride+4095)//4096>265-entries:raise ValueError('GPT metadata bounds')
 if len(table)<count*stride or zlib.crc32(table[:count*stride])!=table_crc:raise ValueError('GPT table CRC')
 parts=[]
 for i in range(count):
  e=table[i*stride:(i+1)*stride]
  if not any(e[:16]):continue
  first,last=struct.unpack_from('<QQ',e,32)
  if first>last or not inside(usable_first,usable_last,first,last):raise ValueError('GPT partition bounds')
  parts.append({'name':e[56:128].decode('utf-16le').split('\0')[0], 'first':first,'last':last,'uuid':bytes(e[16:32]),'type':bytes(e[:16])})
 roots=[x for x in parts if x['name']=='macosroot']
 if len(roots)!=1 or (roots[0]['first'],roots[0]['last'])!=(ROOT_FIRST,ROOT_LAST):raise ValueError('unique exact macosroot required')
 if any(x is not roots[0] and x['first']<=ROOT_LAST and ROOT_FIRST<=x['last'] for x in parts):raise ValueError('macosroot GPT overlap')
 return bytes(header[56:72]),parts,roots[0]

def choose(disk,parts,root,partition):
 if partition=='macosroot-tail':
  if TAIL_FIRST<ROOT_FIRST+(ROOT_TOTAL+GUARD+4095)//4096:raise ValueError('readonly guard overlap')
  return dict(mode=1,first=TAIL_FIRST,last=ROOT_LAST,disk=disk,partition=root['uuid'])
 if partition!='macosdata':raise ValueError('Data partition must be macosroot-tail or macosdata')
 selected=[x for x in parts if x['name']=='macosdata']
 if len(selected)!=1:raise ValueError('one explicit macosdata required')
 p=selected[0]
 if not any(p['uuid']) or any(x is not p and (x['uuid']==p['uuid'] or x['first']<=p['last'] and p['first']<=x['last']) for x in parts):raise ValueError('macosdata overlap/alias')
 if p['first']<=ROOT_LAST and ROOT_FIRST<=p['last'] or p['first']<265 or p['last']>0xffffffff or p['last']-p['first']+1<=ENVELOPE_BLOCKS:raise ValueError('macosdata unsafe geometry')
 return dict(mode=2,first=p['first'],last=p['last'],disk=disk,partition=p['uuid'])

def envelope(identity,container_uuid):
 first,last=identity['first'],identity['last']
 if not any(identity['disk']) or not any(identity['partition']) or last<=first or last>0xffffffff:raise ValueError('invalid identity')
 body=bytearray(4096);body[:8]=b'B5QDATA1'
 struct.pack_into('<4I5Q',body,8,1,identity['mode'],4096,0,first,last,first+ENVELOPE_BLOCKS,last-first+1-ENVELOPE_BLOCKS,ROOT_TOTAL)
 body[64:96]=bytes.fromhex(ROOT_HEADER_SHA);body[96:112]=identity['disk'];body[112:128]=identity['partition']
 body[128:144]=uuid.UUID(DATA_UUID).bytes;body[144:160]=uuid.UUID(str(container_uuid)).bytes
 struct.pack_into('<I',body,4092,zlib.crc32(body[:4092]));return bytes(body)

def validate_envelope(body,identity):
 if len(body)!=4096 or body[:8]!=b'B5QDATA1' or zlib.crc32(body[:4092])!=struct.unpack_from('<I',body,4092)[0]:raise ValueError('Data envelope magic/CRC')
 container=uuid.UUID(bytes=body[144:160])
 if body!=envelope(identity,container):raise ValueError('Data envelope identity/bounds/version mismatch')
 return container

def fletcher(block):
 if len(block)!=4096:return False
 mod=0xffffffff;s1=s2=0
 for word in struct.unpack('<1022I',block[8:]):s1=(s1+word)%mod;s2=(s2+s1)%mod
 c1=(mod-(s1+s2)%mod)%mod;c2=(mod-(s1+c1)%mod)%mod
 return struct.unpack_from('<Q',block)[0]==c1|(c2<<32)

def apfs_superblock(block,blocks,container):
 return fletcher(block) and block[32:36]==b'NXSB' and struct.unpack_from('<IQ',block,36)==(4096,blocks) and block[72:88]==uuid.UUID(str(container)).bytes
