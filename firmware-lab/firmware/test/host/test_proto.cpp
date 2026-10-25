// Protocol codec, text line and JSON tests.
#include <cstdint>
#include <cstring>

#include "umsf_json.h"
#include "umsf_proto.h"
#include "umsf_test.h"
#include "umsf_text.h"

namespace {

umsf_frame_t paper_physio(uint8_t channel_flags) {
    // Paper Sec. 3.4.2: RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM
    umsf_frame_t f;
    std::memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, "A01", 1, 13, 122488);
    umsf_physio_set_null(&f.u.physio);
    f.u.physio.skin_temp = 2219;
    f.u.physio.ppg_ir_mean = 1187;
    f.u.physio.motion_rms_mg = 97;
    f.u.physio.hr = 760;
    f.u.physio.channel_flags = channel_flags;
    f.u.physio.n_ppg_samples = 1000;
    f.u.physio.n_imu_samples = 250;
    f.u.physio.window_ms = 10000;
    f.u.physio.fw_build = 1;
    return f;
}

umsf_frame_t sample_station() {
    umsf_frame_t f;
    std::memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_STATIONARY, UMSF_FT_STATION_STATE, "S01", 7, 42, 61000);
    umsf_station_t &s = f.u.station;
    umsf_station_set_null(&s);
    s.vib_peak_cg = 3; s.accel_rms_mg = 12; s.tilt_ddeg = 4; s.tilt_delta_ddeg = -2;
    s.pressure_dhpa = 10037; s.pressure_delta_pa = 3; s.temp = 2190; s.gas_mv = 800;
    s.gas_baseline_mv = 780; s.sound_index = 262; s.flags = UMSF_SF_PIR_PRESENCE;
    s.quality_pct = 90; s.battery_pct = UMSF_NULL_U8; s.sensor_flags = 0x1F;
    s.n_imu_samples = 200; s.window_ms = 1000; s.zone_code = 1; s.fw_build = 1;
    return f;
}

bool roundtrip(const umsf_frame_t &f, umsf_frame_t &out, size_t &len) {
    uint8_t buf[64];
    len = umsf_encode(&f, buf, sizeof buf);
    return len == umsf_frame_len(f.hdr.frame_type) && umsf_decode(buf, len, &out) == UMSF_OK;
}

}  // namespace

TEST(proto_crc_known_vector) {
    const char *s = "123456789";
    CHECK_EQ(umsf_crc16(reinterpret_cast<const uint8_t *>(s), 9), 0x29B1);
    CHECK_EQ(umsf_crc16(nullptr, 0), 0xFFFF);
}

TEST(proto_lengths) {
    CHECK_EQ(umsf_frame_len(UMSF_FT_PHYSIO_FEATURE), 50);
    CHECK_EQ(umsf_frame_len(UMSF_FT_STATION_STATE), 52);
    CHECK_EQ(umsf_frame_len(UMSF_FT_EVENT), 32);
    CHECK_EQ(umsf_frame_len(UMSF_FT_STATUS), 36);
    CHECK_EQ(umsf_frame_len(UMSF_FT_ACK), 28);
    CHECK_EQ(umsf_frame_len(UMSF_FT_CONFIG), 28);
    CHECK_EQ(umsf_frame_len(7), 0);
}

TEST(proto_header_layout) {
    umsf_frame_t f = paper_physio(0x0F);
    uint8_t b[64];
    size_t n = umsf_encode(&f, b, sizeof b);
    CHECK_EQ(n, 50);
    CHECK_EQ(b[0], 0xB5); CHECK_EQ(b[1], 1); CHECK_EQ(b[2], 1); CHECK_EQ(b[3], 1);
    CHECK(std::memcmp(b + 4, "A01\0", 4) == 0);
    CHECK_EQ(b[8] | (b[9] << 8), 1);
    CHECK_EQ(b[10], 13); CHECK_EQ(b[11], 0);
    CHECK_EQ((uint32_t)b[14] | (uint32_t)b[15] << 8 | (uint32_t)b[16] << 16 | (uint32_t)b[17] << 24, 122488u);
    CHECK_EQ(b[18] | (b[19] << 8), 2219);               // skin_temp LE
    uint16_t crc = umsf_crc16(b, 48);
    CHECK_EQ(b[48] | (b[49] << 8), crc);                // CRC LE
}

