#!/usr/bin/env python3
"""Inventory actual probe/thread exits; refuse new silent error branches."""
import hashlib,json,os,re
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-v33b-fix-work'))
files=sorted((R/'UniXNU-b5q/package').glob('*.cpp'))
for folder in ['generated-adsp','generated-audio-service','generated-video']:
 files+=sorted((R/'artifacts/b5q-p4-work/target'/folder).glob('*.cpp'))
# These exact guards are ordinary configuration/idempotence/lifecycle exits.
# Errors are never excused merely because the function logs on another path.
guards=[r'PE_parse_boot_argn',r'__atomic_(?:exchange|compare_exchange)_n',r'if\s*\(!mode\s*\|\|',
 r'if\s*\(mode\s*!=\s*1',r'if\s*\(native_hid_stage\)',r'if\s*\(native_legacy_stage\)',
 r'B5qFeatures::option',r'if\s*\(relativePointer\(device\)\)',r'native_keyevents_stage\) return',
 r'native_keystore_stage\) return',r'pendingLegacyDisplay=display;',r'startB5qPeripherals\(\);return',
 r'if\s*\(!enabled\)',r'if\s*\(\(mode!=1&&mode!=3\)',r'if\(!mode\|\|native_adsp_stats',r'if\s*\(!gDmaReady\)',r'if\s*\(!gRoleLock\)',r'if\s*\(gDpLanes==4\)']
callee=[r'native_legacy_display_checkpoint\(\)',r'if\s*\(!setup\(\)\)',r'\bfail\(',r'\bstage\(',r'\bpowerResult\(']
rows=[];functions=[];errors=[];seen=set()
for f in files:
 s=f.read_text();names=set(re.findall(r'kernel_thread_start\(\s*(\w+)',s))
 names.update(re.findall(r'\b([\w]*probe)\s*\(',s))
 for name in sorted(names):
  m=re.search(r'(?:static\s+)?(?:void|bool|int|IOReturn)\s+'+name+r'\s*\([^;{}]*\)\s*\{',s)
  if not m:continue
  start=m.end();end=start;depth=1
  while depth and end<len(s):depth+=(s[end]=='{')-(s[end]=='}');end+=1
  body=s[start:end-1];key=(str(f),name)
  if key in seen:continue
  seen.add(key);functions.append(dict(source=str(f.relative_to(R)),name=name,line=s[:m.start()].count('\n')+1))
  for hit in re.finditer(r'\breturn\s*(?:false)?\s*;|\bgoto\s+(?:failed|fail)\s*;',body):
   i=hit.start();lineStart=body.rfind('\n',0,i)+1
   text=body[lineStart:body.find('\n',hit.end())if '\n'in body[hit.end():]else len(body)].strip()
   previous=body[max(0,i-260):hit.end()]
   if hit.group().startswith('goto'):
    tail=body[body.rfind('failed:'):]
    reason='central error cleanup with result log'if 'native_wifi_logf(3,"stopped result=%d'in tail else None
   elif any(re.search(p,text)for p in guards):reason='reviewed feature-disabled/idempotence/ordinary lifecycle exit'
   elif 'IOLog('in text or 'printf('in text:reason='same-branch diagnostic'
   elif any(re.search(p,text)for p in callee):reason='callee emits stage/result before exit'
   elif any(re.search(p,previous)for p in [r'fail\([^;]+\);\s*return',r'if\s*\(mode < 2 \|\| !start\(\) \|\| !startGlink\(\)\)',r'if \(!dspReady\(\)\)',r'if \(!openGraphs\(\)\)']):reason='reviewed production callee logs its exact failure stage/result'
   elif 'IOLog('in previous and not '}'in previous[previous.rfind('IOLog('):]:reason='same-block diagnostic'
   else:reason=None
   row=dict(source=str(f.relative_to(R)),function=name,line=s[:start+i].count('\n')+1,branch=text,classification=reason)
   rows.append(row)
   if reason is None:errors.append(row)
report=dict(passed=not errors,hardware_verified=False,functions=functions,exits=rows,unclassified=errors,
 source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files},
 scope='Every defined board and production-generated media probe/thread entry; error helpers and caller checkpoints explicitly classified. Disabled features/normal timer/IRQ no-work paths are not failures. Startup failures log once; recurring paths bounded by existing timers/counters.')
(W/'failure-gates.json').write_text(json.dumps(report,indent=2)+'\n')
if errors:
 for row in errors:print(row)
 raise SystemExit('FAIL unclassified silent exits')
print('PASS',len(functions),'production probe/worker functions;',len(rows),'classified exits, zero unclassified failures')
