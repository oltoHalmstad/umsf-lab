// umsf_hw.h - board pins (paper Table 4 / Stage 2), GATT UUIDs (protocol 1) and NVS helpers.
// Arduino-ESP32 2.0.x. Hardware glue: UNTESTED on hardware and uncompiled in release 1.0.0.
#pragma once
#include <Arduino.h>
#include <Preferences.h>

#ifndef UMSF_FW_BUILD
#define UMSF_FW_BUILD 1
#endif

namespace pins {
// shared I2C bus (MAX30102 0x57, MPU6050 0x68 with AD0 low, BMP280 0x76/0x77)
constexpr int I2C_SDA = 21;
constexpr int I2C_SCL = 22;
constexpr int DS18B20 = 4;        // 1-Wire, 4.7 kOhm pull-up to 3.3 V
constexpr int BUTTON = 27;        // help / SOS button to GND, internal pull-up + software debounce
constexpr int GSR = 34;           // optional Grove GSR, ADC1 (usable with Wi-Fi/BLE active)
constexpr int MQ2 = 35;           // stationary: MQ-2 AO through divider, ADC1
constexpr int MIC = 36;           // stationary: analog microphone module (VP), ADC1
constexpr int PIR = 26;           // stationary: PIR digital output (3.3 V level)
constexpr int STATUS_LED = 2;     // DevKit on-board LED
constexpr int BUZZER = 25;        // optional local buzzer (indication only, no actuation)
}  // namespace pins

namespace uuids {
constexpr const char *SERVICE = "6e5a0001-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *TELEMETRY = "6e5a0002-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *EVENT = "6e5a0003-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *ACK = "6e5a0004-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *STATUS = "6e5a0005-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *CONFIG = "6e5a0006-55f0-4c1b-9b6a-0d3c2b7a5e01";
constexpr const char *COMPACT = "6e5a0007-55f0-4c1b-9b6a-0d3c2b7a5e01";
}  // namespace uuids

constexpr uint16_t kRequestedMtu = 247;

// boot_id: u16 incremented in NVS at every boot; skips 0 and 0xFFFF (null sentinel).
inline uint16_t umsf_next_boot_id() {
    Preferences p;
    p.begin("umsf", false);
    uint16_t b = p.getUShort("boot", 0);
    b = (b >= 0xFFFE) ? 1 : (uint16_t)(b + 1);
    p.putUShort("boot", b);
    p.end();
    return b;
}
