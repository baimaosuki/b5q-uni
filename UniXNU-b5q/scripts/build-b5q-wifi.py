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
EXPORTS.add('nw_wifi_disconnect_pending')

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
    s=re.sub(r'\bath11k_pci_exit\b','b5q_ath11k_pci_exit',s)
    # A single MSI already requires ASPM off in the original driver because
    # MHI M2 reads can hang. Do not enable firmware IMPS on that unqualified
    # WCN6855 wake path. Multi-MSI and other hardware keep their own policy.
    original='\t\tath11k_info(ab, "leaving PCI ASPM disabled to avoid MHI M2 problems\\n");'
    guarded='''\t{
\t\tif (ab->hw_rev == ATH11K_HW_WCN6855_HW21 && ab->hw_params.idle_ps) {
\t\t\tab->hw_params.idle_ps = false;
\t\t\tath11k_info(ab, "B5qWifi: single-MSI WCN6855 idle_ps=0; IMPS wake deferred\\n");
\t\t}
'''+original+'\n\t}'
    s=replace(s,original,guarded,'single-MSI IMPS guard')
    p.write_text(s)
    p=gen/'pcic.c';s=p.read_text()
    s=replace(s,'''static void ath11k_pcic_ce_tasklet(struct tasklet_struct *t)
{
	struct ath11k_ce_pipe *ce_pipe = from_tasklet(ce_pipe, t, intr_tq);
	int irq_idx = ATH11K_PCI_IRQ_CE0_OFFSET + ce_pipe->pipe_num;

	ath11k_ce_per_engine_service(ce_pipe->ab, ce_pipe->pipe_num);

	enable_irq(ce_pipe->ab->irq_num[irq_idx]);
}''','''static void ath11k_pcic_ce_tasklet(struct tasklet_struct *t)
{
	struct ath11k_ce_pipe *ce_pipe = from_tasklet(ce_pipe, t, intr_tq);

	ath11k_ce_per_engine_service(ce_pipe->ab, ce_pipe->pipe_num);

	ath11k_pcic_ce_irq_enable(ce_pipe->ab, ce_pipe->pipe_num);
}''','single-MSI CE tasklet enable')
    s=replace(s,'\tdisable_irq_nosync(ab->irq_num[irq_idx]);\n\n\ttasklet_schedule(&ce_pipe->intr_tq);',
        '\tath11k_pcic_ce_irq_disable(ab, ce_pipe->pipe_num);\n\n\ttasklet_schedule(&ce_pipe->intr_tq);','single-MSI CE handler disable')
    s=replace(s,'\t\tfor (i = 0; i < irq_grp->num_irq; i++)\n\t\t\tenable_irq(irq_grp->ab->irq_num[irq_grp->irqs[i]]);',
        '\t\tath11k_pcic_ext_grp_enable(irq_grp);','single-MSI ext NAPI enable')
    s=replace(s,'\tfor (i = 0; i < irq_grp->num_irq; i++)\n\t\tdisable_irq_nosync(irq_grp->ab->irq_num[irq_grp->irqs[i]]);\n\n\tnapi_schedule(&irq_grp->napi);',
        '\tath11k_pcic_ext_grp_disable(irq_grp);\n\n\tnapi_schedule(&irq_grp->napi);','single-MSI ext handler disable')
    s=replace(s,'\t\tdisable_irq_nosync(ab->irq_num[irq_idx]);\n\t\tsynchronize_irq(ab->irq_num[irq_idx]);',
        '\t\tath11k_pcic_ce_irq_disable(ab, i);\n\t\tsynchronize_irq(ab->irq_num[irq_idx]);','single-MSI CE shutdown disable')
    p.write_text(s)
    p=gen/'hw.c';s=p.read_text()
    start=s.index('static void ath11k_init_wmi_config_qca6390(')
    stop=s.index('\n}\n',start)+3
    section=s[start:stop]
    anchor='\tconfig->flag1 |= WMI_RSRC_CFG_FLAG1_BSS_CHANNEL_INFO_64;\n}'
    if section.count(anchor)!=1:raise ValueError('qca6390 WMI config tail changed')
    section=section.replace(anchor,
        '\tconfig->twt_ap_pdev_count = ab->hw_params.max_radios ? ab->hw_params.max_radios : 3;\n'
        '\tconfig->twt_ap_sta_count = 8;\n'+anchor)
    s=s[:start]+section+s[stop:]
    p.write_text(s)
    p=gen/'wmi.c';s=p.read_text()
    s=replace(s,'\tmemcpy(&wmi_ab->wlan_resource_config, &config, sizeof(config));\n',
        '\tmemcpy(&wmi_ab->wlan_resource_config, &config, sizeof(config));\n'
        '\tath11k_info(ab, "B5qWifi: wmi-init radios=%u max_radios=%u vdevs=%u peers=%u twt_ap_pdev=%u twt_ap_sta=%u\\n",\n'
        '\t\t    ab->num_radios, ab->hw_params.max_radios, config.num_vdevs, config.num_peers,\n'
        '\t\t    config.twt_ap_pdev_count, config.twt_ap_sta_count);\n',
        'WMI init twt probe')
    if s.count('wait_event_timeout(')!=2:raise ValueError('ath11k WMI ownership wait changed')
    s=s.replace('wait_event_timeout(','wait_event_timeout_once(')
    s=replace(s,'int ath11k_wmi_cmd_send(struct ath11k_pdev_wmi *wmi, struct sk_buff *skb,\n\t\t\tu32 cmd_id)\n{\n',
        'int ath11k_wmi_cmd_send(struct ath11k_pdev_wmi *wmi, struct sk_buff *skb,\n\t\t\tu32 cmd_id)\n{\n'
        '\tb5q_ath11k_trace_tx(1u, cmd_id, skb ? skb->len : 0);\n'
        '\tb5q_ath11k_trace_startup(1u, cmd_id, skb ? skb->len : 0, wmi->wmi_ab->ab->htc.endpoint[wmi->eid].tx_credits);\n',
        'WMI crash history')
    s=replace(s,'\t\tath11k_warn(wmi_ab->ab, "wmi command %d timeout\\n", cmd_id);',
        '\t{\n\t\tath11k_warn(wmi_ab->ab, "wmi command %d timeout\\n", cmd_id);\n'
        '\t\tath11k_warn(ab, "B5qWifi: credit-timeout cmd=%u eid=%u credits=%d idle_ps=%u multi-msi=%u\\n",\n'
        '\t\t\tcmd_id, wmi->eid, ab->htc.endpoint[wmi->eid].tx_credits,\n'
        '\t\t\tab->hw_params.idle_ps, test_bit(ATH11K_FLAG_MULTI_MSI_VECTORS, &ab->dev_flags));\n'
        '\t\tb5q_ath11k_wmi_timeout(cmd_id);\n\t}',
        'WMI credit diagnostic')
    s=replace(s,'\tid = FIELD_GET(WMI_CMD_HDR_CMD_ID, (cmd_hdr->cmd_id));\n\n\ttrace_ath11k_wmi_event',
        '\tid = FIELD_GET(WMI_CMD_HDR_CMD_ID, (cmd_hdr->cmd_id));\n'
        '\tb5q_ath11k_trace_startup(4u, id, skb->len, -1);\n\n\ttrace_ath11k_wmi_event','WMI startup receive')
    # Low-noise pre-crash configuration probes. These run only on vdev
    # create/set-param, STA power save and WMM updates, never on TX/RX data.
    s=replace(s,'\tether_addr_copy(cmd->vdev_macaddr.addr, macaddr);\n',
        '\tether_addr_copy(cmd->vdev_macaddr.addr, macaddr);\n'
        '\tb5q_wifi_mac_context(macaddr);\n'
        '\tath11k_info(ar->ab, "B5qWifi: vdev-create id=%u type=%u subtype=%u pdev=%u mac=%02x:%02x:%02x:%02x:%02x:%02x\\n",\n'
        '\t\t    param->if_id, param->type, param->subtype, param->pdev_id,\n'
        '\t\t    macaddr[0], macaddr[1], macaddr[2], macaddr[3], macaddr[4], macaddr[5]);\n',
        'WMI vdev create probe')
    s=replace(s,'\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_VDEV_SET_PARAM_CMDID);\n',
        '\t{ static u32 b5q_set_param; if (b5q_set_param++ < 32u) ath11k_info(ar->ab, "B5qWifi: vdev-set-param vdev=%u param=%u value=%u\\n", vdev_id, param_id, param_value); }\n'
        '\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_VDEV_SET_PARAM_CMDID);\n',
        'WMI vdev set param probe')
    s=replace(s,'\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_STA_POWERSAVE_PARAM_CMDID);\n',
        '\tath11k_info(ar->ab, "B5qWifi: sta-ps vdev=%u param=%u value=%u\\n", vdev_id, param, param_value);\n'
        '\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_STA_POWERSAVE_PARAM_CMDID);\n',
        'WMI STA PS param probe')
    s=replace(s,'\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_STA_POWERSAVE_MODE_CMDID);\n',
        '\tath11k_info(ar->ab, "B5qWifi: sta-psmode vdev=%d psmode=%u\\n", vdev_id, (u32)psmode);\n'
        '\tret = ath11k_wmi_cmd_send(wmi, skb, WMI_STA_POWERSAVE_MODE_CMDID);\n',
        'WMI STA PS mode probe')
    s=replace(s,'\tret = ath11k_wmi_cmd_send(wmi, skb,\n\t\t\t\t  WMI_VDEV_SET_WMM_PARAMS_CMDID);\n',
        '\tath11k_info(ar->ab, "B5qWifi: wmm-update vdev=%u type=%u BE=%u/%u/%u/%u/%u/%u BK=%u/%u/%u/%u/%u/%u VI=%u/%u/%u/%u/%u/%u VO=%u/%u/%u/%u/%u/%u\\n",\n'
        '\t\t    vdev_id, (u32)wmm_param_type,\n'
        '\t\t    param->ac_be.aifs, param->ac_be.cwmin, param->ac_be.cwmax, param->ac_be.txop, param->ac_be.acm, param->ac_be.no_ack,\n'
        '\t\t    param->ac_bk.aifs, param->ac_bk.cwmin, param->ac_bk.cwmax, param->ac_bk.txop, param->ac_bk.acm, param->ac_bk.no_ack,\n'
        '\t\t    param->ac_vi.aifs, param->ac_vi.cwmin, param->ac_vi.cwmax, param->ac_vi.txop, param->ac_vi.acm, param->ac_vi.no_ack,\n'
        '\t\t    param->ac_vo.aifs, param->ac_vo.cwmin, param->ac_vo.cwmax, param->ac_vo.txop, param->ac_vo.acm, param->ac_vo.no_ack);\n'
        '\tret = ath11k_wmi_cmd_send(wmi, skb,\n\t\t\t\t  WMI_VDEV_SET_WMM_PARAMS_CMDID);\n',
        'WMM four-AC probe')
    p.write_text('extern void b5q_ath11k_trace_tx(u32, u32, size_t);\nextern void b5q_ath11k_trace_startup(u32, u32, size_t, int);\nextern void b5q_ath11k_wmi_timeout(u32);\n'+s)
    p=gen/'htc.c';s=p.read_text()
    s=replace(s,'\tif (eid >= ATH11K_HTC_EP_COUNT) {\n'
        '\t\tath11k_warn(ab, "Invalid endpoint id: %d\\n", eid);\n'
        '\t\treturn -ENOENT;\n\t}\n\n\tskb_push(skb, sizeof(struct ath11k_htc_hdr));',
        '\tif (eid >= ATH11K_HTC_EP_COUNT) {\n'
        '\t\tath11k_warn(ab, "Invalid endpoint id: %d\\n", eid);\n'
        '\t\treturn -ENOENT;\n\t}\n\n'
        '\tif (ep->service_id == ATH11K_HTC_SVC_ID_HTT_DATA_MSG)\n'
        '\t\tb5q_ath11k_trace_tx(2u, skb && skb->len ? *(u8 *)skb->data : 0xffffffffu,\n'
        '\t\t\t\t     skb ? skb->len : 0);\n'
        '\tb5q_ath11k_trace_startup(2u, eid, skb ? skb->len : 0, ep->tx_credits);\n\n'
        '\tskb_push(skb, sizeof(struct ath11k_htc_hdr));',
        'HTT crash history')
    s=replace(s,'\tpayload_len = FIELD_GET(HTC_HDR_PAYLOADLEN, hdr->htc_info);',
        '\tpayload_len = FIELD_GET(HTC_HDR_PAYLOADLEN, hdr->htc_info);\n'
        '\tb5q_ath11k_trace_startup(3u, eid, payload_len, ep->tx_credits);','HTC startup receive')
    p.write_text('extern void b5q_ath11k_trace_tx(u32, u32, size_t);\nextern void b5q_ath11k_trace_startup(u32, u32, size_t, int);\n'+s)
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
        r'\t.link_info_changed = ath11k_mac_op_bss_info_changed,\n\t.vif_cfg_changed = b5q_ath11k_vif_cfg_changed,',s)
    if n!=1:raise ValueError('ath11k BSS operations changed')
    ops=s.split('static const struct ieee80211_ops ath11k_ops = {',1)[1].split('};',1)[0]
    if re.search(r'\.bss_info_changed\s*=',ops) or any(len(re.findall(r'\.'+name+r'\s*=',ops))!=1 for name in ('link_info_changed','vif_cfg_changed')):
        raise ValueError('mac80211 split callbacks must replace the legacy BSS callback')
    # Missing regulatory data must not be followed by vdev/WMM commands.
    # Fail before side effects; regulatory restrictions are never bypassed.
    start=s.index('static int ath11k_mac_op_add_interface(')
    stop=s.index('static void ath11k_mac_op_remove_interface(',start)
    section=s[start:stop]
    section=replace(section,'\tmutex_lock(&ar->conf_mutex);',
        '\tmutex_lock(&ar->conf_mutex);\n\n'
        '\tif (!ab->default_regd[ar->pdev_idx]) {\n'
        '\t\tath11k_warn(ab, "B5qWifi: add-interface deferred: default regd missing\\n");\n'
        '\t\tret = -EAGAIN;\n\t\tgoto err;\n\t}', 'regdomain before vdev')
    s=s[:start]+section+s[stop:]
    s=replace(s,'\tarvif->ar = ar;\n\tarvif->vif = vif;\n',
        '\tarvif->ar = ar;\n\tarvif->vif = vif;\n\n'
        '\t/* The WMI command carries all four ACs on every conf_tx call.\n'
        '\t * mac80211 may configure VO first, so never expose the firmware\n'
        '\t * to the zero-filled values left by the arvif reset. */\n'
        '\tarvif->wmm_params.ac_be = (struct wmi_wmm_params_arg){ .aifs = 3, .cwmin = 15, .cwmax = 1023 };\n'
        '\tarvif->wmm_params.ac_bk = (struct wmi_wmm_params_arg){ .aifs = 7, .cwmin = 15, .cwmax = 1023 };\n'
        '\tarvif->wmm_params.ac_vi = (struct wmi_wmm_params_arg){ .aifs = 2, .cwmin = 7, .cwmax = 15, .txop = 94 };\n'
        '\tarvif->wmm_params.ac_vo = (struct wmi_wmm_params_arg){ .aifs = 2, .cwmin = 3, .cwmax = 7, .txop = 47 };\n',
        'complete WMM defaults')
    s=replace(s,'\tvif->driver_flags |= IEEE80211_VIF_SUPPORTS_UAPSD;\n\n\tmutex_lock(&ar->conf_mutex);\n',
        '\tvif->driver_flags |= IEEE80211_VIF_SUPPORTS_UAPSD;\n\n'
        '\t{\n\t\tstruct ieee80211_regdomain *b5q_regd = ab->default_regd[ar->pdev_idx];\n'
        '\t\tath11k_info(ab, "B5qWifi: add-interface type=%u state=%u regd=%02x%02x dfs=%u\\n",\n'
        '\t\t\t    (u32)vif->type, (u32)ar->state, b5q_regd ? (unsigned)(unsigned char)b5q_regd->alpha2[0] : 0,\n'
        '\t\t\t    b5q_regd ? (unsigned)(unsigned char)b5q_regd->alpha2[1] : 0, b5q_regd ? (u32)b5q_regd->dfs_region : 0);\n'
        '\t}\n\n\tmutex_lock(&ar->conf_mutex);\n',
        'MAC add-interface probe')
    s=replace(s,'\tstruct wmi_wmm_params_arg *p = NULL;\n\tint ret;\n\n\tmutex_lock(&ar->conf_mutex);\n',
        '\tstruct wmi_wmm_params_arg *p = NULL;\n\tint ret;\n\n\tmutex_lock(&ar->conf_mutex);\n'
        '\tath11k_info(ar->ab, "B5qWifi: conf-tx type=%u ac=%u aifs=%u cwmin=%u cwmax=%u txop=%u uapsd=%u state=%u\\n",\n'
        '\t\t    (u32)vif->type, ac, params->aifs, params->cw_min, params->cw_max, params->txop, params->uapsd, (u32)ar->state);\n',
        'MAC conf-tx probe')
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
        native_mac80211=True,legacy_station_linked=False,hardware_verified=False,
        wcn6855_wmm_defaults='BE=3/15/1023 BK=7/15/1023 VI=2/7/15/94 VO=2/3/7/47',
        wcn6855_twt_ap_config='twt_ap_pdev_count=max_radios(fallback 3) twt_ap_sta_count=8',
        fatal_tx_history='32 lock-free committed WMI/HTT entries, a 32-entry WMI RX ring (last 16 dumped) and MHI/BHI crash registers'),indent=2)+'\n')
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
            if name=='shim/src/lx_rt.c':
                selected=out/'b5q_lx_rt.c';text=src.read_text()
                text=replace(text,'void lx_enable_irq(unsigned int irq) { for (int i = 0; i < 64; i++) if (g_irq[i].used && g_irq[i].strict && g_irq[i].irq == irq && g_irq[i].disabled) g_irq[i].disabled--; }',
                    'void lx_enable_irq(unsigned int irq) { for (int i = 0; i < 64; i++) if (g_irq[i].used && g_irq[i].strict && g_irq[i].irq == irq && g_irq[i].disabled) g_irq[i].disabled--; }\n'
                    'int lx_irq_disabled(unsigned int irq) { int depth=0; for (int i=0;i<64;i++) if (g_irq[i].used && g_irq[i].strict && g_irq[i].irq==irq && g_irq[i].disabled>depth) depth=g_irq[i].disabled; return depth; }',
                    'shared IRQ diagnostic depth')
                selected.write_text(text);src=selected
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
