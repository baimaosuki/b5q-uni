/* SPDX-License-Identifier: GPL-2.0-only */
/* ath11k lifecycle over the same native cfg80211/mac80211/wpa boundary used
 * by sheng. This file selects the QCA6490 core, not another station stack. */
#include "lx_pci.h"
#include "lx_plat.h"
#include <net/mac80211.h>
#include "core.h"
#include "pci.h"
#include "dp_rx.h"
#include "nw_mainline.h"
#include "nw_cfg80211_control.h"
#include "nw_qrtr.h"
#include "nw_board.h"
#include "nw_wifi.h"
#include "nw_control_endpoint.h"
#include <linux/mhi.h>
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

void nw_wifi_hw_ready(struct ieee80211_hw *hw){hardware=hw;}
int mhi_init_mmio(struct mhi_controller *);
void nw_mhi_pre_load(struct mhi_controller *controller) {
    // Preserve the shared SM8550 boot sequence: publish real channel/event
    // contexts before the endpoint's firmware transfer doorbell.
    lx_delay_ms(200);
    int error=mhi_init_mmio(controller);
    if(error){firmware_error=error;nw_wifi_stats.last_err=error;}
    lx_log(error?3:6,"B5qWifi: MHI contexts before image result=%d",error);
}
void b5q_ath11k_mhi_failed(struct mhi_controller *controller,int reason) {
    if(firmware_error)return;
    firmware_error=-EIO;nw_wifi_stats.last_err=firmware_error;
    struct ath11k_base *ab=dev_get_drvdata(controller->cntrl_dev);
    if(ab)set_bit(ATH11K_FLAG_CRASH_FLUSH,&ab->dev_flags);
    lx_log(3,"B5qWifi: firmware-failed reason=%d; DMA retained until controller reset",reason);
}
void nw_wifi_set_platform(const struct lx_platform *platform){lx_plat=platform;}
void nw_wifi_irq_mode(int delivered){lx_irq_polling(!delivered);}
void nw_wifi_irq_pending(u32 vectors) {
    if(!nw_board)return;
    while(vectors){unsigned i=__builtin_ctz(vectors);vectors&=vectors-1;lx_irq_raise(nw_board->irq_base+i);}
}
void nw_wifi_poll(void){nw_mainline_poll();nw_wifi_control_poll();}
unsigned nw_wifi_wait_ms(unsigned maximum) {
    return nw_mainline_pending()||nw_wifi_control_pending()?0:lx_next_wait_ms(maximum);
}
int nw_wifi_start(const struct lx_platform *platform,const struct nw_board *board) {
    if(!platform || !board || board->device_id!=0x1103 || !board->bar || board->bar_len<0x200000 ||
       !board->cfg_read || !board->cfg_write || !board->msi_target ||
       !platform->dma_alloc || !platform->dma_free || !platform->dma_map || !platform->dma_sync ||
       !platform->fw_get || !platform->now_ms || !platform->sleep_ms || !platform->poll ||
       !platform->alloc || !platform->free || !platform->log)return -EINVAL;
    if(pci_started)return -EBUSY;
    lx_plat=platform;nw_board=board;firmware_error=0;ath11k_debug_mask=0;
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
int nw_wifi_step(void) {
    if(firmware_error)return firmware_error;
    static u64 signal_at;
    nw_wifi_control_poll();lx_pump();nw_mainline_run();
    if(hardware && lx_now_ms()>=signal_at){signal_at=lx_now_ms()+1000;char text[128];nw_wifi_link_state(text,sizeof(text));}
    return nw_mainline_pending()||nw_wifi_control_pending()||lx_next_wait_ms(1000)==0;
}
void nw_wifi_stop(void) {
    nw_mainline_shutdown();nw_wifi_control_shutdown();
    if(pci_started){b5q_ath11k_pci_exit();pci_started=false;}
    if(qrtr_started){nw_qrtr_mhi_unregister();qrtr_started=false;}
    if(mhi_started){bus_unregister(&mhi_bus_type);mhi_started=false;}
    if(mac_started){lx_exit_ieee80211_exit();mac_started=false;}
    if(cfg_started){lx_exit_cfg80211_exit();cfg_started=false;}
    hardware=NULL;nw_wifi_buffer_pool_configure(0);
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

