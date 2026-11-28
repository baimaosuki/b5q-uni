/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
extern const IORegistryPlane *gIODTPlane;
namespace B5qFeatures {
// Bit1 is permanently unused: no hall GPIO or clamshell power policy.
enum:uint32_t {Battery=1u<<0,Backlight=1u<<2,Adsp=1u<<3,Audio=1u<<4,Video=1u<<5,DisplayPort=1u<<6};
// Feature selection belongs to the menu's ADT; it is never a hardware-ready
// flag. Each normal boot argument remains an explicit independent override.
inline unsigned option(const char *name,uint32_t bit,unsigned selected=1){
    unsigned value=0;if(PE_parse_boot_argn(name,&value,sizeof(value)))return value;
    uint32_t mask=0;if(PE_parse_boot_argn("b5q-f",&mask,sizeof(mask)))return mask&bit?selected:0;
    auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    auto *data=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-feature-mask")):nullptr;
    if(data&&data->getLength()==sizeof(mask))memcpy(&mask,data->getBytesNoCopy(),sizeof(mask));
    OSSafeReleaseNULL(chosen);return mask&bit?selected:0;
}
}
