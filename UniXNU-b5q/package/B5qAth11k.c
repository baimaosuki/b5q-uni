/* SPDX-License-Identifier: GPL-2.0-only */
/* ath11k lifecycle over the same native cfg80211/mac80211/wpa boundary used
 * by sheng. This file selects the QCA6490 core, not another station stack. */
#include "lx_pci.h"
#include "lx_plat.h"
#include <net/mac80211.h>
#include "core.h"
#include "pci.h"
#include "pcic.h"
#include "dp_rx.h"
#include "nw_mainline.h"
#include "nw_cfg80211_control.h"
#include "nw_qrtr.h"
#include "nw_board.h"
#include "nw_wifi.h"
#include "nw_control_endpoint.h"
#include <linux/mhi.h>
#include "B5qAth11kRddm.h"
int b5q_ath11k_pci_init(void);
void b5q_ath11k_pci_exit(void);
int mhi_init_hook(void);
int lx_init_cfg80211_init(void),lx_init_ieee80211_init(void);
void lx_exit_cfg80211_exit(void),lx_exit_ieee80211_exit(void);
extern const struct bus_type mhi_bus_type;
extern unsigned int ath11k_debug_mask;
struct nw_wifi_stats nw_wifi_stats;
static struct ieee80211_hw *hardware;
static bool cfg_started,mac_started,mhi_started,qrtr_started,pci_started;
static int firmware_error;
static struct mhi_controller *active_mhi;
extern int lx_irq_disabled(unsigned int);

#define B5Q_TX_HISTORY_COUNT 32u
#define B5Q_WMI_RX_HISTORY_COUNT 32u
#define B5Q_WMI_RX_DUMP_COUNT 16u
#define B5Q_TX_WMI 1u
#define B5Q_TX_HTT 2u
struct b5q_tx_history_entry {
    u64 time_ms;
    u32 sequence,id,length,kind;
    volatile u32 committed;
};
static struct b5q_tx_history_entry tx_history[B5Q_TX_HISTORY_COUNT];
static struct b5q_tx_history_entry wmi_rx_history[B5Q_WMI_RX_HISTORY_COUNT];
static volatile u32 tx_sequence,wmi_rx_sequence;
static volatile u32 startup_sequence,timeout_dumps;

