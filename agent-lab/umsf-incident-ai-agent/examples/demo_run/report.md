# UMSF incident AI agent — technical run report

Agent version 1.0.0; scenario `umsf-p3-post-impact-demo-v1`; data origin `synthetic`; state at 2026-10-14T09:10:00Z.

## Inputs

| file | SHA-256 |
|---|---|
| assets.json | `14ea1a6e04c823101fe6f4c779bc0f7392890cd0443ba31b135250b0f0c92eb5` |
| events.jsonl | `f487391620c54e2b68817f3b3ad921c778dda9b3591faf012d7ff9d08be9bf4f` |
| manifest.json | `b772ecbec69c3f9c08f2aed7a7084d598ffed9284649fa81d93dcf26d62610b9` |
| physio.jsonl | `01a872f8d00af476a898b6898fd16d2c866b036347f80e56fe6777b01a1f8c9f` |
| roster.json | `2d99371eb7096ebac866267e2d8267d6f0ca65230f74fb3fb87c08d7491c631d` |
| station.jsonl | `3e0d56ea9ea73267d4a61beaedcb8db0dac87ab8a14e17efdde05050e684b401` |
| teams.json | `9938be013385fed7f55d34fc3b401b50ffd272483689b377d7e3292f60f472ab` |

Records: physio 4709, station 2415, events 30; duplicates dropped 1; quarantined identities 1; rejected lines 0.

## Decision packages

| package | domain | authorising role | solver | status |
|---|---|---|---|---|
| `PKG-urgent_personnel_assistance-c21bce43a6` | urgent_personnel_assistance | rescue_coordinator, emergency_coordinator | direct pass-through of assistance requests | awaiting_authorisation |
| `PKG-rescue_task_assignment-2f69aa684c` | rescue_task_assignment | rescue_coordinator, incident_command | lexicographic Eq. (9) via exact max-weight bipartite matchin | rejected |
| `PKG-personnel_accounting-0b4929afc9` | personnel_accounting | incident_coordination_team | explicit identity and time reconciliation rules | awaiting_authorisation |
| `PKG-structural_access_status-1ccbfbb0ff` | structural_access_status | qualified_assessor, incident_command | source-linked assertions; explicit unknown | awaiting_authorisation |
| `PKG-essential_service_preservation-bead1ffdc8` | essential_service_preservation | infrastructure_operator | exact enumeration over 64 candidates | approved |
| `PKG-recovery_scheduling-9d4b5ac38c` | recovery_scheduling | recovery_management | CPM (earliest/latest start) + serial schedule-generation sch | awaiting_authorisation |
| `PKG-physiological_group_warning-8c9dbd166f` | physiological_group_warning | occupational_health, site_safety_officer | Eq. (1)-(5) deterministic | awaiting_authorisation |

## Rescue assignment (Eq. 8-9)

| team | task | zone | urgent | p | delta (s) |
|---|---|---|---|---|---|
| RT1 | RT-assist_help_request-W10 | Z4 | True | 90 | 1495 |
| RT4 | RT-locate_unaccounted-W12 | Z5 | True | 70 | 300 |
| RT2 | RT-check_presence_cue-Z2 | Z2 | False | 40 | 377 |

Unassigned:

- RT-assist_sos-S03: access authorisation for zone Z3 unknown: incident command decision required; task retained (not abandoned)

Objective: {'urgent_assigned': 2, 'total_priority': 200, 'total_estimated_time_s': 2172}; solver: lexicographic Eq. (9) via exact max-weight bipartite matching (Hungarian / Kuhn-Munkres, integer scaled weights)

## Service continuity (Eq. 10-11)

Status **OPTIMAL**, method enumeration, Q = 81.48148148148148

| resource | capacity (lower bound) | used | unused |
|---|---|---|---|
| energy_kwh | 200.0 | 160.0 | 40.0 |
| power_kw | 60.0 | 40.0 | 20.0 |
| radio_channels | 4.0 | 3.0 | 1.0 |
| staff | 6.0 | 4.0 | 2.0 |

| service | y |
|---|---|
| communications | 1 |
| emergency_lighting | 1 |
| fire_water_pump | 1 |
| water_support | 0 |
| production | 0 |
| process_monitoring | 1 |

## Recovery schedule

Makespan 155.0 min; critical path: RC-gas_hazard_check-Z2 -> RC-structural_inspection-Z2 -> RC-debris_clearance-Z2

