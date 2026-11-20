// SPDX-License-Identifier: BSD-2-Clause-Patent
// Local Ethernet interface for the original IOTimeSyncFamily clock identity.
// Lifecycle/ABI: pinned UniXNU-sheng ShengEthernet.cpp, OS-only subset.
// This has no radio, MMIO or packet transport; outgoing packets are dropped.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/OSKextLib.h>
#include <pexpert/pexpert.h>
#include <kern/thread.h>
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-anon-enum-enum-conversion"
#define __PRIVATE_SPI__
#include <IOKit/network/IOEthernetController.h>
#include <IOKit/network/IOEthernetInterface.h>
#include <IOKit/network/IONetworkMedium.h>
#include <IOKit/network/IOOutputQueue.h>
#pragma clang diagnostic pop

static_assert(sizeof(IOEthernetController) == B5Q_ETHERNET_CONTROLLER_SIZE,
              "IOEthernetController must match the 26C5035r collection");
extern kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_ethernet_static_init(void) __asm__("__GLOBAL__sub_I_B5qEthernet.cpp");
extern "C" { volatile int b5q_ethernet_state = 0; }

// An ephemeral locally administered unicast address from the official build
// namespace, not a Samsung hardware address or a copied reference-board MAC.
static bool localAddress(uint8_t address[6]) {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    OSData *id = chosen ? OSDynamicCast(OSData, chosen->getProperty("unique-chip-id")) : nullptr;
    uint64_t seed = 0;
    if (id && id->getLength() == sizeof(seed)) memcpy(&seed, id->getBytesNoCopy(), sizeof(seed));
    OSSafeReleaseNULL(chosen);
    if (!seed) return false;
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (unsigned i = 0; i < 8; ++i) hash = (hash ^ ((seed >> (8 * i)) & 0xff)) * 0x100000001b3ULL;
    for (unsigned i = 0; i < 6; ++i) address[i] = uint8_t(hash >> (8 * i));
    address[0] = uint8_t((address[0] & 0xfe) | 0x02);
    return true;
}

class B5qEthernet : public IOEthernetController {
    OSDeclareDefaultStructors(B5qEthernet)
    IONetworkInterface *interface = nullptr;
    const IONetworkMedium *medium = nullptr;
    uint8_t address[6] = {};
public:
    UInt32 getFeatures() const override { return kIONetworkFeatureNoBSDWait; }
    bool start(IOService *provider) override {
        if (!localAddress(address) || !IOEthernetController::start(provider)) return false;
        OSDictionary *media = OSDictionary::withCapacity(1);
        IONetworkMedium *automatic = IONetworkMedium::medium(kIOMediumEthernetAuto, 1000000000ULL);
        bool ok = media && automatic && IONetworkMedium::addMedium(media, automatic) && publishMediumDictionary(media);
        medium = ok ? IONetworkMedium::getMediumWithType(getMediumDictionary(), automatic->getType()) : nullptr;
        OSSafeReleaseNULL(automatic);
        OSSafeReleaseNULL(media);
        // The parent joined its PM tree during start. Once that succeeded,
        // every failure must undo it before the worker detaches/releases us.
        if (!ok || !medium || !setProperty("IOBuiltin", true) ||
            !setProperty("UniXNULocalClockInterface", true) ||
            !attachInterface(&interface, false)) {
            medium = nullptr;
            IOEthernetController::stop(provider);
            return false;
        }
        interface->registerService();
        return true;
    }
    void stop(IOService *provider) override {
        if (interface) { detachInterface(interface); OSSafeReleaseNULL(interface); }
        medium = nullptr;
        IOEthernetController::stop(provider);
    }
    IOReturn getHardwareAddress(IOEthernetAddress *out) override {
        if (!out) return kIOReturnBadArgument;
        memcpy(out->bytes, address, sizeof(address));
        return kIOReturnSuccess;
    }
    IOReturn enable(IONetworkInterface *) override {
        setLinkStatus(kIONetworkLinkValid | kIONetworkLinkActive, medium, 1000000000ULL);
        return kIOReturnSuccess;
    }
    IOReturn disable(IONetworkInterface *) override {
        setLinkStatus(kIONetworkLinkValid, nullptr);
        return kIOReturnSuccess;
    }
    UInt32 outputPacket(mbuf_t packet, void *) override {
        freePacket(packet);
        return kIOReturnOutputDropped;
    }
    IOReturn setPromiscuousMode(bool) override { return kIOReturnSuccess; }
    IOReturn setMulticastMode(bool) override { return kIOReturnSuccess; }
    IOReturn setMulticastList(IOEthernetAddress *, UInt32) override { return kIOReturnSuccess; }
};
OSDefineMetaClassAndStructors(B5qEthernet, IOEthernetController)

static void ethernetWorker(void *, wait_result_t) {
    OSReturn loaded = OSKextLoadKextWithIdentifier("com.apple.iokit.IONetworkingFamily");
    if (loaded != kOSReturnSuccess && loaded != kOSKextReturnStartStopError) {
        b5q_ethernet_state = -1;
    } else {
        void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if (!handle) b5q_ethernet_state = -2;
        else {
            b5q_ethernet_static_init();
            if (OSMetaClass::postModLoad(handle)) b5q_ethernet_state = -3;
            else {
                B5qEthernet *controller = OSTypeAlloc(B5qEthernet);
                IOService *parent = IOService::getResourceService();
                bool attached = false;
                if (!controller || !controller->init(nullptr) || !parent) b5q_ethernet_state = -4;
                else if (!(attached = controller->attach(parent))) b5q_ethernet_state = -5;
                else if (!controller->start(parent)) b5q_ethernet_state = -6;
                else { controller->registerService(); controller->retain(); b5q_ethernet_state = 1; }
                if (b5q_ethernet_state != 1 && attached) controller->detach(parent);
                OSSafeReleaseNULL(controller);
            }
        }
    }
    IOLog("B5qEthernet: local TimeSync interface state %d\n", b5q_ethernet_state);
    thread_terminate(current_thread());
}

extern "C" void b5q_ethernet_start(void) {
    unsigned enabled = 0;
    if (!PE_parse_boot_argn("ethernet", &enabled, sizeof(enabled)) || enabled != 1) return;
    static uint32_t once = 0;
    if (__atomic_exchange_n(&once, 1U, __ATOMIC_ACQ_REL)) return;
    thread_t thread = nullptr;
    if (kernel_thread_start(ethernetWorker, nullptr, &thread) == KERN_SUCCESS) thread_deallocate(thread);
    else { b5q_ethernet_state = -7; IOLog("B5qEthernet: worker allocation failed\n"); }
}
