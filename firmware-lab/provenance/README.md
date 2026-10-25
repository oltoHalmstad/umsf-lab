# Original source provenance

The supplied `umsf-ble-firmware-v1.0.0.zip` is retained unchanged in this directory. `source_sha256.json` records every original file extracted into `firmware/`. All original source bytes are preserved. The notebook verifies these hashes before and after its native experiment run. Build outputs are generated only in temporary runtime directories, not in the archived firmware tree.

The original archive is retained for provenance but is not redundantly embedded in the notebook; its individual source files are embedded instead. New companion code is in `lab/` and `scripts/`. The notebook self-extraction payload (an xz-compressed tar in Base85 text) includes the native harness, the source and the source inventory. Notebook builds are written to `umsf_firmware_runs/project/build/` and the original Makefile build directory at runtime only.
