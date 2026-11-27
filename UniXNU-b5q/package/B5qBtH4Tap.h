/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Streaming H4 tap for the Bluetooth transport.
 *
 * qbt_core's trace_hci only reports discovery packets, so the board taps the
 * exact bytes: TX after qbt_transport_tx_take() and RX only for the prefix
 * qbt_transport_receive() actually accepted (backpressure must never re-feed
 * bytes into this parser). This header has no heap, no IOKit and no logging
 * dependency; B5qBluetooth.cpp supplies a line sink and the host tests include
 * this exact file under ASan/UBSan.
 */
#ifndef B5Q_BT_H4_TAP_H
#define B5Q_BT_H4_TAP_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define B5Q_BT_H4_PREFIX 64u
#define B5Q_BT_H4_LINE 512u
#define B5Q_BT_H4_QUOTA_TOTAL 1600u
#define B5Q_BT_H4_QUOTA_KEY 1100u
#define B5Q_BT_H4_QUOTA_NORMAL 496u
#define B5Q_BT_H4_ATT_LIMIT 160u
#define B5Q_BT_H4_CID_LIMIT 80u

struct B5qBtH4Sink {
    void (*line)(void *ctx, const char *text);
    uint64_t (*now_ms)(void *ctx);
};

struct B5qBtH4Stats {
    uint64_t tx_cmd, tx_acl, tx_sco, tx_iso;
    uint64_t rx_evt, rx_acl, rx_sco, rx_iso;
    uint64_t errs, smp, l2cap, desync, filtered, malformed;
    uint64_t evt13;
    uint32_t sco_commands, sco_events, role_changes, mode_changes, supervision_changes;
    uint64_t att, att_dropped, cid, cid_dropped;
    uint32_t logged, dropped;
};

struct B5qBtH4Quota {
    uint32_t total, key, normal, att, cid, dropped;
    uint8_t att_summary, cid_summary;
};

struct B5qBtH4Parser {
    uint8_t state, type, hdr_len, hdr_have;
    uint8_t hdr[4];
    uint8_t prefix[B5Q_BT_H4_PREFIX];
    uint32_t prefix_len, payload_left, total_len, payload_offset, desync;
};
struct B5qBtH4Handle {
    uint8_t active,is_le,mode,last_sig_code;
    uint16_t handle,mode_interval,sup_slots,last_tx_cid,last_rx_cid,last_psm;
    uint64_t conn_ms,last_tx_acl_ms,last_rx_acl_ms;
    uint32_t tx_acl,rx_acl;
};

struct B5qBtH4Tap {
    const struct B5qBtH4Sink *sink;
    void *ctx;
    int enabled;
    struct B5qBtH4Parser tx, rx;
    struct B5qBtH4Stats stats;
    struct B5qBtH4Quota quota;
    struct B5qBtH4Handle handles[8];
    uint32_t disconnLogged;
};

struct B5qBtH4View {
    uint8_t type;
    const uint8_t *prefix;
    uint32_t prefix_len, total_len, payload_offset, payload_len;
    int truncated;
};

struct B5qBtH4Text {
    char buf[B5Q_BT_H4_LINE];
    uint32_t len;
};

static inline void b5q_h4_text_putc(struct B5qBtH4Text *t, char c) {
    if (t->len + 1u < sizeof(t->buf)) { t->buf[t->len++] = c; t->buf[t->len] = 0; }
}
static inline void b5q_h4_text_puts(struct B5qBtH4Text *t, const char *s) {
    while (s && *s) b5q_h4_text_putc(t, *s++);
}
static inline void b5q_h4_text_u(struct B5qBtH4Text *t, uint64_t value) {
    char digits[21];uint32_t n = 0;
    if (!value) { b5q_h4_text_putc(t, '0'); return; }
    while (value && n < sizeof(digits)) { digits[n++] = (char)('0' + value % 10u); value /= 10u; }
    while (n) b5q_h4_text_putc(t, digits[--n]);
}
static inline void b5q_h4_text_hex(struct B5qBtH4Text *t, uint32_t value, unsigned digits) {
    static const char hex[] = "0123456789abcdef";
    b5q_h4_text_puts(t, "0x");
    for (unsigned i = digits; i; i--) b5q_h4_text_putc(t, hex[(value >> ((i - 1u) * 4u)) & 15u]);
}
static inline void b5q_h4_text_bytes(struct B5qBtH4Text *t, const uint8_t *data,
                                     uint32_t available, uint32_t maximum) {
    static const char hex[] = "0123456789abcdef";
    const uint32_t n = available < maximum ? available : maximum;
    for (uint32_t i = 0; i < n; i++) {
        b5q_h4_text_putc(t, hex[data[i] >> 4]);b5q_h4_text_putc(t, hex[data[i] & 15u]);
    }
}
static inline void b5q_h4_text_mac(struct B5qBtH4Text *t, const struct B5qBtH4View *v,
                                   uint32_t offset) {
    static const char hex[] = "0123456789abcdef";
    for (uint32_t i = 0; i < 6u; i++) {
        if (i) b5q_h4_text_putc(t, ':');
        if (offset + i < v->prefix_len) {
            const uint8_t value = v->prefix[offset + i];
            b5q_h4_text_putc(t, hex[value >> 4]);b5q_h4_text_putc(t, hex[value & 15u]);
        } else {
            b5q_h4_text_putc(t, '?');b5q_h4_text_putc(t, '?');
        }
    }
}

