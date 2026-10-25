import unittest

from umsf_dataset.frames import physio_record
from umsf_dataset.records import event_record, station_record
from umsf_dataset.summaries import (physio_current_state, physio_window_summaries, roster_personnel_devices,
                                    station_zone_state)
from umsf_dataset.timeutil import from_epoch, to_epoch, to_kyiv

T0 = to_epoch("2026-09-08T06:00:00Z")
ROSTER = {"site_id": "S", "zones": [{"zone_id": "Z1", "name": "z", "expected_workers": [f"W{i}" for i in range(6)],
                                     "stationary_nodes": ["N1"]}],
          "device_map": {f"D{i}": f"W{i}" for i in range(6)}, "valid_from": "2026-09-08T00:00:00Z", "valid_to": None}


def rec(dev, k, delay=0.5, q=0.9):
    m = T0 + 10 * k
    return physio_record(site_id="S", device_id=dev, boot_id=1, sequence=k + 1, measured_at=from_epoch(m),
                         received_at=from_epoch(m + delay), hr_bpm=70.0, quality=q)


class WindowSummaryTest(unittest.TestCase):
    def test_roster_denominators_not_reporting_devices(self):
        recs = [rec(f"D{i}", k) for i in range(4) for k in range(30)]  # only 4 of 6 report
        recs += [rec("N1", k) for k in range(30)]  # stationary node is not a worker
        (s,) = physio_window_summaries(recs, {"S": ROSTER})
        self.assertEqual(s["expected_records"], 180)
        self.assertEqual(s["fresh_expected"], 36)
        self.assertEqual(s["received_records"], 120)
        self.assertEqual(s["device_coverage"], round(4 / 6, 4))
        self.assertEqual(s["sample_completeness"], round(120 / 180, 4))
        self.assertEqual(s["fresh_received"], 24)
        self.assertEqual(s["unrostered_records"], 30)
        self.assertEqual(s["window_start_local"], "2026-09-08T09:00:00+03:00")

    def test_cutoff_and_delayed_first_arrivals(self):
        recs = [rec("D0", k) for k in range(30)]
        recs[29] = rec("D0", 29, delay=180)  # arrives after window end -> history only
        recs[5] = rec("D0", 5, delay=180)  # arrives before cutoff -> admitted to the window
        (s,) = physio_window_summaries(recs, {"S": ROSTER})
        self.assertEqual((s["received_records"], s["late_after_cutoff"], s["fresh_received"]), (29, 1, 5))
        (later,) = physio_window_summaries(recs, {"S": ROSTER}, cutoff_at=from_epoch(T0 + 1000))
        self.assertEqual(later["received_records"], 30)

    def test_partial_report_cutoff(self):
        recs = [rec("D0", k) for k in range(30)]
        (s,) = physio_window_summaries(recs, {"S": ROSTER}, cutoff_at=from_epoch(T0 + 120.6))
        self.assertFalse(s["complete_window"])
        self.assertEqual(s["received_records"], 13)
        self.assertEqual(s["cutoff"], "2026-09-08T06:02:00.600Z")

    def test_device_vs_sample_vs_channel(self):
        recs = [rec(f"D{i}", k, q=None if k % 2 else 0.9) for i in range(6) for k in range(30)]
        (s,) = physio_window_summaries(recs, {"S": ROSTER})
        self.assertEqual(s["device_coverage"], 1.0)
        self.assertEqual(s["channel_valid_counts"]["quality"], 90)
        self.assertEqual(s["channel_valid_counts"]["spo2_pct"], 0)
        self.assertEqual(s["quality_null"], 90)

    def test_current_state(self):
        recs = [rec("D0", k) for k in range(30)] + [rec("D1", 0)]
        st = physio_current_state(recs, ROSTER, from_epoch(T0 + 300))
        self.assertEqual(st["devices"]["D0"]["status"], "fresh")
        self.assertEqual(st["devices"]["D1"]["status"], "stale")
        self.assertEqual(st["devices"]["D2"]["status"], "missing")
        self.assertEqual(roster_personnel_devices(ROSTER), {f"D{i}" for i in range(6)})


class StationStateTest(unittest.TestCase):
    def _st(self, t):
        return station_record(site_id="S", zone_id="Z1", device_id="N1", boot_id=1, sequence=t,
                              measured_at=from_epoch(T0 + t), received_at=from_epoch(T0 + t + 0.1), gas_v=0.8)

    def _ev(self, t, etype, src="gateway"):
        return event_record(site_id="S", zone_id="Z1", event_id=f"E{t}", source_class=src, device_id="N1",
                            event_type=etype, level="warning", observed_at=from_epoch(T0 + t),
                            reported_at=from_epoch(T0 + t), provenance={"source": "g", "method": "m"})

    def test_staleness_and_link_loss_unknown(self):
        sts = [self._st(t) for t in range(0, 10)]
        z = station_zone_state(sts, [], ROSTER, from_epoch(T0 + 10))["zones"]["Z1"]
        self.assertEqual(z["nodes"]["N1"]["status"], "current")
        z = station_zone_state(sts, [], ROSTER, from_epoch(T0 + 10), compact=True)["zones"]["Z1"]
        self.assertEqual(z["nodes"]["N1"]["status"], "current")
        z = station_zone_state(sts, [], ROSTER, from_epoch(T0 + 12), compact=True)["zones"]["Z1"]
        self.assertEqual(z["nodes"]["N1"]["status"], "stale")
        z = station_zone_state(sts, [self._ev(11, "link_loss")], ROSTER, from_epoch(T0 + 12))["zones"]["Z1"]
        self.assertEqual(z["nodes"]["N1"]["status"], "unknown")
        self.assertTrue(z["observation_gap"])
        self.assertEqual(z["structural_state"], "unknown")
        evs = [self._ev(11, "link_loss"), self._ev(15, "link_restored")]
        z = station_zone_state(sts + [self._st(16)], evs, ROSTER, from_epoch(T0 + 17))["zones"]["Z1"]
        self.assertEqual(z["nodes"]["N1"]["status"], "current")

    def test_local_impact_is_not_strike(self):
        evs = [self._ev(5, "possible_impact_local", "stationary_node"), self._ev(6, "sos", "stationary_node")]
        out = station_zone_state([self._st(5)], evs, ROSTER, from_epoch(T0 + 7))
        self.assertTrue(out["zones"]["Z1"]["possible_impact_local_unverified"])
        self.assertTrue(out["zones"]["Z1"]["sos_active"])
        self.assertEqual(out["external_alerts"], [])

    def test_kyiv_winter_offset(self):
        self.assertEqual(to_kyiv("2026-12-01T10:00:00Z"), "2026-12-01T12:00:00+02:00")


if __name__ == "__main__":
    unittest.main()
