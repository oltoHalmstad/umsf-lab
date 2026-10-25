// Feature extraction and detector tests on synthetic signals.
#include <cmath>
#include <cstring>
#include <vector>

#include "umsf_features.h"
#include "umsf_test.h"

using namespace umsf;

namespace {
std::vector<DetectedEvent> drain(StationDetector &d) {
    std::vector<DetectedEvent> v;
    DetectedEvent e;
    while (d.pop_event(e)) v.push_back(e);
    return v;
}
int count_type(const std::vector<DetectedEvent> &v, uint8_t t) {
    int n = 0;
    for (auto &e : v) n += e.type == t;
    return n;
}
const DetectedEvent *first_of(const std::vector<DetectedEvent> &v, uint8_t t) {
    for (auto &e : v) if (e.type == t) return &e;
    return nullptr;
}
// 1 s window of still accel at 200 Hz starting at t0
void still(StationDetector &d, uint32_t t0, float x = 0, float y = 0, float z = 1000) {
    for (int i = 0; i < 200; ++i) d.add_accel_mg(t0 + i * 5, x, y, z);
}
StationDetector make_station(const RuleConfig &c) {
    StationDetector d(c);
    d.begin(0);
    d.set_sensor_ok(true, true, true, true);
    return d;
}
}  // namespace

TEST(physio_clean_window) {
    RuleConfig c;
    PhysioWindow w(c);
    for (int i = 0; i < 1000; ++i) w.add_ppg(80000, 100000);
    for (int i = 0; i < 250; ++i) w.add_accel_mg(0, 0, 1000);
    for (int i = 0; i < 10; ++i) w.add_temp_c100(3312);
    umsf_physio_t p = w.finish(10000, UMSF_NULL_U8, false, 7, 1);
    CHECK_EQ(p.channel_flags, UMSF_CH_T | UMSF_CH_PPG | UMSF_CH_MOTION);
    CHECK_EQ(p.artifact_flags, 0);
    CHECK_EQ(p.ppg_ir_mean, 100000u);
    CHECK_EQ(p.ppg_red_mean_div16, 5000);
    CHECK_EQ(p.ppg_valid_permille, 1000);
    CHECK_EQ(p.motion_rms_mg, 0);
    CHECK_EQ(p.skin_temp, 3312);
    CHECK_EQ(p.hr, UMSF_NULL_U16);    // default: no synthetic, estimator disabled
    CHECK_EQ(p.spo2, UMSF_NULL_U16);
    CHECK_EQ(p.gsr_mv, UMSF_NULL_U16);
    CHECK_EQ(p.quality_pct, 100);
    CHECK_EQ(p.n_ppg_samples, 1000); CHECK_EQ(p.n_imu_samples, 250);
    CHECK_EQ(p.window_ms, 10000); CHECK_EQ(p.fw_build, 7);
}

TEST(physio_no_contact_saturation_gap_motion) {
    RuleConfig c;
    PhysioWindow w(c);
    for (int i = 0; i < 1000; ++i) w.add_ppg(900, 1187);  // paper-like low IR: no skin contact
    for (int i = 0; i < 250; ++i) w.add_accel_mg(0, 0, i % 2 ? 1300.f : 700.f);  // +-300 mg
    w.temp_error();
    umsf_physio_t p = w.finish(10000, 50, false, 1, 1);
    CHECK(p.artifact_flags & UMSF_AF_NO_CONTACT);
    CHECK(p.artifact_flags & UMSF_AF_MOTION_ARTIFACT);
    CHECK(p.artifact_flags & UMSF_AF_TEMP_ERROR);
    CHECK(!(p.channel_flags & UMSF_CH_T));
    CHECK_EQ(p.skin_temp, UMSF_NULL_I16);
    CHECK_EQ(p.ppg_valid_permille, 0);
    CHECK_NEAR(p.motion_rms_mg, 300, 1);
    CHECK_EQ(p.quality_pct, 0);

    w.reset();
    for (int i = 0; i < 500; ++i) w.add_ppg(100000, i < 20 ? 262143u : 100000u);
    for (int i = 0; i < 250; ++i) w.add_accel_mg(0, 0, 1000);
    p = w.finish(10000, 50, true, 1, 1);
    CHECK(p.artifact_flags & UMSF_AF_SAMPLE_GAP);
    CHECK(p.artifact_flags & UMSF_AF_SATURATION);
    CHECK(p.channel_flags & UMSF_CH_SOS_ACTIVE);
    CHECK_EQ(p.ppg_valid_permille, 960);
    CHECK_EQ(p.quality_pct, 48);  // 0.96 valid x 0.5 completeness
}

