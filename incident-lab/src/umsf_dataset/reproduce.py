"""Reproduce the paper's documented software results and compare with the published numbers."""

from __future__ import annotations

import os
import tempfile

from . import frames
from .export import sizing
from .synth import bench, incident, study_a, study_b


def _row(group, item, paper, got, skip=False):
    return {"group": group, "item": item, "paper": paper, "reproduced": got,
            "status": "SKIP" if skip else ("OK" if paper == got else "MISMATCH")}


def run(workdir: str | None = None, protection: bool = True) -> dict:
    rows = []
    workdir = workdir or tempfile.mkdtemp(prefix="umsf-reproduce-")
    # ---------------- Study A (Table 11)
    a = study_a.run(os.path.join(workdir, "study_a"), protection=protection)
    t = "Study A / Table 11"
    rows += [_row(t, "records (baseline + evaluation)", "40320 (11520 + 28800)",
                  f"{a['records']} ({a['baseline_records']} + {a['evaluation_records']})"),
             _row(t, "evaluation zone-minutes", 4800, a["zone_minutes"]),
             _row(t, "strong / weak episodes detected", "10/10; 0/5",
                  f"{a['strong_detected']}/{a['strong_total']}; {a['weak_detected']}/{a['weak_total']}"),
             _row(t, "zone-minute TP / FP / FN / TN", "280 / 0 / 120 / 4400",
                  f"{a['TP']} / {a['FP']} / {a['FN']} / {a['TN']}"),
             _row(t, "precision / recall / F1", "1.000 / 0.700 / 0.824",
                  f"{a['precision']:.3f} / {a['recall']:.3f} / {a['F1']:.3f}"),
             _row(t, "FN split (weak / strong confirmation lag)", "100 / 20",
                  f"{a['fn_in_weak']} / {a['fn_strong_confirmation_lag']}"),
             _row(t, "degraded-coverage zone-minutes", 50, a["degraded_zone_minutes"])]
    p = a.get("protection")
    if p and p.get("available"):
        rows.append(_row(t, "ordinary protected records verified", "40320/40320",
                         f"{p['ordinary_verified']}/{p['ordinary_records']}"))
        for name, v in p["negative"].items():
            rows.append(_row(t, f"negative class: {name}", "1000/1000 rejected", f"{v['rejected']}/{v['cases']} rejected"))
    else:
        rows.append(_row(t, "host-side protection demo", "40320/40320; 4 x 1000/1000",
                         "skipped (cryptography not installed or disabled)", skip=True))
    # ---------------- Study B (Table 12)
    b = study_b.run(os.path.join(workdir, "study_b"))
    t = "Study B / Table 12"
    rows += [_row(t, "input lines; unique identities", "2173; 2160", f"{b['input_lines']}; {b['unique_identities']}"),
             _row(t, "duplicates; conflicts; rejected lines", "6; 1; 6",
                  f"{b['duplicates']}; {b['conflicts']}; {b['rejected']}"),
             _row(t, "nonconflicting records exported", 2159, b["exported"]),
             _row(t, "five-minute summaries (per site)", "12 (6 + 6)",
                  f"{b['summaries']} ({' + '.join(str(v) for v in b['windows_per_site'].values())})"),
             _row(t, "expected window / final-minute records", "180 / 36",
                  f"{'/'.join(map(str, b['expected_per_window']))} / {'/'.join(map(str, b['fresh_expected']))}"),
             _row(t, "functional self-checks passed / failed", "10 / 0",
                  f"{b['selfchecks_passed']} / {b['selfchecks_failed']}")]
    # ---------------- Stage 1 (Table 13)
    s = bench.stage1_stats()
    t = "Stage 1 / Table 13"
    parsed = frames.parse_gateway_line(bench.PAPER_EXAMPLE_LINE)
    rows += [_row(t, "records; sequence continuous", "13; True", f"{s['records']}; {s['sequence_continuous']}"),
             _row(t, "node-time span (s)", 120, s["span_s"]),
             _row(t, "temperature change (degC)", 0.38, s["temp_change"]),
             _row(t, "PPG IR range; motion range", "1181-1224; 75-102",
                  f"{s['ppg_ir_range'][0]}-{s['ppg_ir_range'][1]}; {s['motion_range'][0]}-{s['motion_range'][1]}"),
             _row(t, "example line -> seq, node ms, temp, PPG, motion, HR", "13, 122488, 22.19, 1187, 97, 76",
                  f"{parsed['sequence']}, {parsed['node_time_ms']}, {parsed['temp_x100'] / 100:.2f}, "
                  f"{parsed['ppg_ir']}, {parsed['motion_mg']}, {parsed['hr_x1']}")]
    # ---------------- Table 16 / Sec. 3.3.8 analytical checks
    t = "Sec. 4.9 / Table 16"
    q = {r["capacity_units"]: r["Q_percent"] if r["feasible"] else "infeasible"
         for r in (incident.allocate_services(c) for c in (2, 4, 6, 10))}
    rows.append(_row(t, "Q at B = 2 / 4 / 6 / 10", "infeasible / 68.75 / 93.75 / 100.0",
                     f"{q[2]} / {q[4]} / {q[6]} / {q[10]}"))
    z = sizing()
    rows.append(_row("Sec. 3.3.8", "storage sizing (12 nodes, 1.5 kB/record, 8 h)", "1.8 kB/s; 51.84 MB",
                     f"{z['bytes_per_s'] / 1000:.1f} kB/s; {z['MB_total']} MB"))
    ok = all(r["status"] != "MISMATCH" for r in rows)
    return {"rows": rows, "ok": ok, "workdir": workdir, "study_a": a, "study_b": b}


def format_table(rows) -> str:
    cols = ("group", "item", "paper", "reproduced", "status")
    data = [[str(r[c]) for c in cols] for r in rows]
    widths = [max(len(c), *(len(d[i]) for d in data)) for i, c in enumerate(cols)]
    line = lambda vals: "| " + " | ".join(v.ljust(w) for v, w in zip(vals, widths)) + " |"  # noqa: E731
    out = [line(cols), "|" + "|".join("-" * (w + 2) for w in widths) + "|"]
    out += [line(d) for d in data]
    return "\n".join(out)
