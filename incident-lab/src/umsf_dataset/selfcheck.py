"""The ten functional self-checks of the offline collector (Study B, Table 12).

They cover parsing, rejection classes, null preservation, deduplication, conflict quarantine,
export exclusion, time cutoffs, roster denominators, orderly SQLite reopening and UTC/Kyiv
display. The reopen check is an ORDERLY close/reopen; it is not a crash or power-loss test.
"""

from __future__ import annotations

import glob
import json
import os

from .store import Store
from .summaries import roster_personnel_devices
from .timeutil import to_epoch, to_kyiv


def _check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def study_b_selfchecks(store: Store, db_path: str, gen: dict, summaries: list, export_dir: str) -> dict:
    from .synth.study_b import INVALID_KINDS, rosters

    truth = gen["truth"]
    checks = []
    st = store.stats()
    # 1 parsing
    checks.append(_check("parsing", st["lines"] == truth["input_lines"] and
                         store.count("physio") == truth["base_records"],
                         f"lines={st['lines']} stored_identities={store.count('physio')}"))
    # 2 rejection classes
    reasons = " | ".join(r["reason"] for r in store.rejects())
    needles = {"measured_origin": "'measured' rejected", "unknown_field": "unknown field",
               "invalid_range": "above maximum", "invalid_type": "invalid type", "nan_value": "non-finite",
               "malformed_json": "malformed JSON"}
    missing = [k for k in INVALID_KINDS if needles[k] not in reasons]
    checks.append(_check("rejection_classes", st["rejected"] == truth["invalid"] and not missing,
                         f"rejected={st['rejected']} missing_classes={missing}"))
    # 3 null preservation
    recs = store.records("physio", include_quarantined=True)
    nullq = sum(1 for r in recs if r["quality"] is None)
    zeros = sum(1 for r in recs if r["quality"] == 0)
    checks.append(_check("null_preservation", nullq == truth["null_quality"] and zeros == 0,
                         f"null_quality={nullq} zero_quality={zeros}"))
    # 4 deduplication
    checks.append(_check("deduplication", st["duplicates"] == truth["duplicates"] and
                         st["unique_identities"] == truth["base_records"],
                         f"duplicates={st['duplicates']} unique={st['unique_identities']}"))
    # 5 conflict quarantine (retained for audit)
    audit = store.quarantine_log()
    checks.append(_check("conflict_quarantine", st["conflicts"] == truth["conflicts"] and
                         st["quarantined_identities"] == 1 and len(audit) == 1,
                         f"conflicts={st['conflicts']} audit_rows={len(audit)}"))
    # 6 export excludes the whole conflicted identity
    exported = []
    for p in sorted(glob.glob(os.path.join(export_dir, "physio_*.jsonl"))):
        with open(p, encoding="utf-8") as fh:
            exported += [json.loads(x) for x in fh]
    conflict_ids = {tuple(c) for c in truth["conflict_identities"]}
    leaked = [r for r in exported if (r["site_id"], r["device_id"], r["boot_id"], r["sequence"]) in conflict_ids]
    checks.append(_check("export_excludes_conflict",
                         len(exported) == truth["base_records"] - truth["conflicts"] and not leaked,
                         f"exported={len(exported)} leaked={len(leaked)}"))
    # 7 time cutoffs: delayed first arrivals after the window cutoff enter history, not the window
    delayed = {tuple(d) for d in truth["delayed_identities"]}
    by_id = {(r["site_id"], r["device_id"], r["boot_id"], r["sequence"]): r for r in recs}
    late_expected = 0
    for ident in delayed:
        r = by_id[ident]
        m = to_epoch(r["measured_at"])
        if to_epoch(r["received_at"]) > (m // 300) * 300 + 300:
            late_expected += 1
    late_seen = sum(s["late_after_cutoff"] for s in summaries)
    in_history = all(i in by_id for i in delayed)
    admitted = sum(s["received_records"] for s in summaries)
    checks.append(_check("time_cutoffs", late_seen == late_expected and in_history and
                         admitted == len(exported) - late_seen and late_expected > 0,
                         f"late_after_cutoff={late_seen} expected={late_expected} admitted={admitted}"))
    # 8 roster denominators (stationary nodes never counted as workers)
    ros = rosters()
    devs_ok = all(len(roster_personnel_devices(r)) == 6 for r in ros.values())
    den_ok = all(s["expected_records"] == 180 and s["fresh_expected"] == 36 and s["roster_devices"] == 6
                 for s in summaries)
    checks.append(_check("roster_denominators", devs_ok and den_ok and len(summaries) == 12,
                         f"summaries={len(summaries)} expected=180 fresh=36 roster_devices=6"))
    # 9 orderly SQLite close and reopen (NOT a power-loss test)
    before = store.stats()
    store.close()
    store = Store(db_path, clock=store.clock)
    after = store.stats()
    pr = store.pragmas()
    checks.append(_check("sqlite_orderly_reopen", before == after and pr["journal_mode"] == "wal" and
                         pr["synchronous"] == "FULL" and pr["integrity_check"] == "ok",
                         f"pragmas={pr}; orderly close/reopen only, not a power-loss test"))
    # 10 UTC storage / Europe/Kyiv display
    utc_ok = all(r["measured_at"].endswith("Z") and r["received_at"].endswith("Z") for r in recs)
    kyiv = to_kyiv("2026-09-08T06:00:00Z")
    checks.append(_check("utc_storage_kyiv_display", utc_ok and kyiv == "2026-09-08T09:00:00+03:00" and
                         summaries[0]["window_start_local"].endswith("+03:00"),
                         f"06:00Z -> {kyiv}"))
    return {"checks": checks, "_store": store}