void b5q_ath11k_trace_tx(u32 kind,u32 id,size_t length) {
    const u32 sequence=__atomic_add_fetch(&tx_sequence,1u,__ATOMIC_RELAXED);
    struct b5q_tx_history_entry *entry=&tx_history[(sequence-1u)&(B5Q_TX_HISTORY_COUNT-1u)];
    __atomic_store_n(&entry->committed,0u,__ATOMIC_RELAXED);
    entry->time_ms=lx_now_ms();entry->sequence=sequence;entry->id=id;
    entry->length=length>UINT32_MAX?UINT32_MAX:(u32)length;entry->kind=kind;
    __atomic_store_n(&entry->committed,sequence,__ATOMIC_RELEASE);
}
void b5q_ath11k_trace_startup(u32 kind,u32 id,size_t length,int credits) {
    const u32 sequence=__atomic_add_fetch(&startup_sequence,1u,__ATOMIC_RELAXED);
    const char *name=kind==1?"WMI-TX":kind==2?"HTC-TX":kind==3?"HTC-RX":kind==4?"WMI-RX":"unknown";
    if(sequence<=64)lx_log(6,"B5qWifi: startup-io seq=%u kind=%s id=%u len=%u credits=%d",
        sequence,name,id,length>UINT32_MAX?UINT32_MAX:(u32)length,credits);
    if(kind==4u){
        const u32 rx_sequence=__atomic_add_fetch(&wmi_rx_sequence,1u,__ATOMIC_RELAXED);
        struct b5q_tx_history_entry *entry=&wmi_rx_history[(rx_sequence-1u)&(B5Q_WMI_RX_HISTORY_COUNT-1u)];
        __atomic_store_n(&entry->committed,0u,__ATOMIC_RELAXED);
        entry->time_ms=lx_now_ms();entry->sequence=rx_sequence;entry->id=id;
        entry->length=length>UINT32_MAX?UINT32_MAX:(u32)length;entry->kind=kind;
        __atomic_store_n(&entry->committed,rx_sequence,__ATOMIC_RELEASE);
    }
}
static void b5q_ath11k_trace_reset(void) {
    memset(tx_history,0,sizeof(tx_history));
    memset(wmi_rx_history,0,sizeof(wmi_rx_history));
    __atomic_store_n(&tx_sequence,0u,__ATOMIC_RELEASE);
    __atomic_store_n(&wmi_rx_sequence,0u,__ATOMIC_RELEASE);
    __atomic_store_n(&startup_sequence,0u,__ATOMIC_RELEASE);
    __atomic_store_n(&timeout_dumps,0u,__ATOMIC_RELEASE);
}
static void b5q_ath11k_trace_dump(void) {
    const u32 end=__atomic_load_n(&tx_sequence,__ATOMIC_ACQUIRE);
    const u32 first=end>B5Q_TX_HISTORY_COUNT?end-B5Q_TX_HISTORY_COUNT+1u:1u;
    for(u32 sequence=first;sequence<=end;sequence++) {
        const struct b5q_tx_history_entry *entry=&tx_history[(sequence-1u)&(B5Q_TX_HISTORY_COUNT-1u)];
        const u32 committed=__atomic_load_n(&entry->committed,__ATOMIC_ACQUIRE);
        if(committed!=sequence) {
            lx_log(3,"B5qWifi: tx-history seq=%u unavailable committed=%u",sequence,committed);
            continue;
        }
        lx_log(3,"B5qWifi: tx-history seq=%u kind=%s id=%u len=%u at-ms=%llu",
            sequence,entry->kind==B5Q_TX_WMI?"WMI":entry->kind==B5Q_TX_HTT?"HTT":"unknown",
            entry->id,entry->length,entry->time_ms);
    }
    const u32 rx_end=__atomic_load_n(&wmi_rx_sequence,__ATOMIC_ACQUIRE);
    const u32 rx_first=rx_end>B5Q_WMI_RX_DUMP_COUNT?rx_end-B5Q_WMI_RX_DUMP_COUNT+1u:1u;
    for(u32 sequence=rx_first;sequence<=rx_end;sequence++) {
        const struct b5q_tx_history_entry *entry=&wmi_rx_history[(sequence-1u)&(B5Q_WMI_RX_HISTORY_COUNT-1u)];
        const u32 committed=__atomic_load_n(&entry->committed,__ATOMIC_ACQUIRE);
        if(committed!=sequence) {
            lx_log(3,"B5qWifi: wmi-rx-history seq=%u unavailable committed=%u",sequence,committed);
            continue;
        }
        lx_log(3,"B5qWifi: wmi-rx-history seq=%u id=%u len=%u at-ms=%llu",
            sequence,entry->id,entry->length,entry->time_ms);
    }
}
static u32 b5q_mhi_read(struct mhi_controller *controller,void __iomem *base,u32 offset) {
    u32 value=UINT32_MAX;
    if(!controller || !base || !controller->read_reg ||
       controller->read_reg(controller,(u8 __iomem *)base+offset,&value))return UINT32_MAX;
    return value;
}
static u32 b5q_ring_read(volatile u32 *value) {
    return value?*value:UINT32_MAX;
}
#define B5Q_RDDM_MAX_SEGMENTS 64u
struct b5q_rddm_read_ctx { struct mhi_controller *controller; };
struct b5q_rddm_emit_ctx { u32 index; };
static u32 b5q_rddm_read_status(void *context,u32 offset) {
    struct b5q_rddm_read_ctx *ctx=context;
    return ctx?b5q_mhi_read(ctx->controller,ctx->controller?ctx->controller->bhie:NULL,offset):UINT32_MAX;
}
static void b5q_rddm_delay(void *context,unsigned ms) {
    (void)context;
    // A bounded busy delay keeps this callback context free of sleep locks
    // and wait_event_timeout, which would deadlock inside MHI's state change.
    lx_delay_ms(ms);
}
static void b5q_rddm_emit_hit(void *context,const struct B5qRddmHit *hit) {
    struct b5q_rddm_emit_ctx *ctx=context;
    if(!ctx||!hit)return;
    lx_log(3,"B5qWifi: rddm-hit idx=%u seg=%u off=%06x text='%s'",ctx->index++,hit->seg,hit->off,hit->text);
}
static void b5q_rddm_dump(struct mhi_controller *controller) {
    if(!controller||!controller->bhie||!controller->rddm_image||!controller->rddm_image->mhi_buf||
       controller->rddm_image->entries<=1u)return;
    const u32 entries=controller->rddm_image->entries;
    u64 total=0;
    for(u32 i=0;i+1u<entries;i++)total+=controller->rddm_image->mhi_buf[i].len;
    const u32 initial=b5q_rddm_read_status(&(struct b5q_rddm_read_ctx){controller},B5Q_RDDM_RXVECSTATUS_OFFS);
    lx_log(3,"B5qWifi: rddm-initial rxvec=%08x entries=%u bytes=%llu",initial,entries,total);
    const struct B5qRddmWait wait=b5q_rddm_wait_rxvec(b5q_rddm_read_status,b5q_rddm_delay,
        &(struct b5q_rddm_read_ctx){controller},B5Q_RDDM_WAIT_MAX_MS,B5Q_RDDM_WAIT_STEP_MS);
    lx_log(3,"B5qWifi: rddm-status rxvec=%08x state=%u waited-ms=%u entries=%u",
        wait.rxvec,wait.state,wait.waited_ms,entries);
    struct B5qRddmSegment segments[B5Q_RDDM_MAX_SEGMENTS];
    u32 segment_count=0,nonzero_segments=0;
    u64 nonzero_bytes=0;
    for(u32 i=0;i+1u<entries;i++) {
        struct mhi_buf *buffer=&controller->rddm_image->mhi_buf[i];
        if(!buffer->buf||!buffer->len)continue;
        if(lx_plat&&lx_plat->dma_sync)
            lx_plat->dma_sync(buffer->dma_addr,buffer->len,2 /* DMA_FROM_DEVICE */);
        const u32 length=buffer->len>UINT32_MAX?UINT32_MAX:(u32)buffer->len;
        size_t nonzero=0;
        b5q_rddm_segment_nonzero(buffer->buf,buffer->len,&nonzero);
        if(nonzero){
            nonzero_segments++;nonzero_bytes+=nonzero;
            char hex[49];unsigned used=0;
            for(u32 j=0;j<16u&&j<length&&used+3u<sizeof(hex);j++){
                static const char digits[]="0123456789abcdef";
                const u8 value=((const u8 *)buffer->buf)[j];
                hex[used++]=digits[value>>4];hex[used++]=digits[value&15u];hex[used++]=' ';
            }
            hex[used?used-1u:0u]=0;
            lx_log(3,"B5qWifi: rddm-seg seg=%u len=%u nonzero=%u elf=%u first=%s",i,length,
                nonzero>UINT32_MAX?UINT32_MAX:(u32)nonzero,b5q_rddm_is_elf(buffer->buf,length),hex);
        }
        if(segment_count<B5Q_RDDM_MAX_SEGMENTS)segments[segment_count++]=(struct B5qRddmSegment){buffer->buf,length};
    }
    if(entries-1u>B5Q_RDDM_MAX_SEGMENTS)
        lx_log(3,"B5qWifi: rddm-segments truncated entries=%u scanned=%u",entries-1u,segment_count);
    lx_log(3,"B5qWifi: rddm-summary segments=%u nonzero-segments=%u nonzero-bytes=%llu scanned=%u",
        entries-1u,nonzero_segments,nonzero_bytes,segment_count);
    if(segment_count){
        struct B5qRddmScan scan;
        struct b5q_rddm_emit_ctx emit={0};
        b5q_rddm_scan_init(&scan,b5q_rddm_emit_hit,&emit);
        b5q_rddm_scan(&scan,segments,segment_count);
        lx_log(3,"B5qWifi: rddm-hits high=%u low=%u dropped=%u",scan.high,scan.low,scan.dropped);
    }
}
#define B5Q_WCN6855_ASSERT_PC_ADDR 0x016cc148u
#define B5Q_WCN6855_ASSERT_MSG_ADDR 0x016cc150u
#define B5Q_WCN6855_ASSERT_FMT_ADDR 0x016cc94cu
#define B5Q_WCN6855_ASSERT_LINE_ADDR 0x016cc950u

