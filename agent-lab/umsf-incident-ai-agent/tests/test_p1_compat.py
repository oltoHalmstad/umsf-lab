"""Compatibility with the P1 `umsf-incident-dataset` export conventions (docs/DATASET_FORMAT.md of P1)."""

import json
import os
import unittest

from helpers import tmpdir
from umsf_agent.agent import Agent
from umsf_agent.ingest import load_dataset

P1_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "umsf-incident-dataset", "data", "incident")


def _ev(eid, et, sc, dev, obs, zone=None, level="warning", value=None, unit=None, prov=None, details=None, unc=0.5):
    e = {"schema_version": "ev-1.0", "data_origin": "synthetic", "scenario_id": "p1-mini", "site_id": "SITE-A",
         "zone_id": zone, "event_id": eid, "source_class": sc, "device_id": dev, "event_type": et, "level": level,
         "value": value, "unit": unit, "observed_at": obs, "reported_at": obs, "time_uncertainty_s": unc,
         "rule_version": 1, "quality": 0.9, "ack_state": "unacknowledged", "provenance": prov or {"source": dev, "method": "x"}}
    if details is not None:
        e["details"] = details
    return e


def write_p1_mini(d):
    os.makedirs(d, exist_ok=True)
    roster = {"facility_id": "FAC", "valid_from": "2026-10-14T00:00:00Z", "valid_to": "2026-10-15T00:00:00Z",
              "sites": [{"site_id": "SITE-A", "zones": [
                  {"zone_id": "A-Z1", "name": "Workshop", "expected_workers": ["W01", "W02", "W03"], "stationary_nodes": ["SA1"]},
                  {"zone_id": "A-Z3", "name": "Electrical room", "expected_workers": [], "stationary_nodes": ["SA3"]}],
                  "device_map": {"A01": "W01", "A02": "W02", "A03": "W03"}}]}
    events = [
        _ev("EV1", "impact_excursion", "stationary_node", "SA1", "2026-10-14T05:08:00Z", "A-Z1", value=4.1, unit="g"),
        _ev("EV2", "possible_impact_local", "stationary_node", "SA1", "2026-10-14T05:08:01Z", "A-Z1", value=4.1, unit="g"),
        _ev("EV3", "sos", "personnel_node", "A01", "2026-10-14T05:08:30Z", "A-Z1", level="urgent", value=1.0),
        _ev("EV4", "personnel_accounting", "operator_report", "OP-A", "2026-10-14T05:09:30Z", None, value=1.0,
            details={"expected": 3, "accounted": ["W02"], "assistance_requested": ["W01"], "unaccounted": ["W03"],
                     "last_confirmed": {"W03": {"zone_id": "A-Z1", "at": "2026-10-14T05:07:50Z"}}}),
        _ev("EV5", "asset_status", "operator_report", "OP-A", "2026-10-14T05:10:05Z", "A-Z3", value=6.0,
            unit="illustrative units", details={"resource_id": "backup_power_units", "capacity_lower_bound": 6,
                                                "capacity_upper_bound": 8, "pre_event_rating": 10}),
        _ev("EV6", "structural_assessment", "responder_report", "RT-1", "2026-10-14T05:15:00Z", "A-Z1",
            prov={"source": "responder_report:RT-1", "method": "visual", "assessor": "qualified assessor",
                  "valid_until": "2026-10-14T06:15:00Z"}, details={"status": "restricted_access", "scope": "A-Z1"}),
        _ev("EV7", "external_strike_report", "authoritative_external_alert", "EXT", "2026-10-14T05:12:00Z", level="urgent",
            prov={"source": "regional administration (simulated)", "method": "bulletin"}, unc=300),
    ]
    assets = {"facility_id": "FAC", "site_id": "SITE-A", "planning_interval_min": 60,
              "resources": [{"resource_id": "backup_power_units", "unit": "units", "capacity_lower_bound": 2,
                             "capacity_upper_bound": 8, "pre_event_rating": 10}],
              "services": [
                  {"service_id": "communications", "demand_units": 1, "weight": 6, "mandatory": True, "prerequisites": [],
                   "demand": {"backup_power_units": 1}, "admissible": True},
                  {"service_id": "emergency_lighting", "demand_units": 2, "weight": 5, "mandatory": True, "prerequisites": [],
                   "demand": {"backup_power_units": 2}, "admissible": True},
                  {"service_id": "water_support", "demand_units": 3, "weight": 4, "mandatory": False, "prerequisites": [],
                   "demand": {"backup_power_units": 3}, "admissible": True},
                  {"service_id": "production", "demand_units": 4, "weight": 1, "mandatory": False,
                   "prerequisites": ["communications"], "demand": {"backup_power_units": 4}, "admissible": True}]}
    teams = {"teams": [
        {"team_id": "RT-1", "competencies": ["search_and_rescue", "first_aid"], "available": True,
         "eta_min": {"A-Z1": 3, "A-Z3": 4}},
        {"team_id": "RT-5", "competencies": ["structural_assessment"], "available": False, "available_from_min": 15,
         "eta_min": {"A-Z1": 3}}]}
    manifest = {"scenario_id": "p1-mini", "incident_id": "INC-X", "data_origin": "synthetic",
                "t0": "2026-10-14T05:00:00Z", "duration_s": 1800,
                "incident_associations": [{"association_id": "ASSOC-1", "external_event_id": "EV7",
                                           "local_event_ids": ["EV1", "EV2"], "associated_by": "OP-A",
                                           "associated_at": "2026-10-14T05:14:00Z", "basis": "coincidence"}]}
    for name, obj in (("roster.json", roster), ("assets.json", assets), ("teams.json", teams), ("manifest.json", manifest)):
        with open(os.path.join(d, name), "w") as fh:
            json.dump(obj, fh)
    with open(os.path.join(d, "events.jsonl"), "w") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    return d


