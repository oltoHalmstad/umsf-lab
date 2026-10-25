# Dataset format (UMSF protocol v1.0)

This document specifies every file produced by `umsf-incident-dataset` so that other tools — in
particular the decision-support agent **P3 `umsf-incident-ai-agent`** — can consume them without
reading the generator code. The shared byte-level protocol and JSON field lists are defined by the
UMSF Shared Protocol Specification v1.0 (§2 frames, §3 gateway lines, §5 JSON records). The JSON
Schema files in `src/umsf_dataset/schemas/` are authoritative for record validation.

General rules (apply to every file):

| Rule | Meaning |
|---|---|
| Encoding | UTF-8. JSONL = one JSON object per line, `\n` line ends. |
| Time | ISO-8601 UTC with `Z` (`2026-10-14T05:08:00Z`, optional `.mmm`). Display in Europe/Kyiv only. |
| Missing values | `null` (or an absent record when the source was silent). Never 0 or "normal". |
| Identity | Physio/station: `(site_id, device_id, boot_id, sequence)`. Events: `(site_id, event_id)`. |
| `measured_at` vs `received_at` | Capture time vs arrival time at the collector. `measured_at` is never rewritten. A delayed first arrival (large `received_at − measured_at`) belongs to history, not to the current 60 s window. |
| `data_origin` | `synthetic`, `synthetic_payload_physical_transport`, `bench_transcription` or `measured`. All shipped data are `synthetic` or `bench_transcription`. `measured` is rejected unless `--allow-measured`. |
| Units | As in the field names (`_g`, `_deg`, `_hpa`, `_pa`, `_c`, `_v`, `_pct`, `_s`). `gas_v` is an **uncalibrated MQ-2 channel voltage**, not a concentration. |
| Strikes | Only `event_type = external_strike_report` from `source_class = authoritative_external_alert`. A local composite is `possible_impact_local` (unverified). The validator rejects `external_strike_report` from any other source class. |
| Link loss | Current evidence becomes `unknown`. Never "collapse" or "casualty". |

## 1. Incident scenario directory (`synth-incident`, e.g. `data/incident/`)

| File | Content |
|---|---|
| `roster.json` | Facility wrapper: `{"facility_id", "valid_from", "valid_to", "sites": [<roster>...]}`; each `<roster>` is exactly the spec §5.4 object. |
| `roster_<SITE>.json` | The same per-site roster objects, one file per site (spec §5.4 shape). |
| `physio.jsonl` | Personnel feature records, schema `1.0`, 10 s interval, ordered by `received_at`. |
| `station.jsonl` | Stationary building-state records, schema `st-1.0`, 1 s interval (configurable), ordered by `measured_at`. |
| `events.jsonl` | Source-qualified events, schema `ev-1.0`, ordered by `observed_at`. |
| `assets.json` | Services, resources and reference allocations (Table 16 example). |
| `teams.json` | Rescue / response teams with competencies and ETA estimates. |
| `manifest.json` | Scenario metadata, counts, SHA-256 of every file, operator associations, evidence boundaries and the generator's scenario script. |

### 1.1 Roster (`roster_<SITE>.json`, spec §5.4)

```json
{"site_id": "SITE-A",
 "zones": [{"zone_id": "A-Z1", "name": "Workshop No. 1, north wing",
            "expected_workers": ["W01", "W02", "W03"], "stationary_nodes": ["SA1"]}, ...],
 "device_map": {"A01": "W01", ...},
 "valid_from": "2026-10-14T00:00:00Z", "valid_to": "2026-10-15T00:00:00Z"}
```

* `expected_workers` is the denominator `N` for coverage (Eq. 4). A zone may have zero workers
  (`A-Z3`): coverage is then not computed and no automated group-normal conclusion is allowed.
* `device_map` maps personnel devices to worker pseudonyms. Stationary nodes are never workers and
  never appear in `expected_workers`.

### 1.2 Physio record (schema `1.0`)

Required: `schema_version, data_origin, scenario_id, site_id, device_id, boot_id, sequence,
measured_at, received_at, hr_bpm, spo2_pct, skin_temp_c, motion_rms_g, quality, battery_pct`.
Optional extension: `gateway_id, zone_id, worker_pseudonym, ppg_ir, channel_flags, artifact_flags,
hr_synthetic, fw_build, time_uncertainty_s, frame_hex`.