TEST(proto_roundtrip_physio) {
    umsf_frame_t f = paper_physio(0x0F), g;
    f.u.physio.ppg_red_mean_div16 = 4321; f.u.physio.ppg_valid_permille = 950;
    f.u.physio.gsr_mv = 1234; f.u.physio.quality_pct = 88; f.u.physio.battery_pct = 77;
    f.u.physio.artifact_flags = UMSF_AF_MOTION_ARTIFACT;
    size_t n;
    CHECK(roundtrip(f, g, n));
    CHECK_STR(g.hdr.device_id, "A01");
    CHECK_EQ(g.hdr.boot_id, 1); CHECK_EQ(g.hdr.sequence, 13); CHECK_EQ(g.hdr.node_time_ms, 122488);
    CHECK_EQ(g.u.physio.skin_temp, 2219); CHECK_EQ(g.u.physio.hr, 760);
    CHECK_EQ(g.u.physio.spo2, UMSF_NULL_U16); CHECK_EQ(g.u.physio.ppg_ir_mean, 1187);
    CHECK_EQ(g.u.physio.ppg_red_mean_div16, 4321); CHECK_EQ(g.u.physio.ppg_valid_permille, 950);
    CHECK_EQ(g.u.physio.motion_rms_mg, 97); CHECK_EQ(g.u.physio.gsr_mv, 1234);
    CHECK_EQ(g.u.physio.quality_pct, 88); CHECK_EQ(g.u.physio.battery_pct, 77);
    CHECK_EQ(g.u.physio.channel_flags, 0x0F); CHECK_EQ(g.u.physio.artifact_flags, 1);
    CHECK_EQ(g.u.physio.n_ppg_samples, 1000); CHECK_EQ(g.u.physio.n_imu_samples, 250);
    CHECK_EQ(g.u.physio.window_ms, 10000); CHECK_EQ(g.u.physio.fw_build, 1);
}

TEST(proto_roundtrip_station) {
    umsf_frame_t f = sample_station(), g;
    size_t n;
    CHECK(roundtrip(f, g, n));
    CHECK_EQ(n, 52);
    CHECK_EQ(g.hdr.source_class, UMSF_SRC_STATIONARY);
    CHECK_EQ(g.u.station.vib_peak_cg, 3); CHECK_EQ(g.u.station.accel_rms_mg, 12);
    CHECK_EQ(g.u.station.tilt_ddeg, 4); CHECK_EQ(g.u.station.tilt_delta_ddeg, -2);
    CHECK_EQ(g.u.station.pressure_dhpa, 10037); CHECK_EQ(g.u.station.pressure_delta_pa, 3);
    CHECK_EQ(g.u.station.temp, 2190); CHECK_EQ(g.u.station.gas_mv, 800);
    CHECK_EQ(g.u.station.gas_baseline_mv, 780); CHECK_EQ(g.u.station.sound_index, 262);
    CHECK_EQ(g.u.station.flags, 1); CHECK_EQ(g.u.station.quality_pct, 90);
    CHECK_EQ(g.u.station.battery_pct, 0xFF); CHECK_EQ(g.u.station.sensor_flags, 0x1F);
    CHECK_EQ(g.u.station.n_imu_samples, 200); CHECK_EQ(g.u.station.window_ms, 1000);
    CHECK_EQ(g.u.station.zone_code, 1); CHECK_EQ(g.u.station.fw_build, 1);
}