static void b5q_sram_assert_dump(struct ath11k_base *ab,u32 mhi_status) {
    if(mhi_status==UINT32_MAX||!ab||!ab->mem||!ab->pci.ops||!ab->pci.ops->window_read32)return;
    const u32 pc=ab->pci.ops->window_read32(ab,B5Q_WCN6855_ASSERT_PC_ADDR);
    const u32 fmt=ab->pci.ops->window_read32(ab,B5Q_WCN6855_ASSERT_FMT_ADDR);
    const u32 line=ab->pci.ops->window_read32(ab,B5Q_WCN6855_ASSERT_LINE_ADDR);
    u32 words[16];char msg[65]={0};
    for(unsigned i=0;i<16;i++)words[i]=ab->pci.ops->window_read32(ab,B5Q_WCN6855_ASSERT_MSG_ADDR+4u*i);
    for(unsigned i=0;i<64;i++){
        const unsigned char c=(words[i/4]>>((i%4)*8))&0xffu;
        if(!c)break;
        msg[i]=c>=0x20&&c<=0x7e?(char)c:'.';
    }
    lx_log(3,"B5qWifi: sram-assert pc=%08x line=%u fmt=%08x raw=%08x:%08x:%08x:%08x",
        pc,line,fmt,words[0],words[1],words[2],words[3]);
    lx_log(3,"B5qWifi: sram-assert-msg='%s'",msg);
}
static void b5q_ce_dump(struct ath11k_base *ab,unsigned ce) {
    if(!ab||ce>=ab->hw_params.ce_count)return;
    struct ath11k_ce_pipe *pipe=&ab->ce.ce_pipe[ce];
    const unsigned irq=ab->irq_num[ATH11K_PCI_IRQ_CE0_OFFSET+ce];
    if(pipe->src_ring){
        struct ath11k_ce_ring *ring=pipe->src_ring;
        struct hal_srng *hal=&ab->hal.srng_list[ring->hal_ring_id];
        lx_log(3,"B5qWifi: CE%u src sw=%u write=%u hp=%u reap=%u tp-shadow=%u tp-cached=%u hp-hw=%u irq=%u disabled=%d",
            ce,ring->sw_index,ring->write_index,hal->u.src_ring.hp,hal->u.src_ring.reap_hp,
            b5q_ring_read(hal->u.src_ring.tp_addr),hal->u.src_ring.cached_tp,
            b5q_ring_read(hal->u.src_ring.hp_addr),irq,lx_irq_disabled(irq));
    }
    if(pipe->dest_ring){
        struct ath11k_ce_ring *ring=pipe->dest_ring;
        struct hal_srng *hal=&ab->hal.srng_list[ring->hal_ring_id];
        lx_log(3,"B5qWifi: CE%u dest sw=%u write=%u tp=%u hp-shadow=%u hp-cached=%u tp-hw=%u irq=%u disabled=%d",
            ce,ring->sw_index,ring->write_index,hal->u.dst_ring.tp,b5q_ring_read(hal->u.dst_ring.hp_addr),
            hal->u.dst_ring.cached_hp,b5q_ring_read(hal->u.dst_ring.tp_addr),irq,lx_irq_disabled(irq));
    }
}
static void b5q_ath11k_dump_state(struct mhi_controller *controller,const char *event,int reason) {
    const u32 status=b5q_mhi_read(controller,controller?controller->regs:NULL,0x48);
    const u32 exec=b5q_mhi_read(controller,controller?controller->bhi:NULL,0x28);
    const u32 code=b5q_mhi_read(controller,controller?controller->bhi:NULL,0x30);
    const u32 dbg1=b5q_mhi_read(controller,controller?controller->bhi:NULL,0x34);
    const u32 dbg2=b5q_mhi_read(controller,controller?controller->bhi:NULL,0x38);
    const u32 dbg3=b5q_mhi_read(controller,controller?controller->bhi:NULL,0x3c);
    lx_log(3,"B5qWifi: diagnostic event=%s reason=%d MHI_STATUS=%08x MHI_EXEC_ENV=%08x state=%u ee=%u",
        event,reason,status,exec,controller?(u32)controller->dev_state:UINT32_MAX,
        controller?(u32)controller->ee:UINT32_MAX);
    lx_log(3,"B5qWifi: diagnostic BHI_ERRCODE=%08x BHI_ERRDBG1=%08x BHI_ERRDBG2=%08x BHI_ERRDBG3=%08x",
        code,dbg1,dbg2,dbg3);
    b5q_ath11k_trace_dump();
    struct ath11k_base *ab=controller&&controller->cntrl_dev?dev_get_drvdata(controller->cntrl_dev):NULL;
    b5q_ce_dump(ab,2);b5q_ce_dump(ab,3);
    if(exec==MHI_EE_RDDM||reason==MHI_CB_EE_RDDM){
        b5q_rddm_dump(controller);
        lx_log(3,"B5qWifi: sram-assert skipped/expected-zero in RDDM");
    } else {
        b5q_sram_assert_dump(ab,status);
    }
}

