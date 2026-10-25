"""Self-contained SYNTHETIC post-impact scenario generator.

Everything produced here is constructed test data (data_origin = "synthetic").
It does not represent a real site, real people, a real attack or measured
physiology. Heart-rate values are synthetic interface fields (Sec. 4.6, A.2).

Storyline (UTC, scenario day 2026-10-14):
  08:00-08:30  baseline work; personal references are built from this period
  08:30        air-raid alert (authoritative external alert)
  08:34:12     Site A / Z2 workshop: impact excursion + pressure transient + loud
               sound -> local composite possible_impact_local (UNVERIFIED);
               node S02 reports tilt change and attachment uncertainty
  08:34:20     SOS from worker W05 (personnel node) in Z2
  08:34:40     Z3 pump room: uncalibrated gas-channel alarm on S03
  08:34:50     SOS button on stationary node S03 (person unknown)
  08:35:30     gateway GA2 (Z3) link lost -> observation gap
  08:36        operator: grid feed A unavailable; 08:39 generator G1 verified
  08:36:40     external strike report (authoritative), reported 08:41
  08:37:05     help request from W10 (Site B / Z4)
  08:38        operator relays an unverified "missile hit" claim -> rejected
  08:45-08:52  responder reports: W01-W04 accounted at assembly Z6, W05 handed
               to medical; Z1 structural assessment by a qualified assessor
  08:50        W12's device stops (battery) -> silence, never "casualty"
  08:58        GA2 link restored: buffered backlog arrives (history only),
               older records evicted
  09:10        scenario end
"""

from __future__ import annotations

import json
import math
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .util import fmt_ts, parse_ts, sha256_file

SCENARIO_ID = "umsf-p3-post-impact-demo-v1"
T0 = parse_ts("2026-10-14T08:00:00Z")
BASELINE_END = parse_ts("2026-10-14T08:30:00Z")
T_END = parse_ts("2026-10-14T09:10:00Z")
T_IMPACT = parse_ts("2026-10-14T08:34:12Z")
T_LINK_LOSS = parse_ts("2026-10-14T08:35:30Z")
T_LINK_RESTORE = parse_ts("2026-10-14T08:58:00Z")
T_W12_SILENT = parse_ts("2026-10-14T08:50:00Z")
SITE_A, SITE_B = "UMSF-A", "UMSF-B"

ZONES = [
    # zone, site, name, workers, stationary node, gateway
    ("Z1", SITE_A, "Адміністративний блок", ["W01", "W02"], "S01", "GA1"),
    ("Z2", SITE_A, "Механічний цех", ["W03", "W04", "W05", "W06", "W07"], "S02", "GA1"),
    ("Z3", SITE_A, "Насосна (підвал)", ["W08", "W09"], "S03", "GA2"),
    ("Z6", SITE_A, "Пункт збору / укриття", [], "S06", "GA1"),
    ("Z4", SITE_B, "Диспетчерська", ["W10", "W11"], "S04", "GB1"),
    ("Z5", SITE_B, "Склад", ["W12"], "S05", "GB1"),
]
AFFECTED = {"W03", "W04", "W06"}            # synthetic stipulated deviation after impact
EVACUEES = {"W01", "W02", "W03", "W04"}     # move to assembly zone Z6


def _r(x, d=3):
    return None if x is None else round(x, d)


def _ts(t: datetime) -> str:
    return fmt_ts(t)


VARIANTS = {
    "post_impact": "main storyline (generator and fuel verified at 08:39)",
    "no_backup_power": "same storyline, but no backup power is ever verified: mandatory life-safety demand "
                       "exceeds justified capacity, so continuity is INFEASIBLE (never relaxed)",
}


