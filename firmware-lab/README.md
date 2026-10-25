# UMSF Firmware Laboratory

A self-contained English notebook companion to the supplied ESP32/BLE firmware.

## Run in Google Colab

1. Open https://colab.research.google.com/ and use File → Upload notebook.
2. Upload `UMSF_Firmware_Lab.ipynb` from this release. Use Python 3 on a CPU runtime.
3. Choose Runtime → Run all (well under a minute on a CPU). No Google Drive mount, dataset download, device, MQTT service or secret is required.
4. Inspect the figures, explanatory text and verification ledger. Download the generated results ZIP if desired.

The notebook carries a SHA-256-checked embedded source bundle and compiles the original portable C/C++ code.

**Self-sufficient cells (release 1.2.0).** Section 0 has three setup cells: two collapsed `%%writefile` cells save the embedded payload (`umsf_fw_payload.py`) and the readable runtime (`umsf_fw_lab.py`, also shipped as `notebook/umsf_fw_lab.py`); a start cell imports it. Every analysis cell begins with `from umsf_fw_lab import *` and obtains the native builds, CSV traces and checks it needs on first use (cached; incremental builds). Any analysis cell can therefore run alone, in any order, or after **Runtime → Restart session**. Only after the runtime files are deleted (**Disconnect and delete runtime**) must Section 0 run again. Python packages are installed only if missing. Linux GCC/G++, make and a Python/IPython environment are prerequisites. The hosted Colab frontend has not been directly tested; the isolated local execution report is included.

## What is included

| Item | Purpose |
|---|---|
| `UMSF_Firmware_Lab.ipynb` | Standalone clean notebook: 62 cells, 31 executable code cells (3 setup + 28 self-sufficient analysis cells) |
| `UMSF_Firmware_Lab_executed.ipynb` | Same notebook with verified outputs |
| `UMSF_Firmware_Lab.html` | Readable output report without running code |
| `figures/` | 30 figures in PNG and editable SVG |
| `results/` | Native experiment CSVs, logs, versions and validation reports |
| `firmware/` | All original source files, preserved verbatim |
| `lab/native_experiments.cpp` | Added controlled experiments using original public APIs |
| `notebook/umsf_fw_lab.py` | Notebook runtime: setup, verification, helpers and cached native states |
| `scripts/build_notebook.py`, `scripts/execute_notebook.py`, `scripts/package_release.py` | Rebuild the notebook; fresh-kernel execution with per-cell isolation check; checksummed Zenodo ZIP |
| `provenance/` | Original archive, original-source SHA-256 inventory |
| `docs/` | Reproduction, data dictionary and evidence boundaries |
| `.zenodo.json`, `CITATION.cff`, `ZENODO_DESCRIPTION.md` | Publication metadata with supplied authors |
| `SHA256SUMS.txt` | Integrity inventory for the release |

## Reproduce locally

```bash
python -m pip install -r requirements.txt
python scripts/build_notebook.py      # optional: rebuild the notebook from notebook/umsf_fw_lab.py + sources
python scripts/execute_notebook.py    # Run all + per-cell isolation check; refreshes results/figures/HTML
python scripts/package_release.py     # verify and write ../umsf-firmware-colab-v1.2.0-zenodo.zip
```

The runner creates a temporary working directory, supplies only the notebook, executes every code cell in order in a fresh Jupyter kernel and stops on error. It then runs the setup cells once and every analysis cell alone in its own fresh kernel (reverse order) to prove that each cell is self-sufficient.

The script regenerates executed notebook, results, figures and HTML. Checksums describe the packaged release and must be regenerated after edits. `requirements-tested.txt` records Python package versions from validation; `requirements.txt` gives compatible ranges rather than claiming a universal binary lockfile.

## Evidence and provenance

This release retains all 43 original tests (475 checks) and 19 supplied vectors, including one intentionally corrupted CRC vector. It adds 1,155 personnel-window parameter combinations and a 260-second controlled stationary scenario. All scenario inputs are synthetic. Native tests establish software behavior only. ESP32 images were not compiled; sensors, BLE radio, MQTT/mTLS and physical operation remain unverified.

Default HR is null; synthetic HR is flagged; SpO2 is null. Quality is a heuristic, not confidence. MQ voltage is not gas concentration. Tilt displacement latches attachment uncertainty. `possible_impact_local` is an unverified local composite. The buffer is volatile, and its priority policy does not guarantee urgent-record retention when full. The supplied ACK parser is a limited field extractor, not strict JSON validation.

The new notebook and documentation are English. The archived source retains original localized web-page strings and README to preserve its identity. Author names and affiliations come from the supplied metadata; version 1.2.0 denotes the notebook companion, not newly validated hardware. The original MIT license is retained. No DOI is invented and no record is published automatically.

Official usage references (checked 2026-10-14):
- https://research.google.com/colaboratory/intl/en-GB/faq.html
- https://help.zenodo.org/docs/deposit/create-new-upload/
