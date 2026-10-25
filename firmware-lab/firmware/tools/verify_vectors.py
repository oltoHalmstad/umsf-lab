#!/usr/bin/env python3
"""Independent check of test_vectors.json against the byte layout in PROTOCOL.md.

Written separately from the C codec (struct-based decoding written from the spec tables) so
that a layout error in lib/umsf_proto would show up as a mismatch. Standard library only.
Usage: python3 tools/verify_vectors.py [test_vectors.json]
"""
import json
import struct
import sys

HDR = ("<BBBB4sHII", ["magic", "version", "source_class", "frame_type", "device_id", "boot_id", "sequence", "node_time_ms"])
PAYLOADS = {
    1: ("<hHHIHHHHBBBBHHHH", ["skin_temp", "hr", "spo2", "ppg_ir_mean", "ppg_red_mean_div16", "ppg_valid_permille",
                             "motion_rms_mg", "gsr_mv", "quality_pct", "battery_pct", "channel_flags", "artifact_flags",
                             "n_ppg_samples", "n_imu_samples", "window_ms", "fw_build"]),
    2: ("<HHhhHhhHHHBBBBHHHH", ["vib_peak_cg", "accel_rms_mg", "tilt_ddeg", "tilt_delta_ddeg", "pressure_dhpa",
                               "pressure_delta_pa", "temp", "gas_mv", "gas_baseline_mv", "sound_index", "flags",
                               "quality_pct", "battery_pct", "sensor_flags", "n_imu_samples", "window_ms", "zone_code",
                               "fw_build"]),
    3: ("<BBiHHH", ["event_type", "level", "value", "rule_version", "zone_code", "related_seq_lo"]),
    4: ("<BBHIIHBB", ["battery_pct", "buffered_records", "evicted_total", "sent_total", "acked_up_to_seq", "fw_build",
                     "sensor_flags", "rssi_neg"]),
    5: ("<HHI", ["target_boot_id", "reserved", "ack_up_to_seq"]),
    6: ("<HHBBH", ["zone_code", "feature_window_ms", "sample_profile", "synthetic_hr_enabled", "reserved"]),
}
COMPACT = ("<BBHHhHhHHBB", ["magic", "node_index", "seq", "vib_peak_cg", "tilt_ddeg", "pressure_dhpa", "temp", "gas_mv",
                            "sound_index", "flags", "battery_pct"])
# measurement fields whose sentinel means null (counters/flags/ids never null)
NULLABLE = {"skin_temp", "hr", "spo2", "ppg_ir_mean", "ppg_red_mean_div16", "ppg_valid_permille", "motion_rms_mg",
            "gsr_mv", "quality_pct", "battery_pct", "vib_peak_cg", "accel_rms_mg", "tilt_ddeg", "tilt_delta_ddeg",
            "pressure_dhpa", "pressure_delta_pa", "temp", "gas_mv", "gas_baseline_mv", "sound_index", "rssi_neg",
            "n_ppg_samples", "n_imu_samples", "window_ms", "fw_build", "zone_code", "rule_version", "value",
            "buffered_records", "evicted_total", "sent_total", "acked_up_to_seq"}
SENTINEL = {"B": 0xFF, "H": 0xFFFF, "h": -32768, "I": 0xFFFFFFFF, "i": -2**31}


def crc16(data):
    c = 0xFFFF
    for x in data:
        c ^= x << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def unpack(fmt, names, buf, kinds=True):
    vals = struct.unpack(fmt, buf)
    out = {}
    for code, name, v in zip(fmt[1:], names, vals):
        if isinstance(v, bytes):
            v = v.rstrip(b"\0").decode("ascii")
        elif name in NULLABLE and SENTINEL.get(code) == v:
            v = None
        out[name] = v
    return out


def main(path):
    assert crc16(b"123456789") == 0x29B1
    vectors = json.load(open(path))
    for v in vectors:
        b = bytes.fromhex(v["hex"])
        crc_ok = crc16(b[:-2]) == struct.unpack("<H", b[-2:])[0]
        exp = v["expected"]
        if b[0] == 0xC5:
            assert len(b) == 20, v["name"]
            got = unpack(COMPACT[0], COMPACT[1], b[:18])
            got["crc_ok"] = crc_ok
            assert got == exp, (v["name"], got, exp)
        else:
            hdr = unpack(HDR[0], HDR[1], b[:18])
            fmt, names = PAYLOADS[hdr["frame_type"]]
            assert len(b) == 18 + struct.calcsize(fmt) + 2, v["name"]
            pl = unpack(fmt, names, b[18:-2])
            assert hdr == exp["header"], (v["name"], hdr, exp["header"])
            assert pl == exp["payload"], (v["name"], pl, exp["payload"])
            assert crc_ok == exp["crc_ok"], v["name"]
        print("ok  ", v["name"])
    print(f"{len(vectors)} vectors verified")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "test_vectors.json")
