#!/usr/bin/env python3
"""Execute the locked original PCI ID/revision switch and MHI tables."""
import hashlib,json,re,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];L=R/'sources/UniXNU-sheng/drivers/Ath12kWifi/deps/linux/drivers/net/wireless/ath/ath11k'
pci=(L/'pci.c').read_text();core=(L/'core.h').read_text();mhi=(L/'mhi.c').read_text()
start=pci.index('\tswitch (pci_dev->device) {');end=pci.index('\n\tret = ath11k_pcic_init_msi_config',start)
switch=pci[start:end]
enum=core[core.index('enum ath11k_hw_rev {'):];enum=enum[:enum.index('};')+2]
definitions='\n'.join(re.findall(r'^#define (?:QCA6390_DEVICE_ID|QCN9074_DEVICE_ID|WCN6855_DEVICE_ID|TCSR_SOC_HW_SUB_VER)\s+[^\n]+',pci,re.M))
tables=mhi[mhi.index('static const struct mhi_channel_config ath11k_mhi_channels_qca6390'):mhi.index('static const struct mhi_channel_config ath11k_mhi_channels_qcn9074')]
harness=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define ATH11K_BDF_SEARCH_BUS_AND_BOARD 2
#define ATH11K_DBG_PCI 1
#define dev_err(...) ((void)0)
#define ath11k_dbg(...) ((void)0)
#define ath11k_err(...) ((void)0)
ENUM
DEFINITIONS
struct device {unsigned unused;};struct pci_dev {struct device dev;unsigned device;};
struct ath11k_base {struct {unsigned bdf_search;}id;enum ath11k_hw_rev hw_rev;};
static int ath11k_pci_ops_qca6390,ath11k_pci_ops_qcn9074;
static uint32_t major,minor,sub;static int failOps;
static int ath11k_pcic_register_pci_ops(struct ath11k_base *ab,void *ops){(void)ab;assert(ops);return failOps;}
static void ath11k_pci_read_hw_version(struct ath11k_base *ab,uint32_t *a,uint32_t *b){(void)ab;*a=major;*b=minor;}
static uint32_t ath11k_pcic_read32(struct ath11k_base *ab,uint32_t reg){(void)ab;assert(reg==TCSR_SOC_HW_SUB_VER);return sub;}
static int probe(struct pci_dev *pdev,struct ath11k_base *ab) {
 struct pci_dev *pci_dev=pdev;uint32_t soc_hw_version_major,soc_hw_version_minor,sub_version;int ret=0;
 SWITCH
 return 0;
err_pci_free_region:return ret;
}
enum {DMA_TO_DEVICE=1,DMA_FROM_DEVICE=2,MHI_DB_BRST_DISABLE=0,MHI_ER_CTRL=0};
struct mhi_channel_config {unsigned num;const char *name;unsigned num_elements,event_ring,dir,ee_mask,pollcfg,doorbell;bool lpm_notify,offload_channel,doorbell_mode_switch;};
struct mhi_event_config {unsigned num_elements,irq_moderation_ms,irq,mode,data_type,priority;bool hardware_event,client_managed,offload_channel;};
struct mhi_controller_config {unsigned max_channels,timeout_ms;bool use_bounce_buf;unsigned buf_len,num_channels;const struct mhi_channel_config *ch_cfg;unsigned num_events;struct mhi_event_config *event_cfg;};
TABLES
int main(void) {
 struct pci_dev device={.device=0x1103};struct ath11k_base ab={0};
 for(unsigned i=0;i<4;i++){major=2;minor=(unsigned[]){0,1,0x10,0x11}[i];sub=0;assert(!probe(&device,&ab));assert(ab.hw_rev==(i<2?ATH11K_HW_WCN6855_HW20:ATH11K_HW_WCN6855_HW21));assert(ab.id.bdf_search==2);}
 for(unsigned i=0;i<4;i++){sub=(uint32_t[]){0x1019a0e1,0x1019b0e1,0x1019c0e1,0x1019d0e1}[i];assert(!probe(&device,&ab)&&ab.hw_rev==ATH11K_HW_QCA2066_HW21);}
 sub=0x001e60e1;assert(!probe(&device,&ab)&&ab.hw_rev==ATH11K_HW_QCA6698AQ_HW21);
 major=1;assert(probe(&device,&ab)==-EOPNOTSUPP);major=2;minor=0x12;assert(probe(&device,&ab)==-EOPNOTSUPP);
 minor=0;failOps=-EIO;assert(probe(&device,&ab)==-EIO);failOps=0;
 device.device=0x1107;assert(probe(&device,&ab)==-EOPNOTSUPP);
 const struct mhi_controller_config *c=&ath11k_mhi_config_qca6390;
 assert(c->max_channels==128&&c->timeout_ms==2000&&c->num_channels==2&&c->num_events==2&&!c->use_bounce_buf&&c->buf_len==8192);
 for(unsigned i=0;i<2;i++){const struct mhi_channel_config *ch=&c->ch_cfg[i];assert(ch->num==20+i&&!strcmp(ch->name,"IPCR")&&ch->num_elements==64&&ch->event_ring==1&&ch->ee_mask==4&&ch->dir==(i?DMA_FROM_DEVICE:DMA_TO_DEVICE));}
 assert(c->event_cfg[0].irq==1&&c->event_cfg[0].num_elements==32&&c->event_cfg[1].irq==2&&c->event_cfg[1].num_elements==256);
 puts("PASS original ath11k17cb:1103 revision/ops/bdf selection,otherchips/versions/errors rejected; native QCA6490 MHI IPCR20/21+event rings");
}
'''.replace('ENUM',enum).replace('DEFINITIONS',definitions).replace('SWITCH',switch).replace('TABLES',tables)
with tempfile.TemporaryDirectory(prefix='b5q-ath11k-qca6490-')as td:
    td=Path(td);src=td/'test.c';src.write_text(harness)
    subprocess.run(['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
report=dict(passed=True,hardware_verified=False,source_revision='458c6079fc1d41d564c37679c8ace02cd83ee817',
    source_sha256={n:hashlib.sha256((L/n).read_bytes()).hexdigest()for n in ('pci.c','core.h','mhi.c')},
    scope='Original unmodified switch and config declarations; hardware dependencies simulated; ABI covered by target compile')
(R/'artifacts/b5q-p3-work/qca6490-host.json').write_text(json.dumps(report,indent=2)+'\n')
