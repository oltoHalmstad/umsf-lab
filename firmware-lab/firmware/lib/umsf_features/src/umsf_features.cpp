// umsf_features.cpp - see umsf_features.h
#include "umsf_features.h"

#include <math.h>
#include <stdlib.h>

namespace umsf {

namespace {
constexpr double kPi = 3.14159265358979323846;
inline int32_t dt(uint32_t a, uint32_t b) { return (int32_t)(a - b); }  // a - b, wrap-safe
inline uint16_t clamp_u16(double v) { return v < 0 ? 0 : v > 65534.0 ? 65534 : (uint16_t)(v + 0.5); }
inline int16_t round_i16(double v) {
    if (v > 32767.0) return 32767;
    if (v < -32767.0) return -32767;  // -32768 is the null sentinel
    return (int16_t)lround(v);
}
double angle_deg(double ax, double ay, double az, double bx, double by, double bz) {
    double na = sqrt(ax * ax + ay * ay + az * az), nb = sqrt(bx * bx + by * by + bz * bz);
    if (na <= 0 || nb <= 0) return NAN;
    double c = (ax * bx + ay * by + az * bz) / (na * nb);
    if (c > 1) c = 1;
    if (c < -1) c = -1;
    return acos(c) * 180.0 / kPi;
}
}  // namespace

// ================================================================ button
bool Debouncer::update(bool raw, uint32_t now) {
    if (raw != candidate_) {
        candidate_ = raw;
        candidate_since_ = now;
        return false;
    }
    if (candidate_ != state_ && (uint32_t)(now - candidate_since_) >= stable_ms_) {
        state_ = candidate_;
        changed_at_ = now;
        return true;
    }
    return false;
}

SosButton::Action SosButton::update(bool raw, uint32_t now) {
    if (deb_.update(raw, now) && deb_.pressed()) {
        ++presses_;
        press_started_latched_ = active_;
        reset_done_this_press_ = false;
        if (!active_) {
            active_ = true;
            return RAISED;
        }
    }
    if (deb_.pressed() && press_started_latched_ && !reset_done_this_press_ &&
        (uint32_t)(now - deb_.since_ms()) >= hold_ms_) {
        active_ = false;
        reset_done_this_press_ = true;
        return RESET;
    }
    return NONE;
}

SosButton::Action SosButton::operator_reset() {
    if (!active_) return NONE;
    active_ = false;
    return RESET;
}

// ================================================================ pulse (UNVALIDATED)
void PulseEstimator::reset(uint16_t rate_hz) {
    *this = PulseEstimator();
    rate_hz_ = rate_hz ? rate_hz : 100;
}

void PulseEstimator::add(uint32_t ir, bool valid) {
    ++n_;
    if (!valid) {  // a gap breaks beat-to-beat continuity: restart from the next valid segment
        init_ = false;
        peaks_ = 0;
        return;
    }
    double x = (double)ir;
    if (!init_) {
        dc_ = x;
        lp_ = prev_ = prev2_ = env_ = 0;
        init_ = true;
        return;
    }
    dc_ += (x - dc_) / (0.75 * rate_hz_);  // ~0.75 s DC tracker
    lp_ += ((x - dc_) - lp_) * 0.3;         // light smoothing
    env_ = fmax(env_ * 0.995, fabs(lp_));
    uint32_t idx = n_ - 2;                   // index of prev_
    if (env_ > 0 && prev_ > prev2_ && prev_ >= lp_ && prev_ > 0.4 * env_) {
        uint32_t refractory = (uint32_t)(0.33 * rate_hz_);  // <= ~180 bpm
        if (peaks_ == 0 || idx - last_peak_ >= refractory) {
            if (peaks_ == 0) first_peak_ = idx;
            last_peak_ = idx;
            ++peaks_;
        }
    }
    prev2_ = prev_;
    prev_ = lp_;
}

uint16_t PulseEstimator::bpm_x10() const {
    if (peaks_ < 4 || last_peak_ <= first_peak_) return UMSF_NULL_U16;
    double bpm = 60.0 * (peaks_ - 1) * rate_hz_ / (double)(last_peak_ - first_peak_);
    if (bpm < 30 || bpm > 220) return UMSF_NULL_U16;
    return (uint16_t)lround(bpm * 10);
}

// ================================================================ personnel window
void PhysioWindow::reset() {
    n_ppg_ = n_valid_ = n_contact_ = n_sat_ = 0;
    ir_sum_ = red_sum_ = 0;
    n_imu_ = 0;
    dev2_sum_ = 0;
    temp_ = UMSF_NULL_I16;
    has_temp_ = temp_err_ = imu_err_ = ppg_err_ = false;
    gsr_sum_ = gsr_n_ = 0;
    pulse_.reset(cfg_.ppg_rate_hz);
}

void PhysioWindow::add_ppg(uint32_t red, uint32_t ir) {
    ++n_ppg_;
    ir_sum_ += ir;
    red_sum_ += red;
    bool contact = ir >= cfg_.ppg_contact_min_ir;
    bool sat = ir >= cfg_.ppg_saturation_ir || red >= cfg_.ppg_saturation_ir;
    if (contact) ++n_contact_;
    if (sat) ++n_sat_;
    bool valid = contact && !sat;
    if (valid) ++n_valid_;
    if (cfg_.pulse_estimator_enabled) pulse_.add(ir, valid);
}

void PhysioWindow::add_accel_mg(float ax, float ay, float az) {
    double dev = sqrt((double)ax * ax + (double)ay * ay + (double)az * az) - 1000.0;
    dev2_sum_ += dev * dev;
    ++n_imu_;
}

umsf_physio_t PhysioWindow::finish(uint16_t window_ms, uint8_t battery_pct, bool sos_active, uint16_t fw_build,
                                   uint32_t synthetic_seq) const {
    umsf_physio_t p;
    umsf_physio_set_null(&p);
    p.window_ms = window_ms;
    p.fw_build = fw_build;
    p.battery_pct = battery_pct;
    uint32_t exp_ppg = (uint32_t)window_ms * cfg_.ppg_rate_hz / 1000u;
    uint32_t exp_imu = (uint32_t)window_ms * cfg_.imu_rate_hz / 1000u;
    uint8_t cf = 0, af = 0;
    int32_t q = -1;  // permille, -1 = no channel
    auto qmin = [&q](int32_t v) { q = (q < 0 || v < q) ? v : q; };
    auto completeness = [](uint32_t n, uint32_t e) -> int32_t { return e == 0 ? 1000 : (int32_t)(n >= e ? 1000 : n * 1000ull / e); };

    p.n_ppg_samples = (uint16_t)(n_ppg_ > 0xFFFF ? 0xFFFF : n_ppg_);
    p.n_imu_samples = (uint16_t)(n_imu_ > 0xFFFF ? 0xFFFF : n_imu_);

    if (n_ppg_ > 0) {
        cf |= UMSF_CH_PPG;
        p.ppg_ir_mean = (uint32_t)(ir_sum_ / n_ppg_);
        uint64_t r16 = red_sum_ / n_ppg_ / 16u;
        p.ppg_red_mean_div16 = (uint16_t)(r16 > 0xFFFE ? 0xFFFE : r16);
        p.ppg_valid_permille = (uint16_t)(n_valid_ * 1000ull / n_ppg_);
        if (n_contact_ * 2u < n_ppg_) af |= UMSF_AF_NO_CONTACT;
        if (n_sat_ * 100u > n_ppg_) af |= UMSF_AF_SATURATION;
        qmin((int32_t)p.ppg_valid_permille * completeness(n_ppg_, exp_ppg) / 1000);
    }
    if ((n_ppg_ > 0 || ppg_err_) && (uint64_t)n_ppg_ * 1000u < (uint64_t)exp_ppg * cfg_.sample_gap_permille)
        af |= UMSF_AF_SAMPLE_GAP;

    if (n_imu_ > 0) {
        cf |= UMSF_CH_MOTION;
        double rms = sqrt(dev2_sum_ / n_imu_);
        p.motion_rms_mg = clamp_u16(rms);
        if (rms > cfg_.motion_artifact_mg) af |= UMSF_AF_MOTION_ARTIFACT;
        qmin(completeness(n_imu_, exp_imu));
        if ((uint64_t)n_imu_ * 1000u < (uint64_t)exp_imu * cfg_.sample_gap_permille) af |= UMSF_AF_SAMPLE_GAP;
    }
    if (imu_err_) af |= UMSF_AF_IMU_ERROR;

    if (has_temp_) {
        cf |= UMSF_CH_T;
        p.skin_temp = temp_;
        qmin(1000);
    }
    if (temp_err_) af |= UMSF_AF_TEMP_ERROR;

    if (gsr_n_ > 0) {
        cf |= UMSF_CH_GSR;
        p.gsr_mv = (uint16_t)(gsr_sum_ / gsr_n_);
    }

    if (cfg_.synthetic_hr_enabled) {
        p.hr = synthetic_hr_x10(synthetic_seq);  // bench test field, never a measurement
        cf |= UMSF_CH_HR_SYNTHETIC;
    } else if (cfg_.pulse_estimator_enabled && n_ppg_ > 0 && p.ppg_valid_permille >= cfg_.ppg_min_valid_permille) {
        p.hr = pulse_.bpm_x10();  // UNVALIDATED estimate, may stay null
    }
    p.spo2 = UMSF_NULL_U16;  // no validated estimator (paper A.2)
    if (sos_active) cf |= UMSF_CH_SOS_ACTIVE;

    if (q >= 0) {
        if (af & UMSF_AF_MOTION_ARTIFACT) q /= 2;
        p.quality_pct = (uint8_t)(q / 10);
    }
    p.channel_flags = cf;
    p.artifact_flags = af;
    return p;
}

// ================================================================ stationary
void StationDetector::begin(uint32_t now) {
    t0_ = now;
    gas_warm_ = gas_alarm_ = gas_has_base_ = false;
    gas_last_t_ = now;
    reset_live();
}

void StationDetector::set_tilt_baseline(float x, float y, float z) {
    bx_ = x; by_ = y; bz_ = z;
    has_base_ = true;
    tilt_alarm_ = false;
    tilt_latched_uncertain_ = false;
}

bool StationDetector::last_gravity(float &x, float &y, float &z) const {
    if (!has_lg_) return false;
    x = lgx_; y = lgy_; z = lgz_;
    return true;
}

bool StationDetector::refractory_ok(uint8_t type, uint32_t t) {
    if (type >= 16) return true;
    return !(emitted_[type] && (uint32_t)(t - last_emit_[type]) < cfg_.event_refractory_ms);
}

void StationDetector::emit(uint8_t type, uint8_t level, int32_t v, uint32_t t) {
    if (type < 16) { emitted_[type] = true; last_emit_[type] = t; }
    if (qn_ == QN) { qh_ = (qh_ + 1) % QN; --qn_; }  // drop the oldest undelivered local event
    q_[(qh_ + qn_) % QN] = DetectedEvent{type, level, v, t};
    ++qn_;
}

bool StationDetector::pop_event(DetectedEvent &e) {
    if (!qn_) return false;
    e = q_[qh_];
    qh_ = (qh_ + 1) % QN;
    --qn_;
    return true;
}

void StationDetector::check_composite(uint32_t) {
    if (!have_impact_ || composite_done_) return;
    int32_t w = cfg_.composite_window_ms;
    bool loud = have_loud_ && abs(dt(last_loud_t_, last_impact_t_)) <= w;
    bool pres = have_ptrans_ && abs(dt(last_ptrans_t_, last_impact_t_)) <= w;
    if (loud || pres) {
        composite_done_ = true;
        // unverified local composite; never a strike attribution (protocol 0.8)
        emit(UMSF_EV_POSSIBLE_IMPACT_LOCAL, UMSF_LVL_WARNING, (int32_t)lround(last_impact_peak_), last_impact_t_);
    }
}

void StationDetector::close_impact() {
    impact_open_ = false;
    impact_in_window_ = true;
    have_impact_ = true;
    last_impact_t_ = impact_start_;
    last_impact_peak_ = impact_peak_;
    composite_done_ = false;
    if (refractory_ok(UMSF_EV_IMPACT_EXCURSION, impact_start_))
        emit(UMSF_EV_IMPACT_EXCURSION, UMSF_LVL_WARNING, (int32_t)lround(impact_peak_), impact_start_);  // mg == g x1000
    check_composite(impact_start_);
}

void StationDetector::add_accel_mg(uint32_t t, float ax, float ay, float az, bool saturated) {
    ++n_imu_;
    if (saturated) ++n_sat_;
    float dev = fabsf(sqrtf(ax * ax + ay * ay + az * az) - 1000.0f);
    if (dev > peak_mg_) peak_mg_ = dev;
    if (dev > live_peak_mg_) live_peak_mg_ = dev;
    dev2_ += (double)dev * dev;
    gx_ += ax; gy_ += ay; gz_ += az;
    float thr = cfg_.impact_threshold_cg * 10.0f;
    if (dev >= thr) {
        if (!impact_open_) { impact_open_ = true; impact_start_ = t; impact_peak_ = dev; }
        if (dev > impact_peak_) impact_peak_ = dev;
        impact_last_above_ = t;
    } else if (impact_open_ && (uint32_t)(t - impact_last_above_) >= 50) {
        close_impact();
    }
}

void StationDetector::add_pressure(uint32_t t, float pa, float temp_c) {
    while (pn_ > 0 && (uint32_t)(t - pt_[ph_]) > cfg_.pressure_window_ms) { ph_ = (ph_ + 1) % PN; --pn_; }
    float dp = 0;
    for (int i = 0; i < pn_; ++i) {
        float d = fabsf(pa - pv_[(ph_ + i) % PN]);
        if (d > dp) dp = d;
    }
    if (pn_ == PN) { ph_ = (ph_ + 1) % PN; --pn_; }
    pt_[(ph_ + pn_) % PN] = t;
    pv_[(ph_ + pn_) % PN] = pa;
    ++pn_;
    if (dp > dp_max_) dp_max_ = dp;
    p_sum_ += pa;
    t_sum_ += temp_c;
    ++p_n_;
    p_dhpa_ = clamp_u16(pa / 10.0);
    temp_c100_ = round_i16(temp_c * 100.0);
    if (dp >= cfg_.pressure_transient_pa) {
        p_transient_in_window_ = true;
        have_ptrans_ = true;
        last_ptrans_t_ = t;
        if (refractory_ok(UMSF_EV_PRESSURE_TRANSIENT, t))
            emit(UMSF_EV_PRESSURE_TRANSIENT, UMSF_LVL_NOTICE, (int32_t)lround(dp * 1000.0), t);
        check_composite(t);
    }
}

void StationDetector::add_gas_mv(uint32_t t, uint16_t mv) {
    gas_last_ = mv;
    gas_sum_ += mv;
    ++gas_n_;
    if (!gas_warm_) {  // preheat lockout: no baseline, no alarm
        if ((uint32_t)(t - t0_) >= cfg_.gas_preheat_ms) {
            gas_warm_ = true;
            gas_base_ = mv;
            gas_has_base_ = true;
            gas_last_t_ = t;
        }
        return;
    }
    uint32_t d = t - gas_last_t_;
    gas_last_t_ = t;
    double rise = (double)mv - gas_base_;
    if (!gas_alarm_) {
        if (rise >= cfg_.gas_rise_on_mv) {
            gas_alarm_ = true;
            emit(UMSF_EV_GAS_CHANNEL_ALARM, UMSF_LVL_WARNING, (int32_t)mv, t);  // V x1000 == mV
        } else {
            double a = d / (cfg_.gas_baseline_tau_s * 1000.0);
            gas_base_ += ((double)mv - gas_base_) * (a > 1 ? 1 : a);
        }
    } else if (rise < cfg_.gas_rise_off_mv) {
        gas_alarm_ = false;
    }
}

uint16_t StationDetector::last_gas_baseline_mv() const {
    return gas_has_base_ ? clamp_u16(gas_base_) : UMSF_NULL_U16;
}

void StationDetector::add_mic(uint32_t t, uint16_t raw) {
    if (raw < snd_min_) snd_min_ = raw;
    if (raw > snd_max_) snd_max_ = raw;
    if (raw < live_snd_min_) live_snd_min_ = raw;
    if (raw > live_snd_max_) live_snd_max_ = raw;
    if (!sub_open_) {
        sub_open_ = true;
        sub_start_ = t;
        sub_min_ = sub_max_ = raw;
        return;
    }
    if (raw < sub_min_) sub_min_ = raw;
    if (raw > sub_max_) sub_max_ = raw;
    if ((uint32_t)(t - sub_start_) >= cfg_.sound_subwindow_ms) {
        uint16_t p2p = (uint16_t)(sub_max_ - sub_min_);
        sub_open_ = false;
        if (p2p >= cfg_.loud_sound_p2p) {
            loud_in_window_ = true;
            have_loud_ = true;
            last_loud_t_ = t;
            if (refractory_ok(UMSF_EV_LOUD_SOUND, t)) emit(UMSF_EV_LOUD_SOUND, UMSF_LVL_NOTICE, (int32_t)p2p * 1000, t);
            check_composite(t);
        }
    }
}

void StationDetector::add_pir(uint32_t t, bool level) {
    if (level || pir_level_) pir_last_high_ = t;  // high, or the falling edge
    if (level && !presence_) {
        presence_ = true;
        emit(UMSF_EV_PRESENCE, UMSF_LVL_INFO, 1000, t);
    }
    pir_level_ = level;
}

void StationDetector::tick(uint32_t now) {
    if (impact_open_ && (uint32_t)(now - impact_last_above_) >= 50) close_impact();
    if (presence_ && !pir_level_ && (uint32_t)(now - pir_last_high_) >= cfg_.pir_hold_ms) {
        presence_ = false;
        emit(UMSF_EV_PRESENCE, UMSF_LVL_INFO, 0, now);
    }
}

uint8_t StationDetector::live_flags() const {
    uint8_t f = 0;
    if (pir_ok_ && presence_) f |= UMSF_SF_PIR_PRESENCE;
    if (sos_) f |= UMSF_SF_SOS_ACTIVE;
    if (impact_open_ || impact_in_window_) f |= UMSF_SF_IMPACT;
    if (loud_in_window_) f |= UMSF_SF_LOUD_SOUND;
    if (gas_alarm_) f |= UMSF_SF_GAS_ALARM;
    if (tilt_alarm_) f |= UMSF_SF_TILT_ALARM;
    if (p_transient_in_window_) f |= UMSF_SF_PRESSURE_TRANSIENT;
    if (!has_base_ || tilt_latched_uncertain_) f |= UMSF_SF_ATTACHMENT_UNCERTAIN;
    return f;
}

umsf_station_t StationDetector::finish_window(uint32_t now, uint16_t zone, uint16_t fw, uint8_t battery) {
    tick(now);
    umsf_station_t s;
    umsf_station_set_null(&s);
    s.window_ms = cfg_.station_window_ms;
    s.zone_code = zone;
    s.fw_build = fw;
    s.battery_pct = battery;
    s.n_imu_samples = (uint16_t)(n_imu_ > 0xFFFF ? 0xFFFF : n_imu_);

    if (n_imu_ > 0) {
        s.vib_peak_cg = clamp_u16(peak_mg_ / 10.0);
        s.accel_rms_mg = clamp_u16(sqrt(dev2_ / n_imu_));
        lgx_ = (float)(gx_ / n_imu_); lgy_ = (float)(gy_ / n_imu_); lgz_ = (float)(gz_ / n_imu_);
        has_lg_ = true;
        double ax = axis_ == 0, ay = axis_ == 1, az = axis_ == 2;
        double tilt = angle_deg(lgx_, lgy_, lgz_, ax, ay, az);
        tilt_ddeg_ = isnan(tilt) ? UMSF_NULL_I16 : round_i16(tilt * 10.0);
        if (has_base_) {
            double d = angle_deg(lgx_, lgy_, lgz_, bx_, by_, bz_);
            tilt_delta_ddeg_ = isnan(d) ? UMSF_NULL_I16 : round_i16(d * 10.0);
            if (!isnan(d)) {
                if (!tilt_alarm_ && d * 10.0 >= cfg_.tilt_alarm_ddeg) {
                    tilt_alarm_ = true;
                    tilt_latched_uncertain_ = true;  // displaced node loses its structural interpretation
                    emit(UMSF_EV_TILT_CHANGE, UMSF_LVL_WARNING, (int32_t)lround(d * 1000.0), now);
                } else if (tilt_alarm_ && d * 10.0 < cfg_.tilt_alarm_ddeg * 0.8) {
                    tilt_alarm_ = false;  // attachment stays uncertain until recommissioned
                }
            }
        } else {
            tilt_delta_ddeg_ = UMSF_NULL_I16;
        }
    } else {
        tilt_ddeg_ = tilt_delta_ddeg_ = UMSF_NULL_I16;
    }
    s.tilt_ddeg = tilt_ddeg_;
    s.tilt_delta_ddeg = tilt_delta_ddeg_;

    if (p_n_ > 0) {
        s.pressure_dhpa = clamp_u16(p_sum_ / p_n_ / 10.0);
        s.pressure_delta_pa = dp_max_ < 0 ? 0 : round_i16(dp_max_);
        s.temp = round_i16(t_sum_ / p_n_ * 100.0);
    }
    if (gas_n_ > 0) {
        s.gas_mv = (uint16_t)(gas_sum_ / gas_n_);
        s.gas_baseline_mv = last_gas_baseline_mv();
    }
    if (snd_max_ >= snd_min_) s.sound_index = (uint16_t)(snd_max_ - snd_min_);

    s.flags = live_flags();
    s.sensor_flags = (imu_ok_ ? UMSF_SEN_IMU_OK : 0) | (bmp_ok_ ? UMSF_SEN_BMP_OK : 0) |
                     (gas_warm_ ? UMSF_SEN_GAS_WARM : 0) | (mic_ok_ ? UMSF_SEN_MIC_OK : 0) |
                     (pir_ok_ ? UMSF_SEN_PIR_OK : 0);

    // heuristic quality: mean channel availability, IMU weighted by completeness and saturation
    uint32_t exp_imu = (uint32_t)cfg_.station_window_ms * cfg_.station_imu_rate_hz / 1000u;
    double imu_q = !imu_ok_ || exp_imu == 0 ? 0.0 : fmin(1.0, (double)n_imu_ / exp_imu);
    if (n_imu_ > 0) imu_q *= 1.0 - (double)n_sat_ / n_imu_;
    double qsum = imu_q + (bmp_ok_ && p_n_ > 0) + gas_warm_ + (mic_ok_ && snd_max_ >= snd_min_) + pir_ok_;
    s.quality_pct = (uint8_t)lround(qsum / 5.0 * 100.0);

    // reset window accumulators
    n_imu_ = n_sat_ = 0;
    peak_mg_ = -1;
    dev2_ = gx_ = gy_ = gz_ = 0;
    impact_in_window_ = false;
    p_sum_ = t_sum_ = 0;
    p_n_ = 0;
    dp_max_ = -1;
    p_transient_in_window_ = false;
    gas_sum_ = gas_n_ = 0;
    snd_min_ = 0xFFFF;
    snd_max_ = 0;
    loud_in_window_ = false;
    return s;
}

}  // namespace umsf
