# Test plan

## 1. What has been tested in release 1.0.0

Host unit tests of the portable libraries (`test/host`, g++ 13, `-Wall -Wextra -Werror`, also run under
AddressSanitizer/UBSan during development):

| Area | Tests |
|---|---|
| CRC-16/CCITT-FALSE | known vector "123456789" → 0x29B1 |
| Codec | header layout, little-endian, encode/decode round trip for all six frame types, decode errors (short, length, magic, version, type, CRC) |
| Null sentinels | i16 0x8000, u16 0xFFFF, u32 0xFFFFFFFF, u8 0xFF survive the round trip |
| COMPACT | 20-byte layout, CRC, corruption detection |
| Fragmentation | MTU 247 single fragment, MTU 23 out-of-order with duplicate, 2 s timeout, 512 B limit (overflow rejected, exactly 512 accepted), 3 concurrent messages + eviction of the oldest, malformed headers |
| Ring buffer | cumulative ACK per (source, boot), wrong boot ignored, idempotent ACK, oldest eviction + one-time report, priority order (urgent → event → telemetry), stale requeue, reconnect resend, 3-source gateway case, urgent events spared from eviction |
| Text line | paper example reproduced exactly; null → empty field; station and event formats |
| JSON | schema 1.0 / st-1.0 / ev-1.0 keys, scaled values, null times when unsynchronised, ISO-8601, `frame_hex`, gateway-generated event identity |
| Time map | minimum-offset estimate, resend exclusion, unknown boot |
| Features | clean PPG/IMU/temperature window; no contact; saturation; sample gap; motion artifact; temperature error; synthetic HR flagged; UNVALIDATED pulse estimator on a 72 bpm synthetic signal |
| Detectors | impact excursion (3 g), tilt 63° vs baseline (+ attachment_uncertain latch), gas preheat lockout + hysteresis + frozen baseline, pressure transient vs slow drift, loud sound, composite `possible_impact_local` (impact+loud, impact+pressure, not 3 s apart), PIR hold, unknown channels → null |
| Button | contact bounce ignored, latch, long-press reset only when already latched, operator reset |
| Gateway logic | link loss after 2 s staleness, restore with outage value, disconnect, site-ACK parser (valid and invalid), allowlist |
| Vectors | `test_vectors.json` decoded by an independent Python implementation (`tools/verify_vectors.py`) |

**Not tested:** none of the three firmware images has been compiled for ESP32 or run on hardware.

## 2. Mapping to the prospective scenarios (paper Table A.1, protocol v0.2 EN)

All main scenarios use 12 physical nodes and 4 active gateways, with payload origin
`synthetic_payload_physical_transport`. Enable `UMSF_CONFIG_SYNTHETIC_HR` and set
`UMSF_DATA_ORIGIN` accordingly. Use three replicate blocks of S0–S5 in an order randomised with seed
20260909, saved before evaluation.

| Scenario | Intervention | Firmware behaviour exercised | Evidence the firmware provides |
|---|---|---|---|
| S0 · 60 min | normal operation | 10 s feature records, BLE → gateway → MQTT QoS 1 → COMMIT → ACK relay | `SLOT` lines (node), `RX` lines (gateway), `SITEACK`/`ACKR` (gateway), `ACKW` (node) |
| S1 · 60 min | Wi-Fi load at 70 % of baseline goodput | BLE/Wi-Fi coexistence, gateway buffer, republish | gateway status: `buffered`, `published_total`, `rx_dropped`, `wifi_rssi_dbm`; node STATUS `rssi_neg` |
| S2 · 90 min | 30 min VPN outage | local path unaffected (gateway talks to the local broker) | as S0. Replication is P1's job |
| S3 · 60 min | gateway power off 4 min at minute 20 | node buffer (32 ≥ 30) holds 4 min = 24 records; link_loss/restored; resend on reconnect | node `EVICT` (should stay absent), `buffered_records`, gateway `link_loss`/`link_restored` events |
| S4 · 60 min | site receiver stopped 10 min | gateway buffer 48 + node buffer 32 → expected **evictions** (10 min = 60 records/node); all slots accounted | `EVICT,…,last_seq` lines, `buffer_eviction` events, `evicted_total` in STATUS and gateway status |
| S5 · 60 min | collector killed 60 s; host power cut 60 s | ACK only after COMMIT, so no pre-failure ACKed ID may be lost | `ACKW` witness lines (node serial) compared with recovered origin records |
| S6 (supplemental) | 8 challenge classes × 20 × 3 | exact duplicates (resend), conflicting payloads, unknown devices (allowlist), incomplete fragments (2 s timeout), oversized features (> 512 B rejected), delayed first arrivals (timestamps preserved, `received_at` separate) | gateway counters `crc_errors`, `identity_mismatch`, reassembler counters; P1 manifest |
| Button check | 120 presses | help_request urgent priority, ahead of telemetry | node and gateway `E,…,help_request` lines with timestamps |

## 3. Firmware counters and logs needed by the protocol

| Requirement (A.2/A.4) | Provided by | Format |
|---|---|---|
| Independent **planned-slot ledger** | node serial, one line per generated feature record | `SLOT,<device>,<boot>,<seq>,<node_ms>,<window_index>` |
| **Eviction log** (RAM-buffer loss explicit) | node and gateway | `EVICT,<device>,<boot>,<count>,last_seq=<n>` + `buffer_eviction` EVENT + `evicted_total` |
| **ACK witness** (application ACKs actually received by nodes) | node serial | `ACKW,<device>,<boot>,<ack_up_to_seq>,<node_ms>,<released>` |
| Site ACK received / relayed | gateway serial | `SITEACK,<device>,<boot>,<seq>,released=<n>` and `ACKR,<device>,<boot>,<seq>` |
| Reboot visibility | all | `boot_id` increments; banner line `# UMSF ... boot <n>` |
| Config freeze | node serial | `CFG,…` line on every accepted CONFIG; `fw_build` and `rule_version` in every record |
| Sample-loss counters | records | `n_ppg_samples`, `n_imu_samples`, `sample_gap` artifact flag |

Capture the serial lines with a logger that is **outside the host subjected to failure** (A.2), for
example a separate Raspberry Pi with USB serial and its own clock-qualified time stamps.

## 4. Before the first hardware run

1. `pio run` for all three environments. Fix any library API drift (see README "Assumed library versions").
2. Bench-check one node + one gateway against `hardware/COMMISSIONING_CHECKLIST.md`.
3. Run `pio test -e native` and `make -C test/host` and record the results with the firmware hashes.
