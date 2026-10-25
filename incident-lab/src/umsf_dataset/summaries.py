"""Roster-based summaries with explicit denominators and arrival cutoffs (manuscript Sec. 3.3.8).

* Expected records come from the roster, not from devices that happened to report:
  ``expected = roster_devices * window_s / interval_s`` (6 devices -> 180 per 5-min window;
  final 60 s freshness horizon -> 36).
* Device coverage, sample completeness and channel-specific valid counts are separate.
* Only arrivals available by the cutoff are admitted; delayed first arrivals enter history
  (a later re-summary) but are never counted as current evidence.
* Stationary nodes are never counted as workers. Link loss turns current state into ``unknown``.
* UTC is stored; Europe/Kyiv is used for display only.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable, Optional

from .timeutil import from_epoch, to_epoch, to_kyiv

WINDOW_S = 300
INTERVAL_S = 10
FRESHNESS_S = 60
GOOD_QUALITY = 0.6
STATION_STALE_S = 60.0
COMPACT_STALE_S = 2.0
CHANNELS = ("hr_bpm", "spo2_pct", "skin_temp_c", "motion_rms_g", "quality", "battery_pct")


def roster_personnel_devices(roster: dict) -> set[str]:
    """Personnel devices expected by the roster (device_map entries pointing to rostered workers)."""
    workers = {w for z in roster["zones"] for w in z["expected_workers"]}
    nodes = {n for z in roster["zones"] for n in z["stationary_nodes"]}
    return {d for d, w in roster["device_map"].items() if w in workers and d not in nodes}


def roster_zone_of_device(roster: dict) -> dict:
    out = {}
    for z in roster["zones"]:
        for w in z["expected_workers"]:
            for d, ww in roster["device_map"].items():
                if ww == w:
                    out[d] = z["zone_id"]
        for n in z["stationary_nodes"]:
            out[n] = z["zone_id"]
    return out


def _is_good(q) -> bool:
    return q is not None and q >= GOOD_QUALITY


def physio_window_summaries(records: Iterable[dict], rosters: dict, *, window_s: int = WINDOW_S,
                            interval_s: int = INTERVAL_S, freshness_s: int = FRESHNESS_S,
                            cutoff_at: Optional[str] = None, grace_s: float = 0.0) -> list[dict]:
    """Five-minute site summaries.

    ``records`` must already exclude quarantined identities (``Store.records``). ``rosters`` maps
    site_id -> roster. Each window's cutoff is ``window_end + grace_s`` unless ``cutoff_at`` (a
    fixed report time for a partial report) is given; the cutoff is always reported.
    """
    by_site = defaultdict(list)
    for r in records:
        by_site[r["site_id"]].append(r)
    fixed_cutoff = to_epoch(cutoff_at) if cutoff_at else None
    out = []
    for site_id in sorted(by_site):
        if site_id not in rosters:
            continue
        devices = roster_personnel_devices(rosters[site_id])
        recs = [(to_epoch(r["measured_at"]), to_epoch(r["received_at"]), r) for r in by_site[site_id]]
        windows = sorted({math.floor(m / window_s) * window_s for m, _, _ in recs})
        for ws in windows:
            we = ws + window_s
            cutoff = fixed_cutoff if fixed_cutoff is not None else we + grace_s
            in_win = [(m, rc, r) for m, rc, r in recs if ws <= m < we]
            admitted = [(m, rc, r) for m, rc, r in in_win if rc <= cutoff and r["device_id"] in devices]
            late = [1 for m, rc, r in in_win if rc > cutoff and r["device_id"] in devices]
            unrostered = sum(1 for _m, _rc, r in in_win if r["device_id"] not in devices)
            fresh = [(m, rc, r) for m, rc, r in admitted if m >= min(we, cutoff) - freshness_s]
            n_dev = len(devices)
            expected = n_dev * window_s // interval_s
            fresh_expected = n_dev * freshness_s // interval_s
            quality_good = sum(1 for *_x, r in admitted if _is_good(r.get("quality")))
            quality_null = sum(1 for *_x, r in admitted if r.get("quality") is None)
            out.append({
                "site_id": site_id,
                "window_start": from_epoch(ws), "window_end": from_epoch(we),
                "window_start_local": to_kyiv(from_epoch(ws)), "display_tz": "Europe/Kyiv",
                "cutoff": from_epoch(cutoff), "complete_window": cutoff >= we,
                "roster_devices": n_dev,
                "expected_records": expected,
                "received_records": len(admitted),
                "sample_completeness": round(len(admitted) / expected, 4) if expected else None,
                "devices_reporting": len({r["device_id"] for *_x, r in admitted}),
                "device_coverage": round(len({r["device_id"] for *_x, r in admitted}) / n_dev, 4) if n_dev else None,
                "channel_valid_counts": {c: sum(1 for *_x, r in admitted if r.get(c) is not None) for c in CHANNELS},
                "quality_good": quality_good,
                "quality_poor": len(admitted) - quality_good - quality_null,
                "quality_null": quality_null,
                "fresh_horizon_s": freshness_s,
                "fresh_expected": fresh_expected,
                "fresh_received": len(fresh),
                "fresh_good": sum(1 for *_x, r in fresh if _is_good(r.get("quality"))),
                "fresh_devices_good": len({r["device_id"] for *_x, r in fresh if _is_good(r.get("quality"))}),
                "late_after_cutoff": len(late),
                "unrostered_records": unrostered,
            })
    return out


def physio_current_state(records: Iterable[dict], roster: dict, at: str,
                         freshness_s: int = FRESHNESS_S) -> dict:
    """Per-device current state at ``at``: fresh / stale / missing (never 'normal')."""
    t = to_epoch(at)
    devices = roster_personnel_devices(roster)
    last = {}
    for r in records:
        if r["site_id"] != roster["site_id"] or r["device_id"] not in devices:
            continue
        m, rc = to_epoch(r["measured_at"]), to_epoch(r["received_at"])
        if rc <= t and m <= t and (r["device_id"] not in last or m > last[r["device_id"]][0]):
            last[r["device_id"]] = (m, r)
    states = {}
    for d in sorted(devices):
        if d not in last:
            states[d] = {"status": "missing", "age_s": None, "last_measured_at": None}
        else:
            age = round(t - last[d][0], 3)
            states[d] = {"status": "fresh" if age <= freshness_s else "stale", "age_s": age,
                         "last_measured_at": last[d][1]["measured_at"], "quality": last[d][1].get("quality")}
    fresh = sum(1 for s in states.values() if s["status"] == "fresh")
    return {"site_id": roster["site_id"], "at": at, "at_local": to_kyiv(at), "roster_devices": len(devices),
            "fresh_devices": fresh, "device_coverage": round(fresh / len(devices), 4) if devices else None,
            "devices": states}


def station_zone_state(station_records: Iterable[dict], events: Iterable[dict], roster: dict, at: str, *,
                       stale_s: float = STATION_STALE_S, compact: bool = False) -> dict:
    """Zone state from stationary nodes: last values, age, staleness, link loss -> ``unknown``.

    Staleness is 60 s for 1 s records and 2 s for 20-byte COMPACT packets (``compact=True``).
    Local composites stay ``possible_impact_local`` (unverified); strikes only appear when an
    ``authoritative_external_alert`` reported them.
    """
    t = to_epoch(at)
    stale_s = COMPACT_STALE_S if compact else stale_s
    last = {}
    for r in station_records:
        if r["site_id"] != roster["site_id"]:
            continue
        m, rc = to_epoch(r["measured_at"]), to_epoch(r["received_at"])
        if rc <= t and m <= t and (r["device_id"] not in last or m > last[r["device_id"]][0]):
            last[r["device_id"]] = (m, r)
    link_down, evs = {}, []
    for e in sorted(events, key=lambda e: e["reported_at"]):
        if to_epoch(e["reported_at"]) > t or e["site_id"] != roster["site_id"]:
            continue
        evs.append(e)
        if e["event_type"] == "link_loss":
            link_down[e["device_id"]] = True
        elif e["event_type"] == "link_restored":
            link_down[e["device_id"]] = False
    zones = {}
    for z in roster["zones"]:
        nodes = {}
        for n in z["stationary_nodes"]:
            if n not in last:
                status, age, vals = "unknown", None, None
            else:
                age = round(t - last[n][0], 3)
                status = "current" if age <= stale_s else "stale"
                vals = {k: last[n][1].get(k) for k in ("vib_peak_g", "tilt_deg", "tilt_delta_deg", "pressure_hpa",
                                                      "temp_c", "gas_v", "sound_index", "pir_presence", "sos")}
            if link_down.get(n):
                status = "unknown"  # never 'collapse' or 'casualty'
            nodes[n] = {"status": status, "age_s": age, "last_values": vals,
                        "last_measured_at": last[n][1]["measured_at"] if n in last else None,
                        "attachment_verified": last[n][1].get("attachment_verified") if n in last else None}
        zev = [e for e in evs if e.get("zone_id") == z["zone_id"]]
        zones[z["zone_id"]] = {
            "name": z["name"], "nodes": nodes,
            "observation_gap": any(v["status"] != "current" for v in nodes.values()) or not nodes,
            "sos_active": _active(zev, ("sos", "help_request"), ("sos_reset",)),
            "possible_impact_local_unverified": any(e["event_type"] == "possible_impact_local" for e in zev),
            "gas_channel_alarm_uncalibrated": any(e["event_type"] == "gas_channel_alarm" for e in zev),
            "presence_cue_last": max((e["observed_at"] for e in zev if e["event_type"] == "presence" and e["value"]),
                                     default=None),
            "structural_state": _latest(zev, "structural_assessment") or "unknown",
        }
    ext = [e for e in evs if e["source_class"] == "authoritative_external_alert"]
    return {"site_id": roster["site_id"], "at": at, "at_local": to_kyiv(at), "stale_after_s": stale_s,
            "zones": zones,
            "external_alerts": [{"event_type": e["event_type"], "observed_at": e["observed_at"],
                                 "provenance": e["provenance"]} for e in ext]}


def _active(evs, on, off) -> bool:
    state = {}
    for e in evs:
        if e["event_type"] in on:
            state[e["device_id"]] = True
        elif e["event_type"] in off:
            state = {k: False for k in state} if e["source_class"] in ("operator_report",) else \
                {**state, e["device_id"]: False}
    return any(state.values())


def _latest(evs, etype):
    cands = [e for e in evs if e["event_type"] == etype]
    if not cands:
        return None
    e = cands[-1]
    return {"value": e["value"], "details": e.get("details"), "provenance": e["provenance"]}
