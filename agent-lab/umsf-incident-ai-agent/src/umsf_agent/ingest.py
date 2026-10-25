"""Tolerant loader for a dataset directory (P1 `umsf-incident-dataset` export format).

Expected files (all optional except that something must be present):
    roster.json     explicit roster (PROTOCOL.md Sec. 5.4); one object or a list
                    of per-site objects, or {"rosters": [...]}
    physio.jsonl    physio records, schema "1.0" (PROTOCOL Sec. 5.1)
    station.jsonl   stationary-node records, schema "st-1.0" (Sec. 5.2)
    events.jsonl    events, schema "ev-1.0" (Sec. 5.3)
    assets.json     resources/services/assets for continuity (docs/INPUT_FORMAT.md)
    teams.json      response teams, access authorisations, zone distances
    manifest.json   dataset metadata (origin, scenario, period, baseline end)

Semantics applied at load (PROTOCOL Sec. 0):
* identity (site_id, device_id, boot_id, sequence); identical redelivery is
  idempotent; changed payload under the same identity is a conflict -> the
  whole identity is quarantined (excluded from analysis, kept for audit);
* values out of the declared physical range become null with a reason; they are
  never replaced by "normal" values;
* stationary nodes are never counted as workers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .util import canonical_json, parse_ts, sha256_file, sha256_obj

PHYSIO_REQUIRED = ["schema_version", "data_origin", "scenario_id", "site_id", "device_id", "boot_id",
                   "sequence", "measured_at", "received_at", "hr_bpm", "spo2_pct", "skin_temp_c",
                   "motion_rms_g", "quality", "battery_pct"]
PHYSIO_RANGES = {"hr_bpm": (20, 250), "spo2_pct": (50, 100), "skin_temp_c": (20, 45),
                 "motion_rms_g": (0, 16), "battery_pct": (0, 100), "quality": (0, 1)}
SOURCE_CLASSES = {"personnel_node", "stationary_node", "gateway", "operator_report",
                  "responder_report", "authoritative_external_alert"}
IDENTITY_KEYS = ("site_id", "device_id", "boot_id", "sequence")


@dataclass
class Dataset:
    path: str
    rosters: List[dict] = field(default_factory=list)
    zones: Dict[str, dict] = field(default_factory=dict)            # zone_id -> zone (+site_id)
    device_map: Dict[str, str] = field(default_factory=dict)        # personnel device -> worker pseudonym
    station_zone: Dict[str, str] = field(default_factory=dict)      # stationary device -> zone
    worker_zone: Dict[str, str] = field(default_factory=dict)       # roster worker -> expected zone
    physio: List[dict] = field(default_factory=list)
    station: List[dict] = field(default_factory=list)
    events: List[dict] = field(default_factory=list)
    assets: dict = field(default_factory=dict)
    teams: dict = field(default_factory=dict)
    manifest: dict = field(default_factory=dict)
    quarantine: List[dict] = field(default_factory=list)
    rejected: List[dict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    duplicates_dropped: int = 0
    file_hashes: Dict[str, str] = field(default_factory=dict)
    as_of: Optional[datetime] = None

    # -- derived -----------------------------------------------------------
    @property
    def data_origin(self) -> str:
        o = self.manifest.get("data_origin")
        if o:
            return o
        origins = {r.get("data_origin") for r in self.physio[:50]} - {None}
        return origins.pop() if len(origins) == 1 else "unknown"

    @property
    def scenario_id(self) -> str:
        return (self.manifest.get("scenario_id") or
                (self.physio[0].get("scenario_id") if self.physio else None) or
                (self.events[0].get("scenario_id") if self.events else None) or "unknown")

    def time_bounds(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        start = parse_ts(self.manifest.get("start"))
        end = parse_ts(self.manifest.get("end"))
        ts = []
        for r in self.physio + self.station:
            t = parse_ts(r.get("received_at")) or parse_ts(r.get("measured_at"))
            if t:
                ts.append(t)
        for e in self.events:
            t = parse_ts(e.get("reported_at")) or parse_ts(e.get("observed_at"))
            if t:
                ts.append(t)
        if ts:
            start = start or min(ts)
            end = end or max(ts)
        return start, end

    def baseline_end(self) -> Optional[datetime]:
        b = parse_ts(self.manifest.get("baseline_end"))
        if b:
            return b
        # fallback: the first incident-relevant event, else 40% into the record
        # fallback: the first local incident-relevant observation (external alerts,
        # reports and status messages do not end the personal-reference period)
        local = {"impact_excursion", "possible_impact_local", "pressure_transient", "tilt_change", "loud_sound",
                 "gas_channel_alarm", "sos", "help_request"}
        evs = [parse_ts(e.get("observed_at")) for e in self.events if e.get("event_type") in local]
        evs = [t for t in evs if t]
        if evs:
            return min(evs)
        s, e = self.time_bounds()
        if s and e:
            return s + (e - s) * 0.4
        return None

    def snapshot(self, as_of: datetime) -> "Dataset":
        """Information available to the agent at `as_of` (arrival-time filter)."""
        def arrived(r, key_rcv, key_obs):
            t = parse_ts(r.get(key_rcv)) or parse_ts(r.get(key_obs))
            return t is not None and t <= as_of
        snap = Dataset(self.path, self.rosters, self.zones, self.device_map, self.station_zone,
                       self.worker_zone,
                       [r for r in self.physio if arrived(r, "received_at", "measured_at")],
                       [r for r in self.station if arrived(r, "received_at", "measured_at")],
                       [e for e in self.events if arrived(e, "reported_at", "observed_at")],
                       self.assets, self.teams, self.manifest, self.quarantine, self.rejected,
                       self.warnings, self.duplicates_dropped, self.file_hashes, as_of)
        return snap

    def digest(self) -> str:
        """SHA-256 over the canonical content of the (snapshot) inputs."""
        return sha256_obj({
            "rosters": self.rosters, "physio": [_ident(r) + (r.get("received_at"),) for r in self.physio],
            "physio_n": len(self.physio), "station_n": len(self.station),
            "station_last": [_ident(r) for r in self.station[-20:]],
            "events": [e.get("event_id") for e in self.events],
            "assets": self.assets, "teams": self.teams, "manifest": self.manifest,
        })

    def summary(self) -> dict:
        return {"path": self.path, "zones": len(self.zones), "workers": len(self.worker_zone),
                "stationary_nodes": len(self.station_zone), "physio_records": len(self.physio),
                "station_records": len(self.station), "events": len(self.events),
                "quarantined_identities": len({tuple(q["identity"]) for q in self.quarantine}),
                "rejected_lines": len(self.rejected), "duplicates_dropped": self.duplicates_dropped,
                "warnings": list(self.warnings), "data_origin": self.data_origin,
                "scenario_id": self.scenario_id}


def _ident(r: dict) -> tuple:
    return tuple(r.get(k) for k in IDENTITY_KEYS)


def _read_json(path: str, ds: Dataset, default):
    if not os.path.exists(path):
        ds.warnings.append(f"{os.path.basename(path)} missing")
        return default
    ds.file_hashes[os.path.basename(path)] = sha256_file(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        ds.warnings.append(f"{os.path.basename(path)} unreadable: {exc}")
        return default


def _read_jsonl(path: str, ds: Dataset) -> List[dict]:
    out: List[dict] = []
    name = os.path.basename(path)
    if not os.path.exists(path):
        alt = path[:-1] if path.endswith(".jsonl") else None  # tolerate .json arrays
        if alt and os.path.exists(alt):
            data = _read_json(alt, ds, [])
            return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
        ds.warnings.append(f"{name} missing")
        return out
    ds.file_hashes[name] = sha256_file(path)
    with open(path, "r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError as exc:
                ds.rejected.append({"file": name, "line": ln, "reason": f"invalid JSON: {exc}"})
                continue
            if not isinstance(obj, dict):
                ds.rejected.append({"file": name, "line": ln, "reason": "not an object"})
                continue
            obj["_line"] = ln
            out.append(obj)
    return out


def _dedupe(records: List[dict], key_fn, ds: Dataset, kind: str) -> List[dict]:
    """Idempotent redelivery; conflicting immutable payload quarantines the identity."""
    seen: Dict[Any, dict] = {}
    canon: Dict[Any, str] = {}
    conflicted = set()
    order = []
    for r in records:
        k = key_fn(r)
        if k is None or any(x is None for x in (k if isinstance(k, tuple) else (k,))):
            ds.rejected.append({"file": kind, "line": r.get("_line"), "reason": "missing identity"})
            continue
        body = {kk: v for kk, v in r.items() if kk not in ("_line", "received_at", "reported_at",
                                                           "ack_state", "gateway_id", "frame_hex")}
        c = canonical_json(body)
        if k in seen:
            if canon[k] == c:
                ds.duplicates_dropped += 1
                # keep earliest arrival time
                continue
            conflicted.add(k)
            ds.quarantine.append({"kind": kind, "identity": list(k) if isinstance(k, tuple) else [k],
                                  "line": r.get("_line"), "reason": "conflicting payload under same identity"})
            continue
        seen[k] = r
        canon[k] = c
        order.append(k)
    for k in conflicted:
        ds.quarantine.append({"kind": kind, "identity": list(k) if isinstance(k, tuple) else [k],
                              "line": seen[k].get("_line"), "reason": "original record of conflicted identity"})
    return [seen[k] for k in order if k not in conflicted]


def _normalise_physio(r: dict, ds: Dataset) -> dict:
    missing = [k for k in PHYSIO_REQUIRED if k not in r]
    reasons = list(r.get("_quality_reasons", []))
    if missing:
        reasons.append("missing keys: " + ",".join(missing))
    for k, (lo, hi) in PHYSIO_RANGES.items():
        v = r.get(k)
        if v is None:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v < lo or v > hi:
            reasons.append(f"{k} out of range -> null")
            r[k] = None
    for k in PHYSIO_REQUIRED:
        r.setdefault(k, None)
    if reasons:
        r["_quality_reasons"] = reasons
    return r


def _load_roster(raw: Any, ds: Dataset) -> None:
    if isinstance(raw, dict) and "rosters" in raw:
        rosters = raw["rosters"]
    elif isinstance(raw, dict) and "sites" in raw and "zones" not in raw:
        rosters = raw["sites"]          # P1 facility wrapper {"facility_id", "sites": [...]}
    elif isinstance(raw, list):
        rosters = raw
    elif isinstance(raw, dict) and raw:
        rosters = [raw]
    else:
        rosters = []
    if not rosters:
        ds.warnings.append("roster unavailable: coverage cannot be calculated, no group-normal conclusion")
    ds.rosters = rosters
    for ro in rosters:
        site = ro.get("site_id")
        for z in ro.get("zones", []) or []:
            zid = z.get("zone_id")
            if not zid:
                continue
            zz = dict(z)
            zz["site_id"] = z.get("site_id", site)
            ds.zones[zid] = zz
            for w in z.get("expected_workers", []) or []:
                if w in ds.worker_zone and ds.worker_zone[w] != zid:
                    ds.warnings.append(f"worker {w} expected in two zones; keeping first")
                    continue
                ds.worker_zone[w] = zid
            for s in z.get("stationary_nodes", []) or []:
                ds.station_zone[s] = zid
        for dev, w in (ro.get("device_map") or {}).items():
            if dev in ds.station_zone or w in ds.station_zone:
                ds.warnings.append(f"device_map entry {dev}->{w} refers to a stationary node; ignored")
                continue
            ds.device_map[dev] = w


def load_dataset(path: str) -> Dataset:
    ds = Dataset(path=path)
    if not os.path.isdir(path):
        raise FileNotFoundError(f"dataset directory not found: {path}")
    ds.manifest = _read_json(os.path.join(path, "manifest.json"), ds, {}) or {}
    _load_roster(_read_json(os.path.join(path, "roster.json"), ds, {}), ds)
    phys = _read_jsonl(os.path.join(path, "physio.jsonl"), ds)
    ds.physio = [_normalise_physio(r, ds) for r in _dedupe(phys, _ident, ds, "physio.jsonl")]
    st = _read_jsonl(os.path.join(path, "station.jsonl"), ds)
    ds.station = _dedupe(st, _ident, ds, "station.jsonl")
    ev = _read_jsonl(os.path.join(path, "events.jsonl"), ds)

    def ev_key(e):
        if e.get("event_id"):
            return e["event_id"]
        return (e.get("site_id"), e.get("device_id"), e.get("event_type"), e.get("observed_at"))
    events = _dedupe(ev, ev_key, ds, "events.jsonl")
    for e in events:
        sc = e.get("source_class")
        if sc not in SOURCE_CLASSES:
            ds.warnings.append(f"event {e.get('event_id')}: unknown source_class {sc!r} -> treated as unqualified")
            e["_unqualified_source"] = True
        if not e.get("zone_id") and e.get("device_id") in ds.station_zone:
            e["zone_id"] = ds.station_zone[e["device_id"]]
    assets = _read_json(os.path.join(path, "assets.json"), ds, {})
    ds.assets = assets if isinstance(assets, dict) else {}
    teams = _read_json(os.path.join(path, "teams.json"), ds, {})
    ds.teams = teams if isinstance(teams, dict) else {}
    _normalise_manifest(ds)
    ds.events = _normalise_events(events, ds)
    _normalise_assets(ds)
    _normalise_teams(ds)
    # map physio devices without explicit device_map entry via worker_pseudonym
    for r in ds.physio:
        dev = r.get("device_id")
        if dev in ds.station_zone:
            continue
        if dev not in ds.device_map and r.get("worker_pseudonym"):
            ds.device_map[dev] = r["worker_pseudonym"]
    ds.physio.sort(key=lambda r: (r.get("measured_at") or "", r.get("device_id") or ""))
    ds.station.sort(key=lambda r: (r.get("measured_at") or "", r.get("device_id") or ""))
    ds.events.sort(key=lambda e: (e.get("observed_at") or e.get("reported_at") or "", e.get("event_id") or ""))
    return ds


# ---------------------------------------------------------------------------
# Normalisation of P1 (`umsf-incident-dataset`) conventions
# ---------------------------------------------------------------------------

LEVELS = {"info": 0, "notice": 1, "warning": 2, "urgent": 3}


def _normalise_manifest(ds: Dataset) -> None:
    m = ds.manifest
    t0 = parse_ts(m.get("t0"))
    if t0 and not m.get("start"):
        m["start"] = m["t0"]
    if t0 and not m.get("end") and m.get("duration_s") is not None:
        from .util import fmt_ts
        from datetime import timedelta
        m["end"] = fmt_ts(t0 + timedelta(seconds=float(m["duration_s"])))


def _normalise_events(events: List[dict], ds: Dataset) -> List[dict]:
    """Map P1 event conventions onto the internal ones; keep originals for audit."""
    out: List[dict] = []
    for e in events:
        lv = e.get("level")
        if isinstance(lv, str):
            e["level_label"] = lv
            e["level"] = LEVELS.get(lv.lower())
        det = e.get("details") if isinstance(e.get("details"), dict) else None
        prov = e.get("provenance") if isinstance(e.get("provenance"), dict) else {}
        e["provenance"] = prov
        et = e.get("event_type")
        if et == "structural_assessment" and e.get("value") is None and det and det.get("status"):
            e["value"] = det["status"]
            prov.setdefault("scope", det.get("scope"))
        if et == "asset_status" and det:
            if det.get("resource_id") and "capacity_lower_bound" in det:
                # resource-level report: replaces the resource's guaranteed capacity
                prov.setdefault("capacity_lower_bounds", {det["resource_id"]: det.get("capacity_lower_bound")})
                prov.setdefault("asset_id", f"resource:{det['resource_id']}")
                prov["resource_level"] = True
                prov.setdefault("basis", det.get("note", ""))
            if det.get("service_id"):
                prov.setdefault("asset_id", f"service:{det['service_id']}")
                prov.setdefault("service_id", det["service_id"])
                if e.get("value") in (None, 0, 1, 0.0, 1.0):
                    e["value"] = det.get("status", e.get("value"))
        if et == "personnel_accounting" and det and not prov.get("worker"):
            out.extend(_expand_accounting(e, det, ds))
            continue
        out.append(e)
    return out


def _expand_accounting(e: dict, det: dict, ds: Dataset) -> List[dict]:
    """Aggregated roll call / reconciliation -> one per-worker record (same provenance)."""
    rows = []
    last = det.get("last_confirmed") or {}
    groups = [("accounted", "accounted"), ("responder_confirmed_assistance", "assisted"),
              ("unaccounted", "whereabouts_unresolved"), ("assistance_requested", "assistance_requested")]
    for key, value in groups:
        for w in det.get(key, []) or []:
            r = dict(e)
            r["event_id"] = f"{e.get('event_id')}#{w}"
            r["value"] = value
            r["provenance"] = dict(e.get("provenance") or {})
            r["provenance"]["worker"] = w
            r["provenance"]["aggregated_from"] = e.get("event_id")
            if key == "responder_confirmed_assistance":
                r["provenance"]["responder_confirmed"] = True
            lc = last.get(w) or {}
            if lc.get("zone_id"):
                r["provenance"]["location_zone"] = lc["zone_id"]
                r["provenance"]["location_at"] = lc.get("at")
            r["zone_id"] = e.get("zone_id") or lc.get("zone_id") or ds.worker_zone.get(w)
            rows.append(r)
    if not rows:
        rows.append(e)
    return rows


def _normalise_assets(ds: Dataset) -> None:
    a = ds.assets
    if not a:
        return
    if "planning_horizon_h" not in a and a.get("planning_interval_min"):
        a["planning_horizon_h"] = float(a["planning_interval_min"]) / 60.0
    for r in a.get("resources", []) or []:
        if "lower_bound" not in r and "contributions" not in r and "capacity_lower_bound" in r:
            r["lower_bound"] = r["capacity_lower_bound"]   # never the pre-event rating
        if r.get("basis") is None and r.get("source"):
            r["basis"] = r["source"]
    for s in a.get("services", []) or []:
        if "priority_weight" not in s and "weight" in s:
            s["priority_weight"] = s["weight"]
        if "requires" not in s and "prerequisites" in s:
            s["requires"] = s["prerequisites"]
        if "demand" not in s and s.get("demand_units") is not None and len(a.get("resources", []) or []) == 1:
            s["demand"] = {a["resources"][0]["resource_id"]: s["demand_units"]}


def _normalise_teams(ds: Dataset) -> None:
    t0 = parse_ts(ds.manifest.get("t0") or ds.manifest.get("start"))
    for tm in ds.teams.get("teams", []) or []:
        if tm.get("available_from_min") is not None and t0 and not tm.get("available_from"):
            from .util import fmt_ts
            from datetime import timedelta
            tm["available_from"] = fmt_ts(t0 + timedelta(minutes=float(tm["available_from_min"])))
            if tm.get("available") is False:
                tm["available"] = None     # unavailable only until available_from
