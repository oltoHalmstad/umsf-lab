# UMSF Incident Lab — standalone Colab notebook

**Notebook release 1.2.0 · Original analytical core 1.0.0 · English · MIT**

An executable research companion for evidence-aware multisensor monitoring. The notebook
contains its own compressed source, tests and data. Uploading the single `.ipynb` is sufficient;
no GitHub repository, API token, mounted Drive, ZIP upload, or external dataset is required.
Use a CPU runtime. All results are derived from the supplied package, not from live devices.

## Start in Google Colab

1. Extract this ZIP on your computer.
2. Visit https://colab.research.google.com/ and choose **File → Upload notebook**.
3. Upload `UMSF_Incident_Lab.ipynb`.
4. Select **Runtime → Run all** (about 1–2 minutes on a CPU). Section 1 installs only missing
   Python libraries and verifies the embedded project.
5. Browse the figures, tables and interactive scenario explorer. In Colab's Files pane,
   download `umsf_notebook_runs/latest/results.zip` when the run completes.

The notebook embeds the research inputs. Internet access is needed only if dependencies are
missing; the analytical pipeline itself makes no network requests. Offline execution works
with the requirements installed. Runtime outputs are temporary unless you download them.

## Self-sufficient cells

Section 1 consists of three setup cells: two collapsed `%%writefile` cells save the embedded payload
(`umsf_payload.py`) and the readable runtime (`umsf_lab.py`, also shipped as `notebook/umsf_lab.py`),
and a start cell imports it. Every analysis cell then begins with `from umsf_lab import *`; shared
results are computed on first use and cached. Consequently any analysis cell can be run alone, in any
order, or after **Runtime → Restart session**. Only after the runtime files are deleted (for example by
**Disconnect and delete runtime**) must Section 1 be run again.

## Contents

| Path | Purpose |
|---|---|
| `UMSF_Incident_Lab.ipynb` | Portable notebook, with all code and data embedded |
| `UMSF_Incident_Lab_executed.ipynb` | Same notebook with verified execution outputs |
| `UMSF_Incident_Lab.html` | Read-only HTML report with embedded plots |
| `interactive_dashboard.html` | Offline incident explorer with device/channel/time controls |
| `figures/` | Publication-friendly PNG and SVG figures |
| `results/` | Computed metrics, analysis CSVs, software test evidence and run report |
| `notebook/umsf_lab.py` | Notebook runtime: setup, verification, helpers and cached analysis states |
| `src/umsf_dataset/`, `tests/`, `data/` | Original core, tests and supplied example data |
| `docs/` | Protocol, data dictionary, methodology and Colab/Zenodo instructions |
| `provenance/` | Source archive fingerprint and byte-preservation inventory |
| `CITATION.cff`, `.zenodo.json`, `LICENSE` | Citation, deposit metadata and original MIT license |
| `ZENODO_DESCRIPTION.txt`, `START_HERE.txt` | Ready-to-copy English deposit text and quick start |
| `SHA256SUMS.txt` | Release integrity inventory (excludes itself) |

## Reproduce locally

```bash
python -m pip install -r requirements.txt
python scripts/build_notebook.py      # optional: rebuild the notebook from notebook/umsf_lab.py + sources
python scripts/execute_notebook.py    # Run all + per-cell isolation check, refreshes results/figures
PYTHONPATH=src python -m unittest discover -s tests
PYTHONPATH=src python -m umsf_dataset reproduce
```

The execution script uses a fresh kernel and working directory for a full Run all, then runs the setup
cells once and every other code cell alone in its own fresh kernel (reverse order) to prove that each
cell is self-sufficient. Rerunning **Run all** reloads the runtime and overwrites the deterministic
results in `umsf_notebook_runs/project/results/`.

## Scientific interpretation

Study A and Study B are independent synthetic re-implementations designed to reproduce supplied
manuscript aggregates. Their match is a reproducibility demonstration, not independent predictive
validation. Stage 1 is a supplied bench transcription; its HR channel is a synthetic test field.
Stage 2 is a synthetic re-enactment, not an original measurement log. The incident scenario is fully
synthetic. No human-subject data are included.

Missing observations remain missing. Uncalibrated gas voltage is not a concentration estimate.
Loss of a link does not establish injury or collapse. Simulated external reports retain provenance;
local composite events remain unverified. The software does not control equipment or dispatch teams.

Authors and affiliations are retained from the supplied citation metadata. This release adds the
notebook, explanatory documentation, analysis and visual exports without changing the core algorithms.
No DOI is invented: add the actual DOI after Zenodo reserves or publishes it.
See `docs/ZENODO_DEPOSIT.md` and `results/VALIDATION_REPORT.json` for deposit and verification details.