TEST(proto_roundtrip_event_status_ack_config) {
    umsf_frame_t f, g;
    size_t n;
    std::memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_STATIONARY, UMSF_FT_EVENT, "S01", 7, 43, 61200);
    f.u.event = umsf_event_t{UMSF_EV_POSSIBLE_IMPACT_LOCAL, UMSF_LVL_WARNING, -15300, 1, 1, 42};
    CHECK(roundtrip(f, g, n));
    CHECK_EQ(n, 32);
    CHECK_EQ(g.u.event.event_type, 10); CHECK_EQ(g.u.event.level, 2); CHECK_EQ(g.u.event.value, -15300);
    CHECK_EQ(g.u.event.rule_version, 1); CHECK_EQ(g.u.event.zone_code, 1); CHECK_EQ(g.u.event.related_seq_lo, 42);

    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_STATUS, "A01", 1, 13, 130000);
    f.u.status = umsf_status_t{UMSF_NULL_U8, 5, 2, 100000, 12, 1, 0x07, 67};
    CHECK(roundtrip(f, g, n));
    CHECK_EQ(n, 36);
    CHECK_EQ(g.u.status.battery_pct, 0xFF); CHECK_EQ(g.u.status.buffered_records, 5);
    CHECK_EQ(g.u.status.evicted_total, 2); CHECK_EQ(g.u.status.sent_total, 100000);
    CHECK_EQ(g.u.status.acked_up_to_seq, 12); CHECK_EQ(g.u.status.fw_build, 1);
    CHECK_EQ(g.u.status.sensor_flags, 7); CHECK_EQ(g.u.status.rssi_neg, 67);

    umsf_header_init(&f.hdr, UMSF_SRC_GATEWAY, UMSF_FT_ACK, "AG1", 3, 900, 5000);
    f.u.ack = umsf_ack_t{1, 0, 13};
    CHECK(roundtrip(f, g, n));
    CHECK_EQ(g.hdr.source_class, UMSF_SRC_GATEWAY);
    CHECK_EQ(g.u.ack.target_boot_id, 1); CHECK_EQ(g.u.ack.reserved, 0); CHECK_EQ(g.u.ack.ack_up_to_seq, 13);

    umsf_header_init(&f.hdr, UMSF_SRC_GATEWAY, UMSF_FT_CONFIG, "AG1", 3, 901, 5001);
    f.u.config = umsf_config_t{2, 10000, 0, 1, 0};
    CHECK(roundtrip(f, g, n));
    CHECK_EQ(g.u.config.zone_code, 2); CHECK_EQ(g.u.config.feature_window_ms, 10000);
    CHECK_EQ(g.u.config.sample_profile, 0); CHECK_EQ(g.u.config.synthetic_hr_enabled, 1);
}

TEST(proto_null_sentinels) {
    umsf_frame_t f, g;
    std::memset(&f, 0, sizeof f);
    umsf_header_init(&f.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_PHYSIO_FEATURE, "A02", 2, 1, 10000);
    umsf_physio_set_null(&f.u.physio);
    uint8_t b[64];
    size_t n = umsf_encode(&f, b, sizeof b);
    CHECK_EQ(n, 50);
    // skin_temp i16 null = 0x8000 little-endian
    CHECK_EQ(b[18], 0x00); CHECK_EQ(b[19], 0x80);
    // hr, spo2 = 0xFFFF; ppg_ir_mean = 0xFFFFFFFF
    for (int i = 20; i < 28; ++i) CHECK_EQ(b[i], 0xFF);
    CHECK_EQ(umsf_decode(b, n, &g), UMSF_OK);
    CHECK_EQ(g.u.physio.skin_temp, UMSF_NULL_I16);
    CHECK_EQ(g.u.physio.ppg_ir_mean, UMSF_NULL_U32);
    CHECK_EQ(g.u.physio.quality_pct, UMSF_NULL_U8);
    CHECK_EQ(g.u.physio.gsr_mv, UMSF_NULL_U16);
}