| task | status | start | finish | crew | prerequisites | blocked |
|---|---|---|---|---|---|---|
| RC-gas_hazard_check-Z2 | scheduled_candidate | 2026-10-14T09:10:00Z | 2026-10-14T09:30:00Z | RC2 | — | — |
| RC-temporary_power_path-Z1 | scheduled_candidate | 2026-10-14T09:10:00Z | 2026-10-14T10:10:00Z | RC1 | — | — |
| RC-gas_hazard_check-Z3 | scheduled_candidate | 2026-10-14T09:30:00Z | 2026-10-14T09:50:00Z | RC2 | — | — |
| RC-structural_inspection-Z2 | scheduled_candidate | 2026-10-14T09:30:00Z | 2026-10-14T10:15:00Z | ST1 | RC-gas_hazard_check-Z2 | — |
| RC-debris_clearance-Z2 | scheduled_candidate | 2026-10-14T10:15:00Z | 2026-10-14T11:45:00Z | RC2 | RC-gas_hazard_check-Z2, RC-structural_inspection-Z2 | — |
| RC-water_support_restoration-Z3 | blocked | — | — | — | RC-gas_hazard_check-Z3 | access authorisation for zone Z3 unknown: incident command decision required; task retained (not abandoned); equipment 'pump_kit' unavailable or unknown (need 1, verified 0) |

## Timing (Eq. 7)

| event | type | T_report | T_action |
|---|---|---|---|
| E005 | possible_impact_local | [46.5, 47.5] s | not_recorded |
| E007 | sos | [39.5, 40.5] s | [429.5, 430.5] s |
| E008 | gas_channel_alarm | [19.5, 20.5] s | not_recorded |
| E009 | sos | [9.5, 10.5] s | not_recorded |
| E013 | help_request | [54.5, 55.5] s | not_recorded |

## Re-planning timeline

| as_of | changed domains | open requests | unassigned urgent | continuity | Q |
|---|---|---|---|---|---|
| 2026-10-14T08:30:00Z | urgent_personnel_assistance, rescue_task_assignment, personnel_accounting, structural_access_status, essential_service_preservation, recovery_scheduling, physiological_group_warning | 0 | 0 | OPTIMAL | 81.48 |
| 2026-10-14T08:31:00Z | (no change) | 0 | 0 | OPTIMAL | 81.48 |
| 2026-10-14T08:32:00Z | (no change) | 0 | 0 | OPTIMAL | 81.48 |
| 2026-10-14T08:33:00Z | physiological_group_warning | 0 | 0 | OPTIMAL | 81.48 |
| 2026-10-14T08:34:00Z | (no change) | 0 | 0 | OPTIMAL | 81.48 |
| 2026-10-14T08:35:00Z | urgent_personnel_assistance, rescue_task_assignment, personnel_accounting, structural_access_status, recovery_scheduling, physiological_group_warning | 1 | 2 | OPTIMAL | 81.48 |
| 2026-10-14T08:36:00Z | rescue_task_assignment, structural_access_status | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T08:37:00Z | rescue_task_assignment, personnel_accounting, structural_access_status, essential_service_preservation, recovery_scheduling, physiological_group_warning | 1 | 3 | INFEASIBLE |  |
| 2026-10-14T08:38:00Z | urgent_personnel_assistance, rescue_task_assignment, personnel_accounting, structural_access_status, physiological_group_warning | 2 | 3 | INFEASIBLE |  |
| 2026-10-14T08:39:00Z | (no change) | 2 | 3 | INFEASIBLE |  |
| 2026-10-14T08:40:00Z | essential_service_preservation, recovery_scheduling | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:41:00Z | personnel_accounting, structural_access_status | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:42:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:43:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:44:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:45:00Z | rescue_task_assignment, structural_access_status | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:46:00Z | personnel_accounting | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:47:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:48:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:49:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:50:00Z | rescue_task_assignment | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:51:00Z | rescue_task_assignment, personnel_accounting, structural_access_status, physiological_group_warning | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:52:00Z | (no change) | 2 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:53:00Z | urgent_personnel_assistance, rescue_task_assignment, personnel_accounting, physiological_group_warning | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:54:00Z | (no change) | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:55:00Z | structural_access_status, recovery_scheduling | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:56:00Z | rescue_task_assignment | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:57:00Z | (no change) | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:58:00Z | (no change) | 1 | 3 | OPTIMAL | 81.48 |
| 2026-10-14T08:59:00Z | rescue_task_assignment, personnel_accounting, structural_access_status, recovery_scheduling | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:00:00Z | physiological_group_warning | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:01:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:02:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:03:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:04:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:05:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:06:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:07:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:08:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:09:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |
| 2026-10-14T09:10:00Z | (no change) | 1 | 1 | OPTIMAL | 81.48 |

All plans are proposals. See docs/SAFETY_AND_ETHICS.md.
