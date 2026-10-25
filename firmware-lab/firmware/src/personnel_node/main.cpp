// Personnel node (ESP32 DevKit): MAX30102 PPG + DS18B20 contact temperature + MPU6050 motion +
// help button (+ optional Grove GSR). One PHYSIO_FEATURE record per 10 s window over BLE.
//
// Release 1.0.0: UNTESTED on hardware and NOT compiled (no ESP32 toolchain in the build
// environment). Portable logic (framing, buffer, features) is host-tested in test/host.
// Not a medical device: HR is null unless the bench synthetic test field is enabled (flagged
// HR_SYNTHETIC) or the UNVALIDATED estimator is explicitly enabled; SpO2 is always null.
#include <Arduino.h>
#include <DallasTemperature.h>
#include <OneWire.h>
#include <Preferences.h>
#include <Wire.h>

#include "MAX30105.h"  // SparkFun MAX3010x library (MAX30102 compatible)
#include "mpu6050_min.h"
#include "node_link.h"
#include "umsf_features.h"
#include "umsf_hw.h"
#include "umsf_proto.h"
#include "umsf_text.h"

#ifndef UMSF_DEVICE_ID
#define UMSF_DEVICE_ID "A01"
#endif
#ifndef UMSF_PASSKEY
#define UMSF_PASSKEY 123456
#endif
#ifndef UMSF_HAS_GSR
#define UMSF_HAS_GSR 0  // optional channel (Table 4); a floating ADC must not be reported as data
#endif

namespace {
umsf::RuleConfig g_cfg;
umsf::PhysioWindow g_win(g_cfg);
umsf::SosButton g_button(g_cfg);
NodeLink<umsf::kNodeBufferRecords> g_link;

MAX30105 g_ppg;
OneWire g_ow(pins::DS18B20);
DallasTemperature g_ds(&g_ow);
Mpu6050 g_imu;
bool g_ppg_ok = false, g_imu_ok = false, g_ds_ok = false;

uint16_t g_boot = 0;
uint32_t g_seq = 0;         // per-boot sequence shared by telemetry and events (cumulative ACK)
uint32_t g_last_tel_seq = 0;
uint32_t g_window_index = 0;
uint16_t g_zone = 0;
uint32_t t_win = 0, t_imu = 0, t_temp = 0, t_gsr = 0, t_status = 0, t_evict = 0;
uint32_t g_evict_pending = 0;

void load_config() {
    Preferences p;
    p.begin("umsf", true);
    g_zone = p.getUShort("zone", 0);
    g_cfg.feature_window_ms = p.getUShort("win", 10000);
    g_cfg.synthetic_hr_enabled = p.getBool("synhr", false);
    p.end();
}

void on_config(const umsf_config_t &c) {
    // CONFIG arrives only over an encrypted, bonded link. Record the change: the paper requires the
    // configuration to be frozen after commissioning, so changes are logged for the audit trail.
    if (c.feature_window_ms < 1000 || c.feature_window_ms > 60000) return;
    g_zone = c.zone_code;
    g_cfg.feature_window_ms = c.feature_window_ms;
    g_cfg.synthetic_hr_enabled = c.synthetic_hr_enabled != 0;
    Preferences p;
    p.begin("umsf", false);
    p.putUShort("zone", g_zone);
    p.putUShort("win", g_cfg.feature_window_ms);
    p.putBool("synhr", g_cfg.synthetic_hr_enabled);
    p.end();
    Serial.printf("CFG,%s,%u,zone=%u,win=%u,synhr=%u,profile=%u\n", UMSF_DEVICE_ID, g_boot, g_zone,
                  g_cfg.feature_window_ms, c.synthetic_hr_enabled, c.sample_profile);
}

void emit_event(uint8_t type, uint8_t level, int32_t value_x1000, uint32_t now) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_EVENT, UMSF_DEVICE_ID, g_boot, ++g_seq, now);
    f.u.event = umsf_event_t{type, level, value_x1000, g_cfg.rule_version, g_zone, (uint16_t)g_last_tel_seq};
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    uint8_t prio = level >= UMSF_LVL_URGENT ? umsf::PRIO_URGENT : umsf::PRIO_EVENT;
    g_link.enqueue(b, n, g_seq, prio, now);
    char line[128];
    if (umsf_text_line("NODE", now, &f, line, sizeof line) > 0) Serial.println(line);
}

