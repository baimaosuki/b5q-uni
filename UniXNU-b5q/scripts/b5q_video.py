"""Reuse pinned QcomIris with a retained firmware DMA pool on Samsung b5q.

No ArmSmmu4KLive/IrisMmu/Sm8550AppsSmmu implementation is selected. Client
planes use explicit bounded copies through the retained coherent pool.
"""
import hashlib,json,os,subprocess
from pathlib import Path
from b5q_adsp import REVISION,replace

def pinned_linux(lock,path):
    # These four public, hash-locked sources are retained with the device.
    # CI must not redownload the same inputs from rate-limited raw GitHub.
    device=Path(os.environ.get('UNIXNU_DEVICE',Path(__file__).resolve().parents[1]))
    source=device/'inputs/iris-linux'/lock['commit']/path
    data=source.read_bytes()
    if hashlib.sha256(data).hexdigest()!=lock['files'][path]:
        raise ValueError('Iris dependency SHA mismatch: '+path)
    return data

def prepare(reference,soc,out,fetch=True):
    reference,soc,out=map(Path,(reference,soc,out));out.mkdir(parents=True,exist_ok=True)
    if subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()!=REVISION:
        raise ValueError('Video reference identity changed')
    iris=reference/'drivers/QcomIris';package=reference/'package'
    text=(package/'VideoProbe.cpp').read_text()
    text=replace(text,'#include <kern/thread.h>',
        '#include <kern/thread.h>\nextern "C" kern_return_t clear_wait(thread_t,wait_result_t);', 'clear_wait private declaration')
    text=replace(text,'#include "QcomIrisDevice.h"','#include "QcomIrisDevice.h"\n#include "B5qVideoMemory.h"','retained memory API')
    for header in ('Sm8550AppsSmmu.h','ArmSmmu4KLive.h','QcomIrisMmu.h'):
        text=replace(text,'#include "'+header+'"\n','','remove EL1 domain header '+header)
    begin=text.index('// ---- table pages of the VPU domain:')
    end=text.index('struct Video {',begin);text=text[:begin]+text[end:]
    text=replace(text,'Window vpu, gcc, videocc, smmu, rsc;','Window vpu, gcc, videocc, rsc;','remove SMMU window')
    text=replace(text,'    struct sm8550_apps_smmu_domain domain;\n    struct qcom_iris_mmu mmu;\n    TablePages tables;\n','','remove live domain state')
    begin=text.index('uint32_t smmuRead(');end=text.index('// ---- secure world calls:',begin);text=text[:begin]+text[end:]
    for line in ('constexpr uint16_t kSids[2] = {0x1940, 0x1947};\n','constexpr unsigned kPollBudget = 1000;\n'):
        text=replace(text,line,'','remove unused domain constants')
    text=replace(text,'/sm8550/sheng/vpu30_4v.mbn','/sm8550/b5q/vpu30_4v.mbn','original Samsung VPU file')
    text=replace(text,'void fail(int step, int error) {native_video_stats[1] = error; native_video_stats[0] = -step;}',
        'void fail(int step, int error) {native_video_stats[1] = error; native_video_stats[0] = -step; IOLog("B5qVideo: stage=-%d error=%d\\n",step,error);}', 'failure evidence')
    text=replace(text,'    native_video_stats[15] = (int32_t)v.mmu.last_status;\n    native_video_stats[16] = (int32_t)(v.mmu.iova.allocated / 4096);',
        '    native_video_stats[15] = 0;\n    native_video_stats[16] = (int32_t)(b5q_video_memory_used() / 4096);','retained pool accounting')
    begin=text.index('// ---- memory for the VPU ----');end=text.index('int QcomIrisDeviceSend(',begin)
    text=text[:begin]+'''// ---- firmware-retained memory, no live EL1 SMMU operations ----
}  // namespace
bool QcomIrisDeviceReady(void) {return __atomic_load_n(&v.ready, __ATOMIC_ACQUIRE);}
IOLock *QcomIrisDeviceLock(void) {return v.lock;}
struct qcom_iris_core *QcomIrisDeviceCore(void) {return QcomIrisDeviceReady() ? &v.core : nullptr;}
int QcomIrisDeviceAllocate(uint64_t bytes,QcomIrisBuffer *b) {
    const int e=b5q_video_allocate(bytes,4096,b);
    if(!e)native_video_stats[17]=native_video_stats[17]+1;
    return e;
}
int QcomIrisDeviceMap(IOMemoryDescriptor *m,uint64_t at,uint64_t bytes,QcomIrisBuffer *b) {
    const int e=b5q_video_map(m,at,bytes,b);
    if(!e)native_video_stats[17]=native_video_stats[17]+1;
    return e;
}
void QcomIrisDeviceRelease(QcomIrisBuffer *b) {
    if(b&&b->cpu)native_video_stats[17]=native_video_stats[17]-1;
    b5q_video_release(b);
}
''' +text[end:]
    text=replace(text,'        !mapWindow(v.videocc, SM8550_VIDEO_CC_BASE, SM8550_VIDEO_CC_SIZE) || !mapWindow(v.smmu, SM8550_APPS_SMMU_BASE, SM8550_APPS_SMMU_SIZE))',
        '        !mapWindow(v.videocc, SM8550_VIDEO_CC_BASE, SM8550_VIDEO_CC_SIZE))','no apps SMMU mapping')
    begin=text.index('    // The domain: bank, ASID and slots picked,');end=text.index('    uint8_t *base = static_cast<uint8_t *>(v.uc.cpu);',begin)
    text=text[:begin]+'''    if(!b5q_video_memory_init()){fail(StDomain,-ENXIO);return false;}
    native_video_stats[0]=StDomain;
    // Firmware HFI requires a 1 MiB aligned queue/SFR region.
    const uint32_t region=qcom_iris_uc_region_size();
    if(const int error=b5q_video_allocate(region,1u<<20,&v.uc)){fail(StQueues,error);return false;}
''' +text[end:]
    text=replace(text,'    if (start() && qcom_iris_video_publish) qcom_iris_video_publish();',
        '    if (start() && qcom_iris_video_publish) {IOLog("B5qVideo: stage=ready retained-WBIS=1\\n"); qcom_iris_video_publish();}', 'observed setup success')
    # IONewZero/IODelete are supported by both the module SDK and native XNU.
    # Native XNU still selects its typed allocator for these object types.
    for typename in ('QcomMdtImage','QcomIrisBuffer'):
        text=replace(text,'IOMallocType('+typename+')','IONewZero('+typename+',1)','module allocator '+typename)
    text=replace(text,'IOFreeType(image, QcomMdtImage)','IODelete(image,QcomMdtImage,1)','metadata release')
    if text.count('IOFreeType(b, QcomIrisBuffer)')!=2:raise ValueError('Buffer release shape changed')
    text=text.replace('IOFreeType(b, QcomIrisBuffer)','IODelete(b,QcomIrisBuffer,1)')
    text=replace(text,'    const int rc = QcomIrisDeviceAllocate(bytes, b);',
        '    if(!b)return -ENOMEM;\n    const int rc = QcomIrisDeviceAllocate(bytes, b);','checked object allocation')
    text=replace(text,'    IOBufferMemoryDescriptor *meta = nullptr;\n    Window region = {};',
        '    if(!image){sheng_fw_close(file);return -ENOMEM;}\n    IOBufferMemoryDescriptor *meta = nullptr;\n    Window region = {};','checked firmware metadata allocation')
    # The shared implementation treated submission as success after 2ms. A
    # missing/failed RSC vote must not start a VPU at an unqualified voltage.
    text=replace(text,'        AppsSmmuLock guard;\n        auto send',
        '        AppsSmmuLock guard;\n        if(!guard.ready())ok=false;\n        auto send','RSC mutex check')
    text=replace(text,'            for (unsigned i = 0; i < n; ++i) wr(v.rsc, kRscTcs + writes[i].offset, writes[i].value);\n            IOSleep(2);',
        '''            if(!n)return false;
            wr(v.rsc,kRscTcs,rd(v.rsc,kRscTcs)|(1u<<kOwnedTcs));
            for (unsigned i = 0; i < n; ++i) wr(v.rsc, kRscTcs + writes[i].offset, writes[i].value);
            bool done=false;
            for(unsigned us=0;us<20000;us+=10) {
                if(rd(v.rsc,kRscTcs+layout.irq_status)&(1u<<kOwnedTcs)){done=true;break;}
                IODelay(10);
            }''','bounded RSC completion')
    text=replace(text,'            for (unsigned i = 0; i < m; ++i) wr(v.rsc, kRscTcs + writes[i].offset, writes[i].value);',
        '            for (unsigned i = 0; i < m; ++i) wr(v.rsc, kRscTcs + writes[i].offset, writes[i].value);\n            return done;','RSC result')
    text=replace(text,'            send(mxc.address, mxcLevel);\n            send(mmcx.address, mmcxLevel);',
        '            ok=send(mxc.address,mxcLevel)&&send(mmcx.address,mmcxLevel);','propagate rail failure')
    text=replace(text,'            send(mm1.address, 1u << 30 | 1u << 29 | 1u);',
        '            if(ok)ok=send(mm1.address,1u<<30|1u<<29|1u);','propagate MM1 failure')
    text=replace(text,'#include <IOKit/IOLib.h>','#include <IOKit/IOLib.h>\n#include "B5qFeatures.h"','independent boot/menu video switch')
    text=replace(text,'    PE_parse_boot_argn("sheng-video", &enabled, sizeof enabled);','    enabled=B5qFeatures::option("sheng-video",B5qFeatures::Video);','video menu selection')
    destination=out/'VideoProbe.cpp';destination.write_text(text)
    media=(iris/'kernel/IrisMedia.cpp').read_text()
    media=replace(media,'#include "QcomIrisDevice.h"','#include "QcomIrisDevice.h"\n#include "B5qVideoMemory.h"','bounded copies')
    media=replace(media,'    if (f->error) flags |= BufFlagError;',
        '''    const bool copied=f->data_offset<=slot.length && f->data_size<=slot.length-f->data_offset &&
        b5q_video_output(&slot.map,f->data_offset,f->data_size);
    if (f->error || !copied) flags |= BufFlagError;''','copy decoded picture before delivery')
    media=replace(media,'noteBuffer(m, TypeCaptureMplane, f->index, slot, f->data_size, flags, f->timestamp);',
        'noteBuffer(m, TypeCaptureMplane, f->index, slot, copied?f->data_size:0, flags, f->timestamp);','failed copy never returns stale picture')
    media=replace(media,'if (slot.mapped && slot.memory != memory) unmapSlot(slot);',
        'if (slot.mapped && (slot.memory != memory || slot.length != need)) unmapSlot(slot);','remap resized planes')
    media=replace(media,'else if ((cacheSync(memory, b->plane.bytesused), false)) r = Einval;',
        'else if (!b5q_video_input(&slot.map,b->plane.bytesused)) r = Eio;','copy every queued bitstream')
    (out/'IrisMedia.cpp').write_text(media)
    host=(iris/'kernel/VtHost.cpp').read_text()
    host=replace(host,'#include <IOKit/IOUserClient.h>',
        '#include "B5qIrisUserClient.h"','exact 2022 declaration for the module SDK')
    host=replace(host,'client->callExternalMethod(selector, &arguments)',
        'b5q_iris_call_external(client,selector,&arguments)','native nonvirtual member binding')
    (out/'VtHost.cpp').write_text(host)
    header=(iris/'include/QcomIrisDevice.h').read_text()
    header=replace(header,'    IOMemoryMap *map;','    IOMemoryMap *map;\n    uint64_t clientBytes; /* bounded client plane length, distinct from rounded pool extent */','logical bounds')
    (out/'QcomIrisDevice.h').write_text(header)
    lock=json.loads((iris/'tools/source-lock.json').read_text())['linux']
    for path,digest in lock['files'].items():
        p=out/'linux'/path
        if not p.exists()or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            if not fetch:raise ValueError('Missing pinned Iris file '+path)
            data=pinned_linux(lock,path)
            if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Iris dependency SHA mismatch: '+path)
            p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    linux=out/'linux/drivers/media/platform/qcom/iris'
    c=[p for p in sorted((iris/'src').glob('*.c'))if p.name!='IrisMmu.c']
    sources=[destination,out/'IrisMedia.cpp',package/'VideoToolboxProbe.cpp',out/'VtHost.cpp',
        iris/'kernel/VtParavirt.cpp',*c,linux/'iris_vpu_buffer.c',soc/'Sm8550VideoCc.c']
    (out/'sources.json').write_text(json.dumps(dict(reference_revision=REVISION,hardware_verified=False,
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources},
        excluded=['IrisMmu.c','Sm8550AppsSmmu.c','ArmSmmu4KLive'],
        memory='UEFI retained128MiBWBIS; original b5q DTS both nonsecure CBs dma-coherent; explicit client copies'),indent=2)+'\n')
    return sources,[out,iris/'include',iris/'kernel',iris/'shim',linux,soc,package]
