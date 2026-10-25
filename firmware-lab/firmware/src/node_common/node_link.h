// node_link.h - BLE GATT peripheral shared by the personnel and stationary nodes.
//
// NimBLE-Arduino 1.4.x API (h2zero/NimBLE-Arduino@1.4.3). UNTESTED on hardware in release 1.0.0.
//
// - One service, six characteristics (protocol 1); COMPACT only when enabled (stationary).
// - LE Secure Connections + bonding + MITM (static passkey shown at enrollment). New bonds are
//   accepted only in enrollment mode (no bonds yet, or button held at boot); otherwise unknown
//   peers are disconnected. Nothing is notified before the link is encrypted.
// - Reliable records (telemetry + events) live in a RecordBuffer until an application ACK
//   (written by the gateway after site-agent COMMIT) releases them. EVENT frames go first.
// - Every TELEMETRY/EVENT notification carries the 4-byte fragment header.
// - Advertising: name "UMSF-<id>" and manufacturer data 0xFFFF + source_class only.
#pragma once
#include <Arduino.h>
#include <NimBLEDevice.h>

#include "umsf_buffer.h"
#include "umsf_frag.h"
#include "umsf_hw.h"
#include "umsf_proto.h"

template <size_t CAP>
class NodeLink : public NimBLEServerCallbacks, public NimBLECharacteristicCallbacks {
public:
    using Buffer = umsf::RecordBuffer<CAP, UMSF_MAX_FRAME_LEN>;
    using ConfigFn = void (*)(const umsf_config_t &);

    static constexpr uint32_t kAckTimeoutMs = 60000;  // retransmit unacked records after 60 s
    static constexpr uint32_t kSendSpacingMs = 15;    // pace notifications (notify() returns no status in 1.4)

    void begin(const char *device_id, uint8_t source_class, uint32_t passkey, bool with_compact, bool enrollment_mode) {
        strncpy(id_, device_id, 4);
        source_class_ = source_class;
        enroll_ = enrollment_mode;
        char name[12];
        snprintf(name, sizeof name, "UMSF-%s", id_);
        NimBLEDevice::init(name);
        NimBLEDevice::setMTU(kRequestedMtu);
        NimBLEDevice::setPower(ESP_PWR_LVL_P9);
        NimBLEDevice::setSecurityAuth(true, true, true);          // bonding, MITM, Secure Connections
        NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);   // node "displays" its static passkey
        NimBLEDevice::setSecurityPasskey(passkey);
        if (enroll_ == false && NimBLEDevice::getNumBonds() == 0) enroll_ = true;

        srv_ = NimBLEDevice::createServer();
        srv_->setCallbacks(this, false);
        NimBLEService *svc = srv_->createService(uuids::SERVICE);
        tel_ = svc->createCharacteristic(uuids::TELEMETRY, NIMBLE_PROPERTY::NOTIFY);
        evt_ = svc->createCharacteristic(uuids::EVENT, NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::INDICATE);
        ack_ = svc->createCharacteristic(uuids::ACK, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC | NIMBLE_PROPERTY::WRITE_AUTHEN);
        sta_ = svc->createCharacteristic(uuids::STATUS, NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::READ_ENC |
                                                            NIMBLE_PROPERTY::READ_AUTHEN | NIMBLE_PROPERTY::NOTIFY);
        cfg_ = svc->createCharacteristic(uuids::CONFIG, NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_ENC | NIMBLE_PROPERTY::WRITE_AUTHEN);
        if (with_compact) cmp_ = svc->createCharacteristic(uuids::COMPACT, NIMBLE_PROPERTY::NOTIFY);
        tel_->setCallbacks(this);
        evt_->setCallbacks(this);
        ack_->setCallbacks(this);
        cfg_->setCallbacks(this);
        svc->start();

