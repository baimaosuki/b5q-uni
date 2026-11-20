// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qPeripheralHardware.h"
#include "NativeAdrenoSha256.h"
#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
// The ADT owns these OSData objects for the kernel lifetime. Pin them while
// the GMU/CP reference the buffers, including all failed startup paths.
static const uint8_t *b5q_gmu_firmware_image, *b5q_sqe_firmware_image, *b5q_zap_image;
static uint64_t b5q_gmu_firmware_image_size, b5q_sqe_firmware_image_size, b5q_zap_image_size;
static bool b5q_gpu_firmware_bind() {
    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    if (!chosen) return false;
    const char *names[]={"b5q-gmu-fw","b5q-sqe-fw","b5q-zap-fw"};
    const uint64_t sizes[]={B5qHardware::gmuFirmwareBytes,B5qHardware::sqeFirmwareBytes,B5qHardware::zapFirmwareBytes};
    const uint8_t *hashes[]={B5qHardware::gmuFirmwareSha256,B5qHardware::sqeFirmwareSha256,B5qHardware::zapFirmwareSha256};
    OSData *data[3]={}; bool valid=true;
    for (unsigned i=0;i<3;++i) {
        data[i]=OSDynamicCast(OSData,chosen->getProperty(names[i]));
        uint8_t hash[32]={};
        if (!data[i] || data[i]->getLength()!=sizes[i]) {valid=false; break;}
        NativeAdrenoSha256::hash(static_cast<const uint8_t *>(data[i]->getBytesNoCopy()),sizes[i],hash);
        if (memcmp(hash,hashes[i],32)) {valid=false; break;}
    }
    if (valid) {
        for (auto *d:data) d->retain();
        b5q_gmu_firmware_image=static_cast<const uint8_t *>(data[0]->getBytesNoCopy());
        b5q_sqe_firmware_image=static_cast<const uint8_t *>(data[1]->getBytesNoCopy());
        b5q_zap_image=static_cast<const uint8_t *>(data[2]->getBytesNoCopy());
        b5q_gmu_firmware_image_size=sizes[0];b5q_sqe_firmware_image_size=sizes[1];b5q_zap_image_size=sizes[2];
    }
    chosen->release();return valid;
}
