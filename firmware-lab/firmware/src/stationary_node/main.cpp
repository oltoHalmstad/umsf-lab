// Stationary building-state node (ESP32 DevKit), after the Stage-2 bench node:
// MPU6050 (200 Hz, +-16 g impact capture), BMP280 pressure/temperature, MQ-2 analog gas channel,
// analog microphone peak-to-peak, PIR, SOS button. 1 s STATION_STATE + 200 ms COMPACT + immediate
// EVENT frames over BLE; local soft-AP page at http://192.168.4.1 with cards and an event log.
//
// Release 1.0.0: UNTESTED on hardware and NOT compiled. The Stage-2 bench values were not
// calibrated: thresholds are engineering defaults, the MQ-2 channel is an uncalibrated voltage,
// mechanical values do not measure structural damage, and PIR/sound are cues of *possible
// presence*, not vital signs. possible_impact_local is unverified and never a strike attribution.
#include <Adafruit_BMP280.h>
#include <Arduino.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <Wire.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#include "secrets.example.h"
#endif
#include "mpu6050_min.h"
#include "node_link.h"
#include "station_page.h"
#include "umsf_features.h"
#include "umsf_hw.h"
#include "umsf_proto.h"
#include "umsf_text.h"

#ifndef UMSF_DEVICE_ID
#define UMSF_DEVICE_ID "S01"
#endif
#ifndef UMSF_NODE_INDEX
#define UMSF_NODE_INDEX 1
#endif
#ifndef UMSF_PASSKEY
#define UMSF_PASSKEY 654321
#endif

