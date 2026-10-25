# Architecture

```
 BLE nodes ──► gateway ──► MQTT/TLS ──┐                      ┌──► exports (CSV/JSONL, summaries,
 (frames §2)  (lines §3)  (JSON §5)   │                      │     quarantine log, SHA-256 manifest)
                                      ▼                      │
   adapters/ble_direct ─┐   frames.py (decode, CRC,   store.py (SQLite WAL, FULL;   summaries.py
   adapters/serial ─────┼─► reassembly, line parser) ─► dedup, conflict quarantine) ─► (roster-based,
   adapters/mqtt ───────┤   validate.py (bounded                ▲                       cutoffs, Kyiv)
   JSONL files ─────────┘   parse + JSON Schema)                │ application ACK only after COMMIT
                                                                 └── adapters (ACK to node/gateway)
 synth/ (Study A, Study B, bench, incident) ──► JSONL ──► same pipeline ──► reproduce.py (paper check)
```

| Module | Responsibility | Paper reference |
|---|---|---|
| `frames.py` | §2 frame encoder/decoder, CRC-16/CCITT-FALSE, null sentinels, 512 B / 2 s fragment reassembly, 20 B COMPACT packet, §3 gateway-line parser, frame/line → §5 JSON, test-vector checker | Sec. 3.3.7, 3.4.2, 3.4.4 |
| `validate.py` + `schemas/` | Bounded strict JSON parsing (size, depth, duplicate keys, NaN/Infinity), JSON-Schema subset interpreter, `measured` origin gate, strike-source rule | Sec. 3.3.4, 3.3.8, Table 12 |
| `store.py` | SQLite WAL + `synchronous=FULL`; identity key; idempotent redelivery; conflict quarantine of the whole identity with audit; rejects log; counters | Sec. 3.3.4, 3.3.8 |
| `summaries.py` | Roster-based 5-min summaries (180 / 36 expected for 6 devices), device coverage vs sample completeness vs channel counts, arrival cutoffs, current state, station/zone state with staleness and `unknown` on link loss | Sec. 3.3.8, 3.4.4, 3.8 |
| `export.py` | Daily CSV/JSONL, summaries, quarantine/rejects logs, manifest (SHA-256, versions, counters, timing rules), storage sizing | Sec. 3.3.8, 4.5 |
| `selfcheck.py` | Ten functional self-checks of Study B | Table 12 |
| `synth/study_a.py`, `synth/protection.py` | Study A generator, restricted directional detector, zone-minute evaluation; optional Ed25519 + AES-GCM host-side demo | Sec. 3.6, 4.4, Table 11 |
| `synth/study_b.py` | Study B challenge stream and end-to-end run | Sec. 4.5, Table 12 |
| `synth/bench.py` | Stage-1 transcription (Table 13); Stage-2 synthetic re-enactment (Table 6) | Sec. 3.4, 4.6, 4.7 |
| `synth/incident.py` | Post-impact synthetic incident dataset for P3; Table 16 enumeration | Sec. 3.8, 3.9, 4.9 |
| `adapters/` | Serial/stdin gateway lines, MQTT/TLS mutual-auth ingest, BLE central (bench) | Sec. 3.3.7, A.2 |
| `reproduce.py`, `cli.py` | Paper comparison table; command line | — |

## Design decisions (implementation choices, not paper results)

* **Immutable payload** for conflict detection = all record fields except `received_at`,
  `reported_at` and `gateway_id` (transport metadata may differ between redeliveries).
* **Window alignment**: UTC epoch multiples of 300 s. Cutoff = window end (grace 0 s) unless a
  fixed report cutoff is given; the fresh horizon is the last 60 s before `min(window_end, cutoff)`.
* **Good quality** in summaries: `quality ≥ 0.6` (Study A eligibility uses `≥ 0.8`).
* **SpO2 from frames** is emitted only when the `SPO2_VALIDATED` flag is set; otherwise `null`.
* **Clock mapping**: `measured_at` is derived from a qualified boot epoch when supplied; otherwise
  the receive time is used with `time_uncertainty_s = null` (age cannot be bounded). Live adapters
  estimate the boot epoch from the earliest arrival; such estimates stay unqualified.
* **Application ACK** is cumulative over the per-boot sequence space and is sent only after the
  SQLite COMMIT returns; MQTT QoS 1 broker acknowledgement never authorises deletion.
* **No actuation**: nothing in this package switches power, ventilation, locks or processes.

## Trust boundaries

The CRC detects corruption only. The `data_origin` label is not cryptographic proof. The optional
Ed25519/AES-GCM code is a host-side demonstration with deterministic demo keys, not key management.
BLE security (LE Secure Connections, bonding, passkey) and broker authorization are configured on
the devices and broker; this package only consumes their outputs.
