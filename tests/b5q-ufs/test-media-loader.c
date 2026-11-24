// SPDX-License-Identifier: BSD-2-Clause-Patent
#define main qualified_usb_main
#include "test-usb-firmware-dma.c"
#undef main
#define AsciiStrLen strlen
#define AsciiStrnCmp strncmp
#define CompareMem memcmp
#define ALIGN_VALUE(v,a) (((v)+((a)-1))&~((a)-1))
#define EFI_ERROR(v) ((v)!=0)
static UINT32 ReadUnaligned32(const UINT32 *p){UINT32 v;memcpy(&v,p,4);return v;}
static UINTN AsciiStrnLenS(const char *p,UINTN n){UINTN i=0;while(i<n&&p[i])i++;return i;}
#include "B5qMediaDmaLoader.h"
static unsigned locates,prepares;static bool missing;
static void prepare(UINT32 kind,B5Q_MEDIA_DMA_RESULT *r) {
    prepares++;assert(kind==1||kind==2);r->PrepareStatus=7;
}
static B5Q_MEDIA_DMA_PROTOCOL protocol={1,prepare};
static EFI_STATUS locate(EFI_GUID *guid,void *unused,void **out) {
    assert(guid->Data1==0x061f797d&&!unused&&!*out);locates++;
    if(missing)return 14;*out=&protocol;return 0;
}
static void prop(UINT8 *tree,UINTN *at,const char *name,const void *value,UINT32 length) {
    memset(tree+*at,0,36);memcpy(tree+*at,name,strlen(name));memcpy(tree+*at+32,&length,4);*at+=36;
    if(value)memcpy(tree+*at,value,length);else memset(tree+*at,0,length);
    *at=ALIGN_VALUE(*at+length,4);
}
int main(void) {
    assert(!qualified_usb_main());
    for(const char **p=(const char*[]){"audio=1","audio=0 audio=3","x=1 audio=1 x=0",NULL};*p;p++)assert(MediaArgEnabled(*p,1,0));
    for(const char **p=(const char*[]){"audio=0","audio=1 audio=0","audio=-1","audio=bad","noaudio=1","audio=","audio=99999999999999999",NULL};*p;p++)assert(!MediaArgEnabled(*p,1,0));
    assert(MediaArgEnabled("sheng-video=1",2,0)&&!MediaArgEnabled("video=1",2,0));
    assert(!MediaArgEnabled(NULL,1,0));services.LocateProtocol=locate;
    B5Q_MEDIA_DMA_RESULT result;GetMediaDmaResult("audio=0",1,63,&result);assert(!locates&&!prepares&&result.PrepareStatus==19);
    GetMediaDmaResult("audio=1",1,0,&result);assert(locates==1&&prepares==1&&result.PrepareStatus==7);
    missing=true;GetMediaDmaResult("sheng-video=1",2,0,&result);assert(result.PrepareStatus==14&&prepares==1);
    UINT8 tree[1024]={0};UINTN at=8;UINT32 root[2]={1,1};memcpy(tree,root,8);prop(tree,&at,"name","/",2);
    UINT32 chosen[2]={6,0};memcpy(tree+at,chosen,8);at+=8;prop(tree,&at,"name","chosen",7);
    UINT32 features=63;prop(tree,&at,"b5q-feature-mask",&features,4);
    prop(tree,&at,"b5q-audio-dma-ready",NULL,4);prop(tree,&at,"b5q-audio-dma-state",NULL,104);
    prop(tree,&at,"b5q-video-dma-ready",NULL,4);prop(tree,&at,"b5q-video-dma-state",NULL,104);
    UINTN length=at,cursor=0;B5Q_MEDIA_DMA_ADT adt[2]={{MAX_UINTN,MAX_UINTN},{MAX_UINTN,MAX_UINTN}};
    assert(FindMediaDmaNode(tree,length,&cursor,0,3,adt)&&cursor==length);
    assert(adt[0].Features==63&&adt[1].Features==63);
    for(UINT32 mask=0;mask<128;mask++)for(UINT32 kind=1;kind<=2;kind++) {
        char args[100];const unsigned bit=kind==1?16:32;
        assert(MediaArgEnabled(NULL,kind,mask)==((mask&bit)!=0));
        snprintf(args,sizeof(args),"b5q-f=%u",mask);
        assert(MediaArgEnabled(args,kind,~mask)==((mask&bit)!=0));
        snprintf(args,sizeof(args),"b5q-f=%u %s=0",mask,kind==1?"audio":"sheng-video");
        assert(!MediaArgEnabled(args,kind,mask));
        snprintf(args,sizeof(args),"b5q-f=0 %s=1",kind==1?"audio":"sheng-video");
        assert(MediaArgEnabled(args,kind,0));
    }
    assert(!MediaArgEnabled("audio=2",1,63));
    assert(!MediaArgEnabled("b5q-f=4294967296",1,63));
    assert(MediaArgEnabled("b5q-f=4294967295",1,0));
    for(UINTN n=0;n<length;n++) {
        cursor=0;B5Q_MEDIA_DMA_ADT rejected[2]={{MAX_UINTN,MAX_UINTN},{MAX_UINTN,MAX_UINTN}};
        assert(!FindMediaDmaNode(tree,n,&cursor,0,3,rejected));
    }
    for(UINT32 kind=1;kind<=2;kind++) {
        const bool audio=kind==1;
        result=(B5Q_MEDIA_DMA_RESULT){.Version=1,.Kind=kind,.Sid={audio?0x00801001:0x1940,audio?0x1061:0x1947},
            .PoolBase=0xb0000000,.PoolBytes=audio?0x200000:0x8000000,.Iova=audio?0xa0000000:0x40000000,
            .TableBase=0xffe00000,.TableBytes=0x20000};
        EFI_MEMORY_DESCRIPTOR map[2]={{.Type=EfiReservedMemoryType,.PhysicalStart=result.PoolBase,.NumberOfPages=result.PoolBytes/4096},
            {.Type=EfiReservedMemoryType,.PhysicalStart=result.TableBase,.NumberOfPages=32}};
        UINT32 ready=0;
        WriteMediaDmaResult(tree,&adt[kind-1],&result,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false,kind);
        memcpy(&ready,tree+adt[kind-1].Ready,4);assert(ready==1);
        for(unsigned n=0;n<7;n++) {
            B5Q_MEDIA_DMA_RESULT bad=result;
            if(n==0)bad.Create=1;if(n==1)bad.Configure=1;if(n==2)bad.Attach[0]=1;
            if(n==3)bad.Attach[1]=1;if(n==4)bad.Map=1;if(n==5)bad.Sid[0]^=1;if(n==6)bad.Sid[1]^=1;
            WriteMediaDmaResult(tree,&adt[kind-1],&bad,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false,kind);
            memcpy(&ready,tree+adt[kind-1].Ready,4);assert(!ready);
        }
        for(unsigned n=0;n<2;n++) {
            map[n].Type=EfiBootServicesData;
            WriteMediaDmaResult(tree,&adt[kind-1],&result,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false,kind);
            memcpy(&ready,tree+adt[kind-1].Ready,4);assert(!ready);map[n].Type=EfiReservedMemoryType;
        }
        WriteMediaDmaResult(tree,&adt[kind-1],&result,map,sizeof(map),sizeof(map[0]),result.PoolBase,result.PoolBytes,false,kind);
        memcpy(&ready,tree+adt[kind-1].Ready,4);assert(!ready);
    }
    puts("PASS actual media loader:args/HALmissing/incompatible/failures,allADTtruncations,distinctSIDtuples and retained-only ready; USB regression retained");
}
