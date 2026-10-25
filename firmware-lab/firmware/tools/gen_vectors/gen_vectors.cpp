// gen_vectors - writes protocol test vectors (test_vectors.json) and example MQTT JSON records.
//
// Usage: gen_vectors <test_vectors.json> [mqtt_samples.jsonl]
//
// Every vector is produced by encoding with lib/umsf_proto and re-decoding the bytes, so
// "expected" reflects what the codec actually reads back. Measurement fields that hold a null
// sentinel are written as JSON null; flags, counters and identifiers are raw integers.
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "umsf_json.h"
#include "umsf_proto.h"

namespace {

std::string fmt(const char *f, ...) {
    char b[512];
    va_list ap;
    va_start(ap, f);
    vsnprintf(b, sizeof b, f, ap);
    va_end(ap);
    return b;
}

struct Obj {  // ordered JSON object builder
    std::vector<std::string> kv;
    Obj &raw(const char *k, const std::string &v) { kv.push_back(fmt("\"%s\": ", k) + v); return *this; }
    Obj &num(const char *k, long long v) { return raw(k, fmt("%lld", v)); }
    Obj &str(const char *k, const char *v) { return raw(k, fmt("\"%s\"", v)); }
    Obj &boolean(const char *k, bool v) { return raw(k, v ? "true" : "false"); }
    Obj &u8n(const char *k, uint8_t v) { return v == UMSF_NULL_U8 ? raw(k, "null") : num(k, v); }
    Obj &u16n(const char *k, uint16_t v) { return v == UMSF_NULL_U16 ? raw(k, "null") : num(k, v); }
    Obj &i16n(const char *k, int16_t v) { return v == UMSF_NULL_I16 ? raw(k, "null") : num(k, v); }
    Obj &u32n(const char *k, uint32_t v) { return v == UMSF_NULL_U32 ? raw(k, "null") : num(k, v); }
    std::string s(int ind) const {
        std::string pad(ind + 2, ' '), out = "{\n";
        for (size_t i = 0; i < kv.size(); ++i) out += pad + kv[i] + (i + 1 < kv.size() ? ",\n" : "\n");
        return out + std::string(ind, ' ') + "}";
    }
};

std::string hex(const uint8_t *b, size_t n) {
    std::string h(2 * n, '0');
    umsf_hex(b, n, &h[0]);
    return h;
}

Obj header_obj(const umsf_header_t &h) {
    char id[5] = {0};
    std::memcpy(id, h.device_id, 4);
    Obj o;
    o.num("magic", h.magic).num("version", h.version).num("source_class", h.source_class)
        .num("frame_type", h.frame_type).str("device_id", id).num("boot_id", h.boot_id)
        .num("sequence", h.sequence).num("node_time_ms", h.node_time_ms);
    return o;
}

Obj payload_obj(const umsf_frame_t &f) {
    Obj o;
    switch (f.hdr.frame_type) {
    case UMSF_FT_PHYSIO_FEATURE: {
        const umsf_physio_t &p = f.u.physio;
        o.i16n("skin_temp", p.skin_temp).u16n("hr", p.hr).u16n("spo2", p.spo2).u32n("ppg_ir_mean", p.ppg_ir_mean)
            .u16n("ppg_red_mean_div16", p.ppg_red_mean_div16).u16n("ppg_valid_permille", p.ppg_valid_permille)
            .u16n("motion_rms_mg", p.motion_rms_mg).u16n("gsr_mv", p.gsr_mv).u8n("quality_pct", p.quality_pct)
            .u8n("battery_pct", p.battery_pct).num("channel_flags", p.channel_flags).num("artifact_flags", p.artifact_flags)
            .u16n("n_ppg_samples", p.n_ppg_samples).u16n("n_imu_samples", p.n_imu_samples).u16n("window_ms", p.window_ms)
            .u16n("fw_build", p.fw_build);
        break;
    }
    case UMSF_FT_STATION_STATE: {
        const umsf_station_t &s = f.u.station;
        o.u16n("vib_peak_cg", s.vib_peak_cg).u16n("accel_rms_mg", s.accel_rms_mg).i16n("tilt_ddeg", s.tilt_ddeg)
            .i16n("tilt_delta_ddeg", s.tilt_delta_ddeg).u16n("pressure_dhpa", s.pressure_dhpa)
            .i16n("pressure_delta_pa", s.pressure_delta_pa).i16n("temp", s.temp).u16n("gas_mv", s.gas_mv)
            .u16n("gas_baseline_mv", s.gas_baseline_mv).u16n("sound_index", s.sound_index).num("flags", s.flags)
            .u8n("quality_pct", s.quality_pct).u8n("battery_pct", s.battery_pct).num("sensor_flags", s.sensor_flags)
            .u16n("n_imu_samples", s.n_imu_samples).u16n("window_ms", s.window_ms).u16n("zone_code", s.zone_code)
            .u16n("fw_build", s.fw_build);
        break;
    }
    case UMSF_FT_EVENT: {
        const umsf_event_t &e = f.u.event;
        o.num("event_type", e.event_type).num("level", e.level).num("value", e.value)
            .u16n("rule_version", e.rule_version).u16n("zone_code", e.zone_code).num("related_seq_lo", e.related_seq_lo);
        break;
    }
    case UMSF_FT_STATUS: {
        const umsf_status_t &s = f.u.status;
        o.u8n("battery_pct", s.battery_pct).u8n("buffered_records", s.buffered_records)
            .u16n("evicted_total", s.evicted_total).u32n("sent_total", s.sent_total)
            .u32n("acked_up_to_seq", s.acked_up_to_seq).u16n("fw_build", s.fw_build)
            .num("sensor_flags", s.sensor_flags).u8n("rssi_neg", s.rssi_neg);
        break;
    }
    case UMSF_FT_ACK:
        o.num("target_boot_id", f.u.ack.target_boot_id).num("reserved", f.u.ack.reserved)
            .num("ack_up_to_seq", f.u.ack.ack_up_to_seq);
        break;
    case UMSF_FT_CONFIG:
        o.num("zone_code", f.u.config.zone_code).num("feature_window_ms", f.u.config.feature_window_ms)
            .num("sample_profile", f.u.config.sample_profile)
            .num("synthetic_hr_enabled", f.u.config.synthetic_hr_enabled).num("reserved", f.u.config.reserved);
        break;
    }
    return o;
}

std::vector<std::string> g_vectors;

void add_frame(const char *name, const char *note, const umsf_frame_t &f, bool corrupt = false) {
    uint8_t b[64];
    size_t n = umsf_encode(&f, b, sizeof b);
    if (!n) { std::fprintf(stderr, "encode failed: %s\n", name); std::exit(1); }
    if (corrupt) b[UMSF_HDR_LEN + 2] ^= 0x01;  // flip one payload bit, keep stored CRC
    umsf_frame_t d;
    int rc = umsf_decode(b, n, &d);
    if (rc != UMSF_OK && !(corrupt && rc == UMSF_ERR_CRC)) { std::fprintf(stderr, "decode failed: %s\n", name); std::exit(1); }
    Obj exp;
    exp.raw("header", header_obj(d.hdr).s(6)).raw("payload", payload_obj(d).s(6)).boolean("crc_ok", rc == UMSF_OK);
    Obj v;
    v.str("name", name).str("note", note).num("length", (long long)n).str("hex", hex(b, n).c_str()).raw("expected", exp.s(4));
    g_vectors.push_back(v.s(2));
}

void add_compact(const char *name, const char *note, const umsf_compact_t &c) {
    uint8_t b[UMSF_COMPACT_LEN];
    umsf_compact_encode(&c, b);
    umsf_compact_t d;
    int rc = umsf_compact_decode(b, sizeof b, &d);
    Obj exp;
    exp.num("magic", d.magic).num("node_index", d.node_index).num("seq", d.seq).u16n("vib_peak_cg", d.vib_peak_cg)
        .i16n("tilt_ddeg", d.tilt_ddeg).u16n("pressure_dhpa", d.pressure_dhpa).i16n("temp", d.temp)
        .u16n("gas_mv", d.gas_mv).u16n("sound_index", d.sound_index).num("flags", d.flags)
        .u8n("battery_pct", d.battery_pct).boolean("crc_ok", rc == UMSF_OK);
    Obj v;
    v.str("name", name).str("note", note).num("length", (long long)sizeof b).str("hex", hex(b, sizeof b).c_str())
        .raw("expected", exp.s(4));
    g_vectors.push_back(v.s(2));
}

umsf_frame_t frame(uint8_t sc, uint8_t ft, const char *dev, uint16_t boot, uint32_t seq, uint32_t ms) {
    umsf_frame_t f;
    std::memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, sc, ft, dev, boot, seq, ms);
    if (ft == UMSF_FT_PHYSIO_FEATURE) umsf_physio_set_null(&f.u.physio);
    if (ft == UMSF_FT_STATION_STATE) umsf_station_set_null(&f.u.station);
    if (ft == UMSF_FT_STATUS) umsf_status_set_null(&f.u.status);
    return f;
}

