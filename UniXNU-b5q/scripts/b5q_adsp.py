"""Adapt the pinned shared ADSP transport using source-verified b5q inputs.

The generated files keep shared runtime symbols. Only the carveout length,
firmware source policy and failure handling are board adaptations.
"""
import hashlib,json,subprocess
from pathlib import Path
REVISION='6c42e1055ffb3b335fda991190ad221edaa7af3c'
CORES=['QcomMdt','QcomSmem','QcomSmp2p','QcomGlink','QcomQmp','QcomQrtr','ShengQrtr']

def replace(text,old,new,meaning):
    if text.count(old)!=1:raise ValueError('Pinned ADSP source changed: '+meaning)
    return text.replace(old,new)

def prepare(reference,out):
    reference,out=map(Path,(reference,out));out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION:raise ValueError('ADSP reference revision changed')
    package=reference/'package';path=package/'AdspProbe.cpp';text=path.read_text()
    text=replace(text,'#include <kern/thread.h>',
        '#include <kern/thread.h>\nextern "C" kern_return_t clear_wait(thread_t,wait_result_t);',
        'source-private clear_wait declaration for the SDK target checker')
    text=replace(text,'#include <sys/errno.h>',
        '#include <sys/errno.h>\n#include "AppsSmmuLock.h"\n#include "B5qAossQmpLock.h"',
        'shared RSC register mutex; no SMMU MMIO')
    text=replace(text,'if (gTcs < 0) {',
        'if (gTcs < 0) {\n        AppsSmmuLock guard;\n        if (!guard.ready()) return -16;',
        'serialize shared IRQ_ENABLE RMW with USB/WCN votes')
    text=replace(text,'    qcom_qmp_init(&gQmp,',
        '    {\n    B5qAossQmpLock guard;\n    if(!guard.ready()){fail(StLoadState, -12); release(dtb); release(adsp); return false;}\n    qcom_qmp_init(&gQmp,',
        'serialize AOSS QMP handshake/send/wait/abandon with WCN')
    text=replace(text,'    stage(StLoadState);',
        '    } // Release AOSS QMP before RPMh votes.\n    stage(StLoadState);',
        'limit shared AOSS mutex to the mailbox transaction')
    text=replace(text,'kAdspSize = 0x4680000','kAdspSize = 0x59b4000','Samsung ADSP reserved length')
    text=replace(text,'const char *sources[3] = {"modem:", "/private/var/firmware/qcom/sm8550/sheng", "/private/var/ngpu/fw"};',
        'const char *sources[1] = {"/private/var/ngpu/firmware/qcom/sm8550/b5q"};',
        'read only staged b5q firmware, no partition discovery')
    text=replace(text,'const unsigned count = chosen ? 1 : 3;',
        'const unsigned count = sizeof(sources)/sizeof(sources[0]);',
        'firmware source count')
    text=replace(text,'void fail(int step, int error) {native_adsp_stats[1] = error; native_adsp_stats[0] = -step;}',
        'void fail(int step, int error) {native_adsp_stats[1] = error; native_adsp_stats[0] = -step; IOLog("B5qAdsp: stage=-%d error=%d\\n",step,error);}',
        'bounded failure diagnostics')
    text=replace(text,'void stage(int value) {native_adsp_stats[0] = value;}',
        'void stage(int value) {native_adsp_stats[0] = value; IOLog("B5qAdsp: stage=%d\\n",value);}',
        'stage diagnostics')
    # A timed-out RPMh vote is a failed transaction; never authenticate/start
    # a DSP merely because a request was submitted to the RSC.
    text=replace(text,'(done ? 0 : 1u << 15));\n    return 0;',
        '(done ? 0 : 1u << 15));\n    return done ? 0 : -60;',
        'RPMh completion must be observed')
    text=replace(text,'#include <IOKit/IOLib.h>','#include <IOKit/IOLib.h>\n#include "B5qFeatures.h"','independent boot/menu ADSP switch')
    text=replace(text,'    PE_parse_boot_argn("adsp", &mode, sizeof mode);','    mode=B5qFeatures::option("adsp",B5qFeatures::Adsp,2);','selected ADSP mode')
    text=replace(text,'    if (!PE_parse_boot_argn("adsp", &mode, sizeof mode) || !mode || native_adsp_stats[0]) return;',
        '    mode=B5qFeatures::option("adsp",B5qFeatures::Adsp,2);\n    if(!mode||native_adsp_stats[0])return;','ADSP probe selection')
    destination=out/'AdspProbe.cpp';destination.write_text(text)
    board=Path(__file__).resolve().parents[1]/'package'
    sources=[destination]+[(board if name=='QcomQmp' else package)/(name+'.c')for name in CORES]
    (out/'sources.json').write_text(json.dumps(dict(reference_revision=revision,
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [path,*sources[1:]]},
        generated_sha256=hashlib.sha256(destination.read_bytes()).hexdigest(),
        hardware_verified=False,stage_complete=False,
        board_evidence='Original b5q adspslpi9ea00000+59b4000, q6dtb9e980000+80000; stock ADSP/DTB MDT files',
        pending='Target/callback audit, Samsung audio topology, firmware DMA and final integration'),indent=2)+'\n')
    return sources,[board,package]
