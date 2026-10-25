# Communication protocol

All values are little-endian (ESP32). Structures are `__attribute__((packed))`. The gateway
accepts a packet only if both the magic number **and** the exact length match.

## 1. ESP-NOW transport

* Broadcast address `FF:FF:FF:FF:FF:FF`, Wi-Fi channel `ESPNOW_CH = 1`, no encryption.
* A node sends once per second (`SEND_PERIOD_MS`), and also immediately when its flag word
  changes, at most once per 100 ms (`MIN_GAP_MS`, wearable).
* `seq` grows by 1 for every packet. The gateway counts gaps in `seq` as lost packets.
* `node` is a 3-character ID followed by a NUL byte (`"W01"`, `"A01"`, ...).

## 2. Wearable packet: `WearPacket` (40 bytes, magic `0x57534D55` = "UMSW")

| Offset | Type      | Field      | Meaning |
|-------:|-----------|------------|---------|
| 0  | uint32 | `magic`    | `0x57534D55` |
| 4  | char[4]| `node`     | e.g. `"W01"` |
| 8  | uint32 | `seq`      | packet counter since boot |
| 12 | uint32 | `uptimeS`  | node uptime, s |
| 16 | uint16 | `flags`    | see below |
| 18 | uint8  | `sensors`  | detected sensors: bit0 PPG (MAX30102), bit1 IMU (MPU-6050), bit2 TEMP (DS18B20) |
| 19 | uint8  | `hrBpm`    | heart rate, bpm; 0 = no estimate |
| 20 | uint8  | `beats`    | number of intervals in the HR median (0–8) |
| 21 | uint8  | `led`      | MAX30102 LED current register |
| 22 | float  | `pi`       | perfusion index, % |
| 26 | uint32 | `irRaw`    | last raw IR sample (18-bit) |
| 30 | float  | `tempC`    | skin temperature, °C; NaN if not available |
| 34 | uint16 | `motionMg` | peak motion metric since the previous packet, mg |
| 36 | float  | `peakG`    | peak \|a\| since the previous packet, g |

Wearable `flags`:

| Bit | Name         | Set when |
|----:|--------------|----------|
| 0 | `W_FINGER`   | IR level indicates a finger on the sensor |
| 1 | `W_HR_VALID` | `hrBpm` is a valid estimate |
| 2 | `W_HR_SYNTH` | `hrBpm` is **simulated** (`HR_SYNTHETIC = 1`) |
| 3 | `W_MOTION`   | acceleration change > 60 mg within the last 1 s |
| 4 | `W_IMPACT`   | \|a\| > 3 g within the last 30 s |
| 5 | `W_SOS`      | SOS button pressed within the last 30 s |
| 8 | `W_HR_ABN`   | set **by the gateway**: valid HR outside `HR_LOW`–`HR_HIGH` |

## 3. Fixed-node packet: `NodePacket` (55 bytes, magic `0x46534D55` = "UMSF")

| Offset | Type    | Field         | Meaning |
|-------:|---------|---------------|---------|
| 0  | uint32  | `magic`       | `0x46534D55` |
| 4  | char[4] | `node`        | e.g. `"A01"` |
| 8  | uint32  | `seq`         | packet counter |
| 12 | uint32  | `uptimeS`     | node uptime, s |
| 16 | uint16  | `flags`       | see below |
| 18 | uint8   | `sensors`     | bit0 MPU, bit1 BMP (pressure), bit2 DS18B20, bit3 MIC, bit4 MQ (gas), bit5 PIR |
| 19 | float   | `peakDev`     | peak acceleration deviation, g |
| 23 | float   | `tiltDeg`     | tilt from the initial position, ° |
| 27 | uint16  | `sndPeak`     | sound peak, ADC units |
| 29 | float   | `mqV`         | gas sensor voltage, V |
| 33 | float   | `mqBase`      | gas sensor baseline, V |
| 37 | float   | `tempC`       | temperature, °C |
| 41 | float   | `tempBase`    | temperature baseline, °C |
| 45 | float   | `pressHpa`    | air pressure, hPa |
| 49 | float   | `pressJumpPa` | short-term pressure change, Pa |
| 53 | uint16  | `motionAgoS`  | seconds since the last PIR motion; 65535 = none since boot |

Fixed-node `flags` (bits 0–8 are events; the gateway logs a rising edge of each):

| Bit | Name         | Dashboard label | Latched |
|----:|--------------|-----------------|:------:|
| 0 | `F_SHOCK`    | Structural shock | yes |
| 1 | `F_TILT`     | Node displaced   | yes |
| 2 | `F_LOUD`     | Loud sound       | yes |
| 3 | `F_PRESSURE` | Pressure jump    | yes |
| 4 | `F_GAS`      | Smoke or gas     | yes |
| 5 | `F_HEAT`     | Temperature rise | yes |
| 6 | `F_MOTION`   | Movement in zone | no  |
| 7 | `F_VOICE`    | Voice or knocking| no  |
| 8 | `F_SOS`      | SOS at fixed node| yes |
| 9 | `F_MQ_WARM`  | gas sensor warming up (status) | — |
| 10| `PIR_WARM`   | PIR calibrating (status, used by the dashboard) | — |

## 4. Gateway HTTP interface (http://192.168.4.1)

| Method | Path     | Response |
|--------|----------|----------|
| GET    | `/`      | dashboard HTML (`interface/dashboard.html`) |
| GET    | `/api`   | JSON state, polled by the dashboard once per second |
| POST   | `/reset` | clears latched alarms, maxima and the event log; logs event 22; returns `{"ok":true}` |

`/api` structure (abbreviated):

```json
{
  "gw": "AG1", "up": 240000, "hrLo": 45, "hrHi": 130,
  "nodes":  [{"id":"A01","zone":"Workshop 1 · north wing","online":true,"age":120,
              "pk":187,"lost":0,"upS":180,"flags":64,"latched":0,"sensors":63,
              "pg":0.03,"tilt":0.1,"snd":128,"mq":0.93,"mqb":1.01,"t":20.4,"tb":20.3,
              "p":1021.8,"pj":4,"mot":0,"mx":{"g":0.05,"pj":6,"t":20.5,"mq":1.02}}],
  "people": [{"id":"W01","name":"Responder 1","online":true,"age":300,"pk":215,"lost":1,
              "upS":220,"flags":0,"latched":0,"sensors":7,"hr":0,"beats":0,"pi":0.00,
              "t":20.4,"mot":12,"mx":{"g":0.0,"hrMin":0,"hrMax":0}}],
  "events": [{"ago":108000,"n":"AG1","k":22,"v":null}]
}
```

`age` and `ago` are milliseconds before the response. `latched` is the OR of all alarm flags
since the last reset. `mx` holds maxima since the last reset. Unavailable numbers are `null`.

Event codes: 0–8 fixed-node flag bits (table above), 20 node online, 21 link lost
(no packet for 5 s), 22 alarms reset by operator, 30 SOS from a person, 31 impact or fall,
32 heart rate out of range.

## 5. Serial output of the gateway (115200 baud)

```
EVENT,<node>,<kind>,<value>
W,<id>,<seq>,<node_uptime_s>,<hr_bpm>,<flags_hex>,<temp_c>,<motion_mg>,<peak_g>,<pi_pct>
```

`EVENT` lines use the event codes above (`value` = `nan` if not applicable). There is one
`W` line per received wearable packet, for logging measurement sessions.
