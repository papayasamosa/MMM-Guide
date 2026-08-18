# Specification Authority

## Current PRD suite

| Property | Value |
|---|---|
| Suite name | Ancestry MMM PRD Suite Manifest |
| Version | Cross-Document Coherent v1.5 |
| v1.4 baseline effective date | 28 July 2026 |
| Operating model | Direct internal build by Ancestry Marketing Data Science |
| Repository | `papayasamosa/Media-Mix-Lab` |

## Version history: v1.4 to v1.5

v1.5 is a **focused update**, not a full-suite rewrite:

- Parts 3, 6, 10 and 11 are updated in v1.5 for the graph-first causal
  configuration decision (see `REQ-GRAPH-001`).
- Parts 1, 2, 4, 5, 7, 8 and 9 retain their v1.4 normative content under the
  v1.5 suite manifest, pending the next full-suite consolidation.

The v1.5 suite manifest describes Family History GSA acquisition (New, DNA
cross-sell, Winback) as the current primary business acquisition scope. Root
`AGENTS.md` separately requires that no hard-coded primary Family History
outcome be assumed without the approved outcome-definition and use-specific
approval chain (`REQ-OUT-001`, `REQ-OUT-002`). These are compatible only at
the level that GSA is the current business acquisition scope while its exact
event definition and permitted uses remain governed by the outcome-approval
chain — this repository does not hard-code a GSA default, and no change here
introduces one.

## Version history: focused Bayesian validation, causal identification, calibration and forecast-risk overlay

A newer focused source has been supplied, covering five parts:

```text
Ancestry MMM PRD Part 3, Cross-Document Coherent v1.7
  Bayesian Validation and Experiment Calibration
Ancestry MMM PRD Part 6, Cross-Document Coherent v1.6
  Causal Identification and Stability
Ancestry MMM PRD Part 7, Cross-Document Coherent v1.5
  Bayesian Validation, Structural Stability and Calibration
Ancestry MMM PRD Part 9, Cross-Document Coherent v1.5
  Bayesian Validation, Stability and Forecast Risk
Ancestry MMM PRD Part 10, Cross-Document Coherent v1.6
  Validation, Identification, Calibration and Forecast Risk
```

This is a **focused overlay/replacement for exactly these five parts**, not
a full-suite version bump. It does not, by itself, move any other part's
version, and it does not, by itself, move Part 3 beyond this overlay's
v1.7 (superseding the narrower Part 3 v1.6 variable-coverage/mixed-frequency
overlay recorded below — that overlay's own approved capability,
`REQ-COVERAGE-001`, is retained in full; only the version label advances).

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.7 focused overlay | Bayesian validation and experiment calibration — supersedes the v1.6 variable-coverage/mixed-frequency overlay's version label; that overlay's approved capability (`REQ-COVERAGE-001`) is unaffected |
| Part 4 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 5 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 6 | v1.6 focused overlay | Estimand-specific causal identification, latent-state identification, structural stability, experiment calibration — see `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-STAB-001`, `REQ-EXPMODE-001`, `REQ-CALIB-001` |
| Part 7 | v1.5 focused overlay | Uncertainty-aware predictive validation, leakage-safe historical validation, structural stability, identification, calibration, downstream forecast consequence — see `REQ-LEAK-001`, `REQ-STAB-001`, `REQ-PPD-001`, `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-EXPMODE-001`, `REQ-CALIB-001`, `REQ-FORECAST-001` |
| Part 8 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 9 | v1.5 focused overlay | Reporting requirements for the above evidence types — see the same records; reporting must consume, not recompute, these artefacts |
| Part 10 | v1.6 focused overlay | UX requirements for the above evidence types, including the mandated graphical-identification disclaimer — see the same records |
| Part 11 | v1.5 (graph-first update) | Retained; not updated by this overlay |