void finish_window(uint32_t now) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, UMSF_DEVICE_ID, g_boot, ++g_seq, now);
    if (!g_ppg_ok) g_win.ppg_missing();
    f.u.physio = g_win.finish(g_cfg.feature_window_ms, UMSF_NULL_U8 /* no battery sense wired */,
                              g_button.active(), UMSF_FW_BUILD, g_seq);
    g_last_tel_seq = g_seq;
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    g_link.enqueue(b, n, g_seq, umsf::PRIO_TELEMETRY, now);
    // planned-slot ledger line (paper A.2): window index -> identity, for an external logger
    Serial.printf("SLOT,%s,%u,%lu,%lu,%lu\n", UMSF_DEVICE_ID, g_boot, (unsigned long)g_seq, (unsigned long)now,
                  (unsigned long)g_window_index++);
    char line[128];
    if (umsf_text_line("NODE", now, &f, line, sizeof line) > 0) Serial.println(line);
    g_win.reset();
}

void send_status(uint32_t now) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    // STATUS is a snapshot, not a record: it reuses the last allocated sequence number
    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_STATUS, UMSF_DEVICE_ID, g_boot, g_seq, now);
    umsf_status_set_null(&f.u.status);
    auto &buf = g_link.buffer();
    f.u.status.buffered_records = (uint8_t)buf.size();
    f.u.status.evicted_total = (uint16_t)(buf.evicted_total() > 0xFFFF ? 0xFFFF : buf.evicted_total());
    f.u.status.sent_total = buf.sent_total();
    f.u.status.acked_up_to_seq = g_link.acked_up_to();
    f.u.status.fw_build = UMSF_FW_BUILD;
    f.u.status.sensor_flags = (g_ds_ok ? UMSF_CH_T : 0) | (g_ppg_ok ? UMSF_CH_PPG : 0) | (g_imu_ok ? UMSF_CH_MOTION : 0) |
                              (UMSF_HAS_GSR ? UMSF_CH_GSR : 0);
    int8_t rssi = g_link.last_rssi();
    f.u.status.rssi_neg = rssi < 0 ? (uint8_t)(-rssi) : UMSF_NULL_U8;
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    g_link.notify_status(b, n);
}
}  // namespace

void setup() {
    Serial.begin(115200);
    pinMode(pins::BUTTON, INPUT_PULLUP);
    pinMode(pins::STATUS_LED, OUTPUT);
    delay(50);
    bool enroll = digitalRead(pins::BUTTON) == LOW;  // hold help button at power-up = enrollment mode
    g_boot = umsf_next_boot_id();
    load_config();
    Serial.printf("# UMSF personnel node %s boot %u fw %u rule_version %u\n", UMSF_DEVICE_ID, g_boot, UMSF_FW_BUILD,
                  g_cfg.rule_version);
    Serial.println("# RAM buffer only: unacknowledged records are lost on reset/power loss");

    Wire.begin(pins::I2C_SDA, pins::I2C_SCL, 400000);
    g_ppg_ok = g_ppg.begin(Wire, I2C_SPEED_FAST, 0x57);
    if (g_ppg_ok) {
        // LED 0x1F (~6.4 mA), no averaging, ledMode 2 = red + IR, 100 samples/s, 411 us, ADC range 16384
        g_ppg.setup(0x1F, 1, 2, 100, 411, 16384);
    }
    g_imu_ok = g_imu.begin(Wire, 0x68, Mpu6050::A4G, Mpu6050::G500, 25, 4);  // 25 Hz, ~20 Hz DLPF
    g_ds.begin();
    g_ds_ok = g_ds.getDeviceCount() > 0;
    g_ds.setResolution(12);
    g_ds.setWaitForConversion(false);  // 750 ms conversion, read once per second
    g_ds.requestTemperatures();
#if UMSF_HAS_GSR
    analogSetPinAttenuation(pins::GSR, ADC_11db);
#endif
    Serial.printf("# sensors: max30102=%d mpu6050=%d ds18b20=%d gsr=%d\n", g_ppg_ok, g_imu_ok, g_ds_ok, UMSF_HAS_GSR);

    g_link.set_boot_id(g_boot);
    g_link.set_config_handler(on_config);
    g_link.begin(UMSF_DEVICE_ID, UMSF_SRC_PERSONNEL, UMSF_PASSKEY, false, enroll);
    uint32_t now = millis();
    t_win = t_imu = t_temp = t_gsr = t_status = now;
}

