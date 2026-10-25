# Methods, evidence and limitations

## What is computed

1. Original ingestion deduplicates identities and quarantines conflicting payloads. A snapshot uses evidence available by its receipt/report cutoff.
2. Original robust references use median/MAD with an epsilon floor. The score is a weighted sum of capped absolute z values. Missing required channels produce undefined scores.
3. Original persistence requires current eligibility, minimum eligible windows and an above-threshold fraction. The group gate uses the roster denominator and integer eligibility/flag thresholds.
4. Original incident state retains typed M/H/P/F/U assertions with provenance, source class, age and status. It does not collapse evidence into a damage score.
5. Original rescue assignment maximizes urgent assignments, then policy priority, then minimizes estimated time. Eligibility includes access, competencies, PPE, availability and a time estimate.
6. Original continuity allocation is exact under specified binary-service constraints, dependencies, mandatory services and resource lower bounds. Energy and power are distinct. INFEASIBLE never receives a fabricated Q value.
7. Original recovery scheduling uses CPM and a serial scheduling heuristic. Hard prerequisites and crew/equipment capacity are modeled. It is not globally optimal and does not operate equipment.
8. Original proposal roles, content hashes and audit chains remain intact. The notebook never approves operational packages.

## What is verified

The unchanged116-test suite passes including six tests against the bundled P1 fixture. The44 supplied analytical targets pass. The notebook runs from its embedded bundle alone in an isolated fresh Jupyter kernel, and each analysis cell also runs alone in its own fresh kernel after the three setup cells. It verifies roster conservation, selected schedule precedences and crew non-overlap, original-source hashes, audit integrity/tamper detection and wrong-role rejection. Exact-solver tests in the original suite include comparisons with brute force.

## What is not verified

Real sensor validity, clinical accuracy, field rescue outcomes, access permission in an actual building, actual team availability, physical power switching, live LLM API compatibility and the hosted Colab frontend. A successful local run does not establish those properties.

## Prototype limitations demonstrated

- A role string is not an authenticated identity. Production deployment would need an external identity and authorization system.
- The audit is an unkeyed hash chain. Without trusted external checkpoints it cannot reliably establish authenticity, detect a complete rewrite or prove an omitted tail never existed.
- The LLM post-check tolerates numbers0–10 and does not reject a forbidden phrase already present in its input corpus. Therefore passing the filter is not semantic validation. The live LLM is disabled throughout this laboratory.
- The supplied P1 test class name includes 'RealP1Dataset'; it means the actual companion package fixture, not a real-world incident. Its data are synthetic.
- Replay display delays depend on the chosen one-minute step and uncertainty in source timestamps, not measured transport speed.
- Deterministic decisions can be reproduced, but audit wall-clock timestamps, temporary paths and corresponding hashes differ between runs. Byte-identical logs are not promised.
- The interactive explorer intentionally displays aggregate summaries. Raw numerical outputs remain available for audit, including original-language labels.

The limits are documented without modifying the original algorithms or quietly substituting another planner.
