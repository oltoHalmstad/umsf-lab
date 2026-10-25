# Reproducibility

## Quick start

```sh
# no installation needed (standard library only)
PYTHONPATH=src python3 -m unittest discover -s tests      # full test suite
PYTHONPATH=src python3 -m umsf_dataset reproduce          # paper comparison, exit code != 0 on mismatch
# or
sh scripts/reproduce.sh
# or, installed:
pip install .            # optional extras: .[crypto]  .[live]  .[all]
umsf-dataset reproduce
```

Tested with CPython 3.10, 3.11, 3.12 and 3.13 on Linux. Runtime: about 10 s (≈ 1 s without the
optional protection demo).

## What is reproduced, and how

| Paper item | Command / function | Seed | Notes |
|---|---|---|---|
| Table 11 (Study A) | `umsf-dataset synth-study-a --out DIR` | 20260908 | Exact: 10/10, 0/5; TP 280, FP 0, FN 120, TN 4400; P/R/F1 1.000/0.700/0.824; 50 degraded zone-minutes. |
| Table 11, protection rows | same (needs `cryptography`) | 20260908 | 40,320/40,320 verified; 4 × 1,000/1,000 rejected. Demo keys only. |
| Table 12 (Study B) | `umsf-dataset selfcheck` | 82026 | 2,173 lines; 2,160 unique; 6 dup; 1 conflict; 6 rejected; 2,159 exported; 12 summaries; 10/0 checks. |
| Table 13 (Stage 1) | `umsf-dataset synth-bench --out DIR` | — | Transcription + descriptive statistics (span 120 s, +0.38 °C, PPG 1181–1224, motion 75–102). |
| Table 6 / 14 (Stage 2) | same | 2026 | **Synthetic re-enactment** of the timeline for pipeline tests, not the original data. |
| Table 16 / Sec. 4.9 | `synth.incident.allocate_services(B)` | — | Exhaustive enumeration: infeasible (B<3), 68.75 %, 93.75 %, 100 %. |
| Sec. 3.3.8 sizing | `export.sizing()` | — | 1.8 kB/s; 51.84 MB per 8 h for 12 nodes. |

## Provenance of the Study A/B implementations

The manuscript analyses reported aggregates of Study A [21] and Study B [22]; their original code and
raw results were not available. The generators in `synth/` are **independent re-implementations of
the documented designs**. Where the paper does not specify a detail, this package fixes it as follows
(these choices are what make the reproduction exact and deterministic):

Study A
* HR noise σ = 3 bpm (rounded to 1 bpm), SpO2 noise σ = 0.3 pp (rounded to 0.1); worker offsets
  HR U(62, 80), SpO2 U(96.6, 98.0); activity offsets rest/light/moderate = 0/+10/+22 bpm and
  0/−0.2/−0.4 pp; 30-min activity blocks rotating per worker and day.
* Exceedance is strict (`> 3` scales); a flag needs the current and the two previous minutes
  eligible and exceeding; eligibility needs HR, SpO2 and quality ≥ 0.8 and a baseline for the
  activity. A worker's flag is *available* whenever the current minute is eligible.
* One strong episode per evaluation zone-shift (start minute 20–199), five weak episodes in
  randomly chosen zone-shifts (start 250–439), ten five-minute degraded intervals (two workers:
  one with null values, one with quality < 0.8) at least 5 min away from any episode.
* "Degraded-coverage zone-minutes" = zone-minutes with group state
  `insufficient_monitoring_evidence` (eligible < 5).

Study B
* Start 2026-09-08T06:00:00Z (09:00 Kyiv), epoch-aligned 5-min windows → 6 windows per site.
* Poor quality = U(0.2, 0.55), good threshold 0.6; delayed records arrive 180 s (+0.2–1.5 s) late;
  exact duplicates are redelivered 30 s later; the conflict changes `hr_bpm` by +9 bpm.
* Invalid lines: `measured` origin, unknown field, out-of-range HR, string sequence, `NaN`,
  truncated JSON.
* Observed fresh-good counts in full windows: 33–36 of 36 (the paper reports 32–36 for its run);
  all six devices per site contribute a fresh good record in every window.

## Determinism

All generators use `random.Random(seed)` and fixed start times; exports use a fixed
`generated_at`, and audit timestamps use an injected clock in Study B, so `scripts/make_data.sh`
regenerates byte-identical files under the same Python version (the manifest records Python and
SQLite versions).

## Not reproduced / not tested

* No abrupt power-loss durability test (only orderly SQLite close and reopen).
* No physical BLE, MQTT/TLS, enrollment or key management; adapters are unit-tested with fakes.
* No physiological, gas, structural or human-detection validity of any value.
