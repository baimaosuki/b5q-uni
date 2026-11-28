// SPDX-License-Identifier: BSD-2-Clause-Patent
// Public IOStorageFamily base, volatile RamBlock Data and authenticated b5q UFS roots.
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/OSKextLib.h>
#include <libkern/c++/OSSymbol.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
extern "C" void b5q_pmgr_start(void);
extern "C" void b5q_power_start(void);
extern "C" bool b5q_power_ready(void);
extern "C" void b5q_ufs_start(IOService *);
extern "C" void b5q_storage_ufs_init(void) __asm__("__GLOBAL__sub_I_B5qUfs.cpp");
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" uint32_t ml_outside_memory_pages,ml_outside_memory_refused;
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
    b5q_pmgr_start();b5q_power_start();
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
    unsigned persistent=0;PE_parse_boot_argn("b5q-data-ufs",&persistent,sizeof(persistent));
    if(!seed && persistent!=1)return;
    if(persistent==1) {
        if(!b5q_power_ready())panic("B5qPower: persistent Data requires verified PSCI reset/off handler");
        // Six GiB is the target, not a boot prerequisite: firmware reservations
        // and refused outside pages legitimately reduce the usable total.
        constexpr uint64_t minimum=9ULL<<29; // 4.5 GiB, user-approved floor
        IOLog("B5qMemory: after-outside-adoption physical-bytes=%llu minimum=%llu target=%llu\n",
              (unsigned long long)max_mem,(unsigned long long)minimum,(unsigned long long)(6ULL<<30));
        IOLog("B5qMemory: outside adopted=%u refused=%u pages\n",ml_outside_memory_pages,ml_outside_memory_refused);
        if(max_mem<minimum)panic("B5qMemory: less than required 4.5 GiB usable physical RAM");
        if(seed)panic("B5qMemory: persistent profile must not load a RAM Data seed");
    }
    IOService *provider=IOService::getResourceService();
    IOService *disk=seed?OSDynamicCast(IOService,OSMetaClass::allocClassWithName("NativeRamBlock")):nullptr;
    if(!provider || (seed && (!disk || !disk->init() || !disk->attach(provider) || !disk->start(provider))))
        panic("B5qRamStorage: RAM seed start failed");
    status=OSKextLoadKextWithIdentifier("com.apple.filesystems.apfs");
    if(status!=kOSReturnSuccess)panic("B5qRootStorage: APFS load %x",status);
    b5q_ufs_start(provider);
    IOLog("B5qRamStorage: Data=%s root=authenticated-read-only\n",persistent==1?"persistent-UFS":"volatile-RAM");
}
