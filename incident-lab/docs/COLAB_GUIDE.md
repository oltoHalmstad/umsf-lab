# Colab and local execution

Upload `UMSF_Incident_Lab.ipynb` through https://colab.research.google.com/ → File → Upload notebook,
then choose Runtime → Run all. Use a standard CPU runtime. GPU and TPU are not required. A full run takes
about one to two minutes.

## Setup (Section 1, three cells)

1. A collapsed `%%writefile umsf_payload.py` cell stores the embedded project: an LZMA-compressed ZIP in
   Base85 text with source, tests, schemas, data and documentation, plus its SHA-256 digest.
2. A collapsed `%%writefile umsf_lab.py` cell stores the readable runtime (identical to
   `notebook/umsf_lab.py` in the release). Expand it to inspect the code.
3. The start cell imports the runtime. It installs only missing packages (NumPy, pandas, Matplotlib,
   seaborn, cryptography), verifies the payload and all 66 original source/data hashes, and extracts the
   project once to `umsf_notebook_runs/project/`. Later imports reuse the verified copy; a damaged or
   edited copy is replaced. Nothing is fetched from Zenodo or GitHub.

## Self-sufficient analysis cells

Every analysis cell begins with `from umsf_lab import *`. Shared states — incident data, Study A and B,
the as-of replay, semantic, protocol and cryptographic checks, and the original test-suite verification —
are computed on first use and cached for the session. Therefore each cell can be run alone, in any order,
and again after **Runtime → Restart session** (files on the runtime disk survive a restart). The first
cell that needs an expensive state prints how long it took to prepare it.

Figures are written to `results/figures/` and registered in a persistent catalog. The export cell is also
self-sufficient: it computes missing verification or dashboard outputs itself and tells you how many of
the 30 figures have not yet been produced. Re-running setup reloads the runtime and clears the caches.

If a cell reports `No module named 'umsf_lab'`, the runtime files were removed (for example after
**Disconnect and delete runtime**); run Section 1 again. If a package installation fails, restore network
access and rerun the start cell. If a custom detector setting gives zero alerts, precision is undefined and
is displayed as missing; this is an analytical result, not a cell failure.

## Outputs

Use the Colab Files pane to download `umsf_notebook_runs/latest/results.zip`. It includes figures, tables,
generated Study A/B files, test evidence and checksums. The notebook itself is saved using Colab's File
menu. No automatic browser download is forced during Run all. The HTML explorer is optional: its data
are also shown by static figures and tables. In notebook viewers that disable scripts, open
`interactive_dashboard.html` directly in a browser.

For offline use, install `requirements.txt` while online first, then execute with Jupyter. Standard
Python 3.10 or later is required by the original core. The exact environment used for this release is
recorded in `results/environment.json`; a passing local run is not a hosted Colab session test.

Official Colab guidance (accessed 2026-10-14):
https://research.google.com/colaboratory/faq.html — notebook upload, dependency/file setup, and runtime storage.
