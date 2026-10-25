# Safety and ethics

This software is **supplementary decision support** for authorised people at a critical-infrastructure
site. It carries no claim of medical-device approval, certified safety integrity or demonstrated
reduction in injury, and it has **not been validated against real rescue or recovery operations**.

## Human authority (Table 9)

* Every plan is a **proposal**. Nothing is executed by the software.
* Each decision package names its authorising role(s): rescue / emergency coordinator, incident command,
  incident coordination team, qualified assessor, infrastructure operator, recovery management,
  occupational health / site safety officer.
* Approvals and rejections require the decider's identity, an authorising role and a reason; they are
  appended to a hash-chained audit log together with the input SHA-256, versions, solver method and
  status. Superseded proposals lose their authorisation.
* `--auto-approve-for-simulation` exists only for testing pipelines. It is labelled in the CLI output,
  the briefing, the dashboard, the packages (`approved_simulation`) and the audit log (`simulated: true`).

## What the software never does

* No actuation: it does not stop a process, operate ventilation, unlock an area, switch power, restart
  production or authorise entry. Such task kinds are listed as excluded from recovery schedules.
* No medical triage categories, no diagnosis, no exposure or pathogen identification. A physiological
  group warning is a request for investigation.
* No building entry route selection; δ_rj is a qualified time estimate only.
* No automated building clearance; structural status is "unknown" unless a named qualified assessor
  reported it, with scope, method and validity.
* No strike attribution from local sensors; only `authoritative_external_alert` can report a strike.
  `possible_impact_local` is always labelled unverified.
* No casualty, injury, death or collapse inference from silence, link loss or missing telemetry. Link
  loss creates an observation gap with the last known state.
* Acoustic and PIR outputs are possible presence cues; they cannot establish that a person is present,
  trapped, alive, conscious or medically stable, and their absence cannot exclude a person.

## Uncertainty handling

* Missing → unknown, never normal; unknown capacity → zero guaranteed; unknown admissibility, access or
  eligibility → zero for automatic recommendation with an explicit escalation record (the task is never
  abandoned or down-ranked).
* Mandatory life-safety services are hard constraints; if they cannot be met the result is INFEASIBLE.
* Stale assertions remain visible as history but lose current authority.
* Coefficients h_j, p_j, w_j are command policy values, not survival probabilities; Q is weighted service
  coverage, not people rescued.

## Language-model layer

* Optional, off by default; the deterministic outputs are complete without it.
* The model sees only five read-only tools returning minimised aggregates (pseudonyms, counts, states,
  ages) — no raw physiology and no write or control capability.
* Its text is labelled "AI-generated summary — verify against deterministic outputs" and is rejected
  (deterministic briefing used instead) if it contains forbidden claims or numbers absent from the tool
  outputs, if the model refuses, or on any API error.

## Workers' rights and data protection (Sec. 3.7.2)

* Workers are participants and beneficiaries, not data sources only. Monitoring is not for disciplinary
  scoring, emotion inference, productivity ranking or covert assessment. Non-participation or a sensor
  outage is never evidence of misconduct.
* Packages, briefings, dashboard and LLM tools contain aggregates and pseudonyms; individual physiological
  windows stay in `result.json` under `workers_restricted` for authorised roles only.
* Small groups can be re-identifiable; deployments should restrict access to outputs accordingly, without
  hiding an urgent request from the person responsible for assistance.

## Data in this repository

All bundled data are **synthetic** (constructed scenario; no real site, persons, attack or measured
physiology). Heart-rate values are synthetic interface fields. Do not present outputs of the demo as
operational evidence.
