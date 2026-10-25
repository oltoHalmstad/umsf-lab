# Architecture

## Deployment (proposed two-site pilot, paper Sec. 3.3.6–3.3.7, Fig. 3, A.1)

```
 Site A (UMSF cyber range, HEALTH GW segment)        Site B
 ┌───────────────────────────────────────────┐        ┌───────────────────────────────────────────┐
 │ A01 A02 A03   A04 A05 A06   (+ S01 ...)    │        │ B01 B02 B03   B04 B05 B06   (+ S.. ...)    │
 │   \  |  /       \  |  /    personnel nodes │        │   \  |  /       \  |  /                    │
 │   BLE LE SC     BLE LE SC  (3 per gateway) │        │   BLE LE SC     BLE LE SC                  │
 │  ┌──────┐      ┌──────┐                    │        │  ┌──────┐      ┌──────┐    [cold spare]    │
 │  │ AG1  │      │ AG2  │   ESP32 gateways   │        │  │ BG1  │      │ BG2  │                    │
 │  └──┬───┘      └──┬───┘   (BLE central +   │        │  └──┬───┘      └──┬───┘                    │
 │     │ Wi-Fi STA, MQTT/TLS mutual auth, QoS1│        │     │             │                        │
 │  ┌──▼─────────────▼──┐                     │  VPN   │  ┌──▼─────────────▼──┐                     │
 │  │ site broker A     │◄────────────────────┼────────┼─►│ site broker B     │                     │
 │  │ site agent (P1)   │ durable COMMIT,     │ repli- │  │ site agent (P1)   │                     │
 │  │ SQLite WAL, FULL  │ application ACK     │ cation │  │ SQLite WAL, FULL  │                     │
 │  └───────────────────┘                     │        │  └───────────────────┘                     │
 └───────────────────────────────────────────┘        └───────────────────────────────────────────┘
   12 personnel nodes → 4 active gateways (+1 cold spare) → 2 site brokers / agents
```

Stationary building-state nodes (S..) can occupy gateway slots. They are separate source classes and
are **never counted as workers**.

## What this repository implements (P2)

| Component | Code | Status in 1.0.0 |
|---|---|---|
| Frame codec, CRC, null sentinels, COMPACT packet | `lib/umsf_proto/umsf_proto.[ch]` | host-tested |
| Fragmentation / reassembly (512 B, 2 s, 3 concurrent) | `lib/umsf_proto/umsf_frag.[ch]` | host-tested |
| Stage-1 text log line | `lib/umsf_proto/umsf_text.[ch]` | host-tested (paper line reproduced exactly) |
| MQTT JSON records (1.0 / st-1.0 / ev-1.0), time mapping | `lib/umsf_proto/umsf_json.[ch]` | host-tested |
| Unacked-record RAM buffer, cumulative ACK, eviction | `lib/umsf_buffer/umsf_buffer.h` | host-tested |
| Feature extraction and local detectors, button | `lib/umsf_features/` | host-tested on synthetic signals |
| Link supervision, site-ACK parser, allowlist | `lib/umsf_gwcore/umsf_gwcore.h` | host-tested |
| Personnel node firmware | `src/personnel_node/` + `src/node_common/` | **uncompiled, untested on hardware** |
| Stationary node firmware + local page | `src/stationary_node/` | **uncompiled, untested on hardware** |
| Gateway firmware + local page | `src/gateway/` | **uncompiled, untested on hardware** |

## Data path

```
 sensors ──► window features (10 s personnel / 1 s stationary) ──► frame (header+payload+CRC)
        ──► node RAM buffer (>=30, RAM only) ──► BLE notify with 4-byte fragment header
        ──► gateway: reassembly (512 B / 2 s) ─► CRC ─► identity binding (enrolled id == frame id)
        ──► gateway RAM buffer (>=18, events first) ──► JSON + frame_hex ──► MQTT QoS 1 over mTLS
        ──► site agent COMMIT ──► umsf/<site>/ack/<gw> {"device_id","boot_id","ack_up_to_seq"}
        ──► gateway releases its copy, writes ACK frame to node ACK characteristic
        ──► node releases its copy (ACK witness line ACKW on node serial)
```

