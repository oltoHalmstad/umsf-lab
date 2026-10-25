# Changelog

## 1.2.0 — 2026-10-15 (optimized, self-sufficient cells)

- Every analysis cell is self-sufficient: after the three setup cells it can be run alone, in any order,
  or after **Restart session**. Each cell starts with `from umsf_ai_lab import *`; shared states (original
  test suite, supplied analytical checks, ingested scenario, both 41-cutoff agent replays, verification
  ledger) are computed on first use and cached. Figures and the figure index persist on disk; the ledger and
  export cell works whenever it is run and reports sections not yet executed.
- Re-running is safe: each replay and the simulated-authority demonstration start fresh audit chains (the
  original audit log appends to an existing file). New readable runtime module `notebook/umsf_ai_lab.py`.
- Faster: full Run all ≈ 27 s instead of ≈ 33 s on the same machine. The ten original test modules run as
  concurrent processes, the independent no-backup replay runs in a background process alongside them, and
  the service-selection matrix solves each capacity once instead of once per service.
- Smaller: payload is a solid xz tar in Base85 (369 kB instead of 734 kB; notebook 580 kB instead of 1,029 kB);
  `results/snapshots.json` is stored as compact JSON (same content).
- Recorded outputs use project-relative paths, so no machine-specific directories appear in results.
- Execution evidence now includes a per-cell isolation run (`results/VALIDATION_REPORT.json`).
- Timelines, checks, tables, report and explorer are identical to release 1.1.0; snapshot and audit contents
  differ only by run paths and wall-clock timestamps. The original agent 1.0.0 source is unchanged.

## 1.1.0 — 2026-10-15

Added an English standalone Colab laboratory, 30 exported figures, offline interactive explorer, fully executed notebook, HTML report, CSV/JSON results and publication metadata. Included the P1 fixture to execute all 116 original tests without skips. Preserved agent 1.0.0 source and documented prototype limitations. No claim of operational validation or live-LLM compatibility.
