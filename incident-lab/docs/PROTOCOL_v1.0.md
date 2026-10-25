# UMSF Evidence-Aware Monitoring — Shared Protocol Specification v1.0

Shared by three projects:
- **P1 `umsf-incident-dataset`** — dataset collection (Python): ingestion, validation, storage, export.
- **P2 `umsf-ble-firmware`** — ESP32 firmware: personnel node, stationary (building-state) node, BLE gateway.
- **P3 `umsf-incident-ai-agent`** — AI decision-support agent (Python): rescue logistics and consequence-liquidation logistics.

Source: manuscript "Evidence-Aware Multisensor Monitoring for Critical Infrastructure Incident Support"
(Torstensson, Prokopovych-Tkachenko, Adilzhanova, Tykhonenko, Beketova, Sydybayeva, 2026).
All numbers below that come from the paper are cited by section/table. Everything else is a design
choice of this implementation and is labelled as such.

## 0. Non-negotiable semantics (from the paper)

1. Missing measurements are `null`, never zero/normal (Sec. 3.3.8).
2. Measurement identity = (site_id, device_id, boot_id, sequence). Identical redelivery is idempotent;
   changed immutable payload under same identity = **conflict** → quarantined, whole identity excluded
   from analysis, retained for audit (Sec. 3.3.4, Table 12).
3. Freshness is separate from deduplication: a delayed first arrival may enter history but not the current
   60 s window (Sec. 3.3.4, 3.3.8).
4. Summaries use an explicit roster, not "devices that happened to report" (Sec. 3.3.8).
5. Stationary nodes are never counted as workers (Sec. 3.4.4, 3.8.1).
6. SOS / urgent assistance bypasses group rules and has independent delivery priority (Sec. 3.6.4, 4.2).
7. Link loss → current evidence becomes `unknown`; never "collapse"/"casualty" (Sec. 3.4.4, 3.8.3).
8. The system never attributes a strike from a local sensor: "missile strike" comes only from an
   authoritative external source; local composite = `possible_impact_local` (unverified) (Sec. 3.8.1).
9. No actuation: no output stops a process, operates ventilation, unlocks, switches power (Sec. 3.3.5).
10. HR from bench firmware is a synthetic test field unless a validated estimator exists; SpO2 stays
    `null` by default (Sec. 4.6, A.2).

## 1. BLE GATT (personnel and stationary nodes are GATT peripherals; gateway is central)

Service UUID: `6e5a0001-55f0-4c1b-9b6a-0d3c2b7a5e01`

| Characteristic | UUID | Props | Direction | Content |
|---|---|---|---|---|
| TELEMETRY | `6e5a0002-55f0-4c1b-9b6a-0d3c2b7a5e01` | notify | node→gw | framed records (Sec. 2), fragmented if > MTU-3 |
| EVENT | `6e5a0003-55f0-4c1b-9b6a-0d3c2b7a5e01` | notify, indicate | node→gw | EVENT frames, sent immediately, priority over telemetry |
| ACK | `6e5a0004-55f0-4c1b-9b6a-0d3c2b7a5e01` | write | gw→node | ACK frame (application ack after site-agent commit) |
| STATUS | `6e5a0005-55f0-4c1b-9b6a-0d3c2b7a5e01` | read, notify | node→gw | STATUS frame |
| CONFIG | `6e5a0006-55f0-4c1b-9b6a-0d3c2b7a5e01` | write (encrypted, bonded) | gw→node | CONFIG frame |
| COMPACT | `6e5a0007-55f0-4c1b-9b6a-0d3c2b7a5e01` | notify | stationary→gw | 20-byte compact state, every 200 ms (Sec. 3.4.4 design) |

Physiological values are never placed in advertisements (Sec. 3.3.7). Advertising name: `UMSF-<device_id>`,
manufacturer data: company 0xFFFF + source_class byte only.
Security: LE Secure Connections, bonding, MITM with passkey (enrollment), characteristics require encryption.
Requested MTU: 247.

