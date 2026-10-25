import itertools
import random
import unittest
from fractions import Fraction

import helpers  # noqa: F401  (sets sys.path)
from umsf_agent.physio_rules import (
    ILLUSTRATIVE_PARAMS, STUDY_A_PARAMS, GroupParams, INDIVIDUAL_REVIEW, INSUFFICIENT_EVIDENCE, NO_DEVIATION,
    POSSIBLE_GROUP_EVENT, build_reference, decide, group_gate, min_eligible_required, min_flags_required,
    persistent_flag, robust_z, threshold_feasibility, weighted_score)
from umsf_agent.paper import table10_case


class TestEq1RobustZ(unittest.TestCase):
    def test_median_mad_scaling(self):
        ref = build_reference([70, 71, 72, 73, 74, 75, 76, 77, 78, 79], "hr", "rest", eps=0.1, min_n=8)
        self.assertEqual(ref.median, 74.5)
        self.assertEqual(ref.mad, 2.5)
        self.assertAlmostEqual(ref.scale, 1.4826 * 2.5)
        self.assertAlmostEqual(robust_z(80, ref), (80 - 74.5) / (1.4826 * 2.5))

    def test_scale_floor_epsilon(self):
        ref = build_reference([33.0] * 10, "skin", "rest", eps=0.1, min_n=8)
        self.assertEqual(ref.scale, 0.1)
        self.assertAlmostEqual(robust_z(33.5, ref), 5.0)

    def test_uncalibrated_when_reference_insufficient(self):
        ref = build_reference([70, 71, 72], "hr", "rest", eps=1.0, min_n=8)
        self.assertEqual(ref.state, "uncalibrated")
        self.assertIsNone(robust_z(90, ref))

    def test_missing_value_is_not_zero(self):
        ref = build_reference(list(range(60, 75)), "hr", "rest", eps=1.0, min_n=8)
        self.assertIsNone(robust_z(None, ref))


class TestEq2Score(unittest.TestCase):
    W = {"hr": 0.5, "t": 0.5}

    def test_weighted_capped(self):
        self.assertAlmostEqual(weighted_score({"hr": 10.0, "t": -2.0}, self.W, z_max=6.0), 0.5 * 6 + 0.5 * 2)

    def test_missing_channel_makes_score_undefined(self):
        self.assertIsNone(weighted_score({"hr": 1.0, "t": None}, self.W, 6.0))
        self.assertIsNone(weighted_score({"hr": 1.0}, self.W, 6.0))

    def test_weights_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            weighted_score({"hr": 1.0}, {"hr": 0.7}, 6.0)


class TestEq3PersistentFlag(unittest.TestCase):
    def test_unavailable_not_zero_when_current_ineligible(self):
        r = persistent_flag([(True, 5), (True, 5), (True, 5), (True, 5), (False, None)], L=5, v_min=3, rho=0.6, tau=3)
        self.assertFalse(r.available)
        self.assertIsNone(r.value)

    def test_unavailable_when_too_few_eligible_windows(self):
        r = persistent_flag([(False, None), (False, None), (False, None), (True, 5), (True, 5)], 5, 3, 0.6, 3)
        self.assertIsNone(r.value)
        self.assertEqual(r.eligible_windows, 2)

    def test_ineligible_windows_omitted_from_ratio(self):
        r = persistent_flag([(True, 4), (False, None), (True, 1), (True, 4), (True, 4)], 5, 3, 0.75, 3)
        self.assertEqual((r.eligible_windows, r.windows_at_or_above_tau, r.value), (4, 3, 1))
        r = persistent_flag([(True, 1), (False, None), (True, 1), (True, 4), (True, 4)], 5, 3, 0.75, 3)
        self.assertEqual(r.value, 0)

    def test_lookback_limited_to_L(self):
        r = persistent_flag([(True, 9)] * 10 + [(True, 0)] * 3, L=3, v_min=3, rho=0.5, tau=3)
        self.assertEqual(r.value, 0)


class TestTable10(unittest.TestCase):
    """Sec. 4.1 constructed cases, n_min=6, C_min=0.70, m_min=3, theta=0.30."""

    def test_case_A(self):
        g, d = table10_case("A")
        self.assertEqual((g.N, g.n, g.m, g.C_pct, g.p_pct, g.A), (12, 10, 4, 83.3, 40.0, 1))
        self.assertEqual(d.states, [POSSIBLE_GROUP_EVENT])
        self.assertEqual(d.label_en, "Possible group event")

    def test_case_B(self):
        g, d = table10_case("B")
        self.assertEqual((g.N, g.n, g.m, g.C_pct, g.p_pct, g.A), (12, 4, 3, 33.3, 75.0, 0))
        self.assertIn(INSUFFICIENT_EVIDENCE, d.states)
        self.assertIn(INDIVIDUAL_REVIEW, d.states)
        self.assertFalse(g.conditions["n>=n_min"])
        self.assertFalse(g.conditions["C>=C_min"])
        self.assertEqual(d.label_en, "Insufficient group evidence; individual review")
        self.assertEqual(len(g.flagged_workers), 3)   # individual concerns stay visible

    def test_case_C(self):
        g, d = table10_case("C")
        self.assertEqual((g.N, g.n, g.m, g.C_pct, g.p_pct, g.A), (12, 10, 1, 83.3, 10.0, 0))
        self.assertTrue(g.gate_available)
        self.assertEqual(len(d.urgent), 1)
        self.assertEqual(d.label_en, "Urgent individual assistance; no group trigger")


