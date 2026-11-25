// SPDX-License-Identifier: GPL-2.0-only
#include "B5qBtFifo.h"
#include "qbt_geni_regs.h"
#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <vector>
struct Model {
    b5q_bt_fifo g{};
    uint32_t regs[0x1000/4]{};
    std::deque<uint8_t> input,pendingWire;
    std::vector<uint8_t> output,received;
    unsigned queuedWords=0,commandLeft=0,accept=8192,wakes=0,writes=0;
    bool masked=true,ctsLow=true;
    uint64_t time=1;
    Model() {regs[0x68/4]=0x203;regs[0xe24/4]=regs[0xe28/4]=(32u<<24)|(16u<<16);}
    static uint32_t read(void *p,uint32_t reg) {
        auto &m=*static_cast<Model*>(p);
        assert(reg<0xc00 || reg==0xe24 || reg==0xe28); // no DMA/SMMU reads
        if(reg==0x800)return m.queuedWords;
        if(reg==0x804)return uint32_t((m.input.size()+3)/4)|(1u<<31)|((uint32_t(m.input.size())%4)<<28);
        if(reg==0x780) {
            uint32_t w=0;for(unsigned i=0;i<4 && !m.input.empty();i++){w|=uint32_t(m.input.front())<<(8*i);m.input.pop_front();}return w;
        }
        return m.regs[reg/4];
    }
    static void write(void *p,uint32_t reg,uint32_t v) {
        auto &m=*static_cast<Model*>(p);m.writes++;
        assert(reg<0xc00 || reg==0xe18 || reg==0xe1c); // no DMA address/control writes
        if(reg==0x618){m.regs[0x610/4]&=~v;return;}
        if(reg==0x648){m.regs[0x640/4]&=~v;return;}
        if(reg==0x600){m.commandLeft=m.regs[0x270/4];m.regs[0x40/4]|=1;}
        if(reg==0x630)m.regs[0x40/4]|=1u<<12;
        if(reg==0x700){
            assert(m.queuedWords<16 && m.commandLeft);
            for(unsigned i=0;i<4 && m.commandLeft;i++,m.commandLeft--)m.pendingWire.push_back(uint8_t(v>>(8*i)));
            m.queuedWords++;return;
        }
        m.regs[reg/4]=v;
    }
    static void barrier(void*){}
    static uint64_t now(void *p){return static_cast<Model*>(p)->time;}
    static void mask(void *p,bool value){static_cast<Model*>(p)->masked=value;}
    static void wake(void *p){static_cast<Model*>(p)->wakes++;}
    static size_t receive(void *p,const uint8_t *b,size_t n){
        auto &m=*static_cast<Model*>(p);n=std::min(n,size_t(m.accept));m.received.insert(m.received.end(),b,b+n);return n;
    }
    int prepare(){b5q_bt_fifo_ops ops{this,read,write,barrier,now,mask,wake,receive};return b5q_bt_fifo_prepare(&g,&ops);}
    void start(){assert(!prepare());assert(!b5q_bt_fifo_set_rate(&g,115200,7372800,16));assert(!b5q_bt_fifo_start(&g));}
    void drain(){if(!ctsLow)return;while(!pendingWire.empty()){output.push_back(pendingWire.front());pendingWire.pop_front();}queuedWords=0;regs[0x610/4]|=1u<<30;if(!commandLeft){regs[0x610/4]|=1;regs[0x40/4]&=~1u;}}
    void inject(const std::vector<uint8_t>& v){assert(input.empty());input.insert(input.end(),v.begin(),v.end());regs[0x640/4]|=1u<<27;}
};
int main(){
    {Model m;m.regs[0x64/4]=1;assert(m.prepare()==-ENOTSUP && !m.writes && m.masked);}
    {Model m;m.regs[0x68/4]=0x103;assert(m.prepare()==-ENXIO && !m.writes);}
    {Model m;m.regs[0x40/4]=1;assert(m.prepare()==-EBUSY && !m.writes);}
    {Model m;m.regs[0xe24/4]=0;assert(m.prepare()==-ENXIO && !m.writes);}
    {Model m;assert(!m.prepare());assert(b5q_bt_fifo_set_rate(&m.g,0,7372800,16)==-EINVAL);
     assert(b5q_bt_fifo_set_rate(&m.g,3200000,19200000,16)==-ERANGE);
     assert(!b5q_bt_fifo_set_rate(&m.g,3200000,51200000,16));assert(!b5q_bt_fifo_start(&m.g));
     assert(m.regs[0x258/4]==0 && !m.masked);b5q_bt_fifo_irq(&m.g);assert(m.masked && m.wakes==1);
     b5q_bt_fifo_service(&m.g);assert(!m.masked && m.g.stats.interrupts==1);}
    for(unsigned length=1;length<=4096;length++) {
        Model m;m.start();std::vector<uint8_t> p(length);for(unsigned i=0;i<length;i++)p[i]=uint8_t(i*67+length);
        assert(b5q_bt_fifo_write(&m.g,p.data(),p.size())==p.size());
        assert(!b5q_bt_fifo_write(&m.g,p.data(),1));
        for(unsigned budget=0;m.g.tx_busy && budget<66;budget++){m.drain();b5q_bt_fifo_service(&m.g);}
        assert(!m.g.tx_busy && m.output==p && m.g.stats.tx_bytes==length && b5q_bt_fifo_drained(&m.g));
        assert(!(m.regs[0x614/4]&(1u<<30)));
    }
    for(unsigned length=1;length<=64;length++) {
        Model m;m.start();m.accept=3;std::vector<uint8_t> p(length);
        for(unsigned i=0;i<length;i++)p[i]=uint8_t(i+length);m.inject(p);
        for(unsigned budget=0;(m.g.rx_count || !m.input.empty()) && budget<64;budget++)b5q_bt_fifo_service(&m.g);
        assert(m.received==p && !m.g.rx_count && m.g.stats.rx_bytes==length);
    }
    {Model m;m.start();m.accept=0;std::vector<uint8_t> block(64,0x81);
     for(unsigned i=0;i<128;i++){m.inject(block);b5q_bt_fifo_service(&m.g);}
     assert(m.g.rx_count==8192 && m.regs[0x2ac/4]==G_RFR_OFF);
     assert(!(m.regs[0x644/4]&((1u<<26)|(1u<<27))) && b5q_bt_fifo_deadline(&m.g)==m.time+1000000);
     m.inject(block);b5q_bt_fifo_service(&m.g);assert(m.input.size()==64 && m.g.state==B5Q_BT_FIFO_RUN);
     m.accept=8192;b5q_bt_fifo_service(&m.g);assert(m.received.size()==8256 && m.input.empty());
     assert(m.regs[0x644/4]&(1u<<26));}
    {Model m;m.start();m.inject(std::vector<uint8_t>(65,1));b5q_bt_fifo_service(&m.g);assert(m.g.error==-EOVERFLOW && m.masked);}
    {Model m;m.start();m.regs[0x640/4]=1u<<9;b5q_bt_fifo_service(&m.g);assert(m.g.error==-EIO && m.masked);}
    {Model m;m.start();assert(b5q_bt_fifo_quiesce(&m.g)==-EINPROGRESS);
     m.regs[0x40/4]=0;b5q_bt_fifo_service(&m.g);assert(m.g.state==B5Q_BT_FIFO_STOPPED && m.masked);
     assert(!b5q_bt_fifo_resume(&m.g));}
    {Model m;m.start();assert(b5q_bt_fifo_quiesce(&m.g)==-EINPROGRESS);
     m.time+=10000000;b5q_bt_fifo_service(&m.g);assert(m.g.state==B5Q_BT_FIFO_ABORT && m.regs[0x634/4]==2);
     m.time+=10000000;b5q_bt_fifo_service(&m.g);assert(m.g.error==-ETIMEDOUT && m.masked);}
    // Reset/mux garbage is discarded before the first HCI request.
    {Model m;assert(!m.prepare());assert(!b5q_bt_fifo_set_rate(&m.g,115200,7372800,16));
     m.input={0,0,0,0};m.regs[0x640/4]=0xc00;
     assert(!b5q_bt_fifo_startup(&m.g)&&m.input.empty());
     m.regs[0x640/4]=0xc00;m.input={0,0};b5q_bt_fifo_service(&m.g);
     assert(m.g.state==B5Q_BT_FIFO_RUN&&m.g.stats.startup_line_errors==1&&m.received.empty());
     m.inject({4,14,1,0});b5q_bt_fifo_service(&m.g);assert((m.received==std::vector<uint8_t>{4,14,1,0}));}
    for(unsigned mode=0;mode<4;mode++){
     Model m;assert(!m.prepare());assert(!b5q_bt_fifo_set_rate(&m.g,115200,7372800,16));assert(!b5q_bt_fifo_startup(&m.g));
     if(mode==0){m.regs[0x640/4]=0xc00;b5q_bt_fifo_service(&m.g);}
     if(mode==1)m.time+=50000000;
     if(mode==2){const uint8_t command[]={1,3,12,0};assert(b5q_bt_fifo_write(&m.g,command,4)==4);}
     m.regs[0x640/4]=mode==3?1u<<24:0xc00;b5q_bt_fifo_service(&m.g);
     assert(m.g.state==B5Q_BT_FIFO_FAILED&&m.g.error==-EIO&&m.masked);
    }
    // 3.2Mbps NVM commands: 243B payload + H4/opcode/length, CTS stalls,
    // lost watermark/completion interrupts and short 7B CC replies. Hardware
    // consumes FIFO bytes only while CTS is asserted; no immediate echo.
    {Model m;assert(!m.prepare());assert(!b5q_bt_fifo_set_rate(&m.g,3200000,51200000,16));assert(!b5q_bt_fifo_start(&m.g));
     std::vector<uint8_t> expected;
     for(unsigned segment=0;segment<64;segment++){
      std::vector<uint8_t> command(249);command[0]=1;command[1]=0;command[2]=0xfc;command[3]=245;command[4]=0x1e;command[5]=243;
      for(unsigned i=6;i<command.size();i++)command[i]=uint8_t(segment+i);
      expected.insert(expected.end(),command.begin(),command.end());
      assert(b5q_bt_fifo_write(&m.g,command.data(),command.size())==command.size());
      assert(b5q_bt_fifo_deadline(&m.g)==m.time+1000000);
      const auto sent=m.output.size();m.ctsLow=false;
      for(unsigned i=0;i<3;i++){m.time+=1000000;m.drain();b5q_bt_fifo_service(&m.g);assert(m.output.size()==sent&&m.g.tx_busy);}
      m.ctsLow=true;
      for(unsigned budget=0;m.g.tx_busy&&budget<10;budget++){
       m.time=b5q_bt_fifo_deadline(&m.g);assert(m.time!=UINT64_MAX);
       m.drain();m.regs[0x610/4]&=~(1u<<30); // lost TX watermark edge
       b5q_bt_fifo_service(&m.g);
      }
      assert(!m.g.tx_busy&&b5q_bt_fifo_drained(&m.g)&&m.output==expected);
      m.inject({4,14,5,1,0,0xfc,0});b5q_bt_fifo_service(&m.g);
      m.inject({0x1e});b5q_bt_fifo_service(&m.g); // final partial FIFO word
      assert(m.g.stats.rx_bytes==(segment+1)*8&&!m.g.rx_count&&!m.g.error);
     }
     assert(m.g.stats.tx_bytes==expected.size()&&m.g.flow&&m.regs[0x2ac/4]==0);
    }
    puts("PASS64 NVM-like TLV segments at3.2Mbps, causalCTS pauses, lostwatermark, timedprogress, partialRXACK, zeroDMA");
    puts("PASS startup stale RX/single pre-command break recovery; repeated/late/in-command/FIFO errors still fatal");
    puts("PASS production BT FIFO: capability refusal, 4096 TX lengths, partial RX/tails/backpressure, IRQ, bounded cancel/abort, zero DMA registers");
}
