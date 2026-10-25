/*
 * umsf_features.h - portable feature extraction and local detectors (C++17, no heap).
 *
 * Personnel node: PhysioWindow turns 10 s of PPG / IMU / temperature / GSR samples into a
 * PHYSIO_FEATURE payload. Stationary node: StationDetector produces 1 s STATION_STATE
 * summaries and immediate local events. SosButton debounces GPIO27 and latches SOS.
 *
 * Evidence boundary: all outputs are channel features and uncalibrated threshold rules.
 * The optional pulse-rate estimator is UNVALIDATED and disabled by default; SpO2 is always
 * null here. possible_impact_local is an unverified local composite and never a strike
 * attribution. PIR/sound indicate *possible presence*, not vital signs.
 */
#ifndef UMSF_FEATURES_H
#define UMSF_FEATURES_H

#include <stddef.h>
#include <stdint.h>

#include "umsf_config.h"
#include "umsf_proto.h"

namespace umsf {

// ---------------------------------------------------------------- button
class Debouncer {
public:
    explicit Debouncer(uint16_t stable_ms = 30) : stable_ms_(stable_ms) {}
    // raw_pressed: electrical level already converted (active-low input -> pressed = !digitalRead).
    // Returns true when the debounced state changed.
    bool update(bool raw_pressed, uint32_t now_ms);
    bool pressed() const { return state_; }
    uint32_t since_ms() const { return changed_at_; }
private:
    uint16_t stable_ms_;
    bool state_ = false;
    bool candidate_ = false;
    uint32_t candidate_since_ = 0;
    uint32_t changed_at_ = 0;
};

class SosButton {
public:
    enum Action { NONE = 0, RAISED, RESET };
    explicit SosButton(const RuleConfig &c) : deb_(c.button_debounce_ms), hold_ms_(c.button_reset_hold_ms) {}
    // Press -> RAISED (latched). A long press that *starts while already latched* -> RESET.
    Action update(bool raw_pressed, uint32_t now_ms);
    Action operator_reset();  // e.g. stationary web page reset; RESET only if latched
    bool active() const { return active_; }
    uint32_t presses() const { return presses_; }
private:
    Debouncer deb_;
    uint16_t hold_ms_;
    bool active_ = false;
    bool press_started_latched_ = false;
    bool reset_done_this_press_ = false;
    uint32_t presses_ = 0;
};

// ---------------------------------------------------------------- personnel
class PulseEstimator {  // UNVALIDATED peak counter on the IR channel
public:
    void reset(uint16_t rate_hz);
    void add(uint32_t ir, bool valid);
    // bpm x10, or UMSF_NULL_U16 if fewer than 4 accepted beats
    uint16_t bpm_x10() const;
private:
    uint16_t rate_hz_ = 100;
    uint32_t n_ = 0;
    double dc_ = 0, lp_ = 0, prev_ = 0, prev2_ = 0, env_ = 0;
    bool init_ = false;
    uint32_t last_peak_ = 0, first_peak_ = 0, peaks_ = 0;
};

class PhysioWindow {
public:
    explicit PhysioWindow(const RuleConfig &c) : cfg_(c) { reset(); }
    void reset();
    void add_ppg(uint32_t red, uint32_t ir);
    void add_accel_mg(float ax, float ay, float az);
    void add_temp_c100(int16_t t_c100) { temp_ = t_c100; has_temp_ = true; }
    void temp_error() { temp_err_ = true; }
    void imu_error() { imu_err_ = true; }
    void ppg_missing() { ppg_err_ = true; }
    void add_gsr_mv(uint16_t mv) { gsr_sum_ += mv; ++gsr_n_; }
    // Builds the payload. synthetic_seq drives the deterministic synthetic HR test value.
    umsf_physio_t finish(uint16_t window_ms, uint8_t battery_pct, bool sos_active, uint16_t fw_build,
                         uint32_t synthetic_seq) const;
    static uint16_t synthetic_hr_x10(uint32_t seq) { return (uint16_t)(700u + (seq % 11u) * 10u); }
private:
    const RuleConfig &cfg_;
    uint32_t n_ppg_ = 0, n_valid_ = 0, n_contact_ = 0, n_sat_ = 0;
    uint64_t ir_sum_ = 0, red_sum_ = 0;
    uint32_t n_imu_ = 0;
    double dev2_sum_ = 0;
    int16_t temp_ = UMSF_NULL_I16;
    bool has_temp_ = false, temp_err_ = false, imu_err_ = false, ppg_err_ = false;
    uint32_t gsr_sum_ = 0, gsr_n_ = 0;
    PulseEstimator pulse_;
};

// ---------------------------------------------------------------- stationary
struct DetectedEvent {
    uint8_t type;
    uint8_t level;
    int32_t value_x1000;
    uint32_t t_ms;
};

class StationDetector {
public:
    explicit StationDetector(const RuleConfig &c) : cfg_(c) {}
    void begin(uint32_t power_up_ms);

    // Mounting reference: device axis that is "up" when mounted (0=X, 1=Y, 2=Z).
    void set_mount_axis(uint8_t axis) { axis_ = axis > 2 ? 2 : axis; }
    // Gravity vector captured at commissioning (any unit). Unknown baseline -> attachment_uncertain.
    void set_tilt_baseline(float x, float y, float z);
    void clear_tilt_baseline() { has_base_ = false; }
    bool has_tilt_baseline() const { return has_base_; }
    // Current window mean gravity vector, e.g. to capture a baseline at commissioning.
    bool last_gravity(float &x, float &y, float &z) const;