namespace {
constexpr float kMq2DividerRatio = 1.5f;  // AO -> 10 k / 20 k divider -> GPIO35; report AO voltage
constexpr size_t kStationBuffer = 64;     // 64 s of 1 s records (+ events); RAM only

umsf::RuleConfig g_cfg;
umsf::StationDetector g_det(g_cfg);
umsf::SosButton g_button(g_cfg);
NodeLink<kStationBuffer> g_link;
Mpu6050 g_imu;
Adafruit_BMP280 g_bmp(&Wire);
WebServer g_web(80);
SemaphoreHandle_t g_mtx;
QueueHandle_t g_station_q, g_event_q;
volatile bool g_sos_active = false;
bool g_imu_ok = false, g_bmp_ok = false;

uint16_t g_boot = 0, g_zone = 1, g_compact_seq = 0;
uint32_t g_seq = 0, g_last_state_seq = 0, g_window_index = 0;
uint32_t g_evict_pending = 0, t_evict = 0, t_status = 0;

struct Live {  // latest values for COMPACT and the web page (guarded by g_mtx)
    umsf_compact_t compact;
    umsf_station_t last_state;
    uint32_t last_state_ms;
    bool has_state;
} g_live;

struct StateItem { umsf_station_t s; uint32_t t; };

struct LogEntry { uint32_t t_ms; uint8_t type, level; int32_t value; bool operator_action; };
LogEntry g_log[24];
size_t g_log_n = 0, g_log_head = 0;

void log_event(uint32_t t, uint8_t type, uint8_t level, int32_t v, bool op) {
    g_log[(g_log_head + g_log_n) % 24] = LogEntry{t, type, level, v, op};
    if (g_log_n < 24) ++g_log_n; else g_log_head = (g_log_head + 1) % 24;
}

// ------------------------------------------------------------------ sensor task (core 1)
void sensor_task(void *) {
    TickType_t last = xTaskGetTickCount();
    uint32_t tick = 0, t_window = millis();
    for (;;) {
        vTaskDelayUntil(&last, pdMS_TO_TICKS(1));  // 1 kHz base tick (configTICK_RATE_HZ = 1000)
        uint32_t now = millis();
        xSemaphoreTake(g_mtx, portMAX_DELAY);
        g_det.add_mic(now, (uint16_t)analogRead(pins::MIC));
        if (tick % 5 == 0 && g_imu_ok) {  // 200 Hz
            float x, y, z;
            bool sat;
            if (g_imu.read_accel_mg(x, y, z, sat)) g_det.add_accel_mg(now, x, y, z, sat);
        }
        if (tick % 40 == 0 && g_bmp_ok) {  // 25 Hz
            float t = g_bmp.readTemperature(), p = g_bmp.readPressure();
            if (!isnan(p) && p > 30000.0f && p < 110000.0f) g_det.add_pressure(now, p, t);
        }
        if (tick % 100 == 0) g_det.add_gas_mv(now, (uint16_t)(analogReadMilliVolts(pins::MQ2) * kMq2DividerRatio));
        if (tick % 10 == 0) g_det.add_pir(now, digitalRead(pins::PIR) == HIGH);
        g_det.set_sos(g_sos_active);
        g_det.tick(now);
        if (tick % 200 == 0) {  // COMPACT snapshot every 200 ms
            umsf_compact_t &c = g_live.compact;
            c.magic = UMSF_COMPACT_MAGIC;
            c.node_index = UMSF_NODE_INDEX;
            c.seq = ++g_compact_seq;
            c.vib_peak_cg = g_det.live_vib_peak_cg();
            c.tilt_ddeg = g_det.last_tilt_ddeg();
            c.pressure_dhpa = g_det.last_pressure_dhpa();
            c.temp = g_det.last_temp_c100();
            c.gas_mv = g_det.last_gas_mv();
            c.sound_index = g_det.live_sound_index();
            c.flags = g_det.live_flags();
            c.battery_pct = UMSF_NULL_U8;
            g_det.reset_live();
        }
        if ((uint32_t)(now - t_window) >= g_cfg.station_window_ms) {
            t_window += g_cfg.station_window_ms;
            umsf_station_t s = g_det.finish_window(now, g_zone, UMSF_FW_BUILD, UMSF_NULL_U8);
            StateItem item{s, now};
            xQueueSend(g_station_q, &item, 0);
        }
        umsf::DetectedEvent e;
        while (g_det.pop_event(e)) xQueueSend(g_event_q, &e, 0);
        xSemaphoreGive(g_mtx);
        ++tick;
    }
}

// ------------------------------------------------------------------ framing (loop context)
void emit_event(uint8_t type, uint8_t level, int32_t value, uint32_t t, bool op = false) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_STATIONARY, UMSF_FT_EVENT, UMSF_DEVICE_ID, g_boot, ++g_seq, t);
    f.u.event = umsf_event_t{type, level, value, g_cfg.rule_version, g_zone, (uint16_t)g_last_state_seq};
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    g_link.enqueue(b, n, g_seq, level >= UMSF_LVL_URGENT ? umsf::PRIO_URGENT : umsf::PRIO_EVENT, millis());
    log_event(t, type, level, value, op);
    char line[128];
    if (umsf_text_line("NODE", millis(), &f, line, sizeof line) > 0) Serial.println(line);
}

void emit_state(const umsf_station_t &s, uint32_t t) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_STATIONARY, UMSF_FT_STATION_STATE, UMSF_DEVICE_ID, g_boot, ++g_seq, t);
    f.u.station = s;
    g_last_state_seq = g_seq;
    uint8_t b[UMSF_MAX_FRAME_LEN];
    size_t n = umsf_encode(&f, b, sizeof b);
    g_link.enqueue(b, n, g_seq, umsf::PRIO_TELEMETRY, millis());
    Serial.printf("SLOT,%s,%u,%lu,%lu,%lu\n", UMSF_DEVICE_ID, g_boot, (unsigned long)g_seq, (unsigned long)t,
                  (unsigned long)g_window_index++);
}

