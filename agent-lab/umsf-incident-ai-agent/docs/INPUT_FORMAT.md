# Input format

The agent reads one **dataset directory**. Record schemas for `physio.jsonl`, `station.jsonl`,
`events.jsonl` and `roster.json` are those of the UMSF shared protocol (PROTOCOL.md §5, schema versions
`1.0`, `st-1.0`, `ev-1.0`) as exported by P1 `umsf-incident-dataset` (its `docs/DATASET_FORMAT.md`).
`assets.json` and `teams.json` are defined below; the loader accepts both this project's form and P1's
form. Every file is optional — a missing file produces a warning and conservative behaviour (e.g. no
roster → no coverage, no group conclusion; no teams → every task escalated).

General rules: UTF-8; JSONL one object per line; times ISO-8601 UTC with `Z`; missing values `null`
(never 0 or "normal"); units as in field names.

| File | Required | Notes |
|---|---|---|
| `roster.json` | recommended | explicit roster (coverage denominator) |
| `physio.jsonl` | optional | schema `1.0` |
| `station.jsonl` | optional | schema `st-1.0` |
| `events.jsonl` | optional | schema `ev-1.0` |
| `assets.json` | optional | resources, services, equipment (continuity, recovery) |
| `teams.json` | optional | teams, access authorisations, distances / ETAs |
| `manifest.json` | optional | metadata (`start`/`end` or `t0`/`duration_s`, `baseline_end`) |
| `policy.json` | optional | incident-command overrides of the default policy |

## roster.json

Accepted shapes: one §5.4 object; a list of them; `{"rosters": [...]}`; or P1's facility wrapper
`{"facility_id", "valid_from", "valid_to", "sites": [<§5.4 roster>, ...]}`.

```json
{"site_id": "UMSF-A",
 "zones": [{"zone_id": "Z2", "name": "Workshop", "expected_workers": ["W03", "W04"], "stationary_nodes": ["S02"]}],
 "device_map": {"A03": "W03", "A04": "W04"}, "valid_from": "...", "valid_to": "..."}
```

`expected_workers` is N in Eq. (4). Stationary nodes are never workers; a `device_map` entry that refers
to a stationary node is ignored with a warning. Physio devices without a `device_map` entry are mapped via
`worker_pseudonym` if present.

## physio.jsonl (schema `1.0`)

Required keys: `schema_version, data_origin, scenario_id, site_id, device_id, boot_id, sequence,
measured_at, received_at, hr_bpm, spo2_pct, skin_temp_c, motion_rms_g, quality, battery_pct`; optional
`gateway_id, zone_id, worker_pseudonym, ppg_ir, channel_flags, artifact_flags, hr_synthetic, fw_build,
time_uncertainty_s, frame_hex`.

* Identity `(site_id, device_id, boot_id, sequence)`: identical redelivery dropped (idempotent);
  different immutable payload → identity quarantined (excluded, kept for audit).
* Values outside the protocol ranges become `null` with a reason.
* `zone_id` is the gateway/device location; it is never treated as the person's position.
* Features used by default: `hr_bpm`, `skin_temp_c` (weights 0.5/0.5), context from `motion_rms_g`,
  eligibility `quality ≥ 0.8`.

## station.jsonl (schema `st-1.0`)

Keys per PROTOCOL §5.2. Used: `measured_at`, `received_at` (current if ≤ 60 s old), `attachment_verified`
(`false` → structural interpretation withdrawn), `pir_presence` (presence cue only), last-known values for
observation gaps. Any cadence (1 s in P1, 10 s summaries in the bundled scenario) is accepted.

## events.jsonl (schema `ev-1.0`)

Keys per PROTOCOL §5.3. `level` may be an integer 0–3 or `info/notice/warning/urgent`. Identity is
`event_id`. Event types and their use:

| event_type | source_class | effect |
|---|---|---|
| `impact_excursion`, `pressure_transient`, `tilt_change`, `loud_sound`, `possible_impact_local` | stationary_node | M layer; composite shown as UNVERIFIED; `loud_sound` > 5 s from an impact → acoustic presence cue (P) |
| `gas_channel_alarm` | stationary_node | H layer, uncalibrated channel response |
| `sos`, `help_request` | personnel_node / stationary_node | P layer; urgent pathway; rescue task |
| `sos_reset` | any | recorded, not proof of assistance |
| `presence` | stationary_node | possible presence cue |
| `link_loss`, `link_restored`, `buffer_eviction` | gateway / node | U layer; `device_id` = affected node |
| `personnel_accounting` | responder_report / operator_report | per worker: `provenance.worker`, `value` ∈ {`accounted`, `accounted_at_assembly`, `assisted`, `handed_to_medical`, `assistance_in_progress`, `not_found_at_last_location`, `whereabouts_unresolved`}, optional `provenance.location_zone`; or P1 aggregated `details` {`accounted`, `responder_confirmed_assistance`, `assistance_requested`, `unaccounted`, `last_confirmed`} (expanded per worker) |
| `structural_assessment` | responder_report / operator_report | qualified only with `provenance.assessor`; state from `value` or `details.status`; `provenance.valid_until`; `restricted_access` / `entry_restricted` / `unsafe` / `no_entry` restrict access |
| `asset_status` | operator_report | F layer; `provenance.capacity_lower_bounds` {resource: value} with `provenance.asset_id` (per-asset contribution) or P1 `details` {`resource_id`, `capacity_lower_bound`} (replaces the resource bound) / {`service_id`, `status`} |
| `air_raid_alert`, `air_raid_all_clear`, `external_strike_report` | **authoritative_external_alert only** | site context; from any other source → rejected as attribution |

