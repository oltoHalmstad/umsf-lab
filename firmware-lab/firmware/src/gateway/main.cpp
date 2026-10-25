// BLE gateway (ESP32 DevKit): NimBLE central for up to 3 enrolled nodes (personnel and/or
// stationary) merged into ONE ordered uplink stream with per-source identity, plus Wi-Fi STA
// with MQTT over mutually authenticated TLS (QoS 1) and a local status page.
//
// Release 1.0.0: UNTESTED on hardware and NOT compiled. Portable logic (reassembly, CRC,
// buffer, link supervision, JSON, ACK parsing) is host-tested in test/host.
//
// Delivery semantics (paper 3.3.7, A.2): a record stays in the gateway RAM buffer until the site
// agent publishes an application ACK on umsf/<site>/ack/<gw> after durable COMMIT. Only then is
// the record released here and the ACK relayed to the node's ACK characteristic. An MQTT PUBACK
// (QoS 1 broker acknowledgement) never releases anything. The gateway is a trusted endpoint
// that sees plaintext (hop-by-hop pilot profile); see docs/SECURITY.md.
#include <Arduino.h>
#include <LittleFS.h>
#include <NimBLEDevice.h>
#include <WebServer.h>
#include <WiFi.h>
#include <espMqttClient.h>
#include <sys/time.h>
#include <time.h>

#include "esp_sntp.h"
#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif
#include "gateway_page.h"
#include "umsf_buffer.h"
#include "umsf_frag.h"
#include "umsf_gwcore.h"
#include "umsf_hw.h"
#include "umsf_json.h"
#include "umsf_proto.h"
#include "umsf_text.h"

#ifndef UMSF_GATEWAY_ID
#define UMSF_GATEWAY_ID "AG1"
#endif
#ifndef UMSF_SITE_ID
#define UMSF_SITE_ID "A"
#endif

