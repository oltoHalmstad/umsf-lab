"""Study B: deterministic offline-collector challenge stream (manuscript Sec. 4.5, Table 12).

Seed 82026; 12 virtual sources (2 sites x 6), one record per 10 s for 30 min = 2,160 base
records; 6 exact duplicates, 1 conflicting duplicate and 6 invalid lines -> 2,173 input lines.
The base stream contains 58 poor-quality records, 22 records without quality and 31 records
delayed by 180 s (categories may overlap). All payloads are labelled ``synthetic``.
"""

from __future__ import annotations

import json
import os
import random

from .. import SCHEMA_PHYSIO
from ..timeutil import from_epoch, to_epoch

SEED = 82026
SITES = ("SITE-A", "SITE-B")
DEVICES_PER_SITE = 6
INTERVAL_S = 10
DURATION_S = 30 * 60
START = "2026-09-08T06:00:00Z"  # 09:00 Europe/Kyiv; aligned to 5-minute windows
N_DUPLICATES, N_CONFLICTS, N_POOR, N_NULLQ, N_DELAYED = 6, 1, 58, 22, 31
DELAY_S = 180
SCENARIO_ID = "study-b-82026"
INVALID_KINDS = ("measured_origin", "unknown_field", "invalid_range", "invalid_type", "nan_value", "malformed_json")


def device_ids(site: str) -> list[str]:
    return [f"{site[-1]}{i:02d}" for i in range(1, DEVICES_PER_SITE + 1)]


def rosters() -> dict:
    out = {}
    for site in SITES:
        devs = device_ids(site)
        out[site] = {"site_id": site,
                     "zones": [{"zone_id": f"{site}-Z1", "name": "Synthetic zone 1",
                                "expected_workers": [f"W{d}" for d in devs],
                                "stationary_nodes": [f"S{site[-1]}1"]}],
                     "device_map": {d: f"W{d}" for d in devs},
                     "valid_from": "2026-09-08T00:00:00Z", "valid_to": "2026-09-09T00:00:00Z"}
    return out


def _dump(rec: dict) -> str:
    return json.dumps(rec, separators=(",", ":"))


def generate(seed: int = SEED) -> dict:
    """Return ``{"lines": [...], "base": [...], "truth": {...}}`` deterministically."""
    rng = random.Random(seed)
    t0 = to_epoch(START)
    n_per = DURATION_S // INTERVAL_S
    base = []
    for site in SITES:
        for dev in device_ids(site):
            hr0, t_skin, batt = rng.uniform(64, 80), rng.uniform(32.5, 34.0), rng.uniform(88, 99)
            for k in range(n_per):
                m = t0 + k * INTERVAL_S
                base.append({
                    "schema_version": SCHEMA_PHYSIO, "data_origin": "synthetic", "scenario_id": SCENARIO_ID,
                    "site_id": site, "device_id": dev, "boot_id": 1, "sequence": k + 1,
                    "measured_at": from_epoch(m), "received_at": from_epoch(m + rng.uniform(0.2, 1.5)),
                    "hr_bpm": round(hr0 + rng.gauss(0, 3), 1),
                    "spo2_pct": round(min(100.0, 97.2 + rng.gauss(0, 0.6)), 1),
                    "skin_temp_c": round(t_skin + rng.gauss(0, 0.15), 2),
                    "motion_rms_g": round(abs(rng.gauss(0.05, 0.03)), 3),
                    "quality": round(rng.uniform(0.75, 1.0), 2),
                    "battery_pct": round(batt - 3.0 * k / n_per, 1)})
    idx = list(range(len(base)))
    poor = rng.sample(idx, N_POOR)
    nullq = rng.sample(sorted(set(idx) - set(poor)), N_NULLQ)
    delayed = rng.sample(idx, N_DELAYED)
    for i in poor:
        base[i]["quality"] = round(rng.uniform(0.2, 0.55), 2)
    for i in nullq:
        base[i]["quality"] = None
    for i in delayed:
        base[i]["received_at"] = from_epoch(to_epoch(base[i]["measured_at"]) + DELAY_S + rng.uniform(0.2, 1.5))

    # Arrival order = received_at order (stable).
    stream = [(to_epoch(r["received_at"]), _dump(r), "base") for r in base]
    special = rng.sample(sorted(set(idx) - set(delayed)), N_DUPLICATES + N_CONFLICTS)
    dup_idx, conflict_idx = special[:N_DUPLICATES], special[N_DUPLICATES:]
    for i in dup_idx:  # exact redelivery 30 s later
        stream.append((to_epoch(base[i]["received_at"]) + 30, _dump(base[i]), "duplicate"))
    for i in conflict_idx:  # same identity, changed immutable payload
        c = dict(base[i])
        c["hr_bpm"] = round(c["hr_bpm"] + 9.0, 1)
        stream.append((to_epoch(base[i]["received_at"]) + 45, _dump(c), "conflict"))
    tmpl = dict(base[0])
    invalid = []
    for j, kind in enumerate(INVALID_KINDS):
        r = dict(tmpl, device_id="A01", sequence=900 + j, measured_at=from_epoch(t0 + 600 + j),
                 received_at=from_epoch(t0 + 601 + j))
        if kind == "measured_origin":
            line = _dump(dict(r, data_origin="measured"))
        elif kind == "unknown_field":
            line = _dump(dict(r, operator_note="free text"))
        elif kind == "invalid_range":
            line = _dump(dict(r, hr_bpm=412.0))
        elif kind == "invalid_type":
            line = _dump(dict(r, sequence="nine hundred"))
        elif kind == "nan_value":
            line = _dump(dict(r, skin_temp_c=0.0)).replace('"skin_temp_c":0.0', '"skin_temp_c":NaN')
        else:
            line = _dump(r)[:-27]
        invalid.append((t0 + rng.uniform(30, DURATION_S - 30), line, "invalid:" + kind))
    stream += invalid
    stream.sort(key=lambda x: x[0])
    truth = {
        "seed": seed, "base_records": len(base), "input_lines": len(stream), "duplicates": N_DUPLICATES,
        "conflicts": N_CONFLICTS, "invalid": len(INVALID_KINDS), "poor_quality": N_POOR, "null_quality": N_NULLQ,
        "delayed": N_DELAYED, "delay_s": DELAY_S,
        "conflict_identities": [[base[i]["site_id"], base[i]["device_id"], 1, base[i]["sequence"]]
                                for i in conflict_idx],
        "delayed_identities": [[base[i]["site_id"], base[i]["device_id"], 1, base[i]["sequence"]] for i in delayed],
    }
    return {"lines": [s[1] for s in stream], "labels": [s[2] for s in stream], "base": base, "truth": truth}


