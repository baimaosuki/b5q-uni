"""Adapt the pinned AudioReach packet encoder to original b5q PRIMARY TDM.

This module does not publish an audio service. The transport, retained DMA,
amplifier lifecycle and HAL integration must succeed before publication.
"""
import hashlib,json,subprocess
from pathlib import Path
from b5q_adsp import REVISION,replace

def prepare_protocol(reference,out):
    reference,out=map(Path,(reference,out));out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION:raise ValueError('AudioReach reference revision changed')
    source=reference/'package/ShengAudioReach.c';header=reference/'package/ShengAudioReach.h'
    text=source.read_text();h=header.read_text()
    h=replace(h,'#define AR_MOD_I2S_SINK 0x0700100Au',
        '#define AR_MOD_I2S_SINK 0x0700100Eu /* original Qualcomm TDM sink; keep shared API spelling */','TDM module ID')
    text=replace(text,'#include "ShengAudioReach.h"','#include "ShengAudioReach.h"\n#include "B5qAudioTdm.h"','original TDM wire settings')
    text=replace(text,'#define PARAM_I2S_INTF 0x08001019u','#define PARAM_I2S_INTF 0x0800101Bu /* PARAM_ID_TDM_INTF_CFG */','TDM parameter ID')
    text=replace(text,'put16(w, f->bits); put16(w, 1); put16(w, f->bits); put16(w, f->bits - 1u);',
        'put16(w, f->bits); put16(w, 1); put16(w, f->bits == 24 ? 32 : f->bits); put16(w, f->bits == 24 ? 27 : f->bits - 1u);',
        'Qualcomm playback24-bit PCM uses32-bit samples/Q27, not packed24')
    begin=text.index('uint32_t ar_config_speaker_device(');end=text.index('\nuint32_t ar_config_mic_device(',begin)
    text=text[:begin]+'''uint32_t ar_config_speaker_device(uint8_t *out, uint32_t capacity, uint32_t port, uint32_t token, const ArFormat *f)
{
    if (!f || f->rate != B5Q_AUDIO_RATE || f->bits != B5Q_AUDIO_ENDPOINT_BITS || f->channels != B5Q_AUDIO_CHANNELS) return 0;
    W w;
    begin(&w, out, capacity, port, AR_APM_IID, token, AR_OP_SET_CFG);
    const uint32_t cmd = cmd_payload_start(&w);
    const uint32_t at = param_begin(&w, AR_IID_SPEAKER_I2S, PARAM_I2S_INTF);
    for (unsigned i = 0; i < sizeof b5q_tdm_stereo_config; ++i) put8(&w, b5q_tdm_stereo_config[i]);
    param_end(&w, at);
    /* APM param_size excludes transport padding; TDM's packed structure is28B. */
    set32(&w, at + 8, sizeof b5q_tdm_stereo_config);
    hw_ep_mf(&w, AR_IID_SPEAKER_I2S, f);
    frame_size_factor(&w, AR_IID_SPEAKER_I2S);
    cmd_payload_end(&w, cmd);
    return finish(&w);
}
''' +text[end:]
    text=replace(text,'    pcm_output(&w, AR_IID_PLAY_CNV, f, DEINTERLEAVED_UNPACKED);',
        '    const ArFormat endpoint = {f->rate, B5Q_AUDIO_ENDPOINT_BITS, f->channels};\n    pcm_output(&w, AR_IID_PLAY_CNV, &endpoint, DEINTERLEAVED_UNPACKED);','16-bit shared PCM converted to original24-bit endpoint')
    generated=out/source.name;generated.write_text(text);(out/header.name).write_text(h)
    (out/'protocol-source.json').write_text(json.dumps(dict(reference_revision=revision,
        original_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [source,header,reference/'package/ShengGpr.c']},
        generated_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in [generated,out/header.name]},
        hardware_verified=False,complete_audio=False,stage='Packet encoding only; no service or hardware ready flag'),indent=2)+'\n')
    return [generated,reference/'package/ShengGpr.c'],[out,reference/'package']

