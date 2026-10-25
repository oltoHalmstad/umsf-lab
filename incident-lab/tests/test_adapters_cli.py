import contextlib
import io
import json
import os
import tempfile
import unittest

from umsf_dataset import frames
from umsf_dataset.adapters import AckTracker
from umsf_dataset.adapters.ble_direct import COMPACT_UUID, EVENT_UUID, TELEMETRY_UUID, BleDirectCollector
from umsf_dataset.adapters.mqtt_ingest import MqttIngest
from umsf_dataset.adapters.serial_gateway import SerialGatewayIngest
from umsf_dataset.cli import main
from umsf_dataset.store import Store

PHYSIO = {"skin_temp": 3310, "hr": 720, "spo2": None, "ppg_ir_mean": 50000, "ppg_red_mean_div16": 3000,
          "ppg_valid_permille": 990, "motion_rms_mg": 40, "gsr_mv": None, "quality_pct": 95, "battery_pct": 80,
          "channel_flags": 0x07, "artifact_flags": 0, "n_ppg_samples": 1000, "n_imu_samples": 250,
          "window_ms": 10000, "fw_build": 3}


def physio_frame(seq, **kw):
    return frames.encode_frame(1, {"source_class": 1, "device_id": "A01", "boot_id": 2, "sequence": seq,
                                   "node_time_ms": 10000 * seq}, {**PHYSIO, **kw})


class FakeClient:
    def __init__(self, store):
        self.store, self.published = store, []

    def publish(self, topic, payload, qos=0):
        # An ACK must never be published while a transaction is still open (i.e. before COMMIT).
        assert not self.store._in_tx, "ACK before COMMIT"
        self.published.append((topic, json.loads(payload), qos))


def rec_json(seq, **kw):
    r = {"schema_version": "1.0", "data_origin": "synthetic_payload_physical_transport", "scenario_id": "t",
         "site_id": "SITE-A", "device_id": "A01", "boot_id": 2, "sequence": seq,
         "measured_at": "2026-09-08T06:00:00Z", "received_at": "2026-09-08T06:00:01Z", "hr_bpm": 72.0,
         "spo2_pct": None, "skin_temp_c": 33.1, "motion_rms_g": 0.04, "quality": 0.95, "battery_pct": 80,
         "gateway_id": "AG1"}
    r.update(kw)
    return json.dumps(r).encode()


class AckTrackerTest(unittest.TestCase):
    def test_contiguous(self):
        t = AckTracker()
        self.assertEqual(t.commit("A", 1, 1), 1)
        self.assertIsNone(t.commit("A", 1, 3))
        self.assertEqual(t.commit("A", 1, 2), 3)
        self.assertIsNone(t.commit("A", 1, 2))


class MqttTest(unittest.TestCase):
    def setUp(self):
        self.st = Store()
        self.client = FakeClient(self.st)
        self.m = MqttIngest(self.st, "SITE-A", client=self.client)

    def tearDown(self):
        self.st.close()

    def test_ack_after_commit_and_topics(self):
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(1)), "inserted")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(1)), "duplicate")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(3)), "inserted")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(2)), "inserted")
        self.assertEqual([p[1]["ack_up_to_seq"] for p in self.client.published], [1, 3])
        self.assertEqual(self.client.published[0][0], "umsf/SITE-A/ack/AG1")
        self.assertEqual(self.client.published[0][1], {"device_id": "A01", "boot_id": 2, "ack_up_to_seq": 1})
        self.assertEqual(self.m.handle_message("umsf/SITE-B/AG1/physio", rec_json(4)), "ignored")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/status", b'{"uptime": 5}'), "status")

    def test_rejections_get_no_ack(self):
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(1, data_origin="measured")),
                         "rejected")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", b"{oops"), "rejected")
        self.assertEqual(self.client.published, [])

    def test_frame_hex_verified(self):
        good = physio_frame(1).hex()
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(1, frame_hex=good)), "inserted")
        bad = bytearray(physio_frame(2))
        bad[25] ^= 1
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(2, frame_hex=bad.hex())),
                         "rejected")
        self.assertEqual(self.m.handle_message("umsf/SITE-A/AG1/physio", rec_json(5, frame_hex=good)), "rejected")