void nw_wifi_hw_ready(struct ieee80211_hw *hw){hardware=hw;}
int mhi_init_mmio(struct mhi_controller *);
void nw_mhi_pre_load(struct mhi_controller *controller) {
    // Preserve the shared SM8550 boot sequence: publish real channel/event
    // contexts before the endpoint's firmware transfer doorbell.
    active_mhi=controller;lx_delay_ms(200);
    int error=mhi_init_mmio(controller);
    if(error){firmware_error=error;nw_wifi_stats.last_err=error;}
    lx_log(error?3:6,"B5qWifi: MHI contexts before image result=%d",error);
}
void b5q_ath11k_mhi_failed(struct mhi_controller *controller,int reason) {
    if(firmware_error)return;
    firmware_error=-EIO;nw_wifi_stats.last_err=firmware_error;
    b5q_ath11k_dump_state(controller,"MHI-fatal",reason);
    struct ath11k_base *ab=controller&&controller->cntrl_dev?dev_get_drvdata(controller->cntrl_dev):NULL;
    if(ab)set_bit(ATH11K_FLAG_CRASH_FLUSH,&ab->dev_flags);
    lx_log(3,"B5qWifi: firmware-failed reason=%d; DMA retained until controller reset",reason);
}
void b5q_ath11k_wmi_timeout(u32 cmd_id) {
    if(__atomic_fetch_add(&timeout_dumps,1u,__ATOMIC_RELAXED)<4u)
        b5q_ath11k_dump_state(active_mhi,"WMI-timeout",(int)cmd_id);
}
void nw_wifi_set_platform(const struct lx_platform *platform){lx_plat=platform;}
void nw_wifi_irq_mode(int delivered){lx_irq_polling(!delivered);}
void nw_wifi_irq_pending(u32 vectors) {
    if(!nw_board)return;
    while(vectors){unsigned i=__builtin_ctz(vectors);vectors&=vectors-1;lx_irq_raise(nw_board->irq_base+i);}
}
void nw_wifi_poll(void){nw_mainline_poll();nw_wifi_control_poll();}
extern int b5q_wifi_requests_pending(void);
unsigned nw_wifi_wait_ms(unsigned maximum) {
    return b5q_wifi_requests_pending()||nw_mainline_pending()||nw_wifi_control_pending()?0:lx_next_wait_ms(maximum);
}
int nw_wifi_start(const struct lx_platform *platform,const struct nw_board *board) {
    if(!platform || !board || board->device_id!=0x1103 || !board->bar || board->bar_len<0x200000 ||
       !board->cfg_read || !board->cfg_write || !board->msi_target ||
       !platform->dma_alloc || !platform->dma_free || !platform->dma_map || !platform->dma_sync ||
       !platform->fw_get || !platform->now_ms || !platform->sleep_ms || !platform->poll ||
       !platform->alloc || !platform->free || !platform->log)return -EINVAL;
    if(pci_started)return -EBUSY;
    lx_plat=platform;nw_board=board;firmware_error=0;active_mhi=NULL;ath11k_debug_mask=0;b5q_ath11k_trace_reset();
    // Native mac80211 owns Ethernet encapsulation and SME/authentication.
    // Keep the original ath11k default frame mode; no retired nw_sta path.
    nw_wifi_buffer_pool_configure(1024*1024);lx_root_init();nw_qrtr_init();
    int error=nw_mainline_init();if(error)goto fail;
    error=lx_init_cfg80211_init();if(error)goto fail;cfg_started=true;
    error=lx_init_ieee80211_init();if(error)goto fail;mac_started=true;
    error=mhi_init_hook();if(error)goto fail;mhi_started=true;
    error=nw_qrtr_mhi_register();if(error)goto fail;qrtr_started=true;
    nw_wifi_stats.stage=1;
    error=b5q_ath11k_pci_init();if(error)goto fail;
    pci_started=true;nw_wifi_stats.stage=2;return 0;
fail:
    nw_wifi_stats.last_err=error;nw_wifi_stop();lx_log(3,"B5qWifi: ath11k startup error=%d",error);return error;
}
void nw_wifi_link_state(char *text,int size) {
    if(size<=0)return;text[0]=0;
    struct nw_wifi_status state;nw_wifi_status_get(&state);
    if(!hardware || state.state!=NW_STA_UP)return;
    struct ath11k *ar=hardware->priv;
    rcu_read_lock();
    struct ieee80211_sta *sta=ieee80211_find_sta_by_ifaddr(hardware,state.bssid,NULL);
    if(sta) {
        struct ath11k_sta *peer=ath11k_sta_to_arsta(sta);
        struct rate_info rate;int signal;
        spin_lock_bh(&ar->data_lock);rate=peer->txrate;signal=(s8)peer->rssi_comb;spin_unlock_bh(&ar->data_lock);
        nw_mainline_rate_update(state.bssid,cfg80211_calculate_bitrate(&rate));
        if(signal) {
            if(!test_bit(WMI_TLV_SERVICE_HW_DB2DBM_CONVERSION_SUPPORT,ar->ab->wmi_ab.svc_map))signal+=ATH11K_DEFAULT_NOISE_FLOOR;
            nw_mainline_signal_update(state.bssid,signal);
        }
    }
    rcu_read_unlock();nw_wifi_status_get(&state);
    snprintf(text,size,"ath11k freq=%u signal=%d tx=%u.%u Mbps",state.freq_mhz,state.signal_dbm,state.tx_rate_100kbps/10,state.tx_rate_100kbps%10);
}
void nw_wifi_tx_reasons(char *text,int size) {
    if(size<=0)return;
    if(!hardware){text[0]=0;return;}
    struct ath11k *ar=hardware->priv;
    snprintf(text,size,"ath11k tx-exception=%u tx-invalid-rbm=%u",
        ar->ab->soc_stats.tx_err.desc_na[0],ar->ab->soc_stats.invalid_rbm);
}
static unsigned b5q_step_phase,b5q_step_logs;
static u64 b5q_step_since,b5q_step_next_log;
extern volatile uint64_t nw_wifi_where[4],b5q_wifi_last_slow[4];
void b5q_wifi_step_observe(unsigned op,u64 age) {
    const u64 now=lx_now_ms();u64 next=__atomic_load_n(&b5q_step_next_log,__ATOMIC_RELAXED);
    if(now<next || !__atomic_compare_exchange_n(&b5q_step_next_log,&next,now+1000,0,__ATOMIC_RELAXED,__ATOMIC_RELAXED))return;
    if(__atomic_fetch_add(&b5q_step_logs,1,__ATOMIC_RELAXED)>=96)return;
    unsigned phase=__atomic_load_n(&b5q_step_phase,__ATOMIC_ACQUIRE);
    u64 since=__atomic_load_n(&b5q_step_since,__ATOMIC_RELAXED);
    lx_log(4,"B5qWifi: step-slow op=%u pending_ms=%llu phase=%u phase_ms=%llu pump=%llu fn_off=%llx depth=%llu slow_kind=%llu slow_off=%llx slow_ms=%llu slow_depth=%llu",
        op,age,phase,now>=since?now-since:0,nw_wifi_where[0],nw_wifi_where[1],nw_wifi_where[2],
        b5q_wifi_last_slow[0],b5q_wifi_last_slow[1],__atomic_load_n(&b5q_wifi_last_slow[2],__ATOMIC_ACQUIRE),b5q_wifi_last_slow[3]);
}
static void b5q_step_mark(unsigned phase) {
    const unsigned previous=__atomic_load_n(&b5q_step_phase,__ATOMIC_RELAXED);
    const u64 since=__atomic_load_n(&b5q_step_since,__ATOMIC_RELAXED),now=lx_now_ms();
    if(previous && now>=since && now-since>200)b5q_wifi_step_observe(0,now-since);
    __atomic_store_n(&b5q_step_since,now,__ATOMIC_RELAXED);
    __atomic_store_n(&b5q_step_phase,phase,__ATOMIC_RELEASE);
}
int nw_wifi_step(void) {
    if(firmware_error)return firmware_error;
    static u64 signal_at;
    for(unsigned i=0;i<4;i++)__atomic_store_n(&b5q_wifi_last_slow[i],0,__ATOMIC_RELAXED);
    const u64 began=lx_now_ms();
    b5q_step_mark(1);nw_wifi_control_poll();
    // Dispatch UI requests before potentially synchronous Linux work.
    b5q_step_mark(3);nw_mainline_run();
    b5q_step_mark(2);lx_pump();
    b5q_step_mark(4);
    if(hardware && lx_now_ms()>=signal_at){signal_at=lx_now_ms()+1000;char text[128];nw_wifi_link_state(text,sizeof(text));}
    const u64 elapsed=lx_now_ms()-began;
    if(elapsed>200)b5q_wifi_step_observe(0,elapsed);
    b5q_step_mark(0);
    return b5q_wifi_requests_pending()||nw_mainline_pending()||nw_wifi_control_pending()||lx_next_wait_ms(1000)==0;
}
void nw_wifi_stop(void) {
    nw_mainline_shutdown();nw_wifi_control_shutdown();
    if(pci_started){b5q_ath11k_pci_exit();pci_started=false;}
    if(qrtr_started){nw_qrtr_mhi_unregister();qrtr_started=false;}
    if(mhi_started){bus_unregister(&mhi_bus_type);mhi_started=false;}
    if(mac_started){lx_exit_ieee80211_exit();mac_started=false;}
    if(cfg_started){lx_exit_cfg80211_exit();cfg_started=false;}
    hardware=NULL;active_mhi=NULL;nw_wifi_buffer_pool_configure(0);
}

static int hexval(char c) { return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1; }
void nw_board_mac(u8 *a) {
  static u8 made[6]; static int have;
  const u8 *d; size_t n;
  if (!have && lx_plat->fw_get && !lx_plat->fw_get("wlan_mac.bin", &d, &n)) {
    size_t s = 0; for (size_t i = 0; i < n; i++) if (d[i] == '=') s = i + 1;
    u8 m[6]; size_t k = 0;
    for (size_t i = s; i < n && k < 12; i++) { int v = hexval((char)d[i]); if (v < 0) { if (k) break; continue; } m[k / 2] = (u8)(k & 1 ? m[k / 2] << 4 | v : v); k++; }
    if (k == 12 && is_valid_ether_addr(m)) { memcpy(made, m, 6); have = 1; lx_log(6, "wifi: address from wlan_mac.bin"); }
  }
  if (!have) {
    for (int i = 0; i < 6; i++) made[i] = (u8)(lx_random_u32() ^ lx_now_ms() >> (i * 3));
    made[0] = (made[0] & 0xfe) | 0x02; have = 1; lx_log(4, "wifi: the firmware and the board give no address: a made-up one is used");
  }
  memcpy(a, made, 6); }

