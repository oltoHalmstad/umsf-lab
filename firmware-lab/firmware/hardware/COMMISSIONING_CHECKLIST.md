# Commissioning and qualification checklist

Derived from Appendix A.2 of the manuscript and protocol v0.2 EN. Commissioning records stay **outside**
the evaluation series. Record every item with date, operator, unit serial, firmware build (`fw_build`) and
`rule_version`.

## 1. Before assembly (one documented node + one gateway first)

- [ ] Board layout photographed and documented. Supply ratings checked.
- [ ] Voltage levels measured: I2C idle levels at 3.3 V; no 5 V on any GPIO; MQ-2 divider output ≤ 3.3 V.
- [ ] Pull-ups checked: one I2C pull-up set (2.2–4.7 kΩ); DS18B20 4.7 kΩ to 3.3 V.
- [ ] Bus addresses checked with an I2C scan: MAX30102 0x57, MPU-6050 0x68, BMP280 0x76/0x77.
- [ ] Only then replicate the assembly.

## 2. Firmware and enrollment

- [ ] `include/secrets.h` created from `secrets.example.h`; no real secrets in the repository.
- [ ] Unique `UMSF_DEVICE_ID` and passkey per node; gateway enrollment table updated (address, passkey, zone).
- [ ] Node enrolled: hold the button at power-up, then the gateway pairs with LE Secure Connections + passkey (MITM).
- [ ] After enrollment, an unbonded central is rejected (test with a phone BLE scanner app).
- [ ] Advertising checked with a scanner: only `UMSF-<id>` and manufacturer data `FFFF` + class byte, no physiology.
- [ ] Gateway TLS credentials loaded (LittleFS); broker rejects a client without a valid certificate.
- [ ] Test credentials cannot publish to the live broker (paper 3.3.7).

## 3. Two-hour qualification run (per node + gateway)

- [ ] 2 h continuous run: acquisition, heating, intermittent connections, reboot behaviour, power-bank shutdown.
- [ ] Rates verified from `n_ppg_samples` ≈ 1000, `n_imu_samples` ≈ 250, `window_ms` = 10000 per record;
      DS18B20 1 conversion/s; `sample_gap` flag rate recorded.
- [ ] One feature record every 10 s: `SLOT` lines continuous; no unexplained sequence gaps.
- [ ] Reboot test: `boot_id` increments and `sequence` restarts at 1; no identity reused.
- [ ] Disconnect test: gateway emits `link_loss` and `link_restored`; node resends unacked records; site agent deduplicates.
- [ ] Buffer test: with the broker stopped, the node holds ≥ 30 records and the gateway ≥ 18. Then force
      overflow: `buffer_eviction` event and `EVICT` line appear; `evicted_total` increases.
- [ ] Power-bank shutdown observed and documented (RAM buffers are lost, as designed).

## 4. Temperature calibration (contact temperature only)

- [ ] Reference bath/block at **25, 32 and 37 °C**, three independent equilibration cycles each.
- [ ] Separate verification cycle at each temperature.
- [ ] Criterion: |corrected residual| + expanded comparison uncertainty ≤ 0.5 °C.
- [ ] Correction coefficients and calibration ID recorded (they are not applied in firmware 1.0.0).
- [ ] Record what this qualifies: acquisition and contact temperature only. It is not core temperature or diagnosis.

## 5. IMU checks

- [ ] Six stationary orientations (±X, ±Y, ±Z up): magnitude ≈ 1000 mg, motion RMS near 0.
- [ ] Documented movement sequence; `motion_artifact` flag behaviour recorded.
- [ ] Stationary node: mount on the documented support, capture the tilt baseline, verify
      `attachment_uncertain` clears, tilt the node and verify `tilt_change` and the latch.

## 6. Stationary-node bench checks (descriptive, uncalibrated)

- [ ] MQ-2 preheat lockout: no alarm during the first 180 s.
- [ ] SOS: press, then the event appears in the gateway log within the upper delay bound; operator reset logged as an action.
- [ ] Impact / loud sound / pressure transient each logged; the composite `possible_impact_local` appears only
      with impact + (loud or pressure) within 2 s; the UI says «можливий удар — не верифіковано».
- [ ] Link loss: power off the node, then the gateway shows "unknown/stale" within 2 s (COMPACT staleness), never "collapse".

## 7. Clock

- [ ] Time exchanges before, during and after runs and after reboot to establish offset, drift and uncertainty.
- [ ] Combined timing uncertainty ≤ 0.5 s for latency acceptance; unknown timing does not count as timely.

## 8. Freeze

- [ ] Configuration, firmware build, `rule_version`, sample-loss counters and processing rules **frozen** after
      commissioning; hashes of the firmware images and of `platformio.ini` recorded.
- [ ] SpO2 stays null; the synthetic HR field is enabled only for synthetic-payload runs and is flagged `HR_SYNTHETIC`.
