// SPDX-License-Identifier: BSD-2-Clause-Patent
// macOS: the board's network interface en0, an IOEthernetController of the original IONetworkingFamily (SDK headers; the build
// checks its vtable against the collection's, net-ether-<build>.json). Its address is the WiFi radio's (WifiProbe.cpp: made from
// /chosen/unique-chip-id), and it carries the WiFi module's frames (WifiNet.cpp, macOS: sheng_ethernet_wifi_attach): the stack's
// frames go to the module's transmit queue, received ones enter the interface's ifnet, the link follows the module's join. Before
// the module attaches, frames are dropped and the link is reported up while the interface is enabled.
//
// The system takes en0 for a Wi-Fi interface the way it does on a Mac, where the Wi-Fi driver's Skywalk interface has an
// IOEthernetController below it that carries the property IOClassNameOverride = "IO80211Controller" (IOKit.framework's
// IOObjectConformsTo reads it; SystemConfiguration classifies the interface by that test). The wireless framework finds the
// interface's service by the property IOInterfaceName and, where that service opens no user client, sends its Apple80211
// requests as ioctls on the interface: ShengWifiInterface, the family's IOEthernetInterface with those two requests, passes them
// to the module's handler (WifiNet.cpp).
//
// Why macOS needs it before the radio: IOTimeSyncFamily makes the TimeSync clock identifier from the MAC of an IOEthernetInterface or
// IO80211Interface; without one clocksyncd never gets a clock, and WindowServer (QuartzCore's TimeSync clock) waits on clocksyncd.
// The WiFi module's own registry classes (WifiNet.cpp) are named like IONetworkingFamily's and cannot register next to them.
#include <IOKit/IOLib.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/OSKextLib.h>
#include <pexpert/pexpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <kern/thread.h>
#include <sys/errno.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOCommandGate.h>
#include <IOKit/IOMemoryDescriptor.h>
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-anon-enum-enum-conversion"   // the family's headers mix anonymous enums
#define __PRIVATE_SPI__   // the shipped family uses IONetworkController's reserved slots 2-5 (outputStart ... networkInterfaceNotification)
#include <IOKit/network/IOEthernetController.h>
#include <IOKit/network/IOEthernetInterface.h>
#include <IOKit/network/IONetworkMedium.h>
#include <IOKit/network/IOOutputQueue.h>   // kIOReturnOutputDropped
#pragma clang diagnostic pop

// The subclasses below are allocated with the sizes these headers give; the build passes the collection's.
static_assert(sizeof(IOEthernetController) == B5Q_ETHERNET_CONTROLLER_SIZE, "IOEthernetController as the collection has it");
static_assert(sizeof(IOEthernetInterface) == B5Q_ETHERNET_INTERFACE_SIZE, "IOEthernetInterface as the collection has it");

extern kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_ethernet_static_init(void) __asm__("__GLOBAL__sub_I_B5qEthernet.cpp");
// Result of the probe: 0 not run, 1 started, negative: the step that failed.
extern "C" {volatile int b5q_ethernet_state = 0;}
// The WiFi module's transmit function (consumes the frame; WifiNet.cpp), its Apple80211 request handler (an errno) and its link
// state, once it attached.
static int (*volatile gWifiOutput)(mbuf_t);
static int (*volatile gWifiRequest)(unsigned long, void *);
static int (*volatile gWifiKernelRequest)(unsigned long, void *, void *, uint32_t);
static volatile bool gWifiLink;

static IOLock *gWifiLock;
static bool wifiLockReady(){
    if(__atomic_load_n(&gWifiLock,__ATOMIC_ACQUIRE))return true;
    auto *made=IOLockAlloc();if(!made)return false;IOLock *expected=nullptr;
    if(!__atomic_compare_exchange_n(&gWifiLock,&expected,made,false,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE))IOLockFree(made);
    return true;
}
struct WifiCallbacks {
    IOLock *lock;
    WifiCallbacks():lock(__atomic_load_n(&gWifiLock,__ATOMIC_ACQUIRE)){if(lock)IOLockLock(lock);}
    ~WifiCallbacks(){if(lock)IOLockUnlock(lock);}
};
#define SHENG_SIOCSA80211 0x802869c8UL   // _IOW('i', 200, struct apple80211req)
#define SHENG_SIOCGA80211 0xc02869c9UL   // _IOWR('i', 201, struct apple80211req)