void send_status(uint32_t now) {
    umsf_frame_t f;
    memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_STATIONARY, UMSF_FT_STATUS, UMSF_DEVICE_ID, g_boot, g_seq, now);
    umsf_status_set_null(&f.u.status);
    auto &buf = g_link.buffer();
    f.u.status.buffered_records = (uint8_t)buf.size();
    f.u.status.evicted_total = (uint16_t)(buf.evicted_total() > 0xFFFF ? 0xFFFF : buf.evicted_total());
    f.u.status.sent_total = buf.sent_total();
    f.u.status.acked_up_to_seq = g_link.acked_up_to();
    f.u.status.fw_build = UMSF_FW_BUILD;
    xSemaphoreTake(g_mtx, portMAX_DELAY);
    f.u.status.sensor_flags = g_live.has_state ? g_live.last_state.sensor_flags : 0;
    xSemaphoreGive(g_mtx);
    int8_t rssi = g_link.last_rssi();
    f.u.status.rssi_neg = rssi < 0 ? (uint8_t)(-rssi) : UMSF_NULL_U8;
    uint8_t b[UMSF_MAX_FRAME_LEN];
    g_link.notify_status(b, umsf_encode(&f, b, sizeof b));
}

// ------------------------------------------------------------------ web page (192.168.4.1)
bool pin_ok() { return g_web.hasArg("pin") && g_web.arg("pin") == UMSF_OPERATOR_PIN; }

void add_u16(String &s, const char *k, uint16_t v, int dec) {
    s += '"'; s += k; s += "\":";
    if (v == UMSF_NULL_U16) s += "null"; else s += String(v / pow(10, dec), dec);
    s += ',';
}
void add_i16(String &s, const char *k, int16_t v, int dec) {
    s += '"'; s += k; s += "\":";
    if (v == UMSF_NULL_I16) s += "null"; else s += String(v / pow(10, dec), dec);
    s += ',';
}

void handle_state() {
    uint32_t now = millis();
    umsf_station_t st;
    uint32_t st_ms;
    bool has;
    xSemaphoreTake(g_mtx, portMAX_DELAY);
    st = g_live.last_state;
    st_ms = g_live.last_state_ms;
    has = g_live.has_state;
    bool warm = g_det.gas_warm(), base = g_det.has_tilt_baseline();
    xSemaphoreGive(g_mtx);
    String s;
    s.reserve(2048);
    s += "{\"device_id\":\"" UMSF_DEVICE_ID "\",\"boot_id\":" + String(g_boot) + ",\"uptime_ms\":" + String(now) +
         ",\"ble_ready\":" + (g_link.ready() ? "true" : "false") + ",\"buffered\":" + String(g_link.buffer().size()) +
         ",\"evicted_total\":" + String(g_link.buffer().evicted_total()) + ",\"rule_version\":" +
         String(g_cfg.rule_version) + ",\"zone\":" + String(g_zone) + ",";
    s += "\"state_age_ms\":";
    s += has ? String(now - st_ms) : String("null");
    s += ",\"cards\":{";
    if (has) {
        add_u16(s, "vib_peak_g", st.vib_peak_cg, 2);
        add_i16(s, "tilt_deg", st.tilt_ddeg, 1);
        add_i16(s, "tilt_delta_deg", st.tilt_delta_ddeg, 1);
        add_u16(s, "pressure_hpa", st.pressure_dhpa, 1);
        add_i16(s, "temp_c", st.temp, 2);
        add_u16(s, "gas_v", st.gas_mv, 3);
        add_u16(s, "gas_baseline_v", st.gas_baseline_mv, 3);
        add_u16(s, "sound_index", st.sound_index, 0);
        s += "\"flags\":" + String(st.flags) + ",\"sensor_flags\":" + String(st.sensor_flags) +
             ",\"quality_pct\":" + String(st.quality_pct) + ",";
    }
    s += "\"gas_warm\":" + String(warm ? "true" : "false") + ",\"tilt_baseline\":" + String(base ? "true" : "false") +
         ",\"sos\":" + String(g_button.active() ? "true" : "false") + "},\"events\":[";
    for (size_t i = 0; i < g_log_n; ++i) {
        const LogEntry &e = g_log[(g_log_head + g_log_n - 1 - i) % 24];  // newest first
        if (i) s += ',';
        s += "{\"age_ms\":" + String(now - e.t_ms) + ",\"type\":\"" + umsf_event_type_name(e.type) +
             "\",\"level\":" + String(e.level) + ",\"value\":" + String(e.value / 1000.0, 3) +
             ",\"operator\":" + (e.operator_action ? "true" : "false") + "}";
    }
    s += "]}";
    g_web.sendHeader("Cache-Control", "no-store");
    g_web.send(200, "application/json", s);
}

