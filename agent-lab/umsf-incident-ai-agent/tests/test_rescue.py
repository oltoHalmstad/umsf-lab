import copy
import unittest

from helpers import scenario_dir
from umsf_agent.incident_state import build_incident_state
from umsf_agent.ingest import load_dataset
from umsf_agent.policy import load_policy
from umsf_agent.rescue import access_for, plan_rescue
from umsf_agent.util import parse_ts

T = parse_ts


class TestRescue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(scenario_dir())
        cls.pol = load_policy()

    def plan(self, ts, ds=None, pol=None):
        ds = (ds or self.ds).snapshot(T(ts))
        st = build_incident_state(ds, T(ts), pol or self.pol, {})
        return plan_rescue(ds, st, T(ts), pol or self.pol)

    def test_personnel_reconciliation_states(self):
        p = self.plan("2026-10-14T08:40:00Z")
        cat = {r["worker"]: r["category"] for r in p["personnel"]}
        self.assertEqual(cat["W05"], "assistance_requested")
        self.assertEqual(cat["W10"], "assistance_requested")
        self.assertEqual(cat["W08"], "unaccounted")              # link lost; never "casualty"
        self.assertEqual(cat["W01"], "observed_not_location_confirmed")
        late = {r["worker"]: r["category"] for r in self.plan("2026-10-14T09:10:00Z")["personnel"]}
        self.assertEqual(late["W01"], "known")
        self.assertEqual(late["W05"], "known")                   # handed to medical, SOS reconciled
        self.assertEqual(late["W12"], "unaccounted")            # silent device
        self.assertEqual(late["W08"], "observed_not_location_confirmed")
        w12 = next(r for r in self.plan("2026-10-14T09:10:00Z")["personnel"] if r["worker"] == "W12")
        self.assertIn("not the person's current position", w12["last_confirmed_location"]["basis"])
        self.assertTrue(any("not evidence of injury or death" in n for n in w12["notes"]))

    def test_tasks_from_requests_unaccounted_and_cues(self):
        p = self.plan("2026-10-14T08:50:00Z")
        ids = {t["task_id"] for t in p["tasks"]}
        self.assertIn("RT-assist_sos-W05", ids)
        self.assertIn("RT-assist_sos-S03", ids)
        self.assertIn("RT-assist_help_request-W10", ids)
        self.assertIn("RT-locate_unaccounted-W08", ids)
        self.assertIn("RT-check_presence_cue-Z2", ids)          # presence cue in impact zone
        self.assertNotIn("RT-check_presence_cue-Z5", ids)       # cue without impact/gas evidence
        for t in p["tasks"]:
            self.assertNotIn("victim", t["task_id"])
            self.assertNotIn("triage", t["kind"])

    def test_unknown_access_is_escalated_not_abandoned(self):
        p = self.plan("2026-10-14T08:50:00Z")
        u = next(x for x in p["unassigned"] if x["task_id"] == "RT-assist_sos-S03")
        self.assertTrue(u["urgent"])
        self.assertIn("not abandoned", u["status"])
        self.assertTrue(any("unknown" in c for c in u["limiting_constraints"]))
        self.assertTrue(any(e["task_id"] == "RT-assist_sos-S03" and e["type"] == "access" for e in p["escalations"]))
        self.assertIn(u, p["unassigned_urgent"])

    def test_ppe_required_in_gas_zone(self):
        p = self.plan("2026-10-14T08:50:00Z")
        t = next(t for t in p["tasks"] if t["task_id"] == "RT-assist_sos-S03")
        self.assertIn("scba", t["ppe"])
        self.assertIn("missing PPE for zone hazard: gas_monitor,scba", p["pairs"]["RT2|RT-assist_sos-S03"]["why_not"])

    def test_assignment_respects_eq8(self):
        p = self.plan("2026-10-14T08:40:00Z")
        teams = [a["team_id"] for a in p["assignments"]]
        tasks = [a["task_id"] for a in p["assignments"]]
        self.assertEqual(len(teams), len(set(teams)))
        self.assertEqual(len(tasks), len(set(tasks)))
        for a in p["assignments"]:
            info = p["pairs"][f"{a['team_id']}|{a['task_id']}"]
            self.assertEqual((info["e"], info["a"]), (1, 1))
            self.assertIn("qualified estimate", a["delta_label"])

    def test_access_granted_later_allows_assignment(self):
        ds = copy.deepcopy(self.ds)
        ds.teams["access"].append({"zone_id": "Z3", "status": "authorised", "scope": ["rescue"],
                                   "authorised_by": "incident command", "valid_from": "2026-10-14T08:59:00Z"})
        p = self.plan("2026-10-14T09:10:00Z", ds=ds)
        self.assertIn("RT-assist_sos-S03", [a["task_id"] for a in p["assignments"]])

    def test_policy_override_and_multi_team(self):
        pol = copy.deepcopy(self.pol)
        pol["rescue"]["task_overrides"] = {"RT-check_presence_cue-Z2": {"h": 1, "p": 95}}
        pol["rescue"]["multi_team_task_kinds"] = ["locate_unaccounted"]
        p = self.plan("2026-10-14T09:10:00Z", pol=pol)
        t = next(t for t in p["tasks"] if t["task_id"] == "RT-check_presence_cue-Z2")
        self.assertEqual((t["h"], t["p"]), (1, 95))
        m = next(u for u in p["unassigned"] if u["task_id"] == "RT-locate_unaccounted-W12")
        self.assertIn("separate resource model", m["limiting_constraints"][0])

    def test_access_for_unknown_zone(self):
        a = access_for("Z9", "assist_sos", {"access": []}, T("2026-10-14T09:00:00Z"))
        self.assertEqual((a["a"], a["status"]), (0, "unknown"))


if __name__ == "__main__":
    unittest.main()
