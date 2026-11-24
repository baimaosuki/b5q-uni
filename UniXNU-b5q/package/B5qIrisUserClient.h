/* SPDX-License-Identifier: APSL-2.0 */
#pragma once
#include <IOKit/IOUserClient.h>
// Exact IOUserClient2022 declaration from locked XNU12377.121.6
// iokit/IOKit/IOUserClient.h:564..590. No instances/vptrs are manufactured.
#ifndef IOUSERCLIENT2022_SUPPORTED
class IOUserClient2022 : public IOUserClient
{
    OSDeclareDefaultStructors(IOUserClient2022);
private:
    MIG_SERVER_ROUTINE virtual IOReturn
    externalMethod(uint32_t selector,IOExternalMethodArguments *arguments,
        IOExternalMethodDispatch *dispatch=NULL,OSObject *target=NULL,
        void *reference=NULL) APPLE_KEXT_OVERRIDE;
protected:
    IOReturn dispatchExternalMethod(uint32_t selector,IOExternalMethodArgumentsOpaque *arguments,
        const IOExternalMethodDispatch2022 dispatchArray[],size_t dispatchArrayCount,
        OSObject *target,void *reference);
public:
    MIG_SERVER_ROUTINE virtual IOReturn
    externalMethod(uint32_t selector,IOExternalMethodArgumentsOpaque *arguments)=0;
    OSMetaClassDeclareReservedUnused(IOUserClient2022,0);
    OSMetaClassDeclareReservedUnused(IOUserClient2022,1);
    OSMetaClassDeclareReservedUnused(IOUserClient2022,2);
    OSMetaClassDeclareReservedUnused(IOUserClient2022,3);
};
#endif
// The private nonvirtual member uses the standard AArch64 this/x1/x2 ABI.
// Bind its real symbol, preserving its native locking/open-state semantics.
// The actual returned kernel must define this import during closure checks.
extern "C" IOReturn b5q_iris_call_external(IOUserClient *,uint32_t,IOExternalMethodArguments *)
    __asm__("__ZN12IOUserClient18callExternalMethodEjP25IOExternalMethodArguments");