class BleTest(unittest.TestCase):
    def test_fragmented_telemetry_event_compact_and_ack(self):
        st = Store()
        acks = []
        t = [100.0]
        c = BleDirectCollector(st, "BENCH", ack_writer=acks.append, clock=lambda: "2026-09-08T06:00:30Z",
                               monotonic=lambda: t[0])
        for seq in (1, 2):
            parts = frames.fragment(physio_frame(seq), att_payload=20, msg_id=seq)
            res = [c.handle_notification(TELEMETRY_UUID, p) for p in parts]
            self.assertEqual(res[-1], "inserted")
            self.assertTrue(all(r is None for r in res[:-1]))
        ev = frames.encode_frame(3, {"source_class": 1, "device_id": "A01", "boot_id": 2, "sequence": 3,
                                     "node_time_ms": 30500},
                                 {"event_type": 1, "level": 3, "value": 1000, "rule_version": 1, "zone_code": 1,
                                  "related_seq_lo": 0})
        (n,) = frames.fragment(ev, msg_id=9)
        self.assertEqual(c.handle_notification(EVENT_UUID, n), "inserted")
        self.assertEqual(st.records("event")[0]["event_type"], "sos")
        self.assertEqual(len(acks), 3)  # telemetry and events share the per-boot sequence space
        dec = frames.decode_frame(acks[-1])
        self.assertEqual((dec["header"]["frame_type"], dec["header"]["source_class"]), (5, 3))
        self.assertEqual((dec["payload"]["target_boot_id"], dec["payload"]["ack_up_to_seq"]), (2, 3))
        for rec in st.records("physio"):  # unqualified boot-clock estimate: never later than arrival
            self.assertLessEqual(rec["measured_at"], rec["received_at"])
            self.assertIsNone(rec["time_uncertainty_s"])
        comp = frames.encode_compact(1, 9, {"vib_peak_cg": 3, "tilt_ddeg": 4, "pressure_dhpa": 10037, "temp": 2190,
                                            "gas_mv": 800, "sound_index": 262, "flags": 0, "battery_pct": 90})
        self.assertEqual(c.handle_notification(COMPACT_UUID, comp), "compact")
        self.assertFalse(c.compact_snapshot()[1]["stale"])
        t[0] += 2.5
        self.assertTrue(c.compact_snapshot()[1]["stale"])
        bad = bytearray(physio_frame(4))
        bad[30] ^= 1
        (n,) = frames.fragment(bytes(bad), msg_id=10)
        self.assertEqual(c.handle_notification(TELEMETRY_UUID, n), "rejected")
        st.close()


class SerialTest(unittest.TestCase):
    def test_stream(self):
        st = Store()
        s = SerialGatewayIngest(st, "BENCH-1", clock=lambda: "2026-01-01T00:02:33Z")
        out = s.run(io.StringIO("ESP-ROM boot\nRX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM\n"
                                "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM\nRX,garbage\n"))
        self.assertEqual(out, {"ignored": 1, "inserted": 1, "duplicate": 1, "conflict": 0, "rejected": 1})
        st.close()


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = main(list(args))
        return code, buf.getvalue()

    def test_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            code, _ = self.run_cli("synth-study-b", "--out", d)
            self.assertEqual(code, 0)
            db = os.path.join(d, "x.sqlite")
            code, out = self.run_cli("ingest", "--db", db, os.path.join(d, "study_b_input.jsonl"))
            self.assertEqual(json.loads(out)["store"]["exportable_physio"], 2159)
            code, _ = self.run_cli("summarize", "--db", db, "--roster", os.path.join(d, "rosters.json"),
                                   "--out", os.path.join(d, "s.json"))
            with open(os.path.join(d, "s.json"), encoding="utf-8") as fh:
                self.assertEqual(len(json.load(fh)), 12)
            code, out = self.run_cli("export", "--db", db, "--out", os.path.join(d, "exp"), "--roster",
                                     os.path.join(d, "rosters.json"), "--generated-at", "2026-09-08T07:00:00Z")
            self.assertEqual(code, 0)
            self.assertTrue(os.path.exists(os.path.join(d, "exp", "manifest.json")))
            code, out = self.run_cli("validate", os.path.join(d, "study_b_input.jsonl"))
            self.assertEqual(code, 1)
            self.assertIn("2173 lines, 2167 valid, 6 invalid", out)
            code, _ = self.run_cli("synth-bench", "--out", os.path.join(d, "bench"))
            code, out = self.run_cli("ingest", "--db", db, "--format", "gateway-lines", "--site", "BENCH-1",
                                     "--received-at", "2026-01-01T00:02:33Z",
                                     os.path.join(d, "bench", "stage1_gateway_lines.txt"))
            self.assertEqual(json.loads(out)["ingest"]["inserted"], 13)
            code, out = self.run_cli("ingest", "--db", db, "--format", "frames-hex", "--site", "BENCH-2",
                                     "--origin", "synthetic", "--boot-epoch", "2026-09-01T10:00:00Z",
                                     os.path.join(d, "bench", "stage2_station_frames.hex"))
            self.assertEqual(json.loads(out)["ingest"]["inserted"], 179)

    def test_selfcheck_and_vectors(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli("selfcheck", "--workdir", d)
            self.assertEqual(code, 0)
            self.assertIn("10 passed, 0 failed", out)
        code, out = self.run_cli("vectors", os.path.join(os.path.dirname(__file__), "vectors_p1.json"))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