void handle_sos_reset() {
    if (!pin_ok()) { g_web.send(403, "application/json", "{\"ok\":false,\"error\":\"pin\"}"); return; }
    if (g_button.operator_reset() == umsf::SosButton::RESET) {
        g_sos_active = false;
        emit_event(UMSF_EV_SOS_RESET, UMSF_LVL_INFO, 1000, millis(), true);  // operator action is logged
    }
    g_web.send(200, "application/json", "{\"ok\":true}");
}

void handle_commission() {  // capture the current gravity vector as the mounting reference
    if (!pin_ok()) { g_web.send(403, "application/json", "{\"ok\":false,\"error\":\"pin\"}"); return; }
    float x, y, z;
    xSemaphoreTake(g_mtx, portMAX_DELAY);
    bool ok = g_det.last_gravity(x, y, z);
    if (ok) g_det.set_tilt_baseline(x, y, z);
    xSemaphoreGive(g_mtx);
    if (ok) {
        Preferences p;
        p.begin("umsf", false);
        p.putFloat("bx", x); p.putFloat("by", y); p.putFloat("bz", z); p.putBool("base", true);
        p.end();
        Serial.printf("COMMISSION,%s,%u,baseline=%.1f,%.1f,%.1f\n", UMSF_DEVICE_ID, g_boot, x, y, z);
    }
    g_web.send(ok ? 200 : 409, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false,\"error\":\"no imu data\"}");
}

void on_config(const umsf_config_t &c) {
    g_zone = c.zone_code;
    Preferences p;
    p.begin("umsf", false);
    p.putUShort("zone", g_zone);
    p.end();
    Serial.printf("CFG,%s,%u,zone=%u\n", UMSF_DEVICE_ID, g_boot, g_zone);
}
}  // namespace

void setup() {
    Serial.begin(115200);
    pinMode(pins::BUTTON, INPUT_PULLUP);
    pinMode(pins::PIR, INPUT);
    pinMode(pins::STATUS_LED, OUTPUT);
    analogSetPinAttenuation(pins::MQ2, ADC_11db);
    analogSetPinAttenuation(pins::MIC, ADC_11db);
    delay(50);
    bool enroll = digitalRead(pins::BUTTON) == LOW;
    g_boot = umsf_next_boot_id();
    uint32_t now = millis();

    Wire.begin(pins::I2C_SDA, pins::I2C_SCL, 400000);
    // +-16 g for impact capture (the wearable +-4 g / 25 Hz setting is not an impact specification);
    // 200 Hz output with DLPF_CFG 2 (~94 Hz accelerometer bandwidth) as anti-aliasing below Nyquist.
    g_imu_ok = g_imu.begin(Wire, 0x68, Mpu6050::A16G, Mpu6050::G500, 200, 2);
    g_bmp_ok = g_bmp.begin(0x76) || g_bmp.begin(0x77);
    if (g_bmp_ok)  // no IIR filter so that 1 s pressure transients are not smoothed away
        g_bmp.setSampling(Adafruit_BMP280::MODE_NORMAL, Adafruit_BMP280::SAMPLING_X2, Adafruit_BMP280::SAMPLING_X16,
                          Adafruit_BMP280::FILTER_OFF, Adafruit_BMP280::STANDBY_MS_1);

    Preferences p;
    p.begin("umsf", true);
    g_zone = p.getUShort("zone", 1);
    g_det.set_mount_axis(p.getUChar("axis", 2));
    if (p.getBool("base", false)) g_det.set_tilt_baseline(p.getFloat("bx", 0), p.getFloat("by", 0), p.getFloat("bz", 1000));
    p.end();
    g_det.begin(now);
    g_det.set_sensor_ok(g_imu_ok, g_bmp_ok, true, true);  // mic/PIR have no self-test: assumed present
    Serial.printf("# UMSF stationary node %s boot %u fw %u rule_version %u imu=%d bmp=%d baseline=%d\n", UMSF_DEVICE_ID,
                  g_boot, UMSF_FW_BUILD, g_cfg.rule_version, g_imu_ok, g_bmp_ok, g_det.has_tilt_baseline());
    Serial.printf("# MQ-2 preheat lockout %lu s; values uncalibrated\n", (unsigned long)(g_cfg.gas_preheat_ms / 1000));

    g_mtx = xSemaphoreCreateMutex();
    g_station_q = xQueueCreate(4, sizeof(StateItem));
    g_event_q = xQueueCreate(16, sizeof(umsf::DetectedEvent));

    g_link.set_boot_id(g_boot);
    g_link.set_config_handler(on_config);
    g_link.begin(UMSF_DEVICE_ID, UMSF_SRC_STATIONARY, UMSF_PASSKEY, true, enroll);

    WiFi.mode(WIFI_AP);
    WiFi.softAP("UMSF-" UMSF_DEVICE_ID, UMSF_AP_PASSWORD);  // default soft-AP address 192.168.4.1
    g_web.on("/", HTTP_GET, [] { g_web.send_P(200, "text/html; charset=utf-8", kStationPage); });
    g_web.on("/api/state", HTTP_GET, handle_state);
    g_web.on("/api/sos_reset", HTTP_POST, handle_sos_reset);
    g_web.on("/api/commission", HTTP_POST, handle_commission);
    g_web.begin();
    Serial.printf("# local page http://%s/\n", WiFi.softAPIP().toString().c_str());

    xTaskCreatePinnedToCore(sensor_task, "sensors", 6144, nullptr, 3, nullptr, 1);
    t_status = now;
}

