"""The AI AGENT orchestrator.

    observe (ingest) -> assess (physio_rules + incident_state)
      -> plan (rescue, continuity, recovery) -> propose (decision packages, Table 9)
      -> await authorisation (human role) -> log (append-only audit)

The agent is "AI" in the decision-support sense: it perceives a data stream,
maintains state, plans with exact/deterministic algorithms and proposes actions.
It never executes an action. Every package is a PROPOSAL that needs approval or
rejection (with a recorded reason) by the role named in Table 9. The optional
language model (llm.py) only writes a summary of minimised aggregates.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from . import AGENT_NAME, RULE_VERSION, __version__
from .audit import AuditLog
from .continuity import resources_from_assets, services_from_assets, solve as solve_continuity
from .incident_state import build_incident_state
from .ingest import Dataset, load_dataset
from .physio_rules import (GroupParams, PhysioConfig, decide, evaluate_worker, group_gate,
                           threshold_feasibility, POSSIBLE_GROUP_EVENT, INSUFFICIENT_EVIDENCE)
from .policy import load_policy
from .recovery import plan_recovery
from .rescue import plan_rescue
from .util import dumps, fmt_ts, parse_ts, sha256_obj

DOMAINS = [
    ("urgent_personnel_assistance", "Термінова допомога персоналу"),
    ("rescue_task_assignment", "Розподіл рятувальних завдань"),
    ("personnel_accounting", "Облік персоналу"),
    ("structural_access_status", "Стан конструкцій і доступу"),
    ("essential_service_preservation", "Збереження життєво важливих сервісів"),
    ("recovery_scheduling", "Графік ліквідації наслідків"),
    ("physiological_group_warning", "Фізіологічне групове попередження"),
]
DOMAIN_UK = dict(DOMAINS)

ROLE_UK = {
    "rescue_coordinator": "координатор рятувальних робіт",
    "emergency_coordinator": "координатор надзвичайних ситуацій",
    "incident_command": "штаб реагування (incident command)",
    "incident_coordination_team": "уповноважена група координації інциденту",
    "qualified_assessor": "кваліфікований експерт",
    "infrastructure_operator": "відповідальний оператор інфраструктури",
    "recovery_management": "уповноважене керівництво відновленням",
    "occupational_health": "фахівець з гігієни праці",
    "site_safety_officer": "відповідальний з безпеки об'єкта",
}

BOUNDARY_UK = ("Це ПРОПОЗИЦІЯ системи підтримки рішень. Вона не виконує жодних дій, не керує обладнанням, "
               "не ставить діагнозів, не призначає категорій медичного сортування і не обирає маршрути входу до будівель. "
               "Потрібне затвердження або відхилення з обґрунтуванням уповноваженою роллю.")


# ---------------------------------------------------------------------------
# Assessment helpers
# ---------------------------------------------------------------------------

def assess_physiology(ds: Dataset, as_of: datetime, policy: Mapping, urgent_by_worker: Mapping[str, List[dict]]) -> Dict[str, Any]:
    cfg = PhysioConfig.from_policy(policy.get("physio", {}))
    params = GroupParams.from_dict(policy.get("group_rule", {}))
    base_end = ds.baseline_end()
    by_worker: Dict[str, List[dict]] = {}
    for r in ds.physio:
        w = ds.device_map.get(r.get("device_id"), r.get("worker_pseudonym"))
        if w:
            by_worker.setdefault(w, []).append(r)
    zones = {}
    evals = {}
    for zid, z in sorted(ds.zones.items()):
        roster = list(z.get("expected_workers") or []) if ds.rosters else None
        flags = {}
        if base_end is None or as_of <= base_end:
            for w in roster or []:
                flags[w] = None
        else:
            for w in roster or []:
                ev = evaluate_worker(w, by_worker.get(w, []), base_end, as_of, cfg, ds.data_origin)
                evals[w] = ev
                flags[w] = ev.flag.value if ev.flag.available else None
        g = group_gate(zid, roster, flags, params)
        urgent = [u for w in (roster or []) for u in urgent_by_worker.get(w, [])]
        d = decide(g, urgent)
        zones[zid] = {"decision": d.to_dict(), "feasibility": threshold_feasibility(len(roster or []), params).to_dict()}
    workers = {w: {"flag_available": e.flag.available, "flag": e.flag.value, "reason": e.flag.reason,
                   "eligible_windows": e.flag.eligible_windows, "current_context": e.current_context,
                   "reference_state": e.reference_state}
               for w, e in sorted(evals.items())}
    return {"params": asdict(params), "config": asdict(cfg), "baseline_end": fmt_ts(base_end),
            "zones": zones, "workers_restricted": workers,
            "note": "individual physiological details are restricted to authorised roles (Sec. 3.7.2); "
                    "scores are general deviation measures, not diagnoses; HR is a synthetic field in synthetic data"}


def continuity_inputs(ds: Dataset, state) -> Dict[str, Any]:
    services, _, horizon = services_from_assets(ds.assets or {})
    reports = []
    for z in state.zones.values():
        for a in z.F:
            reports.append({"provenance": a.provenance, "status": a.status, "observed_at": a.observed_at,
                            "source_class": a.source_class, "assertion_id": a.assertion_id, "source_id": a.source_id})
    for a in state.site_context:
        if a.kind == "asset_status":
            reports.append({"provenance": a.provenance, "status": a.status, "observed_at": a.observed_at,
                            "source_class": a.source_class, "assertion_id": a.assertion_id, "source_id": a.source_id})
    resources, rows = resources_from_assets(ds.assets or {}, reports)
    # derive energy demand again with final resource set
    for s in services:
        if "energy_kwh" in resources and "energy_kwh" not in s.demand and "power_kw" in s.demand:
            s.demand["energy_kwh"] = s.demand["power_kw"] * horizon
    return {"services": services, "resources": resources, "rows": rows, "horizon_h": horizon}


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self, data_dir: str, out_dir: str, policy_path: Optional[str] = None,
                 use_llm: bool = False, auto_approve: bool = False, llm_client: Any = None,
                 interactive: bool = False, input_fn: Callable[[str], str] = input,
                 audit_path: Optional[str] = None):
        self.data_dir = data_dir
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.policy = load_policy(policy_path, data_dir)
        self.dataset = load_dataset(data_dir)
        self.use_llm = use_llm
        self.auto_approve = auto_approve
        self.llm_client = llm_client
        self.interactive = interactive
        self.input_fn = input_fn
        self.audit = AuditLog(audit_path or os.path.join(out_dir, "audit.jsonl"))
        self.first_display: Dict[str, str] = {}
        self.last_stable: Dict[str, str] = {}
        self.current_packages: Dict[str, dict] = {}
        self.timeline: List[dict] = []
        self.audit.append("session_start", {
            "agent": AGENT_NAME, "agent_version": __version__, "rule_version": RULE_VERSION,
            "data_dir": data_dir, "file_sha256": self.dataset.file_hashes,
            "policy_sha256": self.policy.get("_sha256"), "policy_sources": self.policy.get("_sources"),
            "llm_requested": use_llm, "auto_approve_for_simulation": auto_approve,
            "dataset": self.dataset.summary(),
        })

    # ---- observe / assess / plan ------------------------------------------
    def assess_and_plan(self, as_of: datetime) -> Dict[str, Any]:
        ds = self.dataset.snapshot(as_of)
        input_sha = ds.digest()
        state = build_incident_state(ds, as_of, self.policy, self.first_display)
        rescue = plan_rescue(ds, state, as_of, self.policy)
        urgent_by_worker: Dict[str, List[dict]] = {}
        for p in rescue["personnel"]:
            for r in p["assistance_requests"]:
                urgent_by_worker.setdefault(p["worker"], []).append({"worker": p["worker"], **r})
        physio = assess_physiology(ds, as_of, self.policy, urgent_by_worker)
        ci = continuity_inputs(ds, state)
        cont = solve_continuity(ci["services"], ci["resources"])
        recovery = plan_recovery(ds, state, cont, as_of, self.policy,
                                 busy_teams={a["team_id"] for a in rescue["assignments"]})
        return {
            "as_of": fmt_ts(as_of),
            "input_sha256": input_sha,
            "file_sha256": self.dataset.file_hashes,
            "policy_sha256": self.policy.get("_sha256"),
            "data_origin": self.dataset.data_origin,
            "scenario_id": self.dataset.scenario_id,
            "dataset": ds.summary() | {"quarantine": self.dataset.quarantine[:20]},
            "physiology": physio,
            "incident": state.to_dict(),
            "rescue": rescue,
            "continuity": {
                "result": cont.to_dict(),
                "services": [asdict(s) for s in ci["services"]],
                "capacity_provenance": ci["rows"],
                "horizon_h": ci["horizon_h"],
                "solver_method": f"exact {cont.method} over {cont.candidates_examined} candidates",
            },
            "recovery": recovery,
        }

    # ---- propose ----------------------------------------------------------
    def build_packages(self, res: Dict[str, Any]) -> List[dict]:
        roles = self.policy.get("decision_authority", {})
        inc = res["incident"]
        resc = res["rescue"]
        cont = res["continuity"]["result"]
        rec = res["recovery"]
        out = []

        def pkg(domain, stable, context, solver, limitations):
            sh = sha256_obj(stable)
            pid = f"PKG-{domain}-{sh[:10]}"
            return {
                "package_id": pid, "domain": domain, "title_uk": DOMAIN_UK[domain],
                "authorising_roles": roles.get(domain, []),
                "authorising_roles_uk": [ROLE_UK.get(r, r) for r in roles.get(domain, [])],
                "status": "awaiting_authorisation", "proposal": True,
                "scenario_time": res["as_of"], "created_at": fmt_ts(datetime.now(timezone.utc)),
                "input_sha256": res["input_sha256"], "policy_sha256": res["policy_sha256"],
                "versions": {"agent": __version__, "rule_version": RULE_VERSION,
                             "policy_version": self.policy.get("policy_version"), "schemas": ["1.0", "st-1.0", "ev-1.0"]},
                "solver": solver, "content": stable, "context": context, "content_sha256": sh,
                "limitations": limitations, "boundary_uk": BOUNDARY_UK, "data_origin": res["data_origin"],
                "supersedes": None, "authorisation": None,
            }

        # 1 urgent assistance (no group threshold prerequisite)
        reqs = []
        for p in resc["personnel"]:
            for r in p["assistance_requests"]:
                reqs.append({"worker": p["worker"], "event_id": r["event_id"], "type": r["event_type"],
                             "observed_at": r["observed_at"], "zone_id": r["zone_id"], "ack_state": r["ack_state"],
                             "last_confirmed_context": p["last_confirmed_location"]})
        for t in resc["tasks"]:
            if t["kind"] == "assist_sos" and t["subject"].get("device"):
                reqs.append({"worker": None, "device": t["subject"]["device"], "event_id": t["subject"].get("request_event"),
                             "type": "sos (stationary button, person unknown)", "zone_id": t["zone_id"],
                             "observed_at": None, "ack_state": "unacknowledged"})
        ages = {}
        for r in reqs:
            for pk in inc["packets"]:
                if r["event_id"] and pk["assertion_id"] == f"A-{r['event_id']}":
                    ages[r["event_id"]] = pk["age_s"]
                    r["observed_at"] = r["observed_at"] or pk["observed_at"]
        out.append(pkg("urgent_personnel_assistance", {"requests": reqs},
                       {"age_s": ages}, {"method": "direct pass-through of assistance requests", "status": "n/a"},
                       ["request location may be uncertain", "acknowledgement is not proof of assistance"]))
        # 2 rescue task assignment
        out.append(pkg("rescue_task_assignment",
                       {"assignments": resc["assignments"], "unassigned": resc["unassigned"],
                        "active_limiting_constraints": resc["active_limiting_constraints"],
                        "escalations": resc["escalations"], "objective": resc["objective"],
                        "tasks": [{k: t[k] for k in ("task_id", "kind", "zone_id", "h", "p", "competencies", "ppe", "teams_required")}
                                  for t in resc["tasks"]]},
                       {}, resc["solver"] | {"status": "OPTIMAL"},
                       ["coefficients h_j, p_j are command policy values, not survival probabilities",
                        "delta_rj is a qualified estimate, not a validated route; no entry route is selected",
                        "not calibrated or evaluated against actual rescue operations"]))
        # 3 personnel accounting
        out.append(pkg("personnel_accounting",
                       {"counts": resc["personnel_counts"],
                        "records": [{**{k: p[k] for k in ("worker", "expected_zone", "status", "category", "notes")},
                                     "last_confirmed_zone": p["last_confirmed_location"].get("zone_id"),
                                     "last_confirmed_basis": p["last_confirmed_location"].get("basis")}
                                    for p in resc["personnel"]]},
                       {"last_confirmed_at": {p["worker"]: p["last_confirmed_location"].get("at") for p in resc["personnel"]}}, {"method": "explicit identity and time reconciliation rules", "status": "n/a"},
                       ["no sensor-only casualty inference", "device/gateway location is not the person's position"]))
        # 4 structural / access status
        restr = {zid: {"state": z["summary"]["structural"]["state"], "assessor": z["summary"]["structural"].get("assessor"),
                       "observed_at": next((a["observed_at"] for a in z["M"]
                                            if a["assertion_id"] == z["summary"]["structural"].get("assertion_id")), None)}
                 for zid, z in inc["zones"].items()
                 if z["summary"]["structural"]["state"] in ("restricted_access", "entry_restricted", "unsafe", "no_entry")}
        zs = []
        for zid, z in inc["zones"].items():
            zs.append({"zone_id": zid, "structural": z["summary"].get("structural"), "hazard_state": z["summary"].get("hazard_state"),
                       "flags": z["summary"].get("flags"),
                       "rescue_access": _access_summary(self.dataset.teams, zid, parse_ts(res["as_of"]), "rescue",
                                                        self.policy, restr.get(zid)),
                       "recovery_access": _access_summary(self.dataset.teams, zid, parse_ts(res["as_of"]), "recovery",
                                                          self.policy, restr.get(zid))})
        out.append(pkg("structural_access_status", {"zones": zs, "strike_statement_en": inc["strike_statement_en"]}, {},
                       {"method": "source-linked assertions; explicit unknown", "status": "n/a"},
                       ["no automated building clearance", "local channel values are uncalibrated"]))
        # 5 service continuity
        out.append(pkg("essential_service_preservation",
                       {"status": cont["status"], "y": cont["y"], "Q_pct": cont["Q_pct"], "objective": cont["objective"],
                        "infeasibility_reasons": cont["infeasibility_reasons"], "binding_resources": cont["binding_resources"],
                        "resource_capacity": cont["resource_capacity"], "unused": cont["unused"],
                        "excluded_inadmissible": cont["excluded_inadmissible"],
                        "options_for_review": cont["options_for_review"]},
                       {"capacity_provenance": res["continuity"]["capacity_provenance"]},
                       {"method": res["continuity"]["solver_method"], "status": cont["status"],
                        "horizon_h": res["continuity"]["horizon_h"]},
                       ["Q is weighted service coverage under assumed weights, not people rescued or facility restored",
                        "no switching, startup transients or network flow modelled; no actuation",
                        "mandatory life-safety services are constraints and are never relaxed"]))
        # 6 recovery scheduling
        out.append(pkg("recovery_scheduling",
                       {"tasks": [{k: t[k] for k in ("task_id", "kind", "zone_id", "status", "crew",
                                                     "prerequisites", "blocked_reasons", "priority", "critical")}
                                  for t in rec["tasks"]],
                        "unresolved_prerequisites": rec["unresolved_prerequisites"],
                        "excluded_actuation": rec["excluded_actuation"], "restoration_order": rec["restoration_order"]},
                       {"times": {t["task_id"]: {"start": t["start"], "finish": t["finish"],
                                                 "start_offset_min": t["start_offset_min"],
                                                 "finish_offset_min": t["finish_offset_min"]} for t in rec["tasks"]},
                        "makespan_min": rec["makespan_min"]}, rec["solver"] | {"status": "CANDIDATE"},
                       ["candidate schedule; durations are planning assumptions", "industrial actuation excluded"]))
        # 7 physiological group warning (only aggregated counts)
        zw = []
        for zid, z in res["physiology"]["zones"].items():
            d = z["decision"]
            g = d["group"]
            zw.append({"zone_id": zid, "states": d["states"], "label_uk": d["label_uk"], "N": g["N"], "n": g["n"], "m": g["m"],
                       "coverage_pct": g["C_pct"], "affected_pct": g["p_pct"], "conditions": g["conditions"],
                       "urgent_requests": len(d["urgent"]), "feasibility": z["feasibility"]["note"]})
        out.append(pkg("physiological_group_warning", {"zones": zw, "params": res["physiology"]["params"]}, {},
                       {"method": "Eq. (1)-(5) deterministic", "status": "n/a"},
                       ["a group warning is a request for investigation, not a diagnosis or exposure identification",
                        "insufficient coverage is not absence of concern", "thresholds are development parameters"]))
        return out

    # ---- authorise / log --------------------------------------------------
    def _propose(self, res: Dict[str, Any]) -> List[str]:
        changed = []
        for p in self.build_packages(res):
            dom = p["domain"]
            if self.last_stable.get(dom) == p["content_sha256"]:
                continue
            prev = self.current_packages.get(dom)
            if prev:
                p["supersedes"] = prev["package_id"]
                self.audit.append("supersede", {"package_id": prev["package_id"], "by": p["package_id"],
                                                "reason": "inputs changed: proposal content differs"}, res["as_of"])
            self.current_packages[dom] = p
            self.last_stable[dom] = p["content_sha256"]
            changed.append(dom)
            self.audit.append("propose", {"package_id": p["package_id"], "domain": dom,
                                          "authorising_roles": p["authorising_roles"], "input_sha256": p["input_sha256"],
                                          "content_sha256": p["content_sha256"], "policy_sha256": p["policy_sha256"],
                                          "versions": p["versions"], "solver": p["solver"], "status": "awaiting_authorisation"},
                              res["as_of"])
            if self.auto_approve:
                self.authorise(p["package_id"], "approved", p["authorising_roles"][0] if p["authorising_roles"] else "simulation",
                               "SIMULATION-AUTO-APPROVE",
                               "--auto-approve-for-simulation: simulated authorisation, NOT a human decision",
                               res["as_of"], simulated=True)
            elif self.interactive:
                self._interactive(p, res["as_of"])
        return changed

    def _interactive(self, p: dict, at: str) -> None:
        print(f"\n[{p['package_id']}] {p['title_uk']} — authorising role(s): {', '.join(p['authorising_roles'])}")
        ans = self.input_fn("approve / reject / defer? [a/r/d]: ").strip().lower()
        if ans in ("a", "r"):
            role = self.input_fn(f"your role ({'/'.join(p['authorising_roles'])}): ").strip()
            actor = self.input_fn("your name or id: ").strip()
            reason = self.input_fn("reason: ").strip()
            try:
                self.authorise(p["package_id"], "approved" if ans == "a" else "rejected", role, actor, reason, at)
            except ValueError as exc:
                print("not recorded:", exc)

    def authorise(self, package_id: str, decision: str, role: str, actor: str, reason: str,
                  at: Optional[str] = None, simulated: bool = False) -> dict:
        pk = next((p for p in self.current_packages.values() if p["package_id"] == package_id), None)
        if pk is None:
            raise ValueError(f"unknown or superseded package {package_id}")
        return record_authorisation(self.audit, pk, decision, role, actor, reason, at, simulated)

    # ---- outputs ------------------------------------------------------------
    def step(self, as_of: datetime) -> Dict[str, Any]:
        res = self.assess_and_plan(as_of)
        self.audit.append("observe_assess_plan", {"input_sha256": res["input_sha256"],
                                                  "records": {"physio": res["dataset"]["physio_records"],
                                                              "station": res["dataset"]["station_records"],
                                                              "events": res["dataset"]["events"]},
                                                  "continuity_status": res["continuity"]["result"]["status"],
                                                  "rescue_objective": res["rescue"]["objective"]}, res["as_of"])
        changed = self._propose(res)
        if not changed:
            self.audit.append("no_change", {"input_sha256": res["input_sha256"],
                                            "note": "inputs changed only in volatile fields; no new proposal"}, res["as_of"])
        self.timeline.append(_timeline_row(res, changed))
        return res

    def run(self, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        _, end = self.dataset.time_bounds()
        as_of = as_of or end
        res = self.step(as_of)
        self.write_outputs(res)
        return res

    def replay(self, start: Optional[datetime] = None, end: Optional[datetime] = None, step_s: int = 60) -> Dict[str, Any]:
        s0, e0 = self.dataset.time_bounds()
        start = start or self.dataset.baseline_end() or s0
        end = end or e0
        t = start
        res = None
        while t <= end:
            res = self.step(t)
            t += timedelta(seconds=step_s)
        if res is None or parse_ts(res["as_of"]) < end:
            res = self.step(end)
        self.write_outputs(res)
        return res

    def write_outputs(self, res: Dict[str, Any]) -> None:
        from .report import write_reports
        pk = list(self.current_packages.values())
        for p in pk:
            p["authorisation"] = latest_authorisation(self.audit.path, p["package_id"])
            if p["authorisation"]:
                p["status"] = p["authorisation"]["decision"]
        llm_out = None
        if self.use_llm:
            from .llm import generate_briefing
            llm_out = generate_briefing(res, pk, self.policy, client=self.llm_client)
            self.audit.append("llm_summary", {"source": llm_out["source"], "model": llm_out.get("model"),
                                              "accepted": llm_out["source"] == "llm",
                                              "fallback_reason": llm_out.get("fallback_reason"),
                                              "post_check": llm_out.get("post_check"),
                                              "text_sha256": sha256_obj(llm_out["text"])}, res["as_of"])
        write_reports(self.out_dir, res, pk, self.timeline, llm_out, auto_approve=self.auto_approve)
        self.audit.append("outputs_written", {"out_dir": self.out_dir,
                                              "packages": [p["package_id"] for p in pk]}, res["as_of"])


# ---------------------------------------------------------------------------
# authorisation helpers usable from the CLI without re-running the agent
# ---------------------------------------------------------------------------

def record_authorisation(audit: AuditLog, pk: Mapping, decision: str, role: str, actor: str, reason: str,
                         at: Optional[str] = None, simulated: bool = False) -> dict:
    if decision not in ("approved", "rejected"):
        raise ValueError("decision must be 'approved' or 'rejected'")
    roles = pk.get("authorising_roles", [])
    if not simulated and role not in roles:
        raise ValueError(f"role '{role}' is not an authorising role for {pk['domain']} (requires one of {roles})")
    if not actor:
        raise ValueError("actor identity required")
    if not reason or not reason.strip():
        raise ValueError("a reason must be recorded for every approval or rejection")
    e = audit.append("authorisation", {"package_id": pk["package_id"], "domain": pk["domain"], "decision": decision,
                                       "role": role, "actor": actor, "reason": reason, "simulated": simulated,
                                       "content_sha256": pk.get("content_sha256")}, at)
    return e


def latest_authorisation(audit_path: str, package_id: str) -> Optional[dict]:
    last = None
    if not os.path.exists(audit_path):
        return None
    with open(audit_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            e = json.loads(line)
            if e.get("entry_type") == "authorisation" and e["payload"].get("package_id") == package_id:
                last = {"decision": e["payload"]["decision"] + ("_simulation" if e["payload"].get("simulated") else ""),
                        "role": e["payload"]["role"], "actor": e["payload"]["actor"], "reason": e["payload"]["reason"],
                        "seq": e["seq"], "recorded_at": e["recorded_at"]}
    return last


def _access_summary(teams_doc, zid, as_of, domain, policy=None, restriction=None):
    from .rescue import access_for, merged_access
    a = access_for(zid, domain, merged_access(teams_doc or {}, policy or {}), as_of, domain=domain,
                   restriction=restriction)
    return {"status": a["status"], "authorised_by": a.get("authorised_by"), "conditions": a.get("conditions", [])}


def _timeline_row(res, changed) -> dict:
    zones = res["physiology"]["zones"]
    return {
        "as_of": res["as_of"],
        "changed_domains": changed,
        "open_assistance_requests": sum(len(p["assistance_requests"]) for p in res["rescue"]["personnel"]),
        "rescue_tasks": len(res["rescue"]["tasks"]),
        "assigned": len(res["rescue"]["assignments"]),
        "unassigned_urgent": len(res["rescue"]["unassigned_urgent"]),
        "personnel_counts": res["rescue"]["personnel_counts"],
        "continuity_status": res["continuity"]["result"]["status"],
        "Q_pct": res["continuity"]["result"]["Q_pct"],
        "group_states": {z: v["decision"]["states"] for z, v in zones.items()},
        "recovery_scheduled": sum(1 for t in res["recovery"]["tasks"] if t["status"] == "scheduled_candidate"),
        "recovery_blocked": len(res["recovery"]["blocked"]),
        "observation_gaps": sum(z["summary"].get("observation_gaps_current", 0) for z in res["incident"]["zones"].values()),
    }
