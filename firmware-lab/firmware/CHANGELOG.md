# Changelog

## 1.0.0 — 2026-10-14

First public release, for the Zenodo deposit.

- `lib/umsf_proto` (C99): protocol v1.0 codec for all six frame types, CRC-16/CCITT-FALSE, null
  sentinels, 20-byte COMPACT packet, fragmentation and reassembly (512 B limit, 2 s timeout, three
  concurrent messages per link), Stage-1 text log line, JSON records (1.0 / st-1.0 / ev-1.0, `frame_hex`)
  and node-time mapping.
- `lib/umsf_buffer`: RAM buffer of unacknowledged records with cumulative application ACK,
  priority-aware oldest eviction and an explicit eviction report.
- `lib/umsf_features`: PPG/IMU window features, artifact flags, quality heuristic, an UNVALIDATED pulse
  estimator (off by default) and the synthetic HR test field; stationary detectors (impact, tilt vs.
  baseline, pressure transient, gas with preheat and hysteresis, loud sound, PIR hold, composite
  `possible_impact_local`); debounced SOS button with latch and local reset.
- `lib/umsf_gwcore`: link supervision (`link_loss` / `link_restored`), site-agent ACK parser, enrollment allowlist.
- Firmware sources for the personnel node, the stationary node (with a Ukrainian local page) and the BLE
  gateway (NimBLE central, MQTT/TLS via espMqttClient, status page with JSON polling and a stale indicator).
- Host unit tests (43 cases), PlatformIO `native` test environment, `test_vectors.json` and an
  independent Python vector checker.
- Hardware wiring tables, BOM, commissioning checklist; architecture, protocol, security and test-plan documents.

Known limitations: the ESP32 images are uncompiled and untested on hardware; TLS 1.2 only on the pinned
core; RAM-only buffers; thresholds are uncalibrated.