namespace {

// The WiFi radio's address, as WifiProbe.cpp's boardMac makes it: FNV-1a of /chosen/unique-chip-id, locally administered, unicast.
bool radioAddress(uint8_t m[6]) {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    OSData *id = chosen ? OSDynamicCast(OSData, chosen->getProperty("unique-chip-id")) : nullptr;
    uint64_t seed = 0;
    if (id && id->getLength() >= sizeof seed) memcpy(&seed, id->getBytesNoCopy(), sizeof seed);
    OSSafeReleaseNULL(chosen);
    if (!seed) return false;
    uint64_t h = 0xcbf29ce484222325ull;
    for (unsigned i = 0; i < 8; ++i) h = (h ^ ((seed >> (8 * i)) & 0xff)) * 0x100000001b3ull;
    for (unsigned i = 0; i < 6; ++i) m[i] = (uint8_t)(h >> (8 * i));
    m[0] = (uint8_t)((m[0] & 0xfe) | 0x02);
    return true;
}

}  // namespace

// The wireless framework's connection to the interface (IOServiceOpen type 0), the transport it uses before it falls back to ioctls;
// only this one returns the request's own result, which the framework's scan needs to find the end of the result list. Methods, as
// the framework calls them (IOConnectCallStructMethod):
//   0  an Apple80211 request: input {request code, data length, data[0x3c00], the 40-byte request}, output the request's data
//      (4 bytes holding the value for a request without data); the result is the request's errno. The framework fills the
//      request's name, type and value only: the length of a set's data is the data length in front, that of a get's answer the
//      output's size.
//   1  one byte: requests go through this connection
//   5  one byte: events come through this connection's event pipe (no: the framework then listens on the kernel event socket)
//   7  one byte: the driver is a DriverKit one (no)
// A set needs the administrator privilege, as the wireless daemon has.
// The original sandbox profiles of the wireless daemons allow the class IO80211APIUserClient only (IO80211Family's, which is in the
// collection, so the name cannot be taken here); the interface names those daemons in NativeSandboxGrantProcess, the kernel's grant
// in place of the profile's verdict (IOUserClient.cpp, native_sandbox_grant).
class ShengWifiUserClient : public IOUserClient {
    OSDeclareDefaultStructors(ShengWifiUserClient)
    enum { kInputSize = 0x3c30, kRequestAt = 0x3c08, kDataAt = 8, kDataMax = 0x3c00 };
    bool administrator = false;
public:
    bool initWithTask(task_t owningTask, void *securityID, UInt32 type) override {
        if (!IOUserClient::initWithTask(owningTask, securityID, type)) return false;
        administrator = clientHasPrivilege(securityID, kIOClientPrivilegeAdministrator) == kIOReturnSuccess;
        return true;
    }
    IOReturn clientClose() override { terminate(); return kIOReturnSuccess; }
    static IOReturn answerByte(IOExternalMethodArguments *args, uint8_t value) {
        if (!args->structureOutput || args->structureOutputSize < 1) return kIOReturnBadArgument;
        *static_cast<uint8_t *>(args->structureOutput) = value;
        args->structureOutputSize = 1;
        return kIOReturnSuccess;
    }
    IOReturn request(IOExternalMethodArguments *args) {
        WifiCallbacks callbacks;if(!callbacks.lock)return kIOReturnNotReady;
        int (*handler)(unsigned long, void *, void *, uint32_t) = __atomic_load_n(&gWifiKernelRequest,__ATOMIC_ACQUIRE);
        if (!handler) return ENXIO;
        uint8_t *input = static_cast<uint8_t *>(IOMallocData(kInputSize));
        if (!input) return kIOReturnNoMemory;
        IOReturn result = kIOReturnBadArgument;
        bool have = false;
        if (IOMemoryDescriptor *in = args->structureInputDescriptor) {
            // The caller's pages are wired for the copy (readBytes of an unprepared descriptor panics).
            if (in->getLength() == kInputSize && in->prepare() == kIOReturnSuccess) {
                have = in->readBytes(0, input, kInputSize) == kInputSize;
                in->complete();
            }
        } else if (args->structureInput && args->structureInputSize == kInputSize) {
            memcpy(input, args->structureInput, kInputSize); have = true;
        }
        if (have) {
            uint32_t code, sent, length;
            memcpy(&code, input, 4); memcpy(&sent, input + 4, 4); memcpy(&length, input + kRequestAt + 24, 4);
            const bool set = code == SHENG_SIOCSA80211;
            // The request's own length field is not filled. A set's payload has the length sent in front of it; a get that brings
            // an output buffer has that buffer's size (4 bytes: the value alone).
            const uint32_t room = args->structureOutputDescriptor ? args->structureOutputDescriptorSize : args->structureOutputSize;
            if (!length) {
                if (set) length = sent;
                else if (room > 4) length = room < kDataMax ? room : static_cast<uint32_t>(kDataMax);
                memcpy(input + kRequestAt + 24, &length, 4);
            }
            if ((set || code == SHENG_SIOCGA80211) && length <= kDataMax && sent <= kDataMax) {
                if (set && !administrator) result = kIOReturnNotPrivileged;
                else {
                    if (sent < length) memset(input + kDataAt + sent, 0, length - sent);   // what the caller did not send is zero
                    result = static_cast<IOReturn>(handler(code, input + kRequestAt, input + kDataAt, length));
                    if (!result && !set) {
                        uint32_t value; memcpy(&value, input + kRequestAt + 20, 4);
                        memcpy(&length, input + kRequestAt + 24, 4);
                        if (length > kDataMax) length = kDataMax;
                        const void *from = length ? static_cast<const void *>(input + kDataAt) : &value;
                        const uint32_t bytes = length ? length : 4;
                        if (IOMemoryDescriptor *out = args->structureOutputDescriptor) {
                            const uint32_t n = bytes < args->structureOutputDescriptorSize ? bytes : args->structureOutputDescriptorSize;
                            if (out->prepare() != kIOReturnSuccess) result = kIOReturnVMError;
                            else {
                                if (out->writeBytes(0, from, n) != n) result = kIOReturnVMError;
                                else args->structureOutputDescriptorSize = n;
                                out->complete();
                            }
                        } else if (args->structureOutput) {
                            const uint32_t n = bytes < args->structureOutputSize ? bytes : args->structureOutputSize;
                            memcpy(args->structureOutput, from, n); args->structureOutputSize = n;
                        }
                    }
                }
            }
        }
        IOFreeData(input, kInputSize);
        return result;
    }
    IOReturn externalMethod(uint32_t selector, IOExternalMethodArguments *args, IOExternalMethodDispatch *, OSObject *, void *) override {
        switch (selector) {
        case 0: return request(args);
        case 1: return answerByte(args, 1);
        case 5: case 7: return answerByte(args, 0);
        default: return kIOReturnUnsupported;
        }
    }
};

