import itertools
import random
import unittest

import helpers  # noqa: F401
from umsf_agent.continuity import (INFEASIBLE, OPTIMAL, Resource, Service, fig14_table, q_metric,
                                   resources_from_assets, solve, table16_services, table16_solve)


class TestSection49(unittest.TestCase):
    def test_capacity_boundaries(self):
        for B in range(0, 3):
            r = table16_solve(B)
            self.assertEqual(r.status, INFEASIBLE)
            self.assertIsNone(r.Q_pct)
            self.assertIsNone(r.objective)
        for B, y, q in [(3, (1, 1, 0, 0), 68.75), (4, (1, 1, 0, 0), 68.75), (5, (1, 1, 0, 0), 68.75),
                        (6, (1, 1, 1, 0), 93.75), (7, (1, 1, 1, 0), 93.75), (9, (1, 1, 1, 0), 93.75),
                        (10, (1, 1, 1, 1), 100.0), (12, (1, 1, 1, 1), 100.0)]:
            r = table16_solve(B)
            self.assertEqual((r.status, r.vector, r.Q_pct), (OPTIMAL, y, q), B)

    def test_text_details(self):
        self.assertEqual(table16_solve(4).unused["units"], 1.0)        # one unit unused
        r7 = table16_solve(7)
        self.assertEqual((r7.y["water_support"], r7.y["production"]), (1, 0))  # production does not displace water
        r6 = table16_solve(6)
        self.assertEqual((r6.objective, r6.total_weight), (15.0, 16.0))
        self.assertEqual(r6.candidates_examined, 16)
        self.assertTrue(any("exceeds usable capacity 2" in s for s in table16_solve(2).infeasibility_reasons))

    def test_fig14_table(self):
        rows = fig14_table()
        self.assertEqual([r["B"] for r in rows], list(range(13)))
        self.assertEqual([r["Q_pct"] for r in rows],
                         [None, None, None, 68.75, 68.75, 68.75, 93.75, 93.75, 93.75, 93.75, 100.0, 100.0, 100.0])

    def test_q_metric(self):
        s = table16_services()
        self.assertEqual(q_metric(s, {"communications": 1, "emergency_lighting": 1}), 68.75)


def _random_instance(rng, n):
    services = []
    for i in range(n):
        req = [f"s{j}" for j in range(n) if j != i and rng.random() < 0.12]
        adm = rng.choice([True, True, True, None, False])
        services.append(Service(f"s{i}", f"s{i}", {"p": rng.randint(0, 9), "e": rng.randint(0, 9)},
                                rng.randint(0, 9), rng.random() < 0.15, req, adm))
    res = {"p": Resource("p", "kW", rng.randint(0, 40)), "e": Resource("e", "kWh", rng.choice([None, rng.randint(0, 40)]))}
    return services, res


def _brute(services, res):
    best = None
    for y in itertools.product((0, 1), repeat=len(services)):
        ok = True
        for i, s in enumerate(services):
            if s.mandatory and not y[i]:
                ok = False
            if y[i] and s.g == 0:
                ok = False
            for l in s.requires:
                j = int(l[1:])
                if y[i] > y[j]:
                    ok = False
        for k, r in res.items():
            if sum(s.demand.get(k, 0) for i, s in enumerate(services) if y[i]) > r.b:
                ok = False
        if ok:
            v = sum(s.weight for i, s in enumerate(services) if y[i])
            best = v if best is None or v > best else best
    return best


