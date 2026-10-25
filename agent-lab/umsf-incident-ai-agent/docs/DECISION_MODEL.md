# Decision model

Equation numbers refer to Torstensson et al. (2026). Thresholds marked *policy* are development
parameters edited by incident command / occupational health (`src/umsf_agent/data/default_policy.json`),
not clinical thresholds or survival probabilities.

## 1. Personal deviation (Sec. 3.6.1–3.6.2)

**Eq. (1) robust z-score**

    z_ikt = (x_ikt − median(B_ikc)) / max{1.4826 · MAD(B_ikc), ε_k}

* B_ikc: quality-accepted 60 s window medians of worker i, feature k, context c (`low_motion` /
  `high_motion`, from motion RMS), strictly before the baseline end (`manifest.baseline_end`, else the
  first local incident observation).
* Fewer than `min_reference_windows` (*policy*, 8) → state `uncalibrated` → z undefined (never 0).
* ε_k (*policy*): 1.0 bpm for HR, 0.1 °C for skin temperature.

**Eq. (2) weighted capped score**

    d_it = Σ_k w_k · min{|z_ikt|, z_max},   Σ_k w_k = 1, w_k ≥ 0

Missing any feature of K → d undefined. It is a general deviation measure, not an infection probability
or toxic-exposure score.

**Eq. (3) persistent flag**

    a_it = 1{ Σ_{u=t−L+1..t} e_iu · 1{d_iu ≥ τ} / v_it ≥ ρ },   v_it = Σ e_iu

Evaluated only if the current window is eligible and v_it ≥ v_min; otherwise *unavailable* (None),
never 0. A window is eligible only if its records arrived within the freshness horizon (60 s) of the
window end: late backlog extends history but never makes a past window eligible.

## 2. Coverage-aware group gate (Sec. 3.6.3)

**Eq. (4)**  m = Σ_{i∈V} a_i,   p = m / n,   C = n / N

N = workers expected in the zone by the explicit roster; V = workers with an available flag. If n = 0, p
is undefined; if the roster is unavailable or N = 0, C is not computed and no automated group-normal
conclusion is allowed.

**Eq. (5)**  A = 1{ n ≥ n_min ∧ C ≥ C_min ∧ m ≥ m_min ∧ p ≥ θ }

**Integer reformulation (Sec. 4.3).** For N > 0: A = 1 ⇔ n ≥ max(n_min, ⌈C_min·N⌉) and
m ≥ max(m_min, ⌈θ·n⌉). The code evaluates both forms with exact rational arithmetic and asserts that they
agree; `tests/test_physio_rules.py` checks the equivalence exhaustively for N ≤ 15 and 32 parameter sets.
`threshold_feasibility` reports when a configuration can never issue a group warning for a roster
(e.g. N = 2 with n_min = 3).

**Decision states (Sec. 3.6.4):** `no_configured_deviation_detected_under_adequate_monitoring` (never
"safe"), `individual_review_indicated`, `possible_group_event`, `insufficient_monitoring_evidence`; the
urgent pathway (SOS / help request) is listed alongside, independent of coverage and persistence.

Table 10 (n_min 6, C_min 0.70, m_min 3, θ 0.30) is reproduced exactly; Study A (N = 6, n_min 5) gives an
effective minimum coverage of 83.3 % and a redundant nominal 70 % condition.

## 3. Zone incident state (Sec. 3.8)

**Eq. (6)**  S_z(t) = (M_z, H_z, P_z, F_z, U_z) — lists of typed assertions with source class, source id,
observed/report time, time uncertainty, quality, provenance, version / supersedes, status
(`current`, `stale`, `superseded`, `resolved`), verification (`unverified`, `instrument_uncalibrated`,
`qualified`, `authoritative`, `report`). No averaging into a damage score.

Freshness horizons (*policy*): mechanical excursion 1800 s, hazard alarm 600 s, presence cue 300 s,
responder/operator report 1800 s, asset status 3600 s, station current 60 s. Assistance requests never
age out silently. A silent node or link loss creates an `observation_gap` with the last known state and
removes the current authority of that node's hazard/presence evidence.

**Eq. (7)**  T_report = t_p − t_e,  T_action = t_a − t_e

t_e = event `observed_at` with `time_uncertainty_s`; t_p = first display by this agent; t_a = first
responder record with `provenance.method = response_action_start` and `related_event` = the event.
Uncertainty > 0 → interval [d − u, d + u]; unknown uncertainty or unqualified clock → `unqualified`.