OSDefineMetaClassAndStructors(ShengWifiUserClient, IOUserClient)

class ShengWifiInterface : public IOEthernetInterface {
    OSDeclareDefaultStructors(ShengWifiInterface)
public:
    // The interface's ioctls arrive here (IONetworkInterface's if_ioctl: arg0 the ifnet, arg1 the request). Before the module
    // attached there is no radio to ask: ENXIO, as for a device that is not there.
    SInt32 performCommand(IONetworkController *controller, unsigned long cmd, void *arg0, void *arg1) override {
        if (cmd == SHENG_SIOCSA80211 || cmd == SHENG_SIOCGA80211) {
            WifiCallbacks callbacks;if(!callbacks.lock)return ENXIO;
            int (*request)(unsigned long, void *) = __atomic_load_n(&gWifiRequest,__ATOMIC_ACQUIRE);
            return request && arg1 ? request(cmd, arg1) : ENXIO;
        }
        return IOEthernetInterface::performCommand(controller, cmd, arg0, arg1);
    }
    // Type 0 is the wireless framework's connection; the family's own types stay the family's.
    IOReturn newUserClient(task_t owningTask, void *securityID, UInt32 type, IOUserClient **handler) override {
        if (type != 0) return IOEthernetInterface::newUserClient(owningTask, securityID, type, handler);
        if (!__atomic_load_n(&gWifiKernelRequest,__ATOMIC_ACQUIRE)) return kIOReturnNotReady;
        ShengWifiUserClient *client = OSTypeAlloc(ShengWifiUserClient);
        if (!client || !client->initWithTask(owningTask, securityID, type)) { OSSafeReleaseNULL(client); return kIOReturnNoMemory; }
        if (!client->attach(this)) { client->release(); return kIOReturnError; }
        if (!client->start(this)) { client->detach(this); client->release(); return kIOReturnError; }
        *handler = client;
        return kIOReturnSuccess;
    }
    // The interface's subfamily is Wi-Fi (the wireless framework lists the Ethernet-family interfaces whose SIOCGIFTYPE answer
    // says so); the family takes it between init and the attach. Named once the network stack attached it: the framework
    // looks the service up by that property.
    IOReturn attachToDataLinkLayer(IOOptionBits options, void *parameter) override {
        setInterfaceSubType(IFNET_SUBFAMILY_WIFI);
        const IOReturn result = IOEthernetInterface::attachToDataLinkLayer(options, parameter);
        if (result == kIOReturnSuccess) {
            char name[16];
            snprintf(name, sizeof name, "%s%u", getNamePrefix(), getUnitNumber());
            setProperty("IOInterfaceName", name);
        }
        return result;
    }
};

