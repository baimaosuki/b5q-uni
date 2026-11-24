/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung dsi_ctrl_hw_cmn_kickoff_fifo_command, msm_drm.ko .text+1403c0.
 * DSI command FIFO transfers do not fetch memory and need no DMA mapping.
 * The caller serializes access to the retained inner-panel controller. */
#pragma once
#include <stdint.h>
namespace B5qPanelCommand {
constexpr uint32_t control=0x004, dmaControl=0x03c, length=0x04c;
constexpr uint32_t status=0x008;
constexpr uint32_t trigger=0x090, interrupts=0x110, pattern=0x15c;
constexpr uint32_t fifo=0x17c, fifoReset=0x1ec;
constexpr uint32_t done=1, error=1u<<24;
enum class Result { Ok, Off, Busy, Range, Timeout, Error };

template<class Read,class Write,class Delay>
Result brightness(Read read,Write write,Delay delay,uint32_t level) {
    if(level>4095)return Result::Range;
    // Do not turn on/reset an unowned controller or overwrite an in-flight
    // firmware command. The retained scanout stays running throughout.
    if(!(read(control)&1))return Result::Off;
    // Original dsi_ctrl_hw_cmn_wait_for_cmd_mode_mdp_idle checks bit2.
    // Never change command control while the retained MDP transfer is busy.
    if(read(status)&(1u<<2))return Result::Busy;
    const uint32_t oldPattern=read(pattern);
    if(oldPattern)return Result::Busy;
    const uint32_t oldDma=read(dmaControl),oldLength=read(length);
    // INT_CTRL mixes W1C status and enables. Acknowledge only DMA_DONE and
    // preserve enable bits; never clear another owner's completion/errors.
    constexpr uint32_t enables=(1u<<1)|(1u<<9)|(1u<<11)|(1u<<13)|
        (1u<<15)|(1u<<17)|(1u<<21)|(1u<<25)|(1u<<29)|(1u<<31);
    const uint32_t oldInterrupts=read(interrupts)&enables;
    if(read(interrupts)&error)return Result::Error;
    write(interrupts,oldInterrupts|done);
    write(pattern,0x30006);
    // MSM embedded long packet: WC=3, DCS long write 0x39, LAST|LONG.
    // Payload is DCS 0x51 followed by the panel's big-endian 12-bit level.
    write(fifo,0xc0390003);
    write(fifo,0xff000051|((level>>8)<<8)|((level&255)<<16));
    write(dmaControl,(oldDma&~((1u<<31)|(1u<<30)))|(1u<<28));
    write(length,8);
    write(trigger,1);
    Result result=Result::Timeout;
    // Samsung poll_dma_status uses a 5ms deadline in 10us steps.
    for(unsigned n=0;n<500;++n) {
        const uint32_t status=read(interrupts);
        if(status&error){result=Result::Error;break;}
        if(status&done){result=Result::Ok;break;}
        delay(10);
    }
    write(interrupts,oldInterrupts|done);
    write(pattern,0);
    write(fifoReset,1);delay(1);write(fifoReset,0);
    write(dmaControl,oldDma);write(length,oldLength);
    return result;
}
}