class TestExactSolvers(unittest.TestCase):
    def test_enumeration_and_bnb_match_bruteforce(self):
        rng = random.Random(11)
        for _ in range(250):
            n = rng.randint(1, 9)
            s, r = _random_instance(rng, n)
            ref = _brute(s, r)
            for m in ("enumeration", "branch_and_bound"):
                out = solve(s, r, m)
                if ref is None:
                    self.assertEqual(out.status, INFEASIBLE, m)
                else:
                    self.assertEqual(out.status, OPTIMAL, m)
                    self.assertEqual(out.objective, ref, m)

    def test_auto_switches_to_bnb_beyond_20(self):
        rng = random.Random(3)
        s, r = _random_instance(rng, 22)
        for x in s:
            x.mandatory = False
        out = solve(s, r)
        self.assertEqual(out.method, "branch_and_bound")

    def test_unknown_capacity_is_zero(self):
        s = [Service("a", "a", {"p": 1}, 1, False)]
        out = solve(s, {"p": Resource("p", "kW", None)})
        self.assertEqual(out.y["a"], 0)
        self.assertTrue(any("unknown" in n for n in out.notes))

    def test_unknown_admissibility_excludes(self):
        s = [Service("a", "a", {"p": 1}, 5, False, [], None)]
        out = solve(s, {"p": Resource("p", "kW", 10)})
        self.assertEqual(out.y["a"], 0)
        self.assertIn("a", out.excluded_inadmissible)

    def test_mandatory_inadmissible_is_infeasible_never_relaxed(self):
        s = [Service("life", "life", {"p": 1}, 5, True, [], None), Service("b", "b", {"p": 1}, 1)]
        out = solve(s, {"p": Resource("p", "kW", 10)})
        self.assertEqual(out.status, INFEASIBLE)
        self.assertTrue(any("admissibility unknown" in x for x in out.infeasibility_reasons))
        self.assertIn("transfer functions to a qualified alternate facility", out.options_for_review)

    def test_dependency_respected(self):
        s = [Service("comms", "c", {"p": 5}, 1, False), Service("prod", "p", {"p": 1}, 10, False, ["comms"])]
        out = solve(s, {"p": Resource("p", "kW", 5)})
        self.assertEqual(out.y, {"comms": 1, "prod": 0})   # prod alone would score more but needs comms
        out = solve(s, {"p": Resource("p", "kW", 6)})
        self.assertEqual(out.y, {"comms": 1, "prod": 1})

    def test_power_and_energy_are_separate_constraints(self):
        s = [Service("a", "a", {"power_kw": 10, "energy_kwh": 40}, 1, False)]
        out = solve(s, {"power_kw": Resource("power_kw", "kW", 20), "energy_kwh": Resource("energy_kwh", "kWh", 30)})
        self.assertEqual(out.y["a"], 0)
        self.assertIn("energy_kwh", out.binding_resources)


class TestCapacityProvenance(unittest.TestCase):
    ASSETS = {"resources": [{"resource_id": "power_kw", "unit": "kW",
                             "contributions": [{"asset_id": "grid", "lower_bound": 250}]}]}

    def test_reports_replace_contributions(self):
        rep = [{"provenance": {"asset_id": "grid", "capacity_lower_bounds": {"power_kw": 0}}, "status": "current",
                "observed_at": "2026-10-14T08:36:00Z", "source_class": "operator_report", "assertion_id": "a1"},
               {"provenance": {"asset_id": "gen", "capacity_lower_bounds": {"power_kw": 60}}, "status": "current",
                "observed_at": "2026-10-14T08:39:00Z", "source_class": "operator_report", "assertion_id": "a2"}]
        res, rows = resources_from_assets(self.ASSETS, rep)
        self.assertEqual(res["power_kw"].b, 60.0)
        self.assertEqual(len(rows), 2)

    def test_stale_report_removes_guarantee(self):
        rep = [{"provenance": {"asset_id": "grid", "capacity_lower_bounds": {"power_kw": 250}}, "status": "stale",
                "observed_at": "2026-10-14T08:36:00Z", "source_class": "operator_report", "assertion_id": "a1"}]
        res, _ = resources_from_assets(self.ASSETS, rep)
        self.assertEqual(res["power_kw"].b, 0.0)
        self.assertIsNone(res["power_kw"].lower_bound)


if __name__ == "__main__":
    unittest.main()