def function_span(text,signature):
    start=text.index(signature);begin=text.index('{',start);end=begin+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return start,end

def replace_function(text,signature,replacement):
    start,end=function_span(text,signature);return text[:start]+replacement+text[end:]

def prepare_service(reference,out):
    reference,out=map(Path,(reference,out));out.mkdir(parents=True,exist_ok=True)
    if subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()!=REVISION:raise ValueError('Audio service reference changed')
    source=reference/'package/AudioProbe.cpp';text=source.read_text()
    text=text[text.index('#include <IOKit/IOLib.h>'):]
    for header in ['AppsSmmuLock.h','ShengCs35l43.h','GeniI2c.h','TouchBoard.h','SmmuBypass.h','QcomRpmh.h']:
        text=replace(text,'#include "'+header+'"\n','','remove sheng board input '+header)
    text=replace(text,'#include <kern/thread.h>','#include <kern/thread.h>\n#include <sys/errno.h>','native errors')
    text=replace(text,'extern kmod_info_t g_kernel_kmod_info;', '''extern kmod_info_t g_kernel_kmod_info;
extern "C" bool b5q_audio_amps_prepare(void),b5q_audio_amps_start(void),b5q_audio_amps_stop(void);
extern "C" bool b5q_audio_dma_buffer(uint8_t **,uint64_t *,uint64_t *);''','Samsung board API')
    for first,last in [('extern "C" {volatile uint32_t native_audio_amps[CS35_AMPS][4];}','namespace {'),
                       ('// Capture periods (mono)','const int16_t kSine[64]'),
                       ('struct Region {','uint64_t nowMs()')]:
        begin=text.index(first);end=text.index(last,begin);text=text[:begin]+text[end:]
    text=replace(text,'    Region gccLow, gcc18, gcc1e, gcc23, gccVote, smmu, se[2];\n    Region pins[16];\n    unsigned pinCount;\n    GeniI2c bus[2];\n    OSSharedPtr<IOBufferMemoryDescriptor> buffer;\n','','remove hardware/MMU state')
    text=replace(text,'    Region low;\n','','remove unowned low buffer')
    text=replace(text,'    OSSharedPtr<IOBufferMemoryDescriptor> control, outRing, inRing;','    OSSharedPtr<IOBufferMemoryDescriptor> control, outRing;','output-only shared service')
    begin=text.index('    // Capture for the plug-in');end=text.index('\n};\nAudio gAudio;',begin);text=text[:begin]+text[end:]
    begin=text.index('// One I2C transfer on bus b,');end=text.index('bool waitUp(',begin)
    text=text[:begin]+'''// Samsung firmware-retained WBIS memory and native TFA9878 board transport.
bool setupBuffer(){
    if(!b5q_audio_dma_buffer(&gAudio.bufferVa,&gAudio.bufferPa,&gAudio.dspAddr))return false;
    native_audio_pa=gAudio.bufferPa;return true;
}
void powerDownAmps(){
    if(!b5q_audio_amps_stop())IOLog("B5qAudio: amp powerdown transaction failed\\n");
}
void cacheClean(const void *p,size_t bytes){
    uint64_t ctr;__asm__ volatile("mrs %0, ctr_el0":"=r"(ctr));const size_t line=4u<<((ctr>>16)&15);
    for(uintptr_t at=reinterpret_cast<uintptr_t>(p)&~(line-1),end=reinterpret_cast<uintptr_t>(p)+bytes;at<end;at+=line)
        __asm__ volatile("dc cvac, %0"::"r"(at):"memory");
    __asm__ volatile("dsb sy":::"memory");
}

''' +text[end:]
    begin=text.index('// ---- the microphones (audio bit 2) ----');end=text.index('bool publishService()',begin);text=text[:begin]+text[end:]
    text=replace_function(text,'void syncCapture()', '')
    begin=text.index('extern "C" {extern volatile int32_t native_mic_capture[8];}');end=text.index('void handle(const ArAnswer &a) {',begin);text=text[:begin]+text[end:]
    text=replace_function(text,'void powerUpAmps()', '')
    begin=text.index('// audio bit 8:');end=text.index('bool openGraphs()',begin);text=text[:begin]+text[end:]
    text=replace(text,'    powerUpAmps();\n    if (!graphs(AR_OP_GRAPH_PREPARE) || !graphs(AR_OP_GRAPH_START)) {powerDownAmps(); return;}',
        '''    if (!graphs(AR_OP_GRAPH_PREPARE) || !graphs(AR_OP_GRAPH_START)) {graphs(AR_OP_GRAPH_STOP);powerDownAmps();return;}
    // The original TFA9878 needs TDM clocks before CLKS/AMPE can succeed.
    if(!b5q_audio_amps_start()){graphs(AR_OP_GRAPH_STOP);powerDownAmps();fail(59);return;}''','start endpoint before amplifier clock wait')
    text=replace(text,'    __atomic_and_fetch(&gAudio.ctl->state, ~ShengAudioOutputRunning, __ATOMIC_ACQ_REL);','    __atomic_and_fetch(&gAudio.ctl->state, ~ShengAudioOutputRunning, __ATOMIC_ACQ_REL);','output state retained')
    text=replace(text,'        if (gAudio.running && !gAudio.statusRead && gAudio.done - gAudio.first == 10) {readAmpStatus(); gAudio.statusRead = true;}\n','', 'remove CS35-only status read')
    text=replace(text,'    } else if (a.opcode == AR_OP_READ_DONE) {\n        captured(a);\n','', 'remove unimplemented capture completion')
    for line in ['            if ((want & ShengAudioInputRunning) && !gAudio.capturing) startInput();\n','            if (!(want & ShengAudioInputRunning) && gAudio.capturing) stopInput();\n']:
        text=replace(text,line,'','output-only service requests')
    text=replace(text,'gAudio.running || gAudio.capturing ? 100 : 1000','gAudio.running ? 100 : 1000','wait output events')
    begin=text.index('    gAudio.inRing = ');end=text.index('    if (!gAudio.control',begin);text=text[:begin]+text[end:]
    text=replace(text,'if (!gAudio.control || !gAudio.outRing || !gAudio.inRing)','if (!gAudio.control || !gAudio.outRing)','output buffers only')
    for line in ['    gAudio.in = static_cast<int16_t *>(gAudio.inRing->getBytesNoCopy());\n','    memset(gAudio.inRing->getBytesNoCopy(), 0, kRingFrames * SHENG_AUDIO_IN_CHANNELS * 2);\n']:
        text=replace(text,line,'','remove absent input ring')
    text=replace(text,'c->in_channels = SHENG_AUDIO_IN_CHANNELS;','c->in_channels = 0;','do not advertise microphone hardware')
    text=replace(text,'int64_t gBaseLead, gBaseCapture;','int64_t gBaseLead;','remove unused capture clock')
    text=replace(text,'            native_mic_stats[1] = (int32_t)a.status;','            native_audio_stats[1] = (int32_t)a.status;','PRM errors audio evidence')
    text=replace(text,'const ArFormat f = {kRate, 16, kChannels};','const ArFormat f = {kRate, 16, kChannels},endpoint={kRate,24,kChannels};','distinct PCM stream/endpoint formats')
    text=replace(text,'++gAudio.token, &f), b, AR_OP_SET_CFG)) {fail(55);','++gAudio.token, &endpoint), b, AR_OP_SET_CFG)) {fail(55);','Samsung24bit endpoint')
    text=replace(text,'    if (!setupSmmu()) {fail(11); return;}\n    stage(20);\n    if (!setupPins()) {fail(20); return;}\n    stage(30);\n    if (!setupClocks()) {fail(30); return;}\n    if (!setupBus(0) || !setupBus(1)) {fail(31); return;}\n    stage(40);\n    if (!setupAmps()) {fail(40); return;}',
        '    stage(40);\n    if(!b5q_audio_amps_prepare()){fail(40);return;}','source-qualified Samsung board path')
    text=replace(text,'    if (gAudio.mode & 4) micBringUp();\n','','no microphone bringup')
    begin=text.index('    if (gAudio.mode & 8) {');end=text.index('    serve(0);',begin);text=text[:begin]+text[end:]
    text=replace(text,'                                  type == ShengAudioMemoryInput ? gAudio.inRing.get() : nullptr;', '                                  nullptr;', 'no input memory mapping')
    for line in ['    case ShengAudioStartInput: __atomic_or_fetch(&gAudio.want, ShengAudioInputRunning, __ATOMIC_ACQ_REL); break;\n','    case ShengAudioStopInput: __atomic_and_fetch(&gAudio.want, ~ShengAudioInputRunning, __ATOMIC_ACQ_REL); break;\n']:
        text=replace(text,line,'','reject unsupported microphone selectors')
    text=replace(text,'!mode || mode > 15 || native_audio_stats[0]', '(mode!=1 && mode!=3) || native_audio_stats[0]','output/service or explicit tone only')
    text=replace(text,'void fail(int step) {native_audio_stats[0] = -step;}','void fail(int step) {native_audio_stats[0] = -step;IOLog("B5qAudio: stage=-%d status=%d\\n",step,native_audio_stats[1]);}','diagnostics')
    text=replace(text,'void stage(int step) {native_audio_stats[0] = step;}','void stage(int step) {native_audio_stats[0] = step;IOLog("B5qAudio: stage=%d\\n",step);}','stage diagnostics')
    text=replace(text,'namespace {','extern "C" {volatile uint64_t native_audio_pa;}\nnamespace {','DMA diagnostics definition')
    text=replace(text,'extern "C" void sheng_audio_service_start(void);','extern "C" bool sheng_audio_service_start(void);','publication reports real result')
    text=replace(text,'    sheng_audio_service_start();\n    return true;','    return sheng_audio_service_start();','no ready state after publication failure')
    text=replace(text,'        const uint32_t want = __atomic_load_n(&gAudio.want, __ATOMIC_ACQUIRE);',
        '''        if(!__atomic_load_n(&gAudio.up,__ATOMIC_ACQUIRE)) {
            powerDownAmps();gAudio.running=false;
            __atomic_and_fetch(&gAudio.ctl->state,~(ShengAudioOutputReady|ShengAudioOutputRunning),__ATOMIC_ACQ_REL);
            __atomic_store_n(&gAudio.serving,0u,__ATOMIC_RELEASE);fail(61);return;
        }
        const uint32_t want = __atomic_load_n(&gAudio.want, __ATOMIC_ACQUIRE);''','DSP disconnect closes real output path')
    text=replace(text,'    if (!publishService()) {fail(58); return;}\n    __atomic_store_n(&gAudio.ctl->state, gAudio.ctl->state | ShengAudioOutputReady, __ATOMIC_RELEASE);\n    __atomic_store_n(&gAudio.serving, 1u, __ATOMIC_RELEASE);',
        '''    __atomic_store_n(&gAudio.ctl->state,gAudio.ctl->state|ShengAudioOutputReady,__ATOMIC_RELEASE);
    __atomic_store_n(&gAudio.serving,1u,__ATOMIC_RELEASE);
    if(!publishService()){
        __atomic_store_n(&gAudio.serving,0u,__ATOMIC_RELEASE);
        __atomic_and_fetch(&gAudio.ctl->state,~(ShengAudioOutputReady|ShengAudioOutputRunning),__ATOMIC_ACQ_REL);
        powerDownAmps();fail(58);return;
    }''','initialize published service memory before client can open it')
    text=replace(text,'#include "ShengAudioAbi.h"','#include "ShengAudioAbi.h"\n#include "B5qAudioQueue.h"','bounded DSP period ownership')
    text=replace(text,'    uint32_t inFlight;','    uint32_t inFlight;\n    B5qAudio::Queue periods;\n    bool outputError=false;','actual outstanding period queue')
    text=replace(text,'    const uint32_t slot = (uint32_t)(n % kSlots);',
        '    const uint32_t slot = (uint32_t)(n % kSlots);\n    uint32_t periodToken=0;if(!gAudio.periods.reserve(slot,periodToken))return false;','reserve before overwriting DMA buffer')
    text=replace(text,'    if (!send(b, ar_write(b, sizeof b, kPort, (uint32_t)n, gAudio.dspAddr + slot * kPeriodBytes, gAudio.handle, kPeriodBytes))) return false;',
        '    if (!send(b, ar_write(b, sizeof b, kPort, periodToken, gAudio.dspAddr + slot * kPeriodBytes, gAudio.handle, kPeriodBytes))) {gAudio.periods.cancel(slot,periodToken);return false;}','only accepted DMA periods stay owned')
    text=replace(text,'    gAudio.inFlight = 0;','    gAudio.inFlight = 0;\n    gAudio.outputError=false;\n    if(!gAudio.periods.init(gAudio.dspAddr,gAudio.handle,kPeriodBytes)){graphs(AR_OP_GRAPH_STOP);powerDownAmps();fail(62);return;}','initialize periods after endpoint restart')
    text=replace(text,'    if (a.opcode == AR_OP_WRITE_DONE) {',
        '''    if (a.opcode == AR_OP_WRITE_DONE) {
        if(a.src_port!=AR_IID_PLAY_SHMEM||!gAudio.periods.complete(a.address,a.handle,a.token)) {
            static unsigned rejected;
            if(rejected++<8)IOLog("B5qAudio: ignored completion port=%x token=%u handle=%u address=%llx\\n",a.src_port,a.token,a.handle,a.address);
            return;
        }
        if(a.status){gAudio.outputError=true;native_audio_stats[1]=(int32_t)a.status;}''','validate exact period completion')
    text=replace(text,'        if (gAudio.running) {\n            if (!gAudio.tone) syncPlayback();',
        '        if (gAudio.running&&!gAudio.outputError) {\n            if (!gAudio.tone) syncPlayback();','do not resubmit after DSP buffer failure')
    text=replace(text,'        if(!__atomic_load_n(&gAudio.up,__ATOMIC_ACQUIRE)) {',
        '''        if(gAudio.outputError){
            stopOutput();__atomic_and_fetch(&gAudio.want,~ShengAudioOutputRunning,__ATOMIC_ACQ_REL);
            gAudio.outputError=false;fail(63);
        }
        if(!__atomic_load_n(&gAudio.up,__ATOMIC_ACQUIRE)) {''','retire failed DSP output on owning thread')
    text=replace(text,'void startOutput() {','void stopOutput();\nvoid startOutput() {','failed queue start may stop output')
    text=replace(text,'    __atomic_or_fetch(&c->state, ShengAudioOutputRunning, __ATOMIC_ACQ_REL);',
        '''    if(gAudio.inFlight!=kInFlight){
        stopOutput();__atomic_and_fetch(&gAudio.want,~ShengAudioOutputRunning,__ATOMIC_ACQ_REL);fail(64);return;
    }
    __atomic_or_fetch(&c->state, ShengAudioOutputRunning, __ATOMIC_ACQ_REL);''','incomplete initial DMA queue is not reported running')
    text=replace(text,'#include <IOKit/IOLib.h>','#include <IOKit/IOLib.h>\n#include "B5qFeatures.h"','independent boot/menu audio switch')
    text=replace(text,'    if (!PE_parse_boot_argn("audio", &mode, sizeof mode) || (mode!=1 && mode!=3) || native_audio_stats[0]) return;',
        '    mode=B5qFeatures::option("audio",B5qFeatures::Audio);\n    if((mode!=1&&mode!=3)||native_audio_stats[0])return;','audio menu/override mode')
    text+='\nextern "C" bool b5q_audio_runtime_enabled(){const unsigned mode=B5qFeatures::option("audio",B5qFeatures::Audio);return mode==1||mode==3;}\n'
    text=replace(text,'if (!graphs(AR_OP_GRAPH_PREPARE) || !graphs(AR_OP_GRAPH_START)) {graphs(AR_OP_GRAPH_STOP);powerDownAmps();return;}',
        'if (!graphs(AR_OP_GRAPH_PREPARE) || !graphs(AR_OP_GRAPH_START)) {graphs(AR_OP_GRAPH_STOP);powerDownAmps();__atomic_and_fetch(&gAudio.want,~ShengAudioOutputRunning,__ATOMIC_ACQ_REL);fail(60);return;}', 'failed graph does not continuously restart hardware')
    text=replace(text,'graphs(AR_OP_GRAPH_STOP);powerDownAmps();fail(59);return;',
        'graphs(AR_OP_GRAPH_STOP);powerDownAmps();__atomic_and_fetch(&gAudio.want,~ShengAudioOutputRunning,__ATOMIC_ACQ_REL);fail(59);return;', 'failed amplifier clears pending start')
    text=replace(text,'graphs(AR_OP_GRAPH_STOP);powerDownAmps();fail(62);return;',
        'graphs(AR_OP_GRAPH_STOP);powerDownAmps();__atomic_and_fetch(&gAudio.want,~ShengAudioOutputRunning,__ATOMIC_ACQ_REL);fail(62);return;', 'bad period map clears pending start')
    probe=out/'AudioProbe.cpp';probe.write_text(text)
    for term in ['0x15000000','Cs35','SmmuBypass','kResetPin','kI2sPins','micBringUp','kLowBuffer']:
        if term in text:raise ValueError('Unadapted audio hardware input: '+term)
    service=out/'ShengAudioService.cpp';service_text=(reference/'package/ShengAudioService.cpp').read_text()
    # macOS HAL deliberately does not request shared-cache clock rewriting.
    # Keep that unsupported on the kernel side too; use the native timeline.
    begin=service_text.index('extern "C" vm_offset_t phystokv(');end=service_text.index('class ShengAudio :',begin)
    service_text=service_text[:begin]+service_text[end:]
    service_text=replace(service_text,'return setHostClock(owner, args->scalarInput[0]);','return kIOReturnUnsupported;','macOS rejects unused shared-cache clock rewrite')
    service_text=replace(service_text,'extern "C" void sheng_audio_service_start(void) {','extern "C" bool sheng_audio_service_start(void) {','return true only after service registration')
    start=service_text.index('extern "C" bool sheng_audio_service_start(void) {')
    prefix,body=service_text[:start],service_text[start:]
    if body.count('        return;')!=2:raise ValueError('Audio service publication failure shape changed')
    body=body.replace('        return;','        return false;')
    body=replace(body,"    audio->release();   // the platform's attachment keeps it","    audio->release();   // the platform's attachment keeps it\n    return true;",'observed publication success')
    service.write_text(prefix+body)
    return [probe,service],[out,reference/'package']

