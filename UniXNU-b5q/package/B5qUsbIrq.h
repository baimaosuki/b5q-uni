#pragma once
#include <stdint.h>
namespace B5qUsbIrq {
struct Window {
 uint64_t began=0;
 uint32_t count=0;
 static constexpr uint32_t limit=65536;
 bool observe(uint64_t now,uint64_t oneSecond) {
  if(!count || now-began>=oneSecond){began=now;count=0;}
  return ++count>limit;
 }
};
}