    void add_accel_mg(uint32_t t_ms, float ax, float ay, float az, bool saturated = false);
    void add_pressure(uint32_t t_ms, float pa, float temp_c);
    void add_gas_mv(uint32_t t_ms, uint16_t mv);
    void add_mic(uint32_t t_ms, uint16_t raw);
    void add_pir(uint32_t t_ms, bool level);
    void set_sos(bool active) { sos_ = active; }
    void set_sensor_ok(bool imu, bool bmp, bool mic, bool pir) { imu_ok_ = imu; bmp_ok_ = bmp; mic_ok_ = mic; pir_ok_ = pir; }
    void tick(uint32_t now_ms);  // closes impact episodes, expires PIR hold

    bool pop_event(DetectedEvent &e);
    umsf_station_t finish_window(uint32_t now_ms, uint16_t zone_code, uint16_t fw_build, uint8_t battery_pct);

    // live snapshot (for 200 ms COMPACT packets and the local web page)
    uint16_t live_vib_peak_cg() const { return live_peak_mg_ < 0 ? UMSF_NULL_U16 : (uint16_t)((live_peak_mg_ + 5) / 10); }
    int16_t last_tilt_ddeg() const { return tilt_ddeg_; }
    int16_t last_tilt_delta_ddeg() const { return tilt_delta_ddeg_; }
    uint16_t last_pressure_dhpa() const { return p_dhpa_; }
    int16_t last_temp_c100() const { return temp_c100_; }
    uint16_t last_gas_mv() const { return gas_last_; }
    uint16_t last_gas_baseline_mv() const;
    uint16_t live_sound_index() const { return live_snd_max_ >= live_snd_min_ ? (uint16_t)(live_snd_max_ - live_snd_min_) : UMSF_NULL_U16; }
    void reset_live() { live_peak_mg_ = -1; live_snd_max_ = 0; live_snd_min_ = 0xFFFF; }
    uint8_t live_flags() const;
    bool gas_warm() const { return gas_warm_; }
    bool presence() const { return presence_; }

private:
    void emit(uint8_t type, uint8_t level, int32_t v, uint32_t t);
    bool refractory_ok(uint8_t type, uint32_t t);
    void check_composite(uint32_t t);
    void close_impact();

    const RuleConfig &cfg_;
    uint32_t t0_ = 0;
    uint8_t axis_ = 2;

    // event queue
    static constexpr int QN = 16;
    DetectedEvent q_[QN];
    int qh_ = 0, qn_ = 0;
    uint32_t last_emit_[16] = {0};
    bool emitted_[16] = {false};

    // accel / impact
    uint32_t n_imu_ = 0, n_sat_ = 0;
    float peak_mg_ = -1;
    double dev2_ = 0, gx_ = 0, gy_ = 0, gz_ = 0;
    float lgx_ = 0, lgy_ = 0, lgz_ = 0;
    bool has_lg_ = false;
    bool impact_open_ = false;
    float impact_peak_ = 0;
    uint32_t impact_start_ = 0, impact_last_above_ = 0;
    bool impact_in_window_ = false;
    bool have_impact_ = false;
    uint32_t last_impact_t_ = 0, composite_for_ = 0;
    bool composite_done_ = false;
    float last_impact_peak_ = 0;
    float live_peak_mg_ = -1;

    // tilt
    bool has_base_ = false;
    float bx_ = 0, by_ = 0, bz_ = 1;
    bool tilt_alarm_ = false, tilt_latched_uncertain_ = false;
    int16_t tilt_ddeg_ = UMSF_NULL_I16, tilt_delta_ddeg_ = UMSF_NULL_I16;

    // pressure
    static constexpr int PN = 64;
    uint32_t pt_[PN];
    float pv_[PN];
    int ph_ = 0, pn_ = 0;
    double p_sum_ = 0;
    uint32_t p_n_ = 0;
    float dp_max_ = -1;
    bool p_transient_in_window_ = false;
    bool have_ptrans_ = false;
    uint32_t last_ptrans_t_ = 0;
    uint16_t p_dhpa_ = UMSF_NULL_U16;
    int16_t temp_c100_ = UMSF_NULL_I16;
    double t_sum_ = 0;

    // gas
    bool gas_warm_ = false, gas_alarm_ = false, gas_has_base_ = false;
    double gas_base_ = 0;
    uint32_t gas_last_t_ = 0, gas_sum_ = 0, gas_n_ = 0;
    uint16_t gas_last_ = UMSF_NULL_U16;

    // sound
    uint16_t snd_min_ = 0xFFFF, snd_max_ = 0;
    uint16_t sub_min_ = 0xFFFF, sub_max_ = 0;
    uint32_t sub_start_ = 0;
    bool sub_open_ = false, loud_in_window_ = false, have_loud_ = false;
    uint32_t last_loud_t_ = 0;
    uint16_t live_snd_min_ = 0xFFFF, live_snd_max_ = 0;

    // PIR
    bool pir_level_ = false, presence_ = false;
    uint32_t pir_last_high_ = 0;

    bool sos_ = false;
    bool imu_ok_ = false, bmp_ok_ = false, mic_ok_ = false, pir_ok_ = false;
};

}  // namespace umsf
#endif
