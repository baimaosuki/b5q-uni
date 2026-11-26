"""Select the pinned OS-only network adapter; no sheng hardware is copied."""
import hashlib,json,subprocess
from pathlib import Path
REVISION='6c42e1055ffb3b335fda991190ad221edaa7af3c'
def select_shared(source,out):
    source,out=Path(source),Path(out)
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
    replacements=[
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
  if (!gIf) gIf = sheng_ethernet_ifnet();
  return if_output(gIf, m);
}'''),
        ('wifi-net: en0 address %s','wifi-net: interface address %s'),
        ('wifi-net: carried by en0 (ShengEthernet)','wifi-net: carried by Ethernet controller (ShengEthernet)')]
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
        adaptation='Only unbuilt BootUiTrace stack/IPI diagnostics are omitted; Apple80211 events use a zero-filled live BSD interface name with en0 only as the pre-ifnet fallback; TX refreshes a delayed ifnet and guards statistics until it exists; no fake stub or unresolved weak import; native network and real stall counters retained',
        interface_name_audit='The macOS event and runtime diagnostic paths are dynamic; remaining en0 literals are the explicit no-ifnet fallback, comments, and the non-macOS branch that allocates unit 0',
        headers={name:hashlib.sha256((out/name).read_bytes()).hexdigest()for name in headers}),indent=2)+'\n')
    return selected