## 2. Frame format (all multi-byte fields little-endian)

### 2.1 Common header — 18 bytes

| Off | Size | Field | Notes |
|---|---|---|---|
| 0 | 1 | magic | `0xB5` |
| 1 | 1 | version | `1` |
| 2 | 1 | source_class | 1 = personnel_node, 2 = stationary_node, 3 = gateway |
| 3 | 1 | frame_type | 1 PHYSIO_FEATURE, 2 STATION_STATE, 3 EVENT, 4 STATUS, 5 ACK, 6 CONFIG |
| 4 | 4 | device_id | ASCII, NUL-padded, e.g. `"A01\0"` |
| 8 | 2 | boot_id | u16, incremented in NVS at every boot |
| 10 | 4 | sequence | u32, per boot, starts at 1 |
| 14 | 4 | node_time_ms | u32 uptime ms at window end / event |

Then `payload` (length fixed by frame_type), then **CRC-16/CCITT-FALSE** (poly 0x1021, init 0xFFFF,
no reflection, xorout 0) over header+payload, 2 bytes little-endian. CRC detects corruption only — it is
not authentication.

Null sentinels: u16 → `0xFFFF`, i16 → `-32768` (`0x8000`), u8 → `0xFF`, u32 → `0xFFFFFFFF`.

Sentinel scope (v1.0.1 clarification): the sentinel maps to null for every measurement, counter and identifier
field of PHYSIO_FEATURE, STATION_STATE, EVENT (`value` uses i32 sentinel `-2^31`; `rule_version`, `zone_code`),
STATUS and COMPACT. It never applies to bit-field bytes (`channel_flags`, `artifact_flags`, `flags`,
`sensor_flags`), to `event_type`, `level`, `related_seq_lo`, to header fields, or to ACK and CONFIG fields.

### 2.2 PHYSIO_FEATURE payload (frame_type 1) — 30 bytes; total frame 50 bytes

One record per 10 s feature window (Sec. 3.4.2, A.2).

| Off | Size | Field | Scale / unit |
|---|---|---|---|
| 0 | 2 | skin_temp | i16, °C×100 (DS18B20 contact temperature) |
| 2 | 2 | hr | u16, bpm×10 |
| 4 | 2 | spo2 | u16, %×10 (default null) |
| 6 | 4 | ppg_ir_mean | u32, raw counts (mean IR over window) |
| 10 | 2 | ppg_red_mean_div16 | u16, raw red mean / 16 |
| 12 | 2 | ppg_valid_permille | u16, valid fraction ×1000 |
| 14 | 2 | motion_rms_mg | u16, accel magnitude RMS deviation from 1 g, milli-g |
| 16 | 2 | gsr_mv | u16, ADC millivolts (optional Grove GSR; null if absent) |
| 18 | 1 | quality_pct | u8, 0–100 |
| 19 | 1 | battery_pct | u8 |
| 20 | 1 | channel_flags | bit0 T available, bit1 PPG available, bit2 Motion available, bit3 HR_SYNTHETIC, bit4 GSR available, bit5 SOS_ACTIVE, bit6 SPO2_VALIDATED |
| 21 | 1 | artifact_flags | bit0 motion_artifact, bit1 no_contact, bit2 saturation, bit3 sample_gap, bit4 temp_sensor_error, bit5 imu_error |
| 22 | 2 | n_ppg_samples | u16 (expected 1000 at 100 Hz × 10 s) |
| 24 | 2 | n_imu_samples | u16 (expected 250 at 25 Hz × 10 s) |
| 26 | 2 | window_ms | u16 (10000) |
| 28 | 2 | fw_build | u16 firmware build number |

### 2.3 STATION_STATE payload (frame_type 2) — 32 bytes; total frame 52 bytes