namespace {
constexpr size_t kSlots = 3;               // nodes per gateway (paper 3.3.7)
constexpr uint8_t kGwSrc = 255;            // buffer source id of gateway-generated events
constexpr uint32_t kRepublishMs = 60000;   // republish if no site ACK within 60 s
constexpr uint32_t kSntpBaseUncMs = 100;   // assumed SNTP offset bound; must be measured (A.2)

const umsf::EnrolledNode kEnrolled[] = UMSF_ENROLLED_NODES;
constexpr size_t kNumEnrolled = sizeof(kEnrolled) / sizeof(kEnrolled[0]);
static_assert(kNumEnrolled <= 8, "LinkMonitor capacity");

enum Kind : uint8_t { K_TEL, K_EVT, K_STATUS, K_COMPACT };
struct RxItem {
    uint8_t slot, kind;
    uint16_t len;
    uint32_t t;
    uint8_t data[UMSF_FRAG_HDR_LEN + 244];
};

struct Slot {
    NimBLEClient *client = nullptr;
    int enrolled = -1;
    volatile bool connected = false;
    volatile bool disconnect_pending = false;
    NimBLERemoteCharacteristic *ack = nullptr, *cfg = nullptr;
    umsf_reasm_t reasm_tel, reasm_evt;
};

struct NodeState {
    umsf_timemap_t tmap;
    bool ack_pending = false;
    uint16_t ack_boot = 0;
    uint32_t ack_seq = 0;
    uint32_t last_seq = 0;
    umsf_compact_t compact{};
    uint32_t compact_ms = 0;
    bool has_compact = false;
    uint8_t rssi_neg = UMSF_NULL_U8;
};

struct LogLine { uint32_t t; char line[150]; };

Slot g_slot[kSlots];
NodeState g_node[kNumEnrolled];
umsf::LinkMonitor<8> g_links;
umsf::RecordBuffer<umsf::kGatewayBufferRecords, UMSF_MAX_FRAME_LEN> g_buf;
QueueHandle_t g_rxq, g_ackq;
uint8_t g_gw_subject[64];                 // gateway event seq -> subject node (enrolled idx)
LogLine g_log[30];
size_t g_log_n = 0, g_log_head = 0;

uint16_t g_boot = 0;
uint32_t g_gw_seq = 0, g_ctl_seq = 0;
volatile int g_pending_idx = -1;
NimBLEAddress g_pending_addr;
volatile uint32_t g_passkey = 0;
volatile bool g_synced = false;
volatile uint32_t g_last_sync_ms = 0;
uint32_t g_rx_dropped = 0, g_crc_errors = 0, g_identity_mismatch = 0, g_published = 0, g_acks_relayed = 0;
uint32_t g_evict_pending = 0, t_evict = 0, t_status = 0, t_mqtt = 0, t_tick = 0;

espMqttClientSecure g_mqtt(espMqttClientTypes::UseInternalTask::YES);
String g_ca, g_crt, g_key;  // must outlive the TLS client (pointers are kept)
char g_ack_topic[64];
WebServer g_web(80);

// ------------------------------------------------------------------ helpers
void log_line(uint32_t t, const char *s) {
    Serial.println(s);
    LogLine &l = g_log[(g_log_head + g_log_n) % 30];
    l.t = t;
    strncpy(l.line, s, sizeof l.line - 1);
    l.line[sizeof l.line - 1] = '\0';
    if (g_log_n < 30) ++g_log_n; else g_log_head = (g_log_head + 1) % 30;
}

int slot_of(NimBLEClient *c) {
    for (size_t i = 0; i < kSlots; ++i) if (g_slot[i].client == c) return (int)i;
    return -1;
}

int64_t utc_offset_ms() {  // UTC ms - local millis(); valid only when g_synced
    struct timeval tv;
    gettimeofday(&tv, nullptr);
    return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000 - (int64_t)millis();
}
uint32_t sntp_unc_ms() { return kSntpBaseUncMs + (uint32_t)((uint64_t)(millis() - g_last_sync_ms) * 50 / 1000000); }

void emit_gw_event(uint8_t type, uint8_t level, int32_t value, int subject, uint16_t rel_seq) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    uint32_t now = millis();
    umsf_header_init(&f.hdr, UMSF_SRC_GATEWAY, UMSF_FT_EVENT, UMSF_GATEWAY_ID, g_boot, ++g_gw_seq, now);
    uint16_t zone = subject >= 0 ? kEnrolled[subject].zone_code : 0;
    f.u.event = umsf_event_t{type, level, value, 1, zone, rel_seq};
    g_gw_subject[g_gw_seq % 64] = subject >= 0 ? (uint8_t)subject : 0xFF;
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    g_buf.push(kGwSrc, g_boot, g_gw_seq, umsf::PRIO_EVENT, b, n, now);
    char line[150];
    umsf_text_line(UMSF_GATEWAY_ID, now, &f, line, sizeof line);
    if (subject >= 0) { strncat(line, ",subject=", sizeof line - strlen(line) - 1); strncat(line, kEnrolled[subject].device_id, sizeof line - strlen(line) - 1); }
    log_line(now, line);
}

void relay_ack(int idx) {
    NodeState &n = g_node[idx];
    if (!n.ack_pending) return;
    for (auto &s : g_slot) {
        if (s.enrolled != idx || !s.connected || !s.ack) continue;
        umsf_frame_t f;
        memset(&f, 0, sizeof f);
        umsf_header_init(&f.hdr, UMSF_SRC_GATEWAY, UMSF_FT_ACK, UMSF_GATEWAY_ID, g_boot, ++g_ctl_seq, millis());
        f.u.ack = umsf_ack_t{n.ack_boot, 0, n.ack_seq};
        uint8_t b[UMSF_MAX_FRAME_LEN];
        size_t len = umsf_encode(&f, b, sizeof b);
        if (s.ack->writeValue(b, len, true)) {
            ++g_acks_relayed;
            Serial.printf("ACKR,%s,%u,%lu\n", kEnrolled[idx].device_id, n.ack_boot, (unsigned long)n.ack_seq);
        }
    }
}

// ------------------------------------------------------------------ BLE central
void notify_cb(NimBLERemoteCharacteristic *c, uint8_t *data, size_t len, bool) {
    int s = slot_of(c->getRemoteService()->getClient());
    if (s < 0 || len > sizeof(RxItem::data)) { ++g_rx_dropped; return; }
    RxItem it;
    it.slot = (uint8_t)s;
    const NimBLEUUID &u = c->getUUID();
    it.kind = u == NimBLEUUID(uuids::EVENT) ? K_EVT : u == NimBLEUUID(uuids::STATUS) ? K_STATUS
            : u == NimBLEUUID(uuids::COMPACT) ? K_COMPACT : K_TEL;
    it.len = (uint16_t)len;
    it.t = millis();
    memcpy(it.data, data, len);
    if (xQueueSend(g_rxq, &it, 0) != pdTRUE) ++g_rx_dropped;  // node keeps the record until ACK
}

