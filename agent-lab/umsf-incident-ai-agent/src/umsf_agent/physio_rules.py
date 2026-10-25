"""Personal deviation and coverage-aware group warning model.

Implements Torstensson et al. (2026), Section 3.6, Equations (1)-(5), the exact
integer reformulation of Section 4.3, and the decision states of Section 3.6.4.

Key semantics preserved here:
* Missing channels are never assigned zero deviation (Eq. 2 is undefined then).
* The persistent flag is *unavailable* (None), not 0, when eligibility fails.
* Unobserved workers stay in the roster denominator N.
* Insufficient coverage yields "insufficient group evidence", never "normal".
* Urgent assistance (SOS / help request) bypasses the group rule entirely.

The numerical thresholds are development parameters supplied by policy, not
clinical thresholds. The score d is a general deviation measure, not an
infection probability or toxic-exposure score.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from fractions import Fraction
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .util import ceil_frac, fmt_ts, median, pct

MAD_SCALE = 1.4826

# Decision states (Sec. 3.6.4). The first one must never be rendered as
# "safe environment" or "exposure excluded".
NO_DEVIATION = "no_configured_deviation_detected_under_adequate_monitoring"
INDIVIDUAL_REVIEW = "individual_review_indicated"
POSSIBLE_GROUP_EVENT = "possible_group_event"
INSUFFICIENT_EVIDENCE = "insufficient_monitoring_evidence"
DECISION_STATES = (NO_DEVIATION, INDIVIDUAL_REVIEW, POSSIBLE_GROUP_EVENT, INSUFFICIENT_EVIDENCE)

UNCALIBRATED = "uncalibrated"


def _frac(x) -> Fraction:
    """Exact rational of a decimal parameter (0.7 -> 7/10, not binary float)."""
    return Fraction(str(x))


# ---------------------------------------------------------------------------
# Eq. (1) robust personal reference
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Reference:
    """Robust location/scale of a personal, context-specific reference set B_ikc."""
    feature: str
    context: str
    n: int
    median: Optional[float]
    mad: Optional[float]
    eps: float
    min_n: int
    version: str = "ref-1"

    @property
    def calibrated(self) -> bool:
        return self.n >= self.min_n and self.median is not None

    @property
    def scale(self) -> Optional[float]:
        if not self.calibrated:
            return None
        return max(MAD_SCALE * self.mad, self.eps)

    @property
    def state(self) -> str:
        return "calibrated" if self.calibrated else UNCALIBRATED


def build_reference(values: Iterable[float], feature: str, context: str, eps: float,
                    min_n: int, version: str = "ref-1") -> Reference:
    """Median and MAD of quality-accepted historical observations.

    `values` must already be restricted to accepted observations that precede
    the evaluation period (the caller enforces that ordering).
    """
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return Reference(feature, context, 0, None, None, eps, min_n, version)
    med = median(vals)
    mad = median(abs(v - med) for v in vals)
    return Reference(feature, context, len(vals), med, mad, eps, min_n, version)


def robust_z(x: Optional[float], ref: Reference) -> Optional[float]:
    """Eq. (1): z = (x - median(B)) / max(1.4826 MAD(B), eps_k).

    Returns None (not 0) when x is missing or the reference is uncalibrated.
    """
    if x is None or not ref.calibrated:
        return None
    return (float(x) - ref.median) / ref.scale


# ---------------------------------------------------------------------------
# Eq. (2) weighted capped score
# ---------------------------------------------------------------------------

def weighted_score(z: Mapping[str, Optional[float]], weights: Mapping[str, float],
                   z_max: float, absolute: bool = True) -> Optional[float]:
    """Eq. (2): d = sum_k w_k min{|z_k|, z_max}, sum_k w_k = 1.

    The predeclared feature set K is the key set of `weights`. If any feature in
    K is missing the score is undefined (None); missing channels are never
    assigned zero deviation. `absolute=True` implements the general
    absolute-deviation profile; direction-specific profiles are separate.
    """
    total_w = sum(weights.values())
    if abs(total_w - 1.0) > 1e-9:
        raise ValueError("feature weights must sum to 1")
    if any(w < 0 for w in weights.values()):
        raise ValueError("feature weights must be nonnegative")
    d = 0.0
    for k, w in weights.items():
        zk = z.get(k)
        if zk is None:
            return None
        v = abs(zk) if absolute else zk
        d += w * min(v, z_max)
    return d


# ---------------------------------------------------------------------------
# Eq. (3) persistent individual flag
# ---------------------------------------------------------------------------

@dataclass
class FlagResult:
    available: bool
    value: Optional[int]          # 1 / 0 when available, None when unavailable
    eligible_windows: int         # v_it
    windows_at_or_above_tau: int
    reason: str

    def to_dict(self):
        return asdict(self)


def persistent_flag(windows: Sequence[Tuple[bool, Optional[float]]], L: int, v_min: int,
                    rho: float, tau: float) -> FlagResult:
    """Eq. (3) over the last L windows (oldest first, current window last).

    windows: sequence of (e_iu, d_iu). Ineligible windows are omitted from the
    numerator and denominator, so no undefined score is evaluated.
    """
    look = list(windows)[-L:]
    if not look:
        return FlagResult(False, None, 0, 0, "no windows")
    current_eligible = bool(look[-1][0]) and look[-1][1] is not None
    eligible = [(e, d) for e, d in look if e and d is not None]
    v = len(eligible)
    hits = sum(1 for _, d in eligible if d >= tau)
    if not current_eligible:
        return FlagResult(False, None, v, hits, "current window ineligible")
    if v < v_min:
        return FlagResult(False, None, v, hits, f"eligible windows {v} < v_min {v_min}")
    value = 1 if Fraction(hits, v) >= _frac(rho) else 0
    return FlagResult(True, value, v, hits, "evaluated")


# ---------------------------------------------------------------------------
# Eq. (4)-(5) coverage-aware group gate and Sec. 4.3 integer reformulation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GroupParams:
    n_min: int = 6
    c_min: float = 0.70
    m_min: int = 3
    theta: float = 0.30

    @classmethod
    def from_dict(cls, d: Mapping) -> "GroupParams":
        return cls(int(d.get("n_min", 6)), float(d.get("c_min", 0.70)),
                   int(d.get("m_min", 3)), float(d.get("theta", 0.30)))


STUDY_A_PARAMS = GroupParams(n_min=5, c_min=0.70, m_min=3, theta=0.50)
ILLUSTRATIVE_PARAMS = GroupParams(n_min=6, c_min=0.70, m_min=3, theta=0.30)


def min_eligible_required(N: int, p: GroupParams) -> int:
    """Sec. 4.3: at least max(n_min, ceil(C_min * N)) eligible workers."""
    return max(p.n_min, ceil_frac(p.c_min, N))


def min_flags_required(n: int, p: GroupParams) -> int:
    """Sec. 4.3: given n eligible workers, at least max(m_min, ceil(theta * n)) flags."""
    return max(p.m_min, ceil_frac(p.theta, n))


@dataclass
class Feasibility:
    roster_size: int
    min_eligible: Optional[int]
    min_flags_at_min_eligible: Optional[int]
    feasible: bool
    effective_min_coverage_pct: Optional[float]
    coverage_condition_redundant: Optional[bool]
    note: str

    def to_dict(self):
        return asdict(self)


def threshold_feasibility(N: int, p: GroupParams) -> Feasibility:
    """Check thresholds against the actual roster size (Sec. 4.3).

    A group warning is feasible for this configuration only if some n <= N
    satisfies n >= min_eligible and the required flag count does not exceed n.
    """
    if N is None or N <= 0:
        return Feasibility(N or 0, None, None, False, None, None,
                           "roster unavailable or empty: coverage not calculated; no group conclusion allowed")
    n_req = min_eligible_required(N, p)
    if n_req > N:
        return Feasibility(N, n_req, None, False, None, None,
                           f"requires {n_req} eligible workers but roster has {N}: no group warning feasible")
    feasible_ns = [n for n in range(n_req, N + 1) if min_flags_required(n, p) <= n]
    m_req = min_flags_required(n_req, p)
    eff = pct(n_req, N)
    # The coverage condition is redundant when the count condition already implies it.
    redundant = p.n_min >= ceil_frac(p.c_min, N)
    note = (f"group gate needs >= {n_req} eligible of {N} (effective coverage >= {eff}%)"
            f" and >= {m_req} flags at n={n_req}")
    if redundant:
        note += "; the nominal coverage condition adds no restriction beyond n_min in this configuration"
    return Feasibility(N, n_req, m_req, bool(feasible_ns), eff, redundant, note)


@dataclass
class GroupAssessment:
    zone_id: str
    N: Optional[int]                  # roster-expected workers
    n: int                            # workers with available flag (|V|)
    m: int                            # affected count
    p: Optional[float]                # m/n (fraction) or None when n=0
    C: Optional[float]                # n/N or None when roster unavailable
    p_pct: Optional[float]
    C_pct: Optional[float]
    conditions: Dict[str, Optional[bool]]
    A: int                            # Eq. (5) indicator
    gate_available: bool              # False => insufficient group evidence
    min_eligible_required: Optional[int]
    min_flags_required: Optional[int]
    flagged_workers: List[str] = field(default_factory=list)
    unavailable_workers: List[str] = field(default_factory=list)
    reason: str = ""

    def to_dict(self):
        return asdict(self)


def group_gate(zone_id: str, roster: Optional[Sequence[str]],
               flags: Mapping[str, Optional[int]], params: GroupParams) -> GroupAssessment:
    """Eq. (4)-(5) for one zone and interval.

    roster: explicit expected participating workers (None = roster unavailable).
    flags: worker -> a_it (1/0) or None (unavailable). Workers outside the roster
    are ignored for the zone denominator; each worker contributes at most once.
    """
    if roster is None:
        V = {w: f for w, f in flags.items() if f is not None}
        n, m = len(V), sum(V.values())
        return GroupAssessment(zone_id, None, n, m, (m / n) if n else None, None,
                               pct(m, n), None,
                               {"n>=n_min": None, "C>=C_min": None, "m>=m_min": None, "p>=theta": None},
                               0, False, None, None,
                               sorted(w for w, f in V.items() if f == 1), [],
                               "roster unavailable: coverage not calculated, no automated group conclusion")
    members = list(dict.fromkeys(roster))   # dedupe, keep order
    N = len(members)
    V = {w: flags.get(w) for w in members if flags.get(w) is not None}
    unavailable = [w for w in members if flags.get(w) is None]
    n = len(V)
    m = sum(V.values())
    flagged = sorted(w for w, f in V.items() if f == 1)
    if N == 0:
        return GroupAssessment(zone_id, 0, n, m, None, None, None, None,
                               {"n>=n_min": None, "C>=C_min": None, "m>=m_min": None, "p>=theta": None},
                               0, False, None, None, flagged, unavailable,
                               "roster has N=0: coverage not calculated, no automated group conclusion")
    c_ok = Fraction(n, N) >= _frac(params.c_min)
    n_ok = n >= params.n_min
    m_ok = m >= params.m_min
    p_ok = (Fraction(m, n) >= _frac(params.theta)) if n else None
    conds = {"n>=n_min": n_ok, "C>=C_min": c_ok, "m>=m_min": m_ok, "p>=theta": p_ok}
    A = int(bool(n_ok and c_ok and m_ok and p_ok))
    gate_available = bool(n_ok and c_ok)
    n_req = min_eligible_required(N, params)
    m_req = min_flags_required(n, params) if n else None
    # Integer reformulation must agree with Eq. (5) exactly.
    A_int = int(n >= n_req and m_req is not None and m >= m_req)
    assert A_int == A, "integer reformulation disagrees with Eq. (5)"
    if not gate_available:
        reason = (f"insufficient group evidence: eligible {n}/{N} (needs >= {n_req}); "
                  f"available positive observations remain visible")
    elif A:
        reason = f"all four conditions of Eq. (5) hold (m={m} >= {m_req})"
    else:
        reason = f"adequate coverage; affected count/proportion below threshold (m={m}, needs >= {m_req})"
    return GroupAssessment(zone_id, N, n, m, (m / n) if n else None, n / N,
                           pct(m, n), pct(n, N), conds, A, gate_available, n_req, m_req,
                           flagged, unavailable, reason)


# ---------------------------------------------------------------------------
# Sec. 3.6.4 decision states and urgent pathway
# ---------------------------------------------------------------------------

@dataclass
class ZoneDecision:
    zone_id: str
    states: List[str]
    urgent: List[dict]
    group: GroupAssessment
    label_en: str
    label_uk: str

    def to_dict(self):
        d = asdict(self)
        d["group"] = self.group.to_dict()
        return d


def decide(group: GroupAssessment, urgent: Sequence[dict] = ()) -> ZoneDecision:
    """Combine group gate output with the independent urgent pathway.

    `urgent` lists urgent assistance indications U_it (help request, SOS, a
    competent observer). They are presented alongside the states, never folded
    into one ordinal score, and never require a group threshold.
    """
    states: List[str] = []
    if group.A:
        states.append(POSSIBLE_GROUP_EVENT)
    elif not group.gate_available:
        states.append(INSUFFICIENT_EVIDENCE)
    if group.flagged_workers and not group.A:
        states.append(INDIVIDUAL_REVIEW)
    if not states:
        states.append(NO_DEVIATION)
    urgent = list(urgent)
    # English labels mirror Table 10 wording.
    if urgent:
        en = "Urgent individual assistance"
        en += "; possible group event" if group.A else "; no group trigger"
        uk = "Термінова індивідуальна допомога" + (
            "; можлива групова подія" if group.A else "; груповий тригер відсутній")
        if INSUFFICIENT_EVIDENCE in states:
            en += "; insufficient group evidence"
            uk += "; недостатньо даних для групового висновку"
    elif POSSIBLE_GROUP_EVENT in states:
        en, uk = "Possible group event", "Можлива групова подія"
    elif INSUFFICIENT_EVIDENCE in states:
        en, uk = "Insufficient group evidence", "Недостатньо даних для групового висновку"
        if INDIVIDUAL_REVIEW in states:
            en += "; individual review"
            uk += "; індивідуальний перегляд"
    elif INDIVIDUAL_REVIEW in states:
        en, uk = "Individual review indicated", "Показано індивідуальний перегляд"
    else:
        en = "No configured deviation detected under adequate monitoring"
        uk = "Налаштованих відхилень не виявлено за достатнього моніторингу (це НЕ означає безпечне середовище)"
    return ZoneDecision(group.zone_id, states, urgent, group, en, uk)


# ---------------------------------------------------------------------------
# Applying Eq. (1)-(3) to physio records
# ---------------------------------------------------------------------------

@dataclass
class PhysioConfig:
    features: Dict[str, float]               # feature -> weight (set K)
    eps: Dict[str, float]
    z_max: float = 6.0
    tau: float = 3.0
    rho: float = 0.6
    L: int = 5
    v_min: int = 3
    window_s: int = 60
    freshness_s: int = 60
    quality_min: float = 0.8
    min_records_per_window: int = 3
    min_reference_windows: int = 8
    motion_context_threshold_g: float = 0.15
    accept_synthetic_hr: bool = True

    @classmethod
    def from_policy(cls, d: Mapping) -> "PhysioConfig":
        return cls(features=dict(d.get("features", {"hr_bpm": 0.5, "skin_temp_c": 0.5})),
                   eps=dict(d.get("eps", {"hr_bpm": 1.0, "skin_temp_c": 0.1})),
                   z_max=float(d.get("z_max", 6.0)), tau=float(d.get("tau", 3.0)),
                   rho=float(d.get("rho", 0.6)), L=int(d.get("L", 5)),
                   v_min=int(d.get("v_min", 3)), window_s=int(d.get("window_s", 60)),
                   freshness_s=int(d.get("freshness_s", 60)),
                   quality_min=float(d.get("quality_min", 0.8)),
                   min_records_per_window=int(d.get("min_records_per_window", 3)),
                   min_reference_windows=int(d.get("min_reference_windows", 8)),
                   motion_context_threshold_g=float(d.get("motion_context_threshold_g", 0.15)),
                   accept_synthetic_hr=bool(d.get("accept_synthetic_hr", True)))


def _record_ok(r: Mapping, cfg: PhysioConfig, data_origin: str) -> bool:
    q = r.get("quality")
    if q is None or q < cfg.quality_min:
        return False
    if r.get("hr_synthetic") and not cfg.accept_synthetic_hr and data_origin == "measured":
        return False
    return True


def _window_features(records: Sequence[Mapping], cfg: PhysioConfig, data_origin: str):
    """Median per feature over accepted records of a window; context from motion."""
    ok = [r for r in records if _record_ok(r, cfg, data_origin)]
    if len(ok) < cfg.min_records_per_window:
        return None, None, f"accepted records {len(ok)} < {cfg.min_records_per_window}"
    feats = {}
    for k in cfg.features:
        vals = [r.get(k) for r in ok if r.get(k) is not None]
        if len(vals) < cfg.min_records_per_window:
            return None, None, f"feature {k} missing"
        feats[k] = median(vals)
    motion = [r.get("motion_rms_g") for r in ok if r.get("motion_rms_g") is not None]
    if len(motion) < cfg.min_records_per_window:
        return feats, None, "analysis context unknown (motion unavailable)"
    ctx = "low_motion" if median(motion) < cfg.motion_context_threshold_g else "high_motion"
    return feats, ctx, "ok"


@dataclass
class WorkerEvaluation:
    worker: str
    flag: FlagResult
    current_score: Optional[float]
    current_context: Optional[str]
    reference_state: Dict[str, str]
    windows: List[dict]

    def to_dict(self):
        d = asdict(self)
        return d


def evaluate_worker(worker: str, records: Sequence[Mapping], baseline_end: datetime,
                    as_of: datetime, cfg: PhysioConfig, data_origin: str = "synthetic") -> WorkerEvaluation:
    """Evaluate Eq. (1)-(3) for one worker at time `as_of`.

    records: this worker's accepted (non-conflicting) physio records already
    filtered to received_at <= as_of. Reference windows come strictly before
    baseline_end. A window counts as eligible only if its records arrived within
    the freshness horizon of the window end: delayed backlog extends history but
    does not make a past window retroactively eligible for a warning.
    """
    from .util import parse_ts
    W = timedelta(seconds=cfg.window_s)
    # bucket records by window index relative to baseline_end
    def widx(t: datetime) -> int:
        return int((t - baseline_end) // W)

    buckets: Dict[int, List[Mapping]] = {}
    for r in records:
        mt = parse_ts(r.get("measured_at"))
        rt = parse_ts(r.get("received_at"))
        if mt is None:
            continue
        i = widx(mt)
        w_end = baseline_end + (i + 1) * W
        r2 = dict(r)
        r2["_timely"] = rt is not None and (rt - w_end).total_seconds() <= cfg.freshness_s
        buckets.setdefault(i, []).append(r2)
    # reference sets (windows entirely before baseline_end)
    ref_vals: Dict[Tuple[str, str], List[float]] = {}
    for i, recs in buckets.items():
        if i >= 0:
            continue
        feats, ctx, _ = _window_features(recs, cfg, data_origin)
        if feats is None or ctx is None:
            continue
        for k, v in feats.items():
            ref_vals.setdefault((k, ctx), []).append(v)
    refs = {}
    for k in cfg.features:
        for ctx in ("low_motion", "high_motion"):
            refs[(k, ctx)] = build_reference(ref_vals.get((k, ctx), []), k, ctx,
                                             cfg.eps.get(k, 0.1), cfg.min_reference_windows)
    cur = widx(as_of - timedelta(microseconds=1))
    windows = []
    seq = []
    for i in range(cur - cfg.L + 1, cur + 1):
        recs = [r for r in buckets.get(i, []) if r["_timely"]]
        w_end = baseline_end + (i + 1) * W
        feats, ctx, why = _window_features(recs, cfg, data_origin) if i >= 0 else (None, None, "baseline period")
        e, d = False, None
        if feats is not None and ctx is not None:
            z = {k: robust_z(feats[k], refs[(k, ctx)]) for k in cfg.features}
            if any(v is None for v in z.values()):
                why = "uncalibrated reference for context " + ctx
            else:
                d = weighted_score(z, cfg.features, cfg.z_max)
                e = d is not None
        windows.append({"window_end": fmt_ts(w_end), "eligible": e, "score": None if d is None else round(d, 3),
                        "context": ctx, "reason": why if not e else "eligible"})
        seq.append((e, d))
    flag = persistent_flag(seq, cfg.L, cfg.v_min, cfg.rho, cfg.tau)
    ref_state = {f"{k}|{c}": refs[(k, c)].state for (k, c) in refs}
    cur_w = windows[-1] if windows else {}
    return WorkerEvaluation(worker, flag, cur_w.get("score"), cur_w.get("context"), ref_state, windows)
