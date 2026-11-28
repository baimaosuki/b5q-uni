"""Build both wireless transports into the normal Format 2 board archive."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from b5q_bluetooth import prepare as bluetooth_sources
from b5q_wifi import prepare as network_source,REVISION as NETWORK_REVISION

def checkout(tree,name,url,revision,paths=None):
    cache=tree/'.cache/b5q-wireless'/name
    if not (cache/'.git').exists():
        cache.mkdir(parents=True,exist_ok=True);subprocess.run(['git','init','-q',str(cache)],check=True)
    current=subprocess.run(['git','-C',str(cache),'rev-parse','HEAD'],capture_output=True,text=True)
    if current.returncode==0:
        changed=subprocess.check_output(['git','-C',str(cache),'diff','--name-only','HEAD'],text=True).splitlines()
        # Match the locked upstream verifier's case-folding exception. Never
        # discard source edits just to turn an identity failure green.
        changed=[p for p in changed if not p.startswith('include/uapi/linux/netfilter')]
        if changed:raise ValueError('Modified cached source; preserve checkout: '+name)
    if paths:
        subprocess.run(['git','-C',str(cache),'sparse-checkout','init','--cone'],check=True)
        subprocess.run(['git','-C',str(cache),'sparse-checkout','set','--skip-checks',
            *[p.strip('/')for p in paths]],check=True)
    if current.returncode or current.stdout.strip()!=revision:
        subprocess.run(['git','-C',str(cache),'fetch','--depth','1',url,revision],check=True)
        subprocess.run(['git','-C',str(cache),'checkout','--detach','FETCH_HEAD'],check=True)
    if subprocess.check_output(['git','-C',str(cache),'rev-parse','HEAD'],text=True).strip()!=revision:
        raise ValueError('Wireless source identity changed: '+name)
    return cache

def build(tree,package,out):
    from b5q_compile import compile
    tree,package,out=map(Path,(tree,package,out));out.mkdir(parents=True,exist_ok=True)
    reference=checkout(tree,'UniXNU-sheng','https://github.com/UniXNU/UniXNU-sheng.git',NETWORK_REVISION)
    bt=checkout(tree,'QcaBluetooth','https://github.com/UniXNU/QcaBluetooth.git','effe4ec5c57cd400a5f818b21c9903fef237edbc')
    module=checkout(tree,'Ath12kWifi','https://github.com/UniXNU/Ath12kWifi.git','f087c7ddac07e945f20d199dbaf6c95c6db3346a')
    # The upstream fetcher clones source[ref] then checks source[commit]. A
    # release branch may move; materialize the reviewed commit first without
    # editing the lock or weakening its required-file/hash verification.
    lock=json.loads((module/'tools/source-lock.json').read_text())
    if lock.get('schema')!=1:raise ValueError('Wireless source-lock schema changed')
    for name in ('linux','freebsd'):
        source=lock[name]
        checkout(tree,'Ath12kWifi/deps/'+name,source['url'],source['commit'],source['paths'])
    subprocess.run([sys.executable,str(module/'tools/fetch-sources.py')],check=True)
    sources,include=bluetooth_sources(bt,package,tree/'kits/Sm8550Platform',out/'bluetooth',reference)
    sources += [package/'B5qWifiBoard.cpp',package/'WifiFirmware.c',network_source(reference,out/'network')]
    include += [module/'include',module/'src',out/'network',package,tree/'kits/Sm8550Platform']
    flags=[v for path in include for v in ['-I',str(path)]]
    objects=[]
    for source in sources:
        extra=['-Wno-sign-compare','-Wno-misleading-indentation','-Wno-missing-field-initializers']
        if source.name=='btqca.c':extra+=['-include',str(package/'B5qBtLinuxCompat.h')]
        objects.append(compile(source,out/(source.stem+'.o'),flags,extra,bsd=source.suffix=='.c'))
    llvm=Path(subprocess.check_output(['brew','--prefix','llvm'],text=True).strip())/'bin'
    subprocess.run([sys.executable,str(Path(__file__).with_name('build-b5q-wifi.py')),
        '--module',str(module),'--out',str(out/'ath11k'),'--llvm',str(llvm),'--jobs','4'],check=True)
    result=json.loads((out/'ath11k/compile-result.json').read_text())
    if not result['passed'] or result['core_only']:raise ValueError('Full ath11k build required')
    objects += list(map(Path,result['objects']))
    (out/'wireless-build.json').write_text(json.dumps(dict(hardware_verified=False,
        bluetooth_revision='effe4ec5c57cd400a5f818b21c9903fef237edbc',native_network_revision=NETWORK_REVISION,
        ath11k_linux_revision='458c6079fc1d41d564c37679c8ace02cd83ee817',
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources},
        objects={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in objects}),indent=2)+'\n')
    return objects
