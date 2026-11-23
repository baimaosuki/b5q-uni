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
    # BootUiTrace is optional diagnostics, not a station/authentication path.
    # Never substitute an empty implementation of its kernel-only helpers.
    text=text.replace('int boot_kthread_report(const char *name, char *out, unsigned size);',
        'int boot_kthread_report(const char *name, char *out, unsigned size) __attribute__((weak_import));')
    text=text.replace('unsigned boot_cpu_kick(char *out, unsigned size);',
        'unsigned boot_cpu_kick(char *out, unsigned size) __attribute__((weak_import));')
    text=text.replace('if (!boot_kthread_report("dlil_input_en0", where, sizeof where))',
        'if (boot_kthread_report && !boot_kthread_report("dlil_input_en0", where, sizeof where))')
    text=text.replace('if (boot_kthread_report("dlil_input_en0", where, sizeof where))',
        'if (!boot_kthread_report || boot_kthread_report("dlil_input_en0", where, sizeof where))')
    text=text.replace('  char cpus[240]; const unsigned sent = boot_cpu_kick',
        '  if (!boot_cpu_kick) { log(6, "wifi-net: optional CPU kick diagnostic unavailable"); return; }\n  char cpus[240]; const unsigned sent = boot_cpu_kick')
    selected=out/'WifiNet.cpp';selected.write_text(text)
    headers=['WifiScan.h','WifiScanResult.h','WifiScanPolicy.h']
    for name in headers:(out/name).write_bytes((reference/'package'/name).read_bytes())
    (out/'network-source.json').write_text(json.dumps(dict(reference_revision=revision,
        original_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        selected_sha256=hashlib.sha256(selected.read_bytes()).hexdigest(),
        adaptation='Only optional BootUiTrace diagnostic imports are guarded; native network implementation unchanged',
        headers={name:hashlib.sha256((out/name).read_bytes()).hexdigest()for name in headers}),indent=2)+'\n')
    return selected
