"""Constrained service continuity, Torstensson et al. (2026) Sec. 3.9.2, Eq. (10)-(11).

    max_y  sum_j w_j y_j
    s.t.   sum_j a_kj y_j <= b_k        for every resource k (justified lower bound)
           y_j <= g_j                   verified admissibility (unknown -> 0)
           y_j  = 1  for j in L         mandatory life-safety services
           y_j <= y_l                   for each prerequisite dependency (j requires l)
           y_j in {0, 1}

Unknown capacity supplies no guaranteed capacity (b_k = 0). The solver is exact:
exhaustive enumeration for n <= 20 services, depth-first branch-and-bound beyond.
If mandatory requirements exceed admissible capacity the result is INFEASIBLE;
life-safety constraints are never relaxed to display a successful solution.

Nothing here switches power or operates equipment: the output is a proposal for
the responsible infrastructure operator (Table 9).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from fractions import Fraction
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

OPTIMAL = "OPTIMAL"
INFEASIBLE = "INFEASIBLE"
ENUMERATION_LIMIT = 20


@dataclass
class Service:
    service_id: str
    name: str
    demand: Dict[str, float]               # resource -> a_kj
    weight: float                          # w_j
    mandatory: bool = False                # j in L
    requires: List[str] = field(default_factory=list)
    admissible: Optional[bool] = True      # g_j; None = unknown -> treated as 0
    admissibility_basis: str = ""
    zone_id: Optional[str] = None

    @property
    def g(self) -> int:
        return 1 if self.admissible is True else 0


@dataclass
class Resource:
    resource_id: str
    unit: str
    lower_bound: Optional[float]           # justified lower bound b_k; None = unknown
    basis: str = ""
    kind: str = "generic"

    @property
    def b(self) -> float:
        # Unknown capacity is not replaced by its pre-event rating.
        return float(self.lower_bound) if self.lower_bound is not None and self.lower_bound > 0 else 0.0


@dataclass
class ContinuityResult:
    status: str
    method: str
    y: Dict[str, int]
    objective: Optional[float]
    total_weight: float
    Q_pct: Optional[float]
    resource_use: Dict[str, float]
    resource_capacity: Dict[str, float]
    unused: Dict[str, float]
    binding_resources: List[str]
    infeasibility_reasons: List[str]
    excluded_inadmissible: List[str]
    notes: List[str]
    candidates_examined: int
    options_for_review: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    @property
    def vector(self) -> Tuple[int, ...]:
        return tuple(self.y.values())


def _exact(x: float) -> Fraction:
    return Fraction(str(x)) if not isinstance(x, Fraction) else x


def q_metric(services: Sequence[Service], y: Mapping[str, int]) -> Optional[float]:
    """Eq. (11): Q(y) = 100 * sum w_j y_j / sum w_j (weighted service coverage)."""
    tot = sum(_exact(s.weight) for s in services)
    if tot == 0:
        return None
    val = sum(_exact(s.weight) * y.get(s.service_id, 0) for s in services)
    return float(Fraction(100) * val / tot)


def _check_static(services: Sequence[Service], resources: Mapping[str, Resource]) -> List[str]:
    """Reasons why mandatory requirements cannot be met regardless of optional choices."""
    reasons = []
    idx = {s.service_id: s for s in services}
    # mandatory closure under dependencies
    forced = set()
    stack = [s.service_id for s in services if s.mandatory]
    while stack:
        j = stack.pop()
        if j in forced:
            continue
        forced.add(j)
        sj = idx.get(j)
        if sj is None:
            reasons.append(f"mandatory chain references unknown service '{j}'")
            continue
        for l in sj.requires:
            stack.append(l)
    for j in sorted(forced):
        sj = idx.get(j)
        if sj is not None and sj.g == 0:
            why = "admissibility unknown" if sj.admissible is None else "not admissible"
            reasons.append(f"mandatory/required service '{j}' {why} ({sj.admissibility_basis or 'no basis recorded'})")
    for k in sorted({k for s in services for k in s.demand}):
        need = sum(_exact(idx[j].demand.get(k, 0)) for j in forced if j in idx)
        cap = _exact(resources[k].b) if k in resources else Fraction(0)
        if need > cap:
            src = "unknown capacity -> 0 guaranteed" if (k not in resources or resources[k].lower_bound is None) else "justified lower bound"
            reasons.append(f"mandatory demand on '{k}' = {float(need):g} exceeds usable capacity {float(cap):g} ({src})")
    return reasons


def solve(services: Sequence[Service], resources: Mapping[str, Resource],
          method: str = "auto") -> ContinuityResult:
    """Exact solution of Eq. (10). method: 'auto' | 'enumeration' | 'branch_and_bound'."""
    services = list(services)
    n = len(services)
    if method == "auto":
        method = "enumeration" if n <= ENUMERATION_LIMIT else "branch_and_bound"
    keys = sorted({k for s in services for k in s.demand} | set(resources))
    cap = {k: _exact(resources[k].b) if k in resources else Fraction(0) for k in keys}
    pos = {s.service_id: i for i, s in enumerate(services)}
    dem = [[_exact(s.demand.get(k, 0)) for k in keys] for s in services]
    w = [_exact(s.weight) for s in services]
    deps = [(pos[s.service_id], pos[l]) for s in services for l in s.requires if l in pos]
    unknown_dep = [(s.service_id, l) for s in services for l in s.requires if l not in pos]
    fixed_one = [i for i, s in enumerate(services) if s.mandatory]
    fixed_zero = {i for i, s in enumerate(services) if s.g == 0}
    for sid, l in unknown_dep:
        fixed_zero.add(pos[sid])   # a service whose prerequisite is not modelled cannot be supported
    notes = []
    if unknown_dep:
        notes.append("services with unmodelled prerequisites forced to 0: " + ", ".join(f"{a}->{b}" for a, b in unknown_dep))
    for k in keys:
        if k in resources and resources[k].lower_bound is None:
            notes.append(f"resource '{k}': capacity unknown -> 0 guaranteed (not replaced by rating)")
        elif k not in resources:
            notes.append(f"resource '{k}': no capacity record -> 0 guaranteed")

    def feasible(y: Sequence[int]) -> bool:
        for i in fixed_one:
            if y[i] != 1:
                return False
        for i in fixed_zero:
            if y[i] != 0:
                return False
        for j, l in deps:
            if y[j] > y[l]:
                return False
        for kk in range(len(keys)):
            if sum(dem[i][kk] for i in range(n) if y[i]) > cap[keys[kk]]:
                return False
        return True

    def better(a, b) -> bool:
        # objective first; then smaller total normalised demand; then lexicographic y (earlier services preferred)
        if b is None:
            return True
        (oa, ua, ya), (ob, ub, yb) = a, b
        if oa != ob:
            return oa > ob
        if ua != ub:
            return ua < ub
        return ya > yb

    def key_of(y):
        obj = sum(w[i] for i in range(n) if y[i])
        use = sum((dem[i][kk] / cap[keys[kk]]) if cap[keys[kk]] else dem[i][kk]
                  for i in range(n) if y[i] for kk in range(len(keys)))
        return (obj, use, tuple(y))

    best = None
    examined = 0
    if method == "enumeration":
        if n > 24:
            raise ValueError("enumeration limited to n <= 24 services")
        for y in itertools.product((0, 1), repeat=n):
            examined += 1
            if feasible(y):
                kk = key_of(y)
                if better(kk, best):
                    best = kk
    elif method == "branch_and_bound":
        order = list(range(n))
        y = [0] * n
        use = [Fraction(0)] * len(keys)
        suffix = [Fraction(0)] * (n + 1)
        for t in range(n - 1, -1, -1):
            i = order[t]
            suffix[t] = suffix[t + 1] + (w[i] if i not in fixed_zero else 0)
        best_holder = [None]
        counter = [0]

        def dfs(t, obj):
            counter[0] += 1
            if best_holder[0] is not None and obj + suffix[t] < best_holder[0][0]:
                return
            if t == n:
                if feasible(y):
                    kk = key_of(y)
                    if better(kk, best_holder[0]):
                        best_holder[0] = kk
                return
            i = order[t]
            for v in (1, 0):
                if v == 1 and i in fixed_zero:
                    continue
                if v == 0 and i in fixed_one:
                    continue
                if v == 1:
                    # capacity pruning
                    if any(use[kk] + dem[i][kk] > cap[keys[kk]] for kk in range(len(keys))):
                        continue
                    # dependency pruning for already-decided prerequisites
                    if any(j == i and l < i and y[l] == 0 for j, l in deps):
                        continue
                else:
                    if any(l == i and j < i and y[j] == 1 for j, l in deps):
                        continue
                y[i] = v
                if v:
                    for kk in range(len(keys)):
                        use[kk] += dem[i][kk]
                dfs(t + 1, obj + (w[i] if v else 0))
                if v:
                    for kk in range(len(keys)):
                        use[kk] -= dem[i][kk]
                y[i] = 0

        dfs(0, Fraction(0))
        best = best_holder[0]
        examined = counter[0]
    else:
        raise ValueError(f"unknown method {method}")

    total_w = float(sum(w))
    excluded = [s.service_id for s in services if s.g == 0]
    if best is None:
        reasons = _check_static(services, resources) or ["no binary allocation satisfies all constraints"]
        return ContinuityResult(INFEASIBLE, method, {s.service_id: 0 for s in services}, None, total_w, None,
                                {}, {k: float(cap[k]) for k in keys}, {}, [], reasons, excluded, notes,
                                examined,
                                ["request additional verified resources",
                                 "reduce non-essential demand (authorised operator decision)",
                                 "transfer functions to a qualified alternate facility"])
    obj, _, yv = best
    yd = {s.service_id: yv[i] for i, s in enumerate(services)}
    use = {k: float(sum(dem[i][kk] for i in range(n) if yv[i])) for kk, k in enumerate(keys)}
    unused = {k: float(cap[k]) - use[k] for k in keys}
    binding = []
    for kk, k in enumerate(keys):
        # a resource is limiting if some unselected admissible service would fit
        # every other constraint but exceeds the remaining capacity of k
        for i in range(n):
            if yv[i] or i in fixed_zero:
                continue
            if dem[i][kk] > cap[k] - _exact(use[k]):
                binding.append(k)
                break
    return ContinuityResult(OPTIMAL, method, yd, float(obj), total_w, q_metric(services, yd), use,
                            {k: float(cap[k]) for k in keys}, unused, binding, [], excluded, notes, examined)


# ---------------------------------------------------------------------------
# Section 4.9 / Table 16 constructed example
# ---------------------------------------------------------------------------

def table16_services() -> List[Service]:
    """Table 16 inputs: demand 1,2,3,4 units; weights 6,5,4,1; comms+lighting mandatory;
    production requires communications; all services assumed authorised."""
    return [
        Service("communications", "Communications", {"units": 1}, 6, True, [], True, "assumed authorised (Sec. 4.9)"),
        Service("emergency_lighting", "Emergency lighting", {"units": 2}, 5, True, [], True, "assumed authorised (Sec. 4.9)"),
        Service("water_support", "Water support", {"units": 3}, 4, False, [], True, "assumed authorised (Sec. 4.9)"),
        Service("production", "Production", {"units": 4}, 1, False, ["communications"], True, "assumed authorised (Sec. 4.9)"),
    ]


def table16_solve(B: float, method: str = "enumeration") -> ContinuityResult:
    return solve(table16_services(), {"units": Resource("units", "illustrative units", B, "constructed example")}, method)


def fig14_table(b_values: Sequence[int] = tuple(range(0, 13))) -> List[dict]:
    """Data behind Fig. 14: optimal Q for usable capacity B = 0..12 (exhaustive enumeration)."""
    rows = []
    for B in b_values:
        r = table16_solve(B)
        rows.append({
            "B": B,
            "status": r.status,
            "y": list(r.vector) if r.status == OPTIMAL else None,
            "priority_sum": r.objective,
            "Q_pct": r.Q_pct,
            "unused_units": r.unused.get("units") if r.status == OPTIMAL else None,
        })
    return rows


def services_from_assets(assets: Mapping) -> Tuple[List[Service], Dict[str, Resource], float]:
    """Build Eq. (10) inputs from an assets.json document (see docs/INPUT_FORMAT.md)."""
    horizon = float(assets.get("planning_horizon_h", 1.0) or 1.0)
    resources, _ = resources_from_assets(assets)
    services = []
    for s in assets.get("services", []) or []:
        sid = s.get("service_id")
        if not sid:
            continue
        demand = {k: float(v) for k, v in (s.get("demand") or {}).items() if v is not None}
        # energy over the declared horizon is derived from power only when declared so
        if "energy_kwh" in resources and "energy_kwh" not in demand and "power_kw" in demand \
                and s.get("derive_energy", True):
            demand["energy_kwh"] = demand["power_kw"] * horizon
        adm = s.get("admissible")
        services.append(Service(sid, s.get("name", sid), demand, float(s.get("priority_weight", 0)),
                                bool(s.get("mandatory", False)), list(s.get("requires", []) or []),
                                adm if adm in (True, False) else None,
                                s.get("admissibility_basis", ""), s.get("zone_id")))
    return services, resources, horizon


def resources_from_assets(assets: Mapping, asset_reports: Sequence[Mapping] = ()) -> Tuple[Dict[str, Resource], List[dict]]:
    """Justified lower bounds b_k from the asset register plus asset_status reports.

    A resource either has a direct `lower_bound` or a list of per-asset
    `contributions`. Each asset_status report (current, from an operator or
    responder) may carry `provenance.capacity_lower_bounds = {resource: value}`
    which replaces that asset's contribution. A stale report removes the
    guarantee (contribution unknown -> 0). Returns (resources, provenance rows).
    """
    contrib: Dict[str, Dict[str, dict]] = {}
    meta: Dict[str, dict] = {}
    direct: Dict[str, Optional[float]] = {}
    for r in assets.get("resources", []) or []:
        rid = r.get("resource_id")
        if not rid:
            continue
        meta[rid] = r
        status = (r.get("status") or "").lower()
        if r.get("contributions") is not None:
            contrib[rid] = {c.get("asset_id"): {"lower_bound": c.get("lower_bound"), "basis": c.get("basis", ""),
                                                "source": "asset register"} for c in r["contributions"]}
        else:
            lb = r.get("lower_bound")
            if status in ("unknown", "unavailable"):
                lb = None if status == "unknown" else 0
            direct[rid] = lb
    for a in sorted(asset_reports, key=lambda x: x.get("observed_at") or ""):
        prov = a.get("provenance") or {}
        bounds = prov.get("capacity_lower_bounds") or {}
        aid = prov.get("asset_id") or a.get("source_id")
        for rid, lb in bounds.items():
            contrib.setdefault(rid, {})
            if prov.get("resource_level"):
                # a report on the resource as a whole replaces all register/asset contributions
                direct.pop(rid, None)
                contrib[rid] = {}
            if rid in direct:
                # convert a direct register bound into a contribution record
                contrib[rid].setdefault("_register", {"lower_bound": direct.pop(rid), "basis": "register", "source": "asset register"})
            current = a.get("status") == "current"
            contrib[rid][aid] = {"lower_bound": lb if current else None,
                                 "basis": prov.get("basis", "") + ("" if current else " [report stale: no guarantee]"),
                                 "source": f"{a.get('source_class')} {a.get('assertion_id')} at {a.get('observed_at')}"}
    resources: Dict[str, Resource] = {}
    rows: List[dict] = []
    for rid in sorted(set(contrib) | set(direct) | set(meta)):
        m = meta.get(rid, {})
        if rid in contrib:
            known = [c["lower_bound"] for c in contrib[rid].values() if c["lower_bound"] is not None]
            lb = sum(float(x) for x in known) if known else None
            basis = "; ".join(f"{k}: {v['lower_bound']} ({v['basis']})" for k, v in sorted(contrib[rid].items()))
            for k, v in sorted(contrib[rid].items()):
                rows.append({"resource_id": rid, "asset_id": k, **v})
        else:
            lb = direct.get(rid)
            basis = m.get("basis", "")
            rows.append({"resource_id": rid, "asset_id": None, "lower_bound": lb, "basis": basis, "source": "asset register"})
        resources[rid] = Resource(rid, m.get("unit", ""), lb, basis, m.get("kind", "generic"))
    return resources, rows
