# Suggested Zenodo record

Title: UMSF Firmware Laboratory: A Self-Contained Colab Companion for ESP32/BLE Protocols and Native Logic

Resource type: Software

Version: 1.2.0

Language: English

License: MIT

## Description

An English, self-contained computational laboratory accompanying umsf-ble-firmware 1.0.0. The notebook embeds the original source and builds its portable C/C++ libraries, runs all original host tests and supplied protocol vectors, and generates 30 explanatory figures with PNG/SVG exports. Controlled native experiments examine physiological feature quality, null sentinels, explicitly synthetic HR, stationary detector rules, gas warmup and hysteresis, tilt uncertainty, SOS debounce, link freshness, RAM-buffer priorities and application acknowledgements. Protocol experiments inspect CRC corruption and native BLE fragmentation. Includes clean and executed notebooks, a rendered HTML report, CSV traces, source provenance, validation evidence, citation metadata and MIT license. All experimental sensor inputs are synthetic. ESP32 firmware images are not compiled or hardware-validated in this release; hosted Google Colab frontend execution has not been directly tested. After a three-cell setup, every analysis cell is self-sufficient: shared native builds, experiment traces and checks are produced on first use and cached, so any cell can run alone, in any order or after a kernel restart. The notebook is verified locally in a fresh Jupyter kernel with only the notebook supplied, and each of its 28 analysis cells is additionally verified alone in its own fresh kernel. Thresholds are uncalibrated; no clinical, gas-concentration, structural-safety or causal-attribution claims are made.

## Upload preparation

Upload the release ZIP. You may additionally upload the standalone notebook for convenient access. Copy the creators, affiliations and ORCIDs from `.zenodo.json` / `CITATION.cff`; they are retained from the supplied release. Check the release date against the actual publication date. The JSON file is a metadata companion, not a promise that the web form imports it automatically.

Reserve a DOI in the Zenodo draft if you want to put it into the citation files before publication. No DOI is present here. If adding a DOI or changing files, regenerate the checksum inventory before uploading the revised ZIP. Preview and publish the record yourself when its metadata are final. This package has not been uploaded to or published on Zenodo.

Official guidance: https://help.zenodo.org/docs/deposit/create-new-upload/