static inline uint32_t b5q_h4_get8(const struct B5qBtH4View *v, uint32_t offset) {
    return offset < v->prefix_len ? v->prefix[offset] : 0u;
}
static inline uint32_t b5q_h4_get16(const struct B5qBtH4View *v, uint32_t offset) {
    return b5q_h4_get8(v, offset) | (b5q_h4_get8(v, offset + 1u) << 8);
}
static inline int b5q_h4_scan_opcode(uint32_t opcode) {
    static const uint16_t scan[] = {0x0401u, 0x0402u, 0x200bu, 0x200cu, 0x2041u, 0x2042u};
    for (uint32_t i = 0; i < sizeof(scan) / sizeof(scan[0]); i++)
        if (scan[i] == opcode) return 1;
    return 0;
}
static inline int b5q_h4_key_slot(struct B5qBtH4Tap *tap) {
    if (!tap || tap->quota.total >= B5Q_BT_H4_QUOTA_TOTAL || tap->quota.key >= B5Q_BT_H4_QUOTA_KEY) {
        if (tap) { tap->quota.dropped++;tap->stats.dropped++; }
        return 0;
    }
    tap->quota.total++;tap->quota.key++;tap->stats.logged = tap->quota.total;
    return 1;
}
static inline int b5q_h4_summary_slot(struct B5qBtH4Tap *tap) {
    if (!tap || tap->quota.total >= B5Q_BT_H4_QUOTA_TOTAL) return 0;
    tap->quota.total++;tap->stats.logged = tap->quota.total;
    return 1;
}
static inline int b5q_h4_normal_slot(struct B5qBtH4Tap *tap) {
    if (!tap || tap->quota.total >= B5Q_BT_H4_QUOTA_TOTAL || tap->quota.normal >= B5Q_BT_H4_QUOTA_NORMAL) {
        if (tap) { tap->quota.dropped++;tap->stats.dropped++; }
        return 0;
    }
    tap->quota.total++;tap->quota.normal++;tap->stats.logged = tap->quota.total;
    return 1;
}
static inline void b5q_h4_send(struct B5qBtH4Tap *tap, struct B5qBtH4Text *text) {
    if (tap && tap->sink && tap->sink->line) tap->sink->line(tap->ctx, text->buf);
}
static inline uint64_t b5q_h4_now(struct B5qBtH4Tap *tap) {
    return tap && tap->sink && tap->sink->now_ms ? tap->sink->now_ms(tap->ctx) : 0u;
}
static inline void b5q_h4_header(struct B5qBtH4Tap *tap, struct B5qBtH4Text *text, int tx) {
    b5q_h4_text_puts(text, "B5qBluetooth: h4 ms=");
    b5q_h4_text_u(text, b5q_h4_now(tap));
    b5q_h4_text_puts(text, tx ? " dir=TX " : " dir=RX ");
}
static inline void b5q_h4_simple(struct B5qBtH4Tap *tap, int tx, const char *what,
                                 uint32_t value, unsigned digits) {
    struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
    b5q_h4_header(tap, &text, tx);b5q_h4_text_puts(&text, what);
    b5q_h4_text_hex(&text, value, digits);
    b5q_h4_send(tap, &text);
}

