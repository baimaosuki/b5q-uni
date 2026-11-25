// SPDX-License-Identifier: BSD-2-Clause-Patent
// sheng board entry of the QcomDwc3 driver: the controller's classes register here, after the hardware answered, the way a module
// load would register them (see HidInputProbe.cpp for the same deferred metaclass registration).
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOCatalogue.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/OSKextLib.h>
#include <pexpert/pexpert.h>
#include <kern/thread.h>
extern kmod_info_t g_kernel_kmod_info;
extern "C" bool qcom_dwc3_bring_up(void);
extern "C" void qcom_dwc3_publish(void);
extern "C" void qcom_dwc3_diag(bool);
extern "C" void qcom_dwc3_static_init(void) __asm__("__GLOBAL__sub_I_QcomDwc3.cpp");
extern "C" volatile uint32_t native_usb_stats[54];
extern "C" void qcom_dwc3_host_load(int);
static void worker(void *, wait_result_t) {
    if (qcom_dwc3_bring_up()) {
        // AppleUSBXDCI has no personality of its own, so nothing has loaded it: its constructors and metaclasses, and those of
        // IOUSBDeviceFamily below it, run on this load.
        const OSReturn loaded = OSKextLoadKextWithIdentifier("com.apple.driver.AppleUSBXDCI");
        native_usb_stats[21] = (uint32_t)loaded;
        if (loaded != kOSReturnSuccess && loaded != kOSKextReturnStartStopError) {native_usb_stats[0] = (uint32_t)-9; IOLog("qcom-dwc3: stage=xdci-load result=%x\n",loaded); thread_terminate(current_thread()); return;}
        // The same for host mode: Apple's xHCI driver and the USB host family below it.
        qcom_dwc3_host_load((int)OSKextLoadKextWithIdentifier("com.apple.driver.usb.AppleUSBXHCI"));
        const char *families[]={
        "com.apple.iokit.IOUSBDeviceFamily", "com.apple.driver.AppleUSBDeviceMux","com.apple.driver.usb.AppleUSBHub","com.apple.driver.usb.AppleUSBHostCompositeDevice","com.apple.driver.usb.IOUSBHostHIDDevice","com.apple.driver.AppleHIDKeyboard","com.apple.iokit.IOUSBMassStorageDriver"};
        for(const char *identifier:families){
            OSReturn rc=OSKextLoadKextWithIdentifier(identifier);
            if(rc==kOSReturnSuccess){const OSSymbol *name=OSSymbol::withCString(identifier);if(name){if(gIOCatalogue && name)gIOCatalogue->startMatching(name);name->release();}}
            IOLog("qcom-dwc3: family=%s load=%x\n",identifier,rc);
        }
        void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if (!handle) {native_usb_stats[0] = (uint32_t)-10;IOLog("qcom-dwc3: stage=metaclass-pre result=-10\n");}
        else {
            qcom_dwc3_static_init();
            const OSReturn status=OSMetaClass::postModLoad(handle);
            if (status) {native_usb_stats[0] = (uint32_t)-11;IOLog("qcom-dwc3: stage=metaclass-post result=%x\n",status);}
            else {
                qcom_dwc3_publish();
                unsigned mode = 0;
                PE_parse_boot_argn("usb", &mode, sizeof mode);
                if (mode == 2 || mode == 3) qcom_dwc3_diag(mode == 3);
            }
        }
    }
    thread_terminate(current_thread());
}
extern "C" void sheng_usb_probe(void) {
    static uint32_t once=0;
    unsigned enabled = 0;
    if (!PE_parse_boot_argn("usb", &enabled, sizeof enabled) || !enabled) return;
    if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;
    thread_t thread = nullptr;
    const kern_return_t status=kernel_thread_start(worker, nullptr, &thread);
    if (status == KERN_SUCCESS) thread_deallocate(thread);
    else IOLog("qcom-dwc3: stage=worker-start result=%d\n",status);
}