## 4. Rescue assignment (Sec. 3.9.1)

**Eq. (8)**  Σ_j x_rj ≤ 1,  Σ_r x_rj ≤ 1,  x_rj ≤ e_rj · a_j,  x_rj ∈ {0, 1}

* e_rj = 1 iff the team is a rescue team, available in the interval, has all required competencies
  (aliases from policy) and, in a zone with gas evidence or an observation gap, the hazard PPE (*policy*).
* a_j = 1 iff a current incident-command authorisation covers the zone and scope; a current qualified
  assessment restricting entry overrides older authorisations. Unknown → 0 + escalation record; the
  task stays visible as "unresolved task requiring review".
* δ_rj = `eta_min`·60 (if supplied) or distance / speed, plus a setup time per task kind — a
  *qualified estimate*, not a validated route. Unknown δ → not eligible for automatic recommendation.
* Tasks needing several teams are excluded from Eq. (8) and flagged for a separate resource model.

**Eq. (9)**  lexmax ( Σ h_j x_rj ,  Σ p_j x_rj ,  − Σ δ_rj x_rj )

Exact method: with B2 = 1 + Σ_r max_j δ_rj and B1 = 1 + B2·Σ_r max_j p_j + B2, the scalar weight
B1·h_j + B2·p_j − δ_rj orders all matchings exactly as the lexicographic triple (all terms are
integers). A maximum-weight matching is found with the Hungarian algorithm on an (R+J)×(J+R) matrix with
zero-cost idle/unassigned dummies and prohibitive cost on forbidden pairs. `tests/test_assignment.py`
compares the triple with brute-force enumeration on 600 random instances.

## 5. Service continuity (Sec. 3.9.2, 4.9)

**Eq. (10)**  max Σ_j w_j y_j  s.t.  Σ_j a_kj y_j ≤ b_k ∀k;  y_j ≤ g_j;  y_j = 1 ∀j ∈ L;  y_j ≤ y_ℓ for each prerequisite (j requires ℓ)

* b_k: justified lower bound = sum of current per-asset contributions (register + `asset_status`
  reports carrying `capacity_lower_bounds`); a resource-level report replaces the resource total;
  unknown or stale → no guarantee (0). Never the pre-event rating.
* Energy (kWh over the declared horizon) is a separate constraint from power (kW); service energy demand
  is derived as kW × horizon unless given.
* g_j: `admissible` must be `true`; unknown → 0.
* Solver: exhaustive enumeration of 2^n vectors for n ≤ 20, depth-first branch-and-bound otherwise
  (tested against brute force). Tie-break: smaller normalised resource use, then earlier services.
* Empty feasible set → `INFEASIBLE` with reasons and options for review (additional resources,
  reduction of non-essential demand, transfer to a qualified alternate facility). Life-safety
  constraints are never relaxed.

**Eq. (11)**  Q(y) = 100 · Σ w_j y_j / Σ w_j — weighted service coverage, not people rescued.

Table 16 results: B < 3 infeasible; 3 ≤ B < 6 → (1,1,0,0), Q = 68.75 %; 6 ≤ B < 10 → (1,1,1,0),
Q = 93.75 %; B ≥ 10 → (1,1,1,1), Q = 100 %; one unit unused at B = 4; production does not displace water
at B = 7.

## 6. Recovery scheduling (Table 9)

Task templates (*policy*): structural inspection (qualified assessor), gas-hazard check (certified
instrument), debris clearance, temporary power path (connection by an authorised operator), comms
restoration, water / lighting restoration.

* Generation: impact evidence without a qualified assessment → structural inspection; gas or impact
  evidence → hazard check; `possible_impact_local` → debris clearance; link loss → comms restoration;
  services unsupported by the continuity proposal → restoration task (priority += 100 if mandatory,
  + 10·w_j); capacity-limited or infeasible continuity → temporary power path first.
* Hard prerequisites: entry tasks in a zone wait for the hazard check and (if required) the structural
  inspection of that zone; an assessment restricting entry blocks entry without command authorisation.
* Blocked if access is unknown, no crew has the competencies or equipment is unavailable / unknown;
  successors are blocked transitively.
* CPM gives ES/EF/LS/LF and slack; the serial SGS schedules in order (min LS, max priority, id) at the
  earliest time with a free competent crew and equipment capacity. Heuristic, not optimal.
* Actuation task kinds (`restart_production`, `switch_power_feed`, `operate_ventilation`, `unlock_area`,
  `stop_process`) and services needing actuation to restore are listed as excluded, never scheduled.