TEST(physio_synthetic_hr_flagged) {
    RuleConfig c;
    c.synthetic_hr_enabled = true;
    PhysioWindow w(c);
    for (int i = 0; i < 1000; ++i) w.add_ppg(80000, 100000);
    umsf_physio_t p = w.finish(10000, UMSF_NULL_U8, false, 1, 13);
    CHECK(p.channel_flags & UMSF_CH_HR_SYNTHETIC);
    CHECK_EQ(p.hr, PhysioWindow::synthetic_hr_x10(13));
    CHECK_EQ(p.hr, 720);
}

TEST(physio_unvalidated_pulse_estimator) {
    RuleConfig c;
    c.pulse_estimator_enabled = true;  // off by default; UNVALIDATED
    PhysioWindow w(c);
    for (int i = 0; i < 1000; ++i) {
        double t = i / 100.0;
        uint32_t ir = (uint32_t)(100000 + 1500 * std::sin(2 * M_PI * 1.2 * t) + 300 * std::sin(2 * M_PI * 2.4 * t + 1));
        w.add_ppg(80000, ir);
    }
    umsf_physio_t p = w.finish(10000, UMSF_NULL_U8, false, 1, 1);
    CHECK(!(p.channel_flags & UMSF_CH_HR_SYNTHETIC));
    CHECK(p.hr != UMSF_NULL_U16);
    CHECK_NEAR(p.hr, 720, 30);
}

TEST(button_debounce_latch_reset) {
    RuleConfig c;
    SosButton b(c);
    uint32_t t = 0;
    int raised = 0, reset = 0;
    auto step = [&](bool lvl, uint32_t ms) {
        for (uint32_t i = 0; i < ms; ++i, ++t) {
            auto a = b.update(lvl, t);
            raised += a == SosButton::RAISED;
            reset += a == SosButton::RESET;
        }
    };
    step(false, 100);
    for (int k = 0; k < 5; ++k) { step(true, 5); step(false, 5); }  // contact bounce < 30 ms
    CHECK_EQ(raised, 0);
    CHECK(!b.active());
    step(true, 40);
    CHECK_EQ(raised, 1);
    CHECK(b.active());
    step(true, 4000);            // holding the raising press never resets it
    CHECK_EQ(reset, 0);
    step(false, 100);
    step(true, 200); step(false, 100);  // short press while latched: still active
    CHECK(b.active());
    CHECK_EQ(raised, 1);
    step(true, 3100);            // long press while latched -> local reset
    CHECK_EQ(reset, 1);
    CHECK(!b.active());
    step(false, 100);
    CHECK_EQ(b.operator_reset(), SosButton::NONE);
    step(true, 40);
    CHECK_EQ(b.operator_reset(), SosButton::RESET);
}

TEST(station_impact_excursion) {
    RuleConfig c;
    StationDetector d = make_station(c);
    d.set_tilt_baseline(0, 0, 1000);
    for (int i = 0; i < 200; ++i) {
        float z = (i >= 100 && i < 102) ? 4000.f : 1000.f;  // 3 g excursion for 10 ms
        d.add_accel_mg(i * 5, 0, 0, z);
    }
    umsf_station_t s = d.finish_window(1000, 1, 1, UMSF_NULL_U8);
    auto ev = drain(d);
    CHECK_EQ(count_type(ev, UMSF_EV_IMPACT_EXCURSION), 1);
    const DetectedEvent *e = first_of(ev, UMSF_EV_IMPACT_EXCURSION);
    CHECK(e && e->value_x1000 == 3000 && e->t_ms == 500);
    CHECK_EQ(count_type(ev, UMSF_EV_POSSIBLE_IMPACT_LOCAL), 0);  // impact alone is not the composite
    CHECK_EQ(s.vib_peak_cg, 300);
    CHECK(s.flags & UMSF_SF_IMPACT);
    CHECK_EQ(s.n_imu_samples, 200);
}

