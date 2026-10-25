// mpu6050_min.h - minimal MPU-6050 register driver over Wire (no external library).
// Register map: InvenSense MPU-6000/6050 Register Map rev 4.2.
#pragma once
#include <Arduino.h>
#include <Wire.h>

class Mpu6050 {
public:
    enum AccelRange : uint8_t { A2G = 0, A4G = 1, A8G = 2, A16G = 3 };
    enum GyroRange : uint8_t { G250 = 0, G500 = 1, G1000 = 2, G2000 = 3 };

    // rate_hz: output data rate via SMPLRT_DIV (DLPF on -> 1 kHz base). dlpf_cfg 0..6 (2 = ~94 Hz accel BW).
    bool begin(TwoWire &w, uint8_t addr, AccelRange ar, GyroRange gr, uint16_t rate_hz, uint8_t dlpf_cfg) {
        w_ = &w;
        addr_ = addr;
        if (read8(0x75) != 0x68) return false;            // WHO_AM_I (AD0 does not change it)
        write8(0x6B, 0x80);                                // PWR_MGMT_1: device reset
        delay(100);
        write8(0x6B, 0x01);                                // clock = PLL with X gyro, wake
        write8(0x1A, dlpf_cfg & 0x07);                     // CONFIG: DLPF
        write8(0x19, (uint8_t)(1000 / rate_hz - 1));       // SMPLRT_DIV
        write8(0x1B, (uint8_t)(gr << 3));                  // GYRO_CONFIG
        write8(0x1C, (uint8_t)(ar << 3));                  // ACCEL_CONFIG
        lsb_per_g_ = 16384.0f / (float)(1 << ar);
        full_scale_raw_ = 32767;
        return read8(0x1C) == (uint8_t)(ar << 3);
    }

    // Acceleration in milli-g. saturated = any axis at the ADC rail (range exceeded).
    bool read_accel_mg(float &x, float &y, float &z, bool &saturated) {
        uint8_t b[6];
        if (!read_n(0x3B, b, 6)) return false;
        int16_t rx = (int16_t)((b[0] << 8) | b[1]), ry = (int16_t)((b[2] << 8) | b[3]), rz = (int16_t)((b[4] << 8) | b[5]);
        saturated = abs(rx) >= full_scale_raw_ - 1 || abs(ry) >= full_scale_raw_ - 1 || abs(rz) >= full_scale_raw_ - 1;
        x = rx * 1000.0f / lsb_per_g_;
        y = ry * 1000.0f / lsb_per_g_;
        z = rz * 1000.0f / lsb_per_g_;
        return true;
    }

private:
    bool write8(uint8_t reg, uint8_t v) {
        w_->beginTransmission(addr_);
        w_->write(reg);
        w_->write(v);
        return w_->endTransmission() == 0;
    }
    uint8_t read8(uint8_t reg) {
        uint8_t v = 0xFF;
        read_n(reg, &v, 1);
        return v;
    }
    bool read_n(uint8_t reg, uint8_t *dst, size_t n) {
        w_->beginTransmission(addr_);
        w_->write(reg);
        if (w_->endTransmission(false) != 0) return false;
        if (w_->requestFrom((int)addr_, (int)n) != (int)n) return false;
        for (size_t i = 0; i < n; ++i) dst[i] = (uint8_t)w_->read();
        return true;
    }
    TwoWire *w_ = nullptr;
    uint8_t addr_ = 0x68;
    float lsb_per_g_ = 8192.0f;
    int full_scale_raw_ = 32767;
};
