import unittest

from helpers import scenario_dir
from umsf_agent.incident_state import build_incident_state, delay
from umsf_agent.ingest import load_dataset
from umsf_agent.policy import load_policy
from umsf_agent.util import parse_ts

T = parse_ts


class TestIncidentState(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(scenario_dir())
        cls.pol = load_policy()

    def state(self, ts):
        return build_incident_state(self.ds.snapshot(T(ts)), T(ts), self.pol, {})

    def test_layers_are_typed_records_not_scores(self):
        s = self.state("2026-10-14T08:40:00Z")
        z2 = s.zones["Z2"]
        kinds = {a.kind for a in z2.M}
        self.assertIn("possible_impact_local", kinds)
        self.assertNotIn("damage_score", z2.summary)
        for L in ("M", "H", "P", "F", "U"):
            self.assertIsInstance(z2.layer(L), list)

    def test_possible_impact_local_is_unverified(self):
        s = self.state("2026-10-14T08:40:00Z")
        a = next(a for a in s.zones["Z2"].M if a.kind == "possible_impact_local")
        self.assertEqual(a.verification, "unverified")
        self.assertIn("UNVERIFIED", a.semantics)

    def test_strike_attribution_only_from_authoritative_source(self):
        before = self.state("2026-10-14T08:40:00Z")      # external report arrives 08:41
        self.assertIn("No strike attribution", before.strike_statement_en)
        self.assertEqual([a.assertion_id for a in before.rejected_attributions], ["A-E014"])
        after = self.state("2026-10-14T08:42:00Z")
        self.assertIn("authoritative external source reported", after.strike_statement_en)
        self.assertIn("remain UNVERIFIED", after.strike_statement_en)
        ext = [a for a in after.site_context if a.kind == "external_strike_report"]
        self.assertEqual(len(ext), 1)
        self.assertEqual(ext[0].source_class, "authoritative_external_alert")

    def test_link_loss_creates_gap_and_removes_current_authority(self):
        s = self.state("2026-10-14T08:45:00Z")
        z3 = s.zones["Z3"]
        gaps = [a for a in z3.U if a.kind == "observation_gap" and a.status == "current"]
        self.assertTrue(gaps)
        self.assertIn("UNKNOWN", gaps[0].semantics)
        self.assertNotIn("collapse", gaps[0].semantics.replace("not collapse", ""))
        gas = [a for a in z3.H if a.kind == "gas_channel_alarm"]
        self.assertEqual(gas[0].status, "stale")          # history kept, no current authority
        self.assertEqual(z3.summary["hazard_state"], "unknown_after_alarm (observation gap)")
        # SOS stays visible despite the gap
        self.assertTrue(any(a.kind == "sos" and a.status == "current" for a in z3.P))

    def test_link_restored_closes_gap(self):
        s = self.state("2026-10-14T09:05:00Z")
        self.assertFalse([a for a in s.zones["Z3"].U if a.kind == "observation_gap" and a.status == "current"])
        self.assertTrue(any(a.kind == "link_loss" and a.status == "resolved" for a in s.zones["Z3"].U))

    def test_freshness_stale_history(self):
        s = self.state("2026-10-14T09:10:00Z")
        # gas alarm at 08:34:40 is older than the 600 s hazard horizon
        gas = [a for a in s.zones["Z3"].H if a.kind == "gas_channel_alarm"][0]
        self.assertEqual(gas.status, "stale")
        self.assertTrue(any("history" in n for n in gas.notes))

    def test_attachment_uncertain_withdraws_structural_interpretation(self):
        s = self.state("2026-10-14T08:40:00Z")
        self.assertTrue(any(a.kind == "attachment_uncertain" for a in s.zones["Z2"].U))
        tilt = next(a for a in s.zones["Z2"].M if a.kind == "tilt_change")
        self.assertTrue(any("no structural interpretation" in n for n in tilt.notes))

    def test_structural_assessment_qualified_with_validity(self):
        s = self.state("2026-10-14T08:51:00Z")
        st = s.zones["Z1"].summary["structural"]
        self.assertEqual(st["state"], "no_restriction_observed")
        self.assertEqual(st["assessor"], "QA-1")
        self.assertEqual(s.zones["Z2"].summary["structural"]["state"], "unknown")
        s2 = self.state("2026-10-14T08:49:00Z")
        self.assertEqual(s2.zones["Z1"].summary["structural"]["state"], "unknown")

    def test_versioning_supersession(self):
        s = self.state("2026-10-14T08:53:00Z")
        w05 = [a for z in s.zones.values() for a in z.P if a.kind == "personnel_accounting"
               and a.provenance.get("worker") == "W05"]
        self.assertEqual(len(w05), 2)
        old, new = sorted(w05, key=lambda a: a.version)
        self.assertEqual((old.status, new.version, new.supersedes), ("superseded", 2, old.assertion_id))

    def test_presence_cue_semantics(self):
        s = self.state("2026-10-14T08:50:00Z")
        cues = [a for a in s.zones["Z2"].P if a.kind == "presence_cue"]
        self.assertTrue(cues)
        self.assertIn("not a vital sign", cues[0].semantics)

    def test_packets_have_required_fields(self):
        s = self.state("2026-10-14T08:45:00Z")
        req = {"incident_id", "zone_id", "observed_at", "reported_at", "time_uncertainty_s", "source_class",
               "event_semantics", "values", "quality_reasons", "configuration", "last_confirmed_personnel",
               "operational_dependencies", "ack_state"}
        self.assertTrue(s.packets)
        for p in s.packets:
            self.assertTrue(req <= set(p), req - set(p))

    def test_stationary_nodes_not_workers(self):
        s = self.state("2026-10-14T08:40:00Z")
        self.assertEqual(s.zones["Z6"].summary["personnel_telemetry"]["expected"], 0)

    def test_timing_eq7(self):
        s = self.state("2026-10-14T08:45:00Z")
        row = next(r for r in s.timing if r["event_id"] == "E007")
        self.assertEqual(row["T_action"]["status"], "interval")
        lo, hi = row["T_action"]["interval_s"]
        self.assertAlmostEqual((lo + hi) / 2, 430.0)


class TestDelay(unittest.TestCase):
    def test_point_interval_unqualified(self):
        self.assertEqual(delay("2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z", 0)["value_s"], 10.0)
        self.assertEqual(delay("2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z", 2)["interval_s"], [8.0, 12.0])
        self.assertEqual(delay("2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z", None)["status"], "unqualified")
        self.assertEqual(delay("2026-01-01T00:00:00Z", "2026-01-01T00:00:10Z", 0, clock_qualified=False)["status"], "unqualified")
        self.assertEqual(delay("2026-01-01T00:00:00Z", None, 0)["status"], "not_recorded")


if __name__ == "__main__":
    unittest.main()