Do not treat this table as evidence that Part 1, 2, 4, 5, 8, or 11 is now at
any of v1.5/v1.6/v1.7 from this overlay. `REQ-LEAK-001`, `REQ-STAB-001`,
`REQ-PPD-001`, `REQ-IDENT-001`, `REQ-LATENT-001`, `REQ-EXPMODE-001`,
`REQ-CALIB-001`, and `REQ-FORECAST-001` (all `docs/approved_requirements/`)
translate this overlay's implementation-ready invariants into repository
authority. Each explicitly excludes the specific numeric thresholds,
formulas, and business/UX label decisions that the source PRD parts
themselves leave open in their own decision registers (Part 6 §37
`MD-001`–`MD-021`; Part 7 §48 `VL-001`–`VL-027`; Part 9 §48 `RP-001`–`RP-025`;
Part 10 §47 `UX-001`–`UX-030`) — none of those ~100 individually numbered
items is approved by this overlay's reconciliation, and none may be
hard-coded from PRD prose without a separate decision record.

## Version history: focused Part 3 v1.6 overlay (variable coverage and mixed frequency)

A newer focused source has been supplied, covering Part 3 only:

```text
Ancestry MMM PRD Part 3
Cross-Document Coherent v1.6
Variable Coverage and Mixed Frequency
```

This is a **focused overlay/replacement for Part 3**, not a full-suite
version bump. It does not, by itself, move any other part to v1.6. The
table below is the authoritative per-part version record for this overlay
alone — superseded for Part 3 specifically by the v1.7 overlay recorded
above, which retains this overlay's approved capability
(`REQ-COVERAGE-001`) in full and only advances the version label.

| Part | Version | Notes |
|---|---|---|
| Part 1 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 2 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 3 | v1.6 focused overlay | Variable coverage and mixed-frequency handling — see `REQ-COVERAGE-001`; superseded in version label only by the v1.7 overlay above |
| Part 4 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 5 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 6 | v1.5 (graph-first update) | Retained; not updated by this overlay |
| Part 7 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 8 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 9 | v1.4 (within v1.5 suite) | Retained; not updated by this overlay |
| Part 10 | v1.5 (graph-first update) | Retained; not updated by this overlay |
| Part 11 | v1.5 (graph-first update) | Retained; not updated by this overlay |

Do not treat this table as evidence that any part other than Part 3 is now
v1.6. `REQ-COVERAGE-001` (`docs/approved_requirements/REQ-COVERAGE-001.md`)
translates the overlay's approved capability set — the v1.6 invariants,
canonical missingness-state vocabulary, and variable-coverage-matrix
requirement — into repository authority. It separates what is approved now
(data/source/coverage semantics, frequency-transformation semantics,
coverage-matrix UI behaviour) from what still requires an explicit,
separately-approved modelling contract (representing market-specific/ragged
predictor sets inside the hierarchical model equations, `FR-MOD-015`) before
any model-engine mathematics may change.

## Operating model

Ancestry Marketing Data Science builds and operates the MMM platform directly.
There is no vendor handover workflow. The platform is licensed under open-source
terms and operated without an ongoing vendor licence, but the build, maintenance
and operation are performed by Ancestry's own data science team.

## Historical status of earlier documents

| Document | Status | Notes |
|---|---|---|
| Ancestry 2026 MMM RFP brief | Historical traceability source | Referenced for original context; not current authority |
| Ebiquity proposal | Historical traceability source | Informed initial scope; not current authority |
| Vendor implementation brief (Claude Code handoff) | Historical | Superseded by PRD v1.4; the `docs/ancestry_fh_mmm.md` file retains this as a record of what was built against |
| `docs/ancestry_fh_mmm.md` | Historical implementation context | Documents what the initial prototype was built against; not current specification authority |
| `docs/approved_requirements/` | Current specification authority | Approved, versioned implementation records |

## Repository implementation-authority hierarchy

For any implementation task within this repository, follow this order of
authority:

1. The task-specific implementation brief (supplied with the task)
2. Approved requirement records in `docs/approved_requirements/`
3. Applicable `AGENTS.md` files (root and per-directory)
4. Existing schemas, migrations, tests, and documented code contracts
5. Existing implementation behaviour, where it does not conflict with the above

If these sources conflict, stop and report the conflict. Do not independently
invent a business decision, silently reinterpret the PRD, or choose one
requirement based on personal judgement.

## Process for translating PRD decisions into approved requirements

1. A PRD requirement is identified as needing implementation.
2. An approved requirement record is created in `docs/approved_requirements/`
   with a unique `REQ-xxx-nnn` identifier.
3. The record captures: requirement ID, PRD source section, capability status,
   affected modules, acceptance tests, migration impact, unresolved decisions,
   owner and approval date.
