# Architecture

## Agent loop

```
                ┌──────────────────────────── replay: every Δt of scenario time ───────────────────────────┐
                ▼                                                                                          │
 dataset dir ─► OBSERVE ─► ASSESS ──────────────────► PLAN ───────────────────────► PROPOSE ─► AUTHORISE ─► LOG
 (P1 / own)    ingest.py   physio_rules.py           rescue.py + assignment.py     agent.py    human role   audit.py
               snapshot    (Eq. 1-5, Sec. 3.6.4)     (Eq. 8-9)                      decision    (Table 9)    hash-chained
               at t        incident_state.py         continuity.py (Eq. 10-11)      packages    approve /    JSONL
                           (Eq. 6-7, Table 8)        recovery.py (Table 9)          + reports   reject +
                                                                                                 reason
                                                     optional: llm.py (summary only, read-only tools, post-checked)
```

* **Observe.** `ingest.load_dataset` reads the directory once; `Dataset.snapshot(t)` returns only the
  records whose arrival time (`received_at` / `reported_at`) is ≤ t. Identity deduplication and conflict
  quarantine happen at load; freshness is evaluated separately at each step.
* **Assess.**
  * `incident_state.build_incident_state` turns events and station records into typed, source-qualified
    assertions per zone layer (M, H, P, F, U), applies supersession and freshness, derives observation
    gaps (explicit `link_loss` or silence), attachment uncertainty, presence cues, rejected attributions,
    the strike-attribution statement, incident packets and Eq. (7) timing.
  * `agent.assess_physiology` evaluates Eq. (1)–(3) per rostered worker and Eq. (4)–(5) per zone
    with the explicit roster as denominator, and attaches open assistance requests as the independent
    urgent pathway.
* **Plan.**
  * `rescue.plan_rescue`: reconciliation → tasks → e_rj, a_j, δ_rj → exact Eq. (9) via
    `assignment.solve_lexicographic` → unassigned tasks with limiting constraints and escalations.
  * `continuity.solve`: Eq. (10) with capacities from `resources_from_assets` (register + current
    `asset_status` reports; stale or unknown → 0).
  * `recovery.plan_recovery`: tasks from the incident state and the continuity result, hard
    prerequisites, CPM, serial SGS; teams already proposed for rescue tasks are not used as crews.
* **Propose.** `Agent.build_packages` creates seven decision packages (Table 9 domains plus the
  physiological group warning). Each has a stable `content` part (hashed; used for change detection), a
  volatile `context` part (ages, times), the input SHA-256, policy SHA-256, versions, solver method and
  status, limitations and the boundary statement.
* **Authorise.** Packages stay `awaiting_authorisation` until a human with an authorising role records
  `approve` or `reject` with a reason (CLI or `--interactive`). `--auto-approve-for-simulation` records
  simulated approvals flagged `simulated: true` and is announced in every output.
* **Log.** `audit.AuditLog` appends entries (`session_start`, `observe_assess_plan`, `propose`,
  `supersede`, `no_change`, `authorisation`, `llm_summary`, `outputs_written`) with `prev_hash` and
  `entry_hash`; `verify-audit` checks the chain.

## Change detection and re-planning

`replay` advances scenario time in fixed steps (default 60 s). At each step a package is re-proposed only
if the SHA-256 of its stable content changed; the previous package is then marked superseded in the audit
log and its authorisation does not carry over. Otherwise a `no_change` entry is written.

## Separation of authority

Rescue authority and infrastructure-operation authority remain separate (Fig. 9): rescue packages go to
the rescue coordinator / incident command, the continuity package to the infrastructure operator, the
recovery schedule to recovery management. No package executes anything.

## Data minimisation

Individual physiological windows are kept in `result.json → physiology.workers_restricted` (restricted
to authorised roles, Sec. 3.7.2). Decision packages, briefings, the dashboard and the language-model tools
contain only aggregated counts and pseudonyms.

## Modules

| module | lines of responsibility |
|---|---|
| `util.py` | UTC parsing/formatting, canonical JSON, SHA-256 |
| `policy.py` | default command policy + overrides (`<data>/policy.json`, `--policy`) |
| `ingest.py` | loader, validation, deduplication, P1 normalisation |
| `physio_rules.py` | Eq. 1–5, Sec. 4.3, decision states |
| `incident_state.py` | Eq. 6–7, Table 8, packets |
| `assignment.py` | exact lexicographic assignment (Hungarian), brute-force reference |
| `rescue.py` | personnel accounting, rescue tasks, eligibility, access, δ estimates |
| `continuity.py` | Eq. 10–11, capacity provenance, Table 16 / Fig. 14 |
| `recovery.py` | recovery tasks, CPM, SGS |
| `agent.py` | orchestrator, packages, authorisation |
| `audit.py` | hash-chained log |
| `llm.py` | optional Claude layer |
| `report.py` | briefing, Markdown, HTML |
| `scenario.py` | synthetic scenario generator |
| `paper.py` | paper reproduction checks |
| `cli.py` | `umsf-agent` command |
