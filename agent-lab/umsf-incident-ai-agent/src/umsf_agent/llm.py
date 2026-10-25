"""Optional Claude layer: a Ukrainian situation briefing written from minimised aggregates.

Boundary (Sec. 3.3.8): the language model only summarises and explains. It
receives READ-ONLY tools that return minimised aggregates (pseudonyms only, no
raw physiology). It cannot diagnose, issue triage categories, select building
entry routes or actuate equipment, and its text is post-checked; on any
failure (no SDK, no credentials, API error, refusal, forbidden claim,
unsupported number) the deterministic briefing is used instead.

The `anthropic` SDK is imported lazily; the package works fully offline.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from .report import deterministic_briefing, kyiv

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TOOL_TURNS = 12
AI_LABEL = "AI-generated summary — verify against deterministic outputs"

SYSTEM_PROMPT = """You assist an incident commander at a critical-infrastructure site after a possible impact.
Write a concise situation briefing IN UKRAINIAN, in Markdown, for the incident commander.

You have read-only tools that return deterministic outputs of a decision-support agent. Call the tools you need
(normally all five) before writing. Base every statement on tool outputs only.

Rules you must follow:
- Preserve uncertainty. "unknown" stays unknown; missing data is never "normal" or "safe".
- For each key fact, cite the evidence source class and its age or time (Kyiv time fields are provided).
- Do not state a strike, casualty, injury, death, collapse, structural or hazard conclusion that is not explicitly
  present in the tool outputs. Local "possible_impact_local" cues are UNVERIFIED; only an authoritative external
  source may report a strike. Do not mention death or casualties at all, not even in negation.
- Acoustic / PIR signals are possible presence cues only, never signs of life.
- Do not diagnose, do not assign medical triage categories, do not choose building entry routes, do not instruct
  anyone to operate, switch, restart or unlock equipment.
- Do not invent numbers: use only numbers that appear in the tool outputs.
- Every plan is a PROPOSAL. End with a section listing the decisions awaiting human authorisation, each with
  the authorising role (from the tool outputs).
