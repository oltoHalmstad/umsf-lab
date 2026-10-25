import random
import unittest

import helpers  # noqa: F401
from umsf_agent.assignment import AssignmentProblem, brute_force, solve_lexicographic


def _feasible(prob, pairs):
    teams = [r for r, _ in pairs]
    tasks = [j for _, j in pairs]
    return len(teams) == len(set(teams)) and len(tasks) == len(set(tasks)) and all(p in prob.allowed for p in pairs)


class TestLexicographicAssignment(unittest.TestCase):
    def test_exact_against_brute_force_random(self):
        rng = random.Random(20261014)
        for _ in range(600):
            R, J = rng.randint(1, 5), rng.randint(1, 6)
            teams = [f"T{i}" for i in range(R)]
            tasks = [f"J{i}" for i in range(J)]
            prob = AssignmentProblem(teams, tasks, {j: rng.randint(0, 1) for j in tasks},
                                     {j: rng.randint(0, 100) for j in tasks},
                                     {(r, j): rng.randint(0, 3600) for r in teams for j in tasks if rng.random() < 0.6})
            pairs, triple = solve_lexicographic(prob)
            self.assertTrue(_feasible(prob, pairs))
            self.assertEqual(triple, prob.triple(pairs))
            self.assertEqual(triple, brute_force(prob)[1])

    def test_urgent_dominates_priority(self):
        prob = AssignmentProblem(["T"], ["urgent", "high"], {"urgent": 1, "high": 0}, {"urgent": 1, "high": 1000},
                                 {("T", "urgent"): 9000, ("T", "high"): 1})
        pairs, _ = solve_lexicographic(prob)
        self.assertEqual(pairs, [("T", "urgent")])

    def test_priority_dominates_time(self):
        prob = AssignmentProblem(["T"], ["a", "b"], {"a": 0, "b": 0}, {"a": 2, "b": 1},
                                 {("T", "a"): 10000, ("T", "b"): 1})
        self.assertEqual(solve_lexicographic(prob)[0], [("T", "a")])

    def test_time_breaks_ties(self):
        prob = AssignmentProblem(["T1", "T2"], ["a"], {"a": 1}, {"a": 5}, {("T1", "a"): 900, ("T2", "a"): 300})
        self.assertEqual(solve_lexicographic(prob)[0], [("T2", "a")])

    def test_max_urgent_count_over_priority_sum(self):
        # one team can do either of two urgent tasks; the other only the high-priority urgent one
        prob = AssignmentProblem(["A", "B"], ["u1", "u2"], {"u1": 1, "u2": 1}, {"u1": 100, "u2": 1},
                                 {("A", "u1"): 10, ("A", "u2"): 10, ("B", "u1"): 10})
        pairs, triple = solve_lexicographic(prob)
        self.assertEqual(triple[0], 2)
        self.assertEqual(sorted(pairs), [("A", "u2"), ("B", "u1")])

    def test_forbidden_pairs_never_used(self):
        prob = AssignmentProblem(["T"], ["a"], {"a": 1}, {"a": 100}, {})
        self.assertEqual(solve_lexicographic(prob), ([], (0, 0, 0)))


if __name__ == "__main__":
    unittest.main()
