# Changelog

## 1.2.0 — 2026-10-14 (optimized, self-sufficient cells)

- Every analysis cell is self-sufficient: after the three setup cells it can be run alone, in any order,
  or after **Restart session**. Each cell starts with `from umsf_fw_lab import *`; native states (host
  tests, compiled C library, experiment CSVs, vector and corruption checks, verification ledger) are
  produced on first use and cached. Figures and the figure index persist on disk; the ledger and export
  cells work whenever they are run and report sections not yet executed.
- New readable runtime module `notebook/umsf_fw_lab.py` (written by the notebook with `%%writefile`). The
  verified project is extracted once to `umsf_firmware_runs/project/` and reused while its payload and all
  57 original source hashes verify; re-running setup reloads the runtime and clears caches.
- Faster: full Run all ≈ 22 s instead of ≈ 33 s on the same machine. The original Makefile runs with
  parallel jobs, the shared C library compiles concurrently with it, and binaries are rebuilt only when a
  source is newer (incremental after a kernel restart).
- Smaller: payload is a solid xz tar in Base85 (89 kB instead of 136 kB; notebook 186 kB instead of 226 kB).
- Execution evidence now includes a per-cell isolation run (`results/VALIDATION_REPORT.json`) and
  `scripts/package_release.py` rebuilds the checksummed Zenodo ZIP.
- All experiment CSVs, the vector log and the verification ledger are byte-identical to release 1.1.0.
  The original firmware 1.0.0 sources are unchanged.

## 1.1.0 — 2026-10-14

Added an English standalone notebook with embedded source, native experiments, 30 explanatory figures, CSV exports, execution evidence, publication metadata and original-source checksums. Preserved original firmware1.0.0 without source modifications. This is a notebook companion release, not a validated ESP32 firmware update.
