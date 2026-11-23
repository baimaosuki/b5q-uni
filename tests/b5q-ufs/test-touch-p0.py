from pathlib import Path
import subprocess,tempfile,re
root=Path(__file__).resolve().parents[2]
# Compare every reused upstream function body, not just a few expected results.
up=(root/'sources/UniXNU-sheng/package/Wn8030.c').read_text()
local=(root/'UniXNU-b5q/package/Wn8030Pointer.h').read_text()
for name in ['pointer_take','wn8030_gap_bucket','wn8030_pointer_report','wn8030_pointer_report_at']:
 def body(text):
  match=list(re.finditer(r'\b'+name+r'\([^;{}]*\)\s*\{',text))
  assert len(match)==1,name
  first=match[0].end()-1;depth=1;at=first+1
  while depth:
   depth+=(text[at]=='{')-(text[at]=='}');at+=1
  return text[first:at]
 assert body(up)==body(local),name
assert not (root/'UniXNU-b5q/package/B5qTouchPointer.h').exists()
assert 'digitizerPairGuard' in (root/'UniXNU-b5q/package/HidInputProbe.cpp').read_text()
with tempfile.TemporaryDirectory(prefix='b5q-p0-') as td:
 exe=Path(td)/'p0'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(root/'UniXNU-b5q/package'),str(Path(__file__).with_suffix('.cpp')),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('PASS all four reused Wn8030 function bodies match pinned upstream verbatim; old pointer removed; absolute digitizer guard preserved')
