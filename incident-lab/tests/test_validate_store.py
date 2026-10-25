import json
import os
import tempfile
import unittest

from umsf_dataset.store import Store
from umsf_dataset.validate import load_schema, validate_line, validate_record, validate_roster


def physio(**kw):
    rec = {"schema_version": "1.0", "data_origin": "synthetic", "scenario_id": "t", "site_id": "S", "device_id": "A01",
           "boot_id": 1, "sequence": 1, "measured_at": "2026-09-08T06:00:00Z", "received_at": "2026-09-08T06:00:01Z",
           "hr_bpm": 70.0, "spo2_pct": None, "skin_temp_c": 33.1, "motion_rms_g": 0.05, "quality": 0.9,
           "battery_pct": 90}
    rec.update(kw)
    return rec


class ValidateTest(unittest.TestCase):
    def test_schemas_load(self):
        for v in ("1.0", "st-1.0", "ev-1.0", "roster"):
            self.assertEqual(load_schema(v)["type"], "object")

    def test_valid_and_nulls(self):
        self.assertEqual(validate_record(physio(hr_bpm=None, quality=None)), ("physio", []))

    def test_rejections(self):
        cases = {
            "measured": physio(data_origin="measured"),
            "unknown field": physio(extra=1),
            "above maximum": physio(hr_bpm=251),
            "below minimum": physio(spo2_pct=49.9),
            "invalid type": physio(sequence="1"),
            "missing required": {k: v for k, v in physio().items() if k != "battery_pct"},
            "ISO-8601": physio(measured_at="2026-09-08 06:00:00"),
        }
        for needle, rec in cases.items():
            _k, errs = validate_record(rec)
            self.assertTrue(any(needle in e for e in errs), (needle, errs))
        self.assertEqual(validate_record(physio(data_origin="measured"), allow_measured=True)[1], [])
        self.assertTrue(validate_record(physio(boot_id=True))[1])  # bool is not an integer

    def test_parse_rejections(self):
        line = json.dumps(physio())
        self.assertEqual(validate_line(line)[2], [])
        for bad, needle in ((line.replace('"hr_bpm": 70.0', '"hr_bpm": NaN'), "non-finite"),
                            (line.replace('"hr_bpm": 70.0', '"hr_bpm": Infinity'), "non-finite"),
                            (line.replace('"hr_bpm": 70.0', '"hr_bpm": 1e999'), "non-finite"),
                            (line[:-5], "malformed"), ("[1,2]", "object"),
                            (line[:-1] + ', "hr_bpm": 71}', "duplicate key"),
                            (" " * 9000 + line, "exceeds")):
            errs = validate_line(bad)[2]
            self.assertTrue(errs and needle in errs[0], (needle, errs))

    def test_strike_only_from_authoritative_source(self):
        ev = {"schema_version": "ev-1.0", "data_origin": "synthetic", "scenario_id": "t", "site_id": "S",
              "zone_id": None, "event_id": "E1", "source_class": "stationary_node", "device_id": "S01",
              "event_type": "external_strike_report", "level": "urgent", "value": None, "unit": None,
              "observed_at": "2026-09-08T06:00:00Z", "reported_at": "2026-09-08T06:00:01Z",
              "time_uncertainty_s": None, "rule_version": None, "quality": None, "ack_state": "unacknowledged",
              "provenance": {"source": "x", "method": "y"}}
        self.assertTrue(validate_record(ev)[1])
        ev["source_class"] = "authoritative_external_alert"
        self.assertEqual(validate_record(ev)[1], [])
        ev["event_type"] = "missile_strike"
        self.assertTrue(validate_record(ev)[1])

    def test_roster(self):
        r = {"site_id": "S", "zones": [{"zone_id": "Z", "name": "n", "expected_workers": ["W1"],
                                        "stationary_nodes": ["S1"]}], "device_map": {"A01": "W1"},
             "valid_from": "2026-01-01T00:00:00Z", "valid_to": None}
        self.assertEqual(validate_roster(r), [])
        r["zones"][0]["stationary_nodes"] = ["W1"]
        self.assertTrue(validate_roster(r))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "t.sqlite")
        self.st = Store(self.db)

    def tearDown(self):
        try:
            self.st.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def test_pragmas(self):
        p = self.st.pragmas()
        self.assertEqual((p["journal_mode"], p["synchronous"]), ("wal", "FULL"))

    def test_dedup_conflict_quarantine(self):
        a = json.dumps(physio())
        self.assertEqual(self.st.ingest_line(a), "inserted")
        self.assertEqual(self.st.ingest_line(a), "duplicate")
        # redelivery via another path with a later received_at is still the same measurement
        self.assertEqual(self.st.ingest_line(json.dumps(physio(received_at="2026-09-08T06:05:00Z",
                                                               gateway_id="AG2"))), "duplicate")
        self.assertEqual(self.st.ingest_line(json.dumps(physio(hr_bpm=99.0))), "conflict")
        self.assertEqual(self.st.ingest_line(json.dumps(physio(hr_bpm=99.0))), "duplicate")
        self.assertEqual(self.st.ingest_line(json.dumps(physio(sequence=2))), "inserted")
        self.st.commit()
        self.assertEqual([r["sequence"] for r in self.st.records("physio")], [2])  # whole identity excluded
        self.assertEqual(len(self.st.records("physio", include_quarantined=True)), 2)
        self.assertEqual(len(self.st.quarantine_log()), 1)
        orig = [r for r in self.st.records("physio", include_quarantined=True) if r["sequence"] == 1][0]
        self.assertEqual(orig["hr_bpm"], 70.0)  # original retained, measured_at never rewritten
        self.assertEqual(orig["received_at"], "2026-09-08T06:00:01Z")

    def test_reopen_persists(self):
        self.st.ingest_jsonl([json.dumps(physio(sequence=i)) for i in range(1, 6)])
        before = self.st.stats()
        self.st.close()
        self.st = Store(self.db)
        self.assertEqual(self.st.stats(), before)

    def test_reject_logged(self):
        res = self.st.ingest_jsonl(["{bad", json.dumps(physio(data_origin="measured")), ""])
        self.assertEqual(res["rejected"], 2)
        self.assertEqual(res["lines"], 2)
        self.assertEqual(len(self.st.rejects()), 2)

    def test_gateway_lines_ingest(self):
        lines = ["boot banner", "RX,AG1,152639,F,A01,1,13,122488,2219,1187,97,76,TPM", "RX,AG1,1,F,A01,1"]
        res = self.st.ingest_gateway_lines(lines, site_id="BENCH", received_at="2026-01-01T00:00:00Z")
        self.assertEqual((res["inserted"], res["rejected"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
