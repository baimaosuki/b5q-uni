from pathlib import Path
import importlib.util,hashlib,json,urllib.request,subprocess,tempfile,re
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-runtime-v19-work';common=R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform';ref=R/'sources/UniXNU-sheng/package';pins=json.loads((R/'UniXNU/scripts/data/adreno-inputs.json').read_text());src=W/'shared-source'
for n in ['drivers/soc/qcom/cmd-db.c','include/soc/qcom/cmd-db.h']:
 p=src/n
 if not p.is_file():
  data=urllib.request.urlopen(pins['linux']['repository'].replace('https://github.com/','https://raw.githubusercontent.com/').removesuffix('.git')+'/'+pins['linux']['commit']+'/'+n,timeout=30).read();p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 assert hashlib.sha256(p.read_bytes()).hexdigest()==pins['linux']['files'][n]['sha256']
with tempfile.TemporaryDirectory(prefix='b5q-gpu-host-')as td:
 t=Path(td);(t/'scripts/data').mkdir(parents=True);(t/'scripts/data/adreno-inputs.json').write_text(json.dumps(pins));(t/'.cache').mkdir();(t/'.cache/adreno-source').symlink_to(src);(t/'build/sheng-gmu').mkdir(parents=True)
 spec=importlib.util.spec_from_file_location('original_db_oracle',R/'sources/UniXNU-sheng/scripts/prepare-sheng-command-db-oracle.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.ROOT=t;oracle=m.prepare()
 (t/'CommonCrypto').mkdir();(t/'CommonCrypto/CommonDigest.h').write_text('#include <openssl/sha.h>\n#define CC_SHA256_DIGEST_LENGTH SHA256_DIGEST_LENGTH\n#define CC_SHA256(p,n,out) SHA256(p,n,out)\ntypedef unsigned CC_LONG;\n')
 inc=[t,R/'UniXNU-b5q/package/Sm8550Inputs',common,R/'UniXNU/kits/AdrenoFirmware',R/'UniXNU/kits/ArmSmmu4K',R/'UniXNU-b5q/package']
 files=[ref/'ShengGmuHostTests.c',ref/'ShengGmuVotesHostTests.c',ref/'ShengGmuCommandDbHostTests.c',oracle,R/'UniXNU-b5q/package/B5qGmuVotes.c',common/'ShengGmu.c',common/'ShengGmuCommandDb.c']+[R/'UniXNU/kits/AdrenoFirmware'/n for n in ['AdrenoFirmware.c','AdrenoHfi.c','AdrenoHfiVotes.c','AdrenoHfiStartup.c']]
 # Simulated host peers: replace only AArch64 fence instructions by host fences.
 adapted=[]
 for f in files:
  text=f.read_text()
  if '__asm__ volatile' in text:
   text=re.sub(r'__asm__ volatile\("(?:dsb|dmb) [a-z]+":::?"memory"\)', '__atomic_thread_fence(__ATOMIC_SEQ_CST)',text)
   q=t/f.name;q.write_text(text);adapted.append(q)
  else:adapted.append(f)
 files=adapted
 command=['cc','-D__aarch64__=1','-D_POSIX_C_SOURCE=200809L','-std=c11','-g','-O1','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-fsanitize=address,undefined']
 for p in inc:command+=['-I',str(p)]
 command += list(map(str,files))+['-lcrypto','-o',str(t/'gmu-test')];subprocess.run(command,check=True);subprocess.run([str(t/'gmu-test'),str(R/'artifacts/firmware-b5q/F7310ZCS7EYF3/gpu/gmu_gen70200.bin')],check=True)
 test=(ref/'GpuPowerBoardTests.c').read_text().replace('"GpuPowerBoard.h"','"B5qGpuPowerBoard.h"');(t/'power-test.c').write_text(test)
 subprocess.run(['cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package'),str(t/'power-test.c'),'-o',str(t/'power-test')],check=True);subprocess.run([str(t/'power-test')],check=True)
print('PASS: production shared GMU/HFI + Samsung votes, Linux command-db oracle and clock/power fault tests')
