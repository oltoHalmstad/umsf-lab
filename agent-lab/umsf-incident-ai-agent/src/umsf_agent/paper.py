"""Reproduction of the paper's analytical results.

* Table 10 (Sec. 4.1): constructed cases A, B, C with n_min=6, C_min=0.70, m_min=3, theta=0.30.
* Sec. 4.3 / 4.4 Study A note: six-person zone, n_min=5 -> effective coverage 83.3 %.
* Sec. 4.9 / Table 16 / Eq. (11) / Fig. 14: service allocation by exhaustive enumeration.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .continuity import OPTIMAL, INFEASIBLE, fig14_table, table16_solve
from .physio_rules import (ILLUSTRATIVE_PARAMS, STUDY_A_PARAMS, POSSIBLE_GROUP_EVENT, INSUFFICIENT_EVIDENCE,
                           INDIVIDUAL_REVIEW, decide, group_gate, threshold_feasibility)


def table10_case(case: str):
    roster = [f"W{i:02d}" for i in range(1, 13)]
    if case == "A":
        valid, flagged, urgent = 10, 4, []
    elif case == "B":
        valid, flagged, urgent = 4, 3, []
    elif case == "C":
        valid, flagged, urgent = 10, 1, ["W01"]
    else:
        raise ValueError(case)
    flags = {w: None for w in roster}
    for i, w in enumerate(roster[:valid]):
        flags[w] = 1 if i < flagged else 0
    g = group_gate(f"case_{case}", roster, flags, ILLUSTRATIVE_PARAMS)
    d = decide(g, [{"worker": w, "event_type": "sos"} for w in urgent])
    return g, d


TABLE10_EXPECTED = {
    "A": {"N": 12, "n": 10, "m": 4, "C_pct": 83.3, "p_pct": 40.0, "A": 1, "label": "Possible group event"},
    "B": {"N": 12, "n": 4, "m": 3, "C_pct": 33.3, "p_pct": 75.0, "A": 0,
          "label": "Insufficient group evidence; individual review"},
    "C": {"N": 12, "n": 10, "m": 1, "C_pct": 83.3, "p_pct": 10.0, "A": 0,
          "label": "Urgent individual assistance; no group trigger"},
}


def checks() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    def chk(name, expected, actual):
        out.append({"check": name, "expected": expected, "actual": actual, "pass": expected == actual})

    for case, exp in TABLE10_EXPECTED.items():
        g, d = table10_case(case)
        chk(f"Table 10 case {case}: expected/valid", f"{exp['N']} / {exp['n']}", f"{g.N} / {g.n}")
        chk(f"Table 10 case {case}: persistent flags", exp["m"], g.m)
        chk(f"Table 10 case {case}: coverage %", exp["C_pct"], g.C_pct)
        chk(f"Table 10 case {case}: affected proportion %", exp["p_pct"], g.p_pct)
        chk(f"Table 10 case {case}: group indicator A", exp["A"], g.A)
        chk(f"Table 10 case {case}: output", exp["label"], d.label_en)
    _, dB = table10_case("B")
    chk("Table 10 case B: states", sorted([INSUFFICIENT_EVIDENCE, INDIVIDUAL_REVIEW]), sorted(dB.states))
    _, dC = table10_case("C")
    chk("Table 10 case C: urgent pathway independent of group rule", True, bool(dC.urgent) and dC.group.A == 0)
    feas12 = threshold_feasibility(12, ILLUSTRATIVE_PARAMS)
    chk("Sec 4.3: N=12 min eligible max(6, ceil(0.7*12))", 9, feas12.min_eligible)
    gB, _ = table10_case("B")
    chk("Sec 4.3: case B cannot satisfy coverage irrespective of flags", False, gB.conditions["C>=C_min"])
    fA = threshold_feasibility(6, STUDY_A_PARAMS)
    chk("Study A: six-person zone min eligible", 5, fA.min_eligible)
    chk("Study A: effective minimum coverage %", 83.3, fA.effective_min_coverage_pct)
    chk("Study A: nominal 70% condition redundant", True, fA.coverage_condition_redundant)
    # Section 4.9
    for B in range(0, 3):
        chk(f"Sec 4.9: B={B} infeasible", INFEASIBLE, table16_solve(B).status)
    for B in range(3, 6):
        r = table16_solve(B)
        chk(f"Sec 4.9: B={B} allocation / Q", ((1, 1, 0, 0), 68.75), (r.vector, r.Q_pct))
    for B in range(6, 10):
        r = table16_solve(B)
        chk(f"Sec 4.9: B={B} allocation / Q", ((1, 1, 1, 0), 93.75), (r.vector, r.Q_pct))
    for B in range(10, 13):
        r = table16_solve(B)
        chk(f"Sec 4.9: B={B} allocation / Q", ((1, 1, 1, 1), 100.0), (r.vector, r.Q_pct))
    r6 = table16_solve(6)
    chk("Sec 4.9: B=6 priority sum 15 of 16", (15.0, 16.0), (r6.objective, r6.total_weight))
    chk("Sec 4.9: B=4 one unit unused", 1.0, table16_solve(4).unused["units"])
    r7 = table16_solve(7)
    chk("Sec 4.9: B=7 production individually feasible but does not displace water", (1, 0), (r7.y["water_support"], r7.y["production"]))
    chk("Sec 4.9: exhaustive enumeration of 16 binary allocations", 16, table16_solve(6).candidates_examined)
    agree = all(table16_solve(B, "branch_and_bound").vector == table16_solve(B).vector for B in range(0, 13))
    chk("Sec 4.9: branch-and-bound agrees with enumeration for B=0..12", True, agree)
    chk("Sec 4.9: infeasible case assigns no Q", None, table16_solve(2).Q_pct)
    return out


def format_report(rows: List[Dict[str, Any]]) -> str:
    lines = ["Reproduction of Torstensson et al. (2026): Table 10, Sec. 4.3, Study A note, Sec. 4.9 / Table 16 / Fig. 14", ""]
    for r in rows:
        lines.append(f"[{'PASS' if r['pass'] else 'FAIL'}] {r['check']}: expected {r['expected']!r}, got {r['actual']!r}")
    lines += ["", "Fig. 14 data (Table 16 inputs, exhaustive enumeration):", "  B | status     | y         | sum w | Q %    | unused"]
    for row in fig14_table():
        y = "—" if row["y"] is None else "(" + ",".join(map(str, row["y"])) + ")"
        q = "—" if row["Q_pct"] is None else f"{row['Q_pct']:.2f}"
        ps = "—" if row["priority_sum"] is None else f"{row['priority_sum']:g}"
        un = "—" if row["unused_units"] is None else f"{row['unused_units']:g}"
        lines.append(f" {row['B']:2d} | {row['status']:<10} | {y:<9} | {ps:>5} | {q:>6} | {un}")
    n_fail = sum(1 for r in rows if not r["pass"])
    lines += ["", f"{len(rows) - n_fail}/{len(rows)} checks passed" + ("" if not n_fail else f" — {n_fail} MISMATCH(ES)")]
    return "\n".join(lines)
