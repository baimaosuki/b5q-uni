// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <assert.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define STATIC static
#define STATIC_ASSERT _Static_assert
#define OFFSET_OF offsetof
#define CONST const
#define IN
#define OUT
#define EFIAPI
#define TRUE true
#define FALSE false
#define VOID void
#define MAX_UINT32 UINT32_MAX
#define MAX_UINT64 UINT64_MAX
#define MAX_UINTN SIZE_MAX
#define EFI_PAGE_SIZE 4096
#define EFI_SUCCESS 0
#define EFI_NOT_STARTED 19
#define EFI_COMPROMISED_DATA 33
#define EFI_INCOMPATIBLE_VERSION 25
#define EfiReservedMemoryType 0
#define EfiBootServicesData 4
#define EfiConventionalMemory 7
#define AsciiStrCmp strcmp
#define ZeroMem(a, n) memset(a, 0, n)
#define CopyMem memcpy
typedef bool BOOLEAN;
typedef size_t UINTN;
typedef uint8_t UINT8;
typedef uint16_t UINT16;
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef char CHAR8;
typedef uint64_t EFI_STATUS;
typedef struct { UINT32 Data1; UINT16 Data2, Data3; UINT8 Data4[8]; } EFI_GUID;
typedef struct {
  UINT32 Type;
  UINT64 PhysicalStart, VirtualStart, NumberOfPages, Attribute;
} EFI_MEMORY_DESCRIPTOR;

static bool IsZeroBuffer(const void *buffer, size_t length)
{
  const char *p = buffer;
  for (size_t i = 0; i < length; ++i) {
    if (p[i]) {
      return false;
    }
  }
  return true;
}

static EFI_STATUS missing_protocol(EFI_GUID *guid, void *registration, void **value)
{
  assert(guid->Data1 == 0x16470a49 && registration == NULL && *value == NULL);
  return 14;
}
static struct { EFI_STATUS (*LocateProtocol)(EFI_GUID *, void *, void **); } services = {missing_protocol};
static __typeof__(services) *gBS = &services;

#include "B5qUsbDmaLoader.h"
#include "UsbDmaTables.h"

static UINT64 walk(const USB_DMA_TABLES *tables, UINT64 address, unsigned *shift)
{
  const UINT64 *page = tables->Pages;
  for (unsigned bit = 39; bit >= 12; bit -= 9) {
    UINT64 entry = page[(address >> bit) & 511];
    if ((entry & 3) == 0) {
      return 0;
    }
    if ((entry & 3) == 1 || bit == 12) {
      *shift = bit;
      return entry;
    }
    UINT64 pa = entry & USB_DMA_PA_MASK;
    assert(pa >= tables->PhysicalBase);
    UINT64 index = (pa - tables->PhysicalBase) / sizeof(UINT64);
    assert(index < tables->Used * USB_DMA_PAGE / sizeof(UINT64));
    page = tables->Pages + index;
  }
  return 0;
}

int main(void)
{
  static UINT64 pages[16 * USB_DMA_PAGE / sizeof(UINT64)];
  USB_DMA_TABLES tables = {pages, 0x950000000, 1, 16};
  assert(UsbDmaMapRange(&tables, 0x8c0000000, 0x900000000));
  assert(UsbDmaMapRange(&tables, 0x900001000, 0x900200000));
  assert(UsbDmaMapRange(&tables, 0x900200000, 0x900400000));
  unsigned shift = 0;
  UINT64 entry = walk(&tables, 0x8fffff000, &shift);
  assert(shift == 30 && entry == (0x8c0000000 | USB_DMA_LEAF_ATTR | 1));
  entry = walk(&tables, 0x900001000, &shift);
  assert(shift == 12 && entry == (0x900001000 | USB_DMA_LEAF_ATTR | 3));
  entry = walk(&tables, 0x900201000, &shift);
  assert(shift == 21 && entry == (0x900200000 | USB_DMA_LEAF_ATTR | 1));
  assert(!walk(&tables, 0x8b9a00000, &shift));
  assert(!walk(&tables, 0x900000000, &shift));
  assert(!walk(&tables, tables.PhysicalBase, &shift));
  assert(!UsbDmaMapRange(&tables, 0x8c0000000, 0x900000000));
  assert(!UsbDmaMapRange(&tables, B5Q_USB_DMA_LIMIT - 4096, B5Q_USB_DMA_LIMIT + 4096));
  tables.Capacity = tables.Used;
  assert(!UsbDmaMapRange(&tables, 0x8b9c00000, 0x8b9c01000));

  UINT8 tree[100] = {0};
  B5Q_USB_DMA_ADT adt = {MAX_UINTN, MAX_UINTN, MAX_UINTN};
  assert(FindUsbDmaProperty("b5q-usb-dma-ready", tree, 0, 4, &adt));
  assert(!FindUsbDmaProperty("b5q-usb-dma-ready", tree, 0, 4, &adt));
  assert(FindUsbDmaProperty("b5q-usb-dma-state", tree + 4, 4, 48, &adt));
  assert(FindUsbDmaProperty("b5q-usb-dma-diagnostics", tree + 52, 52, 48, &adt));
  B5Q_USB_DMA_RESULT result;
  GetUsbDmaResult(0x8c0004000, 0x100000000, &result);
  EFI_MEMORY_DESCRIPTOR map = {EfiReservedMemoryType, tables.PhysicalBase, 0, 16, 0};
  WriteUsbDmaResult(tree, &adt, &result, &map, sizeof(map), sizeof(map), 0x8c0004000, 0x100000000, FALSE);
  assert(tree[0] == 0 && result.Diagnostics.PrepareStatus == 14);
  result = (B5Q_USB_DMA_RESULT){
    .State = {1, 0x40, 0, 0, 0, 0, 0, 0x8c0004000, 0x80000000},
    .Diagnostics = {.TableBase = tables.PhysicalBase, .TableBytes = 4096, .MappedBytes = 0x80000000}
  };
  WriteUsbDmaResult(tree, &adt, &result, &map, sizeof(map), sizeof(map), 0x8c0004000, 0x80000000, FALSE);
  assert(tree[0] == 1);
  map.Type = EfiBootServicesData;
  WriteUsbDmaResult(tree, &adt, &result, &map, sizeof(map), sizeof(map), 0x8c0004000, 0x80000000, FALSE);
  assert(tree[0] == 0 && result.State.Map == 0);
  map.Type = EfiReservedMemoryType;
  result.State.OwnedBytes = 0x100000000;
  WriteUsbDmaResult(tree, &adt, &result, &map, sizeof(map), sizeof(map), 0x8c0004000, 0x100000000, FALSE);
  assert(tree[0] == 0);
  puts("PASS USB 1GiB/2MiB/4KiB mappings, unmapped holes, held table pool, optional ADT and final-map retry");
}