def prepare_hal(reference,out):
    """Keep the native macOS HAL interface, publishing the real stereo output only."""
    import plistlib
    reference,out=map(Path,(reference,out));out.mkdir(parents=True,exist_ok=True)
    if subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()!=REVISION:raise ValueError('HAL reference changed')
    original=reference/'hal/ShengAudioPlugIn.c';text=original.read_text()
    text=replace(text,'#define kPlugInBundleID "org.unixnu.sheng.audio"','#define kPlugInBundleID "org.unixnu.b5q.audio"','b5q HAL identity')
    text=replace(text,'#define kDeviceUID "ShengAudioDevice"','#define kDeviceUID "B5qAudioDevice"','stable output device UID')
    text=replace(text,'#define kModelUID "ShengAudioModel"','#define kModelUID "B5qAudioModel"','model identity')
    text=replace(text,'static int16_t *gOut, *gIn;','static int16_t *gOut;','output-only mapped samples')
    text=replace(text,'    void *control = NULL, *out = NULL, *in = NULL;','    void *control = NULL, *out = NULL;','no absent microphone map')
    text=replace(text,' || mapType(ShengAudioMemoryInput, &in)','', 'no input memory request')
    text=replace(text,'    gOut = out; gIn = in; gControl = c;','    gOut = out; gControl = c;','only output sample ring')
    text=replace(text,'        if (scope != kAudioObjectPropertyScopeOutput) list[n++] = kInStream;\n','','do not publish absent input stream')
    text=replace(text,'                call(ShengAudioStartInput);\n','','only start real speakers')
    text=replace(text,'call(ShengAudioStopOutput); call(ShengAudioStopInput);','call(ShengAudioStopOutput);','stop actual output')
    text=replace(text,'*will = op == kAudioServerPlugInIOOperationWriteMix || op == kAudioServerPlugInIOOperationReadInput;',
        '*will = op == kAudioServerPlugInIOOperationWriteMix;','only output IO operations')
    begin=text.index('    } else if (op == kAudioServerPlugInIOOperationReadInput && stream == kInStream) {');end=text.index('\n    }\n    return 0;',begin)
    text=text[:begin]+text[end:]
    needle='    const AudioObjectPropertySelector s = a->mSelector;'
    text=replace(text,needle,needle+'\n    if(o==kInStream)return kAudioHardwareBadObjectError;','unpublished stream rejects direct queries')
    for name in ['kAudioDevicePropertyDeviceCanBeDefaultDevice','kAudioDevicePropertyDeviceCanBeDefaultSystemDevice']:
        text=replace(text,'case '+name+': REPLY(UInt32, 1);','case '+name+': REPLY(UInt32, a->mScope != kAudioObjectPropertyScopeInput);','cannot be default capture device')
    # Preserve the shared macOS clock policy: no signed-cache modification.
    assert '#if TARGET_OS_OSX'in text and 'diag->host_clock_result = -2;'in text
    text=replace(text,'static inline int16_t toS16(Float32 v) {v *= 32767.0f;',
        'static inline int16_t toS16(Float32 v) {if(!isfinite(v))return 0;v *= 32767.0f;', 'nonfinite client samples never trigger undefined conversion')
    text=replace(text,'    if (!gControl) return 0;\n    // The play position now,',
        '    if(!gControl)return kAudioHardwareNotRunningError;\n    if(o!=kDevice||!info||!main||frames>SHENG_AUDIO_RING_FRAMES||!isfinite(info->mOutputTime.mSampleTime)||info->mOutputTime.mSampleTime<0||info->mOutputTime.mSampleTime>(Float64)(1ULL<<52))return kAudioHardwareIllegalOperationError;\n    // The play position now,', 'bound native HAL input before ring access/conversion')
    text=replace(text,'    do {seq = gControl->out_seq; anchor = gControl->out_anchor_host;} while ((seq & 1) || seq != gControl->out_seq);',
        '    unsigned tries=0;\n    do {if(++tries>32)return kAudioHardwareNotRunningError;seq = gControl->out_seq; anchor = gControl->out_anchor_host;} while ((seq & 1) || seq != gControl->out_seq);', 'failed seqlock writer cannot trap the audio thread')
    generated=out/'ShengAudioPlugIn.c';generated.write_text(text)
    info=plistlib.loads((reference/'hal/Info.plist').read_bytes());info.update(CFBundleIdentifier='org.unixnu.b5q.audio',CFBundleExecutable='B5qAudio',CFBundleName='B5qAudio',CFBundleSupportedPlatforms=['MacOSX'],LSMinimumSystemVersion='27.0');info.pop('MinimumOSVersion')
    (out/'Info.plist').write_bytes(plistlib.dumps(info))
    return generated,info,[reference/'package']