TEST(station_tilt_63deg) {
    RuleConfig c;
    StationDetector d = make_station(c);
    // no baseline yet: tilt_delta unknown, attachment uncertain
    still(d, 0);
    umsf_station_t s = d.finish_window(1000, 1, 1, UMSF_NULL_U8);
    CHECK_EQ(s.tilt_delta_ddeg, UMSF_NULL_I16);
    CHECK(s.flags & UMSF_SF_ATTACHMENT_UNCERTAIN);
    CHECK_EQ(s.tilt_ddeg, 0);
    float gx, gy, gz;
    CHECK(d.last_gravity(gx, gy, gz));
    d.set_tilt_baseline(gx, gy, gz);  // commissioning
    still(d, 1000);
    s = d.finish_window(2000, 1, 1, UMSF_NULL_U8);
    CHECK(!(s.flags & UMSF_SF_ATTACHMENT_UNCERTAIN));
    CHECK_EQ(s.tilt_delta_ddeg, 0);
    double a = 63.0 * M_PI / 180.0;
    still(d, 2000, (float)(1000 * std::sin(a)), 0, (float)(1000 * std::cos(a)));
    s = d.finish_window(3000, 1, 1, UMSF_NULL_U8);
    CHECK_EQ(s.tilt_delta_ddeg, 630);
    CHECK_EQ(s.tilt_ddeg, 630);
    CHECK(s.flags & UMSF_SF_TILT_ALARM);
    CHECK(s.flags & UMSF_SF_ATTACHMENT_UNCERTAIN);  // displaced node: earlier interpretation lost
    auto ev = drain(d);
    const DetectedEvent *e = first_of(ev, UMSF_EV_TILT_CHANGE);
    CHECK(e != nullptr);
    if (e) CHECK_NEAR(e->value_x1000, 63000, 5);
    // back to the original position: alarm clears, attachment stays uncertain until recommissioned
    still(d, 3000);
    s = d.finish_window(4000, 1, 1, UMSF_NULL_U8);
    CHECK(!(s.flags & UMSF_SF_TILT_ALARM));
    CHECK(s.flags & UMSF_SF_ATTACHMENT_UNCERTAIN);
}

TEST(station_gas_preheat_hysteresis) {
    RuleConfig c;  // preheat 180 s, on +300 mV, off +150 mV
    StationDetector d = make_station(c);
    uint32_t t = 0;
    for (; t < 170000; t += 100) d.add_gas_mv(t, t < 100000 ? 2000 : 800);  // preheat transient ignored
    CHECK(!d.gas_warm());
    CHECK_EQ(count_type(drain(d), UMSF_EV_GAS_CHANNEL_ALARM), 0);
    for (; t < 200000; t += 100) d.add_gas_mv(t, 800);
    CHECK(d.gas_warm());
    CHECK_EQ(d.last_gas_baseline_mv(), 800);
    for (int i = 0; i < 20; ++i, t += 100) d.add_gas_mv(t, 1200);  // lighter-like rise
    auto ev = drain(d);
    CHECK_EQ(count_type(ev, UMSF_EV_GAS_CHANNEL_ALARM), 1);
    const DetectedEvent *e = first_of(ev, UMSF_EV_GAS_CHANNEL_ALARM);
    CHECK(e && e->value_x1000 == 1200);  // 1.200 V
    CHECK(d.live_flags() & UMSF_SF_GAS_ALARM);
    for (int i = 0; i < 20; ++i, t += 100) d.add_gas_mv(t, 1000);  // +200 mV: above off threshold
    CHECK(d.live_flags() & UMSF_SF_GAS_ALARM);
    CHECK_EQ(d.last_gas_baseline_mv(), 800);  // baseline frozen during the alarm
    for (int i = 0; i < 20; ++i, t += 100) d.add_gas_mv(t, 900);   // +100 mV: clears
    CHECK(!(d.live_flags() & UMSF_SF_GAS_ALARM));
    CHECK(d.last_gas_baseline_mv() <= 802);   // slow EMA resumes after clearing
    umsf_station_t s = d.finish_window(t, 1, 1, UMSF_NULL_U8);
    CHECK(s.sensor_flags & UMSF_SEN_GAS_WARM);
}

TEST(station_pressure_transient) {
    RuleConfig c;
    StationDetector d = make_station(c);
    for (int i = 0; i < 25; ++i) d.add_pressure(i * 40, 100370.f, 21.9f);
    umsf_station_t s = d.finish_window(1000, 1, 1, UMSF_NULL_U8);
    CHECK_EQ(s.pressure_dhpa, 10037);
    CHECK_EQ(s.temp, 2190);
    CHECK_EQ(s.pressure_delta_pa, 0);
    CHECK_EQ(count_type(drain(d), UMSF_EV_PRESSURE_TRANSIENT), 0);
    for (int i = 0; i < 25; ++i) d.add_pressure(1000 + i * 40, i < 10 ? 100370.f : 100520.f, 21.9f);
    s = d.finish_window(2000, 1, 1, UMSF_NULL_U8);
    CHECK_EQ(s.pressure_delta_pa, 150);
    CHECK(s.flags & UMSF_SF_PRESSURE_TRANSIENT);
    auto ev = drain(d);
    CHECK_EQ(count_type(ev, UMSF_EV_PRESSURE_TRANSIENT), 1);
    CHECK(first_of(ev, UMSF_EV_PRESSURE_TRANSIENT)->value_x1000 == 150000);
    // a slow drift of 150 Pa over 10 s is not a transient
    StationDetector d2 = make_station(c);
    for (int i = 0; i < 250; ++i) d2.add_pressure(i * 40, 100370.f + 0.6f * i, 21.9f);
    CHECK_EQ(count_type(drain(d2), UMSF_EV_PRESSURE_TRANSIENT), 0);
}

