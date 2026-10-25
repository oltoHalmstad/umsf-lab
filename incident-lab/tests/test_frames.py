import json
import os
import struct
import unittest

from umsf_dataset import frames
from umsf_dataset.validate import validate_record

HERE = os.path.dirname(os.path.abspath(__file__))


class CrcTest(unittest.TestCase):
    def test_check_value(self):
        # Standard CRC-16/CCITT-FALSE check value
        self.assertEqual(frames.crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_crc_little_endian_trailer(self):
        f = frames.encode_frame(5, {"source_class": 3, "device_id": "AG1", "boot_id": 0, "sequence": 1,
                                    "node_time_ms": 0}, {"target_boot_id": 1, "reserved": 0, "ack_up_to_seq": 5})
        self.assertEqual(struct.unpack("<H", f[-2:])[0], frames.crc16_ccitt_false(f[:-2]))


class FrameCodecTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(frames.HEADER_LEN, 18)
        self.assertEqual(frames.PAYLOAD_LEN, {1: 30, 2: 32, 3: 12, 4: 16, 5: 8, 6: 8})

    def test_vectors_file(self):
        rep = frames.load_test_vectors(os.path.join(HERE, "vectors_p1.json"))
        self.assertEqual(rep["failed"], [])
        self.assertGreaterEqual(rep["total"], 10)

    def test_roundtrip_and_null_sentinels(self):
        payload = {"skin_temp": None, "hr": None, "spo2": None, "ppg_ir_mean": None, "ppg_red_mean_div16": None,
                   "ppg_valid_permille": None, "motion_rms_mg": None, "gsr_mv": None, "quality_pct": None,
                   "battery_pct": None, "channel_flags": 0, "artifact_flags": 2, "n_ppg_samples": 0,
                   "n_imu_samples": 0, "window_ms": 10000, "fw_build": 1}
        raw = frames.encode_frame(1, {"source_class": 1, "device_id": "A01", "boot_id": 1, "sequence": 1,
                                      "node_time_ms": 10000}, payload)
        self.assertEqual(len(raw), 50)
        self.assertEqual(raw[18:20], b"\x00\x80")  # i16 null sentinel -32768
        self.assertEqual(raw[24:28], b"\xff\xff\xff\xff")  # u32 null sentinel
        dec = frames.decode_frame(raw)
        self.assertTrue(dec["crc_ok"])
        self.assertEqual(dec["payload"], payload)
        self.assertEqual(dec["header"]["device_id"], "A01")

    def test_corruption_detected_not_raised(self):
        raw = bytearray(frames.encode_compact(1, 7, {"vib_peak_cg": 3, "tilt_ddeg": 4, "pressure_dhpa": 10037,
                                                     "temp": 2190, "gas_mv": 800, "sound_index": 262, "flags": 1,
                                                     "battery_pct": 90}))
        self.assertEqual(len(raw), 20)
        raw[5] ^= 0xFF
        self.assertFalse(frames.decode_compact(bytes(raw))["crc_ok"])

    def test_structural_errors(self):
        with open(os.path.join(HERE, "vectors_p1.json"), encoding="utf-8") as fh:
            good = bytes.fromhex(json.load(fh)[0]["hex"])
        with self.assertRaises(frames.FrameError):
            frames.decode_frame(good[:-1])
        with self.assertRaises(frames.FrameError):
            frames.decode_frame(b"\xb4" + good[1:])
        with self.assertRaises(frames.FrameError):
            frames.decode_frame(good[:3] + b"\x09" + good[4:])

    def test_physio_frame_to_record_valid_and_spo2_null_by_default(self):
        p = {"skin_temp": 2219, "hr": 760, "spo2": 975, "ppg_ir_mean": 1187, "ppg_red_mean_div16": 70,
             "ppg_valid_permille": 950, "motion_rms_mg": 97, "gsr_mv": None, "quality_pct": 92, "battery_pct": 81,
             "channel_flags": 0x0F, "artifact_flags": 0, "n_ppg_samples": 1000, "n_imu_samples": 250,
             "window_ms": 10000, "fw_build": 7}
        raw = frames.encode_frame(1, {"source_class": 1, "device_id": "A01", "boot_id": 1, "sequence": 13,
                                      "node_time_ms": 122488}, p)
        rec = frames.frame_to_record(frames.decode_frame(raw), site_id="S", received_at="2026-01-01T00:02:03Z",
                                     boot_epoch=1767225600.0, time_uncertainty_s=0.5, frame_hex=raw.hex())
        self.assertEqual(rec["skin_temp_c"], 22.19)
        self.assertEqual(rec["hr_bpm"], 76.0)
        self.assertTrue(rec["hr_synthetic"])
        self.assertIsNone(rec["spo2_pct"])  # SPO2_VALIDATED bit not set
        self.assertEqual(rec["measured_at"], "2026-01-01T00:02:02.488Z")
        self.assertEqual(validate_record(rec), ("physio", []))

    def test_event_frame_possible_impact_is_unverified(self):
        raw = frames.encode_frame(3, {"source_class": 2, "device_id": "S01", "boot_id": 1, "sequence": 9,
                                      "node_time_ms": 5000},
                                  {"event_type": 10, "level": 2, "value": 4100, "rule_version": 1, "zone_code": 1,
                                   "related_seq_lo": 4})
        rec = frames.frame_to_record(frames.decode_frame(raw), site_id="S", received_at="2026-01-01T00:00:05Z")
        self.assertEqual(rec["event_type"], "possible_impact_local")
        self.assertIn("not a strike", rec["provenance"]["method"])
        self.assertEqual(rec["value"], 4.1)
        self.assertEqual(validate_record(rec), ("event", []))


class FragmentTest(unittest.TestCase):
    def setUp(self):
        self.t = [0.0]
        self.r = frames.Reassembler(clock=lambda: self.t[0])
        self.frame = bytes(range(200))

    def test_whole_frame(self):
        (n,) = frames.fragment(self.frame, att_payload=244, msg_id=1)
        self.assertEqual(self.r.feed(n), self.frame)

    def test_multi_fragment_out_of_order(self):
        parts = frames.fragment(self.frame, att_payload=20, msg_id=7)
        self.assertGreater(len(parts), 1)
        out = None
        for p in reversed(parts):
            out = self.r.feed(p, source="n1") or out
        self.assertEqual(out, self.frame)

    def test_timeout_2s(self):
        parts = frames.fragment(self.frame, att_payload=20, msg_id=8)
        self.r.feed(parts[0])
        self.t[0] = 2.5
        self.assertIsNone(self.r.feed(parts[1]))
        self.assertEqual(self.r.stats["timeouts"], 1)
        for p in parts[2:]:
            self.assertIsNone(self.r.feed(p))

    def test_limit_512(self):
        with self.assertRaises(frames.FrameError):
            frames.fragment(bytes(513), att_payload=244)
        big = [struct.pack("<HBB", 9, i, 3) + bytes(200) for i in range(3)]
        out = [self.r.feed(b) for b in big]
        self.assertEqual(out, [None, None, None])
        self.assertEqual(self.r.stats["oversize"], 1)


class GatewayLineTest(unittest.TestCase):
    def test_paper_example(self):
        p = frames.parse_gateway_line("RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM")
        self.assertEqual((p["gateway_id"], p["gw_ms"], p["device_id"], p["boot_id"], p["sequence"],
                          p["node_time_ms"]), ("AG1", 152639, "A01", 1, 13, 122488))
        self.assertEqual((p["temp_x100"], p["ppg_ir"], p["motion_mg"], p["hr_x1"]), (2219, 1187, 97, 76))
        self.assertEqual(p["channel_flags"], 0b111)
        rec = frames.line_to_record(p, site_id="BENCH-1", received_at="2026-01-01T00:00:00Z",
                                    data_origin="bench_transcription", hr_synthetic=True)
        self.assertEqual(rec["skin_temp_c"], 22.19)
        self.assertIsNone(rec["time_uncertainty_s"])  # no qualified clock mapping
        self.assertEqual(validate_record(rec), ("physio", []))

    def test_missing_values_are_null(self):
        p = frames.parse_gateway_line("RX,AG1,1,F,A01,1,2,3,,1187,,,P")
        self.assertIsNone(p["temp_x100"])
        rec = frames.line_to_record(p, site_id="S", received_at="2026-01-01T00:00:00Z")
        self.assertIsNone(rec["skin_temp_c"])
        self.assertIsNone(rec["hr_bpm"])
        self.assertIsNone(rec["motion_rms_g"])

    def test_station_and_event_lines(self):
        s = frames.parse_gateway_line("RX,AG1,5,S,S01,1,7,7000,3,4,10037,2190,800,262,13")
        self.assertEqual(s["flags"], 0x13)
        rec = frames.line_to_record(s, site_id="S", received_at="2026-01-01T00:00:00Z", zone_id="Z1")
        self.assertTrue(rec["pir_presence"] and rec["sos"])
        self.assertEqual(rec["gas_v"], 0.8)
        self.assertEqual(validate_record(rec), ("station", []))
        e = frames.parse_gateway_line("RX,AG1,5,E,S01,1,8,7100,gas_channel_alarm,2,1320")
        rec = frames.line_to_record(e, site_id="S", received_at="2026-01-01T00:00:00Z", zone_id="Z1")
        self.assertEqual((rec["event_type"], rec["value"], rec["unit"], rec["level"]),
                         ("gas_channel_alarm", 1.32, "V", "warning"))
        self.assertEqual(validate_record(rec), ("event", []))

    def test_bad_lines(self):
        for line in ("TX,AG1,1,F,A01,1,1,1,1,1,1,1,T", "RX,AG1,1,F,A01,1,1", "RX,AG1,1,F,A01,1,1,1,1,1,1,1,X",
                     "RX,AG1,1,F,A01,,1,1,1,1,1,1,T"):
            with self.assertRaises(frames.FrameError):
                frames.parse_gateway_line(line)


if __name__ == "__main__":
    unittest.main()