- Keep it under about 450 words."""

TOOLS = [
    {"name": "get_incident_summary",
     "description": "Read-only. Site alerts, strike-attribution statement, per-zone structural/hazard state, flags, "
                    "evidence ages, and decisions awaiting human authorisation. Minimised aggregates only.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_rescue_proposal",
     "description": "Read-only. Rescue logistics proposal: open assistance requests (pseudonyms), personnel "
                    "accounting counts, proposed team-task assignments, unassigned tasks and limiting constraints.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_continuity_proposal",
     "description": "Read-only. Service-continuity proposal: status (OPTIMAL/INFEASIBLE), supported services, "
                    "weighted coverage Q, capacities and binding resources.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_recovery_schedule",
     "description": "Read-only. Candidate consequence-liquidation schedule: tasks, times (UTC and Kyiv), crews, "
                    "blocked tasks with unresolved prerequisites, actuation exclusions.",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "get_evidence_gaps",
     "description": "Read-only. Observation gaps, rejected (non-authoritative) attribution claims, personnel "
                    "telemetry gaps and coverage-aware physiological group states (aggregated counts only).",
     "input_schema": {"type": "object", "properties": {}, "additionalProperties": False}},
]


# ---------------------------------------------------------------------------
# Minimised read-only tool implementations
# ---------------------------------------------------------------------------

def build_tool_outputs(res: Mapping, packages: List[Mapping]) -> Dict[str, Any]:
    inc, resc, cont, rec, phys = res["incident"], res["rescue"], res["continuity"]["result"], res["recovery"], res["physiology"]
    pk_age = {p["assertion_id"]: p.get("age_s") for p in inc["packets"]}
    zones = {}
    for zid, z in inc["zones"].items():
        s = z["summary"]
        newest = {}
        for L in ("M", "H", "P", "F", "U"):
            ages = [a.get("age_s") for a in z[L] if a.get("age_s") is not None]
            newest[L] = None if not ages else int(min(ages))
        zones[zid] = {"name": z["name"], "site_id": z["site_id"], "structural": s.get("structural", {}).get("state"),
                      "structural_assessor": s.get("structural", {}).get("assessor"),
                      "hazard_state": s.get("hazard_state"), "flags": s.get("flags"),
                      "newest_evidence_age_s_by_layer": newest}
    summary = {
        "as_of_utc": res["as_of"], "as_of_kyiv": kyiv(res["as_of"]), "data_origin": res["data_origin"],
        "strike_attribution_statement": inc["strike_statement_en"],
        "site_alerts": [{"kind": a["kind"], "status": a["status"], "source_class": a["source_class"],
                         "source": (a.get("provenance") or {}).get("source"),
                         "observed_kyiv": kyiv(a["observed_at"]), "reported_kyiv": kyiv(a["reported_at"])}
                        for a in inc["site_context"] if a["kind"] in ("air_raid_alert", "air_raid_all_clear", "external_strike_report")],
        "zones": zones,
        "decisions_awaiting_authorisation": [{"package_id": p["package_id"], "domain": p["domain"],
                                              "authorising_roles": p["authorising_roles"],
                                              "status": (p.get("authorisation") or {}).get("decision", "awaiting_authorisation")}
                                             for p in packages],
    }
    reqs = []
    for p in resc["personnel"]:
        for r in p["assistance_requests"]:
            reqs.append({"pseudonym": p["worker"], "type": r["event_type"], "zone": r.get("zone_id"),
                         "age_s": None if pk_age.get("A-" + r["event_id"]) is None else int(pk_age["A-" + r["event_id"]]),
                         "observed_kyiv": kyiv(r["observed_at"]), "source_class": "personnel_node"})
    for t in resc["tasks"]:
        if t["kind"] == "assist_sos" and t["subject"].get("device"):
            eid = t["subject"].get("request_event")
            reqs.append({"pseudonym": None, "device": t["subject"]["device"], "type": "sos (stationary button, person unknown)",
                         "zone": t["zone_id"], "age_s": None if pk_age.get(f"A-{eid}") is None else int(pk_age[f"A-{eid}"]),
                         "source_class": "stationary_node"})
    rescue = {
        "open_assistance_requests": reqs,
        "personnel_counts": resc["personnel_counts"],
        "unaccounted_or_unresolved": [{"pseudonym": p["worker"], "category": p["category"],
                                       "last_confirmed_zone": p["last_confirmed_location"].get("zone_id"),
                                       "basis": p["last_confirmed_location"].get("basis"),
                                       "at_kyiv": kyiv(p["last_confirmed_location"].get("at"))}
                                      for p in resc["personnel"] if p["category"] in ("unaccounted", "unresolved")],
        "assignments": [{"team": a["team_id"], "task_kind": a["kind"], "zone": a["zone_id"], "urgent": a["urgent"],
                         "priority": a["priority"], "estimated_minutes": a["delta_s"] // 60,
                         "estimate_label": "qualified estimate, not a route"} for a in resc["assignments"]],
        "unassigned": [{"task_kind": u["kind"], "zone": u["zone_id"], "urgent": u["urgent"],
                        "limiting_constraints": u["limiting_constraints"]} for u in resc["unassigned"]],
        "active_limiting_constraints": resc["active_limiting_constraints"],
        "authorising_role": "rescue_coordinator / incident_command",
    }
    continuity = {
        "status": cont["status"], "supported": [k for k, v in cont["y"].items() if v],
        "not_supported": [k for k, v in cont["y"].items() if not v],
        "Q_pct": None if cont["Q_pct"] is None else round(cont["Q_pct"], 1),
        "capacity_lower_bounds": cont["resource_capacity"], "binding_resources": cont["binding_resources"],
        "infeasibility_reasons": cont["infeasibility_reasons"], "inadmissible_or_unknown": cont["excluded_inadmissible"],
        "authorising_role": "infrastructure_operator",
        "note": "Q is weighted service coverage under assumed weights, not people rescued",
    }
    recovery = {
        "scheduled": [{"kind": t["kind"], "zone": t["zone_id"], "start_kyiv": kyiv(t["start"]), "finish_kyiv": kyiv(t["finish"]),
                       "crew": t["crew"], "critical": t["critical"]} for t in rec["tasks"] if t["status"] == "scheduled_candidate"],
        "blocked": [{"kind": t["kind"], "zone": t["zone_id"], "reasons": t["blocked_reasons"]} for t in rec["blocked"]],
        "excluded_actuation": rec["excluded_actuation"], "makespan_min": rec["makespan_min"],
        "authorising_role": "recovery_management",
    }
    gaps = {
        "observation_gaps": [{"zone": zid, "source": a["source_id"], "since": a["observed_at"], "notes": a["notes"]}
                             for zid, z in inc["zones"].items() for a in z["U"] if a["kind"] == "observation_gap" and a["status"] == "current"],
        "personnel_telemetry": {zid: z["summary"].get("personnel_telemetry") for zid, z in inc["zones"].items()},
        "rejected_attributions": [{"source_class": a["source_class"], "source": (a.get("provenance") or {}).get("source"),
                                   "reason": "; ".join(a["notes"])} for a in inc["rejected_attributions"]],
        "physiological_group_states": {zid: {"label": v["decision"]["label_en"], "eligible": v["decision"]["group"]["n"],
                                             "expected": v["decision"]["group"]["N"],
                                             "coverage_pct": v["decision"]["group"]["C_pct"],
                                             "flags": v["decision"]["group"]["m"]}
                                       for zid, v in phys["zones"].items()},
        "note": "physiological states are coverage-aware aggregates; a group warning is a request for investigation",
    }
    return {"get_incident_summary": summary, "get_rescue_proposal": rescue, "get_continuity_proposal": continuity,
            "get_recovery_schedule": recovery, "get_evidence_gaps": gaps}


# ---------------------------------------------------------------------------
# Post-check
# ---------------------------------------------------------------------------

_NUM = re.compile(r"(?<![A-Za-zА-Яа-яІіЇїЄєҐґ_])\d+(?:[.,]\d+)?")


def _norm_num(s: str) -> str:
    s = s.replace(",", ".")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s.lstrip("0") or "0"


def post_check(text: str, corpus: str, forbidden: List[str]) -> Dict[str, Any]:
    """Reject forbidden claims and numbers that do not occur in the tool outputs."""
    low = text.lower()
    corpus_low = corpus.lower()
    bad_phr = [p for p in forbidden if p.lower() in low and p.lower() not in corpus_low]
    allowed = {_norm_num(m) for m in re.findall(r"\d+(?:[.,]\d+)?", corpus)}
    # integer parts of decimals and simple list numbering are tolerated
    allowed |= {_norm_num(m.split(".")[0]) for m in list(allowed)}
    allowed |= {str(i) for i in range(0, 11)}
    nums = {_norm_num(m) for m in _NUM.findall(text)}
    bad_num = sorted(n for n in nums if n not in allowed)
    ok = not bad_phr and not bad_num and bool(text.strip())
    return {"ok": ok, "forbidden_phrases": bad_phr, "unsupported_numbers": bad_num[:20]}


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------

def _sdk_errors():
    try:
        import anthropic  # noqa: F401
        return anthropic.RateLimitError, anthropic.APIStatusError, anthropic.APIConnectionError
    except ImportError:
        class _Never(Exception):
            pass
        return _Never, _Never, _Never


def _block_type(b) -> Optional[str]:
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", None)


def _attr(b, name):
    return b.get(name) if isinstance(b, dict) else getattr(b, name, None)


def run_tool_loop(client, model: str, tool_impl: Callable[[str, Mapping], Any], user_text: str,
                  system: str = SYSTEM_PROMPT, tools: List[dict] = TOOLS) -> Tuple[Optional[str], Optional[str], List[str]]:
    """Manual agentic loop. Returns (text, failure_reason, tool_names_called)."""
    messages: List[dict] = [{"role": "user", "content": user_text}]
    called: List[str] = []

    def create():
        return client.beta.messages.create(
            model=model,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium"},
            system=system,
            tools=tools,
            messages=messages,
        )

    response = create()
    turns = 0
    while True:
        turns += 1
        if turns > MAX_TOOL_TURNS:
            return None, "tool-loop turn limit reached", called
        stop = getattr(response, "stop_reason", None)
        if stop == "refusal":            # check before reading content
            return None, "model refusal", called
        if stop == "pause_turn":         # server paused a long turn: resend to resume
            messages.append({"role": "assistant", "content": response.content})
            response = create()
            continue
        if stop != "tool_use":
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for b in response.content:
            if _block_type(b) != "tool_use":
                continue
            name = _attr(b, "name")
            called.append(name)
            try:
                out = tool_impl(name, _attr(b, "input") or {})
                results.append({"type": "tool_result", "tool_use_id": _attr(b, "id"),
                                "content": json.dumps(out, ensure_ascii=False)})
            except KeyError:
                results.append({"type": "tool_result", "tool_use_id": _attr(b, "id"),
                                "content": f"unknown tool {name}", "is_error": True})
        messages.append({"role": "user", "content": results})
        response = create()
    if getattr(response, "stop_reason", None) == "max_tokens":
        return None, "response truncated (max_tokens)", called
    text = "".join(_attr(b, "text") or "" for b in response.content if _block_type(b) == "text")
    return text, None, called


def generate_briefing(res: Mapping, packages: List[Mapping], policy: Mapping, client: Any = None) -> Dict[str, Any]:
    """Return {"text", "source", ...}. source = "llm" or "deterministic_fallback"."""
    fallback_text = deterministic_briefing(res, packages)
    model = os.environ.get("UMSF_LLM_MODEL", DEFAULT_MODEL)
    outputs = build_tool_outputs(res, packages)
    corpus = json.dumps(outputs, ensure_ascii=False)

    def fb(reason, called=None, check=None):
        return {"text": fallback_text, "source": "deterministic_fallback", "model": model,
                "fallback_reason": reason, "tool_calls": called or [], "post_check": check}

    if client is None:
        try:
            import anthropic
        except ImportError:
            return fb("anthropic SDK not installed (pip install anthropic)")
        try:
            client = anthropic.Anthropic()
        except Exception as exc:     # e.g. no credentials configured
            return fb(f"client initialisation failed: {type(exc).__name__}")
    RateLimitError, APIStatusError, APIConnectionError = _sdk_errors()

    def tool_impl(name, _input):
        return outputs[name]

    user_text = ("Підготуй оперативну довідку для керівника реагування на основі інструментів. "
                 "Мова: українська. Початок тексту: заголовок «Оперативна довідка (згенеровано ШІ)».")
    try:
        text, failure, called = run_tool_loop(client, model, tool_impl, user_text)
    except RateLimitError as exc:
        return fb(f"rate limited: {exc.__class__.__name__}")
    except APIStatusError as exc:
        return fb(f"API status error {getattr(exc, 'status_code', '')}")
    except APIConnectionError as exc:
        return fb(f"API connection error: {exc.__class__.__name__}")
    except Exception as exc:          # any other SDK or transport error -> deterministic output
        return fb(f"LLM call failed: {type(exc).__name__}")
    if failure:
        return fb(failure, called)
    forbidden = policy.get("llm", {}).get("forbidden_phrases", [])
    check = post_check(text or "", corpus, forbidden)
    if not check["ok"]:
        return fb("post-check rejected LLM text", called, check)
    return {"text": f"_{AI_LABEL}_\n\n" + text.strip() + "\n", "source": "llm", "model": model,
            "fallback_reason": None, "tool_calls": called, "post_check": check}