def write(outdir: str, seed: int = SEED) -> dict:
    os.makedirs(outdir, exist_ok=True)
    g = generate(seed)
    with open(os.path.join(outdir, "study_b_input.jsonl"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(g["lines"]) + "\n")
    with open(os.path.join(outdir, "study_b_truth.json"), "w", encoding="utf-8") as fh:
        json.dump(g["truth"], fh, indent=1)
        fh.write("\n")
    with open(os.path.join(outdir, "rosters.json"), "w", encoding="utf-8") as fh:
        json.dump(rosters(), fh, indent=1)
        fh.write("\n")
    return g


def run(workdir: str, seed: int = SEED, generated_at: str = "2026-09-08T06:45:00Z") -> dict:
    """Generate, ingest, summarise, export and self-check Study B. Returns a result dict."""
    from ..export import export_all
    from ..selfcheck import study_b_selfchecks
    from ..store import Store
    from ..summaries import physio_window_summaries

    os.makedirs(workdir, exist_ok=True)
    g = write(workdir, seed)
    db = os.path.join(workdir, "study_b.sqlite")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db + suffix):
            os.remove(db + suffix)
    store = Store(db, clock=lambda: generated_at)
    src = os.path.join(workdir, "study_b_input.jsonl")
    with open(src, encoding="utf-8") as fh:
        ingest = store.ingest_jsonl(fh, source="study_b_input.jsonl")
    summaries = physio_window_summaries(store.records("physio"), rosters())
    manifest = export_all(store, os.path.join(workdir, "exports"), summaries=summaries, sources=[src],
                          generated_at=generated_at,
                          extra={"study": "B", "seed": seed, "ingest_result": ingest})
    checks = study_b_selfchecks(store, db, g, summaries, os.path.join(workdir, "exports"))
    store = checks.pop("_store")
    stats = store.stats()
    store.close()
    full = [s for s in summaries if s["complete_window"]]
    result = {
        "input_lines": ingest["lines"], "unique_identities": stats["unique_identities"],
        "duplicates": stats["duplicates"], "conflicts": stats["conflicts"], "rejected": stats["rejected"],
        "exported": stats["exportable_physio"], "summaries": len(summaries),
        "windows_per_site": {s: sum(1 for x in summaries if x["site_id"] == s) for s in SITES},
        "expected_per_window": sorted({s["expected_records"] for s in summaries}),
        "fresh_expected": sorted({s["fresh_expected"] for s in summaries}),
        "fresh_good_range": [min(s["fresh_good"] for s in full), max(s["fresh_good"] for s in full)],
        "min_fresh_devices_good": min(s["fresh_devices_good"] for s in full),
        "selfchecks_passed": sum(1 for c in checks["checks"] if c["passed"]),
        "selfchecks_failed": sum(1 for c in checks["checks"] if not c["passed"]),
        "checks": checks["checks"], "manifest_exports": len(manifest["exports"]),
    }
    with open(os.path.join(workdir, "study_b_result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
        fh.write("\n")
    return result