Stationary building-state node, one record per 1 s summary window.

| Off | Size | Field | Scale / unit |
|---|---|---|---|
| 0 | 2 | vib_peak_cg | u16, peak |a|-1g in 0.01 g |
| 2 | 2 | accel_rms_mg | u16, milli-g |
| 4 | 2 | tilt_ddeg | i16, inclination from mounting reference, 0.1° |
| 6 | 2 | tilt_delta_ddeg | i16, change vs. baseline, 0.1° |
| 8 | 2 | pressure_dhpa | u16, hPa×10 (BMP280) |
| 10 | 2 | pressure_delta_pa | i16, max |Δp| in window, Pa |
| 12 | 2 | temp | i16, °C×100 |
| 14 | 2 | gas_mv | u16, MQ-2 channel voltage mV (uncalibrated) |
| 16 | 2 | gas_baseline_mv | u16 |
| 18 | 2 | sound_index | u16, 0–4095 peak-to-peak ADC |
| 20 | 1 | flags | bit0 PIR presence, bit1 SOS active, bit2 impact, bit3 loud sound, bit4 gas alarm, bit5 tilt alarm, bit6 pressure transient, bit7 attachment_uncertain |
| 21 | 1 | quality_pct | u8 |
| 22 | 1 | battery_pct | u8 |
| 23 | 1 | sensor_flags | bit0 IMU ok, bit1 BMP ok, bit2 gas warm (preheat done), bit3 mic ok, bit4 PIR ok |
| 24 | 2 | n_imu_samples | u16 (200 Hz × 1 s = 200 for stationary impact capture) |
| 26 | 2 | window_ms | u16 (1000) |
| 28 | 2 | zone_code | u16, configured zone index |
| 30 | 2 | fw_build | u16 |

### 2.4 EVENT payload (frame_type 3) — 12 bytes; total frame 32 bytes

| Off | Size | Field |
|---|---|---|
| 0 | 1 | event_type (table below) |
| 1 | 1 | level: 0 info, 1 notice, 2 warning, 3 urgent |
| 2 | 4 | value i32 ×1000 (unit implied by event_type) |
| 6 | 2 | rule_version u16 |
| 8 | 2 | zone_code u16 |
| 10 | 2 | related_seq_lo u16 (low 16 bits of the telemetry seq that triggered it; 0 if none) |

| code | event_type | value unit | source |
|---|---|---|---|
| 1 | sos | 1 | personnel or stationary button (GPIO27) |
| 2 | sos_reset | 1 | local operator reset |
| 3 | impact_excursion | g | stationary IMU |
| 4 | loud_sound | index | stationary mic |
| 5 | gas_channel_alarm | V | stationary MQ-2 channel (uncalibrated) |
| 6 | tilt_change | deg | stationary IMU |
| 7 | pressure_transient | Pa | stationary BMP280 |
| 8 | presence | 1/0 | PIR |
| 9 | link_loss | s since last frame | **gateway-generated** |
| 10 | possible_impact_local | g | stationary composite: impact + (loud or pressure transient) within 2 s; **unverified, never "missile strike"** |
| 11 | help_request | 1 | personnel help button |
| 12 | link_restored | s outage | gateway-generated |
| 13 | buffer_eviction | count | node/gateway |

### 2.5 STATUS payload (frame_type 4) — 16 bytes
`u8 battery_pct, u8 buffered_records, u16 evicted_total, u32 sent_total, u32 acked_up_to_seq, u16 fw_build, u8 sensor_flags, u8 rssi_neg (−RSSI dBm as seen by node or 0xFF)`

### 2.6 ACK payload (frame_type 5) — 8 bytes (gateway→node, header source_class=3, device_id = gateway id)
`u16 target_boot_id, u16 reserved(0), u32 ack_up_to_seq` — cumulative application ack issued only after
site agent durable COMMIT (Sec. 3.3.7, A.2). MQTT QoS1 broker ack does NOT authorise deletion.

