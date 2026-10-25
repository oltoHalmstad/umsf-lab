# Stationary building-state node: wiring (ESP32 DevKit)

This follows the functional channels of the Stage-2 bench node (paper Sec. 3.4.3). The bench module
identities (ESP32, MPU6050, BMP280, MQ-2) could not be confirmed from the source frames, so this table
is a candidate build, not a reconstruction. The Stage-2 bench values were not calibrated.

| Module | Module pin | ESP32 pin | Bus / address | Rate (firmware) | Notes |
|---|---|---|---|---|---|
| MPU-6050 (GY-521) | VCC/GND | 3V3/GND | I2C 0x68 (AD0 → GND) | 200 Hz, **±16 g**, DLPF_CFG 2 (≈ 94 Hz) | Impact capture setting. The wearable 25 Hz / ±4 g setting is not an impact specification (paper 3.8.3) |
| | SDA/SCL | GPIO21/GPIO22 | shared I2C 400 kHz | | |
| BMP280 | VCC/GND | 3V3/GND | I2C 0x76 (SDO → GND) or 0x77 | ≈ 25 Hz, P ×16 / T ×2 oversampling, IIR off | IIR off so that 1 s transients are not smoothed away. Check the board is BMP280, not BME280 (chip ID 0x58) |
| | SDA/SCL | GPIO21/GPIO22 | shared | | |
| MQ-2 module | VCC | **5 V** (heater ≈ 150 mA) | – | 10 Hz | Needs a 5 V heater supply; the power bank must deliver the current |
| | AO | GPIO35 (ADC1) **via divider** | – | | AO can reach ≈ 5 V. Use 10 kΩ (AO→pin) + 20 kΩ (pin→GND) to get ≤ 3.3 V. Firmware multiplies by 1.5 and reports the AO voltage in mV, **uncalibrated** |
| | DO | not connected | | | The on-board comparator is not used |
| Analog microphone (MAX4466 / MAX9814 type) | VCC/GND | 3V3/GND | – | 1 kHz sampling, peak-to-peak per 50 ms and per 1 s | OUT → GPIO36 (VP, ADC1). Output must be biased at mid-rail and ≤ 3.3 V |
| PIR (HC-SR501 / AM312 type) | VCC | 5 V (HC-SR501) or 3V3 (AM312) | – | polled at 100 Hz, 30 s hold | OUT → GPIO26. HC-SR501 output is 3.3 V even when powered from 5 V. Check yours |
| SOS button | one side | GPIO27 | – | debounce 30 ms | other side → GND; internal pull-up. Long press 3 s or the operator page resets the latch |
| Status LED / buzzer (optional) | – | GPIO2 / GPIO25 | – | – | Indication only. The node actuates nothing (paper 3.3.5) |

## Notes

- GPIO34–39 are input-only and have no pull-ups. GPIO35/36 are fine for analog inputs. Use ADC1 pins only,
  because ADC2 is unavailable while Wi-Fi/BLE are active.
- Stage 2 was a tabletop assembly that was **not attached to a load-bearing element**. Before a mechanical
  value can mean anything, mount the node, document the attachment, and capture the tilt baseline on the
  local page ("Зафіксувати базове положення", which needs the operator PIN). Without a baseline the node
  sends `attachment_uncertain` and `tilt_delta = null`. A tilt alarm also latches `attachment_uncertain`
  (displaced node).
- MQ-2: the firmware locks out alarms for 180 s after power-up. The datasheet burn-in (24–48 h) is longer
  than this bench preheat. The channel responds to many gases and to humidity and temperature. It is not a
  calibrated gas instrument.
- Soft-AP: the local page is at `http://192.168.4.1` (SSID `UMSF-S01`, WPA2 password from `secrets.h`).
