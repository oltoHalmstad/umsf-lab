# Changelog

## 1.0.0 — 2026-10-21

First archived release of the bench prototype.

* Gateway AG1: ESP-NOW receiver for fixed and wearable nodes, Wi-Fi access point
  `UMSF_AG1`, local dashboard (`/`), JSON API (`/api`), alarm reset (`/reset`), latched
  alarms, link-loss detection (5 s), serial EVENT/W CSV log.
* Wearable W01–W03: on-node heart-rate estimation (MAX30102), motion gating and
  impact detection (MPU-6050), skin temperature (DS18B20), SOS button, explicit
  `W_HR_SYNTH` flag for simulated heart rate.
* English-language dashboard (personnel, structural monitoring, signs of life,
  situation assessment, event log).
* Documentation of hardware, packet formats and the HTTP API. Offline interface
  simulator with synthetic data.
