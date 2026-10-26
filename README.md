# UMSF Incident Lab

Evidence-aware replay of multisensor incident streams and rule-based decision support for the first hours after a missile strike on a critical infrastructure facility.

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23380282.svg)](https://doi.org/10.5281/zenodo.23380282)
![Version](https://img.shields.io/badge/version-1.2.0-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

> **Research software.** All inputs shipped here are synthetic or transcribed, and field performance has not been established. Outputs are proposals for human approval. This is not a medical device and not an operational safety system.

## What it does

- Replays a multisensor record stream at explicit **receipt-time cutoffs**, keeping measurement time (`measured_at`) and receipt time (`received_at`) separate.
- Validates records (bounded strict JSON, JSON Schemas), deduplicates them by `(site, device, boot_id, sequence)` and quarantines conflicting payloads while keeping both versions for audit.
- Labels every source as **current, stale, missing or unknown** at each cutoff. Missing devices stay in the roster denominator and are never imputed.
- Applies a **coverage-aware group gate** that refuses a group conclusion from too few valid observations. SOS requests bypass the gate.
- Proposes rescue-task assignments, service allocations and repair schedules, reports **INFEASIBLE** instead of relaxing mandatory services, and requires a declared role and a reason for every approval (hash-chained audit log).

## Repository layout

| Folder | Release | Zenodo DOI | Role |
|---|---|---|---|
| [`incident-lab/`](incident-lab/) | UMSF Incident Lab 1.2.0 (`umsf_dataset` 1.0.0) | [10.5281/zenodo.23380282](https://doi.org/10.5281/zenodo.23380282) | **Main product**: evidence-aware replay, SQLite store, CSV/JSONL export with SHA-256 manifest |
| [`agent-lab/`](agent-lab/) | UMSF Incident AI Agent Lab 1.2.0 (`umsf_agent` 1.0.0) | [10.5281/zenodo.23380523](https://doi.org/10.5281/zenodo.23380523) | Linked deterministic decision support |
| [`firmware-lab/`](firmware-lab/) | UMSF Firmware Lab 1.2.0 (firmware 1.0.0) | [10.5281/zenodo.23380409](https://doi.org/10.5281/zenodo.23380409) | Host-side native tests and protocol vectors for the reference node firmware |
| [`bench-prototype/`](bench-prototype/) | UMSF Bench Prototype 1.0.0 | [10.5281/zenodo.23542153](https://doi.org/10.5281/zenodo.23542153) | ESP32 bench firmware and local dashboard (provenance only; not part of the verified releases) |

Each folder is an unmodified copy of its Zenodo archive. It contains its own README, LICENSE, CITATION.cff, CHANGELOG, `docs/` and a `SHA256SUMS.txt` inventory, which you can check with `sha256sum -c SHA256SUMS.txt` inside the folder.

## Requirements

- Python ≥ 3.10. The analytical cores of Incident Lab and Agent Lab use only the standard library.
- Notebooks: numpy, pandas, matplotlib, seaborn, nbformat, nbclient, nbconvert, ipykernel (see each `requirements.txt`).
- Optional Incident Lab adapters: `cryptography>=41`, `paho-mqtt>=1.6`, `bleak>=0.21`, `pyserial>=3.5` (`incident-lab/requirements-optional.txt`).
- Firmware Lab: GCC/G++ and make.
- Bench prototype: PlatformIO with an ESP32 DevKit (the interface simulator needs only Python).
- Tested on Linux with CPython 3.13 (3.13.16), SQLite 3.45.1 and GCC 13.3.0.

## Quick start

### Option 1: notebook (no installation)

Open the notebook of a release in Google Colab (**File → Upload notebook**) or local Jupyter, then choose **Run all**:
`incident-lab/UMSF_Incident_Lab.ipynb`, `agent-lab/UMSF_AI_Agent_Lab.ipynb` or `firmware-lab/UMSF_Firmware_Lab.ipynb`.
Each notebook embeds its source, tests and data in a hash-checked payload. Pre-executed versions (`*_executed.ipynb`) and HTML reports are included.

### Option 2: command line

```bash
git clone https://github.com/oltoHalmstad/umsf-lab.git
cd umsf-lab

# UMSF Incident Lab
cd incident-lab
PYTHONPATH=src python3 -m unittest discover -s tests      # 58 tests
PYTHONPATH=src python3 -m umsf_dataset reproduce          # 25 reference rows; non-zero exit on mismatch
cd ..

# UMSF Incident AI Agent Lab
cd agent-lab/umsf-incident-ai-agent
python3 -m unittest discover -s tests -t tests            # 116 tests
PYTHONPATH=src python3 -m umsf_agent reproduce-paper      # 44 analytical checks
pip install .                                             # optional: installs the umsf-agent command
umsf-agent run --data <dataset dir> --out <output dir>
cd ../..

# UMSF Firmware Lab
make -C firmware-lab/firmware/test/host                   # 43 native test cases, 475 checks

# Bench prototype: view the dashboard without hardware
python3 bench-prototype/interface/mock_gateway.py --scenario impact   # open http://127.0.0.1:8000
```

Expected results for v1.2.0: 58/58 and 116/116 unit tests, 25/25 reference rows, 44/44 analytical checks, 43/43 native test cases (475 checks).

## Documentation

- `incident-lab/docs/`: protocol v1.0, data dictionary, methodology, reproducibility
- `agent-lab/docs/`: data dictionary, methods and evidence boundaries
- `firmware-lab/docs/`: reproduction, data dictionary and evidence boundaries
- `bench-prototype/docs/`: hardware, wiring and packet formats

## Known limitations

- All inputs are synthetic or transcribed, and the bench sensors are uncalibrated.
- Thresholds are illustrative and must be set by the facility operator.
- The CRC check provides no authentication, approval roles are declared values rather than authenticated identities, and the audit hash chain is unkeyed.
- The optional language-model briefing layer in Agent Lab is not validated and is never invoked by the notebook.

See each release README and the accompanying paper for details.

## Authors

Saltanat Adilzhanova, Olga Torstensson, Dmytro Prokopovych-Tkachenko, Mariia Tykhonenko, Gulzhanat Beketova and Madina Sydybayeva. See [AUTHORS.md](AUTHORS.md) for affiliations and roles.

## Citation

If you use this software, please cite the archived release (see also [`CITATION.cff`](CITATION.cff)):

> O. Torstensson, D. Prokopovych-Tkachenko, S. Adilzhanova, M. Tykhonenko, G. Beketova, M. Sydybayeva, UMSF Incident Lab, version 1.2.0 [Software], Zenodo, 2026. https://doi.org/10.5281/zenodo.23380282

The bench prototype is cited separately:

> D. Prokopovych-Tkachenko, UMSF Bench Prototype: ESP32 sensor firmware and local monitoring interface, version 1.0.0 [Software], Zenodo, 2026. https://doi.org/10.5281/zenodo.23542153

## Support

Open an issue at https://github.com/oltoHalmstad/umsf-lab/issues, or e-mail olga.torstensson@hh.se.

## License

MIT. See [LICENSE](LICENSE). Each release folder carries its own copy of the license.
