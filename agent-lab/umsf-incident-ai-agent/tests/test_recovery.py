import copy
import unittest

from helpers import scenario_dir
from umsf_agent.agent import continuity_inputs
from umsf_agent.continuity import solve
from umsf_agent.incident_state import build_incident_state
from umsf_agent.ingest import load_dataset
from umsf_agent.policy import load_policy
from umsf_agent.recovery import RecoveryTask, _cpm, plan_recovery, serial_sgs
from umsf_agent.util import parse_ts

T = parse_ts


class TestRecoveryPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ds = load_dataset(scenario_dir())
        cls.pol = load_policy()

    def plan(self, ts, ds=None):
        ds = (ds or self.ds).snapshot(T(ts))
        st = build_incident_state(ds, T(ts), self.pol, {})
        ci = continuity_inputs(ds, st)
        cont = solve(ci["services"], ci["resources"])
        return plan_recovery(ds, st, cont, T(ts), self.pol), cont

    def test_entry_prerequisites_are_hard(self):
        p, _ = self.plan("2026-10-14T09:10:00Z")
        by = {t["task_id"]: t for t in p["tasks"]}
        deb = by["RC-debris_clearance-Z2"]
        self.assertEqual(set(deb["prerequisites"]), {"RC-gas_hazard_check-Z2", "RC-structural_inspection-Z2"})
        self.assertEqual(by["RC-structural_inspection-Z2"]["prerequisites"], ["RC-gas_hazard_check-Z2"])
        for pre in deb["prerequisites"]:
            self.assertGreaterEqual(deb["start"], by[pre]["finish"])

    def test_unknown_access_blocks_and_propagates(self):
        p, _ = self.plan("2026-10-14T08:40:00Z")
        blocked = {t["task_id"] for t in p["blocked"]}
        self.assertIn("RC-water_support_restoration-Z3", blocked)
        self.assertIn("RC-comms_restoration-Z3", blocked)
        self.assertTrue(p["unresolved_prerequisites"])

    def test_future_access_gives_release_time(self):
        p, _ = self.plan("2026-10-14T09:10:00Z")
        g = next(t for t in p["tasks"] if t["task_id"] == "RC-gas_hazard_check-Z3")
        self.assertEqual(g["status"], "scheduled_candidate")
        self.assertGreaterEqual(g["start"], "2026-10-14T09:15:00Z")

    def test_actuation_never_scheduled(self):
        p, _ = self.plan("2026-10-14T09:10:00Z")
        self.assertTrue(any(x.get("service_id") == "production" for x in p["excluded_actuation"]))
        kinds = {t["kind"] for t in p["tasks"]}
        self.assertFalse(kinds & set(self.pol["recovery"]["actuation_task_kinds"]))

    def test_command_supplied_actuation_task_excluded(self):
        ds = copy.deepcopy(self.ds)
        ds.assets["recovery_tasks"] = [{"task_id": "X1", "kind": "switch_power_feed", "zone_id": "Z1"}]
        p, _ = self.plan("2026-10-14T09:10:00Z", ds)
        self.assertTrue(any(x.get("task_id") == "X1" for x in p["excluded_actuation"]))
        self.assertNotIn("X1", [t["task_id"] for t in p["tasks"]])

    def test_continuity_drives_power_task(self):
        p, cont = self.plan("2026-10-14T08:37:00Z")        # grid lost, generator not yet verified
        self.assertEqual(cont.status, "INFEASIBLE")
        tp = next(t for t in p["tasks"] if t["kind"] == "temporary_power_path")
        self.assertGreater(tp["priority"], 150)
        self.assertEqual(p["restoration_order"][0]["task"], tp["task_id"])

    def test_crew_capacity_no_overlap(self):
        p, _ = self.plan("2026-10-14T09:10:00Z")
        by_crew = {}
        for t in p["tasks"]:
            if t["status"] == "scheduled_candidate":
                by_crew.setdefault(t["crew"], []).append((t["start"], t["finish"]))
        for crew, iv in by_crew.items():
            iv.sort()
            for (a, b), (c, d) in zip(iv, iv[1:]):
                self.assertLessEqual(b, c, crew)


class TestSGS(unittest.TestCase):
    def test_cpm_and_equipment_capacity(self):
        tasks = {
            "a": RecoveryTask("a", "k", "Z", "a", ["x"], {"eq": 1}, 10, 5),
            "b": RecoveryTask("b", "k", "Z", "b", ["x"], {"eq": 1}, 10, 5),
            "c": RecoveryTask("c", "k", "Z", "c", ["y"], {}, 5, 1, prerequisites=["a"]),
        }
        cpm = _cpm(tasks)
        self.assertEqual(cpm["c"]["ES"], 10)
        self.assertEqual(cpm["a"]["slack"], 0)
        crews = [{"team_id": "C1", "competencies": ["x"]}, {"team_id": "C2", "competencies": ["x", "y"]}]
        sched, uns = serial_sgs(tasks, crews, {"eq": 1}, cpm)
        self.assertFalse(uns)
        # one unit of equipment: a and b cannot overlap even with two crews
        a, b = sched["a"], sched["b"]
        self.assertTrue(a["finish_s"] <= b["start_s"] or b["finish_s"] <= a["start_s"])
        self.assertGreaterEqual(sched["c"]["start_s"], sched["a"]["finish_s"])

    def test_cycle_detected(self):
        tasks = {"a": RecoveryTask("a", "k", None, "a", [], {}, 1, 1, prerequisites=["b"]),
                 "b": RecoveryTask("b", "k", None, "b", [], {}, 1, 1, prerequisites=["a"])}
        with self.assertRaises(ValueError):
            _cpm(tasks)


if __name__ == "__main__":
    unittest.main()
