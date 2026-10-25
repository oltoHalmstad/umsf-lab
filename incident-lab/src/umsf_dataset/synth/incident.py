"""Synthetic post-impact incident scenario for the decision-support agent (P3).

Everything here is SYNTHETIC (``data_origin: synthetic``) and produced by a deterministic
generator. It exercises the evidence semantics of the manuscript (Sec. 3.8-3.9, 4.9):

* strike attribution only via ``authoritative_external_alert`` (``air_raid_alert`` then
  ``external_strike_report`` with provenance); local composites are ``possible_impact_local``
  (unverified) and are associated with the external report only through an explicit,
  timestamped operator association (manifest ``incident_associations``);
* gas is an uncalibrated MQ-2 channel voltage (``gas_v``) with ``gas_channel_alarm`` events;
* link loss makes current evidence ``unknown``; missing records are absent (never zero);
  no casualty or collapse inference anywhere;
* SOS / help requests are independent urgent events;
* ``asset_status`` records and ``assets.json`` reproduce the Table 16 service example.

See docs/DATASET_FORMAT.md for the directory layout.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import random

from .. import __version__
from ..records import event_record, physio_record, station_record
from ..timeutil import from_epoch, to_epoch

SEED = 20261014
T0 = "2026-10-14T05:00:00Z"  # 08:00 Europe/Kyiv
DURATION_S = 30 * 60
SCENARIO_ID = "incident-synthetic-001"
INCIDENT_ID = "INC-0001"
FACILITY = "FAC-DEMO"

SITES = {
    "SITE-A": {"gateways": ["AG1", "AG2"], "zones": [
        ("A-Z1", "Workshop No. 1, north wing", ["W01", "W02", "W03"], ["SA1"]),
        ("A-Z2", "Control room", ["W04", "W05", "W06"], ["SA2"]),
        ("A-Z3", "Electrical room (no rostered workers)", [], ["SA3"])]},
    "SITE-B": {"gateways": ["BG1", "BG2"], "zones": [
        ("B-Z1", "Water treatment hall", ["W07", "W08", "W09"], ["SB1"]),
        ("B-Z2", "Warehouse", ["W10", "W11", "W12"], ["SB2"])]},
}
DEVICE_OF = {f"W{i:02d}": (f"A{i:02d}" if i <= 6 else f"B{i - 6:02d}") for i in range(1, 13)}

# Event times (seconds after T0)
T_AIR_RAID, T_IMPACT, T_LINK_A03, T_A02_LOSS, T_SA1_LOSS = 120, 480, 480, 495, 500
T_SOS_W01, T_HELP_W05, T_ACCOUNT_1, T_ASSETS, T_STRIKE_REPORT = 510, 540, 570, 600, 720
T_A02_RESTORE, T_STRUCT, T_SB2_LOSS, T_SB2_RESTORE, T_ACCOUNT_2, T_ALL_CLEAR = 840, 900, 1020, 1060, 1200, 1500
NODE_BUFFER = 30  # records (5 min at 10 s), Sec. 3.3.7 / A.2

SERVICES = [  # Table 16
    {"service_id": "communications", "name": "Communications", "demand_units": 1, "weight": 6, "mandatory": True,
     "prerequisites": []},
    {"service_id": "emergency_lighting", "name": "Emergency lighting", "demand_units": 2, "weight": 5,
     "mandatory": True, "prerequisites": []},
    {"service_id": "water_support", "name": "Water support", "demand_units": 3, "weight": 4, "mandatory": False,
     "prerequisites": []},
    {"service_id": "production", "name": "Production", "demand_units": 4, "weight": 1, "mandatory": False,
     "prerequisites": ["communications"]},
]
TEAMS = [
    {"team_id": "RT-1", "name": "Site fire and rescue unit", "site_id": "SITE-A", "members": 4,
     "competencies": ["search_and_rescue", "first_aid", "casualty_extraction"], "available": True},
    {"team_id": "RT-2", "name": "Medical first responders", "site_id": "SITE-A", "members": 2,
     "competencies": ["first_aid", "medical_assessment", "medical_evacuation"], "available": True},
    {"team_id": "RT-3", "name": "Gas and hazmat response", "site_id": "SITE-B", "members": 3,
     "competencies": ["gas_detection_qualified_instrument", "hazmat", "ventilation_assessment"], "available": True},
    {"team_id": "RT-4", "name": "Electrical and utilities restoration", "site_id": "SITE-B", "members": 3,
     "competencies": ["electrical_isolation", "utility_restoration", "backup_power"], "available": True},
    {"team_id": "RT-5", "name": "Structural assessment engineer", "site_id": "SITE-A", "members": 1,
     "competencies": ["structural_assessment"], "available": False, "available_from_min": 15},
]
ZONE_ETA_MIN = {"SITE-A": {"A-Z1": 3, "A-Z2": 2, "A-Z3": 4, "B-Z1": 22, "B-Z2": 24},
                "SITE-B": {"A-Z1": 21, "A-Z2": 22, "A-Z3": 20, "B-Z1": 2, "B-Z2": 3}}


def rosters() -> dict:
    out = {}
    for site, cfg in SITES.items():
        workers = [w for z in cfg["zones"] for w in z[2]]
        out[site] = {"site_id": site,
                     "zones": [{"zone_id": z, "name": n, "expected_workers": ws, "stationary_nodes": ns}
                               for z, n, ws, ns in cfg["zones"]],
                     "device_map": {DEVICE_OF[w]: w for w in workers},
                     "valid_from": "2026-10-14T00:00:00Z", "valid_to": "2026-10-15T00:00:00Z"}
    return out


def allocate_services(capacity_units: float, services=SERVICES) -> dict:
    """Exhaustive enumeration of Eq. (10) for indivisible services (Sec. 4.9 reference solution)."""
    best = None
    for y in itertools.product((0, 1), repeat=len(services)):
        sel = dict(zip((s["service_id"] for s in services), y))
        if any(s["mandatory"] and not sel[s["service_id"]] for s in services):
            continue
        if any(sel[s["service_id"]] and not all(sel[p] for p in s["prerequisites"]) for s in services):
            continue
        if sum(s["demand_units"] * sel[s["service_id"]] for s in services) > capacity_units:
            continue
        score = sum(s["weight"] * sel[s["service_id"]] for s in services)
        if best is None or score > best[0]:
            best = (score, sel)
    if best is None:
        return {"capacity_units": capacity_units, "feasible": False, "allocation": None, "Q_percent": None}
    total = sum(s["weight"] for s in services)
    return {"capacity_units": capacity_units, "feasible": True, "allocation": best[1],
            "priority_sum": best[0], "Q_percent": round(100 * best[0] / total, 2)}


class _Gen:
    def __init__(self, seed: int, duration_s: int, station_interval_s: int):
        self.rng = random.Random(seed)
        self.t0 = to_epoch(T0)
        self.duration_s, self.st_int = duration_s, station_interval_s
        self.physio, self.station, self.events = [], [], []
        self.n_ev = 0

    def ts(self, t):
        return from_epoch(self.t0 + t)

    def ev(self, t, site, zone, src, dev, etype, level, value=None, *, method, source=None, delay=0.4,
           unit="", assessor=None, valid_until=None, **ext):
        if t > self.duration_s:
            return None
        self.n_ev += 1
        prov = {"source": source or f"{src}:{dev}", "method": method}
        if assessor is not None or valid_until is not None:
            prov.update({"assessor": assessor, "valid_until": valid_until})
        e = event_record(site_id=site, zone_id=zone, event_id=f"{INCIDENT_ID}-EV{self.n_ev:04d}", source_class=src,
                         device_id=dev, event_type=etype, level=level, value=value, unit=unit,
                         observed_at=self.ts(t), reported_at=self.ts(t + delay), provenance=prov,
                         time_uncertainty_s=ext.pop("time_uncertainty_s", 0.5), rule_version=ext.pop("rule_version", 1),
                         quality=None, data_origin="synthetic", scenario_id=SCENARIO_ID, incident_id=INCIDENT_ID, **ext)
        self.events.append(e)
        return e["event_id"]

    # -------------------------------------------------------------- physiology
    def gen_physio(self):
        rng = self.rng
        for site, cfg in SITES.items():
            gw = cfg["gateways"]
            for zi, (zone, _n, workers, _nodes) in enumerate(cfg["zones"]):
                for w in workers:
                    dev = DEVICE_OF[w]
                    hr0, tsk, batt = rng.uniform(66, 78), rng.uniform(32.6, 33.8), rng.uniform(80, 98)
                    evicted = 0
                    for k in range(self.duration_s // 10):
                        t = 10 * k
                        if dev == "A03" and t >= T_LINK_A03:
                            break  # node silent: records absent, never zero-filled
                        stress = 0.0
                        if site == "SITE-A" and t >= T_IMPACT:
                            stress = (20.0 if zone == "A-Z1" else 12.0) * math.exp(-(t - T_IMPACT) / 600)
                        if t >= T_AIR_RAID:
                            stress += 3.0
                        moving = site == "SITE-A" and T_IMPACT <= t < T_IMPACT + 150
                        hr = hr0 + stress + rng.gauss(0, 2.5) + (8 if moving else 0)
                        q = rng.uniform(0.85, 0.98)
                        art = 0
                        if moving:
                            q, art = rng.uniform(0.45, 0.7), 1
                        recv = t + rng.uniform(0.3, 1.5)
                        if dev == "A02" and T_A02_LOSS <= t < T_A02_RESTORE:
                            n_out = (T_A02_RESTORE - T_A02_LOSS) // 10
                            idx = (t - T_A02_LOSS) // 10
                            if idx < n_out - NODE_BUFFER:
                                evicted += 1
                                continue  # oldest records evicted from the RAM buffer
                            recv = T_A02_RESTORE + 1 + 0.2 * idx  # delayed first arrival (history only)
                        self.physio.append(physio_record(
                            site_id=site, device_id=dev, boot_id=3, sequence=k + 1, measured_at=self.ts(t),
                            received_at=self.ts(recv), hr_bpm=round(hr, 1), spo2_pct=None,
                            skin_temp_c=round(tsk + rng.gauss(0, 0.1), 2),
                            motion_rms_g=round(abs(rng.gauss(0.6 if moving else 0.05, 0.1 if moving else 0.02)), 3),
                            quality=round(q, 2), battery_pct=round(batt - 4.0 * t / 3600, 1),
                            data_origin="synthetic", scenario_id=SCENARIO_ID, gateway_id=gw[zi % 2],
                            zone_id=zone, worker_pseudonym=w, channel_flags=0x07, artifact_flags=art,
                            time_uncertainty_s=0.5))
                    if dev == "A02" and evicted:
                        self.ev(T_A02_RESTORE + 1, site, zone, "personnel_node", dev, "buffer_eviction", "warning",
                                float(evicted), method="node RAM buffer (30 records) overflow during outage")

    # -------------------------------------------------------------- stationary nodes
    def gen_station(self):
        rng = self.rng
        for site, cfg in SITES.items():
            for zi, (zone, _n, _w, nodes) in enumerate(cfg["zones"]):
                for node in nodes:
                    p0, temp0, gas0, snd0 = rng.uniform(1002.5, 1004.0), rng.uniform(19.5, 23.0), \
                        rng.uniform(0.70, 0.85), rng.uniform(200, 300)
                    seq = 0
                    for t in range(0, self.duration_s, self.st_int):
                        seq += 1
                        if node == "SA1" and t >= T_SA1_LOSS:
                            break
                        if node == "SB2" and T_SB2_LOSS <= t < T_SB2_RESTORE:
                            continue
                        vib, snd, dp = 0.03 + rng.uniform(-0.005, 0.005), snd0 + rng.uniform(-15, 15), \
                            int(rng.uniform(0, 4))
                        tilt, gas, flags = 0.4 + rng.uniform(-0.05, 0.05), gas0 + rng.uniform(-0.005, 0.005), 0
                        if site == "SITE-A" and t == T_IMPACT:
                            vib = {"SA1": 4.1, "SA2": 0.9, "SA3": 0.6}[node]
                            snd, dp = {"SA1": 3900, "SA2": 2600, "SA3": 1800}[node], \
                                {"SA1": 350, "SA2": 120, "SA3": 90}[node]
                            flags |= 4 | 8 | 64 if node == "SA1" else 8
                        if node == "SA1" and t > T_IMPACT:
                            tilt += 7.5
                            flags |= 32 | 128  # tilt alarm + attachment uncertain
                            gas = min(1.45, gas0 + (t - T_IMPACT) * 0.04)
                            if gas >= 1.2:
                                flags |= 16
                        pir = None if node == "SA3" else rng.random() < (0.7 if t < T_IMPACT + 60 else 0.3)
                        if pir:
                            flags |= 1
                        self.station.append(station_record(
                            site_id=site, zone_id=zone, device_id=node, boot_id=1, sequence=seq,
                            measured_at=self.ts(t), received_at=self.ts(t + rng.uniform(0.05, 0.4)),
                            data_origin="synthetic", scenario_id=SCENARIO_ID, vib_peak_g=round(vib, 3),
                            accel_rms_g=round(vib / 3, 3), tilt_deg=round(tilt, 1), tilt_delta_deg=round(tilt - 0.4, 1),
                            pressure_hpa=round(p0 + rng.uniform(-0.05, 0.05), 1), pressure_delta_pa=dp,
                            temp_c=round(temp0 + rng.uniform(-0.03, 0.03), 2), gas_v=round(gas, 3),
                            sound_index=int(snd), pir_presence=pir, sos=False, quality=1.0, battery_pct=90.0,
                            gateway_id=cfg["gateways"][zi % 2], flags=flags,
                            sensor_flags=0x0F if node == "SA3" else 0x1F, fw_build=1))

    # -------------------------------------------------------------- events
    def gen_events(self) -> dict:
        ids = {}
        ext_alert = {"source": "regional air-raid alert service (simulated feed)",
                     "method": "official alert channel; synthetic replay"}
        for site in SITES:
            ids[f"air_raid_{site}"] = self.ev(T_AIR_RAID, site, None, "authoritative_external_alert", "EXT-ALERT",
                                              "air_raid_alert", "urgent", None, unit=None, method=ext_alert["method"],
                                              source=ext_alert["source"], delay=2.0, time_uncertainty_s=5.0,
                                              rule_version=None)
        sa = "SITE-A"
        local = []
        for node, zone, g in (("SA1", "A-Z1", 4.1), ("SA2", "A-Z2", 0.9), ("SA3", "A-Z3", 0.6)):
            if g >= 1.5:
                local.append(self.ev(T_IMPACT, sa, zone, "stationary_node", node, "impact_excursion", "warning", g,
                                     method="stationary IMU peak above design threshold 1.5 g (not calibrated)"))
            local.append(self.ev(T_IMPACT, sa, zone, "stationary_node", node, "loud_sound", "warning",
                                 {"SA1": 3900.0, "SA2": 2600.0, "SA3": 1800.0}[node], method="microphone index"))
        local.append(self.ev(T_IMPACT, sa, "A-Z1", "stationary_node", "SA1", "pressure_transient", "warning", 350.0,
                             method="BMP280 max |dp| in 1 s window"))
        ids["possible_impact_local"] = self.ev(
            T_IMPACT + 1, sa, "A-Z1", "stationary_node", "SA1", "possible_impact_local", "warning", 4.1,
            method="local composite: impact + (loud sound or pressure transient) within 2 s; UNVERIFIED; "
                   "not a strike attribution")
        local.append(ids["possible_impact_local"])
        self.ev(T_IMPACT + 2, sa, "A-Z1", "stationary_node", "SA1", "tilt_change", "warning", 7.5,
                method="inclination change vs. mounting reference; attachment now uncertain")
        self.ev(T_IMPACT + 12, sa, "A-Z1", "stationary_node", "SA1", "gas_channel_alarm", "warning", 1.2,
                method="uncalibrated MQ-2 channel voltage above design threshold 1.20 V; no gas identity or "
                       "concentration")
        gw_a = "gateway"
        self.ev(T_LINK_A03 + 30, sa, "A-Z1", gw_a, "A03", "link_loss", "warning", 30.0, gateway_id="AG1",
                source="gateway:AG1", method="no frame for 30 s; current evidence unknown (not a casualty inference)")
        self.ev(T_A02_LOSS + 30, sa, "A-Z1", gw_a, "A02", "link_loss", "warning", 30.0, gateway_id="AG1",
                source="gateway:AG1", method="no frame for 30 s")
        self.ev(T_SA1_LOSS + 2, sa, "A-Z1", gw_a, "SA1", "link_loss", "warning", 2.0, gateway_id="AG1",
                source="gateway:AG1", method="stationary staleness 2 s; zone mechanical state unknown (not collapse)")
        ids["sos_W01"] = self.ev(T_SOS_W01, sa, "A-Z1", "personnel_node", "A01", "sos", "urgent", 1.0,
                                 method="personnel help button (GPIO27); independent urgent pathway")
        ids["help_W05"] = self.ev(T_HELP_W05, sa, "A-Z2", "personnel_node", "A05", "help_request", "urgent", 1.0,
                                  method="personnel help button")
        self.ev(T_ACCOUNT_1, sa, None, "operator_report", "OP-A", "personnel_accounting", "warning", 1.0, unit="count",
                method="shift supervisor roll call (synthetic)", delay=5.0, time_uncertainty_s=30.0, rule_version=None,
                details={"expected": 6, "accounted": ["W02", "W04", "W06"],
                         "assistance_requested": ["W01", "W05"], "unaccounted": ["W03"],
                         "last_confirmed": {"W03": {"zone_id": "A-Z1", "at": self.ts(T_LINK_A03 - 10)}},
                         "note": "unaccounted means unresolved whereabouts, not injury or death"})
        for i, s in enumerate(SERVICES):
            status = "unavailable" if s["service_id"] == "production" else "available"
            self.ev(T_ASSETS + i, sa, None, "operator_report", "OP-A", "asset_status",
                    "notice" if status == "available" else "warning", 1.0 if status == "available" else 0.0,
                    unit="1/0", method="operator report of service state (synthetic)", delay=10.0,
                    time_uncertainty_s=60.0, rule_version=None,
                    details={"service_id": s["service_id"], "status": status, "demand_units": s["demand_units"],
                             "weight": s["weight"], "mandatory": s["mandatory"], "prerequisites": s["prerequisites"]})
        self.ev(T_ASSETS + 5, sa, "A-Z3", "operator_report", "OP-A", "asset_status", "warning", 6.0,
                unit="illustrative units", method="operator estimate of usable backup capacity (lower bound)",
                delay=10.0, time_uncertainty_s=60.0, rule_version=None,
                details={"resource_id": "backup_power_units", "capacity_lower_bound": 6, "capacity_upper_bound": 8,
                         "pre_event_rating": 10, "note": "unknown capacity is not replaced by the rating"})
        ids["strike_report"] = self.ev(
            T_STRIKE_REPORT, sa, None, "authoritative_external_alert", "EXT-MILADM", "external_strike_report",
            "urgent", None, unit=None, method="official public statement (synthetic replay)", delay=30.0,
            source="regional military administration (simulated)", time_uncertainty_s=300.0, rule_version=None,
            details={"reported_area": "industrial district including SITE-A (synthetic)", "report_ref": "SYN-0001"})
        self.ev(T_A02_RESTORE, sa, "A-Z1", gw_a, "A02", "link_restored", "notice",
                float(T_A02_RESTORE - T_A02_LOSS), gateway_id="AG1", source="gateway:AG1", method="frames resumed")
        self.ev(T_STRUCT, sa, "A-Z1", "responder_report", "RT-1", "structural_assessment", "warning", None,
                unit=None, method="preliminary visual inspection (synthetic)", delay=60.0, time_uncertainty_s=120.0,
                rule_version=None, assessor="qualified structural assessor (synthetic role)",
                valid_until=self.ts(T_STRUCT + 3600),
                details={"status": "restricted_access", "scope": "A-Z1 north wing",
                         "taxonomy": "preliminary; no damage percentage estimated"})
        self.ev(T_SB2_LOSS + 2, "SITE-B", "B-Z2", gw_a, "SB2", "link_loss", "warning", 2.0, gateway_id="BG2",
                source="gateway:BG2", method="stationary staleness 2 s")
        self.ev(T_SB2_RESTORE, "SITE-B", "B-Z2", gw_a, "SB2", "link_restored", "notice",
                float(T_SB2_RESTORE - T_SB2_LOSS), gateway_id="BG2", source="gateway:BG2", method="frames resumed")
        self.ev(T_ACCOUNT_2, sa, None, "operator_report", "OP-A", "personnel_accounting", "warning", 1.0,
                unit="count", method="incident coordinator reconciliation (synthetic)", delay=5.0,
                time_uncertainty_s=30.0, rule_version=None,
                details={"expected": 6, "accounted": ["W02", "W04", "W06"],
                         "responder_confirmed_assistance": ["W05"], "assistance_requested": ["W01"],
                         "unaccounted": ["W03"]})
        for site in SITES:
            self.ev(T_ALL_CLEAR, site, None, "authoritative_external_alert", "EXT-ALERT", "air_raid_all_clear",
                    "info", None, unit=None, method=ext_alert["method"], source=ext_alert["source"], delay=2.0,
                    time_uncertainty_s=5.0, rule_version=None)
        ids["local_events"] = [x for x in local if x]
        return ids


def generate(seed: int = SEED, duration_s: int = DURATION_S, station_interval_s: int = 1) -> dict:
    g = _Gen(seed, duration_s, station_interval_s)
    g.gen_physio()
    g.gen_station()
    ids = g.gen_events()
    g.events.sort(key=lambda e: (e["observed_at"], e["event_id"]))
    g.physio.sort(key=lambda r: (r["received_at"], r["device_id"]))
    g.station.sort(key=lambda r: (r["measured_at"], r["device_id"]))
    associations = []
    if ids.get("strike_report") and ids.get("possible_impact_local"):
        associations.append({
            "association_id": "ASSOC-0001", "external_event_id": ids["strike_report"],
            "local_event_ids": ids["local_events"], "associated_by": "OP-A (incident coordinator, synthetic)",
            "associated_at": from_epoch(to_epoch(T0) + T_STRIKE_REPORT + 120),
            "basis": "temporal and spatial coincidence; both provenance chains retained; local events remain "
                     "unverified and are not themselves a strike attribution"})
    return {"physio": g.physio, "station": g.station, "events": g.events, "associations": associations, "ids": ids}


def assets() -> dict:
    return {
        "facility_id": FACILITY, "site_id": "SITE-A", "planning_interval_min": 60,
        "resources": [{"resource_id": "backup_power_units", "unit": "illustrative units", "capacity_lower_bound": 6,
                       "capacity_upper_bound": 8, "pre_event_rating": 10,
                       "source": "operator report (synthetic)", "as_of": from_epoch(to_epoch(T0) + T_ASSETS + 5)}],
        "services": [{**s, "demand": {"backup_power_units": s["demand_units"]}, "admissible": True,
                      "status": "unavailable" if s["service_id"] == "production" else "available"}
                     for s in SERVICES],
        "reference_solutions": [allocate_services(b) for b in (2, 4, 6, 10)],
        "notes": ["Table 16 inputs (manuscript Sec. 4.9); weights are illustrative, not survival probabilities.",
                  "Q is weighted service coverage, not fraction of personnel rescued or facility restored.",
                  "Mandatory life-safety services are constraints; infeasible means no valid Q."],
    }


def teams() -> dict:
    return {"teams": [{**t, "eta_min": ZONE_ETA_MIN[t["site_id"]]} for t in TEAMS],
            "competency_catalog": sorted({c for t in TEAMS for c in t["competencies"]}),
            "notes": ["eta_min values are qualified assignment-time estimates (delta_rj) for the illustrative "
                      "planner; not measured travel times.",
                      "Task priorities, access restrictions and approvals belong to incident command."]}


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def write(outdir: str, seed: int = SEED, duration_s: int = DURATION_S, station_interval_s: int = 1) -> dict:
    os.makedirs(outdir, exist_ok=True)
    g = generate(seed, duration_s, station_interval_s)
    ros = rosters()

    def dump(name, obj):
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1, ensure_ascii=False)
            fh.write("\n")

    def jsonl(name, rows):
        with open(os.path.join(outdir, name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    dump("roster.json", {"facility_id": FACILITY, "valid_from": "2026-10-14T00:00:00Z",
                         "valid_to": "2026-10-15T00:00:00Z", "sites": list(ros.values())})
    for site, r in ros.items():
        dump(f"roster_{site}.json", r)
    jsonl("physio.jsonl", g["physio"])
    jsonl("station.jsonl", g["station"])
    jsonl("events.jsonl", g["events"])
    dump("assets.json", assets())
    dump("teams.json", teams())
    files = ["roster.json"] + [f"roster_{s}.json" for s in ros] + ["physio.jsonl", "station.jsonl", "events.jsonl",
                                                                   "assets.json", "teams.json"]
    counts = {"physio": len(g["physio"]), "station": len(g["station"]), "events": len(g["events"]),
              "events_by_type": {}}
    for e in g["events"]:
        counts["events_by_type"][e["event_type"]] = counts["events_by_type"].get(e["event_type"], 0) + 1
    manifest = {
        "dataset": "umsf-incident-synthetic", "scenario_id": SCENARIO_ID, "incident_id": INCIDENT_ID,
        "facility_id": FACILITY, "generator": "umsf_dataset.synth.incident", "generator_version": __version__,
        "seed": seed, "data_origin": "synthetic", "t0": T0, "duration_s": duration_s,
        "physio_interval_s": 10, "station_interval_s": station_interval_s, "display_tz": "Europe/Kyiv",
        "schema_versions": {"physio": "1.0", "station": "st-1.0", "event": "ev-1.0"},
        "counts": counts, "files": [{"path": f, "sha256": _sha(os.path.join(outdir, f)),
                                     "bytes": os.path.getsize(os.path.join(outdir, f))} for f in files],
        "incident_associations": g["associations"],
        "scenario_script": {  # generator ground truth for P3 testing; NOT field truth
            "local_impact_zone": "A-Z1", "local_impact_at": from_epoch(to_epoch(T0) + T_IMPACT),
            "silent_nodes": {"A03": "from t0+480 s (no restore)", "SA1": "from t0+500 s (no restore)",
                             "A02": "t0+495..840 s, buffered records delivered late, oldest evicted",
                             "SB2": "t0+1020..1060 s"},
            "urgent_requests": [{"worker": "W01", "zone_id": "A-Z1", "event": "sos"},
                                {"worker": "W05", "zone_id": "A-Z2", "event": "help_request"}],
            "unresolved_personnel": ["W03"], "gas_channel_alarm_zone": "A-Z1",
            "structural_assessment": {"zone_id": "A-Z1", "status": "restricted_access"},
            "usable_backup_capacity_lower_bound": 6, "expected_Q_percent_at_lower_bound": 93.75},
        "evidence_boundaries": [
            "All records are synthetic; no human data.",
            "Strike attribution appears only as external_strike_report from authoritative_external_alert.",
            "possible_impact_local is an unverified local composite.",
            "gas_v is an uncalibrated MQ-2 channel voltage; gas_channel_alarm is not a concentration.",
            "Link loss means current evidence unknown; it never implies collapse or casualties.",
            "Missing measurements are null or absent records; never zero/normal.",
            "spo2_pct is null by default (no validated estimator).",
            "Stationary nodes are not workers; attachment_verified is false (no verified structural mounting).",
        ],
    }
    dump("manifest.json", manifest)
    return manifest