umsf_frame_t ev(uint8_t sc, const char *dev, uint16_t boot, uint32_t seq, uint32_t ms, uint8_t type, uint8_t lvl,
                int32_t v, uint16_t zone, uint16_t rel) {
    umsf_frame_t f = frame(sc, UMSF_FT_EVENT, dev, boot, seq, ms);
    f.u.event = umsf_event_t{type, lvl, v, 1, zone, rel};
    return f;
}

}  // namespace

int main(int argc, char **argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: %s test_vectors.json [mqtt_samples.jsonl]\n", argv[0]); return 2; }

    // 1. Paper Stage-1 record (Sec. 3.4.2): RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM
    umsf_frame_t paper = frame(UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, "A01", 1, 13, 122488);
    paper.u.physio.skin_temp = 2219;
    paper.u.physio.hr = 760;
    paper.u.physio.ppg_ir_mean = 1187;
    paper.u.physio.motion_rms_mg = 97;
    paper.u.physio.channel_flags = UMSF_CH_T | UMSF_CH_PPG | UMSF_CH_MOTION | UMSF_CH_HR_SYNTHETIC;
    paper.u.physio.window_ms = 10000;
    paper.u.physio.fw_build = 1;
    add_frame("physio_paper_stage1_A01",
              "Values of the paper Stage-1 record; fields absent from that record are null (measurements) or 0 "
              "(counters). hr is the synthetic test field (HR_SYNTHETIC). Gateway text line for this frame: "
              "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPMH (paper display without H: TPM).",
              paper);

    umsf_frame_t pn = frame(UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, "A02", 3, 1, 10012);
    pn.u.physio.artifact_flags = UMSF_AF_TEMP_ERROR | UMSF_AF_IMU_ERROR | UMSF_AF_SAMPLE_GAP;
    pn.u.physio.window_ms = 10000;
    pn.u.physio.fw_build = 1;
    add_frame("physio_all_null", "All measurement fields carry their null sentinel (missing is never zero).", pn);

    umsf_frame_t pf = frame(UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, "A03", 65534, 4294967294u, 4294967000u);
    umsf_physio_t &p = pf.u.physio;
    p.skin_temp = -125; p.hr = UMSF_NULL_U16; p.spo2 = UMSF_NULL_U16; p.ppg_ir_mean = 103456;
    p.ppg_red_mean_div16 = 5123; p.ppg_valid_permille = 987; p.motion_rms_mg = 312; p.gsr_mv = 1450;
    p.quality_pct = 46; p.battery_pct = 81;
    p.channel_flags = UMSF_CH_T | UMSF_CH_PPG | UMSF_CH_MOTION | UMSF_CH_GSR | UMSF_CH_SOS_ACTIVE;
    p.artifact_flags = UMSF_AF_MOTION_ARTIFACT; p.n_ppg_samples = 998; p.n_imu_samples = 250;
    p.window_ms = 10000; p.fw_build = 101;
    add_frame("physio_full_edge_values", "Negative temperature, near-max boot/sequence/node time, GSR and SOS flags.", pf);

    umsf_frame_t st = frame(UMSF_SRC_STATIONARY, UMSF_FT_STATION_STATE, "S01", 2, 57, 61000);
    umsf_station_t &s = st.u.station;
    s.vib_peak_cg = 3; s.tilt_ddeg = 4; s.pressure_dhpa = 10037; s.temp = 2190; s.gas_mv = 800; s.sound_index = 262;
    s.flags = UMSF_SF_PIR_PRESENCE | UMSF_SF_ATTACHMENT_UNCERTAIN;
    s.sensor_flags = UMSF_SEN_IMU_OK | UMSF_SEN_BMP_OK | UMSF_SEN_GAS_WARM | UMSF_SEN_MIC_OK | UMSF_SEN_PIR_OK;
    s.n_imu_samples = 200; s.window_ms = 1000; s.zone_code = 1; s.fw_build = 1;
    add_frame("station_stage2_card_values",
              "Displayed Stage-2 card values (0.03 g, 0.4 deg, 1003.7 hPa, 21.9 C, 0.80 V, sound 262, presence) "
              "transcribed into a frame; no baseline, so tilt_delta is null and attachment_uncertain is set.",
              st);

    umsf_frame_t st2 = frame(UMSF_SRC_STATIONARY, UMSF_FT_STATION_STATE, "S02", 5, 900, 905000);
    umsf_station_t &s2 = st2.u.station;
    s2.vib_peak_cg = 41; s2.accel_rms_mg = 18; s2.tilt_ddeg = 630; s2.tilt_delta_ddeg = 630; s2.pressure_dhpa = 10021;
    s2.pressure_delta_pa = -3; s2.temp = -450; s2.gas_mv = 1210; s2.gas_baseline_mv = 795; s2.sound_index = 1800;
    s2.flags = UMSF_SF_TILT_ALARM | UMSF_SF_GAS_ALARM | UMSF_SF_LOUD_SOUND | UMSF_SF_ATTACHMENT_UNCERTAIN | UMSF_SF_SOS_ACTIVE;
    s2.quality_pct = 80; s2.battery_pct = 64; s2.sensor_flags = 0x0F; s2.n_imu_samples = 199; s2.window_ms = 1000;
    s2.zone_code = 2; s2.fw_build = 1;
    add_frame("station_tilt_63deg_alarms", "Tilt change 63.0 deg vs baseline, gas alarm, loud sound, SOS; PIR not ok.", st2);

    add_frame("event_sos_stationary", "SOS button GPIO27 on a stationary node (urgent).",
              ev(UMSF_SRC_STATIONARY, "S01", 2, 58, 61500, UMSF_EV_SOS, UMSF_LVL_URGENT, 1000, 1, 57));
    add_frame("event_help_request_personnel", "Personnel help button (urgent, independent of group rules).",
              ev(UMSF_SRC_PERSONNEL, "A01", 1, 14, 125000, UMSF_EV_HELP_REQUEST, UMSF_LVL_URGENT, 1000, 1, 13));
    add_frame("event_possible_impact_local", "Unverified local composite (impact + loud/pressure within 2 s), value 2.5 g.",
              ev(UMSF_SRC_STATIONARY, "S01", 2, 59, 62210, UMSF_EV_POSSIBLE_IMPACT_LOCAL, UMSF_LVL_WARNING, 2500, 1, 58));
    add_frame("event_pressure_transient", "Pressure transient 150 Pa within 1 s.",
              ev(UMSF_SRC_STATIONARY, "S01", 2, 60, 62300, UMSF_EV_PRESSURE_TRANSIENT, UMSF_LVL_NOTICE, 150000, 1, 58));
    add_frame("event_link_loss_gateway", "Gateway-generated link_loss (source_class 3, device_id = gateway); 2.4 s since last frame.",
              ev(UMSF_SRC_GATEWAY, "AG1", 3, 77, 90000, UMSF_EV_LINK_LOSS, UMSF_LVL_WARNING, 2400, 1, 60));
    add_frame("event_link_restored_gateway", "Gateway-generated link_restored after a 240 s outage.",
              ev(UMSF_SRC_GATEWAY, "AG1", 3, 78, 330000, UMSF_EV_LINK_RESTORED, UMSF_LVL_INFO, 240000, 1, 60));
    add_frame("event_buffer_eviction_zone_max", "Node buffer evicted 2 records (value = count x1000); zone_code 0xFFFF = null (zone unknown).",
              ev(UMSF_SRC_PERSONNEL, "A01", 1, 45, 450000, UMSF_EV_BUFFER_EVICTION, UMSF_LVL_WARNING, 2000, 65535, 0));
    add_frame("event_tilt_negative_value", "Signed i32 value round-trip (-12.345).",
              ev(UMSF_SRC_STATIONARY, "S02", 5, 901, 906000, UMSF_EV_TILT_CHANGE, UMSF_LVL_WARNING, -12345, 2, 900));

    umsf_frame_t sf = frame(UMSF_SRC_PERSONNEL, UMSF_FT_STATUS, "A01", 1, 13, 130000);
    sf.u.status = umsf_status_t{UMSF_NULL_U8, 5, 2, 120, 12, 1, 0x07, 67};
    add_frame("status_personnel", "STATUS: battery unknown (null), 5 buffered, 2 evicted, RSSI -67 dBm.", sf);

    umsf_frame_t ak = frame(UMSF_SRC_GATEWAY, UMSF_FT_ACK, "AG1", 3, 79, 331000);
    ak.u.ack = umsf_ack_t{1, 0, 13};
    add_frame("ack_gateway_to_A01", "Application ACK relayed only after site-agent COMMIT: boot 1 up to seq 13.", ak);

    umsf_frame_t cf = frame(UMSF_SRC_GATEWAY, UMSF_FT_CONFIG, "AG1", 3, 80, 331500);
    cf.u.config = umsf_config_t{2, 10000, 0, 1, 0};
    add_frame("config_gateway", "CONFIG: zone 2, 10 s window, profile 0, synthetic HR test field enabled.", cf);

    add_frame("physio_crc_corrupted", "Negative vector: one payload bit flipped after CRC; must be rejected.", paper, true);

    add_compact("compact_stage2", "20-byte COMPACT packet (no fragment header) with Stage-2 card values.",
                umsf_compact_t{UMSF_COMPACT_MAGIC, 1, 513, 3, 4, 10037, 2190, 800, 262,
                               UMSF_SF_PIR_PRESENCE | UMSF_SF_ATTACHMENT_UNCERTAIN, UMSF_NULL_U8});
    add_compact("compact_nulls_wrap", "COMPACT with null sentinels and seq at the u16 wrap point.",
                umsf_compact_t{UMSF_COMPACT_MAGIC, 3, 65535, UMSF_NULL_U16, UMSF_NULL_I16, UMSF_NULL_U16, UMSF_NULL_I16,
                               UMSF_NULL_U16, UMSF_NULL_U16, UMSF_SF_SOS_ACTIVE, 55});

    FILE *out = std::fopen(argv[1], "w");
    if (!out) { std::perror(argv[1]); return 1; }
    std::fputs("[\n", out);
    for (size_t i = 0; i < g_vectors.size(); ++i)
        std::fprintf(out, "  %s%s\n", g_vectors[i].c_str(), i + 1 < g_vectors.size() ? "," : "");
    std::fputs("]\n", out);
    std::fclose(out);
    std::printf("wrote %zu vectors to %s\n", g_vectors.size(), argv[1]);

    if (argc >= 3) {  // example MQTT records as the gateway would publish them
        FILE *m = std::fopen(argv[2], "w");
        if (!m) { std::perror(argv[2]); return 1; }
        umsf_json_ctx_t c;
        umsf_json_ctx_init(&c);
        c.data_origin = "synthetic";
        c.scenario_id = "S0";
        c.site_id = "A";
        c.gateway_id = "AG1";
        c.zone_id = "Z1";
        c.measured_at_ms = 1791979200000LL;
        c.received_at_ms = 1791979200350LL;
        c.time_uncertainty_ms = 410;
        char js[1600];
        uint8_t raw[64];
        const umsf_frame_t *recs[] = {&paper, &st, nullptr};
        for (const umsf_frame_t **r = recs; *r; ++r) {
            size_t n = umsf_encode(*r, raw, sizeof raw);
            if (umsf_json_record(&c, *r, raw, n, js, sizeof js) < 0) return 1;
            std::fprintf(m, "%s\n", js);
        }
        umsf_frame_t e1 = ev(UMSF_SRC_STATIONARY, "S01", 2, 59, 62210, UMSF_EV_POSSIBLE_IMPACT_LOCAL, UMSF_LVL_WARNING, 2500, 1, 58);
        size_t n = umsf_encode(&e1, raw, sizeof raw);
        umsf_json_event(&c, &e1, raw, n, js, sizeof js);
        std::fprintf(m, "%s\n", js);
        umsf_frame_t e2 = ev(UMSF_SRC_GATEWAY, "AG1", 3, 77, 90000, UMSF_EV_LINK_LOSS, UMSF_LVL_WARNING, 2400, 1, 60);
        c.subject_device_id = "S01";
        c.method = "gateway link supervision: no frame for > 2 s";
        n = umsf_encode(&e2, raw, sizeof raw);
        umsf_json_event(&c, &e2, raw, n, js, sizeof js);
        std::fprintf(m, "%s\n", js);
        std::fclose(m);
        std::printf("wrote MQTT samples to %s\n", argv[2]);
    }
    return 0;
}
