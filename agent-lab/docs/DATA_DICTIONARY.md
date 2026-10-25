# Generated outputs and data provenance

| Output | Meaning |
|---|---|
| `timeline.csv` / `timeline.json` |41 cutoffs,one minute apart,08:30–09:10 UTC; task counts,assignments,unassigned urgent,continuity status/Q,recovery counts and evidence gaps |
| `snapshots.json` | Full original-agent result at each cutoff for the primary synthetic scenario |
| `no_backup_timeline.json` |41 cutoffs for the no-verified-backup variant |
| `paper_cases.csv` | Three supplied analytical cases;coverage n/N and flagged fraction m/n are different quantities |
| `continuity_frontier.csv` | Exact four-service solutions for illustrative capacity B=0…12;undefined Q for infeasible cases |
| `recovery_schedule.csv` |09:00 UTC candidate tasks;minutes are relative to that cutoff;blocked tasks have no start/finish |
| `raw_snapshot_0900.json` | Full selected original-agent snapshot,including original localized metadata |
| `raw_decision_packages.json` | Seven latest proposal packages at the end of replay,awaiting authorization |
| `agent_run/audit.jsonl` | Primary replay hash chain |
| `no_backup_run/audit.jsonl` | Comparison replay hash chain |
| `simulated_authority_demo.jsonl` | Explicitly simulated demonstration;no operational approval |
| `tampered_demo.jsonl` | Deliberately invalid audit copy for the tamper experiment;not an authoritative log |
| `analytical_checks.json` |44 expected-versus-actual comparisons from the source's analytical reference module |
| `llm_filter_demonstration.json` | Five offline lexical-filter examples,including documented false acceptance boundaries |
| `verification.json` / `VALIDATION_REPORT.json` | Actual run outcome,versions,counts and verification boundaries |
| `REPORT_EN.md` | English summary of the09:00 UTC snapshot |
| `interactive_explorer.html` | English aggregate snapshot selector;all data embedded |

All input scenarios are synthetic. Source files retain their original schemas and units. The primary scenario includes12 roster members,6 zones and6 stationary nodes across2 sites. The P1 compatibility fixture has its own5-zone layout and is used only by integration tests. These datasets are never silently combined for analysis.

Physiological example scores and group thresholds are development-policy values. Q is a weighted proportion of selected service priorities,not physical facility restoration. Rescue delta_s is estimated travel-plus-setup in seconds,not a validated route or response time. Timing intervals inherit event-time uncertainty. Empty/null values remain unknown.

The notebook source fully specifies every added illustrative sweep. No random values are generated in its scoring examples;scenario seeds are supplied by the archived manifests.