static inline struct B5qBtH4Handle *b5q_h4_handle(struct B5qBtH4Tap *tap,uint32_t handle,int create){
    handle&=0x0fffu;
    for(unsigned i=0;i<8;i++)if(tap->handles[i].active&&tap->handles[i].handle==handle)return &tap->handles[i];
    if(!create)return NULL;
    for(unsigned i=0;i<8;i++)if(!tap->handles[i].active){
        struct B5qBtH4Handle *h=&tap->handles[i];memset(h,0,sizeof(*h));
        h->active=1;h->handle=(uint16_t)handle;h->conn_ms=b5q_h4_now(tap);return h;
    }
    return NULL; // Never evict a live handle and misattribute its disconnect.
}
static inline void b5q_h4_disconnect(struct B5qBtH4Tap *tap,const struct B5qBtH4View *v){
    const uint32_t p=v->payload_offset,handle=b5q_h4_get16(v,p+1u)&0xfffu;
    struct B5qBtH4Handle unknown;memset(&unknown,0,sizeof(unknown));unknown.handle=(uint16_t)handle;
    struct B5qBtH4Handle *known=b5q_h4_handle(tap,handle,0),*h=known?known:&unknown;
    const uint64_t now=b5q_h4_now(tap);
    if(tap->disconnLogged<32u){
        tap->disconnLogged++;
        struct B5qBtH4Text t;memset(&t,0,sizeof(t));
        b5q_h4_text_puts(&t,"B5qBluetooth: h4-disconn-ctx ms=");b5q_h4_text_u(&t,now);
        b5q_h4_text_puts(&t," handle=");b5q_h4_text_hex(&t,handle,4);
        b5q_h4_text_puts(&t," reason=");b5q_h4_text_hex(&t,b5q_h4_get8(v,p+3u),2);
        b5q_h4_text_puts(&t," le=");b5q_h4_text_u(&t,h->is_le);
        b5q_h4_text_puts(&t," alive_ms=");b5q_h4_text_u(&t,known&&now>=h->conn_ms?now-h->conn_ms:0);
        b5q_h4_text_puts(&t," since_tx_ms=");b5q_h4_text_u(&t,h->tx_acl&&now>=h->last_tx_acl_ms?now-h->last_tx_acl_ms:0);
        b5q_h4_text_puts(&t," since_rx_ms=");b5q_h4_text_u(&t,h->rx_acl&&now>=h->last_rx_acl_ms?now-h->last_rx_acl_ms:0);
        b5q_h4_text_puts(&t," tx_acl=");b5q_h4_text_u(&t,h->tx_acl);
        b5q_h4_text_puts(&t," rx_acl=");b5q_h4_text_u(&t,h->rx_acl);
        b5q_h4_text_puts(&t," tx_cid=");b5q_h4_text_hex(&t,h->last_tx_cid,4);
        b5q_h4_text_puts(&t," rx_cid=");b5q_h4_text_hex(&t,h->last_rx_cid,4);
        b5q_h4_text_puts(&t," mode=");b5q_h4_text_u(&t,h->mode);
        b5q_h4_text_puts(&t," intv=");b5q_h4_text_u(&t,h->mode_interval);
        b5q_h4_text_puts(&t," sup_slots=");b5q_h4_text_u(&t,h->sup_slots);
        b5q_h4_text_puts(&t," last_psm=");b5q_h4_text_hex(&t,h->last_psm,4);
        b5q_h4_send(tap,&t);
    }
    if(known&&b5q_h4_get8(v,p)==0)known->active=0;
}
static inline void b5q_h4_track_event(struct B5qBtH4Tap *tap,const struct B5qBtH4View *v){
    const unsigned evt=b5q_h4_get8(v,1),p=v->payload_offset,sub=b5q_h4_get8(v,p);
    struct B5qBtH4Handle *h=NULL;
    if(evt==3u&&v->payload_len>=11u&&sub==0){
        h=b5q_h4_handle(tap,b5q_h4_get16(v,p+1),1);
        if(h){memset(h,0,sizeof(*h));h->active=1;h->handle=(uint16_t)(b5q_h4_get16(v,p+1)&0xfff);h->conn_ms=b5q_h4_now(tap);}
    }else if(evt==0x3eu&&(sub==1u||sub==0x0au)&&v->payload_len>=(sub==1u?19u:31u)&&b5q_h4_get8(v,p+1)==0){
        h=b5q_h4_handle(tap,b5q_h4_get16(v,p+2),1);
        if(h){memset(h,0,sizeof(*h));h->active=h->is_le=1;h->handle=(uint16_t)(b5q_h4_get16(v,p+2)&0xfff);h->conn_ms=b5q_h4_now(tap);h->sup_slots=(uint16_t)b5q_h4_get16(v,p+(sub==1u?16u:28u));}
    }else if(evt==0x3eu&&sub==3u&&v->payload_len>=10u&&b5q_h4_get8(v,p+1)==0){
        h=b5q_h4_handle(tap,b5q_h4_get16(v,p+2),0);if(h)h->sup_slots=(uint16_t)b5q_h4_get16(v,p+8);
    }else if(evt==0x14u&&v->payload_len>=6u){
        tap->stats.mode_changes++;h=b5q_h4_handle(tap,b5q_h4_get16(v,p+1),0);
        if(h&&sub==0){h->mode=(uint8_t)b5q_h4_get8(v,p+3);h->mode_interval=(uint16_t)b5q_h4_get16(v,p+4);}
    }else if(evt==0x38u&&v->payload_len>=4u){
        tap->stats.supervision_changes++;h=b5q_h4_handle(tap,b5q_h4_get16(v,p),0);
        if(h)h->sup_slots=(uint16_t)b5q_h4_get16(v,p+2);
    }else if(evt==0x12u)tap->stats.role_changes++;
    else if(evt==0x2cu||evt==0x2du)tap->stats.sco_events++;
    if(evt==5u&&v->payload_len>=4u)b5q_h4_disconnect(tap,v);
}

