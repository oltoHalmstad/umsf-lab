"""Exact lexicographic team-task assignment, Torstensson et al. (2026) Eq. (8)-(9).

    sum_j x_rj <= 1,  sum_r x_rj <= 1,  x_rj <= e_rj a_j,  x_rj in {0,1}       (8)
    lexmax ( sum h_j x_rj ,  sum p_j x_rj ,  - sum delta_rj x_rj )             (9)

Exactness argument. All three objective components are integers (h_j in {0,1},
p_j integer, delta_rj rounded to whole seconds). With

    B2 = 1 + sum_r max_j delta_rj        (exceeds any total assignment time)
    B1 = 1 + B2 * sum_r max_j p_j + B2   (exceeds any priority-and-time term)

the scalar weight  W(x) = B1*H(x) + B2*P(x) - D(x)  orders matchings exactly as
the lexicographic triple (H, P, -D): a unit gain in H outweighs any change in
(P, D); a unit gain in P outweighs any change in D. Maximising W over
matchings is a maximum-weight bipartite matching problem, solved exactly here by
the Hungarian (Kuhn-Munkres) algorithm on an augmented square matrix in which
each team may stay idle and each task may stay unassigned at zero weight.
Python integers keep the arithmetic exact. `brute_force` enumerates all
matchings and is used in the test suite to confirm optimality.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple


@dataclass
class AssignmentProblem:
    teams: List[str]
    tasks: List[str]
    h: Dict[str, int]                         # urgent designation per task
    p: Dict[str, int]                         # command-assigned priority per task
    allowed: Dict[Tuple[str, str], int]       # (team, task) -> delta_rj seconds, only if e_rj * a_j = 1

    def triple(self, pairs: Sequence[Tuple[str, str]]) -> Tuple[int, int, int]:
        H = sum(self.h[j] for _, j in pairs)
        P = sum(self.p[j] for _, j in pairs)
        D = sum(self.allowed[(r, j)] for r, j in pairs)
        return (H, P, -D)


def _hungarian_min(cost: List[List[int]]) -> List[int]:
    """Min-cost perfect assignment on a square integer matrix. Returns col for each row."""
    n = len(cost)
    INF = float("inf")
    u = [0] * (n + 1)
    v = [0] * (n + 1)
    p = [0] * (n + 1)
    way = [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = INF
            j1 = -1
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j] = cur
                        way[j] = j0
                    if minv[j] < delta:
                        delta = minv[j]
                        j1 = j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    row_to_col = [-1] * n
    for j in range(1, n + 1):
        if p[j]:
            row_to_col[p[j] - 1] = j - 1
    return row_to_col


def scalar_weights(prob: AssignmentProblem) -> Tuple[int, int]:
    max_d = {r: 0 for r in prob.teams}
    max_p = {r: 0 for r in prob.teams}
    for (r, j), d in prob.allowed.items():
        max_d[r] = max(max_d[r], int(d))
        max_p[r] = max(max_p[r], int(prob.p[j]))
    B2 = 1 + sum(max_d.values())
    B1 = 1 + B2 * sum(max_p.values()) + B2
    return B1, B2


def solve_lexicographic(prob: AssignmentProblem) -> Tuple[List[Tuple[str, str]], Tuple[int, int, int]]:
    """Exact optimum of Eq. (9) subject to Eq. (8). Deterministic for fixed input order."""
    teams = sorted(prob.teams)
    tasks = sorted(prob.tasks)
    R, J = len(teams), len(tasks)
    if R == 0 or J == 0 or not prob.allowed:
        return [], (0, 0, 0)
    B1, B2 = scalar_weights(prob)
    weight = {}
    for (r, j), d in prob.allowed.items():
        weight[(r, j)] = B1 * int(prob.h[j]) + B2 * int(prob.p[j]) - int(d)
    big = 1 + sum(abs(x) for x in weight.values())
    n = R + J
    cost = [[0] * n for _ in range(n)]
    for i, r in enumerate(teams):
        for c, j in enumerate(tasks):
            w = weight.get((r, j))
            # forbidden pairs (e_rj * a_j = 0) get a prohibitive cost; dummies always
            # offer a zero-cost alternative so they are never selected
            cost[i][c] = -w if w is not None else big
        # columns J..J+R-1: team idle (cost 0)
    # rows R..R+J-1: task unassigned (cost 0 everywhere)
    sol = _hungarian_min(cost)
    pairs = []
    for i, r in enumerate(teams):
        c = sol[i]
        if c < J:
            j = tasks[c]
            if (r, j) in weight and weight[(r, j)] > 0:
                pairs.append((r, j))
    return pairs, prob.triple(pairs)


def brute_force(prob: AssignmentProblem) -> Tuple[List[Tuple[str, str]], Tuple[int, int, int]]:
    """Enumerate every feasible matching (small instances only) and return the lexmax."""
    teams = sorted(prob.teams)
    tasks = sorted(prob.tasks)
    best_pairs: List[Tuple[str, str]] = []
    best = (0, 0, 0)
    options = [[None] + [j for j in tasks if (r, j) in prob.allowed] for r in teams]
    for combo in itertools.product(*options):
        chosen = [j for j in combo if j is not None]
        if len(chosen) != len(set(chosen)):
            continue
        pairs = [(r, j) for r, j in zip(teams, combo) if j is not None]
        t = prob.triple(pairs)
        if t > best:
            best, best_pairs = t, pairs
    return best_pairs, best