| Field | Type / range | Notes |
|---|---|---|
| `hr_bpm` | number 20–250 or null | Synthetic in all shipped data; bench HR is a test field (`hr_synthetic: true`). |
| `spo2_pct` | number 50–100 or null | **null by default** (no validated estimator). |
| `skin_temp_c` | number 20–45 or null | Contact-temperature channel. |
| `motion_rms_g` | number 0–16 or null | RMS deviation of acceleration magnitude from 1 g. |
| `quality` | number 0–1 or null | Eligibility uses `quality ≥ 0.8` (Study A); "good" in summaries is `≥ 0.6`. |
| `channel_flags` | int bitfield | bit0 T, bit1 PPG, bit2 Motion, bit3 HR_SYNTHETIC, bit4 GSR, bit5 SOS_ACTIVE, bit6 SPO2_VALIDATED. |
| `artifact_flags` | int bitfield | bit0 motion_artifact, bit1 no_contact, bit2 saturation, bit3 sample_gap, bit4 temp_sensor_error, bit5 imu_error. |
| `time_uncertainty_s` | number ≥ 0 or null | null = clock mapping not qualified (age cannot be bounded). |

### 1.3 Station record (schema `st-1.0`)

Required: `schema_version, data_origin, scenario_id, site_id, zone_id, device_id, boot_id, sequence,
measured_at, received_at, vib_peak_g, accel_rms_g, tilt_deg, tilt_delta_deg, pressure_hpa,
pressure_delta_pa, temp_c, gas_v, sound_index, pir_presence, sos, attachment_verified, quality,
battery_pct`; optional `gateway_id, flags, sensor_flags, fw_build, frame_hex`.

* `attachment_verified` is an installation fact; it is `false` in all shipped data (no verified
  structural mounting), so mechanical values support only "channel excursion / orientation change".
* `pir_presence` is a presence cue, not a vital sign; `null` when the node has no PIR (`SA3`).
* `flags` bits: 0 PIR, 1 SOS, 2 impact, 3 loud sound, 4 gas alarm, 5 tilt alarm, 6 pressure
  transient, 7 attachment_uncertain. `sensor_flags`: 0 IMU ok, 1 BMP ok, 2 gas warm, 3 mic ok, 4 PIR ok.
* Staleness: a node is `current` if its last record is ≤ 60 s old (≤ 2 s for COMPACT packets);
  after a `link_loss` event without a later `link_restored`, its state is `unknown`.

### 1.4 Event record (schema `ev-1.0`)

Required: `schema_version, data_origin, scenario_id, site_id, zone_id, event_id, source_class,
device_id, event_type, level, value, unit, observed_at, reported_at, time_uncertainty_s,
rule_version, quality, ack_state, provenance`. Implementation-defined optional keys:
`incident_id, details (object), related_event_ids, boot_id, sequence, gateway_id, frame_hex`.

| Field | Values |
|---|---|
| `source_class` | `personnel_node`, `stationary_node`, `gateway`, `operator_report`, `responder_report`, `authoritative_external_alert` |
| `event_type` | spec §2.4 table (`sos`, `sos_reset`, `impact_excursion`, `loud_sound`, `gas_channel_alarm`, `tilt_change`, `pressure_transient`, `presence`, `link_loss`, `possible_impact_local`, `help_request`, `link_restored`, `buffer_eviction`) plus `external_strike_report`, `air_raid_alert`, `air_raid_all_clear`, `structural_assessment`, `personnel_accounting`, `asset_status` |
| `level` | string `info` / `notice` / `warning` / `urgent` (the validator also accepts the integer codes 0–3) |
| `zone_id` | zone id, or `null` for site-wide items (alerts, accounting, service status) |
| `device_id` | subject of the event: the node concerned (for gateway-generated `link_loss` / `link_restored` the *affected node*, with the gateway in `gateway_id` and `provenance.source`), `OP-A` for operator reports, `RT-1` for a responder team, `EXT-ALERT` / `EXT-MILADM` for external sources |
| `provenance` | `{"source", "method", "assessor"?, "valid_until"?}`; structural assessments carry `assessor` and `valid_until` |
| `ack_state` | `unacknowledged` in generated data; acknowledgement is not proof of action |

`details` content by event type (synthetic incident):

