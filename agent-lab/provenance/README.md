# Provenance

The uploaded `umsf-incident-ai-agent-v1.0.0.zip` is retained unchanged here. Its individual files are embedded in the notebook and extracted under `umsf-incident-ai-agent/`.

The P1 incident fixture is copied from the user's earlier `umsf-incident-colab-v1.1.0` companion project,under `umsf-incident-dataset/data/incident`,with its MIT license and citation metadata. It supplies the six sibling-dataset tests expected by the original agent. It is synthetic and is not used as an observed field dataset.

`source_sha256.json` inventories all original-agent and P1 fixture files included in the notebook. It is checked before and after execution. New notebook code is contained in the readable code cells and in the runtime module `notebook/umsf_ai_lab.py` (written by the notebook); build, execution and packaging helpers are in `scripts/`. The embedded payload is an xz-compressed tar in Base85 text. Original algorithm source is unchanged.