TEST(proto_decode_errors) {
    umsf_frame_t f = paper_physio(0x0F), g;
    uint8_t b[64];
    size_t n = umsf_encode(&f, b, sizeof b);
    CHECK_EQ(umsf_decode(b, 10, &g), UMSF_ERR_SHORT);
    CHECK_EQ(umsf_decode(b, n - 1, &g), UMSF_ERR_SHORT);
    CHECK_EQ(umsf_decode(b, n + 1, &g), UMSF_ERR_LENGTH);
    b[30] ^= 0x01;
    CHECK_EQ(umsf_decode(b, n, &g), UMSF_ERR_CRC);
    b[30] ^= 0x01;
    b[0] = 0x00;
    CHECK_EQ(umsf_decode(b, n, &g), UMSF_ERR_MAGIC);
    b[0] = UMSF_MAGIC; b[1] = 2;
    CHECK_EQ(umsf_decode(b, n, &g), UMSF_ERR_VERSION);
    b[1] = 1; b[3] = 9;
    CHECK_EQ(umsf_decode(b, n, &g), UMSF_ERR_TYPE);
    CHECK_EQ(umsf_encode(&f, b, 49), 0u);  // buffer too small
}

TEST(proto_compact_roundtrip) {
    umsf_compact_t c{UMSF_COMPACT_MAGIC, 1, 65535, 3, 4, 10037, 2190, 800, 262, UMSF_SF_PIR_PRESENCE, UMSF_NULL_U8}, d;
    uint8_t b[UMSF_COMPACT_LEN];
    umsf_compact_encode(&c, b);
    CHECK_EQ(b[0], 0xC5);
    CHECK_EQ(umsf_compact_decode(b, sizeof b, &d), UMSF_OK);
    CHECK_EQ(d.seq, 65535); CHECK_EQ(d.vib_peak_cg, 3); CHECK_EQ(d.tilt_ddeg, 4);
    CHECK_EQ(d.pressure_dhpa, 10037); CHECK_EQ(d.temp, 2190); CHECK_EQ(d.gas_mv, 800);
    CHECK_EQ(d.sound_index, 262); CHECK_EQ(d.flags, 1); CHECK_EQ(d.battery_pct, 0xFF);
    CHECK_EQ(b[18] | (b[19] << 8), umsf_crc16(b, 18));
    b[5] ^= 0x40;
    CHECK_EQ(umsf_compact_decode(b, sizeof b, &d), UMSF_ERR_CRC);
    CHECK_EQ(umsf_compact_decode(b, 19, &d), UMSF_ERR_SHORT);
}

TEST(text_paper_example_exact) {
    // T|P|M as displayed in the paper's Stage-1 record
    umsf_frame_t f = paper_physio(UMSF_CH_T | UMSF_CH_PPG | UMSF_CH_MOTION);
    char line[160];
    int n = umsf_text_line("AG1", 152639, &f, line, sizeof line);
    CHECK(n > 0);
    CHECK_STR(line, "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM");
    // the synthetic-HR flag adds the H letter (spec 3)
    f.u.physio.channel_flags |= UMSF_CH_HR_SYNTHETIC;
    umsf_text_line("AG1", 152639, &f, line, sizeof line);
    CHECK_STR(line, "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPMH");
}