| event_type | `details` keys |
|---|---|
| `personnel_accounting` | `expected`, `accounted`, `assistance_requested`, `responder_confirmed_assistance`?, `unaccounted`, `last_confirmed`? `{worker: {zone_id, at}}`, `note`. "Unaccounted" = unresolved whereabouts, never injury/death. |
| `asset_status` (service) | `service_id`, `status` (`available`/`unavailable`/`unknown`), `demand_units`, `weight`, `mandatory`, `prerequisites`; `value` 1/0/null. |
| `asset_status` (resource) | `resource_id`, `capacity_lower_bound`, `capacity_upper_bound`, `pre_event_rating`, `note`; `value` = lower bound. |
| `structural_assessment` | `status` (e.g. `restricted_access`), `scope`, `taxonomy`. No damage percentage. |
| `external_strike_report` | `reported_area`, `report_ref`. |

### 1.5 `assets.json`

```json
{"facility_id": "FAC-DEMO", "site_id": "SITE-A", "planning_interval_min": 60,
 "resources": [{"resource_id": "backup_power_units", "unit": "illustrative units",
                "capacity_lower_bound": 6, "capacity_upper_bound": 8, "pre_event_rating": 10, ...}],
 "services": [{"service_id": "communications", "demand_units": 1, "demand": {"backup_power_units": 1},
               "weight": 6, "mandatory": true, "prerequisites": [], "admissible": true,
               "status": "available"}, ... emergency_lighting 2/5/mandatory, water_support 3/4,
              production 4/1 (requires communications)],
 "reference_solutions": [{"capacity_units": 2, "feasible": false, ...},
                         {"capacity_units": 4, "Q_percent": 68.75, ...},
                         {"capacity_units": 6, "Q_percent": 93.75, "allocation": {...}}, {"capacity_units": 10, "Q_percent": 100.0, ...}]}
```

Use `capacity_lower_bound` (never `pre_event_rating`) as the guaranteed capacity `b_k` in Eq. (10).

### 1.6 `teams.json`

```json
{"teams": [{"team_id": "RT-1", "name": "...", "site_id": "SITE-A", "members": 4,
            "competencies": ["search_and_rescue", "first_aid", "casualty_extraction"],
            "available": true, "available_from_min"?: 15,
            "eta_min": {"A-Z1": 3, "A-Z2": 2, ...}}, ...],
 "competency_catalog": [...], "notes": [...]}
```

`eta_min` are illustrative assignment-time estimates `δ_rj` (Eq. 9), not measured travel times.
Eligibility `e_rj` must be derived by P3 from task requirements vs. `competencies`; access `a_j` from
`structural_assessment` / incident-command input. Unknown eligibility or access = 0 with escalation.

### 1.7 `manifest.json`

Keys: `dataset, scenario_id, incident_id, facility_id, generator, generator_version, seed,
data_origin, t0, duration_s, physio_interval_s, station_interval_s, display_tz, schema_versions,
counts, files[{path, sha256, bytes}], incident_associations, scenario_script, evidence_boundaries`.

* `incident_associations`: explicit, timestamped operator association of local (unverified) events
  with the external strike report, keeping both provenance chains:
  `{"association_id", "external_event_id", "local_event_ids", "associated_by", "associated_at", "basis"}`.
* `scenario_script`: what the *generator* did (silent nodes, urgent requests, unresolved personnel,
  expected Q at the capacity lower bound). Use it only to test P3; it is not field truth and is not
  information available to an operator at run time.

Timeline of the default scenario (`t0 = 2026-10-14T05:00:00Z`, 30 min):

| t0 + | What happens |
|---|---|
| 2:00 | `air_raid_alert` (authoritative external), both sites |
| 8:00 | SITE-A: impact/loud/pressure on SA1 (A-Z1), loud on SA2, SA3; A03 goes silent |
| 8:01–8:12 | `possible_impact_local` (unverified), `tilt_change` (attachment uncertain), `gas_channel_alarm` (uncalibrated), all A-Z1 |
| 8:15–14:00 | A02 link outage; 30 buffered records delivered late, 4 evicted (`buffer_eviction`) |
| 8:20 | SA1 silent for the rest of the scenario → `link_loss` → zone mechanical state `unknown` |
| 8:30 / 9:00 | `sos` W01 (A-Z1), `help_request` W05 (A-Z2) |
| 9:30 | `personnel_accounting` (W03 unaccounted = unresolved) |
| 10:00 | `asset_status` for 4 services + backup capacity lower bound 6 units |
| 12:00 | `external_strike_report` (authoritative external, with provenance) |
| 15:00 | `structural_assessment` A-Z1 `restricted_access` by a responder (assessor, valid_until) |
| 17:00–17:40 | SB2 (SITE-B) brief link loss and restore |
| 20:00 | updated `personnel_accounting` |
| 25:00 | `air_raid_all_clear` |