static inline void b5q_h4_event(struct B5qBtH4Tap *tap, const struct B5qBtH4View *v) {
    b5q_h4_track_event(tap,v);
    const uint32_t evt = b5q_h4_get8(v, 1u);
    const uint32_t payload = v->payload_offset;
    uint32_t status = 0, opcode = 0, sub = 0;
    int error = 0;
    if (evt == 0x0eu) {
        opcode = b5q_h4_get16(v, payload + 1u);status = b5q_h4_get8(v, payload + 3u);
        if (status == 0 && b5q_h4_scan_opcode(opcode)) { tap->stats.filtered++; return; }
        error = status != 0;
    } else if (evt == 0x0fu) {
        status = b5q_h4_get8(v, payload);opcode = b5q_h4_get16(v, payload + 2u);
        if (status == 0 && b5q_h4_scan_opcode(opcode)) { tap->stats.filtered++; return; }
        error = status != 0;
    } else if (evt == 0x3eu) {
        sub = b5q_h4_get8(v, payload);
        if (sub == 0x02u || sub == 0x0bu || sub == 0x0du) { tap->stats.filtered++; return; }
        if (sub == 0x0cu && b5q_h4_get8(v, payload + 1u) != 0u) error = 1;
    } else if (evt == 0x02u || evt == 0x22u || evt == 0x2fu || evt == 0x13u) {
        if (evt == 0x13u) tap->stats.evt13++;
        tap->stats.filtered++; return;
    }
    if (error || evt == 0x10u || evt == 0x1au) { tap->stats.errs++;error = 1; }
    if (!b5q_h4_key_slot(tap)) return;
    struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
    b5q_h4_header(tap, &text, 0);b5q_h4_text_puts(&text, "type=EVT evt=");
    b5q_h4_text_hex(&text, evt, 2);b5q_h4_text_puts(&text, " len=");
    b5q_h4_text_u(&text, v->total_len);
    if (evt == 0x3eu) { b5q_h4_text_puts(&text, " sub=");b5q_h4_text_hex(&text, sub, 2); }
    if (evt == 0x0eu || evt == 0x0fu) {
        b5q_h4_text_puts(&text, " op=");b5q_h4_text_hex(&text, opcode, 4);
        b5q_h4_text_puts(&text, " status=");b5q_h4_text_hex(&text, status, 2);
    } else if (evt == 0x05u) {
        b5q_h4_text_puts(&text, " disconn status=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload), 2);
        b5q_h4_text_puts(&text, " handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 1u), 4);
        b5q_h4_text_puts(&text, " reason=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 3u), 2);
    } else if (evt == 0x03u) {
        b5q_h4_text_puts(&text, " conn-complete status=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload), 2);
        b5q_h4_text_puts(&text, " handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 1u), 4);
        b5q_h4_text_puts(&text, " addr=");b5q_h4_text_mac(&text, v, payload + 3u);
        b5q_h4_text_puts(&text, " link=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 9u), 2);
        b5q_h4_text_puts(&text, " enc=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 10u), 2);
    } else if (evt == 0x14u) {
        b5q_h4_text_puts(&text," mode-change handle=");b5q_h4_text_hex(&text,b5q_h4_get16(v,payload+1u),4);
        b5q_h4_text_puts(&text," mode=");b5q_h4_text_u(&text,b5q_h4_get8(v,payload+3u));
        b5q_h4_text_puts(&text," interval=");b5q_h4_text_u(&text,b5q_h4_get16(v,payload+4u));
    } else if (evt == 0x38u) {
        b5q_h4_text_puts(&text," supervision handle=");b5q_h4_text_hex(&text,b5q_h4_get16(v,payload),4);
        b5q_h4_text_puts(&text," sup_slots=");b5q_h4_text_u(&text,b5q_h4_get16(v,payload+2u));
    } else if (evt == 0x12u) {
        b5q_h4_text_puts(&text," role-change status=");b5q_h4_text_hex(&text,b5q_h4_get8(v,payload),2);
        b5q_h4_text_puts(&text," role=");b5q_h4_text_u(&text,b5q_h4_get8(v,payload+7u));
    } else if (evt == 0x2cu || evt == 0x2du) {
        b5q_h4_text_puts(&text," synchronous-link status=");b5q_h4_text_hex(&text,b5q_h4_get8(v,payload),2);
        b5q_h4_text_puts(&text," handle=");b5q_h4_text_hex(&text,b5q_h4_get16(v,payload+1u),4);
    } else if (evt == 0x08u) {
        b5q_h4_text_puts(&text, " enc-change status=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload), 2);
        b5q_h4_text_puts(&text, " handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 1u), 4);
        b5q_h4_text_puts(&text, " enc=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 3u), 2);
    } else if (evt == 0x3eu && sub == 0x06u) {
        b5q_h4_text_puts(&text, " le-conn-param-req handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 1u), 4);
        b5q_h4_text_puts(&text, " min=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 3u), 4);
        b5q_h4_text_puts(&text, " max=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 5u), 4);
        b5q_h4_text_puts(&text, " lat=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 7u), 4);
        b5q_h4_text_puts(&text, " timeout=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 9u), 4);
    } else if (evt == 0x3eu && sub == 0x07u) {
        b5q_h4_text_puts(&text, " le-data-len handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 1u), 4);
        b5q_h4_text_puts(&text, " tx_oct=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 3u), 4);
        b5q_h4_text_puts(&text, " tx_time=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 5u), 4);
        b5q_h4_text_puts(&text, " rx_oct=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 7u), 4);
        b5q_h4_text_puts(&text, " rx_time=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 9u), 4);
    } else if (evt == 0x3eu && sub == 0x0cu) {
        b5q_h4_text_puts(&text, " le-phy status=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 1u), 2);
        b5q_h4_text_puts(&text, " handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 2u), 4);
        b5q_h4_text_puts(&text, " tx_phy=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 4u), 2);
        b5q_h4_text_puts(&text, " rx_phy=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 5u), 2);
    } else if (evt == 0x3eu && (sub == 0x01u || sub == 0x0au)) {
        b5q_h4_text_puts(&text, " le-conn status=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 1u), 2);
        b5q_h4_text_puts(&text, " handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, payload + 2u), 4);
        b5q_h4_text_puts(&text, " role=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 4u), 2);
        b5q_h4_text_puts(&text, " addr_type=");b5q_h4_text_hex(&text, b5q_h4_get8(v, payload + 5u), 2);
        b5q_h4_text_puts(&text, " addr=");b5q_h4_text_mac(&text, v, payload + 6u);
    }
    if (error) b5q_h4_text_puts(&text, " err=1");
    b5q_h4_text_puts(&text, " hex=");
    b5q_h4_text_bytes(&text, v->prefix + payload, v->prefix_len > payload ? v->prefix_len - payload : 0u, 24u);
    b5q_h4_send(tap, &text);
}

static inline void b5q_h4_command(struct B5qBtH4Tap *tap, const struct B5qBtH4View *v, int tx) {
    const uint32_t opcode = b5q_h4_get16(v, 1u);
    if(opcode==0x0428u||opcode==0x0429u||opcode==0x043du||opcode==0x043eu)tap->stats.sco_commands++;
    if(opcode==0x0c37u&&v->payload_len>=4u){
        struct B5qBtH4Handle *h=b5q_h4_handle(tap,b5q_h4_get16(v,v->payload_offset),0);
        if(h)h->sup_slots=(uint16_t)b5q_h4_get16(v,v->payload_offset+2u);
    }
    if (b5q_h4_scan_opcode(opcode)) { tap->stats.filtered++; return; }
    if (!b5q_h4_key_slot(tap)) return;
    struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
    b5q_h4_header(tap, &text, tx);b5q_h4_text_puts(&text, "type=CMD op=");
    b5q_h4_text_hex(&text, opcode, 4);b5q_h4_text_puts(&text, " len=");
    b5q_h4_text_u(&text, v->total_len);
    b5q_h4_text_puts(&text, " vendor=");b5q_h4_text_u(&text, (opcode & 0xfc00u) == 0xfc00u);
    b5q_h4_text_puts(&text, " hex=");
    b5q_h4_text_bytes(&text, v->prefix, v->prefix_len, 24u);
    b5q_h4_send(tap, &text);
}

static inline void b5q_h4_acl(struct B5qBtH4Tap *tap, const struct B5qBtH4View *v, int tx) {
    const uint32_t handle = b5q_h4_get16(v, 1u) & 0x0fffu;
    const uint32_t pb = (b5q_h4_get8(v, 2u) >> 4) & 3u;
    const uint32_t bc = (b5q_h4_get8(v, 2u) >> 6) & 3u;
    struct B5qBtH4Handle *h=b5q_h4_handle(tap,handle,0);
    if(h){if(tx){h->tx_acl++;h->last_tx_acl_ms=b5q_h4_now(tap);}else{h->rx_acl++;h->last_rx_acl_ms=b5q_h4_now(tap);}}
    if (pb == 1u) return;  /* continuation fragment: no L2CAP header */
    if (v->payload_len < 4u || v->prefix_len < v->payload_offset + 4u) {
        tap->stats.malformed++;
        if (!b5q_h4_key_slot(tap)) return;
        b5q_h4_simple(tap, tx, "type=ACL malformed handle=", handle, 4);
        return;
    }
    const uint32_t l2cap_len = b5q_h4_get16(v, v->payload_offset);
    const uint32_t cid = b5q_h4_get16(v, v->payload_offset + 2u);
    const uint32_t protocol = v->payload_offset + 4u;
    if(h){
        if(tx)h->last_tx_cid=(uint16_t)cid;else h->last_rx_cid=(uint16_t)cid;
        if(cid==1u||cid==5u){
            h->last_sig_code=(uint8_t)b5q_h4_get8(v,protocol);
            if((h->last_sig_code==2u||h->last_sig_code==0x14u)&&v->payload_len>=10u)
                h->last_psm=(uint16_t)b5q_h4_get16(v,protocol+4u);
        }
    }
    int key = 0, normal = 0;
    if (cid == 0x0006u) { key = 1;tap->stats.smp++; }
    else if (cid == 0x0001u || cid == 0x0005u) { key = 1;tap->stats.l2cap++; }
    else if (cid == 0x0004u) {
        const uint32_t att_op = b5q_h4_get8(v, protocol);
        if (att_op == 0x01u) { key = 1;tap->stats.errs++; }
        else { tap->stats.att++;normal = 1; }
    } else if (cid >= 0x0040u) { tap->stats.cid++;normal = 1; }
    else { tap->stats.cid++;normal = 1; }
    if (key) { if (!b5q_h4_key_slot(tap)) return; }
    else if (normal) {
        if (cid == 0x0004u) {
            if (tap->quota.att >= B5Q_BT_H4_ATT_LIMIT) {
                tap->stats.att_dropped++;
                if (!tap->quota.att_summary) {
                    tap->quota.att_summary = 1;
                    if (b5q_h4_summary_slot(tap)) {
                        struct B5qBtH4Text summary;memset(&summary, 0, sizeof(summary));
                        b5q_h4_header(tap, &summary, tx);b5q_h4_text_puts(&summary, "att-summary logged=");
                        b5q_h4_text_u(&summary, tap->quota.att);b5q_h4_text_puts(&summary, " further-counted=1");
                        b5q_h4_send(tap, &summary);
                    }
                }
                return;
            }
            tap->quota.att++;
        } else {
            if (tap->quota.cid >= B5Q_BT_H4_CID_LIMIT) {
                tap->stats.cid_dropped++;
                if (!tap->quota.cid_summary) {
                    tap->quota.cid_summary = 1;
                    if (b5q_h4_summary_slot(tap)) {
                        struct B5qBtH4Text summary;memset(&summary, 0, sizeof(summary));
                        b5q_h4_header(tap, &summary, tx);b5q_h4_text_puts(&summary, "cid-summary logged=");
                        b5q_h4_text_u(&summary, tap->quota.cid);b5q_h4_text_puts(&summary, " further-counted=1");
                        b5q_h4_send(tap, &summary);
                    }
                }
                return;
            }
            tap->quota.cid++;
        }
        if (!b5q_h4_normal_slot(tap)) return;
    } else return;
    struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
    b5q_h4_header(tap, &text, tx);b5q_h4_text_puts(&text, "type=ACL handle=");
    b5q_h4_text_hex(&text, handle, 4);b5q_h4_text_puts(&text, " pb=");b5q_h4_text_u(&text, pb);
    b5q_h4_text_puts(&text, " bc=");b5q_h4_text_u(&text, bc);
    b5q_h4_text_puts(&text, " len=");b5q_h4_text_u(&text, v->total_len);
    b5q_h4_text_puts(&text, " l2cap_len=");b5q_h4_text_u(&text, l2cap_len);
    b5q_h4_text_puts(&text, " cid=");b5q_h4_text_hex(&text, cid, 4);
    if (cid == 0x0006u) {
        const uint32_t smp_op = b5q_h4_get8(v, protocol);
        b5q_h4_text_puts(&text, " smp_op=");b5q_h4_text_hex(&text, smp_op, 2);
        if (smp_op == 0x05u) {
            tap->stats.errs++;
            b5q_h4_text_puts(&text, " pairing-failed reason=");
            b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 1u), 2);
        } else if (smp_op == 0x01u || smp_op == 0x02u) {
            b5q_h4_text_puts(&text, " io=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 1u), 2);
            b5q_h4_text_puts(&text, " oob=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 2u), 2);
            b5q_h4_text_puts(&text, " auth=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 3u), 2);
            b5q_h4_text_puts(&text, " maxkey=");b5q_h4_text_u(&text, b5q_h4_get8(v, protocol + 4u));
            b5q_h4_text_puts(&text, " init=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 5u), 2);
            b5q_h4_text_puts(&text, " resp=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 6u), 2);
        }
    } else if (cid == 0x0001u || cid == 0x0005u) {
        b5q_h4_text_puts(&text, " sig-code=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol), 2);
        b5q_h4_text_puts(&text, " sig-id=");b5q_h4_text_u(&text, b5q_h4_get8(v, protocol + 1u));
        b5q_h4_text_puts(&text, " sig-len=");b5q_h4_text_u(&text, b5q_h4_get16(v, protocol + 2u));
    } else if (cid == 0x0004u) {
        const uint32_t att_op = b5q_h4_get8(v, protocol);
        b5q_h4_text_puts(&text, " att-op=");b5q_h4_text_hex(&text, att_op, 2);
        if (att_op == 0x01u) {
            b5q_h4_text_puts(&text, " att-req=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 1u), 2);
            b5q_h4_text_puts(&text, " att-handle=");b5q_h4_text_hex(&text, b5q_h4_get16(v, protocol + 2u), 4);
            b5q_h4_text_puts(&text, " att-error=");b5q_h4_text_hex(&text, b5q_h4_get8(v, protocol + 4u), 2);
        }
    }
    b5q_h4_text_puts(&text, " hex=");
    b5q_h4_text_bytes(&text, v->prefix, v->prefix_len, cid >= 0x0040u ? 20u : 24u);
    b5q_h4_send(tap, &text);
}

static inline void b5q_h4_dispatch(struct B5qBtH4Tap *tap, int tx, const struct B5qBtH4View *v) {
    if (tx) {
        if (v->type == 0x01u) tap->stats.tx_cmd++;
        else if (v->type == 0x02u) tap->stats.tx_acl++;
        else if (v->type == 0x03u) tap->stats.tx_sco++;
        else if (v->type == 0x05u) tap->stats.tx_iso++;
    } else {
        if (v->type == 0x04u) tap->stats.rx_evt++;
        else if (v->type == 0x02u) tap->stats.rx_acl++;
        else if (v->type == 0x03u) tap->stats.rx_sco++;
        else if (v->type == 0x05u) tap->stats.rx_iso++;
    }
    if (v->type == 0x01u) b5q_h4_command(tap, v, tx);
    else if (v->type == 0x04u) b5q_h4_event(tap, v);
    else if (v->type == 0x02u) b5q_h4_acl(tap, v, tx);
    else if (v->type == 0x03u || v->type == 0x05u) {
        if (!b5q_h4_key_slot(tap)) return;
        struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
        b5q_h4_header(tap, &text, tx);b5q_h4_text_puts(&text, v->type == 0x03u ? "type=SCO" : "type=ISO");
        b5q_h4_text_puts(&text, " len=");b5q_h4_text_u(&text, v->total_len);
        b5q_h4_text_puts(&text, " hex=");b5q_h4_text_bytes(&text, v->prefix, v->prefix_len, 24u);
        b5q_h4_send(tap, &text);
    }
}

static inline void b5q_bt_h4_parser_reset(struct B5qBtH4Parser *p) {
    if (!p) return;
    // Frame state only: desync is a session counter and must never move
    // backwards when a valid frame completes.
    p->state = 0;p->type = 0;p->hdr_len = 0;p->hdr_have = 0;
    p->prefix_len = 0;p->payload_left = 0;p->total_len = 0;p->payload_offset = 0;
}
static inline void b5q_bt_h4_tap_reset_streams(struct B5qBtH4Tap *tap) {
    if (!tap) return;
    b5q_bt_h4_parser_reset(&tap->tx);b5q_bt_h4_parser_reset(&tap->rx);
}
static inline void b5q_bt_h4_tap_reset_session(struct B5qBtH4Tap *tap) {
    if (!tap) return;
    b5q_bt_h4_tap_reset_streams(tap);
    tap->tx.desync = 0;tap->rx.desync = 0;
    memset(&tap->stats, 0, sizeof(tap->stats));
    memset(&tap->quota, 0, sizeof(tap->quota));
    memset(tap->handles,0,sizeof(tap->handles));tap->disconnLogged=0;
}
static inline void b5q_bt_h4_tap_init(struct B5qBtH4Tap *tap, const struct B5qBtH4Sink *sink,
                                      void *ctx, int enabled) {
    if (!tap) return;
    memset(tap, 0, sizeof(*tap));
    tap->sink = sink;tap->ctx = ctx;tap->enabled = enabled != 0;
}

static inline void b5q_h4_parser_byte(struct B5qBtH4Tap *tap, struct B5qBtH4Parser *p,
                                      int tx, uint8_t byte) {
    if (p->state == 0) {
        if (byte >= 1u && byte <= 5u) {
            p->type = byte;p->prefix[0] = byte;p->prefix_len = 1;
            p->hdr_len = byte == 0x04u ? 2u : (byte == 0x01u || byte == 0x03u) ? 3u : 4u;
            p->hdr_have = 0;p->state = 1;
        } else {
            p->desync++;tap->stats.desync++;
            if (p->desync <= 8u) {
                struct B5qBtH4Text text;memset(&text, 0, sizeof(text));
                b5q_h4_header(tap, &text, tx);b5q_h4_text_puts(&text, "desync=");
                b5q_h4_text_hex(&text, byte, 2);text.buf[text.len] = 0;
                b5q_h4_send(tap, &text);
            }
        }
        return;
    }
    if (p->state == 1) {
        p->hdr[p->hdr_have++] = byte;
        if (p->prefix_len < B5Q_BT_H4_PREFIX) p->prefix[p->prefix_len++] = byte;
        if (p->hdr_have < p->hdr_len) return;
        uint32_t payload = 0;
        if (p->type == 0x01u || p->type == 0x03u) payload = p->hdr[2];
        else if (p->type == 0x04u) payload = p->hdr[1];
        else if (p->type == 0x02u) payload = p->hdr[2] | ((uint32_t)p->hdr[3] << 8);
        else payload = (p->hdr[2] | ((uint32_t)p->hdr[3] << 8)) & 0x3fffu;
        p->payload_left = payload;p->payload_offset = 1u + p->hdr_len;
        p->total_len = 1u + p->hdr_len + payload;
        p->state = 2;
        if (!payload) goto complete;
        return;
    }
    if (p->prefix_len < B5Q_BT_H4_PREFIX) p->prefix[p->prefix_len++] = byte;
    if (--p->payload_left) return;
complete:
    {
        struct B5qBtH4View view;
        view.type = p->type;view.prefix = p->prefix;view.prefix_len = p->prefix_len;
        view.total_len = p->total_len;view.payload_offset = p->payload_offset;
        view.payload_len = p->total_len - p->payload_offset;
        view.truncated = p->prefix_len < p->total_len;
        b5q_h4_dispatch(tap, tx, &view);
    }
    b5q_bt_h4_parser_reset(p);
}

static inline void b5q_bt_h4_tap_feed(struct B5qBtH4Tap *tap, int tx, const uint8_t *bytes, size_t n) {
    if (!tap || !tap->enabled || !bytes) return;
    struct B5qBtH4Parser *p = tx ? &tap->tx : &tap->rx;
    for (size_t i = 0; i < n; i++) b5q_h4_parser_byte(tap, p, tx, bytes[i]);
}
static inline void b5q_bt_h4_tap_tx(struct B5qBtH4Tap *tap, const uint8_t *bytes, size_t n) {
    b5q_bt_h4_tap_feed(tap, 1, bytes, n);
}
static inline void b5q_bt_h4_tap_rx(struct B5qBtH4Tap *tap, const uint8_t *bytes, size_t n) {
    b5q_bt_h4_tap_feed(tap, 0, bytes, n);
}
/* nativeRx must pass exactly the accepted prefix, never n, or backpressure
 * retries would duplicate bytes and break H4 frame sync. */
static inline void b5q_bt_h4_tap_rx_taken(struct B5qBtH4Tap *tap, const uint8_t *bytes,
                                          size_t n, size_t taken) {
    if (taken > n) taken = n;
    b5q_bt_h4_tap_feed(tap, 0, bytes, taken);
}

#endif
