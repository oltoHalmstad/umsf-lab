"""UMSF incident dataset toolkit.

Collection, validation, storage, summarisation and export of physiological,
building-state (stationary node), gas-channel, presence and incident-event
records following the shared UMSF protocol specification v1.0, plus
deterministic synthetic generators that reproduce the documented software
experiments of the manuscript "Evidence-Aware Multisensor Monitoring for
Critical Infrastructure Incident Support" (Torstensson et al., 2026).

Research software only: not a medical device, not a certified safety system,
and it never attributes a missile strike from local sensor data.
"""

__version__ = "1.0.0"
PROTOCOL_VERSION = "1.0"
SCHEMA_PHYSIO = "1.0"
SCHEMA_STATION = "st-1.0"
SCHEMA_EVENT = "ev-1.0"