void loop() {
    uint32_t now = millis();

    if (g_ppg_ok) {  // drain MAX30102 FIFO (32 samples deep = 320 ms at 100 Hz)
        g_ppg.check();
        while (g_ppg.available()) {
            g_win.add_ppg(g_ppg.getFIFORed(), g_ppg.getFIFOIR());
            g_ppg.nextSample();
        }
    }
    if ((uint32_t)(now - t_imu) >= 40) {  // 25 Hz
        t_imu += 40;
        float x, y, z;
        bool sat;
        if (g_imu_ok && g_imu.read_accel_mg(x, y, z, sat)) g_win.add_accel_mg(x, y, z);
        else g_win.imu_error();
    }
    if ((uint32_t)(now - t_temp) >= 1000) {  // 1 Hz
        t_temp += 1000;
        float c = g_ds.getTempCByIndex(0);
        // -127 = disconnected; 85.0 = power-on reset value (conversion not done)
        if (c == DEVICE_DISCONNECTED_C || c < -55.0f || c > 125.0f || c == 85.0f) g_win.temp_error();
        else g_win.add_temp_c100((int16_t)lroundf(c * 100.0f));
        g_ds.requestTemperatures();
    }
#if UMSF_HAS_GSR
    if ((uint32_t)(now - t_gsr) >= 100) {  // 10 Hz, ADC millivolts (not conductance)
        t_gsr += 100;
        g_win.add_gsr_mv((uint16_t)analogReadMilliVolts(pins::GSR));
    }
#endif
    switch (g_button.update(digitalRead(pins::BUTTON) == LOW, now)) {
    case umsf::SosButton::RAISED:
        emit_event(UMSF_EV_HELP_REQUEST, UMSF_LVL_URGENT, 1000, now);
        break;
    case umsf::SosButton::RESET:
        emit_event(UMSF_EV_SOS_RESET, UMSF_LVL_INFO, 1000, now);
        break;
    default:
        break;
    }
    if ((uint32_t)(now - t_win) >= g_cfg.feature_window_ms) {
        t_win += g_cfg.feature_window_ms;
        finish_window(now);
    }
    // explicit eviction event, aggregated: the event itself occupies a slot, so at most one per 60 s
    g_evict_pending += g_link.buffer().take_eviction_report();
    if (g_evict_pending && (uint32_t)(now - t_evict) >= 60000) {
        Serial.printf("EVICT,%s,%u,%lu,last_seq=%lu\n", UMSF_DEVICE_ID, g_boot, (unsigned long)g_evict_pending,
                      (unsigned long)g_link.buffer().last_evicted_seq());
        emit_event(UMSF_EV_BUFFER_EVICTION, UMSF_LVL_WARNING, (int32_t)g_evict_pending * 1000, now);
        g_evict_pending = 0;
        t_evict = now;
    }
    if ((uint32_t)(now - t_status) >= 30000) {
        t_status = now;
        send_status(now);
    }
    g_link.loop(now);
    digitalWrite(pins::STATUS_LED, g_button.active() ? ((now / 250) & 1) : g_link.ready());
}