### 2.7 CONFIG payload (frame_type 6) — 8 bytes
`u16 zone_code, u16 feature_window_ms, u8 sample_profile, u8 synthetic_hr_enabled, u16 reserved`

### 2.8 Fragmentation (when frame > negotiated ATT payload)
Each BLE notification = 4-byte fragment header + chunk: `u16 msg_id, u8 frag_index, u8 frag_count`.
Reassembly limit 512 bytes, incomplete-message timeout 2 s (Sec. 3.3.7).
Every notification on TELEMETRY and EVENT carries the 4-byte fragment header (frag_count = 1 for a whole frame).
COMPACT notifications carry no fragment header. EVENT frames are queued ahead of telemetry (urgent priority).

### 2.9 COMPACT stationary packet — exactly 20 bytes (fits default MTU 23), every 200 ms
| Off | Size | Field |
|---|---|---|
| 0 | 1 | magic `0xC5` |
| 1 | 1 | node_index u8 |
| 2 | 2 | seq u16 (wraps) |
| 4 | 2 | vib_peak_cg u16 |
| 6 | 2 | tilt_ddeg i16 |
| 8 | 2 | pressure_dhpa u16 |
| 10 | 2 | temp i16 °C×100 |
| 12 | 2 | gas_mv u16 |
| 14 | 2 | sound_index u16 |
| 16 | 1 | flags (same bits as STATION_STATE.flags) |
| 17 | 1 | battery_pct |
| 18 | 2 | CRC-16/CCITT-FALSE over bytes 0..17 |
Staleness at gateway: 2 s (Sec. 3.4.4).

## 3. Gateway text log line (serial + web page, Stage-1 compatible)

Physio: `RX,<gw_id>,<gw_ms>,F,<device_id>,<boot_id>,<seq>,<node_ms>,<temp_x100>,<ppg_ir>,<motion_mg>,<hr_x1>,<flags>`
Example (paper Sec. 3.4.2): `RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM`
`flags` letters: T (temp), P (PPG), M (motion), H (HR synthetic), G (GSR), S (SOS); missing values = empty field.
Note: in this implementation the 6th field is `boot_id` (our definition; the paper leaves the original field
uninterpreted).
Station: `RX,<gw_id>,<gw_ms>,S,<device_id>,<boot_id>,<seq>,<node_ms>,<vib_cg>,<tilt_ddeg>,<p_dhpa>,<temp_x100>,<gas_mv>,<sound>,<flags_hex>`
Event:   `RX,<gw_id>,<gw_ms>,E,<device_id>,<boot_id>,<seq>,<node_ms>,<event_type_name>,<level>,<value_x1000>`

## 4. MQTT (gateway → site broker; TLS 1.3 mutual auth, QoS 1)

- `umsf/<site_id>/<gw_id>/physio`   — JSON record, schema `1.0` (Sec. 5.1)
- `umsf/<site_id>/<gw_id>/station`  — JSON record, schema `st-1.0`
- `umsf/<site_id>/<gw_id>/event`    — JSON record, schema `ev-1.0`
- `umsf/<site_id>/<gw_id>/status`   — gateway status JSON
- `umsf/<site_id>/ack/<gw_id>`      — site agent → gateway: `{"device_id","boot_id","ack_up_to_seq"}` after COMMIT

Gateway also publishes the raw frame hex in field `frame_hex` so P1 can verify CRC and decode itself.

## 5. JSON record schemas (P1 storage, P3 input)