TEST(text_nulls_station_event) {
    umsf_frame_t f = paper_physio(UMSF_CH_PPG);
    f.u.physio.skin_temp = UMSF_NULL_I16;
    f.u.physio.hr = UMSF_NULL_U16;
    f.u.physio.motion_rms_mg = UMSF_NULL_U16;
    char line[200];
    umsf_text_line("AG1", 1, &f, line, sizeof line);
    CHECK_STR(line, "RX,AG1,1,F,A01,1,13,122488,,1187,,,P");

    umsf_frame_t s = sample_station();
    s.u.station.flags = UMSF_SF_PIR_PRESENCE | UMSF_SF_ATTACHMENT_UNCERTAIN;
    umsf_text_line("AG1", 2, &s, line, sizeof line);
    CHECK_STR(line, "RX,AG1,2,S,S01,7,42,61000,3,4,10037,2190,800,262,81");

    umsf_frame_t e;
    std::memset(&e, 0, sizeof e);
    umsf_header_init(&e.hdr, UMSF_SRC_PERSONNEL, UMSF_FT_EVENT, "A01", 1, 14, 125000);
    e.u.event = umsf_event_t{UMSF_EV_HELP_REQUEST, UMSF_LVL_URGENT, 1000, 1, 1, 13};
    umsf_text_line("AG1", 3, &e, line, sizeof line);
    CHECK_STR(line, "RX,AG1,3,E,A01,1,14,125000,help_request,3,1000");

    CHECK_EQ(umsf_text_line("AG1", 3, &e, line, 10), -1);  // too small
}

TEST(json_physio_fields) {
    umsf_frame_t f = paper_physio(UMSF_CH_T | UMSF_CH_PPG | UMSF_CH_MOTION | UMSF_CH_HR_SYNTHETIC);
    f.u.physio.quality_pct = 80;
    uint8_t raw[64];
    size_t rl = umsf_encode(&f, raw, sizeof raw);
    umsf_json_ctx_t c;
    umsf_json_ctx_init(&c);
    c.data_origin = "bench_transcription";
    c.site_id = "A";
    c.gateway_id = "AG1";
    c.measured_at_ms = 1791979200123LL;  // 2026-10-14T12:00:00.123Z
    c.received_at_ms = 1791979200500LL;
    c.time_uncertainty_ms = 350;
    char js[1024];
    int n = umsf_json_physio(&c, &f, raw, rl, js, sizeof js);
    CHECK(n > 0);
    CHECK(std::strstr(js, "\"schema_version\":\"1.0\"") != nullptr);
    CHECK(std::strstr(js, "\"scenario_id\":null") != nullptr);
    CHECK(std::strstr(js, "\"measured_at\":\"2026-10-14T12:00:00.123Z\"") != nullptr);
    CHECK(std::strstr(js, "\"hr_bpm\":76.0") != nullptr);
    CHECK(std::strstr(js, "\"spo2_pct\":null") != nullptr);
    CHECK(std::strstr(js, "\"skin_temp_c\":22.19") != nullptr);
    CHECK(std::strstr(js, "\"motion_rms_g\":0.097") != nullptr);
    CHECK(std::strstr(js, "\"quality\":0.80") != nullptr);
    CHECK(std::strstr(js, "\"battery_pct\":null") != nullptr);
    CHECK(std::strstr(js, "\"hr_synthetic\":true") != nullptr);
    CHECK(std::strstr(js, "\"time_uncertainty_s\":0.350") != nullptr);
    CHECK(std::strstr(js, "\"frame_hex\":\"b5010101413031000100") != nullptr);
    CHECK(js[n - 1] == '}');
    // unsynchronised clock -> null times
    c.measured_at_ms = c.received_at_ms = UMSF_TIME_UNKNOWN;
    c.time_uncertainty_ms = -1;
    umsf_json_physio(&c, &f, raw, rl, js, sizeof js);
    CHECK(std::strstr(js, "\"measured_at\":null,\"received_at\":null") != nullptr);
    CHECK(std::strstr(js, "\"time_uncertainty_s\":null") != nullptr);
    CHECK_EQ(umsf_json_physio(&c, &f, raw, rl, js, 64), -1);
}

