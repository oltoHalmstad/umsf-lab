"""CONSEQUENCE-LIQUIDATION LOGISTICS: candidate recovery schedule.

Table 9, "Recovery scheduling": candidate resource-compatible tasks and
unresolved prerequisites; authorised recovery management decides; industrial
actuation remains outside this service.

Method (deterministic):
1. Generate recovery tasks from the source-qualified incident state and the
   continuity result (policy templates; command may add explicit tasks).
2. Hard prerequisites: no entry task in an impacted/hazard zone before the
   structural inspection by a qualified assessor and the hazard check with a
   qualified instrument; an assessment restricting entry blocks entry tasks.
3. Tasks lacking access authorisation, a competent crew or equipment are
   BLOCKED (listed with reasons, never silently dropped); their successors are
   blocked transitively.
4. Critical-path method (earliest/latest start, slack) on the schedulable set.
5. Serial schedule-generation scheme (SGS) with priority rule
   (min latest start, then max priority, then id) under crew (unit capacity,
   competencies) and equipment (cumulative capacity) constraints.
Tasks of an actuation kind (restart production, switch power feed, operate
ventilation, unlock, stop process) are never scheduled.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .continuity import ContinuityResult, OPTIMAL
from .incident_state import IncidentState
from .ingest import Dataset
from .rescue import (RESTRICTIVE_ASSESSMENTS, access_for, effective_teams, merged_access, team_available,
                     zone_restrictions)
from .util import add_s, fmt_ts, parse_ts


@dataclass
class RecoveryTask:
    task_id: str
    kind: str
    zone_id: Optional[str]
    title_uk: str
    competencies: List[str]
    equipment: Dict[str, int]
    duration_s: int
    priority: int
    prerequisites: List[str] = field(default_factory=list)
    satisfied_by_evidence: List[str] = field(default_factory=list)
    entry: bool = True
    linked_service: Optional[str] = None
    reason: str = ""
    release_s: int = 0
    blocked_reasons: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _zone_needs(state: IncidentState, zid: str) -> Tuple[bool, bool, Optional[dict]]:
    """(needs structural inspection, needs hazard check, current qualified assessment)."""
    z = state.zones.get(zid)
    if z is None:
        return False, False, None
    f = z.summary.get("flags", {})
    st = z.summary.get("structural", {})
    assessed = st if st.get("state") not in (None, "unknown") else None
    impacted = f.get("impact_evidence") or f.get("possible_impact_local")
    needs_struct = bool(impacted) and assessed is None
    needs_haz = bool(f.get("gas_evidence") or impacted)
    return needs_struct, needs_haz, assessed


def generate_recovery_tasks(ds: Dataset, state: IncidentState, cont: ContinuityResult,
                            policy: Mapping) -> Tuple[List[RecoveryTask], List[dict], List[dict]]:
    rp = policy.get("recovery", {})
    tpl = rp.get("task_templates", {})
    tasks: Dict[str, RecoveryTask] = {}
    excluded: List[dict] = []
    order: List[dict] = []

    def add(kind: str, zid: Optional[str], reason: str, linked: Optional[str] = None, prio_bonus: int = 0) -> Optional[str]:
        t = tpl.get(kind)
        if t is None:
            return None
        tid = f"RC-{kind}-{zid or 'site'}"
        if tid in tasks:
            tasks[tid].priority = max(tasks[tid].priority, int(t.get("priority", 0)) + prio_bonus)
            return tid
        tasks[tid] = RecoveryTask(tid, kind, zid, t.get("title_uk", kind), list(t.get("competencies", [])),
                                  {k: int(v) for k, v in (t.get("equipment") or {}).items()},
                                  int(t.get("duration_s", 1800)), int(t.get("priority", 0)) + prio_bonus,
                                  entry=bool(t.get("entry", True)), linked_service=linked, reason=reason)
        return tid

    for zid, z in sorted(state.zones.items()):
        needs_struct, needs_haz, assessed = _zone_needs(state, zid)
        f = z.summary.get("flags", {})
        if needs_haz:
            add("gas_hazard_check", zid, "gas-channel response or impact evidence: hazard check with qualified instrument")
        if needs_struct:
            add("structural_inspection", zid, "mechanical excursion / possible_impact_local and no qualified structural assessment")
        if f.get("possible_impact_local"):
            add("debris_clearance", zid, "possible_impact_local composite in zone (unverified): debris clearance candidate")
        if any(a.kind == "observation_gap" and a.status == "current" and any("link loss" in n for n in a.notes)
               for a in z.U):
            add("comms_restoration", zid, "link loss: monitoring path restoration", "communications")

    # continuity linkage: which services to restore first
    services = {s.get("service_id"): s for s in (ds.assets.get("services") or [])}
    restore_map = rp.get("service_restoration_task", {})
    if cont.status == OPTIMAL:
        unsupported = [sid for sid, v in cont.y.items() if v == 0]
    else:
        unsupported = list(cont.y.keys())
    def svc_rank(sid):
        s = services.get(sid, {})
        return (0 if s.get("mandatory") else 1, -float(s.get("priority_weight", 0)), sid)
    for sid in sorted(unsupported, key=svc_rank):
        s = services.get(sid, {})
        kind = restore_map.get(sid)
        why = ("mandatory service not supportable (continuity INFEASIBLE)" if cont.status != OPTIMAL and s.get("mandatory")
               else "service not supported in continuity proposal")
        entry = {"service_id": sid, "mandatory": bool(s.get("mandatory")), "weight": s.get("priority_weight"),
                 "reason": why, "task": None}
        if s.get("actuation_required_to_restore") or sid in ("production",):
            excluded.append({"service_id": sid, "kind": "restart_production" if sid == "production" else "actuation",
                             "reason": "restoration requires industrial actuation: outside this service; authorised operator procedure only"})
            entry["task"] = "excluded (actuation)"
        elif kind:
            bonus = (100 if s.get("mandatory") else 0) + int(10 * float(s.get("priority_weight", 0)))
            entry["task"] = add(kind, s.get("zone_id"), why, sid, bonus)
        order.append(entry)
    # capacity-raising task when power/energy limits the plan or the plan is infeasible
    power_limited = cont.status != OPTIMAL or any(k in ("power_kw", "energy_kwh") for k in cont.binding_resources)
    if power_limited:
        pz = ds.assets.get("temporary_power_zone")
        bonus = 120 if cont.status != OPTIMAL else 20
        tid = add("temporary_power_path", pz, "power/energy capacity limits the continuity proposal", "power_kw", bonus)
        order.insert(0, {"service_id": "(capacity) power_kw", "mandatory": cont.status != OPTIMAL,
                         "weight": None, "reason": "raises the justified lower bound of usable power", "task": tid})
    # explicit command-supplied tasks
    for et in ds.assets.get("recovery_tasks", []) or []:
        kind = et.get("kind", "custom")
        if kind in rp.get("actuation_task_kinds", []):
            excluded.append({"task_id": et.get("task_id"), "kind": kind,
                             "reason": "industrial actuation: never scheduled by this service"})
            continue
        tid = et.get("task_id") or f"RC-{kind}-{et.get('zone_id') or 'site'}"
        tasks[tid] = RecoveryTask(tid, kind, et.get("zone_id"), et.get("title_uk", kind),
                                  list(et.get("competencies", [])), {k: int(v) for k, v in (et.get("equipment") or {}).items()},
                                  int(et.get("duration_s", 1800)), int(et.get("priority", 0)),
                                  list(et.get("prerequisites", [])), entry=bool(et.get("entry", True)),
                                  reason="command-supplied task")
    # template-defined actuation tasks are excluded as well
    for kind in rp.get("actuation_task_kinds", []):
        for tid in [k for k, t in tasks.items() if t.kind == kind]:
            excluded.append({"task_id": tid, "kind": kind, "reason": "industrial actuation: never scheduled"})
            del tasks[tid]

    # hard prerequisites
    for t in tasks.values():
        if not t.entry or not t.zone_id:
            continue
        needs_struct, needs_haz, assessed = _zone_needs(state, t.zone_id)
        tmpl = tpl.get(t.kind, {})
        if t.kind != "gas_hazard_check" and needs_haz and tmpl.get("requires_hazard_clearance", True):
            pre = f"RC-gas_hazard_check-{t.zone_id}"
            if pre in tasks and pre not in t.prerequisites:
                t.prerequisites.append(pre)
        if t.kind not in ("structural_inspection", "gas_hazard_check"):
            pre = f"RC-structural_inspection-{t.zone_id}"
            if needs_struct and pre in tasks and pre not in t.prerequisites:
                t.prerequisites.append(pre)
            if assessed:
                t.satisfied_by_evidence.append(
                    f"structural assessment {assessed.get('assertion_id')} by {assessed.get('assessor')} "
                    f"({assessed.get('state')}, valid until {assessed.get('valid_until')})")
                if assessed.get("state") in RESTRICTIVE_ASSESSMENTS:
                    t.satisfied_by_evidence[-1] += " -- restricts entry: incident command authorisation required"
    return list(tasks.values()), excluded, order


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------

def _cpm(tasks: Dict[str, RecoveryTask]) -> Dict[str, Dict[str, int]]:
    order = _topo(tasks)
    es, ef = {}, {}
    for tid in order:
        t = tasks[tid]
        es[tid] = max([t.release_s] + [ef[p] for p in t.prerequisites if p in tasks])
        ef[tid] = es[tid] + t.duration_s
    end = max(ef.values()) if ef else 0
    ls, lf = {}, {}
    succ: Dict[str, List[str]] = {tid: [] for tid in tasks}
    for tid, t in tasks.items():
        for p in t.prerequisites:
            if p in succ:
                succ[p].append(tid)
    for tid in reversed(order):
        lf[tid] = min([end] + [ls[s] for s in succ[tid]])
        ls[tid] = lf[tid] - tasks[tid].duration_s
    return {tid: {"ES": es[tid], "EF": ef[tid], "LS": ls[tid], "LF": lf[tid], "slack": ls[tid] - es[tid]}
            for tid in tasks}


def _topo(tasks: Dict[str, RecoveryTask]) -> List[str]:
    indeg = {tid: 0 for tid in tasks}
    for t in tasks.values():
        for p in t.prerequisites:
            if p in tasks:
                indeg[t.task_id] += 1
    ready = sorted(tid for tid, d in indeg.items() if d == 0)
    out = []
    while ready:
        tid = ready.pop(0)
        out.append(tid)
        for t in sorted(tasks.values(), key=lambda x: x.task_id):
            if tid in t.prerequisites:
                indeg[t.task_id] -= 1
                if indeg[t.task_id] == 0:
                    ready.append(t.task_id)
                    ready.sort()
    if len(out) != len(tasks):
        raise ValueError("cyclic prerequisites in recovery tasks")
    return out


def serial_sgs(tasks: Dict[str, RecoveryTask], crews: List[Mapping], equipment: Dict[str, int],
               cpm: Mapping[str, Mapping[str, int]]) -> Tuple[Dict[str, dict], List[dict]]:
    crew_busy: Dict[str, List[Tuple[int, int]]] = {c["team_id"]: [] for c in crews}
    eq_use: Dict[str, List[Tuple[int, int, int]]] = {k: [] for k in equipment}
    sched: Dict[str, dict] = {}
    unsched: List[dict] = []
    remaining = set(tasks)

    def crew_free(cid, s, e):
        return all(e <= a or s >= b for a, b in crew_busy[cid])

    def eq_ok(req, s, e):
        for k, q in req.items():
            cap = equipment.get(k, 0)
            if q > cap:
                return False
            pts = {s} | {a for a, b, _ in eq_use[k] if s <= a < e}
            for t in pts:
                used = sum(qq for a, b, qq in eq_use[k] if a <= t < b)
                if used + q > cap:
                    return False
        return True

    while remaining:
        elig = [tid for tid in remaining if all(p in sched for p in tasks[tid].prerequisites if p in tasks)]
        if not elig:
            for tid in sorted(remaining):
                unsched.append({"task_id": tid, "reason": "prerequisite could not be scheduled"})
            break
        elig.sort(key=lambda tid: (cpm[tid]["LS"], -tasks[tid].priority, tid))
        tid = elig[0]
        t = tasks[tid]
        remaining.discard(tid)
        t0 = max([t.release_s] + [sched[p]["finish_s"] for p in t.prerequisites if p in sched])
        capable = [c for c in crews if set(t.competencies) <= set(c.get("competencies", []))]
        cands = sorted({t0} | {b for c in capable for _, b in crew_busy[c["team_id"]] if b > t0}
                       | {b for k in t.equipment for _, b, _ in eq_use.get(k, []) if b > t0})
        placed = None
        for s in cands:
            e = s + t.duration_s
            if not eq_ok(t.equipment, s, e):
                continue
            free = [c for c in capable if crew_free(c["team_id"], s, e)]
            if free:
                placed = (s, e, sorted(free, key=lambda c: c["team_id"])[0])
                break
        if placed is None:
            unsched.append({"task_id": tid, "reason": "no crew/equipment window found"})
            continue
        s, e, crew = placed
        crew_busy[crew["team_id"]].append((s, e))
        for k, q in t.equipment.items():
            eq_use[k].append((s, e, q))
        sched[tid] = {"start_s": s, "finish_s": e, "crew": crew["team_id"]}
    return sched, unsched


def plan_recovery(ds: Dataset, state: IncidentState, cont: ContinuityResult, as_of: datetime,
                  policy: Mapping, busy_teams: Optional[set] = None) -> Dict[str, Any]:
    """busy_teams: teams proposed for rescue tasks in the same interval (not available as crews)."""
    rp = policy.get("recovery", {})
    tasks, excluded, order = generate_recovery_tasks(ds, state, cont, policy)
    teams_doc = merged_access(ds.teams or {}, policy)
    restr = zone_restrictions(state)
    busy = set(busy_teams or ())
    crews = [dict(t, competencies=t["effective_competencies"]) for t in effective_teams(teams_doc, policy)
             if t["role"] in rp.get("crew_roles", ["recovery", "assessment"]) and team_available(t, as_of)
             and t["team_id"] not in busy]
    equipment: Dict[str, int] = {}
    for e in ds.assets.get("equipment", []) or []:
        if (e.get("status") or "available") == "available":
            equipment[e.get("kind")] = equipment.get(e.get("kind"), 0) + int(e.get("quantity", 1) or 0)
    # access / crews / equipment checks
    for t in tasks:
        if t.entry and t.zone_id:
            acc = access_for(t.zone_id, t.kind, teams_doc, as_of, domain="recovery", restriction=restr.get(t.zone_id))
            if acc["a"] == 0 and acc["status"] == "restricted_by_assessment":
                t.blocked_reasons.append(acc["escalation"])
            elif acc["a"] == 0:
                # a later valid_from authorisation can define a release time
                future = _future_access(t.zone_id, t.kind, teams_doc, as_of)
                if future is not None:
                    t.release_s = future
                else:
                    t.blocked_reasons.append(acc.get("escalation") or "access not authorised")
        if not any(set(t.competencies) <= set(c.get("competencies", [])) for c in crews):
            t.blocked_reasons.append("no available crew with competencies " + ",".join(t.competencies))
        for k, q in t.equipment.items():
            if equipment.get(k, 0) < q:
                t.blocked_reasons.append(f"equipment '{k}' unavailable or unknown (need {q}, verified {equipment.get(k, 0)})")
    by_id = {t.task_id: t for t in tasks}
    changed = True
    while changed:
        changed = False
        for t in tasks:
            for p in t.prerequisites:
                msg = f"prerequisite blocked: {p}"
                if p in by_id and by_id[p].blocked_reasons and msg not in t.blocked_reasons:
                    t.blocked_reasons.append(msg)
                    changed = True
    ok = {t.task_id: t for t in tasks if not t.blocked_reasons}
    cpm = _cpm(ok) if ok else {}
    sched, unsched = serial_sgs(ok, crews, equipment, cpm) if ok else ({}, [])
    makespan = max((v["finish_s"] for v in sched.values()), default=0)
    critical = [tid for tid, v in cpm.items() if v["slack"] == 0]
    rows = []
    for t in sorted(tasks, key=lambda x: (sched.get(x.task_id, {}).get("start_s", 10 ** 9), x.task_id)):
        s = sched.get(t.task_id)
        rows.append({**t.to_dict(),
                     "status": "scheduled_candidate" if s else ("blocked" if t.blocked_reasons else "unscheduled"),
                     "start": fmt_ts(add_s(as_of, s["start_s"])) if s else None,
                     "finish": fmt_ts(add_s(as_of, s["finish_s"])) if s else None,
                     "start_offset_min": round(s["start_s"] / 60, 1) if s else None,
                     "finish_offset_min": round(s["finish_s"] / 60, 1) if s else None,
                     "crew": s["crew"] if s else None,
                     "cpm": cpm.get(t.task_id), "critical": t.task_id in critical})
    unresolved = []
    for t in tasks:
        for r in t.blocked_reasons:
            unresolved.append({"task_id": t.task_id, "prerequisite": r})
    return {
        "as_of": fmt_ts(as_of),
        "tasks": rows,
        "makespan_min": round(makespan / 60, 1),
        "critical_path": [tid for tid in _topo(ok) if tid in critical] if ok else [],
        "blocked": [r for r in rows if r["status"] == "blocked"],
        "unscheduled": unsched,
        "unresolved_prerequisites": unresolved,
        "excluded_actuation": excluded,
        "restoration_order": order,
        "crews": [c["team_id"] for c in crews],
        "teams_excluded_busy_with_rescue": sorted(busy),
        "equipment": equipment,
        "solver": {"method": "CPM (earliest/latest start) + serial schedule-generation scheme, priority rule min-LS / max-priority / id",
                   "exact": False, "note": "heuristic candidate schedule (resource-constrained scheduling is NP-hard); prerequisites are hard constraints"},
        "boundary": ("Candidate schedule for authorised recovery management. Industrial actuation (switching, restarts, "
                     "ventilation, unlocking) is outside this service and never scheduled. No automated building clearance."),
    }


def _future_access(zid, kind, teams_doc, as_of) -> Optional[int]:
    best = None
    for a in teams_doc.get("access", []) or []:
        if a.get("zone_id") != zid or a.get("status") != "authorised":
            continue
        scope = a.get("scope") or ["all"]
        if not ("all" in scope or kind in scope or "recovery" in scope):
            continue
        vf = parse_ts(a.get("valid_from"))
        if vf and vf > as_of:
            d = int((vf - as_of).total_seconds())
            best = d if best is None else min(best, d)
    return best