class TestP1Mini(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = write_p1_mini(os.path.join(tmpdir(), "p1mini"))
        cls.ds = load_dataset(cls.dir)
        cls.res = Agent(cls.dir, tmpdir()).run()

    def test_normalisation(self):
        ds = self.ds
        self.assertEqual(set(ds.zones), {"A-Z1", "A-Z3"})                      # "sites" wrapper
        self.assertEqual(ds.manifest["end"], "2026-10-14T05:30:00Z")           # t0 + duration_s
        ev = {e["event_id"]: e for e in ds.events}
        self.assertEqual(ev["EV3"]["level"], 3)
        self.assertEqual(ev["EV3"]["level_label"], "urgent")
        self.assertEqual(ev["EV6"]["value"], "restricted_access")
        self.assertIn("EV4#W03", ev)                                           # aggregated accounting expanded
        self.assertEqual(ev["EV4#W03"]["provenance"]["location_zone"], "A-Z1")
        self.assertEqual(ds.assets["services"][0]["priority_weight"], 6)
        self.assertEqual(ds.assets["resources"][0]["lower_bound"], 2)          # capacity_lower_bound, never rating
        rt5 = next(t for t in ds.teams["teams"] if t["team_id"] == "RT-5")
        self.assertEqual(rt5["available_from"], "2026-10-14T05:15:00Z")

    def test_resource_report_replaces_register_bound(self):
        c = self.res["continuity"]["result"]
        self.assertEqual(c["resource_capacity"]["backup_power_units"], 6.0)    # not 2 + 6
        self.assertEqual(c["Q_pct"], 93.75)

    def test_personnel_and_restricted_access(self):
        cat = {p["worker"]: p["category"] for p in self.res["rescue"]["personnel"]}
        self.assertEqual(cat, {"W01": "assistance_requested", "W02": "known", "W03": "unresolved"})
        u = {x["task_id"]: x for x in self.res["rescue"]["unassigned"]}
        self.assertIn("RT-assist_sos-W01", u)
        self.assertTrue(any("restricted_access" in c for c in u["RT-assist_sos-W01"]["limiting_constraints"]))

    def test_eta_used_as_delta(self):
        pi = self.res["rescue"]["pairs"]["RT-1|RT-assist_sos-W01"]
        self.assertEqual(pi["delta_s"], 3 * 60 + 120)

    def test_association_reported_without_attribution(self):
        st = self.res["incident"]["strike_statement_en"]
        self.assertIn("ASSOC-1", st)
        self.assertIn("remain unverified", st)


@unittest.skipUnless(os.path.isdir(P1_DIR), "sibling P1 dataset not present")
class TestRealP1Dataset(unittest.TestCase):
    """`umsf-agent run --data ../umsf-incident-dataset/data/incident` against P1's shipped scenario."""

    @classmethod
    def setUpClass(cls):
        from umsf_agent.util import parse_ts
        cls.end = Agent(P1_DIR, tmpdir()).run()
        cls.mid = Agent(P1_DIR, tmpdir()).run(parse_ts("2026-10-14T05:16:30Z"))

    def test_loads(self):
        d = self.end["dataset"]
        self.assertEqual((d["zones"], d["workers"], d["stationary_nodes"]), (5, 12, 5))
        self.assertEqual(d["events"] >= 30, True)
        self.assertEqual(d["rejected_lines"], 0)

    def test_continuity_q(self):
        c = self.end["continuity"]["result"]
        self.assertEqual(c["status"], "OPTIMAL")
        self.assertEqual(c["Q_pct"], 93.75)
        self.assertEqual(c["resource_capacity"]["backup_power_units"], 6.0)   # lower bound, not rating 10

    def test_sos_w01_and_help_w05_tasks(self):
        ids_mid = {t["task_id"] for t in self.mid["rescue"]["tasks"]}
        self.assertIn("RT-assist_sos-W01", ids_mid)
        self.assertIn("RT-assist_help_request-W05", ids_mid)
        ids_end = {t["task_id"] for t in self.end["rescue"]["tasks"]}
        self.assertIn("RT-assist_sos-W01", ids_end)
        # W05: responder-confirmed assistance reported at 05:20 reconciles the help request
        cat = {p["worker"]: p["category"] for p in self.end["rescue"]["personnel"]}
        self.assertEqual(cat["W05"], "known")
        self.assertEqual(cat["W03"], "unresolved")         # never a casualty inference

    def test_a_z1_access_restricted(self):
        z = self.end["incident"]["zones"]["A-Z1"]["summary"]["structural"]
        self.assertEqual(z["state"], "restricted_access")
        u = next(x for x in self.end["rescue"]["unassigned"] if x["task_id"] == "RT-assist_sos-W01")
        self.assertTrue(u["urgent"])
        self.assertTrue(any("restricted_access" in c for c in u["limiting_constraints"]))
        self.assertIn("not abandoned", u["status"])

    def test_sa1_zone_observation_gap(self):
        z = self.end["incident"]["zones"]["A-Z1"]
        gaps = [a for a in z["U"] if a["kind"] == "observation_gap" and a["status"] == "current"]
        self.assertTrue(any(a["source_id"] == "SA1" for a in gaps))
        self.assertTrue(z["summary"]["flags"]["observation_gap"])
        self.assertIn("unknown", z["summary"]["hazard_state"])

    def test_attribution(self):
        st = self.end["incident"]["strike_statement_en"]
        self.assertIn("authoritative external source reported", st)
        self.assertIn("UNVERIFIED", st)
        self.assertIn("ASSOC-0001", st)


if __name__ == "__main__":
    unittest.main()
