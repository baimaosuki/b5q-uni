/* SPDX-License-Identifier: GPL-2.0-only */
/* FIFO word packing and watermark ordering follow Samsung msm_geni_serial.c
 * handle_rx_hs/handle_rx_fifo_xfer/msm_geni_serial_handle_tx. No DMA register,
 * address, buffer mapping or SMMU operation exists in this transport. */
#include "B5qBtFifo.h"
#include "qbt_geni_regs.h"
#ifdef KERNEL
#include <sys/errno.h>
#include <sys/systm.h>
#else
#include <errno.h>
#include <string.h>
#endif
#define F_TX 0x700u
#define F_RX 0x780u
#define F_RX_STATUS 0x804u
#define F_TX_WM 0x80cu
#define F_HW_TX 0xe24u
#define F_IF_DISABLE 0x64u
#define F_SE_CPU_IRQS ((1u << 2) | (1u << 3))
#define F_TX_WATER (1u << 30)
#define F_RX_WATER (1u << 26)
#define F_RX_LAST (1u << 27)
#define F_FIFO_ERRORS (3u << 24)
#define F_M_ERRORS (G_CMD_ERRORS | (3u << 24) | (3u << 28))
#define F_CANCELLED (3u << 4)
#define F_S_IRQS (G_CMD_ERRORS | F_CANCELLED | G_LINE_ERRORS | F_RX_WATER | F_RX_LAST)
#define F_M_IRQS (F_M_ERRORS | F_CANCELLED | G_DONE | (1u << 31))
static uint32_t rd(struct b5q_bt_fifo *g, uint32_t r) {return g->ops.read(g->ops.context,r);}
static void wr(struct b5q_bt_fifo *g,uint32_t r,uint32_t v) {g->ops.write(g->ops.context,r,v);}
static void barrier(struct b5q_bt_fifo *g) {g->ops.barrier(g->ops.context);}
static uint64_t now(struct b5q_bt_fifo *g) {return g->ops.now_ns(g->ops.context);}
static void fifoMask(struct b5q_bt_fifo *g,bool value) {g->ops.irq_mask(g->ops.context,value);}
static void rfr(struct b5q_bt_fifo *g,bool ready) {wr(g,G_MANUAL_RFR,ready && g->flow ? 0 : G_RFR_OFF);}
static void fail(struct b5q_bt_fifo *g,int error) {
    g->error=error;g->state=B5Q_BT_FIFO_FAILED;g->stop_deadline=g->retry_at=0;
    rfr(g,false);wr(g,G_IRQ_EN,0);barrier(g);fifoMask(g,true);
}
int b5q_bt_fifo_prepare(struct b5q_bt_fifo *g,const struct b5q_bt_fifo_ops *ops) {
    if(!g || !ops || !ops->read || !ops->write || !ops->barrier || !ops->now_ns ||
       !ops->irq_mask || !ops->wake_worker || !ops->receive)return -EINVAL;
    memset(g,0,sizeof(*g));g->ops=*ops;g->flow=true;fifoMask(g,true);
    /* This is a read-only hardware capability, never clear it to force FIFO. */
    if(rd(g,F_IF_DISABLE)&1u)return -ENOTSUP;
    if(((rd(g,G_FW_REV)>>8)&255u)!=2)return -ENXIO;
    if(rd(g,G_STATUS)&(G_M_ACTIVE|G_S_ACTIVE))return -EBUSY;
    uint32_t tx=rd(g,F_HW_TX),rx=rd(g,G_HW_PARAM1);
    g->tx_depth=(tx>>16)&255u;g->rx_depth=(rx>>16)&255u;
    if(((tx>>24)&63u)!=32 || ((rx>>24)&63u)!=32 ||
       g->tx_depth<4 || g->rx_depth<4)return -ENXIO;
    wr(g,G_IRQ_EN,0);wr(g,G_GSI_EVENT,0);wr(g,G_M_IRQ_EN,0);wr(g,G_S_IRQ_EN,0);
    wr(g,G_M_CLEAR,UINT32_MAX);wr(g,G_S_CLEAR,UINT32_MAX);
    wr(g,G_CGC,rd(g,G_CGC)|0x7f);wr(g,G_OUTPUT,0x7f);wr(g,G_FORCE_DEFAULT,1);
    wr(g,G_DMA_MODE,0);
    wr(g,G_TX_PACK0,0x4380e);wr(g,G_TX_PACK1,0xc3e0e);
    wr(g,G_RX_PACK0,0x4380e);wr(g,G_RX_PACK1,0xc3e0e);wr(g,G_BYTE_GRAN,0);
    wr(g,G_TX_WORD,8);wr(g,G_RX_WORD,8);wr(g,G_TX_STOP,0);
    wr(g,G_TX_PARITY,0);wr(g,G_RX_PARITY,0);wr(g,G_TX_CFG,0);wr(g,G_RX_CFG,0);
    wr(g,G_LOOPBACK,0);wr(g,G_RX_STALE,160);wr(g,F_TX_WM,2);
    wr(g,G_RX_WM,g->rx_depth/2);wr(g,G_RX_RFR_WM,g->rx_depth-2);
    rfr(g,false);barrier(g);g->state=B5Q_BT_FIFO_STOPPED;return 0;
}
int b5q_bt_fifo_set_rate(struct b5q_bt_fifo *g,uint32_t baud,uint32_t hz,unsigned sample) {
    if(g->state!=B5Q_BT_FIFO_STOPPED || !baud || !hz || (sample!=16 && sample!=32))return -EINVAL;
    uint64_t target=(uint64_t)baud*sample,div=((uint64_t)hz+target/2)/target;
    if(!div || div>4095)return -ERANGE;
    uint64_t actual=hz/div,diff=actual>target?actual-target:target-actual;
    if(diff*100>target)return -ERANGE;
    wr(g,G_M_CLK,((uint32_t)div<<4)|1);wr(g,G_S_CLK,((uint32_t)div<<4)|1);wr(g,G_CLK_SEL,0);
    barrier(g);g->baud=baud;g->source_hz=hz;return 0;
}
int b5q_bt_fifo_start(struct b5q_bt_fifo *g) {
    if(g->state!=B5Q_BT_FIFO_STOPPED || !g->baud || g->rx_count)return -EINVAL;
    wr(g,G_M_CLEAR,UINT32_MAX);wr(g,G_S_CLEAR,UINT32_MAX);
    wr(g,G_M_IRQ_EN,F_M_IRQS);wr(g,G_S_IRQ_EN,F_S_IRQS);
    g->state=B5Q_BT_FIFO_RUN;
    wr(g,G_S_CMD,(1u<<27)|(1u<<7));rfr(g,true);
    wr(g,G_IRQ_EN,F_SE_CPU_IRQS);barrier(g); // CPU M/S interrupts only, no DMA IRQs.
    __atomic_store_n(&g->irq_pending,false,__ATOMIC_RELEASE);fifoMask(g,false);return 0;
}
static bool discard_startup_rx(struct b5q_bt_fifo *g) {
    unsigned words=rd(g,F_RX_STATUS)&0x1ffffffu;
    if(words>g->rx_depth){fail(g,-EOVERFLOW);return false;}
    for(unsigned i=0;i<words;i++)(void)rd(g,F_RX);
    g->stats.startup_rx_discarded+=words*4u;
    return true;
}
int b5q_bt_fifo_startup(struct b5q_bt_fifo *g) {
    if(g->state!=B5Q_BT_FIFO_STOPPED)return -EINVAL;
    if(!discard_startup_rx(g))return g->error;
    int e=b5q_bt_fifo_start(g);
    if(!e)g->startup_deadline=now(g)+50000000ULL;
    return e;
}
void b5q_bt_fifo_irq(struct b5q_bt_fifo *g) {
    fifoMask(g,true);__atomic_store_n(&g->irq_pending,true,__ATOMIC_RELEASE);
    g->ops.wake_worker(g->ops.context);
}
static void deliver(struct b5q_bt_fifo *g) {
    for(unsigned budget=0;g->rx_count && budget<2;budget++) {
        unsigned length=(unsigned)sizeof(g->rx)-g->rx_head;
        if(length>g->rx_count)length=g->rx_count;
        size_t n=g->ops.receive(g->ops.context,g->rx+g->rx_head,length);
        if(n>length){fail(g,-EOVERFLOW);return;}
        g->rx_head=(g->rx_head+(unsigned)n)%(unsigned)sizeof(g->rx);g->rx_count-=(unsigned)n;
        if(n<length){g->stats.rx_backpressure++;break;}
    }
}
static void receive_fifo(struct b5q_bt_fifo *g) {
    uint32_t status=rd(g,F_RX_STATUS);unsigned words=status&0x1ffffffu;
    if(words>g->rx_depth){fail(g,-EOVERFLOW);return;}
    unsigned valid=(status>>28)&7u;
    if(valid>4){fail(g,-EPROTO);return;}
    if(!words)return;
    unsigned length=4*(words-1)+((status&(1u<<31)) && valid?valid:4);
    if(sizeof(g->rx)-g->rx_count<length){rfr(g,false);g->stats.rx_backpressure++;return;}
    for(unsigned i=0;i<words;i++) {
        uint32_t w=rd(g,F_RX);unsigned take=i+1==words?length-4*i:4;
        for(unsigned j=0;j<take;j++) {
            unsigned at=(g->rx_head+g->rx_count)%(unsigned)sizeof(g->rx);
            g->rx[at]=(uint8_t)(w>>(j*8));g->rx_count++;
        }
    }
    g->stats.rx_words+=words;g->stats.rx_bytes+=length;
}
static void transmit_fifo(struct b5q_bt_fifo *g) {
    unsigned used=rd(g,G_TX_FIFO_STATUS)&0xfffffffu;
    if(used>g->tx_depth){fail(g,-EOVERFLOW);return;}
    unsigned room=g->tx_depth-used;
    while(g->tx_offset<g->tx_length && room--) {
        unsigned n=g->tx_length-g->tx_offset;if(n>4)n=4;
        uint32_t w=0;for(unsigned i=0;i<n;i++)w|=(uint32_t)g->tx[g->tx_offset++]<<(8*i);
        wr(g,F_TX,w);barrier(g);g->stats.tx_words++;
    }
    /* A level watermark can relatch before filling: clear again after writes. */
    wr(g,G_M_CLEAR,F_TX_WATER);
    wr(g,G_M_IRQ_EN,F_M_IRQS|(g->tx_offset<g->tx_length?F_TX_WATER:0));
}
bool b5q_bt_fifo_service(struct b5q_bt_fifo *g) {
    if(g->state==B5Q_BT_FIFO_OFF || g->state==B5Q_BT_FIFO_STOPPED || g->state==B5Q_BT_FIFO_FAILED)return false;
    if(__atomic_exchange_n(&g->irq_pending,false,__ATOMIC_ACQ_REL))g->stats.interrupts++;
    uint32_t mi=rd(g,G_M_IRQ),si=rd(g,G_S_IRQ);
    wr(g,G_M_CLEAR,mi);wr(g,G_S_CLEAR,si);
    const uint32_t line=si&(G_LINE_ERRORS&~F_FIFO_ERRORS);
    if(!(mi&F_M_ERRORS) && !(si&(G_CMD_ERRORS|F_FIFO_ERRORS)) && line &&
       now(g)<g->startup_deadline && !g->stats.startup_line_errors &&
       !g->tx_busy && !g->stats.tx_bytes && !g->stats.rx_bytes) {
        /* Samsung counts startup break/parity rather than killing UART.
         * Drop the damaged FIFO bytes; never deliver them as an HCI reply.
         * Repeated, late, overflow or in-command errors still fail closed. */
        g->fault_irq[0]=mi;g->fault_irq[1]=si;
        g->stats.startup_line_errors++;
        if(!discard_startup_rx(g))return false;
        si&=~G_LINE_ERRORS;
    }
    if((mi&F_M_ERRORS) || (si&(G_CMD_ERRORS|G_LINE_ERRORS|F_FIFO_ERRORS))) {
        g->fault_irq[0]=mi;g->fault_irq[1]=si;g->stats.line_errors++;fail(g,-EIO);return false;
    }
    deliver(g);if(g->state==B5Q_BT_FIFO_FAILED)return false;
    // Drain successive hardware batches, bounded by the software queue.
    for(unsigned batch=0;batch<sizeof(g->rx)/4;batch++){
        const uint64_t before=g->stats.rx_words;
        receive_fifo(g);if(g->state==B5Q_BT_FIFO_FAILED)return false;
        deliver(g);if(g->state==B5Q_BT_FIFO_FAILED)return false;
        if(!(rd(g,F_RX_STATUS)&0x1ffffffu)||g->stats.rx_words==before)break;
    }
    if(g->tx_busy && (mi&G_DONE)) {
        if(g->tx_offset!=g->tx_length){fail(g,-EIO);return false;}
        g->stats.tx_bytes+=g->tx_length;g->tx_busy=false;g->tx_length=g->tx_offset=0;
    }
    if(g->tx_busy)transmit_fifo(g);
    if(g->state==B5Q_BT_FIFO_FAILED)return false;
    if(g->state==B5Q_BT_FIFO_CANCEL || g->state==B5Q_BT_FIFO_ABORT) {
        if(!(rd(g,G_STATUS)&G_S_ACTIVE) && !g->rx_count) {
            g->state=B5Q_BT_FIFO_STOPPED;g->stop_deadline=g->retry_at=0;
            wr(g,G_IRQ_EN,0);barrier(g);fifoMask(g,true);return false;
        }
        if(now(g)>=g->stop_deadline) {
            g->stats.cancel_timeouts++;
            if(g->state==B5Q_BT_FIFO_CANCEL) {
                g->state=B5Q_BT_FIFO_ABORT;wr(g,G_S_CTRL,G_ABORT);g->stop_deadline=now(g)+G_STOP_TIMEOUT_NS;
            }else{fail(g,-ETIMEDOUT);return false;}
        }
    } else {
        bool room=sizeof(g->rx)-g->rx_count>=g->rx_depth*4;
        rfr(g,room);
        /* If the reader stalls, an unread level watermark must not repeatedly
         * interrupt the boot CPU. The timed worker retries and reenables it. */
        wr(g,G_S_IRQ_EN,room?F_S_IRQS:F_S_IRQS&~(F_RX_WATER|F_RX_LAST));
    }
    /* A short RX tail may have no watermark edge; a CTS-stalled TX may
     * lose its watermark while the shared IRQ is masked. Keep the owning
     * worker alive until both directions are empty, including during boot. */
    g->retry_at=(g->tx_busy || g->rx_count || (rd(g,F_RX_STATUS)&0x1ffffffu))?now(g)+1000000ULL:0;
    barrier(g);fifoMask(g,false);return false;
}
bool b5q_bt_fifo_drained(struct b5q_bt_fifo *g) {
    return !g->tx_busy && !(rd(g,G_STATUS)&G_M_ACTIVE) && !(rd(g,G_TX_FIFO_STATUS)&0xfffffffu);
}
size_t b5q_bt_fifo_write(struct b5q_bt_fifo *g,const uint8_t *p,size_t n) {
    if(g->state!=B5Q_BT_FIFO_RUN || !p || !n || !b5q_bt_fifo_drained(g))return 0;
    if(n>sizeof(g->tx))n=sizeof(g->tx);
    memcpy(g->tx,p,n);g->tx_length=(unsigned)n;g->tx_offset=0;g->tx_busy=true;
    wr(g,G_TX_LEN,(uint32_t)n);wr(g,G_M_CMD,1u<<27);transmit_fifo(g);g->retry_at=now(g)+1000000ULL;barrier(g);return n;
}
void b5q_bt_fifo_set_flow(struct b5q_bt_fifo *g,bool enabled) {
    g->flow=enabled;uint32_t cfg=rd(g,G_TX_CFG);
    wr(g,G_TX_CFG,enabled?cfg&~2u:cfg|2u);
    rfr(g,g->state==B5Q_BT_FIFO_RUN && sizeof(g->rx)-g->rx_count>=g->rx_depth*4);barrier(g);
}
int b5q_bt_fifo_quiesce(struct b5q_bt_fifo *g) {
    if(g->state==B5Q_BT_FIFO_STOPPED)return 0;
    if(g->state==B5Q_BT_FIFO_FAILED)return g->error;
    if(g->state!=B5Q_BT_FIFO_RUN)return -EINPROGRESS;
    if(!b5q_bt_fifo_drained(g) || g->rx_count)return -EBUSY;
    g->state=B5Q_BT_FIFO_CANCEL;rfr(g,false);g->stop_deadline=now(g)+G_STOP_TIMEOUT_NS;
    wr(g,G_S_CTRL,G_CANCEL);barrier(g);return -EINPROGRESS;
}
int b5q_bt_fifo_resume(struct b5q_bt_fifo *g) {return b5q_bt_fifo_start(g);}
uint64_t b5q_bt_fifo_deadline(const struct b5q_bt_fifo *g) {
    uint64_t at=g->stop_deadline?g->stop_deadline:UINT64_MAX;
    return g->retry_at && g->retry_at<at?g->retry_at:at;
}