def generate(out_dir: str, seed: int = 20261014, variant: str = "post_impact") -> Dict[str, str]:
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; choose from {sorted(VARIANTS)}")
    scenario_id = SCENARIO_ID if variant == "post_impact" else f"{SCENARIO_ID}-{variant}"
    rng = random.Random(seed)
    os.makedirs(out_dir, exist_ok=True)
    zone_of = {w: z for z, _, _, ws, _, _ in ZONES for w in ws}
    site_of_zone = {z: s for z, s, *_ in ZONES}
    gw_of_zone = {z: g for z, _, _, _, _, g in ZONES}
    workers = sorted(zone_of)
    dev_of = {w: "A" + w[1:] for w in workers}

    # ---------------- roster (one object per site; list form) ----------------
    rosters = []
    for site in (SITE_A, SITE_B):
        rosters.append({
            "site_id": site,
            "zones": [{"zone_id": z, "name": n, "expected_workers": ws, "stationary_nodes": [s]}
                      for z, si, n, ws, s, _ in ZONES if si == site],
            "device_map": {dev_of[w]: w for w in workers if site_of_zone[zone_of[w]] == site},
            "valid_from": _ts(T0 - timedelta(hours=1)), "valid_to": _ts(T_END + timedelta(hours=8)),
        })

    # ---------------- physio ----------------
    physio: List[dict] = []
    base_hr = {w: 66 + 2.5 * i for i, w in enumerate(workers)}
    base_t = {w: 33.2 + 0.1 * (i % 5) for i, w in enumerate(workers)}
    seq = {w: 0 for w in workers}
    backlog_lost = 0
    t = T0
    step = timedelta(seconds=10)
    while t < T_END:
        for w in workers:
            z = zone_of[w]
            seq[w] += 1
            if w == "W12" and t >= T_W12_SILENT:
                continue           # device battery exhausted: silence
            minute = (t - T0).total_seconds() / 60
            post = t >= T_IMPACT
            # motion context
            if 12 <= minute < 22:
                motion = 0.25 + rng.gauss(0, 0.02)          # baseline walking period
            elif post and w in EVACUEES and t < T_IMPACT + timedelta(minutes=6):
                motion = 0.30 + rng.gauss(0, 0.03)          # evacuation
            else:
                motion = 0.05 + abs(rng.gauss(0, 0.01))
            hr = base_hr[w] + (14 if motion > 0.15 else 0) + rng.gauss(0, 1.5)
            st = base_t[w] + rng.gauss(0, 0.04)
            quality = min(1.0, max(0.0, 0.93 + rng.gauss(0, 0.02)))
            artifact = 0
            if post and w in AFFECTED:
                hr += 26
                st -= 0.6
            if post and w == "W05":
                quality = 0.45      # motion artifact / no contact after SOS
                artifact = 0b11
            gw_zone = z
            if post and w in EVACUEES and t >= T_IMPACT + timedelta(minutes=6):
                gw_zone = "Z6"
            rec = {
                "schema_version": "1.0", "data_origin": "synthetic", "scenario_id": scenario_id,
                "site_id": site_of_zone[z], "device_id": dev_of[w], "boot_id": 1, "sequence": seq[w],
                "measured_at": _ts(t), "received_at": _ts(t + timedelta(milliseconds=800)),
                "hr_bpm": _r(hr, 1), "spo2_pct": None, "skin_temp_c": _r(st, 2),
                "motion_rms_g": _r(max(0.0, motion), 3), "quality": _r(quality, 2),
                "battery_pct": max(1, 95 - int(minute / 3)) if w != "W12" else max(1, 30 - int(minute / 2.4)),
                "gateway_id": gw_of_zone[gw_zone], "zone_id": gw_zone, "worker_pseudonym": w,
                "channel_flags": 0b1111, "artifact_flags": artifact, "hr_synthetic": True,
                "fw_build": 101, "time_uncertainty_s": 0.5,
            }
            if z == "Z3" and T_LINK_LOSS <= t < T_LINK_RESTORE:
                # node buffer keeps the last 30 unacknowledged records (5 min)
                if t >= T_LINK_RESTORE - timedelta(minutes=5):
                    rec["received_at"] = _ts(T_LINK_RESTORE + timedelta(seconds=2))
                else:
                    backlog_lost += 1
                    continue
            physio.append(rec)
        t += step
    # duplicate redelivery (idempotent) and one conflicting record (quarantined)
    physio.append(dict(physio[100]))
    conflict = dict(physio[205])
    conflict["hr_bpm"] = (conflict["hr_bpm"] or 0) + 40.0
    physio.append(conflict)

    # ---------------- station ----------------
    station: List[dict] = []
    nodes = [(s, z) for z, _, _, _, s, _ in ZONES]
    sseq = {s: 0 for s, _ in nodes}
    t = T0
    while t < T_END:
        for s, z in nodes:
            sseq[s] += 1
            post = t >= T_IMPACT
            vib = abs(rng.gauss(0.02, 0.005))
            tilt_d = rng.gauss(0, 0.05)
            pdelta = abs(rng.gauss(2, 1))
            sound = int(abs(rng.gauss(300, 60)))
            gas = 0.40 + rng.gauss(0, 0.01)
            pir = False
            attach = True
            if s == "S02" and post:
                tilt_d = 7.5 + rng.gauss(0, 0.05)
                attach = False
                if t >= T_IMPACT + timedelta(minutes=10) and int((t - T0).total_seconds() / 10) % 4 == 0:
                    pir = True    # intermittent PIR presence cue in impacted zone
                if t < T_IMPACT + timedelta(seconds=10):
                    vib, pdelta, sound = 2.8, 180, 3900
            if s == "S03" and t >= parse_ts("2026-10-14T08:34:40Z"):
                gas = 1.9 + rng.gauss(0, 0.03)
            if s == "S05" and int((t - T0).total_seconds() / 10) % 9 == 0:
                pir = True        # warehouse PIR: no impact evidence -> no check task
            rec = {
                "schema_version": "st-1.0", "data_origin": "synthetic", "scenario_id": scenario_id,
                "site_id": site_of_zone[z], "zone_id": z, "device_id": s, "boot_id": 1, "sequence": sseq[s],
                "measured_at": _ts(t), "received_at": _ts(t + timedelta(milliseconds=600)),
                "vib_peak_g": _r(vib, 3), "accel_rms_g": _r(vib / 2, 3), "tilt_deg": _r(1.2 + tilt_d, 2),
                "tilt_delta_deg": _r(tilt_d, 2), "pressure_hpa": _r(1003.7 + rng.gauss(0, 0.05), 2),
                "pressure_delta_pa": _r(pdelta, 1), "temp_c": _r(21.9 + rng.gauss(0, 0.1), 2),
                "gas_v": _r(gas, 3), "sound_index": sound, "pir_presence": pir, "sos": False,
                "attachment_verified": attach, "quality": 0.95, "battery_pct": 88,
                "gateway_id": gw_of_zone[z], "sensor_flags": 0b11111, "fw_build": 201,
            }
            if z == "Z3" and T_LINK_LOSS <= t < T_LINK_RESTORE:
                if t >= T_LINK_RESTORE - timedelta(minutes=5):
                    rec["received_at"] = _ts(T_LINK_RESTORE + timedelta(seconds=3))
                else:
                    continue
            station.append(rec)
        t += step

    # ---------------- events ----------------
    events: List[dict] = []

    def ev(eid, site, zone, sc, dev, et, level, value, unit, obs, rep=None, unc=0.5, prov=None, ack="unacknowledged",
           quality=0.9, rule_version=1):
        events.append({
            "schema_version": "ev-1.0", "data_origin": "synthetic", "scenario_id": scenario_id,
            "site_id": site, "zone_id": zone, "event_id": eid, "source_class": sc, "device_id": dev,
            "event_type": et, "level": level, "value": value, "unit": unit,
            "observed_at": obs, "reported_at": rep or _ts(parse_ts(obs) + timedelta(seconds=1)),
            "time_uncertainty_s": unc, "rule_version": rule_version, "quality": quality,
            "ack_state": ack, "provenance": prov or {"source": dev, "method": "device rule"},
        })

    ext = {"source": "regional emergency information service (SYNTHETIC)", "method": "official bulletin"}
    ev("E001", SITE_A, None, "authoritative_external_alert", None, "air_raid_alert", 2, 1, None,
       "2026-10-14T08:30:00Z", unc=0, prov=ext)
    ev("E001B", SITE_B, None, "authoritative_external_alert", None, "air_raid_alert", 2, 1, None,
       "2026-10-14T08:30:00Z", unc=0, prov=ext)
    ev("E002", SITE_A, "Z2", "stationary_node", "S02", "impact_excursion", 2, 2.8, "g", "2026-10-14T08:34:12.400Z")
    ev("E003", SITE_A, "Z2", "stationary_node", "S02", "pressure_transient", 2, 180, "Pa", "2026-10-14T08:34:12.600Z")
    ev("E004", SITE_A, "Z2", "stationary_node", "S02", "loud_sound", 2, 3900, "index", "2026-10-14T08:34:12.700Z")
    ev("E005", SITE_A, "Z2", "stationary_node", "S02", "possible_impact_local", 3, 2.8, "g", "2026-10-14T08:34:13Z",
       prov={"source": "S02", "method": "composite rule: impact + (loud or pressure) within 2 s", "calibration_id": "uncalibrated"})
    ev("E006", SITE_A, "Z2", "stationary_node", "S02", "tilt_change", 2, 7.5, "deg", "2026-10-14T08:34:14Z")
    ev("E007", SITE_A, "Z2", "personnel_node", "A05", "sos", 3, 1, None, "2026-10-14T08:34:20Z")
    ev("E008", SITE_A, "Z3", "stationary_node", "S03", "gas_channel_alarm", 2, 1.9, "V", "2026-10-14T08:34:40Z",
       prov={"source": "S03", "method": "MQ-2 channel threshold", "calibration_id": "uncalibrated"})
    ev("E009", SITE_A, "Z3", "stationary_node", "S03", "sos", 3, 1, None, "2026-10-14T08:34:50Z")
    for i, dev in enumerate(("S03", "A08", "A09")):
        ev(f"E010{'abc'[i]}", SITE_A, "Z3", "gateway", dev, "link_loss", 2, 60, "s", "2026-10-14T08:36:30Z",
           prov={"source": "GA2", "method": "gateway silence detection"})
    ev("E011", SITE_A, "Z1", "operator_report", "OP-A", "asset_status", 2, "unavailable", None, "2026-10-14T08:36:00Z",
       unc=30, prov={"source": "site operator A", "method": "operator report", "asset_id": "grid_feed_A",
                     "capacity_lower_bounds": {"power_kw": 0, "energy_kwh": 0},
                     "basis": "grid feed A lost; no residual capacity can be justified"})
    ev("E012", SITE_A, None, "authoritative_external_alert", None, "external_strike_report", 3, 1, None,
       "2026-10-14T08:36:40Z", rep="2026-10-14T08:41:00Z", unc=120,
       prov={"source": "regional emergency information service (SYNTHETIC)", "method": "official bulletin",
             "area": "industrial district including site A"})
    ev("E013", SITE_B, "Z4", "personnel_node", "A10", "help_request", 3, 1, None, "2026-10-14T08:37:05Z")
    ev("E014", SITE_A, "Z2", "operator_report", "OP-A", "external_strike_report", 2, 1, None, "2026-10-14T08:38:00Z",
       unc=None, prov={"source": "relayed phone call", "method": "hearsay"})
    if variant == "post_impact":
        ev("E015", SITE_A, "Z1", "operator_report", "OP-A", "asset_status", 1, "available", None, "2026-10-14T08:39:00Z",
         unc=30, prov={"source": "site operator A", "method": "operator verification", "asset_id": "generator_G1",
                       "capacity_lower_bounds": {"power_kw": 60},
                       "basis": "generator G1 verified running; 75 kW rating derated to 60 kW justified lower bound"})
        ev("E015B", SITE_A, "Z1", "operator_report", "OP-A", "asset_status", 1, "available", None, "2026-10-14T08:39:30Z",
         unc=30, prov={"source": "site operator A", "method": "fuel gauge + log", "asset_id": "fuel_tank_G1",
                       "capacity_lower_bounds": {"energy_kwh": 200},
                       "basis": "fuel for >= 200 kWh at generator efficiency over 4 h horizon (operator estimate)"})
    for w in ("W01", "W02", "W03", "W04"):
        ev(f"E016{w}", SITE_A, "Z6", "responder_report", "RT2", "personnel_accounting", 1, "accounted_at_assembly", None,
           "2026-10-14T08:45:00Z", unc=60,
           prov={"source": "rescue team RT2", "method": "roll call at assembly point", "worker": w, "location_zone": "Z6"})
    ev("E017", SITE_A, "Z2", "responder_report", "RT1", "personnel_accounting", 2, "assistance_in_progress", None,
       "2026-10-14T08:41:30Z", unc=30,
       prov={"source": "rescue team RT1", "method": "response_action_start", "related_event": "E007", "worker": "W05",
             "location_zone": "Z2"})
    ev("E018", SITE_A, "Z1", "responder_report", "QA-1", "structural_assessment", 1, "no_restriction_observed", None,
       "2026-10-14T08:50:00Z", unc=60,
       prov={"source": "qualified assessor QA-1 (SYNTHETIC)", "method": "visual inspection",
             "assessor": "QA-1", "scope": "Z1 ground floor and corridor", "valid_until": "2026-10-14T12:00:00Z"})
    ev("E019", SITE_A, "Z6", "responder_report", "RT1", "personnel_accounting", 1, "handed_to_medical", None,
       "2026-10-14T08:52:00Z", unc=30,
       prov={"source": "rescue team RT1", "method": "handover record", "worker": "W05", "location_zone": "Z6"})
    for i, dev in enumerate(("S03", "A08", "A09")):
        ev(f"E020{'abc'[i]}", SITE_A, "Z3", "gateway", dev, "link_restored", 1, 1350, "s", "2026-10-14T08:58:00Z",
           prov={"source": "GA2", "method": "gateway reconnect"})
    ev("E021", SITE_A, "Z3", "gateway", "GA2", "buffer_eviction", 1, backlog_lost, "count", "2026-10-14T08:58:01Z",
       prov={"source": "GA2", "method": "node buffer accounting"})
    events.sort(key=lambda e: e["observed_at"])

    # ---------------- assets ----------------
    assets = {
        "schema_version": "as-1.0", "scenario_id": scenario_id, "data_origin": "synthetic",
        "planning_horizon_h": 4, "temporary_power_zone": "Z1",
        "resources": [
            {"resource_id": "power_kw", "unit": "kW", "kind": "power",
             "contributions": [{"asset_id": "grid_feed_A", "lower_bound": 250, "basis": "pre-event register"}],
             "basis": "sum of per-asset justified lower bounds; updated by asset_status events"},
            {"resource_id": "energy_kwh", "unit": "kWh", "kind": "energy",
             "contributions": [{"asset_id": "grid_feed_A", "lower_bound": 1000, "basis": "pre-event: 250 kW x 4 h"}],
             "basis": "energy over the 4 h planning horizon; separate from the power bound"},
            {"resource_id": "staff", "unit": "persons", "kind": "staff", "lower_bound": 6,
             "basis": "operators present on shift roster and accounted"},
            {"resource_id": "radio_channels", "unit": "channels", "kind": "comms", "lower_bound": 4,
             "basis": "licensed site radio channels"},
        ],
        "services": [
            {"service_id": "communications", "name": "Зв'язок", "zone_id": "Z1", "priority_weight": 6, "mandatory": True,
             "demand": {"power_kw": 4, "staff": 1, "radio_channels": 2}, "requires": [], "admissible": True,
             "admissibility_basis": "isolation checked by operator"},
            {"service_id": "emergency_lighting", "name": "Аварійне освітлення", "zone_id": "Z2", "priority_weight": 5,
             "mandatory": True, "demand": {"power_kw": 8}, "requires": [], "admissible": True,
             "admissibility_basis": "life-safety circuit"},
            {"service_id": "fire_water_pump", "name": "Пожежний насос", "zone_id": "Z1", "priority_weight": 8,
             "mandatory": True, "demand": {"power_kw": 25, "staff": 2}, "requires": ["communications"],
             "admissible": True, "admissibility_basis": "life-safety; operator procedure FP-2"},
            {"service_id": "water_support", "name": "Водопостачання (підтримка)", "zone_id": "Z3", "priority_weight": 4,
             "mandatory": False, "demand": {"power_kw": 18, "staff": 2}, "requires": [], "admissible": None,
             "admissibility_basis": "pump room Z3 not assessed (gas-channel alarm, link loss)", "asset_ids": ["pump_P1"]},
            {"service_id": "production", "name": "Виробництво", "zone_id": "Z2", "priority_weight": 1, "mandatory": False,
             "demand": {"power_kw": 45, "staff": 4}, "requires": ["communications"], "admissible": True,
             "admissibility_basis": "operator", "actuation_required_to_restore": True},
            {"service_id": "process_monitoring", "name": "Моніторинг процесу", "zone_id": "Z4", "priority_weight": 3,
             "mandatory": False, "demand": {"power_kw": 3, "staff": 1, "radio_channels": 1}, "requires": ["communications"],
             "admissible": True, "admissibility_basis": "read-only monitoring, no control path"},
        ],
        "equipment": [
            {"kind": "certified_gas_detector", "quantity": 1, "status": "available"},
            {"kind": "loader", "quantity": 1, "status": "available"},
            {"kind": "mobile_generator", "quantity": 1, "status": "available"},
            {"kind": "cable_kit", "quantity": 2, "status": "available"},
            {"kind": "spare_gateway", "quantity": 1, "status": "available"},
            {"kind": "pump_kit", "quantity": 1, "status": "unknown"},
        ],
        "assets": [
            {"asset_id": "grid_feed_A", "zone_id": "Z1", "kind": "power_feed", "status": "available"},
            {"asset_id": "generator_G1", "zone_id": "Z1", "kind": "generator", "status": "available",
             "capacity_interval_kw": [60, 75]},
            {"asset_id": "pump_P1", "zone_id": "Z3", "kind": "pump", "status": "unknown"},
        ],
    }

    # ---------------- teams ----------------
    zones_list = [z for z, *_ in ZONES]
    pos = {"Z1": (0, 0), "Z2": (80, 20), "Z3": (60, 90), "Z6": (150, -40), "Z4": (1800, 0), "Z5": (1850, 120)}
    dist = {a: {b: int(round(math.dist(pos[a], pos[b]))) for b in zones_list if b != a} for a in zones_list}
    teams = {
        "schema_version": "tm-1.0", "scenario_id": scenario_id, "data_origin": "synthetic",
        "travel_speed_m_per_s": 1.2,
        "zone_distance_m": dist,
        "teams": [
            {"team_id": "RT1", "name": "Рятувальна ланка 1", "role": "rescue", "location_zone": "Z6",
             "competencies": ["search", "first_aid", "rope_rescue"], "ppe": ["scba", "gas_monitor", "helmet"]},
            {"team_id": "RT2", "name": "Рятувальна ланка 2", "role": "rescue", "location_zone": "Z6",
             "competencies": ["search", "first_aid"], "ppe": ["helmet"]},
            {"team_id": "RT3", "name": "Медична ланка (майданчик Б)", "role": "rescue", "location_zone": "Z4",
             "competencies": ["first_aid", "medical_support"], "ppe": [],
             "available_until": "2026-10-14T08:55:00Z", "note": "committed to medical point after 08:55"},
            {"team_id": "RT4", "name": "Пошукова ланка (майданчик Б)", "role": "rescue", "location_zone": "Z5",
             "competencies": ["search", "gas_detection"], "ppe": ["scba", "gas_monitor", "helmet"],
             "available_from": "2026-10-14T08:50:00Z"},
            {"team_id": "ST1", "name": "Кваліфікований експерт з конструкцій", "role": "assessment", "location_zone": "Z6",
             "competencies": ["structural_assessment"], "ppe": ["helmet"]},
            {"team_id": "RC1", "name": "Бригада електриків/зв'язку", "role": "recovery", "location_zone": "Z1",
             "competencies": ["electrical", "comms"], "ppe": ["helmet"]},
            {"team_id": "RC2", "name": "Бригада ліквідації наслідків", "role": "recovery", "location_zone": "Z6",
             "competencies": ["gas_detection", "debris_clearance", "water_systems"], "ppe": ["scba", "gas_monitor", "helmet"]},
        ],
        "access": [
            {"zone_id": "Z1", "status": "authorised", "scope": ["all"], "authorised_by": "incident command",
             "valid_from": "2026-10-14T08:00:00Z"},
            {"zone_id": "Z6", "status": "authorised", "scope": ["all"], "authorised_by": "incident command",
             "valid_from": "2026-10-14T08:00:00Z"},
            {"zone_id": "Z4", "status": "authorised", "scope": ["all"], "authorised_by": "incident command",
             "valid_from": "2026-10-14T08:00:00Z"},
            {"zone_id": "Z5", "status": "authorised", "scope": ["all"], "authorised_by": "incident command",
             "valid_from": "2026-10-14T08:00:00Z"},
            {"zone_id": "Z2", "status": "authorised", "scope": ["rescue"], "authorised_by": "incident command",
             "conditions": ["helmet", "two-person rule"], "valid_from": "2026-10-14T08:36:00Z"},
            {"zone_id": "Z2", "status": "authorised", "scope": ["recovery", "assessment"], "authorised_by": "incident command",
             "valid_from": "2026-10-14T08:55:00Z"},
            {"zone_id": "Z3", "status": "authorised", "scope": ["gas_hazard_check"], "authorised_by": "incident command",
             "conditions": ["scba", "certified gas detector"], "valid_from": "2026-10-14T09:15:00Z"},
        ],
        "_note": "Z3 rescue/structural access deliberately left UNKNOWN to exercise escalation records.",
    }

    manifest = {
        "dataset_id": scenario_id, "scenario_id": scenario_id, "variant": variant,
        "variant_description": VARIANTS[variant], "data_origin": "synthetic",
        "label": "SYNTHETIC — constructed scenario; no real site, persons, attack or measured physiology",
        "generator": "umsf_agent.scenario", "seed": seed,
        "start": _ts(T0), "end": _ts(T_END), "baseline_end": _ts(BASELINE_END),
        "sites": [SITE_A, SITE_B], "timezone_display": "Europe/Kyiv",
        "notes": ["station records are synthetic 10 s summaries", "HR is a synthetic interface field",
                  "one duplicate and one conflicting physio record are included on purpose"],
    }

    paths = {}

    def wj(name, obj):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        paths[name] = p

    def wl(name, rows):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")
        paths[name] = p

    wj("roster.json", rosters)
    wl("physio.jsonl", physio)
    wl("station.jsonl", station)
    wl("events.jsonl", events)
    wj("assets.json", assets)
    wj("teams.json", teams)
    manifest["files"] = {n: sha256_file(p) for n, p in sorted(paths.items())}
    wj("manifest.json", manifest)
    return paths
