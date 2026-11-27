// SPDX-License-Identifier: BSD-2-Clause-Patent
// Pure decision for a PD power-role swap on an already enumerated USB host.
// A powered hub may change power role while its data role, CC orientation,
// water state and DP lane allocation stay exactly as applied. That is a VBUS
// source change, not a new cable session: the live xHCI controller and its
// enumerated devices must survive it. Anything else keeps the full
// leaveRole()/enterRole() rebuild.
#pragma once
#include <stdint.h>

namespace B5qUsbHostRole {
struct View {
    bool appliedHost;          // gRoleApplied == kRoleHost
    bool wantedHost;           // gRoleWanted == kRoleHost
    bool hostObjects;          // gHost and gHostNub are still alive
    bool dpLanesUnchanged;     // !dpEnabled || requestedDp == gDpLanes
    bool cableValid;           // PDIC sample is current
    bool cableWater;           // moisture detected
    bool cableAttached;        // VBUS power role is Sink or Source
    bool cableHost;            // PD data role is DFP/host
    bool orientationUnchanged; // CC pin/orientation equals the applied one
};

inline bool canHotSwapVbus(const View &v) {
    return v.appliedHost && v.wantedHost && v.hostObjects && v.dpLanesUnchanged &&
           v.cableValid && !v.cableWater && v.cableAttached && v.cableHost &&
           v.orientationUnchanged;
}

// xhci-hub.c::xhci_port_state_to_neutral, followed by PORT_PE (RW1C).
// Preserve RO/RWS fields and leave all other W1C/reset strobes clear.
inline uint32_t disableSuperSpeed(uint32_t port){
    constexpr uint32_t neutral=(1u<<0)|(1u<<3)|(0xfu<<10)|(0xfu<<5)|(1u<<9)|(3u<<14)|(7u<<25);
    return (port&neutral)|(1u<<1);
}

inline bool canReleaseSuperSpeed(const View &v,unsigned before,unsigned after){
    return v.appliedHost&&v.wantedHost&&v.hostObjects&&v.cableValid&&!v.cableWater&&
           v.cableAttached&&v.cableHost&&v.orientationUnchanged&&before!=4u&&after==4u;
}

// A status bit that merely stays asserted is not a new edge. Only a 0->1
// transition in CSC/PEC/PLC starts a port-edge diagnostic; a PED 1->0 drop is
// also an edge. This prevents one stuck condition from consuming all four
// diagnostic slots.
// The host session gets a 20 x 50ms attach window so the power hold reaches
// connected xHCI ports before their first U3. The caller separately bounds
// the initial wait for a port that has not appeared in PORTSC yet.
constexpr unsigned kPortPowerHoldSlots = 8;
constexpr unsigned kFastPortPollAttempts = 20;
inline bool fastPortPollNeeded(unsigned holds,unsigned connectedPorts) {
    return connectedPorts!=0u&&holds<connectedPorts;
}
inline bool portConnectedForHold(const char *name,uint32_t portsc1,uint32_t portsc2) {
    if(!name)return false;
    for(const char *at=name;*at;at++){
        const char *two="AppleUSB20",*three="AppleUSB30";unsigned i=0;
        while(at[i]&&two[i]&&at[i]==two[i])i++;
        if(!two[i])return (portsc1&1u)!=0;
        i=0;while(at[i]&&three[i]&&at[i]==three[i])i++;
        if(!three[i])return (portsc2&1u)!=0;
    }
    return false;
}

inline bool portEdge(uint32_t previous, uint32_t current) {
    constexpr uint32_t kEdgeMask = (1u << 17) | (1u << 18) | (1u << 22);
    return ((previous & 2u) && !(current & 2u)) ||
           ((current & kEdgeMask & ~previous) != 0u);
}
}  // namespace B5qUsbHostRole