OSDefineMetaClassAndStructors(ShengWifiInterface, IOEthernetInterface)

class B5qEthernet : public IOEthernetController {
    OSDeclareDefaultStructors(B5qEthernet)
    IOEthernetInterface *interface = nullptr;
    const IONetworkMedium *medium = nullptr;
    uint8_t address[6] = {};
public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    // The family's start waits for IOBSD unless the controller says not to; that wait needs IOResources matched, which it is not while
    // this controller, attached to IOResources, is being started there: a random boot deadlock (macOS-DroidVM 0855e2a, DroidVMEthernet).
    UInt32 getFeatures() const override { return kIONetworkFeatureNoBSDWait; }
    IONetworkInterface *createInterface() override {
        ShengWifiInterface *made = OSTypeAlloc(ShengWifiInterface);
        if (made && !made->init(this)) OSSafeReleaseNULL(made);
        return made;
    }
    IOReturn getHardwareAddress(IOEthernetAddress *out) override {
        if (!out) return kIOReturnBadArgument;
        memcpy(out->bytes, address, sizeof address);
        return kIOReturnSuccess;
    }
    IOReturn enable(IONetworkInterface *) override {
        enabled = true;
        link(!__atomic_load_n(&gWifiOutput,__ATOMIC_ACQUIRE) || __atomic_load_n(&gWifiLink,__ATOMIC_ACQUIRE));
        return kIOReturnSuccess;
    }
    IOReturn disable(IONetworkInterface *) override {
        setLinkStatus(kIONetworkLinkValid, nullptr);
        enabled = false;
        return kIOReturnSuccess;
    }
    // To the WiFi module's queue once it attached (it takes the frame in every case); before that consumed and counted as dropped,
    // as a controller with no carrier does.
    UInt32 outputPacket(mbuf_t packet, void *) override {
        WifiCallbacks callbacks;
        if(callbacks.lock)if (int (*output)(mbuf_t) = __atomic_load_n(&gWifiOutput,__ATOMIC_ACQUIRE)) {output(packet); return kIOReturnOutputSuccess;}
        freePacket(packet);
        return kIOReturnOutputDropped;
    }
    static IOReturn linkAction(OSObject *owner,void *value,void *,void *,void *){
        auto *self=static_cast<B5qEthernet*>(owner);
        if(!self->enabled)return kIOReturnSuccess;
        if(value)self->setLinkStatus(kIONetworkLinkValid|kIONetworkLinkActive,self->medium,1000ULL*1000*1000);
        else self->setLinkStatus(kIONetworkLinkValid,nullptr);
        return kIOReturnSuccess;
    }
    void link(bool up){
        if(auto *gate=getCommandGate())gate->runAction(linkAction,reinterpret_cast<void*>(uintptr_t(up)));
    }
    ifnet_t bsdIfnet() const {return interface ? interface->getIfnet() : nullptr;}
    bool enabled = false;
    IOReturn setPromiscuousMode(bool) override { return kIOReturnSuccess; }
    IOReturn setMulticastMode(bool) override { return kIOReturnSuccess; }
    IOReturn setMulticastList(IOEthernetAddress *, UInt32) override { return kIOReturnSuccess; }
};

OSDefineMetaClassAndStructors(B5qEthernet, IOEthernetController)

static B5qEthernet *volatile gController;   // the started controller (never stopped)

bool B5qEthernet::start(IOService *provider)
{
    if (!radioAddress(address) || !IOEthernetController::start(provider)) return false;
    OSDictionary *media = OSDictionary::withCapacity(1);
    // An IEEE 802.11 medium, as the interface's SIOCGIFMEDIA answer (the family answers from this dictionary).
    IONetworkMedium *auto1g = IONetworkMedium::medium(IOMediumType(kIOMediumIEEE80211Auto), 1000ULL * 1000 * 1000);
    bool ok = media && auto1g && IONetworkMedium::addMedium(media, auto1g) && publishMediumDictionary(media);
    medium = ok ? IONetworkMedium::getMediumWithType(getMediumDictionary(), auto1g->getType()) : nullptr;
    OSSafeReleaseNULL(auto1g);
    OSSafeReleaseNULL(media);
    if (!ok || !medium) {IOEthernetController::stop(provider); return false;}
    if(!setProperty("IOBuiltin", true) || !setProperty("IOClassNameOverride", "IO80211Controller")) {IOEthernetController::stop(provider);return false;}
    if (!attachInterface(reinterpret_cast<IONetworkInterface **>(&interface), false)) {IOEthernetController::stop(provider);return false;}
    if(!interface->setProperty("IO80211InterfaceRole", "Infrastructure") ||
       !interface->setProperty("NativeSandboxGrantProcess", "airportd,sharingd,wifivelocityd")) {
        detachInterface(interface);OSSafeReleaseNULL(interface);IOEthernetController::stop(provider);return false;
    }
    interface->registerService();
    return true;
}

