// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <mach/vm_types.h>
#include <mach/kern_return.h>
// XNU12377 vm_kern_xnu.h: kmem_return_t lines70..78, kmem_guard_t98..104,
// KMEM_KOBJECT=0x100 and KMEM_DATA=0x8000, kmem_alloc_guard's scalar ABI.
// Keep the unchanged root-hash allocation off the private-header dependency
// tree when incrementally compiling this board object. Host preflight compares
// these contracts to the pinned XNU, and the real target linker resolves them.
struct b5q_kmem_return {
    kern_return_t status;
    union {vm_address_t address;vm_size_t size;void *pointer;vm_map_t submap;};
};
struct b5q_kmem_guard {uint16_t tag,typeHash;uint32_t options;};
static_assert(sizeof(b5q_kmem_return)==16 && sizeof(b5q_kmem_guard)==8,"XNU12377 kmem ABI");
extern "C" b5q_kmem_return kmem_alloc_guard(vm_map_t,vm_size_t,vm_offset_t,uint32_t,b5q_kmem_guard);
extern "C" vm_map_t kernel_map;
static inline kern_return_t b5q_root_hash_allocate(vm_offset_t *address,vm_size_t bytes) {
    // Original KMA_KOBJECT|KMA_DATA and VM_KERN_MEMORY_SECURITY, no policy change.
    const b5q_kmem_guard guard={23,0,0};
    b5q_kmem_return r=kmem_alloc_guard(kernel_map,bytes,0,0x8100,guard);
    *address=r.address;return r.status;
}
