#!/usr/bin/env python3
"""Run pinned shared production tests on Linux, preserving their assertions.

Only Darwin linker dead_strip and the host libc loff_t/errno namespace are
adapted. Source preparation shares one output tree, so tests run sequentially.
"""
import contextlib,hashlib,json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
module=(R/'sources/UniXNU-sheng/drivers/Ath12kWifi').resolve();out=R/'artifacts/b5q-p3-work/host-regression'
out.mkdir(parents=True,exist_ok=True)
compiler=str(R/'tools/llvm21/usr/lib/llvm-21/bin/clang')
if not Path(compiler).is_file():raise SystemExit('Host clang unavailable')
checks=[]
with contextlib.nullcontext(out/'host-env')as td:
    td=Path(td);td.mkdir(parents=True,exist_ok=True);header=td/'host.h'
    (td/'linux').mkdir(exist_ok=True);(td/'linux/errno.h').write_text('#include <asm-generic/errno.h>\n')
    (td/'supp/linux').mkdir(parents=True,exist_ok=True);(td/'supp/linux/types.h').write_text('#include </usr/include/linux/types.h>\n')
    header.write_text('#include <sys/types.h>\n#include <time.h>\n#include <pthread.h>\n#include <sched.h>\n#include <unistd.h>\n#include <asm-generic/errno.h>\n#define loff_t b5q_host_linux_loff_t\n')
    original=module/'tests/mainline_runtime_test.c'
    fixture=td/'mainline_runtime_test.c'
    text=original.read_text()
    old='static int config(struct ieee80211_hw *hw, u32 changed) { (void)hw; (void)changed; return 0; }'
    assert text.count(old)==1
    text=text.replace(old,'static int config(struct ieee80211_hw *hw, int radio, u32 changed) { (void)hw; (void)radio; (void)changed; return 0; }')
    fixture.write_text(text)
    wrapper=td/'clang'
    wrapper.write_text(f'''#!/usr/bin/python3
import os,sys
sys.path.insert(0,{str(R/'UniXNU-b5q/scripts')!r})
from b5q_wifi import select_shared
args=["-Wl,--gc-sections" if x=="-Wl,-dead_strip" else {str(fixture)!r} if x=={str(original)!r} else x for x in sys.argv[1:]]
args=[str(select_shared(x,{str(out/'selected')!r})) if x.endswith("/cfg80211/scan.c") else x for x in args]
extra=[] if "-target" in args or any(x.startswith("--target=")for x in args) else ["-resource-dir=/usr/lib/llvm-17/lib/clang/17","-I",{str(td)!r},"-include",{str(header)!r}]
if extra and any("out/wpa-src" in x for x in args):extra=["-I",{str(td/'supp')!r},*extra]
os.environ["LD_LIBRARY_PATH"]={str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')!r}
os.execv({compiler!r},[{compiler!r},*extra,*args])
''')
    wrapper.chmod(0o755);env=dict(os.environ,PATH=str(td)+':'+os.environ['PATH'])
    env.pop('LD_PRELOAD',None)
    # The upstream cache records the command before this wrapper substitutes
    # the host fixture. Keep only an object whose dependencies actually name
    # and hash that fixture; an object of the old callback must be rebuilt.
    identity=module/'out/mainline-runtime-test/mainline_runtime_test.inputs.json'
    if identity.is_file():
        saved=json.loads(identity.read_text())
        if saved.get('dependencies',{}).get(str(fixture.resolve()))!=hashlib.sha256(fixture.read_bytes()).hexdigest():
            identity.with_name('mainline_runtime_test.o').unlink(missing_ok=True)
    # Old failed host-only compilations may reference an expired temp header.
    # Invalidate only those host objects; production target caches are intact.
    for dependency in (module/'out/wpa-host').rglob('*.d'):
        if '/tmp/b5q-wireless-host-'in dependency.read_text():
            dependency.with_suffix('.o').unlink(missing_ok=True);dependency.unlink()
    (module/'out/wpa-host/report.json').unlink(missing_ok=True)
    jobs=[(p.stem,[sys.executable,str(p)])for p in sorted((module/'tools').glob('test-*.py'))]
    jobs.append(('test-mhi',['bash',str(module/'tools/test-mhi.sh')]))
    for name,command in jobs:
        with (out/(name+'-linux.log')).open('w')as f:
            result=subprocess.run(command,cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT)
        checks.append(dict(name=name,passed=result.returncode==0,command=command,
            test_source_sha256=hashlib.sha256(Path(command[-1]).read_bytes()).hexdigest()))
        report=dict(passed=len(checks)==len(jobs)and all(c['passed']for c in checks),
            checks=checks,total=len(jobs),hardware_verified=False,complete_stage=False,
            host_adaptation='Darwin dead_strip -> ELF gc-sections; private Linux loff_t/errno/time namespace; fixture config callback gains same-version radio_idx; all production source and assertions retained',
            fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest())
        (out/'shared-linux-report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name,'PASS'if not result.returncode else'FAIL',flush=True)
        if result.returncode:
            print((out/(name+'-linux.log')).read_text()[-6000:]);raise SystemExit(1)