class ClientCB : public NimBLEClientCallbacks {
    void onDisconnect(NimBLEClient *c) override {
        int s = slot_of(c);
        if (s < 0) return;
        g_slot[s].connected = false;
        g_slot[s].disconnect_pending = true;
    }
    uint32_t onPassKeyRequest() override { return g_passkey; }  // enrolled passkey of the node being paired
    bool onConfirmPIN(uint32_t) override { return false; }      // numeric comparison not used
    void onAuthenticationComplete(ble_gap_conn_desc *desc) override {
        if (!desc->sec_state.encrypted || !desc->sec_state.authenticated) {
            NimBLEClient *c = NimBLEDevice::getClientByID(desc->conn_handle);
            if (c) c->disconnect();
        }
    }
} g_client_cb;

class AdvCB : public NimBLEAdvertisedDeviceCallbacks {
    void onResult(NimBLEAdvertisedDevice *d) override {
        if (g_pending_idx >= 0 || !d->isAdvertisingService(NimBLEUUID(uuids::SERVICE))) return;
        int idx = umsf::find_enrolled_by_addr(kEnrolled, kNumEnrolled, d->getAddress().toString().c_str());
        if (idx < 0) return;  // allowlist: unknown devices are ignored
        for (auto &s : g_slot) if (s.enrolled == idx && s.connected) return;
        g_pending_addr = d->getAddress();
        g_pending_idx = idx;
        NimBLEDevice::getScan()->stop();
    }
} g_adv_cb;

bool subscribe(NimBLERemoteService *svc, const char *uuid, bool required) {
    NimBLERemoteCharacteristic *c = svc->getCharacteristic(uuid);
    if (!c || !c->canNotify()) return !required;
    return c->subscribe(true, notify_cb, true);
}

void connect_node(int idx) {
    int s = -1;
    for (size_t i = 0; i < kSlots; ++i) if (!g_slot[i].connected) { s = (int)i; break; }
    if (s < 0) return;
    Slot &sl = g_slot[s];
    const umsf::EnrolledNode &en = kEnrolled[idx];
    g_passkey = en.passkey;
    NimBLEDevice::getScan()->stop();  // the controller cannot initiate a connection while scanning
    Serial.printf("# connecting %s (%s) slot %d\n", en.device_id, en.ble_addr, s);
    if (!sl.client->connect(g_pending_addr)) { Serial.println("# connect failed"); return; }
    if (!sl.client->secureConnection()) { Serial.println("# pairing failed"); sl.client->disconnect(); return; }
    NimBLEConnInfo ci = sl.client->getConnInfo();
    if (!ci.isEncrypted() || !ci.isAuthenticated()) { sl.client->disconnect(); return; }
    NimBLERemoteService *svc = sl.client->getService(uuids::SERVICE);
    if (!svc) { sl.client->disconnect(); return; }
    umsf_reasm_init(&sl.reasm_tel);
    umsf_reasm_init(&sl.reasm_evt);
    sl.enrolled = idx;
    sl.ack = svc->getCharacteristic(uuids::ACK);
    sl.cfg = svc->getCharacteristic(uuids::CONFIG);
    sl.connected = true;
    bool ok = subscribe(svc, uuids::TELEMETRY, true) && subscribe(svc, uuids::EVENT, true) &&
              subscribe(svc, uuids::STATUS, false) &&
              (en.source_class != UMSF_SRC_STATIONARY || subscribe(svc, uuids::COMPACT, true));
    if (!ok || !sl.ack) { Serial.println("# GATT layout mismatch"); sl.client->disconnect(); return; }
    if (sl.cfg) {  // enrollment table is the configuration authority
        umsf_frame_t f;
        memset(&f, 0, sizeof f);
        umsf_header_init(&f.hdr, UMSF_SRC_GATEWAY, UMSF_FT_CONFIG, UMSF_GATEWAY_ID, g_boot, ++g_ctl_seq, millis());
        f.u.config = umsf_config_t{en.zone_code, 10000, 0, (uint8_t)UMSF_CONFIG_SYNTHETIC_HR, 0};
        uint8_t b[UMSF_MAX_FRAME_LEN];
        sl.cfg->writeValue(b, umsf_encode(&f, b, sizeof b), true);
    }
    relay_ack(idx);  // a node that reconnects learns the latest committed position at once
    Serial.printf("# %s connected, MTU %u\n", en.device_id, sl.client->getMTU());
}