TEST(station_loud_sound_and_composite) {
    RuleConfig c;
    // impact + loud within 2 s -> possible_impact_local
    StationDetector d = make_station(c);
    for (int i = 0; i < 200; ++i) d.add_accel_mg(i * 5, 0, 0, (i == 40) ? 3500.f : 1000.f);  // t=200 ms
    for (uint32_t t = 0; t < 1000; ++t) d.add_mic(t, (t >= 700 && t < 760) ? (t % 2 ? 3800 : 200) : 2048);
    umsf_station_t s = d.finish_window(1000, 1, 1, UMSF_NULL_U8);
    auto ev = drain(d);
    CHECK_EQ(count_type(ev, UMSF_EV_IMPACT_EXCURSION), 1);
    CHECK_EQ(count_type(ev, UMSF_EV_LOUD_SOUND), 1);
    CHECK_EQ(count_type(ev, UMSF_EV_POSSIBLE_IMPACT_LOCAL), 1);
    const DetectedEvent *e = first_of(ev, UMSF_EV_POSSIBLE_IMPACT_LOCAL);
    CHECK(e && e->value_x1000 == 2500 && e->t_ms == 200 && e->level == UMSF_LVL_WARNING);
    CHECK_EQ(s.sound_index, 3600);
    CHECK(s.flags & UMSF_SF_LOUD_SOUND);

    // impact + pressure transient (pressure first) -> composite
    StationDetector d2 = make_station(c);
    for (int i = 0; i < 25; ++i) d2.add_pressure(i * 40, i < 5 ? 100000.f : 100200.f, 20.f);
    for (int i = 0; i < 200; ++i) d2.add_accel_mg(1500 + i * 5, 0, 0, (i == 10) ? 3000.f : 1000.f);
    d2.tick(2600);
    CHECK_EQ(count_type(drain(d2), UMSF_EV_POSSIBLE_IMPACT_LOCAL), 1);

    // impact and loud sound 3 s apart -> no composite
    StationDetector d3 = make_station(c);
    for (int i = 0; i < 200; ++i) d3.add_accel_mg(i * 5, 0, 0, (i == 10) ? 3000.f : 1000.f);
    for (uint32_t t = 3100; t < 3200; ++t) d3.add_mic(t, t % 2 ? 3800 : 200);
    auto ev3 = drain(d3);
    CHECK_EQ(count_type(ev3, UMSF_EV_IMPACT_EXCURSION), 1);
    CHECK_EQ(count_type(ev3, UMSF_EV_LOUD_SOUND), 1);
    CHECK_EQ(count_type(ev3, UMSF_EV_POSSIBLE_IMPACT_LOCAL), 0);
}

TEST(station_pir_presence_hold) {
    RuleConfig c;
    StationDetector d = make_station(c);
    d.add_pir(1000, true);
    d.add_pir(3000, false);
    d.tick(32999);
    CHECK(d.presence());
    d.tick(33000);
    CHECK(!d.presence());
    auto ev = drain(d);
    CHECK_EQ(count_type(ev, UMSF_EV_PRESENCE), 2);
    CHECK(ev[0].value_x1000 == 1000 && ev[1].value_x1000 == 0);
}

TEST(station_sos_and_unknown_channels) {
    RuleConfig c;
    StationDetector d(c);
    d.begin(0);
    d.set_sensor_ok(false, false, false, false);
    d.set_sos(true);
    umsf_station_t s = d.finish_window(1000, 3, 1, UMSF_NULL_U8);
    CHECK(s.flags & UMSF_SF_SOS_ACTIVE);
    CHECK(!(s.flags & UMSF_SF_PIR_PRESENCE));
    CHECK_EQ(s.vib_peak_cg, UMSF_NULL_U16);
    CHECK_EQ(s.pressure_dhpa, UMSF_NULL_U16);
    CHECK_EQ(s.gas_mv, UMSF_NULL_U16);
    CHECK_EQ(s.sound_index, UMSF_NULL_U16);
    CHECK_EQ(s.tilt_ddeg, UMSF_NULL_I16);
    CHECK_EQ(s.quality_pct, 0);
    CHECK_EQ(s.zone_code, 3);
}

TEST(event_names_never_attribute_strike) {
    for (int t = 1; t <= 13; ++t) {
        const char *n = umsf_event_type_name((uint8_t)t);
        CHECK(n != nullptr);
        if (n) CHECK(std::strstr(n, "missile") == nullptr && std::strstr(n, "strike") == nullptr);
    }
    CHECK_STR(umsf_event_type_name(UMSF_EV_POSSIBLE_IMPACT_LOCAL), "possible_impact_local");
}
