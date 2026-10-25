"""Exact reproduction of the paper's documented software results (Tables 11, 12, 13, 16)."""

import json
import os
import tempfile
import unittest

from umsf_dataset.export import sizing
from umsf_dataset.synth import bench, incident, protection, study_a, study_b


class StudyATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = study_a.run(protection=False)

    def test_table_11_exact(self):
        m = self.m
        for k, v in study_a.PAPER_TABLE_11.items():
            self.assertEqual(m[k], v, k)
        self.assertEqual((m["fn_in_weak"], m["fn_strong_confirmation_lag"]), (100, 20))
        self.assertEqual(m["strong_detection_delay_min"], {"min": 2, "max": 2})
        self.assertEqual(m["target_zone_minutes"], 400)

    def test_deterministic(self):
        a, _e, _d = study_a.generate()
        b, _e2, _d2 = study_a.generate()
        self.assertEqual(a[:50], b[:50])
        self.assertEqual(a[-1], b[-1])

    @unittest.skipUnless(protection.available(), "optional 'cryptography' not installed")
    def test_protection_demo(self):
        records, _e, _d = study_a.generate()
        p = protection.run_protection_demo(records, study_a.SEED)
        self.assertEqual((p["ordinary_verified"], p["ordinary_records"]), (40320, 40320))
        self.assertEqual(len(p["negative"]), 4)
        for name, v in p["negative"].items():
            self.assertEqual((v["rejected"], v["cases"]), (1000, 1000), name)


class StudyBTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.r = study_b.run(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_table_12_exact(self):
        r = self.r
        self.assertEqual((r["input_lines"], r["unique_identities"], r["duplicates"], r["conflicts"], r["rejected"],
                          r["exported"], r["summaries"]), (2173, 2160, 6, 1, 6, 2159, 12))
        self.assertEqual(r["windows_per_site"], {"SITE-A": 6, "SITE-B": 6})
        self.assertEqual((r["expected_per_window"], r["fresh_expected"]), ([180], [36]))
        self.assertEqual((r["selfchecks_passed"], r["selfchecks_failed"]), (10, 0))
        self.assertEqual(r["min_fresh_devices_good"], 6)  # all six devices contributed a fresh good record

    def test_generator_counts(self):
        t = study_b.generate()["truth"]
        self.assertEqual((t["base_records"], t["input_lines"], t["poor_quality"], t["null_quality"], t["delayed"]),
                         (2160, 2173, 58, 22, 31))

    def test_manifest_hashes(self):
        from umsf_dataset.export import sha256_file
        exp = os.path.join(self.tmp.name, "exports")
        with open(os.path.join(exp, "manifest.json"), encoding="utf-8") as fh:
            m = json.load(fh)
        self.assertEqual(m["counters"]["exportable_physio"], 2159)
        for e in m["exports"]:
            self.assertEqual(sha256_file(os.path.join(exp, e["path"])), e["sha256"])
        self.assertEqual(m["sources"][0]["sha256"], sha256_file(os.path.join(self.tmp.name, "study_b_input.jsonl")))
        self.assertEqual(m["sizing"]["MB_total"], 51.84)


class BenchTest(unittest.TestCase):
    def test_stage1_table_13(self):
        s = bench.stage1_stats()
        self.assertEqual((s["records"], s["span_s"], s["temp_change"], s["ppg_ir_range"], s["motion_range"]),
                         (13, 120, 0.38, [1181, 1224], [75, 102]))
        recs = bench.stage1_records()
        self.assertTrue(all(r["data_origin"] == "bench_transcription" and r["hr_synthetic"] for r in recs))
        self.assertEqual(bench.stage1_lines()[-1], bench.PAPER_EXAMPLE_LINE)
        self.assertEqual(recs[-1]["skin_temp_c"], 22.19)

    def test_stage2_reenactment(self):
        from umsf_dataset.validate import validate_record
        s2 = bench.stage2()
        for r in s2["station"] + s2["events"]:
            self.assertEqual(validate_record(r)[1], [])
            self.assertEqual(r["data_origin"], "synthetic")
        types = [e["event_type"] for e in s2["events"]]
        for t in ("sos", "sos_reset", "impact_excursion", "possible_impact_local", "gas_channel_alarm",
                  "tilt_change", "link_loss", "link_restored", "presence"):
            self.assertIn(t, types)
        self.assertNotIn("external_strike_report", types)
        first = s2["station"][0]
        self.assertEqual((first["pressure_hpa"], first["tilt_deg"]), (1003.7, 0.4))
        self.assertEqual(max(r["tilt_deg"] for r in s2["station"]), 63.3)
        self.assertEqual(max(r["gas_v"] for r in s2["station"]), 1.32)
        seqs = {r["sequence"] for r in s2["station"]}
        self.assertFalse(any(t in seqs for t in range(152, 172)))  # outage: absent, not zero


class IncidentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.m = incident.write(cls.tmp.name, duration_s=1800, station_interval_s=5)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _jsonl(self, name):
        with open(os.path.join(self.tmp.name, name), encoding="utf-8") as fh:
            return [json.loads(x) for x in fh]

    def test_files_and_validation(self):
        from umsf_dataset.validate import validate_record, validate_roster
        for f in ("roster.json", "physio.jsonl", "station.jsonl", "events.jsonl", "assets.json", "teams.json",
                  "manifest.json"):
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, f)), f)
        for f in ("physio.jsonl", "station.jsonl", "events.jsonl"):
            for r in self._jsonl(f):
                self.assertEqual(validate_record(r)[1], [], f)
        with open(os.path.join(self.tmp.name, "roster.json"), encoding="utf-8") as fh:
            for r in json.load(fh)["sites"]:
                self.assertEqual(validate_roster(r), [])

    def test_evidence_semantics(self):
        evs = self._jsonl("events.jsonl")
        strikes = [e for e in evs if e["event_type"] == "external_strike_report"]
        self.assertEqual(len(strikes), 1)
        self.assertEqual(strikes[0]["source_class"], "authoritative_external_alert")
        self.assertTrue(strikes[0]["provenance"]["source"])
        local = [e for e in evs if e["event_type"] == "possible_impact_local"]
        self.assertTrue(local and all("UNVERIFIED" in e["provenance"]["method"] for e in local))
        alerts = [e["event_type"] for e in evs if e["source_class"] == "authoritative_external_alert"]
        self.assertLess(alerts.index("air_raid_alert"), alerts.index("external_strike_report"))
        self.assertTrue(any(e["event_type"] == "sos" for e in evs))
        self.assertTrue(any(e["event_type"] == "help_request" for e in evs))
        assets = [e for e in evs if e["event_type"] == "asset_status"]
        svc = {e["details"]["service_id"]: e["details"] for e in assets if "service_id" in e["details"]}
        self.assertEqual([svc[s]["demand_units"] for s in ("communications", "emergency_lighting", "water_support",
                                                           "production")], [1, 2, 3, 4])
        self.assertEqual([svc[s]["weight"] for s in ("communications", "emergency_lighting", "water_support",
                                                     "production")], [6, 5, 4, 1])
        asserted = {e["event_type"] for e in evs} | {str((e.get("details") or {}).get("status")) for e in evs}
        for word in ("casualty", "collapse", "dead", "killed", "missile_strike", "injured"):
            self.assertFalse(any(word in a for a in asserted), word)
        self.assertEqual(len(self.m["incident_associations"]), 1)

    def test_link_loss_absent_records_and_null_spo2(self):
        phys = self._jsonl("physio.jsonl")
        a03 = [r for r in phys if r["device_id"] == "A03"]
        self.assertEqual(max(r["sequence"] for r in a03), 48)
        self.assertTrue(all(r["spo2_pct"] is None for r in phys))
        late = [r for r in phys if r["device_id"] == "A02" and r["received_at"] > "2026-10-14T05:14:00Z"
                and r["measured_at"] < "2026-10-14T05:14:00Z"]
        self.assertEqual(len(late), 30)  # node buffer of 30 records delivered late; oldest evicted
        st = self._jsonl("station.jsonl")
        self.assertTrue(all(r["attachment_verified"] is False for r in st))
        self.assertFalse(any(r["device_id"] == "SA1" and r["measured_at"] >= "2026-10-14T05:08:20Z" for r in st))

    def test_table_16_allocation(self):
        q = {b: incident.allocate_services(b) for b in range(0, 13)}
        for b in range(0, 3):
            self.assertFalse(q[b]["feasible"])
        for b in range(3, 6):
            self.assertEqual(q[b]["Q_percent"], 68.75)
        for b in range(6, 10):
            self.assertEqual(q[b]["Q_percent"], 93.75)
            self.assertEqual(q[b]["allocation"], {"communications": 1, "emergency_lighting": 1,
                                                  "water_support": 1, "production": 0})
        for b in (10, 11, 12):
            self.assertEqual(q[b]["Q_percent"], 100.0)

    def test_zone_state_after_impact(self):
        from umsf_dataset.summaries import station_zone_state
        ros = incident.rosters()["SITE-A"]
        st = self._jsonl("station.jsonl")
        evs = self._jsonl("events.jsonl")
        z = station_zone_state(st, evs, ros, "2026-10-14T05:13:00Z")["zones"]
        self.assertEqual(z["A-Z1"]["nodes"]["SA1"]["status"], "unknown")
        self.assertTrue(z["A-Z1"]["possible_impact_local_unverified"])
        self.assertTrue(z["A-Z1"]["sos_active"])
        self.assertEqual(z["A-Z2"]["nodes"]["SA2"]["status"], "current")


class SizingTest(unittest.TestCase):
    def test_sizing(self):
        z = sizing()
        self.assertEqual((z["bytes_per_s"], z["MB_total"], z["records"]), (1800.0, 51.84, 34560))


if __name__ == "__main__":
    unittest.main()
