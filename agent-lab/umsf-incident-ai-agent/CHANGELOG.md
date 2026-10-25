# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow semantic versioning.

## [1.0.0] — 2026-10-14

### Added
- `ingest`: tolerant loader for the shared protocol dataset layout (PROTOCOL.md §5) and the P1
  `umsf-incident-dataset` export conventions (facility roster wrapper, string event levels, aggregated
  personnel accounting, `asset_status.details`, `capacity_lower_bound`, `eta_min`, `available_from_min`,
  `incident_associations`); identity deduplication, conflict quarantine, null-not-normal range handling.
- `physio_rules`: Eq. (1)–(5), Sec. 4.3 integer reformulation and threshold feasibility, four decision
  states and the independent urgent pathway.
- `incident_state`: source-qualified zone state S_z = (M, H, P, F, U), freshness, supersession,
  observation gaps, strike attribution only from authoritative external alerts, incident packets,
  T_report / T_action with interval and unqualified handling (Eq. 6–7).
- `rescue` + `assignment`: personnel accounting reconciliation, task generation, eligibility/access with
  escalation records, exact lexicographic assignment (Eq. 8–9) verified against brute force.
- `continuity`: exact service-continuity allocation (Eq. 10–11), multi-resource lower bounds with
  per-asset provenance, enumeration (n ≤ 20) and branch-and-bound, INFEASIBLE without relaxation,
  Fig. 14 data.
- `recovery`: consequence-liquidation task generation, hard prerequisites, CPM, serial SGS,
  blocked-task reporting, actuation exclusion, continuity linkage.
- `agent`: observe → assess → plan → propose → authorise → log loop, time-stepped replay with
  change detection, hash-chained JSONL audit log, CLI approve/reject with reasons and role checks,
  clearly marked `--auto-approve-for-simulation`.
- `llm`: optional Claude briefing via the official `anthropic` SDK with read-only minimised tools,
  manual tool loop, refusal / pause_turn / API-error handling, post-check and deterministic fallback.
- `report`: deterministic Ukrainian briefing, decision-package JSON, Markdown report, single-file HTML
  dashboard with inline SVG (zones, assignments, capacity bars, recovery Gantt, Fig. 14).
- `scenario`: synthetic two-site post-impact scenario (variants `post_impact`, `no_backup_power`).
- `reproduce-paper`: 44 checks covering Table 10, Sec. 4.3, the Study A note and Sec. 4.9.
- Documentation (README in Ukrainian with English abstract, architecture, decision model, input format,
  safety and ethics), Zenodo metadata, examples.