        NimBLEAdvertising *adv = NimBLEDevice::getAdvertising();
        NimBLEAdvertisementData ad, sr;
        ad.setFlags(BLE_HS_ADV_F_DISC_GEN | BLE_HS_ADV_F_BREDR_UNSUP);
        ad.setCompleteServices(NimBLEUUID(uuids::SERVICE));
        const char mfg[3] = {(char)0xFF, (char)0xFF, (char)source_class};  // company 0xFFFF + class only
        ad.setManufacturerData(std::string(mfg, 3));
        sr.setName(name);
        adv->setAdvertisementData(ad);
        adv->setScanResponseData(sr);
        adv->start();
        Serial.printf("# BLE %s up, enrollment=%d, bonds=%d\n", name, enroll_, NimBLEDevice::getNumBonds());
    }

    void set_config_handler(ConfigFn f) { on_config_ = f; }
    Buffer &buffer() { return buf_; }
    bool ready() const { return connected_ && encrypted_; }
    uint32_t acked_up_to() const { return acked_up_to_; }
    uint16_t boot_id() const { return boot_id_; }
    void set_boot_id(uint16_t b) { boot_id_ = b; }
    int8_t last_rssi() {
        if (!connected_) return 0;
        int8_t rssi = 0;
        return ble_gap_conn_rssi(conn_handle_, &rssi) == 0 ? rssi : 0;
    }

    // Queue a reliable record (encoded frame). Returns false only if the frame is malformed.
    bool enqueue(const uint8_t *frame, size_t len, uint32_t seq, uint8_t prio, uint32_t now) {
        auto r = buf_.push(0, boot_id_, seq, prio, frame, len, now);
        return r != Buffer::PUSH_TOO_LONG;
    }

    void notify_status(const uint8_t *frame, size_t len) {
        sta_->setValue(frame, len);
        if (ready()) sta_->notify();
    }
    void notify_compact(const uint8_t pkt[UMSF_COMPACT_LEN]) {
        if (cmp_ && ready()) cmp_->notify(pkt, UMSF_COMPACT_LEN);
    }

    // Call from loop(): applies ACK/CONFIG writes, handles reconnect resend and paced transmission.
    void loop(uint32_t now) {
        uint16_t aboot;
        uint32_t aseq;
        if (take_ack(aboot, aseq)) {
            size_t n = buf_.ack(0, aboot, aseq);
            if (aboot == boot_id_ && aseq > acked_up_to_) acked_up_to_ = aseq;
            // ACK witness line (paper A.2): logged by an external serial logger outside the failed host
            Serial.printf("ACKW,%s,%u,%lu,%lu,%u\n", id_, aboot, (unsigned long)aseq, (unsigned long)now, (unsigned)n);
        }
        umsf_config_t c;
        if (take_config(c) && on_config_) on_config_(c);
        if (resend_all_) {
            resend_all_ = false;
            buf_.reset_sent();
        }
        buf_.requeue_stale(now, kAckTimeoutMs);
        if (!ready() || (uint32_t)(now - last_send_) < kSendSpacingMs) return;
        auto *e = buf_.next_to_send();
        if (!e) return;
        bool is_event = e->len > 3 && e->data[3] == UMSF_FT_EVENT;
        if (!(is_event ? evt_sub_ : tel_sub_)) return;  // gateway not subscribed yet
        send_fragmented(is_event ? evt_ : tel_, e->data, e->len);
        buf_.mark_sent(e, now);
        last_send_ = now;
    }

    // ---- NimBLE callbacks (run in the NimBLE host task) ----
    void onConnect(NimBLEServer *s, ble_gap_conn_desc *desc) override {
        NimBLEAddress peer(desc->peer_id_addr);
        if (!enroll_ && !NimBLEDevice::isBonded(peer)) {  // allowlist = bonded gateways only
            Serial.printf("# reject unbonded peer %s\n", peer.toString().c_str());
            s->disconnect(desc->conn_handle);
            return;
        }
        conn_handle_ = desc->conn_handle;
        connected_ = true;
        encrypted_ = false;
        att_payload_ = 20;
        NimBLEDevice::startSecurity(desc->conn_handle);  // node requests pairing/encryption at once
    }
    void onDisconnect(NimBLEServer *, ble_gap_conn_desc *) override {
        connected_ = encrypted_ = tel_sub_ = evt_sub_ = false;
        NimBLEDevice::startAdvertising();
    }
    void onMTUChange(uint16_t mtu, ble_gap_conn_desc *) override { att_payload_ = mtu > 3 ? mtu - 3 : 20; }
    uint32_t onPassKeyRequest() override { return 0; }  // not used with DISPLAY_ONLY
    bool onConfirmPIN(uint32_t) override { return false; }
    void onAuthenticationComplete(ble_gap_conn_desc *desc) override {
        if (!desc->sec_state.encrypted || !desc->sec_state.authenticated) {
            Serial.println("# pairing failed or not MITM-protected: disconnect");
            NimBLEDevice::getServer()->disconnect(desc->conn_handle);
            return;
        }
        encrypted_ = true;
        resend_all_ = true;  // reconnect: everything unacked is sent again (gateway dedups)
    }
    void onSubscribe(NimBLECharacteristic *c, ble_gap_conn_desc *, uint16_t sub) override {
        if (c == tel_) tel_sub_ = sub != 0;
        if (c == evt_) evt_sub_ = sub != 0;
        if (sub) resend_all_ = true;
    }
    void onWrite(NimBLECharacteristic *c, ble_gap_conn_desc *desc) override {
        if (!desc->sec_state.encrypted) return;
        NimBLEAttValue v = c->getValue();
        umsf_frame_t f;
        if (umsf_decode(v.data(), v.length(), &f) != UMSF_OK || f.hdr.source_class != UMSF_SRC_GATEWAY) {
            ++rejected_writes_;
            return;
        }
        portENTER_CRITICAL(&mux_);
        if (c == ack_ && f.hdr.frame_type == UMSF_FT_ACK) {
            pend_ack_boot_ = f.u.ack.target_boot_id;
            pend_ack_seq_ = f.u.ack.ack_up_to_seq;
            pend_ack_ = true;
        } else if (c == cfg_ && f.hdr.frame_type == UMSF_FT_CONFIG) {
            pend_cfg_ = f.u.config;
            pend_cfg_set_ = true;
        }
        portEXIT_CRITICAL(&mux_);
    }

    uint32_t rejected_writes() const { return rejected_writes_; }