// ------------------------------------------------------------------ frame processing
void process_rx(const RxItem &it) {
    Slot &sl = g_slot[it.slot];
    if (sl.enrolled < 0) return;
    int idx = sl.enrolled;
    const umsf::EnrolledNode &en = kEnrolled[idx];
    NodeState &ns = g_node[idx];
    umsf::LinkEvent le;

    if (it.kind == K_COMPACT) {
        umsf_compact_t c;
        if (umsf_compact_decode(it.data, it.len, &c) != UMSF_OK) { ++g_crc_errors; return; }
        ns.compact = c;
        ns.compact_ms = it.t;
        ns.has_compact = true;
        if (g_links.on_frame(idx, it.t, le)) emit_gw_event(le.type, UMSF_LVL_INFO, le.value_x1000, idx, (uint16_t)ns.last_seq);
        return;
    }
    uint8_t msg[UMSF_REASM_MAX_BYTES];
    size_t mlen = 0;
    if (it.kind == K_STATUS) {  // STATUS characteristic value is a bare frame (no fragment header)
        memcpy(msg, it.data, it.len);
        mlen = it.len;
    } else {
        int r = umsf_reasm_push(it.kind == K_EVT ? &sl.reasm_evt : &sl.reasm_tel, it.data, it.len, it.t, msg,
                                sizeof msg, &mlen);
        if (r != UMSF_REASM_COMPLETE) return;
    }
    umsf_frame_t f;
    int rc = umsf_decode(msg, mlen, &f);
    if (rc != UMSF_OK) {
        ++g_crc_errors;
        Serial.printf("# drop frame from %s: %s\n", en.device_id, umsf_strerror(rc));
        return;
    }
    // identity binding: the authenticated link must carry frames of the enrolled device only
    if (strncmp(f.hdr.device_id, en.device_id, 4) != 0 || f.hdr.source_class != en.source_class) {
        ++g_identity_mismatch;
        return;
    }
    if (g_links.on_frame(idx, it.t, le)) emit_gw_event(le.type, UMSF_LVL_INFO, le.value_x1000, idx, (uint16_t)ns.last_seq);

    if (f.hdr.frame_type == UMSF_FT_STATUS) {
        ns.rssi_neg = f.u.status.rssi_neg;
        if (g_mqtt.connected()) {
            umsf_json_ctx_t c;
            umsf_json_ctx_init(&c);
            c.site_id = UMSF_SITE_ID;
            c.gateway_id = UMSF_GATEWAY_ID;
            if (g_synced) c.received_at_ms = (int64_t)it.t + utc_offset_ms();
            char js[512], topic[64];
            if (umsf_json_node_status(&c, &f, js, sizeof js) > 0) {
                snprintf(topic, sizeof topic, "umsf/%s/%s/status", UMSF_SITE_ID, UMSF_GATEWAY_ID);
                g_mqtt.publish(topic, 1, false, js);
            }
        }
        return;
    }
    bool record = f.hdr.frame_type == UMSF_FT_EVENT ||
                  (f.hdr.frame_type == UMSF_FT_PHYSIO_FEATURE && en.source_class == UMSF_SRC_PERSONNEL) ||
                  (f.hdr.frame_type == UMSF_FT_STATION_STATE && en.source_class == UMSF_SRC_STATIONARY);
    if (!record) return;
    umsf_timemap_observe(&ns.tmap, f.hdr.boot_id, f.hdr.sequence, f.hdr.node_time_ms, (int64_t)it.t);
    if (f.hdr.sequence > ns.last_seq) ns.last_seq = f.hdr.sequence;
    uint8_t prio = f.hdr.frame_type != UMSF_FT_EVENT ? umsf::PRIO_TELEMETRY
                 : f.u.event.level >= UMSF_LVL_URGENT ? umsf::PRIO_URGENT : umsf::PRIO_EVENT;
    auto r = g_buf.push((uint8_t)idx, f.hdr.boot_id, f.hdr.sequence, prio, msg, mlen, it.t);
    if (r == decltype(g_buf)::PUSH_DUPLICATE) return;  // resend of a record still awaiting site ACK
    char line[150];
    if (umsf_text_line(UMSF_GATEWAY_ID, it.t, &f, line, sizeof line) > 0) log_line(it.t, line);
}