**Merging nodes into one Bluetooth channel.** A gateway holds up to three BLE links. It multiplexes all
notifications into one ordered uplink stream. Each record keeps its source identity
`(device_id, boot_id, sequence)`, and the gateway also binds that identity to the enrolled, authenticated
link: a frame whose `device_id` or `source_class` differs from the enrolled peer is dropped and counted
(`identity_mismatch`). Ordering is priority-first: urgent events (SOS, help request), then other
events, then telemetry, oldest first within a class. The serial and web logs show the merged stream as
Stage-1 compatible `RX,...` lines.

**Two acknowledgements.** The MQTT PUBACK (QoS 1) only tells the gateway that the broker accepted the
message, so the gateway does not republish it immediately. It does **not** release the record. Release
happens only on the site agent's application ACK after durable COMMIT (paper 3.3.7, A.2). Records
without an application ACK are republished after 60 s and retransmitted by the node after 60 s. The site
agent deduplicates by identity.

**Sequence numbers.** Per node and boot session, telemetry and events share one `sequence` counter
starting at 1. This makes the cumulative ACK valid across both. A STATUS frame is a snapshot: it reuses
the last allocated sequence and is never buffered. Gateway-generated events (link_loss, link_restored,
buffer_eviction) carry the gateway's own identity (`device_id` = gateway id, gateway boot and
sequence). The node they concern is given in the JSON `device_id` and `provenance.source`, and the site
agent acknowledges them with `device_id` = gateway id.

**Cumulative ACK caveat.** `ack_up_to_seq` releases every record of that boot with `sequence ≤ N`. The
site agent must therefore only issue N when all of 1..N have been committed, or are explicitly accounted
as missing. Otherwise a gap would be released silently.

## Time

- Nodes have no wall clock. `node_time_ms` is uptime at window end or at the event.
- The gateway SNTP-synchronises (site NTP server first) and maps node time per node and boot:
  `offset = rx_local - node_ms`, minimum over live first transmissions (resends are excluded because they
  would bias the offset). The estimate is re-anchored every 10 min against drift.
- `time_uncertainty_s` = observed offset spread + 0.25 s latency allowance + 100 ppm drift allowance
  + SNTP allowance (0.1 s + 50 ppm since last sync). These allowances are **assumptions to be replaced by
  measured clock-qualification values** (A.2: combined timing uncertainty ≤ 0.5 s for latency acceptance).
- If the gateway clock is not synchronised, the JSON builder emits `measured_at`, `received_at`
  (`observed_at`, `reported_at` for events) and `time_uncertainty_s` as `null`. Times are never guessed.
  `node_time_ms` stays recoverable from `frame_hex`. In the gateway firmware, records simply wait in the
  RAM buffer until SNTP sync, because TLS certificate validation needs a valid clock anyway.
- Times are stored in UTC (`Z`). Europe/Kyiv is a display concern of P1/P3.

## Link loss and staleness

- Stationary nodes send COMPACT every 200 ms. With no frame for > 2 s the gateway marks the node stale
  and emits `link_loss` (value = seconds since last frame).
- Personnel nodes: `link_loss` on BLE disconnect, or when no frame arrives for > 25 s (2.5 × the 10 s
  interval; an implementation choice).
- When frames resume the gateway emits `link_restored` (value = outage seconds).
- Link loss makes current evidence `unknown`. The firmware never labels silence as collapse or casualty.

## Buffers (RAM only)

| Buffer | Capacity | Paper minimum |
|---|---|---|
| personnel node | 32 records | ≥ 30 (5 min at 10 s) |
| stationary node | 64 records | not specified (1 s records → ≈ 60 s) |
| gateway | 48 records | ≥ 18 (60 s across 3 nodes) |

When a buffer is full it evicts the oldest record of the lowest priority, so urgent events go last. It
logs an `EVICT` line and emits one aggregated `buffer_eviction` event per 60 s. Contents are lost on
reset or power loss (stated limitation, paper 3.3.7).

## Not implemented (scope boundary)

- Target COSE/CBOR signed and encrypted record profile (paper 3.3.2): not implemented. Hop-by-hop pilot only.
- Patent No. 38233 keystream method: not implemented (paper 3.3.3).
- Validated pulse rate, SpO2, HRV, posture or fall detection: not implemented. HR is null by default.
- Calibrated gas, structural or impact measurement: not implemented. All thresholds are uncalibrated defaults.
- Non-volatile event storage on nodes: not implemented (RAM only).
- Any actuation (process stop, ventilation, locks, power): none. The firmware only reports.
