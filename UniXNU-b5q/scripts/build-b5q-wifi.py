#!/usr/bin/env python3
"""Compile locked Linux ath11k with shared mainline mac80211/cfg80211.

Board power, PCIe, firmware HAL DMA and native networking are separate objects.
No WCN7850 ath12k core or retired in-kernel station/authenticator is selected.
"""
import argparse,hashlib,json,os,re,shlex,shutil,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

DEVICE=Path(os.environ.get('UNIXNU_DEVICE',Path(__file__).resolve().parents[1])).resolve()
LINUX='458c6079fc1d41d564c37679c8ace02cd83ee817'
EXPORTS=set('nw_wifi_start nw_wifi_step nw_wifi_stop nw_wifi_stats nw_wifi_set_events nw_wifi_scan nw_wifi_scan_frequencies nw_wifi_bss_count nw_wifi_bss_get nw_wifi_connect nw_wifi_disconnect nw_wifi_tx nw_wifi_status_get nw_wifi_where nw_wifi_power nw_wifi_tx_packet nw_wifi_link_state nw_wifi_tx_reasons nw_wifi_buffer_stats_get nw_wifi_buffer_pool_configure nw_wifi_buffer_pool_trim nw_wifi_irq_mode nw_wifi_irq_pending nw_wifi_wait_ms nw_wifi_poll nw_wifi_control_transport_set nw_wifi_control_attach nw_wifi_control_detach nw_wifi_control_receive nw_wifi_control_writable nw_wifi_control_stats_get nw_wifi_set_platform'.split())

def replace(s,old,new,name):
    if s.count(old)!=1:raise ValueError('Pinned ath11k '+name+' ABI changed')
    return s.replace(old,new)