// ------------------------------------------------------------------ MQTT uplink
void publish_pending() {
    if (!g_mqtt.connected() || !g_synced) return;  // TLS needs a valid clock; records wait in RAM
    g_buf.requeue_stale(millis(), kRepublishMs);
    for (int k = 0; k < 4; ++k) {  // EVENT frames first (priority), then oldest telemetry
        auto *e = g_buf.next_to_send();
        if (!e) return;
        umsf_frame_t f;
        if (umsf_decode(e->data, e->len, &f) != UMSF_OK) { g_buf.mark_sent(e, millis()); continue; }
        int64_t off = utc_offset_ms();
        umsf_json_ctx_t c;
        umsf_json_ctx_init(&c);
        c.data_origin = UMSF_DATA_ORIGIN;
        c.scenario_id = UMSF_SCENARIO_ID;
        c.site_id = UMSF_SITE_ID;
        c.gateway_id = UMSF_GATEWAY_ID;
        c.received_at_ms = (int64_t)e->t_in_ms + off;
        if (e->src == kGwSrc) {
            uint8_t subj = g_gw_subject[f.hdr.sequence % 64];
            if (subj != 0xFF) {
                c.subject_device_id = kEnrolled[subj].device_id;
                c.zone_id = kEnrolled[subj].zone_id;
            }
            c.method = f.u.event.event_type == UMSF_EV_BUFFER_EVICTION ? "gateway RAM buffer oldest-record eviction"
                                                                      : "gateway link supervision (BLE disconnect or staleness)";
            c.measured_at_ms = (int64_t)f.hdr.node_time_ms + off;
            c.time_uncertainty_ms = (int32_t)sntp_unc_ms();
        } else {
            const umsf::EnrolledNode &en = kEnrolled[e->src];
            c.zone_id = en.zone_id;
            c.attachment_verified = en.attachment_verified;
            int64_t local;
            uint32_t unc;
            if (umsf_timemap_map(&g_node[e->src].tmap, f.hdr.boot_id, f.hdr.node_time_ms, (int64_t)millis(), &local, &unc) == 0) {
                c.measured_at_ms = local + off;
                c.time_uncertainty_ms = (int32_t)(unc + sntp_unc_ms());
            }  // else: no mapping for that boot session -> measured_at null, never guessed
        }
        static char js[1400];
        if (umsf_json_record(&c, &f, e->data, e->len, js, sizeof js) < 0) { g_buf.mark_sent(e, millis()); continue; }
        const char *kind = f.hdr.frame_type == UMSF_FT_PHYSIO_FEATURE ? "physio"
                         : f.hdr.frame_type == UMSF_FT_STATION_STATE ? "station" : "event";
        char topic[64];
        snprintf(topic, sizeof topic, "umsf/%s/%s/%s", UMSF_SITE_ID, UMSF_GATEWAY_ID, kind);
        if (g_mqtt.publish(topic, 1, false, js) == 0) return;  // client queue full: retry later
        g_buf.mark_sent(e, millis());
        ++g_published;
    }
}

void on_mqtt_message(const espMqttClientTypes::MessageProperties &, const char *topic, const uint8_t *payload,
                     size_t len, size_t index, size_t total) {
    if (strcmp(topic, g_ack_topic) != 0 || index != 0 || len != total) return;
    umsf::SiteAck a;
    if (umsf::parse_site_ack((const char *)payload, len, a)) xQueueSend(g_ackq, &a, 0);
}

