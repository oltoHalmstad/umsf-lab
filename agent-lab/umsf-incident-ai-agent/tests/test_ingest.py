import json
import os
import unittest

from helpers import scenario_dir, tmpdir
from umsf_agent.ingest import load_dataset
from umsf_agent.util import parse_ts


def _rec(seq, hr=70.0, **kw):
    r = {"schema_version": "1.0", "data_origin": "synthetic", "scenario_id": "t", "site_id": "S", "device_id": "A01",
         "boot_id": 1, "sequence": seq, "measured_at": f"2026-10-14T08:00:{seq:02d}Z",
         "received_at": f"2026-10-14T08:00:{seq:02d}Z", "hr_bpm": hr, "spo2_pct": None, "skin_temp_c": 33.0,
         "motion_rms_g": 0.05, "quality": 0.9, "battery_pct": 90}
    r.update(kw)
    return r


class TestIngest(unittest.TestCase):
    def test_scenario_loads(self):
        ds = load_dataset(scenario_dir())
        self.assertEqual(len(ds.zones), 6)
        self.assertEqual(len(ds.worker_zone), 12)
        self.assertEqual(ds.duplicates_dropped, 1)
        self.assertEqual(len({tuple(q["identity"]) for q in ds.quarantine}), 1)
        self.assertEqual(ds.data_origin, "synthetic")
        for s in ds.station_zone:
            self.assertNotIn(s, ds.worker_zone)                 # stationary nodes are not workers

    def _write(self, d, physio_lines, roster=None, extra=None):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "physio.jsonl"), "w") as fh:
            for l in physio_lines:
                fh.write(l + "\n")
        if roster is not None:
            with open(os.path.join(d, "roster.json"), "w") as fh:
                json.dump(roster, fh)
        for name, obj in (extra or {}).items():
            with open(os.path.join(d, name), "w") as fh:
                json.dump(obj, fh)

    def test_dedup_conflict_invalid_range(self):
        d = os.path.join(tmpdir(), "x")
        lines = [json.dumps(_rec(1)), json.dumps(_rec(1)), json.dumps(_rec(2)), json.dumps(_rec(2, hr=99.0)),
                 "{not json", json.dumps(_rec(3, hr=900.0)), json.dumps({"device_id": "A01"})]
        roster = {"site_id": "S", "zones": [{"zone_id": "Z", "expected_workers": ["W01"], "stationary_nodes": ["S01"]}],
                  "device_map": {"A01": "W01", "S01": "W99"}}
        self._write(d, lines, roster)
        ds = load_dataset(d)
        self.assertEqual(ds.duplicates_dropped, 1)
        self.assertEqual([r["sequence"] for r in ds.physio], [1, 3])     # seq 2 quarantined entirely
        self.assertEqual({tuple(q["identity"]) for q in ds.quarantine}, {("S", "A01", 1, 2)})
        self.assertEqual(len(ds.rejected), 2)                             # bad JSON + missing identity
        r3 = ds.physio[1]
        self.assertIsNone(r3["hr_bpm"])                                   # out of range -> null, never normal
        self.assertTrue(any("out of range" in x for x in r3["_quality_reasons"]))
        self.assertNotIn("S01", ds.device_map)                            # stationary node never a worker
        self.assertTrue(any("missing" in w for w in ds.warnings))         # tolerant of absent files

    def test_roster_missing_is_tolerated(self):
        d = os.path.join(tmpdir(), "y")
        self._write(d, [json.dumps(_rec(1, worker_pseudonym="W01"))])
        ds = load_dataset(d)
        self.assertEqual(ds.rosters, [])
        self.assertTrue(any("roster unavailable" in w for w in ds.warnings))
        self.assertEqual(ds.device_map.get("A01"), "W01")

    def test_snapshot_uses_arrival_time(self):
        ds = load_dataset(scenario_dir())
        t = parse_ts("2026-10-14T08:50:00Z")
        snap = ds.snapshot(t)
        self.assertTrue(all(parse_ts(r["received_at"]) <= t for r in snap.physio))
        # Z3 backlog measured before 08:50 but delivered at 08:58 is not yet known
        self.assertFalse([r for r in snap.physio if r["device_id"] == "A08" and r["measured_at"] > "2026-10-14T08:36:00Z"])
        self.assertNotEqual(snap.digest(), ds.snapshot(parse_ts("2026-10-14T08:51:00Z")).digest())


if __name__ == "__main__":
    unittest.main()