class TestSec43Integer(unittest.TestCase):
    def test_study_a_note(self):
        f = threshold_feasibility(6, STUDY_A_PARAMS)
        self.assertEqual(f.min_eligible, 5)
        self.assertEqual(f.effective_min_coverage_pct, 83.3)
        self.assertTrue(f.coverage_condition_redundant)
        self.assertTrue(f.feasible)

    def test_infeasible_configuration_reported(self):
        f = threshold_feasibility(4, ILLUSTRATIVE_PARAMS)
        self.assertFalse(f.feasible)
        self.assertIn("no group warning feasible", f.note)

    def test_integer_reformulation_equals_eq5_exhaustively(self):
        rng = random.Random(7)
        params = [ILLUSTRATIVE_PARAMS, STUDY_A_PARAMS] + [
            GroupParams(rng.randint(1, 8), rng.choice([0.5, 0.6, 0.7, 0.75, 0.8, 0.9]), rng.randint(1, 5),
                        rng.choice([0.1, 0.2, 0.3, 0.5, 0.7])) for _ in range(30)]
        for p in params:
            for N in range(1, 16):
                for n in range(0, N + 1):
                    for m in range(0, n + 1):
                        eq5 = (n >= p.n_min and Fraction(n, N) >= Fraction(str(p.c_min)) and m >= p.m_min
                               and n > 0 and Fraction(m, n) >= Fraction(str(p.theta)))
                        integ = n >= min_eligible_required(N, p) and n > 0 and m >= min_flags_required(n, p)
                        self.assertEqual(eq5, integ, (p, N, n, m))

    def test_ceil_robust_to_float(self):
        self.assertEqual(min_eligible_required(10, GroupParams(1, 0.7, 1, 0.3)), 7)
        self.assertEqual(min_flags_required(10, GroupParams(1, 0.7, 1, 0.3)), 3)


class TestGroupSemantics(unittest.TestCase):
    def test_unobserved_workers_stay_in_denominator(self):
        roster = [f"W{i}" for i in range(10)]
        g = group_gate("z", roster, {"W0": 1, "W1": 1, "W2": 1}, ILLUSTRATIVE_PARAMS)
        self.assertEqual((g.N, g.n), (10, 3))
        self.assertEqual(len(g.unavailable_workers), 7)
        self.assertEqual(g.A, 0)

    def test_roster_unavailable_no_group_conclusion(self):
        g = group_gate("z", None, {"a": 0, "b": 0, "c": 0, "d": 0, "e": 0, "f": 0}, ILLUSTRATIVE_PARAMS)
        self.assertIsNone(g.C)
        self.assertFalse(g.gate_available)
        d = decide(g)
        self.assertNotIn(NO_DEVIATION, d.states)

    def test_empty_roster(self):
        g = group_gate("z", [], {}, ILLUSTRATIVE_PARAMS)
        self.assertIsNone(g.C)
        self.assertIsNone(g.p)

    def test_duplicates_count_once(self):
        g = group_gate("z", ["a", "a", "b"], {"a": 1, "b": 0}, ILLUSTRATIVE_PARAMS)
        self.assertEqual((g.N, g.n, g.m), (2, 2, 1))

    def test_no_deviation_never_labelled_safe(self):
        roster = [f"W{i}" for i in range(8)]
        d = decide(group_gate("z", roster, {w: 0 for w in roster}, ILLUSTRATIVE_PARAMS))
        self.assertEqual(d.states, [NO_DEVIATION])
        self.assertNotIn("safe", d.label_en.lower().replace("unsafe", ""))
        self.assertIn("НЕ означає", d.label_uk)

    def test_urgent_bypasses_group_rule_even_with_no_coverage(self):
        d = decide(group_gate("z", ["a", "b"], {}, ILLUSTRATIVE_PARAMS), [{"worker": "a", "event_type": "sos"}])
        self.assertTrue(d.urgent)
        self.assertTrue(d.label_en.startswith("Urgent individual assistance"))

    def test_losing_unaffected_worker_raises_p_but_lowers_C(self):
        roster = [f"W{i}" for i in range(10)]
        f1 = {w: (1 if i < 3 else 0) for i, w in enumerate(roster)}
        f2 = dict(f1)
        f2["W9"] = None
        g1, g2 = group_gate("z", roster, f1, ILLUSTRATIVE_PARAMS), group_gate("z", roster, f2, ILLUSTRATIVE_PARAMS)
        self.assertGreater(g2.p, g1.p)
        self.assertLess(g2.C, g1.C)


if __name__ == "__main__":
    unittest.main()
