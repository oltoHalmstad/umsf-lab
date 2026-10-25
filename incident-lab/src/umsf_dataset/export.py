"""Exports: daily CSV + JSONL, five-minute summaries, quarantine log, SHA-256 manifest."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Iterable, Optional

from . import SCHEMA_EVENT, SCHEMA_PHYSIO, SCHEMA_STATION, __version__
from .summaries import FRESHNESS_S, GOOD_QUALITY, INTERVAL_S, WINDOW_S
from .store import _identity
from .timeutil import fmt_iso

PHYSIO_COLUMNS = ["schema_version", "data_origin", "scenario_id", "site_id", "device_id", "boot_id", "sequence",
                  "measured_at", "received_at", "hr_bpm", "spo2_pct", "skin_temp_c", "motion_rms_g", "quality",
                  "battery_pct", "gateway_id", "zone_id", "worker_pseudonym", "ppg_ir", "channel_flags",
                  "artifact_flags", "hr_synthetic", "fw_build", "time_uncertainty_s"]
STATION_COLUMNS = ["schema_version", "data_origin", "scenario_id", "site_id", "zone_id", "device_id", "boot_id",
                   "sequence", "measured_at", "received_at", "vib_peak_g", "accel_rms_g", "tilt_deg",
                   "tilt_delta_deg", "pressure_hpa", "pressure_delta_pa", "temp_c", "gas_v", "sound_index",
                   "pir_presence", "sos", "attachment_verified", "quality", "battery_pct", "gateway_id", "flags",
                   "sensor_flags", "fw_build"]
EVENT_COLUMNS = ["schema_version", "data_origin", "scenario_id", "site_id", "zone_id", "event_id", "source_class",
                 "device_id", "event_type", "level", "value", "unit", "observed_at", "reported_at",
                 "time_uncertainty_s", "rule_version", "quality", "ack_state", "provenance"]
SUMMARY_COLUMNS = ["site_id", "window_start", "window_end", "window_start_local", "cutoff", "complete_window",
                   "roster_devices", "expected_records", "received_records", "sample_completeness",
                   "devices_reporting", "device_coverage", "quality_good", "quality_poor", "quality_null",
                   "fresh_expected", "fresh_received", "fresh_good", "fresh_devices_good", "late_after_cutoff",
                   "unrostered_records"]
TIMING_RULES = {
    "feature_interval_s": INTERVAL_S, "summary_window_s": WINDOW_S, "freshness_horizon_s": FRESHNESS_S,
    "window_alignment": "UTC epoch multiples of the window length",
    "cutoff": "window_end (+grace 0 s) unless a fixed report cutoff is given; only arrivals with "
              "received_at <= cutoff are admitted; later first arrivals enter history only",
    "good_quality_threshold": GOOD_QUALITY, "storage_timezone": "UTC", "display_timezone": "Europe/Kyiv",
    "daily_partition": "UTC date of measured_at (observed_at for events)",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sizing(nodes: int = 12, record_bytes: int = 1500, interval_s: int = 10, hours: float = 8.0) -> dict:
    """Storage allowance (Sec. 3.3.8): 1.5 kB/record, 12 nodes -> ~1.8 kB/s, 51.84 MB per 8 h."""
    per_s = nodes * record_bytes / interval_s
    total = per_s * hours * 3600
    return {"nodes": nodes, "record_bytes": record_bytes, "interval_s": interval_s, "hours": hours,
            "records": int(nodes * hours * 3600 / interval_s), "bytes_per_s": per_s, "bytes_total": total,
            "MB_total": round(total / 1e6, 2), "note": "sizing calculation, not a network benchmark"}


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return v


def write_csv(path: str, rows: Iterable[dict], columns: list[str]):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(columns)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in columns])


def write_jsonl(path: str, rows: Iterable[dict]):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")


def export_all(store, outdir: str, *, summaries: Optional[list] = None, sources: Iterable[str] = (),
               generated_at: Optional[str] = None, extra: Optional[dict] = None) -> dict:
    """Write analytical exports (accepted, nonconflicting records only) plus audit logs and manifest."""
    os.makedirs(outdir, exist_ok=True)
    written = []

    def rel(p):
        return os.path.relpath(p, outdir).replace(os.sep, "/")

    for kind, cols, tkey in (("physio", PHYSIO_COLUMNS, "measured_at"), ("station", STATION_COLUMNS, "measured_at"),
                             ("event", EVENT_COLUMNS, "observed_at")):
        recs = store.records(kind)
        if not recs:
            continue
        days = defaultdict(list)
        for r in recs:
            days[(r.get(tkey) or r.get("reported_at"))[:10]].append(r)
        for day, rows in sorted(days.items()):
            base = os.path.join(outdir, f"{kind}_{day}")
            write_csv(base + ".csv", rows, cols)
            write_jsonl(base + ".jsonl", rows)
            written += [(base + ".csv", len(rows)), (base + ".jsonl", len(rows))]
    if summaries is not None:
        p = os.path.join(outdir, "summaries_5min.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(summaries, fh, indent=1, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
        flat = [{**s, **{f"valid_{k}": v for k, v in s["channel_valid_counts"].items()}} for s in summaries]
        cols = SUMMARY_COLUMNS + [f"valid_{k}" for k in (summaries[0]["channel_valid_counts"] if summaries else {})]
        write_csv(os.path.join(outdir, "summaries_5min.csv"), flat, cols)
        written += [(p, len(summaries)), (os.path.join(outdir, "summaries_5min.csv"), len(summaries))]
    qpath = os.path.join(outdir, "quarantine_log.jsonl")
    qrows = [{"kind": q["kind"], "original": q["record"]} for q in store.quarantined_identities()]
    audit = store.quarantine_log()
    write_jsonl(qpath, [{"quarantined_identity": q, "conflicts": [
        {k: (json.loads(a[k]) if k == "conflicting_json" else a[k]) for k in a}
        for a in audit if a["kind"] == q["kind"] and a["identity"] == "|".join(map(str, _identity(q["kind"], q["original"])))]}
        for q in qrows])
    rpath = os.path.join(outdir, "rejects_log.jsonl")
    write_jsonl(rpath, store.rejects())
    written += [(qpath, len(qrows)), (rpath, len(store.rejects()))]

    manifest = {
        "package": "umsf-incident-dataset", "package_version": __version__,
        "schema_versions": {"physio": SCHEMA_PHYSIO, "station": SCHEMA_STATION, "event": SCHEMA_EVENT},
        "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
        "generated_at": generated_at or fmt_iso(datetime.now(timezone.utc).replace(microsecond=0)),
        "sources": [{"path": os.path.basename(s), "sha256": sha256_file(s), "bytes": os.path.getsize(s)}
                    for s in sources],
        "exports": [{"path": rel(p), "sha256": sha256_file(p), "bytes": os.path.getsize(p), "records": n}
                    for p, n in written],
        "counters": store.stats(), "sqlite_pragmas": store.pragmas(), "timing_rules": TIMING_RULES,
        "sizing": sizing(),
        "notes": ["Analytical exports contain only accepted, nonconflicting records; conflicted identities are "
                  "excluded entirely and retained in quarantine_log.jsonl for audit.",
                  "The source JSONL may be a challenge stream with invalid lines; see rejects_log.jsonl.",
                  "Orderly SQLite close/reopen is tested; abrupt power loss is not."],
    }
    if extra:
        manifest.update(extra)
    with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return manifest
