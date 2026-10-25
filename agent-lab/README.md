# UMSF Incident AI Agent Laboratory

English standalone notebook companion 1.2.0 to original agent 1.0.0.

## Start in Google Colab

1. Open https://colab.research.google.com/ and select File → Upload notebook.
2. Upload `UMSF_AI_Agent_Lab.ipynb` and choose a Python 3 CPU runtime.
3. Select Runtime → Run all (about half a minute on a CPU). Every input and the original package source are embedded.
4. Inspect the figures and explanations. The last cell creates a results ZIP. Its optional Colab download lines can be uncommented.

No API key, external dataset, Google Drive mount, C compiler, broker or physical device is required. The notebook installs NumPy/pandas/Matplotlib only if absent. Internet may therefore be needed for dependency installation; the analysis itself uses no remote service. Local prerequisites: Python3.10+, IPython and the listed plotting libraries.

## Self-sufficient cells (release 1.2.0)

Section 0 has three setup cells: two collapsed `%%writefile` cells save the embedded payload (`umsf_ai_payload.py`) and the readable runtime (`umsf_ai_lab.py`, also shipped as `notebook/umsf_ai_lab.py`); a start cell imports it. Every analysis cell begins with `from umsf_ai_lab import *` and obtains the tests, checks and agent replays it needs on first use (cached). Any analysis cell can therefore run alone, in any order, or after **Runtime → Restart session**; each replay starts fresh audit chains, so re-running is safe. Only after the runtime files are deleted (**Disconnect and delete runtime**) must Section 0 run again.

## Deliverables

| File/directory | Content |
|---|---|
| `UMSF_AI_Agent_Lab.ipynb` | Clean standalone notebook: 62 cells, 31 code cells (3 setup + 28 self-sufficient analysis cells) |
| `UMSF_AI_Agent_Lab_executed.ipynb` | Verified notebook with all outputs |
| `UMSF_AI_Agent_Lab.html` | Rendered English report |
| `interactive_explorer.html` | Offline browser explorer,41 replay snapshots |
| `figures/` | 30 PNG and30 SVG figures |
| `results/` | CSV/JSON exports, replay audits, logs, verification evidence |
| `umsf-incident-ai-agent/` | Original source, tests, two synthetic scenarios and localized examples |
| `umsf-incident-dataset/` | P1 incident integration fixture and license/citation files |
| `notebook/umsf_ai_lab.py` | Notebook runtime: setup, verification, helpers and cached analysis states |
| `scripts/build_notebook.py`, `scripts/execute_notebook.py`, `scripts/package_release.py` | Rebuild the notebook; fresh-kernel execution with per-cell isolation check; checksummed Zenodo ZIP |
| `docs/` | Data dictionary, methods and evidence boundaries |
| `provenance/` | Original uploaded archive and source/fixture hash inventory |
| `.zenodo.json`, `CITATION.cff` | Publication metadata preserving supplied creators |
| `SHA256SUMS.txt` | Release integrity inventory |

## Reproduce locally

```bash
python -m pip install -r requirements.txt
python scripts/build_notebook.py      # optional: rebuild the notebook from notebook/umsf_ai_lab.py + sources
python scripts/execute_notebook.py    # Run all + per-cell isolation check; refreshes results/figures/HTML
python scripts/package_release.py     # verify and write ../umsf-ai-agent-colab-v1.2.0-zenodo.zip
```

Only the notebook is copied into an isolated working directory. Every code cell executes sequentially in a fresh Jupyter kernel and failures stop the run. The runner then executes the setup cells once and every analysis cell alone in its own fresh kernel (reverse order) to prove that each cell is self-sufficient. The packaged validation is local, not a direct test of Google's hosted frontend. Python versions actually tested are recorded in `requirements-tested.txt` and the validation report.

## Verified outcome

116 original tests passed, zero skipped;44 supplied analytical checks passed;31 code cells completed without errors, and each of the 28 analysis cells also ran alone in a fresh kernel; 30 figures produced. Both synthetic variants ran at41 cutoffs. The six P1 integration tests that the standalone original archive would skip run here because the companion incident fixture is bundled. The notebook retains every original source file unchanged and verifies its SHA-256.

## Interpret correctly

Plans are proposals requiring authorized human review. No dispatch, equipment control or real approval occurs. An isolated authority demonstration is explicitly simulated. The exact matching and allocation solvers do not make the recovery scheduler optimal; recovery uses a heuristic. Scores are not diagnoses, Q is not lives saved, and silence is not casualty evidence. Every scenario record is synthetic. Neither operational safety nor rescue effectiveness is validated.

The optional LLM adapter is preserved but never invoked by the notebook. Its live API compatibility is unverified. The notebook demonstrates limitations in its lexical post-check, including source-text exceptions and tolerated small numbers. The audit chain is an integrity aid, not authentication or tamper-proof storage.

New explanations, tables, figures, report and explorer are English. Original Ukrainian source labels and examples remain in the provenance material and raw outputs. Author metadata are copied from the supplied project; this release does not independently establish manuscript publication status.

No DOI is invented, and no Zenodo record is published automatically. See `ZENODO_DESCRIPTION.md` for the English deposit text.