Response-action timing (Eq. 7): a responder record with `provenance.method = "response_action_start"`
and `provenance.related_event = <event_id>` defines t_a.

## assets.json (this project, schema `as-1.0`)

```json
{"planning_horizon_h": 4, "temporary_power_zone": "Z1",
 "resources": [
   {"resource_id": "power_kw", "unit": "kW", "kind": "power",
    "contributions": [{"asset_id": "grid_feed_A", "lower_bound": 250, "basis": "pre-event register"}]},
   {"resource_id": "staff", "unit": "persons", "lower_bound": 6, "basis": "accounted operators"}],
 "services": [
   {"service_id": "communications", "name": "...", "zone_id": "Z1", "priority_weight": 6, "mandatory": true,
    "demand": {"power_kw": 4, "staff": 1}, "requires": [], "admissible": true, "admissibility_basis": "...",
    "actuation_required_to_restore": false}],
 "equipment": [{"kind": "certified_gas_detector", "quantity": 1, "status": "available"}],
 "assets": [{"asset_id": "pump_P1", "zone_id": "Z3", "kind": "pump", "status": "unknown"}],
 "recovery_tasks": [{"task_id": "...", "kind": "...", "zone_id": "...", "competencies": [], "equipment": {},
                     "duration_s": 1800, "priority": 50, "prerequisites": []}]}
```

* `lower_bound: null` or `status: "unknown"` → 0 guaranteed. `admissible: null` → g_j = 0.
* If `energy_kwh` is a resource and a service gives only `power_kw`, energy demand = kW × horizon.
* P1 form accepted: `capacity_lower_bound` (used; `pre_event_rating` never used), `weight`,
  `prerequisites`, `demand_units`, `planning_interval_min`.

## teams.json (this project, schema `tm-1.0`)

```json
{"travel_speed_m_per_s": 1.2,
 "zone_distance_m": {"Z1": {"Z2": 82, "Z3": 108}},
 "teams": [{"team_id": "RT1", "name": "...", "role": "rescue", "location_zone": "Z6",
            "competencies": ["search", "first_aid"], "ppe": ["scba", "gas_monitor", "helmet"],
            "available_from": "...", "available_until": "...", "eta_min": {"Z1": 3}}],
 "access": [{"zone_id": "Z2", "status": "authorised", "scope": ["rescue"], "authorised_by": "incident command",
             "conditions": ["helmet"], "valid_from": "...", "valid_until": "..."}]}
```

* `role` ∈ `rescue`, `assessment`, `recovery`; if absent it is inferred from competencies
  (documented in `rescue.team_role`) and can be overridden by policy `team_overrides`.
* `scope`: `all`, a domain (`rescue`, `recovery`, `assessment`) or a task kind.
* δ_rj uses `eta_min[zone]` if given, else `zone_distance_m` / speed; plus policy setup time.
* P1 form accepted: no `role`/`ppe`/`access` (→ inferred role; PPE unknown; access unknown → escalation),
  `available_from_min` relative to `manifest.t0`, P1 competency names via policy `competency_aliases`.

## manifest.json

Used keys: `scenario_id`, `data_origin`, `start`/`end` (or `t0` + `duration_s`), `baseline_end`
(otherwise the first local incident observation), `incident_associations` (operator association of local
events with an external report; reported, never turned into an attribution). P1's `scenario_script` is
generator ground truth and is **never read** by the agent.

## policy.json / `--policy` (incident-command input)

Deep-merged over `src/umsf_agent/data/default_policy.json`: decision authority, group-rule and physio
parameters, freshness horizons, rescue task kinds (h_j, p_j, competencies, setup time), `task_overrides`,
hazard PPE, recovery templates, actuation kinds, `competency_aliases`, additional `access`
authorisations and `team_overrides` (e.g. declared PPE). Example: `examples/p1_incident_command_input.json`.
