# Bill of materials (candidate research configuration, no prices)

Procurement estimates in the source materials are not performance evidence and are not used here
(paper 3.3.6).

## Per personnel node

| Qty | Item | Notes |
|---|---|---|
| 1 | ESP32 DevKit V1 (ESP32-WROOM-32, 4 MB) | classic ESP32 (BLE 4.2 + LE Secure Connections in NimBLE) |
| 1 | MAX30102 breakout with on-board regulators | check the I2C pull-up voltage (see wiring) |
| 1 | DS18B20 (TO-92 or waterproof probe) | + 4.7 kΩ resistor if not on the board |
| 1 | MPU-6050 breakout (GY-521) | AD0 tied low |
| 1 | Momentary push button | help request, GPIO27 |
| 0–1 | Grove GSR module | optional, ADC1 GPIO34 |
| 1 | Power bank or Li-ion pack with protection | charged off-body |
| 1 | Enclosure (e.g. D110 type, as in protocol A.1) + protected contacts | bench or belt prototype, not a wrist device |
| – | Breadboard / perfboard, jumper wires | |

## Per stationary node

| Qty | Item | Notes |
|---|---|---|
| 1 | ESP32 DevKit V1 | |
| 1 | MPU-6050 breakout | ±16 g impact setting |
| 1 | BMP280 breakout (I2C) | |
| 1 | MQ-2 gas sensor module | 5 V heater, AO through divider |
| 1+1 | 10 kΩ + 20 kΩ resistors | MQ-2 AO divider |
| 1 | Analog microphone module (MAX4466 or MAX9814) | |
| 1 | PIR module (HC-SR501 or AM312) | |
| 1 | Push button | SOS, GPIO27 |
| 0–1 | LED / buzzer | indication only |
| 1 | 5 V supply able to drive the MQ-2 heater (≥ 500 mA total) | |
| 1 | Rigid mounting hardware for attachment to the structure | attachment must be documented |

## Per gateway

| Qty | Item | Notes |
|---|---|---|
| 1 | ESP32 DevKit V1 | 3 node links per gateway |
| 1 | USB supply on the protected power path | continuity must be measured |

## Pilot quantities (paper 3.3.6, A.1)

12 personnel nodes (6 per site), 4 active gateways + 1 cold spare, 2 local hosts (2 vCPU, 4 GB RAM,
40 GB SSD each) running broker, collector and database. Stationary nodes are an optional extension. They
are never counted as workers.