private:
    void send_fragmented(NimBLECharacteristic *ch, const uint8_t *msg, size_t len) {
        uint8_t n[UMSF_FRAG_HDR_LEN + 244];
        size_t att = att_payload_ > 244 ? 244 : att_payload_;
        unsigned cnt = umsf_frag_count(len, att);
        uint16_t id = msg_id_++;
        for (unsigned i = 0; i < cnt; ++i) {
            size_t k = umsf_frag_build(msg, len, id, i, att, n, sizeof n);
            if (k) ch->notify(n, k);
        }
    }
    bool take_ack(uint16_t &b, uint32_t &s) {
        portENTER_CRITICAL(&mux_);
        bool p = pend_ack_;
        b = pend_ack_boot_;
        s = pend_ack_seq_;
        pend_ack_ = false;
        portEXIT_CRITICAL(&mux_);
        return p;
    }
    bool take_config(umsf_config_t &c) {
        portENTER_CRITICAL(&mux_);
        bool p = pend_cfg_set_;
        c = pend_cfg_;
        pend_cfg_set_ = false;
        portEXIT_CRITICAL(&mux_);
        return p;
    }

    char id_[5] = {0};
    uint8_t source_class_ = 0;
    bool enroll_ = false;
    NimBLEServer *srv_ = nullptr;
    NimBLECharacteristic *tel_ = nullptr, *evt_ = nullptr, *ack_ = nullptr, *sta_ = nullptr, *cfg_ = nullptr, *cmp_ = nullptr;
    volatile bool connected_ = false, encrypted_ = false, tel_sub_ = false, evt_sub_ = false, resend_all_ = false;
    volatile uint16_t att_payload_ = 20;
    uint16_t conn_handle_ = 0;
    uint16_t msg_id_ = 1;
    uint16_t boot_id_ = 0;
    uint32_t last_send_ = 0;
    uint32_t acked_up_to_ = 0;
    uint32_t rejected_writes_ = 0;
    Buffer buf_;
    ConfigFn on_config_ = nullptr;
    portMUX_TYPE mux_ = portMUX_INITIALIZER_UNLOCKED;
    bool pend_ack_ = false, pend_cfg_set_ = false;
    uint16_t pend_ack_boot_ = 0;
    uint32_t pend_ack_seq_ = 0;
    umsf_config_t pend_cfg_{};
};
