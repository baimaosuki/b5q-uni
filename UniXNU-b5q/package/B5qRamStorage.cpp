// SPDX-License-Identifier: BSD-2-Clause-Patent
// Public IOStorageFamily base, volatile RamBlock Data and authenticated b5q UFS roots.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/OSKextLib.h>
#include <libkern/c++/OSSymbol.h>
#include <mach/kmod.h>
extern "C" void b5q_pmgr_start(void);
extern "C" void b5q_ufs_start(IOService *);
extern "C" void b5q_storage_ufs_init(void) __asm__("__GLOBAL__sub_I_B5qUfs.cpp");
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_storage_base_init(void) __asm__("__GLOBAL__sub_I_IOBlockStorageDevice.cpp");
extern "C" void b5q_storage_ram_init(void) __asm__("__GLOBAL__sub_I_NativeRamBlock.cpp");
static const OSMetaClass *parent;
extern "C" const OSMetaClass *native_source_storage_parent(void) {
    if(!parent)panic("B5qRamStorage: base initialized before original storage family");
    return parent;
}
extern "C" void b5q_ram_storage_start(void) {
    static bool attempted=false;
    if(attempted)return;
    attempted=true;
    b5q_pmgr_start();
    OSReturn status=OSKextLoadKextWithIdentifier("com.apple.iokit.IOStorageFamily");
    if(status!=kOSReturnSuccess)panic("B5qRamStorage: family load %x",status);
    const OSSymbol *name=OSSymbol::withCString("IOBlockStorageDevice");
    parent=name?OSMetaClass::getMetaClassWithName(name):nullptr;
    OSSafeReleaseNULL(name);
    if(!parent || parent->getClassSize()!=sizeof(IOBlockStorageDevice))
        panic("B5qRamStorage: incompatible original/source storage ABI");
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle)panic("B5qRamStorage: preModLoad");
    b5q_storage_base_init();b5q_storage_ram_init();b5q_storage_ufs_init();
    if(OSMetaClass::postModLoad(handle))panic("B5qRamStorage: postModLoad");
    IORegistryEntry *map=IORegistryEntry::fromPath("/chosen/memory-map",gIODTPlane);
    bool seed=map && (map->getProperty("PackedRAMDisk") || map->getProperty("RAMDisk"));
    OSSafeReleaseNULL(map);
    if(!seed)return;
    IOService *provider=IOService::getResourceService();
    IOService *disk=OSDynamicCast(IOService,OSMetaClass::allocClassWithName("NativeRamBlock"));
    if(!provider || !disk || !disk->init() || !disk->attach(provider) || !disk->start(provider))
        panic("B5qRamStorage: RAM seed start failed");
    status=OSKextLoadKextWithIdentifier("com.apple.filesystems.apfs");
    if(status!=kOSReturnSuccess)panic("B5qRootStorage: APFS load %x",status);
    b5q_ufs_start(provider);
    // Persistent Data remains disabled; only authenticated root reads are served.
    IOLog("B5qRamStorage: volatile RAM block device started\n");
}