4. The record is added to `docs/approved_requirements/index.json`.
5. Implementation proceeds against the approved record, not the PRD text.

## Current implementation gaps requiring decision records

Each row below is one of two distinct states, not to be conflated:

- **no approved requirement/decision yet** — no indexed `REQ-*` record
  exists for this capability at all;
- **requirement exists but capability incomplete** — an approved, indexed
  `REQ-*` record exists and covers governance, identity, or part of the
  capability, but the record's own text explicitly reserves the remaining
  target-state capability for a future, separately-scoped requirement.

| Capability | State | Notes |
|---|---|---|
| Governed FX (`REQ-FX-001`–`REQ-FX-006`) | No approved requirement/decision yet | No indexed record exists. |
| Sequential / weekly planning (`REQ-STATE-001`, `REQ-SCEN-001`–`003`) | Requirement exists but capability incomplete | All four records are approved and indexed (WP0, PR #261) - see "Approved requirement records already implemented" below for what each has delivered. `application/scenario_service.py` (WP5) and the manual-plan tab of `pages/08_Scenario_Planner.py` (WP5 part 2: short/long horizon, method labelling; WP5 part 3, 2026-08-18: terminal carryover and opt-in posterior uncertainty) now consume the contract for manual (non-optimised) evaluation; `core.optimization`'s objective (sequential optimisation) and scenario persistence/staleness remain unimplemented for all four. |
| Starting state and terminal state | Requirement exists but capability incomplete | Bundled with sequential/weekly planning above - see that row and `REQ-STATE-001`/`REQ-SCEN-003`. |
| Future-assumption bundles | No approved requirement/decision yet | No indexed record exists. |
| Time-varying baseline | No approved requirement/decision yet | No indexed record exists; see `AGENTS.md`'s future-variable-role #5 for the standing invariant any future approval must satisfy. |
| Search demand/capacity mathematics (latent demand estimation, cap-hit probability, captured-versus-unmet demand, joint media/cap optimisation) | Requirement exists but capability incomplete | `REQ-SEARCH-002` (approved 2026-08-15, implemented — see below) approves Candidate A, the first production Search mediation/capacity formulation, depending on the governed identities in `REQ-SEARCH-001` and the compiler in `REQ-GRAPH-001`. The approval authorises implementation and validation only; it does not approve Search estimates for official planning or optimisation — Search planning eligibility and cap optimisation remain disabled pending that separate evidence. |
| Capacity and cap semantics (`REQ-CAP-001`) | No approved requirement/decision yet | `AGENTS.md`'s "Capacity and cap invariants" section states the standing business/mathematical invariant; no `REQ-CAP-001` record yet translates it into an approved modelling contract. |
| Experiment translation and recalibration | Requirement exists but capability incomplete | Superseded by `REQ-EXPMODE-001`/`REQ-CALIB-001` below (approved 2026-08-17) — see those rows. |
| Reporting semantics | No approved requirement/decision yet | No indexed record exists. |
| Background jobs and service boundaries | No approved requirement/decision yet | No indexed record exists. |
| Prior-vs-posterior comparison summaries — `REQ-VAL-001` remaining scope | Requirement exists but capability incomplete | `REQ-VAL-001` is approved and substantially implemented, including prior predictive evidence (schema v4, `core.diagnostics.prior_predictive_summary`) and predictive-density evidence (schema v5, `core.diagnostics.predictive_density_summary` — PSIS-LOO/WAIC via `pm.compute_log_likelihood` + `az.loo`/`az.waic`, no refit). Its own record text explicitly defers this remaining check as a separately-scoped dependent package. |
| Variable coverage / mixed-frequency data contracts (Part 3 v1.6 overlay) — `REQ-COVERAGE-001` implementation scope | Requirement exists but capability incomplete | `REQ-COVERAGE-001` is approved and translates the v1.6 overlay's authority (canonical missingness-state vocabulary, coverage invariants, coverage-matrix requirement) into repository requirements. Delivered incrementally in PRs #151-#161 (2026-08-09 to 2026-08-11): source/coverage-matrix domain objects (`core.coverage`), immutable source-version capture on upload, the coverage-matrix builder and Data Coverage review UI, explicit join-mode and join-loss/unmatched-key diagnostics (`data.pipeline.join_sources_with_diagnostics`), a market x channel engine-capability report (`core.market_data_capability`) bound into model fingerprinting, project export/import, and the pre-fit prior-predictive workflow, an official-use governance gate binding that capability report (plus coverage-matrix freshness) to policy-backed model approval as an optional validation-policy gate, and canonical-calendar/mixed-frequency alignment contracts (`core.frequency_alignment`) — see "Approved requirement records already implemented" below. `REQ-COVERAGE-001` itself approves the typed contract only, not a statistical method (its own "Out of scope"); a narrow WP1 method catalogue (six method/variable-class registrations: `flow_count`/`calendar_overlap_allocation`, `stock_level`/`rate_index`/`survey_measurement`/`release_aware_locf`, `survey_measurement`/`native_cadence_only`, `event_flag`/`calendar_event_alignment`) was separately approved and registered since PR #250 (2026-08-15) by `docs/decision_required_frequency_methods.md`, is registered by default (`core.frequency_conversion.ensure_approved_frequency_methods`), and executes through `core.official_preparation` via `execute_frequency_conversion`. A variable class/method combination outside that narrow catalogue still has no approved method and remains decision-required. Still not implemented: a fit-consumed-variable capability report beyond market x channel. `FR-MOD-015` remains explicitly unresolved (record §6). |
| Market-specific / ragged predictor sets inside the hierarchical model equations (`FR-MOD-015`) | No approved requirement/decision yet | `REQ-COVERAGE-001` explicitly reserves this — no masking, zeroing, missing-data likelihood, or separate-coefficient treatment is approved; the current engine may only compile the rectangular subset it already supports and must fail closed for a requested ragged-predictor treatment it cannot represent. |
| Graph-compilable mediated / capacity-constrained / moderated / residual-interaction edges — `REQ-GRAPH-001` remaining scope | Requirement exists but capability incomplete | `REQ-GRAPH-001` is approved and implemented for `direct`, `cross_product_halo`, and `excluded_diagnostic_only` edges. The remaining edge roles are valid graph vocabulary but not yet engine-compilable (`core.graph_model_compiler.check_engine_capability` is authoritative on current support). |
| Leakage-safe, time-respecting historical validation folds (`REQ-LEAK-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core contract implemented Work Package 1 (2026-08-17): `core.validation_folds` provides typed fold manifests, per-variable leakage assessment against `core.coverage.VariableCoverageMatrix` (reusing `core.frequency_alignment`'s leakage/definition-break checks), and a leakage-safe backtest wrapper that refuses to fit an unsafe fold. `core.diagnostics.expanding_window_backtest` itself remains unchanged and still carries no leakage-safety claim. Not yet implemented: rebuilding the full model-ready frame/scaling pipeline per fold beyond what coverage metadata can verify, and `DiagnosticsArtefact`/UI wiring (deferred to Work Package 2, which shares the same fold manifests). |
| Structural stability evidence across historical folds (`REQ-STAB-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core contract implemented Work Package 2 part 2 (2026-08-17): `core.structural_stability` provides typed per-fold parameter snapshots and a structured, per-parameter cross-fold comparison (no threshold, no composite score), sharing fold-ID identity with `core.validation_folds` (`REQ-LEAK-001`). Still no real per-fold model re-estimation pipeline — the caller must supply each fold's parameter snapshot; `DiagnosticsArtefact`/UI wiring for this and `REQ-PPD-001` remains deferred until one exists. |
| Posterior predictive metric distributions (`REQ-PPD-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core contract implemented Work Package 2 (2026-08-17): `core.diagnostics.posterior_predictive_metric_distributions`/`core.market_specific_diagnostics.posterior_predictive_metric_distributions_market_specific` compute per-draw MAE/RMSE/sMAPE/WAPE/bias distributions from `trace.posterior["mu"]`, reusing (not recomputing) `REQ-VAL-001`'s existing posterior-mean point metrics for direct comparison. Not yet implemented: `DiagnosticsArtefact`/Diagnostics-page wiring (deferred until a real multi-fold re-estimation pipeline exists to also feed `REQ-STAB-001`, so both land in one coherent Diagnostics UI update). |
| Estimand-specific graphical identification (`REQ-IDENT-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core diagnostic implemented Work Package 3 (2026-08-17): `core.estimand_identification.assess_backdoor_identification` implements Pearl's back-door criterion (open backdoor paths, treatment-descendant exclusion, minimal adjustment sets, likely-collider flagging) via `networkx>=3.5` (new dependency), distinct from `REQ-GRAPH-001`'s structural validation and `core.identification_diagnostics`'s fitted-model checks. Supports adjustment-based total-effect estimands only; direct/structural estimands return `unsupported_by_current_checker`. Not yet implemented: `core.graph_model_compiler` blocking-error extension and `DiagnosticsArtefact`/Diagnostics-page wiring. |
| Latent-state scale/location identification (`REQ-LATENT-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core diagnostic implemented Work Package 3, second record (2026-08-17): `core.latent_state_identification` provides a model-agnostic identification-declaration contract (five approved strategy kinds, explicit description, optional anchor) and an empirical cross-chain sign-flip check plus descriptive (non-threshold) scale-drift ratio, resolving a closed four-value status, with `is_eligible_for_official_use` implementing the fail-closed use-eligibility gate. Standalone module — never collapsed into `REQ-IDENT-001`'s or `REQ-STAB-001`'s result types. Candidate A's latent branded-search demand (`core.search_capacity`, `REQ-SEARCH-002`) remains the first concrete integration target, but its actual identifying anchor (`MD-021`) is still an unresolved statistical decision, not approved by this record. Not yet implemented: `core.graph_model_compiler` blocking-error extension, full synthetic-recovery/decision-instability validation, and `DiagnosticsArtefact`/Causal-Graph-page wiring. |
| Experiment evidence modes and provenance (`REQ-EXPMODE-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core registry implemented Work Package 4 (2026-08-18): `core.experiments` provides an immutable, versioned `ExperimentRecord` (mirroring `core.causal_graph`/`core.search_objects`'s lineage pattern), `ExperimentToModelUse`'s closed four-value evidence-mode vocabulary, a caller-evidenced `CompatibilityAssessment` across all nine required dimensions, a fail-closed `build_calibrating_use` gate, a double-counting check, and a per-experiment (never averaged) provenance report. Registering an experiment cannot silently calibrate a model because no model-fitting module reads this registry yet. Not yet implemented: any specific likelihood-/prior-calibration statistical mechanism (reserved for a future decision-support package per this record's own text), `core.persistence` export/import wiring, and `REQ-CALIB-001`'s dependent comparison contract. |
| Calibrated-versus-uncalibrated model comparison (`REQ-CALIB-001`) | Requirement exists but capability incomplete | Approved 2026-08-17 (Work Package 0), core comparison contract implemented Work Package 4 (2026-08-18): `core.calibration_comparison` reuses `core.model_identity.ModelIdentity` directly (resolving this record's own identity-architecture open question), rejecting construction unless the calibrated and uncalibrated identities are genuinely distinct (Requirement 1). Generic per-metric and per-experiment-agreement comparison, with no threshold/verdict/"preferred" field anywhere — verified by an explicit field-name scan (Requirement 3). `CalibrationEventRecord` implements Requirement 5's per-event record as caller-supplied, structured facts. Depends on `REQ-EXPMODE-001` (not yet coupled by import). No calibration mechanism exists or is implied. Not yet implemented: material-change criteria, any comparison metric's computation, and `pages/06_Diagnostics.py` UI wiring (Requirement 4). |
| Downstream forecast-consequence evidence (`REQ-FORECAST-001`) | Requirement exists but capability incomplete | Approved 2026-08-17. Separate from, and narrower than, the still-unapproved "Future-assumption bundles" row above — covers only the consequence-assessment contract for an already-classified exogenous control. Zero implementation yet. |

## Approved requirement records already implemented (with documented capability boundaries)

`REQ-GRAPH-001` (graph-authoritative causal configuration),
`REQ-SEARCH-001` (Search object separation/governance), `REQ-SEARCH-002`
(Candidate A Search mediation/capacity engine), `REQ-STATE-001` (sequential
state contract), `REQ-SCEN-001` (sequential scenario evaluation contract),
`REQ-SCEN-002` (monthly-to-weekly phasing contract), and `REQ-SCEN-003`
(response horizon and terminal reporting contract) are approved, indexed
requirement records with substantive implementation. None is a gap
requiring a new decision record — each has an explicit, narrower capability
boundary documented in its own record:

- `REQ-GRAPH-001` (`docs/approved_requirements/REQ-GRAPH-001.md`): the graph
  domain, versioning, structural/layout fingerprints, deterministic
  validation, compiler integration, and Streamlit editor are implemented.
  Engine-compilable edge roles remain limited — see the gaps table above.
- `REQ-SEARCH-001` (`docs/approved_requirements/REQ-SEARCH-001.md`):
  distinct governed objects for `search_demand`, `paid_search_spend`,
  `paid_search_delivery`, `paid_search_cap`, `organic_search_capture`, and
  `direct_navigation_capture` are implemented, including cap-counterpart
  validation, effective periods, version history, persistence, and
  fit-relevant fingerprint integration. Search demand/capacity mathematics
  is explicitly out of scope for this record — see the gaps table above.
- `REQ-SEARCH-002` (`docs/approved_requirements/REQ-SEARCH-002.md`):
  Candidate A, the first production Search mediation/capacity formulation
  (approved 2026-08-15), depending on `REQ-SEARCH-001`'s governed identities
  and `REQ-GRAPH-001`'s compiler. `core.search_capacity` is wired into Model
  Training's fit path (`application/model_fit_service.py`,
  `core.hierarchical_model.build_fh_hierarchical_model(...,
  search_candidate_a=...)`), governed by the project's approved causal
  graph, never a UI toggle, and into a dedicated "Candidate A Search"
  Diagnostics tab (`DiagnosticsArtefact.search_capacity` schema v7,
  `core.search_capacity.extract_candidate_a_search_posterior_summary`).
  `core.predict.predict_mu` and `core.attribution.compute_shapley_
  contributions` fail closed with a specific, documented exception for a
  Candidate A fit rather than silently reconstructing an outcome missing
  the search-mediated pathway — this is the actual mechanism keeping
  Search planning/optimisation disabled, not a separate per-feature gate.
  Not yet wired: Results attribution, official response curves, and
  Scenario Planner replay (`predict_mu` has no way to re-evaluate a
  *counterfactual* Search state at a hypothetical scenario/curve point — a
  modelling design question, not a mechanical extension; reasons recorded
  in `docs/decision_log.md`). The approval authorises implementation and
  validation only; it does not approve Search estimates for official
  planning or optimisation.
- `REQ-STATE-001` (`docs/approved_requirements/REQ-STATE-001.md`): the
  sequential (weekly, state-transition) simulation state contract —
  real historical-media starting-adstock reconstruction, no cross-market
  carryover, an explicit `WeeklyPlan` input contract, ending state and
  terminal continuation as structurally separate results, both a fixed-
  carry-in and a fully draw-consistent posterior evaluator for both
  production-supported model types (`core.sequential_simulation`, WP5/PR
  #260, draw-consistent evaluators added WP3 of `...Post PR262`), and
  fail-closed historical-state resolution
  (`_resolve_and_validate_market_history`, WP3). Not yet covered: how a
  monthly plan becomes a `WeeklyPlan` (`REQ-SCEN-002`) and application-layer
  integration.
- `REQ-SCEN-001` (`docs/approved_requirements/REQ-SCEN-001.md`): the
  sequential scenario evaluation contract. Kernel-level items (same
  simulator for candidate/reference, exact-zero no-change invariant,
  Model A and Model C support, both posterior-propagation variants, and a
  typed shared evaluation context — `core.sequential_evaluation_context`,
  WP3 — guarding candidate/reference identity beyond
  `compute_incremental_outcome`'s own market/period/outcome check) are
  implemented. Application-level items (monthly aggregation after weekly
  evaluation, steady-state/sequential method labelling, shared phasing
  policy) are implemented at the application-*service* level (WP5 of
  `...Post PR262`, `core.sequential_scenario_evaluation`, `application.
  scenario_service.ScenarioService.evaluate_manual_sequential`), and, for
  the manual-plan path, in the Streamlit page (`pages/08_Scenario_
  Planner.py`, WP5 part 2 - the "Manual plan evaluation method" radio on
  the "Edited plan and calculated result" tab); the constrained and
  unconstrained-benchmark tabs remain steady-state-only.
- `REQ-SCEN-002` (`docs/approved_requirements/REQ-SCEN-002.md`): the
  monthly-to-weekly phasing and future-context contract. Phasing
  (`calendar_day_overlap_v1`, WP1, `core.planning.phasing`): exact
  day-overlap allocation, per-month conservation to strict numerical
  tolerance, auditable boundary-week attribution, an explicit
  weekly-schedule override with its own reconciliation check, and separate
  monetary/model-input-quantity paths. Future context (WP4 of `...Post
  PR262`, `core.planning.future_context`): trend/Fourier continued via the
  fitted model's own definitions, official-mode fail-closed missing-
  control checks, exploratory-mode labelled `hold_last_observed`. Governed
  `WeeklyPlan` construction (`core.planning.weekly_plan_builder`) and the
  terminal candidate/reference evaluator (`core.planning.
  terminal_response`) complete the core-module implementation. Wired into
  `application.scenario_service` (WP5) and the manual-plan tab of
  `pages/08_Scenario_Planner.py` (WP5 part 2) — the page phases its
  necessarily-partial first sequential month (the plan starts the Monday
  immediately after history ends, not at a month boundary) with the same
  day-overlap formula scoped to covered days, summed with the unmodified
  governed function's output for every subsequent whole month; `phasing.py`
  itself is unchanged.
- `REQ-SCEN-003` (`docs/approved_requirements/REQ-SCEN-003.md`): response
  horizon and terminal reporting. The typed `HorizonConfiguration`
  contract (short/long/plan/terminal horizons, explicit values required)
  is implemented (`core.planning.phasing.HorizonConfiguration`), and the
  business-facing terminal candidate/reference evaluator
  (`core.planning.terminal_response`, WP4 of `...Post PR262`) reports
  terminal incremental response as a structurally separate result, sharing
  one real future non-decision context between candidate and reference.
  Persistence with a saved scenario, and exclusion of terminal carryover
  from the optimisation objective, remain unimplemented pending
  application-layer integration.
- `REQ-COVERAGE-001` (`docs/approved_requirements/REQ-COVERAGE-001.md`):
  the variable-coverage/missingness domain (`core.coverage`:
  `SourceDefinition`, `SourceVersion`, `FrequencyMetadata`,
  `DefinitionBreak`, `VariableCoverageRecord`, `VariableCoverageMatrix`,
  strict schema versioning), immutable source-version capture on upload
  (checksum/filename/size; CSV/XLS/XLSX/XLSM/Parquet), the coverage-matrix
  builder (`build_coverage_matrix_from_frame`) and Data Coverage review UI,
  fit-relevant versus presentation-only coverage fingerprinting bound into
  model identity and project export/import, explicit join-mode and
  join-loss/unmatched-key diagnostics (`data.pipeline.
  join_sources_with_diagnostics`), a market x channel engine-capability
  report (`core.market_data_capability.check_market_channel_capability`)
  bound into model staleness and the pre-fit prior-predictive workflow, an
  official-use governance gate binding that capability report (plus
  coverage-matrix freshness against the current joined data) to
  policy-backed model approval as an optional, non-waivable
  `market_channel_capability` validation gate (`core.validation_policy`,
  `DiagnosticsArtefact.market_channel_capability`), and canonical-calendar/
  mixed-frequency alignment contracts (`core.frequency_alignment`:
  `AlignmentSpecification`, publication-leakage/definition-break/
  support-boundary checks, and `resolve_canonical_calendar` — fails closed
  with `CalendarResolutionRequiredError` rather than inferring a calendar
  from raw source intersection) are implemented. `REQ-COVERAGE-001` itself
  approves this typed contract only and starts with a genuinely empty
  conversion-method registry — it does not select a statistical method
  (its own "Out of scope"). Frequency-conversion *execution* for a narrow
  WP1 method catalogue was separately approved and registered since PR
  #250 (2026-08-15, `docs/decision_required_frequency_methods.md`,
  `core.frequency_conversion.ensure_approved_frequency_methods`) and is
  wired into official-use data preparation (`core.official_preparation`,
  `execute_frequency_conversion`) — see the gaps-table row above for the
  current catalogue and its boundary. A fit-consumed-variable capability
  report beyond market x channel (outcome source columns, controls,
  promotions) remains unimplemented — see the gaps table above.
  `FR-MOD-015` (market-specific/ragged predictor sets) remains explicitly
  unresolved (record §6).