void handle_site_acks() {
    umsf::SiteAck a;
    while (xQueueReceive(g_ackq, &a, 0) == pdTRUE) {
        if (strncmp(a.device_id, UMSF_GATEWAY_ID, 4) == 0) {
            g_buf.ack(kGwSrc, a.boot_id, a.ack_up_to_seq);
            continue;
        }
        int idx = umsf::find_enrolled_by_id(kEnrolled, kNumEnrolled, a.device_id);
        if (idx < 0) continue;
        size_t n = g_buf.ack((uint8_t)idx, a.boot_id, a.ack_up_to_seq);
        NodeState &ns = g_node[idx];
        if (!ns.ack_pending || a.boot_id != ns.ack_boot || a.ack_up_to_seq > ns.ack_seq) {
            ns.ack_pending = true;
            ns.ack_boot = a.boot_id;
            ns.ack_seq = a.ack_up_to_seq;
        }
        Serial.printf("SITEACK,%s,%u,%lu,released=%u\n", a.device_id, a.boot_id, (unsigned long)a.ack_up_to_seq, (unsigned)n);
        relay_ack(idx);
    }
}

bool load_pem(const char *path, String &dst, const char *fallback) {
    File f = LittleFS.open(path, "r");
    if (f) { dst = f.readString(); f.close(); }
    if (dst.length() == 0) dst = fallback;
    return dst.length() > 0;
}

void publish_gw_status() {
    char js[1024], topic[64];
    int n = snprintf(js, sizeof js,
                     "{\"kind\":\"gateway_status\",\"site_id\":\"%s\",\"gateway_id\":\"%s\",\"boot_id\":%u,\"uptime_ms\":%lu,"
                     "\"clock_synced\":%s,\"buffered\":%u,\"buffer_capacity\":%u,\"evicted_total\":%lu,\"published_total\":%lu,"
                     "\"acks_relayed\":%lu,\"rx_dropped\":%lu,\"crc_errors\":%lu,\"identity_mismatch\":%lu,\"wifi_rssi_dbm\":%d,\"nodes\":[",
                     UMSF_SITE_ID, UMSF_GATEWAY_ID, g_boot, (unsigned long)millis(), g_synced ? "true" : "false",
                     (unsigned)g_buf.size(), (unsigned)g_buf.capacity(), (unsigned long)g_buf.evicted_total(),
                     (unsigned long)g_published, (unsigned long)g_acks_relayed, (unsigned long)g_rx_dropped,
                     (unsigned long)g_crc_errors, (unsigned long)g_identity_mismatch, (int)WiFi.RSSI());
    uint32_t now = millis();
    for (size_t i = 0; i < kNumEnrolled && n > 0 && n < (int)sizeof js - 160; ++i) {
        static const char *st[] = {"unknown", "up", "lost"};
        uint32_t age = g_links.age_ms(i, now);
        char age_s[12] = "null";
        if (age != UINT32_MAX) snprintf(age_s, sizeof age_s, "%lu", (unsigned long)age);
        n += snprintf(js + n, sizeof js - n, "%s{\"device_id\":\"%s\",\"link\":\"%s\",\"age_ms\":%s}", i ? "," : "",
                      kEnrolled[i].device_id, st[g_links.state(i)], age_s);
    }
    if (n > 0 && n < (int)sizeof js - 3) { js[n++] = ']'; js[n++] = '}'; js[n] = '\0'; }
    snprintf(topic, sizeof topic, "umsf/%s/%s/status", UMSF_SITE_ID, UMSF_GATEWAY_ID);
    if (g_mqtt.connected()) g_mqtt.publish(topic, 1, false, js);
}