def prepare(module,out):
    linux=module/'deps/linux'
    revision=subprocess.check_output(['git','-C',str(linux),'rev-parse','HEAD'],text=True).strip()
    if revision!=LINUX:raise ValueError('Linux source revision differs')
    subprocess.run([sys.executable,str(module/'tools/fetch-sources.py'),'--check'],check=True)
    if not (module/'out/mac80211/main.c').exists():subprocess.run(['bash',str(module/'tools/prepare.sh')],check=True)
    src=linux/'drivers/net/wireless/ath/ath11k';gen=out/'ath11k';gen.mkdir(parents=True,exist_ok=True)
    hashes={}
    for p in src.glob('*'):
        if p.suffix in ('.c','.h') and p.name!='trace.h':
            (gen/p.name).write_bytes(p.read_bytes());hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (out/'spectral_common.h').write_bytes((src.parent/'spectral_common.h').read_bytes())
    traces=sorted({n for p in src.glob('*.[ch]')for n in re.findall(r'\btrace_ath11k_[a-z0-9_]+',p.read_text())})
    (gen/'trace.h').write_text('\n'.join('#define '+n+'(...) '+('0' if n.endswith('_enabled')else'((void)0)')for n in traces)+'\n')
    for name in ('core.h','dp_rx.c'):
        p=gen/name;p.write_text(p.read_text().replace('unsigned long jiffies;','unsigned long bp_jiffies;').replace('bp_stats->jiffies','bp_stats->bp_jiffies'))
    p=gen/'pci.c';s=p.read_text()
    s=replace(s,'static int ath11k_pci_init(void)','int b5q_ath11k_pci_init(void)','PCI init')
    s=replace(s,'static void ath11k_pci_exit(void)','void b5q_ath11k_pci_exit(void)','PCI exit')
    s=re.sub(r'\bath11k_pci_init\b','b5q_ath11k_pci_init',s)
    s=re.sub(r'\bath11k_pci_exit\b','b5q_ath11k_pci_exit',s);p.write_text(s)
    p=gen/'wmi.c';s=p.read_text()
    if s.count('wait_event_timeout(')!=2:raise ValueError('ath11k WMI ownership wait changed')
    p.write_text(s.replace('wait_event_timeout(','wait_event_timeout_once('))
    # ath11k's real unified callback also handles the split notifications the
    # same-version native mac80211 emits. Reuse the community adapter bridge.
    p=gen/'mac.c';s=p.read_text()
    bridge='''static void b5q_ath11k_vif_cfg_changed(struct ieee80211_hw *hw,
        struct ieee80211_vif *vif, u64 changed)
{
    ath11k_mac_op_bss_info_changed(hw, vif, &vif->bss_conf, changed);
}

'''
    s=replace(s,'static const struct ieee80211_ops ath11k_ops = {',bridge+'static const struct ieee80211_ops ath11k_ops = {','mac80211 ops')
    s,n=re.subn(r'(\t\.bss_info_changed\s*= ath11k_mac_op_bss_info_changed,)',
        r'\1\n\t.link_info_changed = ath11k_mac_op_bss_info_changed,\n\t.vif_cfg_changed = b5q_ath11k_vif_cfg_changed,',s)
    if n!=1:raise ValueError('ath11k BSS operations changed')
    p.write_text(s)
    p=gen/'mhi.c';s=p.read_text()
    mark='\tstruct ath11k_pci *ab_pci = ath11k_pci_priv(ab);\n\n\tath11k_dbg(ab, ATH11K_DBG_BOOT, "notify status reason %s\\n",'
    s=replace(s,mark,'\tstruct ath11k_pci *ab_pci = ath11k_pci_priv(ab);\n\n'
        '\tif (cb == MHI_CB_SYS_ERROR || cb == MHI_CB_FATAL_ERROR || cb == MHI_CB_EE_RDDM) {\n'
        '\t\tb5q_ath11k_mhi_failed(mhi_cntrl, cb); return;\n\t}\n\n'
        '\tath11k_dbg(ab, ATH11K_DBG_BOOT, "notify status reason %s\\n",','MHI fatal callback')
    p.write_text('struct mhi_controller;\nextern void b5q_ath11k_mhi_failed(struct mhi_controller *, int);\n'+s)
    p=gen/'core.c';s=p.read_text()
    needle='\tbd->fw = ath11k_core_firmware_request(ab, name);'
    replacement='    char b5q_bdf[64];\n    if (!strcmp(name, ATH11K_DEFAULT_BOARD_FILE)) {\n        if (!b5q_wifi_bdf_name(b5q_bdf, sizeof(b5q_bdf), ab->qmi.target.chip_id, ab->qmi.target.board_id, 0)) return -EINVAL;\n        name=b5q_bdf;\n        ath11k_info(ab, "B5qWifi: QMI chip=%x board=%x BDF=%s\\n", ab->qmi.target.chip_id, ab->qmi.target.board_id, name);\n    }\n'+needle
    s=replace(s,needle,replacement,'Samsung QMI BDF filename')
    p.write_text('#include "B5qWifiFirmwareName.h"\n'+s)
    (out/'source-inputs.json').write_text(json.dumps(dict(linux_revision=revision,ath11k_original_sha256=hashes,
        native_mac80211=True,legacy_station_linked=False,hardware_verified=False),indent=2)+'\n')
    return gen

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--module',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--compiler',type=Path);p.add_argument('--llvm',type=Path);p.add_argument('--jobs',type=int,default=4)
    p.add_argument('--core-only',action='store_true',help='Target compile driver core first; never a complete-stage result')
    a=p.parse_args();module=a.module.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    gen=prepare(module,out)
    cc=str(a.compiler or subprocess.check_output(['xcrun','-f','clang'],text=True).strip())
    resource=subprocess.check_output([cc,'-print-resource-dir'],text=True).strip()+'/include'
    overlay=DEVICE/'package/B5qAth11kCompat'
    flags=['-target','arm64e-apple-ios27.0','-mkernel','-O2','-ffreestanding','-fno-builtin','-fno-common',
        '-fno-strict-aliasing','-fwrapv','-fno-stack-protector','-fno-delete-null-pointer-checks','-mgeneral-regs-only',
        '-std=gnu11','-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics',
        '-fptrauth-function-pointer-type-discrimination','-w','-nostdinc',
        '-DCONFIG_ATH11K_PCI=1','-DCONFIG_ATH11K_DEBUG=1','-DCONFIG_CFG80211=1','-DCONFIG_MAC80211=1',
        '-DCONFIG_MAC80211_STA_HASH_MAX_SIZE=0','-DCONFIG_MAC80211_RC_DEFAULT=""',
        '-isystem',str(module/'shim/libc'),'-isystem',resource,
        '-I',str(DEVICE/'package'),'-I',str(overlay),'-include',str(overlay/'B5qAth11kCompat.h'),
        '-I',str(module/'shim/include'),'-I',str(module/'include'),'-I',str(module/'out/pinned'),
        '-I',str(module/'src'),'-I',str(gen),'-I',str(module/'out')]
    core='core hal hal_tx hal_rx wmi mac reg htc qmi dp dp_tx dp_rx ce peer dbring hw pcic fw p2p mhi pci'.split()
    raw=out/'raw';raw.mkdir(exist_ok=True)
    jobs=[(gen/(n+'.c'),raw/('ath11k_'+n+'.o'),[])for n in core]
    if not a.core_only:
        trees={'mhi':'mhi-src','qmi':'os-src','mac80211':'mac80211','cfg80211':'cfg80211','crypto':'crypto'}
        for line in (module/'tools/sources.txt').read_text().splitlines():
            line=line.strip()
            if not line or line.startswith('#'):continue
            tree,_,name=line.partition(':') if ':'in line else ('','',line)
            if tree=='ath12k' or name in ('src/nw_wifi.c','src/nw_mhi.c'):continue
            if tree in trees:src=module/'out'/trees[tree]/name
            elif tree=='generated':src=module/'out'/name
            else:src=module/name
            from b5q_wifi import select_shared
            original_src=src
            src=select_shared(src,out)
            if name=='src/nw_debug.c':
                selected=out/'b5q_ath11k_debug.c'
                debug=src.read_text().replace('ath12k','ath11k')
                debug=debug.replace('void __ath11k_warn(struct device *dev,','void ath11k_warn(struct ath11k_base *ab,').replace('(void)dev; va_list ap;','(void)ab; va_list ap;')
                selected.write_text(debug);src=selected
            if name=='src/nw_pci.c':
                selected=out/'b5q_ath11k_pci.c'
                text=src.read_text()
                text=replace(text,'  (void)flags; unsigned int n = max < 32 ? max : 32; if (n < min) return -ENOSPC;',
                    '  (void)flags; if (min > 1) return -ENOSPC; unsigned int n = 1; (void)max;',
                    'native single-vector MSI fallback')
                selected.write_text(text);src=selected
            extra=[]
            if tree in trees:extra=['-I',str(module/'out'/trees[tree])]
            if tree=='generated' or name.startswith('src/nw_cfg80211_'):extra=['-I',str(module/'out/cfg80211')]
            if name=='src/nw_fils.c':extra=['-I',str(module/'out/mac80211')]
            if tree=='crypto' or name=='src/nw_crypto_mac80211.c':extra=['-I',str(module/'shim/crypto'),'-I',str(module/'out/crypto'),'-I',str(module/'out/mac80211')]
            if tree=='crypto' and name=='aes-siv.c':extra+=['-Daes_siv_encrypt=nw_aes_siv_encrypt','-Daes_siv_decrypt=nw_aes_siv_decrypt']
            jobs.append((src,raw/((tree+'_' if tree else 'shared_')+original_src.stem+'.o'),extra))
        jobs.append((DEVICE/'package/B5qAth11k.c',raw/'B5qAth11k.o',[]))
    def compile(job):
        src,obj,extra=job;dep=obj.with_suffix('.d');identity=obj.with_suffix('.inputs.json');cmd=[cc,*extra,*flags,'-MD','-MF',str(dep),'-c',str(src),'-o',str(obj)]
        if obj.exists()and identity.exists():
            j=json.loads(identity.read_text())
            if j.get('command')==cmd and j.get('object_sha256')==hashlib.sha256(obj.read_bytes()).hexdigest()and all(Path(n).is_file()and hashlib.sha256(Path(n).read_bytes()).hexdigest()==v for n,v in j['dependencies'].items()):return None
        result=subprocess.run(cmd,text=True,capture_output=True);obj.with_suffix('.log').write_text(result.stdout+result.stderr)
        if result.returncode:return obj.name
        deps=shlex.split(dep.read_text().replace('\\\n','').partition(':')[2])
        identity.write_text(json.dumps(dict(command=cmd,object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),dependencies={n:hashlib.sha256(Path(n).read_bytes()).hexdigest()for n in deps}),indent=2)+'\n')
        return None
    with ThreadPoolExecutor(a.jobs)as pool:failed=[v for v in pool.map(compile,jobs)if v]
    objects={}
    if not failed:
        # Exactly the mainline namespace boundary: Linux globals may never
        # interpose on XNU's socket, crypto, timer, locking or allocator APIs.
        from b5q_abi import object_symbols
        names={name for _,obj,_ in jobs for name,_,kind in object_symbols(obj.read_bytes())
            if kind&1 and kind&0xe and name not in {'_'+n for n in EXPORTS}}
        mapping=out/'rename.txt';mapping.write_text(''.join(n+' _nwk'+n+'\n' for n in sorted(names)))
        llvm=a.llvm or Path(subprocess.check_output(['brew','--prefix','llvm'],text=True).strip())/'bin'
        for _,obj,_ in jobs:
            selected=out/obj.name;shutil.copyfile(obj,selected)
            subprocess.run([str(llvm/'llvm-objcopy'),'--redefine-syms='+str(mapping),str(selected)],check=True)
            objects[str(selected)]=hashlib.sha256(selected.read_bytes()).hexdigest()
    (out/'compile-result.json').write_text(json.dumps(dict(core_only=a.core_only,complete_stage=False,failed=failed,passed=not failed,objects=objects),indent=2)+'\n')
    if failed:raise SystemExit('ath11k target failures (logs retained): '+', '.join(failed))
    print('PASS ath11k target core objects; full P2+P3 integration gate remains pending')
if __name__=='__main__':main()