TEST(json_station_event) {
    umsf_frame_t s = sample_station();
    umsf_json_ctx_t c;
    umsf_json_ctx_init(&c);
    c.site_id = "A"; c.zone_id = "Z1"; c.gateway_id = "AG1";
    char js[1200];
    CHECK(umsf_json_station(&c, &s, nullptr, 0, js, sizeof js) > 0);
    CHECK(std::strstr(js, "\"schema_version\":\"st-1.0\"") != nullptr);
    CHECK(std::strstr(js, "\"vib_peak_g\":0.03") != nullptr);
    CHECK(std::strstr(js, "\"tilt_deg\":0.4") != nullptr);
    CHECK(std::strstr(js, "\"tilt_delta_deg\":-0.2") != nullptr);
    CHECK(std::strstr(js, "\"pressure_hpa\":1003.7") != nullptr);
    CHECK(std::strstr(js, "\"temp_c\":21.90") != nullptr);
    CHECK(std::strstr(js, "\"gas_v\":0.800") != nullptr);
    CHECK(std::strstr(js, "\"pir_presence\":true") != nullptr);
    CHECK(std::strstr(js, "\"attachment_verified\":false") != nullptr);
    CHECK(std::strstr(js, "frame_hex") == nullptr);

    umsf_frame_t e;
    std::memset(&e, 0, sizeof e);
    umsf_header_init(&e.hdr, UMSF_SRC_GATEWAY, UMSF_FT_EVENT, "AG1", 3, 77, 90000);
    e.u.event = umsf_event_t{UMSF_EV_LINK_LOSS, UMSF_LVL_WARNING, 2400, 1, 1, 42};
    c.subject_device_id = "S01";
    c.method = "gateway link supervision, stale > 2 s";
    CHECK(umsf_json_event(&c, &e, nullptr, 0, js, sizeof js) > 0);
    CHECK(std::strstr(js, "\"schema_version\":\"ev-1.0\"") != nullptr);
    CHECK(std::strstr(js, "\"event_id\":\"A:AG1:3:77\"") != nullptr);
    CHECK(std::strstr(js, "\"source_class\":\"gateway\"") != nullptr);
    CHECK(std::strstr(js, "\"device_id\":\"S01\"") != nullptr);
    CHECK(std::strstr(js, "\"event_type\":\"link_loss\"") != nullptr);
    CHECK(std::strstr(js, "\"level\":\"warning\"") != nullptr);
    CHECK(std::strstr(js, "\"value\":2.400,\"unit\":\"s\"") != nullptr);
    CHECK(std::strstr(js, "\"ack_state\":\"unacknowledged\"") != nullptr);
    CHECK(std::strstr(js, "\"provenance\":{\"source\":\"gateway:AG1\",\"method\":\"gateway link supervision, stale > 2 s\"}") != nullptr);
}

TEST(json_iso8601) {
    char t[32];
    CHECK_STR(umsf_iso8601_ms(0, t, sizeof t), "1970-01-01T00:00:00.000Z");
    CHECK_STR(umsf_iso8601_ms(951782400000LL, t, sizeof t), "2000-02-29T00:00:00.000Z");
    CHECK_STR(umsf_iso8601_ms(1791979200123LL, t, sizeof t), "2026-10-14T12:00:00.123Z");
    CHECK(umsf_iso8601_ms(-1, t, sizeof t) == nullptr);
}

TEST(timemap_min_offset_and_resend) {
    umsf_timemap_t m;
    umsf_timemap_init(&m);
    // node frames every 10 s; latencies 120, 40, 300 ms
    umsf_timemap_observe(&m, 1, 1, 10000, 1000000 + 10000 + 120);
    umsf_timemap_observe(&m, 1, 2, 20000, 1000000 + 20000 + 40);
    umsf_timemap_observe(&m, 1, 3, 30000, 1000000 + 30000 + 300);
    // a resend of seq 2 arriving 60 s late must not distort the estimate
    umsf_timemap_observe(&m, 1, 2, 20000, 1000000 + 80000);
    int64_t local;
    uint32_t unc;
    CHECK_EQ(umsf_timemap_map(&m, 1, 30000, 1000000 + 30300, &local, &unc), 0);
    CHECK_EQ(local, 1000000 + 30000 + 40);
    CHECK(unc >= 260 + 250 && unc < 600);
    CHECK_EQ(umsf_timemap_map(&m, 2, 30000, 0, &local, &unc), -1);  // other boot: unknown
}
