"""Select the pinned OS-only network adapter; no sheng hardware is copied."""
import hashlib,json,subprocess
from pathlib import Path
REVISION='6c42e1055ffb3b335fda991190ad221edaa7af3c'
def select_shared(source,out):
    source,out=Path(source),Path(out)
    if source.name=='nw_mainline.c':
        text=source.read_text()
        anchor='void nw_wifi_disconnect(void) {'
        if text.count(anchor)!=1:raise ValueError('Pinned mainline disconnect ABI changed')
        text=text.replace(anchor,'''int nw_wifi_disconnect_pending(void) {
  lx_shared_spin_lock(&boundary_lock);
  const int pending = ui.operation == NW_CONTROL_DISCONNECT_REQUEST;
  lx_shared_spin_unlock(&boundary_lock);
  return pending;
}
'''+anchor)
        out.mkdir(parents=True,exist_ok=True);target=out/'b5q_nw_mainline.c';target.write_text(text);return target
    if source.name!='scan.c' or source.parent.name!='cfg80211':return source
    text=source.read_text();old='!memcmp(elem->data + match_offset, match, match_len)'
    if text.count(old)!=1:raise ValueError('Pinned cfg80211 empty-match ABI changed')
    text=text.replace(old,'(!match_len || !memcmp(elem->data + match_offset, match, match_len))')
    out.mkdir(parents=True,exist_ok=True);target=out/'b5q_cfg80211_scan.c';target.write_text(text)
    return target