### 5.1 Physio — schema_version `"1.0"` (paper Sec. 3.3.8, exact field list) + optional extension
Required keys: `schema_version, data_origin, scenario_id, site_id, device_id, boot_id, sequence, measured_at,
received_at, hr_bpm, spo2_pct, skin_temp_c, motion_rms_g, quality, battery_pct`.
Optional extension keys (allowed): `gateway_id, zone_id, worker_pseudonym, ppg_ir, channel_flags, artifact_flags,
hr_synthetic, fw_build, time_uncertainty_s, frame_hex`.
`data_origin` ∈ {`synthetic`, `synthetic_payload_physical_transport`, `bench_transcription`, `measured`}.
Times: ISO-8601 UTC with `Z`. `quality` ∈ [0,1] or null. Ranges: hr 20–250, spo2 50–100, skin_temp 20–45,
motion_rms_g 0–16, battery 0–100.

### 5.2 Station — schema_version `"st-1.0"`
`schema_version, data_origin, scenario_id, site_id, zone_id, device_id, boot_id, sequence, measured_at, received_at,
vib_peak_g, accel_rms_g, tilt_deg, tilt_delta_deg, pressure_hpa, pressure_delta_pa, temp_c, gas_v, sound_index,
pir_presence (bool|null), sos (bool|null), attachment_verified (bool), quality, battery_pct`
+ optional `gateway_id, flags, sensor_flags, fw_build, frame_hex`.

### 5.3 Event — schema_version `"ev-1.0"`
`schema_version, data_origin, scenario_id, site_id, zone_id, event_id, source_class, device_id, event_type,
level, value, unit, observed_at, reported_at, time_uncertainty_s, rule_version, quality, ack_state, provenance`
`source_class` ∈ {`personnel_node`, `stationary_node`, `gateway`, `operator_report`, `responder_report`,
`authoritative_external_alert`}.
`event_type` ∈ the table in 2.4 plus: `external_strike_report`, `air_raid_alert`, `air_raid_all_clear`,
`structural_assessment`, `personnel_accounting`, `asset_status`.
`ack_state` ∈ {`unacknowledged`, `acknowledged`, `resolved`}.
`provenance`: object `{source, method, assessor?, valid_until?}`.

### 5.4 Roster — `roster.json`
`{"site_id", "zones": [{"zone_id", "name", "expected_workers": ["W01", ...], "stationary_nodes": ["S01", ...]}],
"device_map": {"A01": "W01", ...}, "valid_from", "valid_to"}`

## 6. Default parameters

| Parameter | Value | Source |
|---|---|---|
| feature record interval | 10 s | Sec. 3.3.8, A.2 |
| PPG red/IR | 100 Hz each | Table 4 |
| DS18B20 | 1 Hz, GPIO4, 4.7 kΩ pull-up | Table 4 |
| MPU6050 personnel | 25 Hz, ±4 g, ±500 °/s, I2C 0x68 | Table 4 |
| MAX30102 | I2C GPIO21/22, 0x57 | Table 4 |
| help button | GPIO27 pull-up, debounce | Table 4 |
| GSR | GPIO34 ADC1, 10 Hz | Table 4 |
| node buffer | ≥30 unacked records (5 min) | 3.3.7, A.2 |
| gateway buffer | ≥18 records (60 s across 3 nodes) | A.2 |
| nodes per gateway | 3 | 3.3.7 |
| max serialized feature message | 512 B | 3.3.8, A.2 |
| fragment timeout | 2 s | 3.3.7 |
| freshness horizon | 60 s | 3.3.8 |
| summary window | 5 min; 6 nodes → 180 expected, 36 fresh | 3.3.8 |
| timezone display | Europe/Kyiv, UTC stored | 3.3.8 |
| SQLite | WAL, synchronous=FULL | 3.3.8 |
| storage sizing | 1.5 kB/record → 51.84 MB / 8 h / 12 nodes | 3.3.8 |
| stationary compact packet | 20 B every 200 ms, staleness 2 s | 3.4.4 |
| group rule (Study A) | n_min 5, C_min 0.70, m_min 3, θ 0.50 | 4.4 |
| group rule (illustrative) | n_min 6, C_min 0.70, m_min 3, θ 0.30 | 4.1 |