// ------------------------------------------------------------------ local web page
void handle_records() {
    uint32_t now = millis();
    String s;
    s.reserve(6000);
    s += "{\"gateway_id\":\"" UMSF_GATEWAY_ID "\",\"site_id\":\"" UMSF_SITE_ID "\",\"boot_id\":" + String(g_boot) +
         ",\"uptime_ms\":" + String(now) + ",\"clock_synced\":" + (g_synced ? "true" : "false") +
         ",\"mqtt\":" + (g_mqtt.connected() ? "true" : "false") + ",\"buffered\":" + String(g_buf.size()) +
         ",\"evicted_total\":" + String(g_buf.evicted_total()) + ",\"nodes\":[";
    for (size_t i = 0; i < kNumEnrolled; ++i) {
        static const char *st[] = {"unknown", "up", "lost"};
        uint32_t age = g_links.age_ms(i, now);
        bool conn = false;
        for (auto &sl : g_slot) conn |= sl.enrolled == (int)i && sl.connected;
        if (i) s += ',';
        s += "{\"device_id\":\"" + String(kEnrolled[i].device_id) + "\",\"source_class\":" +
             String(kEnrolled[i].source_class) + ",\"connected\":" + (conn ? "true" : "false") + ",\"link\":\"" +
             st[g_links.state(i)] + "\",\"fresh\":" + (g_links.fresh(i, now) ? "true" : "false") +
             ",\"age_ms\":" + (age == UINT32_MAX ? String("null") : String(age)) + "}";
    }
    s += "],\"records\":[";
    for (size_t i = 0; i < g_log_n; ++i) {
        const LogLine &l = g_log[(g_log_head + g_log_n - 1 - i) % 30];  // newest first
        if (i) s += ',';
        s += "{\"age_ms\":" + String(now - l.t) + ",\"line\":\"" + String(l.line) + "\"}";
    }
    s += "]}";
    g_web.sendHeader("Cache-Control", "no-store");
    g_web.send(200, "application/json", s);
}

void handle_csv() {
    String s = "# RX,gw_id,gw_ms,kind,device_id,boot_id,seq,node_ms,...  (oldest first)\n";
    for (size_t i = 0; i < g_log_n; ++i) { s += g_log[(g_log_head + i) % 30].line; s += '\n'; }
    g_web.send(200, "text/plain; charset=utf-8", s);
}
}  // namespace

void setup() {
    Serial.begin(115200);
    g_boot = umsf_next_boot_id();
    Serial.printf("# UMSF gateway %s site %s boot %u fw %u, buffer %u records (RAM only)\n", UMSF_GATEWAY_ID,
                  UMSF_SITE_ID, g_boot, UMSF_FW_BUILD, (unsigned)g_buf.capacity());
    g_rxq = xQueueCreate(24, sizeof(RxItem));
    g_ackq = xQueueCreate(8, sizeof(umsf::SiteAck));
    for (size_t i = 0; i < kNumEnrolled; ++i) {
        umsf_timemap_init(&g_node[i].tmap);
        g_links.configure(i, kEnrolled[i].source_class == UMSF_SRC_STATIONARY ? 2000 : 25000);
    }

    // ---- Wi-Fi: STA to the site network + AP for the local page (192.168.4.1) ----
    WiFi.mode(WIFI_AP_STA);
    WiFi.softAP("UMSF-" UMSF_GATEWAY_ID, UMSF_GW_AP_PASSWORD);
    WiFi.setAutoReconnect(true);
    WiFi.begin(UMSF_WIFI_SSID, UMSF_WIFI_PASSWORD);
    sntp_set_time_sync_notification_cb([](struct timeval *) {
        g_synced = true;
        g_last_sync_ms = millis();
    });
    configTime(0, 0, UMSF_NTP_SERVER_1, UMSF_NTP_SERVER_2);  // UTC stored; Europe/Kyiv is display only

    // ---- MQTT over TLS with client certificate (no insecure fallback) ----
    LittleFS.begin(true);
    bool certs = load_pem("/ca.pem", g_ca, UMSF_CA_PEM) & load_pem("/client.crt", g_crt, UMSF_CLIENT_CRT_PEM) &
                 load_pem("/client.key", g_key, UMSF_CLIENT_KEY_PEM);
    if (!certs) Serial.println("# WARNING: TLS credentials missing: MQTT disabled (no insecure fallback)");
    g_mqtt.setCACert(g_ca.c_str());
    g_mqtt.setCertificate(g_crt.c_str());
    g_mqtt.setPrivateKey(g_key.c_str());
    g_mqtt.setServer(UMSF_MQTT_HOST, UMSF_MQTT_PORT);
    g_mqtt.setClientId(UMSF_GATEWAY_ID);
    g_mqtt.setCleanSession(false);  // broker keeps our QoS 1 ack subscription while offline
    g_mqtt.setKeepAlive(30);
    snprintf(g_ack_topic, sizeof g_ack_topic, "umsf/%s/ack/%s", UMSF_SITE_ID, UMSF_GATEWAY_ID);
    g_mqtt.onConnect([](bool) {
        g_mqtt.subscribe(g_ack_topic, 1);
        Serial.println("# MQTT connected");
    });
    g_mqtt.onDisconnect([](espMqttClientTypes::DisconnectReason r) { Serial.printf("# MQTT disconnected (%u)\n", (unsigned)r); });
    g_mqtt.onMessage(on_mqtt_message);
    if (!certs) t_mqtt = UINT32_MAX;

    // ---- BLE central ----
    NimBLEDevice::init("UMSF-" UMSF_GATEWAY_ID);
    NimBLEDevice::setMTU(kRequestedMtu);
    NimBLEDevice::setSecurityAuth(true, true, true);         // bonding, MITM, LE Secure Connections
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_KEYBOARD_ONLY); // gateway enters the node's passkey
    for (auto &s : g_slot) {
        s.client = NimBLEDevice::createClient();
        s.client->setClientCallbacks(&g_client_cb, false);
        s.client->setConnectionParams(24, 40, 0, 400);  // 30-50 ms interval, 4 s supervision timeout
        s.client->setConnectTimeout(5);
    }
    NimBLEScan *scan = NimBLEDevice::getScan();
    scan->setAdvertisedDeviceCallbacks(&g_adv_cb, false);
    scan->setActiveScan(true);
    scan->setInterval(97);
    scan->setWindow(37);  // leave radio time for Wi-Fi coexistence (must be measured, paper 3.3.7)
    scan->setMaxResults(0);
    scan->start(0, nullptr, false);

    g_web.on("/", HTTP_GET, [] { g_web.send_P(200, "text/html; charset=utf-8", kGatewayPage); });
    g_web.on("/api/records", HTTP_GET, handle_records);
    g_web.on("/records.csv", HTTP_GET, handle_csv);
    g_web.begin();
}