void loop() {
    uint32_t now = millis();
    switch (g_button.update(digitalRead(pins::BUTTON) == LOW, now)) {
    case umsf::SosButton::RAISED:
        g_sos_active = true;
        emit_event(UMSF_EV_SOS, UMSF_LVL_URGENT, 1000, now);
        break;
    case umsf::SosButton::RESET:  // long press on the node itself
        g_sos_active = false;
        emit_event(UMSF_EV_SOS_RESET, UMSF_LVL_INFO, 1000, now, true);
        break;
    default:
        break;
    }

    umsf::DetectedEvent e;
    while (xQueueReceive(g_event_q, &e, 0) == pdTRUE) emit_event(e.type, e.level, e.value_x1000, e.t_ms);

    StateItem item;
    while (xQueueReceive(g_station_q, &item, 0) == pdTRUE) {
        emit_state(item.s, item.t);
        xSemaphoreTake(g_mtx, portMAX_DELAY);
        g_live.last_state = item.s;
        g_live.last_state_ms = item.t;
        g_live.has_state = true;
        xSemaphoreGive(g_mtx);
    }

    static uint16_t sent_compact = 0;
    xSemaphoreTake(g_mtx, portMAX_DELAY);
    umsf_compact_t c = g_live.compact;
    xSemaphoreGive(g_mtx);
    if (c.magic == UMSF_COMPACT_MAGIC && c.seq != sent_compact) {
        uint8_t pkt[UMSF_COMPACT_LEN];
        umsf_compact_encode(&c, pkt);
        g_link.notify_compact(pkt);
        sent_compact = c.seq;
    }

    g_evict_pending += g_link.buffer().take_eviction_report();
    if (g_evict_pending && (uint32_t)(now - t_evict) >= 60000) {
        emit_event(UMSF_EV_BUFFER_EVICTION, UMSF_LVL_WARNING, (int32_t)g_evict_pending * 1000, now);
        g_evict_pending = 0;
        t_evict = now;
    }
    if ((uint32_t)(now - t_status) >= 30000) {
        t_status = now;
        send_status(now);
    }
    g_link.loop(now);
    g_web.handleClient();
    digitalWrite(pins::STATUS_LED, g_sos_active ? ((now / 250) & 1) : g_link.ready());
}