def prepare(reference,out):
    reference,out=Path(reference),Path(out);out.mkdir(parents=True,exist_ok=True)
    revision=subprocess.check_output(['git','-C',str(reference),'rev-parse','HEAD'],text=True).strip()
    if revision!=REVISION:raise ValueError('Native network reference revision changed')
    source=reference/'package/WifiNet.cpp';text=source.read_text()
    # BootUiTrace is not part of this image. Kernel final links do not permit
    # unresolved weak imports either. Omit only its optional stack/IPI
    # diagnostic calls; preserve real packet/stall counts and all networking.
    log_anchor = '''void log(int level, const char *fmt, ...) __attribute__((format(printf, 2, 3)));
void log(int level, const char *fmt, ...) {
  char line[160]; va_list ap; va_start(ap, fmt); vsnprintf(line, sizeof line, fmt, ap); va_end(ap);
  native_wifi_logf(level, "%s", line);
}'''
    probe_helpers = r'''
// Public SDK omits this KERNEL_PRIVATE KPI; the pinned XNU exports it.
extern "C" uint32_t ifnet_eflags(ifnet_t);
extern "C" int nw_wifi_disconnect_pending(void);
extern "C" int proc_selfpid(void);
static uint32_t gLeaveContextLogged, gJoinContextLogged, gPreJoinDrainLogged;
static uint32_t gIfBindLogged;
static void log_ifnet_bind(const char *where) {
  if (!gIf || __atomic_exchange_n(&gIfBindLogged, 1u, __ATOMIC_ACQ_REL)) return;
  uint8_t lladdr[6] = {};
  if (ifnet_lladdr_copy_bytes(gIf, lladdr, sizeof lladdr)) memset(lladdr, 0, sizeof lladdr);
  log(6, "wifi-net: ifnet-bind where=%s if=%s%u flags=0x%x eflags=0x%x cap=0x%x lladdr=%02x:%02x:%02x:%02x:%02x:%02x gmac=%02x:%02x:%02x:%02x:%02x:%02x",
      where, ifnet_name(gIf), ifnet_unit(gIf), unsigned(ifnet_flags(gIf)), ifnet_eflags(gIf), ifnet_capabilities_enabled(gIf),
      lladdr[0], lladdr[1], lladdr[2], lladdr[3], lladdr[4], lladdr[5],
      gMac[0], gMac[1], gMac[2], gMac[3], gMac[4], gMac[5]);
}
static uint32_t gFrameProbeLogged, gFrameProbeRx, gFrameProbeTx;
static void probe_frame(const uint8_t *frame, size_t length, bool out) {
  if (!frame || length < 14 || __atomic_load_n(&gFrameProbeLogged, __ATOMIC_RELAXED) >= 64) return;
  const uint16_t type = uint16_t((frame[12] << 8) | frame[13]);
  bool dhcp = false;
  if (type == 0x0800 && length >= 34 && frame[23] == 17) {
    const unsigned ihl = unsigned(frame[14] & 15) * 4;
    if (ihl >= 20 && 14 + ihl + 4 <= length) {
      const uint8_t *udp = frame + 14 + ihl;
      const unsigned source = (udp[0] << 8) | udp[1], destination = (udp[2] << 8) | udp[3];
      dhcp = (source == 67 || source == 68) && (destination == 67 || destination == 68);
    }
  }
  uint32_t *seen = out ? &gFrameProbeTx : &gFrameProbeRx;
  const bool limited = type != 0x0806 && !dhcp;
  if (limited && __atomic_load_n(seen, __ATOMIC_RELAXED) >= 24) return;
  if (__atomic_fetch_add(&gFrameProbeLogged, 1u, __ATOMIC_ACQ_REL) >= 64) return;
  if (__atomic_fetch_add(seen, 1u, __ATOMIC_ACQ_REL) >= 24 && limited) return;
  log(6, "wifi-net: frame dir=%s len=%zu dst=%02x:%02x:%02x:%02x:%02x:%02x src=%02x:%02x:%02x:%02x:%02x:%02x type=%04x",
      out ? "tx" : "rx", length, frame[0], frame[1], frame[2], frame[3], frame[4], frame[5],
      frame[6], frame[7], frame[8], frame[9], frame[10], frame[11], type);
}
'''
    replacements=[
        (log_anchor, log_anchor + probe_helpers),
        ('    const errno_t error = ifnet_input(gIf, packets, &inc);', '''    const errno_t error = ifnet_input(gIf, packets, &inc);
    // dlil's Skywalk path does not apply inc to the legacy ifnet counters.
    if (!error && gIf && (ifnet_capabilities_enabled(gIf) & 0x400u)) {
      ifnet_stat_increment_in(gIf, count, bytes, 0);
    }'''),
        ('    if (current.state < NW_STA_AUTH) return 0;',
         '    if (current.state < NW_STA_AUTH && !nw_wifi_disconnect_pending()) return 0;'),
        ('''      if (current.state >= NW_STA_AUTH) {''', '''      if (current.state >= NW_STA_AUTH || nw_wifi_disconnect_pending()) {'''),
        ('''        int error = drain_disconnect(); if (error) return error;''', '''        const uint64_t began = continuous_ms();
        int error = drain_disconnect();
        if (__atomic_fetch_add(&gPreJoinDrainLogged, 1u, __ATOMIC_RELAXED) < 32u)
          log(6, "wifi-net: pre-join-drain rc=%d waited_ms=%u prev_state=%d", error,
              unsigned(continuous_ms() - began), int(current.state));
        if (error) return error;'''),
        ('''      gKeyed = hasKey; int r = nw_wifi_connect(''', '''      if (__atomic_fetch_add(&gJoinContextLogged, 1u, __ATOMIC_RELAXED) < 32u) {
        unsigned cached_freq = 0;
        for (int i = 0; i < nw_wifi_bss_count(); i++) {
          nw_bss_info b{};
          if (!nw_wifi_bss_get(i, &b) && b.ssid_len == a.ssid_length &&
              !memcmp(b.ssid, a.ssid, a.ssid_length) && (!hasBssid || !memcmp(b.bssid, a.bssid, 6))) {
            cached_freq = b.freq_mhz; break;
          }
        }
        char prefix[17] = {};static const char hex[] = "0123456789abcdef";
        const unsigned n = a.ssid_length < 8 ? a.ssid_length : 8;
        for (unsigned i = 0; i < n; i++) { prefix[2*i] = hex[a.ssid[i] >> 4];prefix[2*i+1] = hex[a.ssid[i] & 15]; }
        log(6, "wifi-net: join-ctx ssid_len=%u ssid_hex=%s has_bssid=%u cached_freq=%u", a.ssid_length, prefix, hasBssid, cached_freq);
      }
      gKeyed = hasKey; int r = nw_wifi_connect('''),
        ('''    case kDisassociate: case kDeauth: log(6, "wifi-net: leave"); disconnect_user(); return 0;''', '''    case kDisassociate: case kDeauth: {
      if (__atomic_fetch_add(&gLeaveContextLogged, 1u, __ATOMIC_RELAXED) < 32u) {
        nw_wifi_status st{};nw_wifi_status_get(&st);
        struct ifnet_stats_param counts{};if (gIf) ifnet_stat(gIf, &counts);
        const uint64_t up = __atomic_load_n(&gLinkUpMs, __ATOMIC_ACQUIRE), now = continuous_ms();
        log(6, "wifi-net: leave-ctx type=%u pid=%d state=%d link_up_ms=%llu in_pkts=%llu out_pkts=%llu",
            type, proc_selfpid(), int(st.state), up && now >= up ? now - up : 0,
            counts.packets_in, counts.packets_out);
      }
      log(6, "wifi-net: leave"); disconnect_user(); return 0; }'''),
        ('  gLinkUpMs = up ? continuous_ms() : 0;',
         '  __atomic_store_n(&gLinkUpMs, up ? continuous_ms() : 0, __ATOMIC_RELEASE);'),
        ('      if (st.state != NW_STA_UP) gLinkUpMs = 0; else if (!gLinkUpMs) gLinkUpMs = now;',
         '      if (st.state != NW_STA_UP) __atomic_store_n(&gLinkUpMs, uint64_t(0), __ATOMIC_RELEASE); else if (!__atomic_load_n(&gLinkUpMs, __ATOMIC_ACQUIRE)) __atomic_store_n(&gLinkUpMs, now, __ATOMIC_RELEASE);'),
        ('now - gLinkUpMs, nw_wifi_bss_count()',
         'now - __atomic_load_n(&gLinkUpMs, __ATOMIC_ACQUIRE), nw_wifi_bss_count()'),
        ('extern "C" int boot_kthread_report(const char *name, char *out, unsigned size);   // BootUiTraceProbe.c\n',''),
        ('extern "C" unsigned boot_cpu_kick(char *out, unsigned size);                      // BootUiTraceProbe.c\n',''),
        ('''    char where[240];
    if (!boot_kthread_report("dlil_input_en0", where, sizeof where))
      for (size_t at = 0, n = strlen(where); at < n; at += 80) log(6, "wifi-net: input at %u: %.80s", static_cast<unsigned>(at / 80), where + at);''',
         '    log(6, "wifi-net: input stack diagnostic not included in this build");'),
        ('''  char where[240];
  if (boot_kthread_report("dlil_input_en0", where, sizeof where)) log(6, "wifi-net: input thread not found");
  else for (size_t at = 0, n = strlen(where); at < n; at += 90) log(6, "wifi-net: input thread %u: %.90s", static_cast<unsigned>(at / 90), where + at);
  if (stalled < 2) return;   // one quiet second can be a slow thread
  char cpus[240]; const unsigned sent = boot_cpu_kick(cpus, sizeof cpus); gStall.kicks++; gStall.kicked = true;
  for (size_t at = 0, n = strlen(cpus); at < n; at += 90) log(6, "wifi-net: kick %u (%u sent) %u: %.90s", gStall.kicks, sent, static_cast<unsigned>(at / 90), cpus + at);''',
         '  log(6,"wifi-net: input stalled %u s; optional stack/IPI diagnostics not included",stalled);'),
        ('''  char name[16] = "en0";''','''  char name[16] = {};
  ifnet_t ifp = gIf ? gIf : sheng_ethernet_ifnet();
  if (ifp) snprintf(name, sizeof name, "%s%u", ifnet_name(ifp), ifnet_unit(ifp));
  else snprintf(name, sizeof name, "en0");'''),
        ('ifnet_stat_increment_out(gIf, 1, static_cast<uint32_t>(length), 0);',
         'if (gIf) ifnet_stat_increment_out(gIf, 1, static_cast<uint32_t>(length), 0);'),
        ('int ethernet_output(mbuf_t m) { return if_output(gIf, m); }','''int ethernet_output(mbuf_t m) {
  if (!gIf) { gIf = sheng_ethernet_ifnet(); log_ifnet_bind("tx"); }
  return if_output(gIf, m);
}'''),
        ('wifi-net: en0 address %s','wifi-net: interface address %s'),
        ('wifi-net: carried by en0 (ShengEthernet)','wifi-net: carried by Ethernet controller (ShengEthernet)'),
        ('  gIf = sheng_ethernet_ifnet();\n  nw_wifi_set_events(&gEvents);',
         '  gIf = sheng_ethernet_ifnet();\n  log_ifnet_bind("start");\n  nw_wifi_set_events(&gEvents);'),
        ('#if SHENG_WIFI_ETHERNET\n    if (!gIf) { gIf = sheng_ethernet_ifnet(); if (!gIf) continue; }\n#endif',
         '#if SHENG_WIFI_ETHERNET\n    if (!gIf) { gIf = sheng_ethernet_ifnet(); if (!gIf) continue; log_ifnet_bind("traffic"); }\n#endif'),
        ('#if SHENG_WIFI_ETHERNET\n  if (!gIf) gIf = sheng_ethernet_ifnet();\n#endif',
         '#if SHENG_WIFI_ETHERNET\n  if (!gIf) { gIf = sheng_ethernet_ifnet(); log_ifnet_bind("rx"); }\n#endif'),
        ('  gIf = ifp; ifnet_set_flags(ifp, IFF_UP, IFF_UP);',
         '  gIf = ifp; ifnet_set_flags(ifp, IFF_UP, IFF_UP); log_ifnet_bind("attach");'),
        ('    gRxBatches++; if (count > gRxLargestBatch) gRxLargestBatch = count;\n    gRxBatchSizes[count >= 64 ? 6 : count >= 32 ? 5 : count >= 16 ? 4 : count >= 8 ? 3 : count >= 4 ? 2 : count >= 2 ? 1 : 0]++;',
         '''    gRxBatches++; if (count > gRxLargestBatch) gRxLargestBatch = count;
    gRxBatchSizes[count >= 64 ? 6 : count >= 32 ? 5 : count >= 16 ? 4 : count >= 8 ? 3 : count >= 4 ? 2 : count >= 2 ? 1 : 0]++;
    if (gIf && (gRxBatches <= 16u || error)) {
      struct ifnet_stats_param st; memset(&st, 0, sizeof st); ifnet_stat(gIf, &st);
      log(6, "wifi-net: rx-flush batch=%u bytes=%u rc=%d if_in=%llu if_ierr=%llu if_iqdrop=%llu",
          gRxBatches, bytes, error, st.packets_in, st.errors_in, st.dropped);
    }'''),
        ('void note_frame(const uint8_t *e, size_t n, bool out) {',
         'void note_frame(const uint8_t *e, size_t n, bool out) {\n  probe_frame(e, n, out);'),
        ('''  log(6,"wifi-net: input stalled %u s; optional stack/IPI diagnostics not included",stalled);''',
         '''  if (gIf) {
    struct ifnet_stats_param st; memset(&st, 0, sizeof st); ifnet_stat(gIf, &st);
    log(6, "wifi-net: input stalled %u s if=%s%u flags=%x eflags=%x cap=%x in=%llu ierr=%llu iqdrop=%llu offered=%u",
        stalled, ifnet_name(gIf), ifnet_unit(gIf), ifnet_flags(gIf), ifnet_eflags(gIf), ifnet_capabilities_enabled(gIf),
        st.packets_in, st.errors_in, st.dropped, offered);
  } else log(6, "wifi-net: input stalled %u s if=none offered=%u", stalled, offered);''')]
    for old,new in replacements:
        if text.count(old)!=1:raise ValueError('Pinned optional Wi-Fi diagnostics changed')
        text=text.replace(old,new)
    if 'boot_cpu_kick'in text or 'boot_kthread_report'in text:raise ValueError('Unresolved BootUiTrace reference remains')
    selected=out/'WifiNet.cpp';selected.write_text(text)
    headers=['WifiScan.h','WifiScanResult.h','WifiScanPolicy.h']
    for name in headers:(out/name).write_bytes((reference/'package'/name).read_bytes())
    (out/'network-source.json').write_text(json.dumps(dict(reference_revision=revision,
        original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        selected_sha256=hashlib.sha256(selected.read_bytes()).hexdigest(),
        adaptation='Only unbuilt BootUiTrace stack/IPI diagnostics are omitted; Apple80211 events use a zero-filled live BSD interface name with en0 only as the pre-ifnet fallback; TX refreshes a delayed ifnet and guards statistics until it exists; Review16 adds bounded ifnet bind, frame, rx-flush and stall probes; Review17 accounts Skywalk RX and waits for actual queued disconnect consumption with bounded atomic leave/join probes; no fake stub or unresolved weak import; native network and real stall counters retained',
        interface_name_audit='The macOS event and runtime diagnostic paths are dynamic; remaining en0 literals are the explicit no-ifnet fallback, comments, and the non-macOS branch that allocates unit 0',
        headers={name:hashlib.sha256((out/name).read_bytes()).hexdigest()for name in headers}),indent=2)+'\n')
    return selected
