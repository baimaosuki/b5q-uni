#!/usr/bin/env python3
"""Replay the production early-exit and Type-C init functions without hardware."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

with tempfile.TemporaryDirectory(prefix="b5q-v32-") as temporary:
    work = Path(temporary)
    source = work / "absentd.c"
    source.write_bytes((ROOT / "UniXNU/scripts/absent-service/absentd.c").read_bytes())
    subprocess.run(
        ["patch", "--batch", "--fuzz=0", "-d", str(work), "-p1"],
        input=(ROOT / "UniXNU-b5q/patches/tools/b5q-absentd-user-domains.patch").read_bytes(),
        check=True,
    )
    absentd = source.read_text()
    prefix = absentd[absentd.index("    const char *label = getenv"):absentd.index("    CFPropertyListRef job = NULL;")]
    boot = work / "early.cpp"
    boot.write_text(
        '#include <cassert>\n#include <cstdlib>\n#include <cstring>\n#include <string>\n'
        'extern "C" {extern char PE_builtin_boot_args[];}\n'
        'static int enter_service() {\n' + prefix + '\nreturn 99;}\n'
        'int main() {\n'
        'unsetenv("XPC_SERVICE_NAME");assert(enter_service()==0);\n'
        'setenv("XPC_SERVICE_NAME","",1);assert(enter_service()==0);\n'
        'setenv("XPC_SERVICE_NAME","com.apple.AirPlayXPCHelper",1);assert(enter_service()==99);\n'
        'setenv("XPC_SERVICE_NAME","../invalid",1);assert(enter_service()==78);\n'
        'std::string args=PE_builtin_boot_args;auto at=args.find("deny-exec=");assert(at!=std::string::npos);\n'
        'auto list=args.substr(at+10);assert(list.size()<256);\n'
        'assert(list.find("endpointsecurityd")==std::string::npos);\n'
        'for(const char *p:{"/usr/libexec/mobileactivationd","/usr/libexec/cryptexd",'
        '"/usr/libexec/AirPlayXPCHelper","/usr/libexec/rtcreportingd",'
        '"/System/Library/CoreServices/talagentd"})assert(list.find(p)!=std::string::npos);\n'
        '}\n'
    )
    exe = work / "early"
    policy = work / "policy.o"
    subprocess.run(["cc", "-Wall", "-Wextra", "-Werror", "-c",
                    str(ROOT / "UniXNU-b5q/package/B5qBootPolicy.c"), "-o", str(policy)], check=True)
    subprocess.run(
        ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", str(boot), str(policy), "-o", str(exe)],
        check=True,
    )
    subprocess.run([str(exe)], check=True)

    board = (ROOT / "UniXNU-b5q/package/B5qUsbBoard.cpp").read_text()
    init = board[board.index('extern "C" bool b5q_usb_typec_init'):board.index('extern "C" bool b5q_usb_otg')]
    harness = r'''
#include "B5qMax77705.h"
#include <cassert>
#include <cstdint>
static bool water=false, timeout=false, identityFailure=false;
static unsigned commands=0, writes=0, reads=0, logs=0;
struct Bus {
    int *lock=nullptr;
    bool triggered=false;
    bool open(bool hub){assert(hub);return true;}
    bool read(uint8_t address,uint8_t reg,uint8_t &v) {
        ++reads;
        if(address==0x66){v=reg?2:0x15;return !identityFailure;}
        assert(address==0x25);
        if(reg==0x0a){v=0xb2;return true;}
        if(reg==0x0b){v=water?2:0;return true;}
        if(reg==2){v=triggered&&!timeout?0x80:0;return true;}
        assert(reg==0x51);v=0x5e;return true;
    }
    bool write(uint8_t address,uint8_t reg,uint8_t v){
        assert(address==0x25);++writes;
        if(reg==0x21){assert(v==0x5e);++commands;}
        else if(reg==0x22)assert(v==1);
        else {assert(reg==0x41&&v==0);triggered=true;}
        return true;
    }
};
static Bus *maxim;
static bool maximReady=false;
static void IOLockLock(int*){}
static void IOLockUnlock(int*){}
static void IODelay(unsigned){}
template<class... Args> void IOLog(const char*,Args...){++logs;}
'''
    harness += init + r'''
static void reset(){
    delete maxim;maxim=nullptr;maximReady=false;
    commands=writes=reads=0;water=timeout=identityFailure=false;
}
int main(){
    assert(b5q_usb_typec_init()&&commands==1&&writes==3);
    assert(b5q_usb_cable_role()==2);reset();
    timeout=true;
    assert(b5q_usb_typec_init()&&maximReady&&commands==1&&writes==3);
    unsigned before=reads;assert(b5q_usb_cable_role()==2&&reads>before);reset();
    water=true;
    assert(!b5q_usb_typec_init()&&!maximReady&&commands==0&&writes==0);
    assert(b5q_usb_cable_role()==0);reset();
    identityFailure=true;
    assert(!b5q_usb_typec_init()&&!maximReady&&commands==0&&writes==0);reset();
}
'''
    cpp = work / "typec.cpp"
    cpp.write_text(harness)
    exe = work / "typec"
    subprocess.run(
        ["c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
         "-fsanitize=address,undefined", "-I", str(ROOT / "UniXNU-b5q/package"),
         str(cpp), "-o", str(exe)], check=True,
    )
    subprocess.run([str(exe)], check=True)
print("PASS production absentd one-shot exit, EndpointSecurity exclusion, and Type-C timeout/CC/water/identity paths")
