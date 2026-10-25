"""RESCUE LOGISTICS: personnel accounting and team-task assignment.

Torstensson et al. (2026) Sec. 3.9.1, Eq. (8)-(9), Table 9.

* Personnel information distinguishes expected roster membership, a recent
  device observation, a direct assistance request, responder-confirmed status
  and unresolved whereabouts. Missing telemetry never implies injury or death.
* Tasks come from SOS / help requests, unaccounted persons (with last confirmed
  location) and possible presence cues in zones with impact or gas evidence
  ("check" tasks -- never "victim").
* Urgency h_j and priority p_j are command-assigned (policy file); the agent
  never issues medical triage categories and never selects building entry
  routes. delta_rj is a "qualified estimate" from a zone distance matrix.
* Unknown eligibility or access -> 0 for automatic recommendation plus an
  explicit escalation record. A task is never abandoned.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .assignment import AssignmentProblem, solve_lexicographic
from .incident_state import IncidentState
from .ingest import Dataset
from .util import fmt_ts, parse_ts

ACCOUNTED_VALUES = {"accounted", "assisted", "evacuated_to_assembly", "accounted_at_assembly", "handed_to_medical"}
ACCOUNTING_SOURCES = {"responder_report", "operator_report"}   # incident coordination inputs
RESTRICTIVE_ASSESSMENTS = {"restricted_access", "entry_restricted", "unsafe", "no_entry"}
NOT_FOUND_VALUES = {"not_found_at_last_location", "whereabouts_unresolved"}


# ---------------------------------------------------------------------------
# Personnel accounting reconciliation
# ---------------------------------------------------------------------------

@dataclass
class PersonRecord:
    worker: str
    expected_zone: Optional[str]
    status: str                       # responder_confirmed | accounted_by_report | assistance_requested | recent_device_observation | unaccounted | unresolved
    category: str                     # known | assistance_requested | observed_not_location_confirmed | unaccounted | unresolved
    last_telemetry_at: Optional[str]
    last_telemetry_zone: Optional[str]
    responder_report: Optional[dict]
    assistance_requests: List[dict]
    last_confirmed_location: Dict[str, Any]
    notes: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def reconcile_personnel(ds: Dataset, state: IncidentState, as_of: datetime, policy: Mapping) -> List[PersonRecord]:
    fr = policy.get("freshness_s", {})
    obs_h = fr.get("personnel_observation", 60)
    rep_h = fr.get("responder_report", 1800)
    last_tel: Dict[str, dict] = {}
    for r in ds.physio:
        w = ds.device_map.get(r.get("device_id"), r.get("worker_pseudonym"))
        if not w:
            continue
        t = r.get("measured_at")
        if t and (w not in last_tel or t > last_tel[w].get("measured_at")):
            last_tel[w] = r
    dev_of: Dict[str, List[str]] = {}
    for d, w in ds.device_map.items():
        dev_of.setdefault(w, []).append(d)
    requests: Dict[str, List[dict]] = {}
    reports: Dict[str, List[dict]] = {}
    for e in ds.events:
        et = e.get("event_type")
        if et in ("sos", "help_request") and e.get("source_class") == "personnel_node":
            w = ds.device_map.get(e.get("device_id"))
            if w:
                requests.setdefault(w, []).append(e)
        if et == "personnel_accounting":
            w = (e.get("provenance") or {}).get("worker")
            if w:
                reports.setdefault(w, []).append(e)
    out = []
    for w in sorted(ds.worker_zone):
        zexp = ds.worker_zone[w]
        notes = []
        tel = last_tel.get(w)
        tel_t = parse_ts(tel.get("measured_at")) if tel else None
        recent = tel_t is not None and (as_of - tel_t).total_seconds() <= obs_h
        reps = sorted(reports.get(w, []), key=lambda e: e.get("observed_at") or "")
        resp = reps[-1] if reps else None
        # responder reports and incident-coordination (operator) reconciliations are accepted
        # accounting sources; anything else is shown but not used
        resp_by_responder = resp is not None and resp.get("source_class") in ACCOUNTING_SOURCES
        if resp is not None and not resp_by_responder:
            notes.append(f"latest accounting report from {resp.get('source_class')}: not an accepted accounting source")
        elif resp is not None and resp.get("source_class") == "operator_report" and \
                not (resp.get("provenance") or {}).get("responder_confirmed"):
            notes.append("accounting by operator roll call / coordination report (not responder-confirmed)")
        reqs = sorted(requests.get(w, []), key=lambda e: e.get("observed_at") or "")
        open_reqs = [e for e in reqs if e.get("ack_state") != "resolved"
                     and not (resp_by_responder and resp.get("value") in ACCOUNTED_VALUES
                              and (resp.get("observed_at") or "") > (e.get("observed_at") or ""))]
        if len(dev_of.get(w, [])) > 1:
            notes.append("several devices mapped to this pseudonym: identity rule requires review")
        loc: Dict[str, Any]
        if resp_by_responder and (resp.get("provenance") or {}).get("location_zone"):
            loc = {"zone_id": resp["provenance"]["location_zone"], "basis": f"{resp.get('source_class')} (last confirmed)",
                   "at": resp["provenance"].get("location_at") or resp.get("observed_at")}
        elif tel is not None:
            loc = {"zone_id": tel.get("zone_id") or zexp,
                   "basis": "last device telemetry (gateway/device location is not the person's current position)",
                   "at": tel.get("measured_at")}
        else:
            loc = {"zone_id": zexp, "basis": "roster expected zone (never observed)", "at": None}
        if open_reqs:
            last_req = open_reqs[-1]
            loc = {"zone_id": last_req.get("zone_id") or loc["zone_id"],
                   "basis": "assistance request zone (location uncertain)" if not last_req.get("zone_id") else "assistance request zone",
                   "at": last_req.get("observed_at")}
        resp_fresh = resp_by_responder and parse_ts(resp.get("observed_at")) is not None and \
            (as_of - parse_ts(resp.get("observed_at"))).total_seconds() <= rep_h
        if open_reqs:
            status, cat = "assistance_requested", "assistance_requested"
        elif resp_by_responder and resp.get("value") in NOT_FOUND_VALUES:
            status, cat = "unresolved", "unresolved"
            notes.append("responder could not confirm at last location; no inference of injury or death")
        elif resp_by_responder and resp.get("value") in ACCOUNTED_VALUES and resp_fresh:
            confirmed = resp.get("source_class") == "responder_report" or (resp.get("provenance") or {}).get("responder_confirmed")
            status, cat = ("responder_confirmed" if confirmed else "accounted_by_report"), "known"
        elif recent:
            status, cat = "recent_device_observation", "observed_not_location_confirmed"
            if resp_by_responder and not resp_fresh:
                notes.append("responder confirmation older than freshness horizon")
        else:
            status, cat = "unaccounted", "unaccounted"
            if resp_by_responder and resp.get("value") in ACCOUNTED_VALUES:
                notes.append("responder confirmation is stale: re-confirmation required")
                status, cat = "unresolved", "unresolved"
            notes.append("no recent observation and no current responder confirmation; "
                         "silence is not evidence of injury or death")
        out.append(PersonRecord(
            w, zexp, status, cat, tel.get("measured_at") if tel else None,
            tel.get("zone_id") if tel else None,
            {"event_id": resp.get("event_id"), "value": resp.get("value"), "observed_at": resp.get("observed_at"),
             "source_class": resp.get("source_class")} if resp else None,
            [{"event_id": e.get("event_id"), "event_type": e.get("event_type"), "observed_at": e.get("observed_at"),
              "zone_id": e.get("zone_id"), "ack_state": e.get("ack_state")} for e in open_reqs],
            loc, notes))
    return out


# ---------------------------------------------------------------------------
# Task generation
# ---------------------------------------------------------------------------

@dataclass
class RescueTask:
    task_id: str
    kind: str
    zone_id: Optional[str]
    site_id: Optional[str]
    h: int
    p: int
    competencies: List[str]
    ppe: List[str]
    teams_required: int
    subject: Dict[str, Any]
    evidence: List[str]
    label_uk: str
    access: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _required_ppe(zone_flags: Mapping[str, bool], policy: Mapping) -> List[str]:
    rp = policy.get("rescue", {})
    hp = rp.get("hazard_ppe", {})
    ppe = set()
    if zone_flags.get("gas_evidence"):
        ppe.update(hp.get("gas", []))
    if zone_flags.get("observation_gap") and rp.get("unknown_hazard_requires_ppe", True):
        ppe.update(hp.get("gas", []))
    if zone_flags.get("impact_evidence") and zone_flags.get("structural_unknown"):
        ppe.update(hp.get("impact_unassessed", []))
    return sorted(ppe)


def generate_tasks(ds: Dataset, state: IncidentState, people: List[PersonRecord], policy: Mapping) -> List[RescueTask]:
    kinds = policy.get("rescue", {}).get("task_kinds", {})
    overrides = policy.get("rescue", {}).get("task_overrides", {})
    multi = set(policy.get("rescue", {}).get("multi_team_task_kinds", []))
    tasks: List[RescueTask] = []

    def mk(kind, zid, subject, evidence, notes=()):
        k = kinds.get(kind, {})
        site = ds.zones.get(zid, {}).get("site_id") if zid else None
        tid = f"RT-{kind}-{subject.get('worker') or subject.get('device') or zid}"
        flags = state.zone_flags(zid) if zid else {}
        t = RescueTask(tid, kind, zid, site, int(k.get("h", 0)), int(k.get("p", 1)),
                       list(k.get("competencies", [])), _required_ppe(flags, policy),
                       int(k.get("teams_required", 1)) if kind not in multi else max(2, int(k.get("teams_required", 2))),
                       subject, list(evidence), k.get("label_uk", kind), notes=list(notes))
        ov = overrides.get(tid)
        if ov:
            t.h = int(ov.get("h", t.h))
            t.p = int(ov.get("p", t.p))
            t.notes.append("urgency/priority overridden by incident command policy")
        tasks.append(t)

    # SOS / help requests from personnel nodes
    for pr in people:
        for req in pr.assistance_requests:
            kind = "assist_sos" if req["event_type"] == "sos" else "assist_help_request"
            notes = []
            if not req.get("zone_id"):
                notes.append("request location uncertain: last known zone used")
            mk(kind, pr.last_confirmed_location.get("zone_id"), {"worker": pr.worker, "request_event": req["event_id"]},
               [req["event_id"]], notes)
            break   # one task per person
    # stationary SOS buttons (person unknown)
    for zid, z in state.zones.items():
        for a in z.P:
            if a.kind == "sos" and a.source_class == "stationary_node" and a.status == "current":
                mk("assist_sos", zid, {"device": a.source_id, "request_event": a.event_ids[0] if a.event_ids else None,
                                       "person": "unknown (stationary button)"}, a.event_ids)
    # unaccounted / unresolved persons
    for pr in people:
        if pr.category in ("unaccounted", "unresolved"):
            mk("locate_unaccounted", pr.last_confirmed_location.get("zone_id"),
               {"worker": pr.worker, "last_confirmed_location": pr.last_confirmed_location},
               [], ["task is to establish whereabouts; no casualty inference from silence"])
    # presence cues in zones with impact or gas evidence
    for zid, z in state.zones.items():
        f = z.summary.get("flags", {})
        if f.get("presence_cue_current") and (f.get("impact_evidence") or f.get("gas_evidence")):
            cues = [a for a in z.P if a.kind in ("presence_cue", "presence", "acoustic_presence_cue") and a.status == "current"]
            ev = [eid for a in cues for eid in a.event_ids] or [a.assertion_id for a in cues]
            mk("check_presence_cue", zid, {"zone": zid, "cues": len(cues)}, ev,
               ["possible presence cue only: cannot establish that a person is trapped, alive or conscious"])
    # deduplicate by id
    seen, uniq = set(), []
    for t in tasks:
        if t.task_id in seen:
            continue
        seen.add(t.task_id)
        uniq.append(t)
    return uniq


# ---------------------------------------------------------------------------
# Eligibility e_rj, access a_j, estimate delta_rj
# ---------------------------------------------------------------------------

def access_for(zone_id: Optional[str], kind: str, teams_doc: Mapping, as_of: datetime, domain: str = "rescue",
               restriction: Optional[Mapping] = None) -> Dict[str, Any]:
    """Latest applicable access authorisation for (zone, task kind). Unknown -> a_j = 0.

    `restriction`: a current qualified structural assessment restricting entry
    ({"state", "observed_at", "assessor"}). It sets a_j = 0 unless incident
    command issued an authorisation for this scope AFTER the assessment.
    """
    best = None
    for a in teams_doc.get("access", []) or []:
        if a.get("zone_id") != zone_id:
            continue
        scope = a.get("scope") or ["all"]
        if not ("all" in scope or kind in scope or domain in scope):
            continue
        vf, vu = parse_ts(a.get("valid_from")), parse_ts(a.get("valid_until"))
        if vf and as_of < vf:
            continue
        if vu and as_of > vu:
            continue
        if best is None or (a.get("valid_from") or "") >= (best.get("valid_from") or ""):
            best = a
    if restriction and (best is None or (best.get("valid_from") or "") <= (restriction.get("observed_at") or "")):
        return {"a": 0, "status": "restricted_by_assessment", "authorised_by": None,
                "assessment": dict(restriction),
                "escalation": (f"zone {zone_id}: qualified assessment '{restriction.get('state')}' restricts entry; "
                               "incident command must authorise any entry; task retained (not abandoned)")}
    if best is None:
        return {"a": 0, "status": "unknown", "authorised_by": None,
                "escalation": f"access authorisation for zone {zone_id} unknown: incident command decision required; task retained (not abandoned)"}
    st = best.get("status", "unknown")
    a = 1 if st == "authorised" else 0
    rec = {"a": a, "status": st, "authorised_by": best.get("authorised_by"), "conditions": best.get("conditions", []),
           "valid_from": best.get("valid_from"), "valid_until": best.get("valid_until")}
    if not a:
        rec["escalation"] = f"access to zone {zone_id} is '{st}': incident command review required; task retained"
    return rec


def team_available(team: Mapping, as_of: datetime) -> bool:
    if team.get("available") is False:
        return False
    af, au = parse_ts(team.get("available_from")), parse_ts(team.get("available_until"))
    if af and as_of < af:
        return False
    if au and as_of > au:
        return False
    return True


def zone_distance(teams_doc: Mapping, a: Optional[str], b: Optional[str]) -> Optional[float]:
    if a is None or b is None:
        return None
    if a == b:
        return 0.0
    m = teams_doc.get("zone_distance_m") or {}
    v = (m.get(a) or {}).get(b)
    if v is None:
        v = (m.get(b) or {}).get(a)
    return None if v is None else float(v)


def estimate_delta(team: Mapping, task: RescueTask, teams_doc: Mapping, policy: Mapping) -> Optional[int]:
    """Qualified estimate (seconds): team `eta_min` for the zone if supplied (P1 format),
    else zone distance / speed; plus the policy setup time for the task kind."""
    setup0 = policy.get("rescue", {}).get("task_kinds", {}).get(task.kind, {}).get("setup_s", 0)
    eta = (team.get("eta_min") or {}).get(task.zone_id) if task.zone_id else None
    if eta is not None:
        return int(round(float(eta) * 60 + setup0))
    d = zone_distance(teams_doc, team.get("location_zone"), task.zone_id)
    if d is None:
        return None
    speed = float(teams_doc.get("travel_speed_m_per_s") or policy.get("rescue", {}).get("travel_speed_m_per_s", 1.2))
    setup = policy.get("rescue", {}).get("task_kinds", {}).get(task.kind, {}).get("setup_s", 0)
    return int(round(d / speed + setup))


RESCUE_SKILLS = {"search", "first_aid", "search_and_rescue", "casualty_extraction", "rope_rescue", "medical_support"}
RECOVERY_SKILLS = {"electrical", "comms", "water_systems", "debris_clearance", "gas_detection", "electrical_isolation",
                   "utility_restoration", "backup_power", "gas_detection_qualified_instrument", "hazmat"}


def team_role(team: Mapping) -> str:
    """Explicit role, else a documented inference from competencies (overridable by policy)."""
    if team.get("role"):
        return team["role"]
    comp = set(team.get("competencies", []))
    if comp and comp <= {"structural_assessment"}:
        return "assessment"
    if comp & RESCUE_SKILLS:
        return "rescue"
    if comp & RECOVERY_SKILLS:
        return "recovery"
    return "rescue"


def team_competencies(team: Mapping, policy: Mapping) -> set:
    aliases = policy.get("competency_aliases", {})
    comp = set(team.get("competencies", []))
    for c in list(comp):
        comp.update(aliases.get(c, []))
    return comp


def effective_teams(teams_doc: Mapping, policy: Mapping) -> List[dict]:
    """Team records with command-supplied overrides (policy `team_overrides`) applied."""
    over = policy.get("team_overrides", {})
    out = []
    for t in teams_doc.get("teams", []) or []:
        if not t.get("team_id"):
            continue
        tt = dict(t)
        tt.update(over.get(t["team_id"], {}))
        tt["role"] = team_role(tt)
        tt["effective_competencies"] = sorted(team_competencies(tt, policy))
        out.append(tt)
    return out


def merged_access(teams_doc: Mapping, policy: Mapping) -> Dict[str, Any]:
    """Access authorisations from teams.json plus incident-command input in the policy."""
    doc = dict(teams_doc or {})
    doc["access"] = list(teams_doc.get("access", []) or []) + list(policy.get("access", []) or [])
    return doc


def zone_restrictions(state: IncidentState) -> Dict[str, dict]:
    out = {}
    for zid, z in state.zones.items():
        st = z.summary.get("structural", {})
        if st.get("state") in RESTRICTIVE_ASSESSMENTS:
            a = next((x for x in z.M if x.assertion_id == st.get("assertion_id")), None)
            out[zid] = {"state": st["state"], "assessor": st.get("assessor"),
                        "observed_at": a.observed_at if a else None, "valid_until": st.get("valid_until")}
    return out


def eligibility(team: Mapping, task: RescueTask, as_of: datetime) -> Tuple[int, List[str]]:
    why = []
    if team.get("role", "rescue") != "rescue":
        why.append("team role is not rescue")
    if not team_available(team, as_of):
        why.append("team not available in this planning interval")
    miss_c = sorted(set(task.competencies) - set(team.get("effective_competencies", team.get("competencies", []))))
    if miss_c:
        why.append("missing competencies: " + ",".join(miss_c))
    miss_p = sorted(set(task.ppe) - set(team.get("ppe", [])))
    if miss_p:
        why.append("missing PPE for zone hazard: " + ",".join(miss_p))
    return (0 if why else 1), why


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def plan_rescue(ds: Dataset, state: IncidentState, as_of: datetime, policy: Mapping) -> Dict[str, Any]:
    people = reconcile_personnel(ds, state, as_of, policy)
    tasks = generate_tasks(ds, state, people, policy)
    teams_doc = merged_access(ds.teams or {}, policy)
    teams = effective_teams(teams_doc, policy)
    restr = zone_restrictions(state)
    single = [t for t in tasks if t.teams_required <= 1]
    multi = [t for t in tasks if t.teams_required > 1]
    escalations = []
    allowed: Dict[Tuple[str, str], int] = {}
    pair_info: Dict[Tuple[str, str], dict] = {}
    for t in single:
        t.access = access_for(t.zone_id, t.kind, teams_doc, as_of, restriction=restr.get(t.zone_id))
        if t.access["a"] == 0:
            escalations.append({"task_id": t.task_id, "type": "access", "detail": t.access.get("escalation")})
        for tm in teams:
            e, why = eligibility(tm, t, as_of)
            d = estimate_delta(tm, t, teams_doc, policy)
            if d is None:
                why = why + ["no qualified time estimate (zone distance unknown)"]
            ok = e == 1 and t.access["a"] == 1 and d is not None
            pair_info[(tm["team_id"], t.task_id)] = {"e": e, "a": t.access["a"], "delta_s": d, "why_not": why}
            if ok:
                allowed[(tm["team_id"], t.task_id)] = d
    prob = AssignmentProblem([tm["team_id"] for tm in teams], [t.task_id for t in single],
                             {t.task_id: t.h for t in single}, {t.task_id: t.p for t in single}, allowed)
    pairs, triple = solve_lexicographic(prob)
    assigned = {j: r for r, j in pairs}
    by_id = {t.task_id: t for t in tasks}
    unassigned = []
    for t in single:
        if t.task_id in assigned:
            continue
        reasons = []
        if t.access["a"] == 0:
            reasons.append(t.access.get("escalation"))
        elig = [r for (r, j) in allowed if j == t.task_id]
        if not elig and t.access["a"] == 1:
            agg = {}
            for tm in teams:
                for wn in pair_info[(tm["team_id"], t.task_id)]["why_not"]:
                    agg.setdefault(wn, []).append(tm["team_id"])
            reasons.extend(f"{k} [{', '.join(v)}]" for k, v in sorted(agg.items()))
            if not teams:
                reasons.append("no team records")
        elif elig:
            reasons.append("all eligible teams (" + ", ".join(sorted(elig)) + ") assigned to tasks ranked higher by Eq. (9)")
        unassigned.append({"task_id": t.task_id, "kind": t.kind, "zone_id": t.zone_id, "urgent": bool(t.h),
                           "priority": t.p, "limiting_constraints": reasons,
                           "status": "unresolved task requiring review (not low priority, not abandoned)"})
        if not (t.access["a"] == 0):
            escalations.append({"task_id": t.task_id, "type": "unassigned", "detail": "; ".join(reasons)})
    for t in multi:
        unassigned.append({"task_id": t.task_id, "kind": t.kind, "zone_id": t.zone_id, "urgent": bool(t.h),
                           "priority": t.p, "limiting_constraints": ["multi-team task: requires separate resource model (Eq. 8 covers single-team tasks only)"],
                           "status": "flagged for separate resource model"})
    n_urgent = sum(1 for t in single if t.h)
    elig_teams = {r for (r, _) in allowed}
    active = []
    if n_urgent > len(elig_teams):
        active.append(f"urgent tasks ({n_urgent}) exceed teams eligible for any task ({len(elig_teams)})")
    if any(u["urgent"] for u in unassigned):
        active.append("one-team-per-task / one-task-per-team capacity (Eq. 8)")
    if any(t.access["a"] == 0 for t in single):
        active.append("access authorisation x_rj <= a_j (unknown or restricted access)")
    if any(any("missing PPE" in w for w in pi["why_not"]) for pi in pair_info.values()):
        active.append("PPE requirement for hazard zones (eligibility e_rj)")
    if any(any("missing competencies" in w for w in pi["why_not"]) for pi in pair_info.values()):
        active.append("competency requirement (eligibility e_rj)")
    assignments = []
    for r, j in sorted(pairs, key=lambda x: (-by_id[x[1]].h, -by_id[x[1]].p, x[1])):
        t = by_id[j]
        assignments.append({"team_id": r, "task_id": j, "kind": t.kind, "zone_id": t.zone_id, "urgent": bool(t.h),
                            "priority": t.p, "delta_s": allowed[(r, j)],
                            "delta_label": "qualified estimate (zone distance / speed + setup); not a validated route",
                            "ppe_required": t.ppe})
    counts: Dict[str, int] = {}
    for pr in people:
        counts[pr.category] = counts.get(pr.category, 0) + 1
    return {
        "as_of": fmt_ts(as_of),
        "personnel": [p.to_dict() for p in people],
        "personnel_counts": counts,
        "tasks": [t.to_dict() for t in tasks],
        "assignments": assignments,
        "unassigned": unassigned,
        "unassigned_urgent": [u for u in unassigned if u["urgent"]],
        "active_limiting_constraints": active,
        "escalations": escalations,
        "objective": {"urgent_assigned": triple[0], "total_priority": triple[1], "total_estimated_time_s": -triple[2]},
        "teams_considered": [{"team_id": t["team_id"], "role": t["role"], "competencies": t["effective_competencies"],
                              "ppe": t.get("ppe", []), "available": team_available(t, as_of)} for t in teams],
        "solver": {"method": "lexicographic Eq. (9) via exact max-weight bipartite matching (Hungarian / Kuhn-Munkres, integer scaled weights)",
                   "exact": True, "teams": len(teams), "single_team_tasks": len(single), "multi_team_tasks": len(multi),
                   "eligible_pairs": len(allowed)},
        "pairs": {f"{r}|{j}": v for (r, j), v in sorted(pair_info.items())},
        "boundary": ("Proposal only. No medical triage, no building entry route selection, no casualty inference. "
                     "Coefficients are policy values, not survival probabilities. Authorisation: rescue coordinator / incident command."),
    }