## 2. Study B collector outputs (`data/study_b/`)

| File | Content |
|---|---|
| `study_b_input.jsonl` | 2,173-line challenge stream (includes 6 invalid lines on purpose). |
| `study_b_truth.json` | Generator counts and the conflicted / delayed identities. |
| `rosters.json` | `{site_id: roster}` map for SITE-A and SITE-B (6 devices each). |
| `study_b_result.json` | Table 12 outcome and the 10 self-checks. |
| `exports/physio_<UTC-date>.csv/.jsonl` | Accepted nonconflicting records only (2,159). |
| `exports/summaries_5min.json/.csv` | 12 roster-based five-minute summaries (fields below). |
| `exports/quarantine_log.jsonl` | `{"quarantined_identity": {kind, original}, "conflicts": [...]}` |
| `exports/rejects_log.jsonl` | `{source, line_no, reason, raw, detected_at}` per rejected line. |
| `exports/manifest.json` | Sources and exports with SHA-256, versions, counters, timing rules, sizing. |

Summary fields: `site_id, window_start, window_end, window_start_local, display_tz, cutoff,
complete_window, roster_devices, expected_records (= roster_devices × 300/10), received_records,
sample_completeness, devices_reporting, device_coverage, channel_valid_counts{hr_bpm, spo2_pct,
skin_temp_c, motion_rms_g, quality, battery_pct}, quality_good, quality_poor, quality_null,
fresh_horizon_s (60), fresh_expected (= roster_devices × 6), fresh_received, fresh_good,
fresh_devices_good, late_after_cutoff, unrostered_records`.

## 3. Study A outputs (`data/study_a/`)

`study_a_metrics.json` (Table 11 metrics, states, protection demo results) and
`study_a_episodes.json` (episode and degraded-interval placement). The 40,320 one-minute records are
generated on demand (`umsf-dataset synth-study-a --out DIR --write-records`); their JSONL fields are
`worker, device_id, zone, day, minute, measured_at, activity, hr_bpm, spo2_pct, quality, phase,
injected, degraded, data_origin`. This is a Study-A-specific feature format, not schema `1.0`.

## 4. Bench outputs (`data/bench/`)

| File | Content |
|---|---|
| `stage1_table13.csv` | Exact Table 13 transcription (`hr_test_synthetic` column). |
| `stage1_gateway_lines.txt` | The 13 rows as §3 gateway lines; row 13 equals the paper's example line. |
| `stage1_records.jsonl` | Schema `1.0`, `data_origin: bench_transcription`, `hr_synthetic: true`, nominal clock. |
| `stage2_station.jsonl`, `stage2_events.jsonl` | Synthetic re-enactment of the Table 6 timeline (`data_origin: synthetic`). |
| `stage2_station_frames.hex` | The same station records as §2.3 binary frames: `<received_at> <hex>` per line. |
| `bench_summary.json` | Stage-1 descriptive statistics and Stage-2 timeline/event counts. |

## 5. Binary frames and decoded form

`umsf_dataset.frames.decode_frame(bytes)` returns
`{"header": {magic, version, source_class, frame_type, device_id, boot_id, sequence, node_time_ms},
"payload": {<spec field names, raw integer scaled values>}, "crc_ok": bool}`. Null sentinels
(u8 0xFF, u16 0xFFFF, i16 −32768, u32 0xFFFFFFFF, and i32 −2³¹ for EVENT `value` — an implementation
choice) become `None`, except bit-field bytes (`channel_flags`, `artifact_flags`, `flags`,
`sensor_flags`) and control fields (`event_type`, `level`, `related_seq_lo`, ACK and CONFIG fields).
COMPACT packets decode to header `{magic, node_index, seq}`. Test-vector files are JSON lists of
`{"name", "hex", "expected"}` where `expected` is either nested (`header`/`payload`/`crc_ok`) or
flat (header ∪ payload ∪ `crc_ok`); `"expect_error": true` marks a structurally invalid frame.
See `tests/vectors_p1.json` and `umsf-dataset vectors FILE`.