void loop() {
    uint32_t now = millis();
    RxItem it;
    for (int k = 0; k < 8 && xQueueReceive(g_rxq, &it, 0) == pdTRUE; ++k) process_rx(it);

    for (size_t i = 0; i < kSlots; ++i) {
        Slot &s = g_slot[i];
        if (!s.disconnect_pending) continue;
        s.disconnect_pending = false;
        umsf::LinkEvent le;
        if (s.enrolled >= 0 && g_links.on_disconnect(s.enrolled, now, le))
            emit_gw_event(le.type, UMSF_LVL_WARNING, le.value_x1000, s.enrolled, (uint16_t)g_node[s.enrolled].last_seq);
        s.enrolled = -1;
    }
    if ((uint32_t)(now - t_tick) >= 100) {
        t_tick = now;
        umsf::LinkEvent ev[4];
        size_t n = g_links.tick(now, ev, 4);
        for (size_t i = 0; i < n; ++i)
            emit_gw_event(ev[i].type, UMSF_LVL_WARNING, ev[i].value_x1000, ev[i].node, (uint16_t)g_node[ev[i].node].last_seq);
    }

    if (g_pending_idx >= 0) {
        connect_node(g_pending_idx);
        g_pending_idx = -1;
    }
    bool free_slot = false;
    for (auto &s : g_slot) free_slot |= !s.connected;
    if (free_slot && g_pending_idx < 0 && !NimBLEDevice::getScan()->isScanning())
        NimBLEDevice::getScan()->start(0, nullptr, false);

    handle_site_acks();
    if (t_mqtt != UINT32_MAX && WiFi.status() == WL_CONNECTED && g_synced && !g_mqtt.connected() &&
        (uint32_t)(now - t_mqtt) >= 5000) {
        t_mqtt = now;
        g_mqtt.connect();
    }
    publish_pending();

    g_evict_pending += g_buf.take_eviction_report();
    if (g_evict_pending && (uint32_t)(now - t_evict) >= 60000) {
        emit_gw_event(UMSF_EV_BUFFER_EVICTION, UMSF_LVL_WARNING, (int32_t)g_evict_pending * 1000, -1, 0);
        g_evict_pending = 0;
        t_evict = now;
    }
    if ((uint32_t)(now - t_status) >= 30000) {
        t_status = now;
        publish_gw_status();
    }
    g_web.handleClient();
}
