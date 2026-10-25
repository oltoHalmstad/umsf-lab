# Personnel node: wiring (ESP32 DevKit, classic ESP32-WROOM-32)

This is a candidate configuration from Table 4 of the manuscript. These are settings to check, not
measured performance. Check the actual breakout schematics, regulators and signal levels before you wire
anything (paper Sec. 3.3.6, A.2).

| Module | Module pin | ESP32 pin | Bus / address | Rate (firmware) | Notes |
|---|---|---|---|---|---|
| MAX30102 breakout | VIN | 3V3 (or 5V, see below) | I2C 0x57 | red + IR at 100 Hz each | ledMode 2, pulse width 411 µs, ADC range 16384, LED ≈ 6.4 mA |
| | SDA | GPIO21 | shared I2C, 400 kHz | | |
| | SCL | GPIO22 | | | |
| | GND | GND | | | INT pin not used (the firmware polls the FIFO) |
| MPU-6050 (GY-521) | VCC | 3V3 | I2C 0x68 (AD0 → GND) | 25 Hz, ±4 g, ±500 °/s, DLPF ≈ 20 Hz | AD0 high would give 0x69; firmware expects 0x68 |
| | SDA/SCL | GPIO21/22 | shared | | |
| DS18B20 | DQ | GPIO4 | 1-Wire | 1 conversion/s, 12 bit | **4.7 kΩ pull-up DQ → 3.3 V** if the probe/board has none |
| | VDD / GND | 3V3 / GND | | | Use normal (not parasite) power |
| Help button | one side | GPIO27 | – | debounce 30 ms | other side → GND; internal pull-up enabled; hold 3 s while latched = local reset |
| Grove GSR (optional) | SIG | GPIO34 (ADC1) | – | 10 Hz | Build with `-DUMSF_HAS_GSR=1`. ADC1 only (ADC2 is unusable with radio on). Firmware stores millivolts, **not** conductance |
| Status LED | – | GPIO2 (on-board) | – | – | steady = BLE ready; blinking = help request latched |

## Supply and levels

- **The MAX30102 chip and a MAX30102 breakout have different supply needs.** The bare chip needs 1.8 V
  (logic and core) and 3.3 V (LED driver, nominally 5 V tolerant per breakout). Common breakouts have
  on-board 1.8 V and 3.3 V regulators and level shifting. Some cheap breakouts pull I2C up to 1.8 V, and
  their pull-ups may need rework before the ESP32 sees valid logic levels. Measure the SDA/SCL idle voltage:
  it must be 3.3 V ± 10 %.
- All ESP32 GPIOs are 3.3 V only. Do not feed 5 V into GPIO21/22/4/27/34.
- The I2C bus needs exactly one set of pull-ups (2.2–4.7 kΩ to 3.3 V). Most breakouts already have them.
  Several boards in parallel can make the effective pull-up too strong; remove the extra ones.
- GPIO34 is input-only and has no internal pull-up. That is fine for the GSR analog output.
- Power: the worn assembly runs on its own battery or power bank with protected contacts. **Charge it
  off-body** (paper Sec. 3.3.6). No battery-sense divider is wired, so `battery_pct` is sent as null.
- Electrode-based extensions (ECG/EDA) need an isolated measurement arrangement. They are not part of this
  basic channel set.

## Placement caveats

- The finger-contact PPG is for an initial laboratory session. Wrist or continuous work placement needs
  its own optical and ergonomic assessment.
- DS18B20 gives the temperature at its contact site, and the firmware labels it that way. It is not core
  body temperature or ambient air. Component accuracy is not the same as the accuracy of the assembled
  skin measurement.
