# BLE gateway: wiring (ESP32 DevKit)

The gateway needs no sensors. It is an ESP32 DevKit powered over USB from a supply whose continuity is
itself under test (paper 3.3.7: "the presence of a power bank ... is not evidence of uninterrupted
operation").

| Item | Connection | Notes |
|---|---|---|
| ESP32 DevKit (4 MB flash) | USB 5 V | Partition `min_spiffs.csv` (large app + LittleFS for certificates) |
| On-board LED GPIO2 | – | not used by the gateway firmware |
| Serial (115200 Bd) | USB | Emits the Stage-1 compatible `RX,...` lines plus `SITEACK`/`ACKR` audit lines. Log it on a separate host |

Radio: one 2.4 GHz radio is shared by BLE (central, up to 3 links, scan window 37/97 slots) and Wi-Fi
(STA to the site network plus AP for the local page). BLE/Wi-Fi coexistence under the intended traffic
must be measured (paper 3.3.7). It is not assumed.

Spare: the cold spare is pre-flashed with its own gateway id and enrollment table. Reassignment is a
manual, documented step, not automatic failover.
