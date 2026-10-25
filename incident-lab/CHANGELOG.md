# Changelog

## 1.2.0 — 2026-10-14 (optimized, self-sufficient cells)

- Every analysis cell is self-sufficient: after the three setup cells it can be run alone, in any
  order, or after **Restart session**. Each cell starts with `from umsf_lab import *`; shared states
  (incident data, Study A/B, as-of replay, semantic/protocol/crypto checks, verification) are computed
  on first use and cached. Figures and the figure catalog persist on disk, so the export cell works
  whenever it is run and reports sections not yet executed.
- New readable runtime module `notebook/umsf_lab.py` (written by the notebook with `%%writefile`).
  The verified project is extracted once to `umsf_notebook_runs/project/` and reused while its
  payload and all 66 original hashes verify; re-running setup reloads the runtime and clears caches.
- Faster: full Run all ≈ 60 s instead of ≈ 92 s on the same machine. The as-of replay passes the core
  state functions only the per-device candidate they would select (18 s → 2 s, guarded by an
  equivalence check against unfiltered calls); the original test suite now runs concurrently with the
  reference reproduction and checks (30 s → 16 s); record validation runs once per record; the
  reference seed is reused in the seed study; repeated set/loop work is vectorized.
- Smaller: payload is an LZMA ZIP in Base85 (380 kB instead of 501 kB; notebook 616 kB instead of
  741 kB); the offline dashboard stores data column-wise (0.35 MB instead of 1.2 MB) with identical
  records, snapshots and events.
- Execution evidence now includes a per-cell isolation run (`results/VALIDATION_REPORT.json`).
- All result tables are byte-identical to release 1.1.0; the analytical core v1.0.0 is unchanged.

## 1.1.0 — 2026-10-14 (notebook edition)

- Add a standalone English Colab notebook with an embedded, hash-checked source/data payload.
- Add extensive visual analysis, explicit scientific interpretation and parameter experiments.
- Add a dependency-free interactive HTML incident explorer and PNG/SVG figure exports.
- Add isolated full-cell execution evidence, original test-suite execution and integrity inventories.
- Preserve the original v1.0.0 analytical core, example data, tests, licenses and author metadata.
- The notebook release version is 1.1.0; `umsf_dataset.__version__` remains 1.0.0.
