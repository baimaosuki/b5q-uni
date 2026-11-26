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

// A status bit that merely stays asserted is not a new edge. Only a 0->1
// transition in CSC/PEC/PLC starts a port-edge diagnostic; a PED 1->0 drop is
// also an edge. This prevents one stuck condition from consuming all four
// diagnostic slots.
// The host session gets a 20 x 50ms attach window so the power hold reaches
// both xHCI ports before their first U3. Two held ports end the fast window;
// a single-port board still uses the full 1000ms.
constexpr unsigned kPortPowerHoldSlots = 8;
constexpr unsigned kFastPortPollAttempts = 20;
inline bool fastPortPollNeeded(unsigned holds) { return holds < 2u; }

inline bool portEdge(uint32_t previous, uint32_t current) {
    constexpr uint32_t kEdgeMask = (1u << 17) | (1u << 18) | (1u << 22);
    return ((previous & 2u) && !(current & 2u)) ||
           ((current & kEdgeMask & ~previous) != 0u);
}
}  // namespace B5qUsbHostRole
