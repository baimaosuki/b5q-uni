#!/usr/bin/env python3
"""Regress the exact forced-include/header-attribute failure observed in CI."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-bt-string-')as td:
    td=Path(td);(td/'sys').mkdir()
    # Mirrors XNU's late pure declaration; the production header must consume
    # this header before introducing its private strrchr macro.
    (td/'sys/systm.h').write_text('''#ifndef B5Q_TEST_SYSTM
#define B5Q_TEST_SYSTM
#include <string.h>
extern char *strrchr(const char *,int) __attribute__((pure));
#endif
''')
    (td/'test.c').write_text('''#include <sys/systm.h>
#include <assert.h>
#include <stdio.h>
int main(void){
 const char value[]="abcdb";
 assert(strrchr(value,'b')==value+4);
 assert(strrchr(value,0)==value+5);
 assert(strrchr(value,'z')==0);
 const char high[]={ (char)0x80,0 };
 assert(strrchr(high,0x180)==high);
 puts("PASS production BT forced include: XNU pure declaration ordering and last/zero/high/absent character");
}
''')
    subprocess.run(['/usr/lib/llvm-17/bin/clang','-std=c11','-O1','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-DKERNEL=1','-I'+str(td),'-include',
        str(R/'UniXNU-b5q/package/B5qBtLinuxCompat.h'),str(td/'test.c'),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
