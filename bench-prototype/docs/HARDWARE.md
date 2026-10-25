# Hardware

All devices use an ESP32 DevKit board (PlatformIO board `esp32dev`, Arduino framework) and
are powered over USB. The setup is a breadboard bench prototype with no enclosure,
battery management or calibration.

## Gateway AG1

ESP32 DevKit only, with no sensors. It powers its Wi-Fi access point (`UMSF_AG1`,
channel 1) and receives ESP-NOW on the same channel.

## Wearable node W01–W03

| Component | Function | Interface | ESP32 pin |
|-----------|----------|-----------|-----------|
| MAX30102 | finger PPG (IR channel used for heart rate) | I²C, address 0x57 | SDA 21, SCL 22 |
| MPU-6050 | acceleration: motion gating, impact / fall (±8 g range) | I²C, address 0x68 | SDA 21, SCL 22 |
| DS18B20  | skin temperature (12-bit) | 1-Wire (4.7 kΩ pull-up to 3.3 V) | GPIO 4 |
| Push button | SOS, active low (internal pull-up), to GND | digital input | GPIO 27 |
| On-board LED | 20 ms blink per transmitted packet | digital output | GPIO 2 |

Sensors are detected at start-up. A missing sensor clears its bit in the `sensors`
field, and the dashboard then shows "—" or "NO SENSOR" instead of a value.

MAX30102 configuration: 400 samples/s internal with 4× averaging (100 samples/s to the
FIFO), pulse width 411 µs, ADC range 4096 nA, LED current adjusted automatically
between registers 0x08 and 0x7F.

## Fixed node A01–A03

Channels as reported by the `sensors` bitmap and shown on the dashboard:
MPU-6050 (shock, tilt), barometric pressure sensor (BMP series), DS18B20 temperature,
analog microphone (sound level, voice/knock detection), MQ-series gas sensor (smoke/gas,
~1.5 min warm-up), PIR motion sensor, SOS button. The firmware source and pin assignment
of this node are not part of this archive (see `firmware/fixed_node/README.md`).
