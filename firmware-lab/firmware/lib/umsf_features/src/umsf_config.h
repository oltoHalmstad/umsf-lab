/*
 * umsf_config.h - all detector / feature thresholds in one versioned struct.
 *
 * Every number below is an initial, UNCALIBRATED engineering default chosen for this
 * implementation (not a value from the paper unless marked "paper"). rule_version is
 * written into every EVENT frame so a site agent can reconstruct which rules produced it.
 * Freeze the struct (and bump rule_version on any change) after commissioning (paper A.2).
 */
#ifndef UMSF_CONFIG_H
#define UMSF_CONFIG_H

#include <stdint.h>

namespace umsf {

struct RuleConfig {
    uint16_t rule_version = 1;

    // ---- personnel node ----
    uint16_t feature_window_ms = 10000;     // paper: one feature record every 10 s
    uint16_t ppg_rate_hz = 100;             // paper Table 4
    uint16_t imu_rate_hz = 25;              // paper Table 4 (personnel)
    uint32_t ppg_contact_min_ir = 50000;    // raw IR counts below this = no finger/skin contact
    uint32_t ppg_saturation_ir = 260000;    // 18-bit ADC full scale is 262143
    uint16_t ppg_min_valid_permille = 800;  // pulse estimator needs >= 80 % valid samples
    uint16_t motion_artifact_mg = 150;      // motion RMS above this flags motion_artifact
    uint16_t sample_gap_permille = 950;     // < 95 % of expected samples -> sample_gap
    bool pulse_estimator_enabled = false;   // UNVALIDATED peak counter, off by default (paper 4.6, A.2)
    bool synthetic_hr_enabled = false;      // bench synthetic HR test field (paper Stage 1)

    // ---- button (GPIO27) ----
    uint16_t button_debounce_ms = 30;
    uint16_t button_reset_hold_ms = 3000;   // long press = local reset of the latched SOS

    // ---- stationary node ----
    uint16_t station_window_ms = 1000;      // STATION_STATE every 1 s
    uint16_t station_imu_rate_hz = 200;     // impact capture rate (not the wearable 25 Hz setting)
    uint16_t impact_threshold_cg = 150;     // |a|-1g >= 1.5 g -> impact excursion
    uint16_t tilt_alarm_ddeg = 50;          // >= 5.0 deg change vs. commissioning baseline
    uint16_t pressure_window_ms = 1000;     // |dp| evaluated over 1 s
    uint16_t pressure_transient_pa = 100;   // >= 100 Pa within 1 s
    uint16_t gas_rise_on_mv = 300;          // alarm when gas_mv - baseline >= 300 mV
    uint16_t gas_rise_off_mv = 150;         // clear when below 150 mV (hysteresis)
    uint32_t gas_preheat_ms = 180000;       // MQ-2 heater lockout after power-up (bench value)
    uint16_t gas_baseline_tau_s = 300;      // baseline EMA time constant when not alarmed
    uint16_t loud_sound_p2p = 1500;         // mic peak-to-peak ADC counts (0..4095)
    uint16_t sound_subwindow_ms = 50;       // peak-to-peak sub-window for loud detection
    uint32_t pir_hold_ms = 30000;           // keep "possible presence" for 30 s after last PIR edge
    uint16_t composite_window_ms = 2000;    // impact + (loud | pressure) within 2 s (protocol 2.4)
    uint16_t event_refractory_ms = 2000;    // minimum spacing of repeated events of one type
};

}  // namespace umsf
#endif