void B5qEthernet::stop(IOService *provider)
{
    if (interface) {detachInterface(interface); OSSafeReleaseNULL(interface);}
    IOEthernetController::stop(provider);
}

namespace {

static void ethernetWorker(void *,wait_result_t) {
    OSReturn loaded=OSKextLoadKextWithIdentifier("com.apple.iokit.IONetworkingFamily");
    if(loaded!=kOSReturnSuccess && loaded!=kOSKextReturnStartStopError)b5q_ethernet_state=-1;
    else {
        void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if(!handle)b5q_ethernet_state=-2;
        else {
            b5q_ethernet_static_init();
            if(OSMetaClass::postModLoad(handle))b5q_ethernet_state=-3;
            else {
                B5qEthernet *controller=OSTypeAlloc(B5qEthernet);
                IOService *parent=IOService::getResourceService();bool attached=false;
                if(!controller || !controller->init(nullptr) || !parent)b5q_ethernet_state=-4;
                else if(!(attached=controller->attach(parent)))b5q_ethernet_state=-5;
                else if(!controller->start(parent))b5q_ethernet_state=-6;
                else {controller->registerService();controller->retain();gController=controller;b5q_ethernet_state=1;}
                if(b5q_ethernet_state!=1 && attached)controller->detach(parent);
                OSSafeReleaseNULL(controller);
            }
        }
    }
    IOLog("B5qEthernet: TimeSync/Wi-Fi interface state %d\n",b5q_ethernet_state);
    thread_terminate(current_thread());
}

}  // namespace

// The WiFi module (WifiNet.cpp, macOS): its transmit function and its Apple80211 request handler, for an ioctl and for a kernel buffer;
// the link goes down until it reports a join. False without the controller.
extern "C" bool sheng_ethernet_wifi_attach(int (*output)(mbuf_t), int (*request)(unsigned long, void *),
                                           int (*kernelRequest)(unsigned long, void *, void *, uint32_t))
{
    B5qEthernet *controller = gController;
    if (!controller || !output) return false;
    if(!wifiLockReady())return false;
    {
        WifiCallbacks callbacks;
        __atomic_store_n(&gWifiLink,false,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiRequest,request,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiKernelRequest,kernelRequest,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiOutput,output,__ATOMIC_RELEASE);
    }
    controller->link(false);
    return true;
}
// Taking this mutex drains every previously copied callback before Linux frees its queues.
extern "C" void sheng_ethernet_wifi_detach(void){
    {
        WifiCallbacks callbacks;
        __atomic_store_n(&gWifiOutput,nullptr,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiRequest,nullptr,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiKernelRequest,nullptr,__ATOMIC_RELEASE);
        __atomic_store_n(&gWifiLink,false,__ATOMIC_RELEASE);
    }
    auto *controller=__atomic_load_n(&gController,__ATOMIC_ACQUIRE);
    if(controller)controller->link(false);
}
// The module's link: up after a join, down when it is lost or left.
extern "C" void sheng_ethernet_wifi_link(bool up)
{
    __atomic_store_n(&gWifiLink,up,__ATOMIC_RELEASE);
    B5qEthernet *controller = gController;
    if (controller) controller->link(up);
}
// The interface's ifnet: none until the network configuration has named the interface (IONetworkStack attaches it then).
extern "C" ifnet_t sheng_ethernet_ifnet(void)
{
    B5qEthernet *controller = gController;
    return controller ? controller->bsdIfnet() : nullptr;
}

// The board entry (LegacyDisplayProbe.cpp's late probes), macOS only: ethernet=1.
extern "C" void b5q_ethernet_start(void)
{
    unsigned enabled = 0;
    if (!PE_parse_boot_argn("ethernet", &enabled, sizeof enabled) || enabled != 1) return;
    static uint32_t once=0; if (__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;
    thread_t thread = nullptr;
    if (kernel_thread_start(ethernetWorker, nullptr, &thread) == KERN_SUCCESS) thread_deallocate(thread);
    else {b5q_ethernet_state=-7;IOLog("B5qEthernet: worker allocation failed\n");}
}
