# Media-Mix-Lab: Current Repository State

This document is the concise repository-status summary for the current
checkout. It is intentionally separate from approved business requirements
and does not supersede `AGENTS.md`, `docs/approved_requirements/`, or
`docs/decision_log.md`.

## Repository baseline

Repository: `papayasamosa/Media-Mix-Lab`

This is descriptive repository-status documentation, not a live Git
pointer. Resolve current remote `main` from GitHub before relying on it
for the actual live state of the repository - fetch `origin` and resolve
`origin/main`'s SHA directly; never treat this version-controlled status
file as live remote truth.

This document previously identified its baseline with a leading
"Repository state through merged PR #<N>" milestone marker, on the theory
that a PR-number marker was safer than a live-SHA field. In practice that
marker drifted exactly the same way: it was written as "merged PR #269"
and left in place while PRs #270-#284 (leakage-safe validation folds,
posterior predictive metrics, structural stability, graphical and
latent-state identification, experiment evidence modes, calibration
comparison, sequential Scenario Planner UI reconciliation, and the WP6-WP11
decision/evidence packages) merged on top of it - the identical failure
mode as the earlier live-SHA field it replaced (see the SHA-drift incident
below: `6f342afcc03a588eb5738b8813d3d2b8beb54b57`, PR #261's merge commit,
was once claimed as "current `main`" while PR #262 was already merged on
top of it). Any global "this is the current PR/milestone" field in this
file - by SHA or by PR number - is guaranteed to go stale the moment the
next PR merges, because a branch authoring this file cannot know what
merges after it. `ancestry_mmm/tests/test_repository_status_conformance.py::
test_repo_review_does_not_assert_a_global_current_pr_or_milestone_marker`
guards this convention. Individual historical entries below may still cite
the specific PR they were merged in - that is a fact about the past, not a
claim about the live present - but no sentence in this file may assert
which PR/milestone the *whole repository* is currently at.

Historical markers (all superseded merge commits; recorded only for
history, never as current state):
`a047bca8ddddea760a376b8f3de2e0429d691280` (merged PR #268, WP0: PRD
Bayesian validation/identification/calibration authority reconciliation -
superseded by PR #269 above),
`f7ed28630b50b24baa4b806fcb47213b0a156e0a` (merged PR #267, WP5 part 2 of
`...Post PR262` - sequential scenario planner UI wiring - superseded by
PR #268 above),
`79bbc174e90eb7ec62595f379a61912966be6ec2` (merged PR #266, WP5 part 1 of
`...Post PR262` - sequential scenario evaluation service - superseded by
PR #267 above),
`ba29b04526843879722fc0f4bc4cf799063e4733` (merged PR #265, WP4 of
`...Post PR262` - future context, governed WeeklyPlan construction,
terminal response - superseded by PR #266 above),
`ce5b3962b7eb4f66bc7549ab62cc6178c02e1220` (merged PR #264, WP3 of
`...Post PR262` - draw-consistent sequential state and evaluation context -
superseded by PR #265 above),
`8ddf3568aad0f6806f43e9fe3e5e2ddcfea471cd` (merged PR #263, WP2 of
`...Post PR262` - authority-doc reconciliation and merge-gate hardening -
superseded by PR #264 above),
`a2a4f75422f58f16c1894a2ef02b7a9bb375e53b` (merged PR #262, WP1 of
`...Post WP5` - the monthly-to-weekly phasing contract, `core.planning.
phasing`, `REQ-SCEN-002`/`REQ-SCEN-003` - superseded by PR #263 above),
`6f342afcc03a588eb5738b8813d3d2b8beb54b57`
(merged PR #261, WP0 of `...Post WP5` - reconciled `REQ-SCEN-002`'s
top-of-file wording, indexed `REQ-STATE-001`/`REQ-SCEN-001`-`003`, added
`scripts/wait_for_pr_green_then_merge.ps1`),
`ef4744f1d587f061e8859cb26e24740325335de2` (merged PR #260, WP5 of
`...After PR #253` - the sequential simulation kernel - superseded by
Work Package 0 of `...Post WP5` above, merged as PR #261),
`30c841b3c457771a4df0b5e21c06cd281be3f82e` (merged PR #259, WP5 test-double
fix, superseded by PR #260),
`3a0015848bb85c71c0fa3013cdf312bf7e3f80e4` (merged PR #257, WP3),
`0ed00d8a790669f7fbdf716c070a24fb4442964c` (merged PR #256, WP2),
`e117abcd60171c3f2a57b437d617135e475a62bf` (merged PR #255, WP1),
`3e2e525300a8526a52f59384271e54fe9815cbe0` (merged PR #254, WP0), and
before that `b9b13916ad06c09e37cd53aa83a0fa3a7949a0dc` (merged PR #253) and
`0845b150027dc59b192d2ec314b01910af3496ed` (merged PR #249, before the
mixed-frequency executor and Candidate A Search engine existed). WP4
(targeted structural/test hardening) merged as PR #258 (`3cfe66de1244fc990c4d47ae6f7fa573ce2f64d2`)
but that commit briefly left `main`'s own CI red - the repository has no
branch protection on `main`, so `gh pr merge --auto` merged before checks
completed; the one-file fix (a test double missing a new attribute) merged
as PR #259, restoring `main`'s CI to green before WP5 (PR #260) merged on
top of it. All SHAs listed in this paragraph are superseded and are
recorded here only for history, not as current state.

The local Python distribution name remains `mmm-guide` for compatibility with
the existing install, script, export, and deployment surface. That legacy
distribution identifier is not the GitHub repository identity and is not
renamed by this status reconciliation.

## Delivered foundation

The current implementation includes:

- Streamlit workflow state, readiness guidance, technical pages, reporting,
  planning, project export, and project recovery.
- Immutable source versions and four logical source domains: Outcomes,
  Activity and Media, Context and External Factors, and optional Experiment
  Evidence.
- Standard workbook downloads for all four domains.
- Outcomes source-pack v2 parsing/adoption, governed outcome definitions and
  groups, draw-level grouped totals, DNA partition safeguards, and realistic
  synthetic templates.
- Explicit Family History New, DNA cross-sell, and Winback outcomes plus
  governed DNA outcomes.
- Governed activity definitions, identity-only `pooling_group_id`, ownership,
  model-input/spend/response-unit semantics, and cost mappings.
- Explicit Search-object governance separating demand, Paid Search spend and
  delivery, caps, organic/direct capture, and residual incrementality.
- Graph-authoritative direct, cross-product-halo, and excluded/diagnostic-only
  structures. Unsupported mediated, capacity-constrained, moderated, and
  residual-interaction engine structures fail closed.
- Joint hierarchical and market-specific partially pooled PyMC paths,
  outcome-scale counterfactual curves, draw-level totals, attribution,
  governed curve artefacts, and cost/FX-aware economics.
- Validation, approval, staleness, persistence, migration, resumability,
  scenario-planning, and optimisation contracts.
- Canonical native-weekly official preparation with an explicit governed
  calendar, an outer union of governed source periods, preserved missingness,
  and a fit-consumed-variable capability gate, plus an explicit, versioned,
  **executable** mixed-frequency conversion catalogue/executor
  (`calendar_overlap_allocation` for `flow_count`, `release_aware_locf` for
  `stock_level`/`rate_index`/`survey_measurement`, `native_cadence_only` for
  `survey_measurement`, `calendar_event_alignment` for `event_flag` —
  `docs/mixed_frequency_alignment_wp1.md`). Missing method IDs, version
  mismatches, definition breaks, leakage, and unsupported parameter shapes
  still fail closed; conversion is selected from the Coverage review, never
  inferred from source frequency or column names.
- Standard source-pack semantic adoption for Outcomes, Activity and Media,
  Context and External Factors, and optional Experiment Evidence, plus the
  current source-pack template/download and realistic synthetic-pack UX.
- Current graph-authoritative Causal Graph and Search-object governance UX,
  including direct, cross-product-halo, and excluded/diagnostic-only support
  with unsupported production graph roles still blocked.
- A governed Candidate A Search mediation/capacity engine capability
  (`ancestry_mmm/core/search_capacity.py`, `REQ-SEARCH-002`): a typed
  `SearchCandidateASpec`, forward/reconciliation contracts, identification
  diagnostics, outcome-scale direct/mediated/total effect helpers, a
  Candidate A use gate, and exact Candidate A graph/compiler support.
- Candidate A production integration boundary (WP1): the Candidate A demand/
  capture chain (`attach_candidate_a_demand_capture_chain`) is now spliced
  directly into `core.hierarchical_model.build_fh_hierarchical_model` via an
  optional `search_candidate_a` parameter, reusing that builder's own shared
  multi-channel adstock/Hill-saturated media, market hierarchy, and Negative
  Binomial outcome likelihood rather than a second, simplified model - proven
  by a real `pm.Model` + `pm.draw` reconciliation/non-binding-cap-invariant
  test (`ancestry_mmm/tests/test_hierarchical_model.py::
  TestCandidateASearchIntegration`). `application/model_fit_service.py` is
  the new framework-independent engine-selection adapter
  (`resolve_engine`/`build_model_for_spec`) that
  `pages/05_Model_Training.py` now calls instead of branching on
  `model_type` inline; engine selection is governed by whether the
  project's approved causal graph requires the Candidate A engine
  (`core.graph_model_compiler.check_engine_capability`), never a UI toggle.
  `FHModelMeta.causal_graph_engine` (an existing, already-persisted field)
  carries the Candidate A engine identity through project export/import with
  no schema change - see Known bounded gaps for what remains unintegrated.
- A sequential (weekly, state-transition) simulation kernel (WP5,
  `ancestry_mmm/core/sequential_simulation.py`), sitting alongside - never
  replacing - the existing steady-state monthly planner
  (`core.optimization`, `core.predict.steady_state_outcome_response`): real
  historical-media starting-adstock reconstruction
  (`reconstruct_starting_state`/`_market_specific`, never assuming zero or
  steady state, never crossing market boundaries), an explicit weekly-plan
  input contract (`WeeklyPlan` - it never decides how a coarser plan spreads
  across weeks, deferred to WP6), a candidate/reference contract sharing one
  simulator (`compute_incremental_outcome`, with an exact-zero no-change
  invariant), full per-draw posterior paths
  (`simulate_sequential_outcomes_posterior`, aggregated only by the caller),
  and terminal carryover as a structurally separate result
  (`simulate_terminal_carryover`). Implemented for both production-
  supported model types (shared/Model A and market-specific/Model C).
  Candidate A gets a bounded, explicitly diagnostic-only mediator-state
  replay (`simulate_candidate_a_mediator_state_sequentially`) - demand/
  capture/cap only, never the final outcome; Search planning eligibility
  remains governed separately. Proven by a golden-equivalence test suite
  (`test_sequential_simulation.py`) asserting the kernel's output over a
  future plan window is bit-identical to the existing batch replay
  (`predict_mu`) evaluated over the same series as a whole. Work Package 3
  of `Media-Mix-Lab: Coding LLM Next Steps Post PR262` added: a fully
  draw-consistent posterior evaluator for both model types
  (`simulate_sequential_outcomes_posterior_draw_consistent`/`..._market_
  specific_draw_consistent` - each selected posterior draw's own
  parameters reconstruct historical carry-in *and* run the future
  recursion, proven per-draw against the batch replay and covered by a
  regression that fails if a fixed carry-in state were accidentally reused
  across draws), Model C posterior-evaluator parity at the fixed-carry-in
  level (`simulate_sequential_outcomes_posterior_market_specific`), a
  fail-closed historical-state resolution boundary
  (`_resolve_and_validate_market_history` - rejects a `historical_frame`
  whose market bounds/index metadata is malformed or internally
  inconsistent rather than silently reconstructing carry-in from the wrong
  market), and a typed shared evaluation context
  (`ancestry_mmm/core/sequential_evaluation_context.py`,
  `SequentialEvaluationContext`/`require_matching_context`/
  `compute_incremental_outcome_with_context`) that catches a candidate/
  reference pair built from mismatched model/posterior/historical-state/
  phasing/future-assumption/cost/counterfactual-policy identity -
  something `compute_incremental_outcome`'s own market/period/outcome
  check alone cannot see.
- A monthly-to-weekly phasing contract (WP1 of `Media-Mix-Lab: Coding LLM
  Next Steps Post WP5`, `ancestry_mmm/core/planning/phasing.py`,
  `REQ-SCEN-002`/`REQ-SCEN-003`): `calendar_day_overlap_v1` - inclusive
  day-overlap allocation with per-month conservation to strict numerical
  tolerance, auditable boundary-week attribution (a week spanning two
  months legitimately receives allocations from both); an explicit
  weekly-schedule override with its own tracked-month-weighted
  reconciliation check; separate monetary (phase-then-convert via a
  weekly/period-specific `core.media_costs` mapping resolved per week) and
  model-input-quantity (no cost conversion) paths, so a plan can never be
  ambiguously read as both spend and delivery; and a typed
  `HorizonConfiguration` contract (short/long/plan/terminal horizons,
  explicit values required). This is a framework-independent core module
  only - not yet wired into any application service (see Known bounded
  gaps below).
- Future context, governed `WeeklyPlan` construction, and terminal
  incremental response (Work Package 4 of `Media-Mix-Lab: Coding LLM Next
  Steps Post PR262`, `REQ-SCEN-002`/`REQ-SCEN-003`) - the bridge from
  phased monthly decisions plus explicit future assumptions to an
  application-safe weekly simulation input:
  `ancestry_mmm/core/planning/future_context.py` continues the fitted
  model's own trend definition (per-market row-index normalized by
  historical count) and Fourier/seasonality definition (calendar-anchored,
  day-of-year) forward into future weeks - mirrored, not imported, from
  `data.preprocessor` (`core` must not depend on `data`), kept numerically
  identical by test; official mode fails closed on any missing future
  promo/control value, exploratory mode permits an explicitly opted-in,
  eligible control to use a labelled/fingerprinted/decision-excluded
  `hold_last_observed` assumption (promotions/events never get this
  relaxation, in any mode).
  `ancestry_mmm/core/planning/weekly_plan_builder.py` is the governed
  construction boundary above phased allocations + future context -
  validates exact canonical week order, exact expected channel set (no
  unknown channel silently ignored), finite non-negative values even on
  direct construction, and Fourier/outcome/control shape/identity against
  the fitted model - before building `core.sequential_simulation.
  WeeklyPlan`; stores construction provenance/fingerprint; does not
  duplicate `application.scenario_service.ScenarioPlan`.
  `ancestry_mmm/core/planning/terminal_response.py` is the business-facing
  terminal candidate/reference evaluator distinguished from
  `core.sequential_simulation.zero_media_extension_plan`'s low-level
  all-zero decay fixture: extends candidate and reference over the SAME
  future calendar sharing ONE real future non-decision context, zero
  future decision media only (the initial residual-carryover policy), and
  reports `candidate - reference` as a structurally separate
  `TerminalIncrementalResult`. All three remain framework-independent core
  modules only.
- Sequential-weekly manual scenario evaluation service (Work Package 5 of
  `Media-Mix-Lab: Coding LLM Next Steps Post PR262`,
  `ancestry_mmm/core/sequential_scenario_evaluation.py`,
  `ancestry_mmm/application/scenario_service.py`): orchestrates already-
  governed candidate/reference `WeeklyPlan`s through historical-state
  reconstruction, one shared `SequentialEvaluationContext`, weekly
  incrementality, monthly aggregation (only after weekly evaluation),
  short/long horizon response, terminal incremental carryover (structurally
  separate), and optional fully draw-consistent posterior evaluation -
  reusing the same governance/economics machinery
  (`core.planning_governance.resolve_planning_governance`,
  `core.scenario_governance.resolve_scenario_plan`, both confirmed period-
  key-agnostic, not steady-state-specific) the existing steady-state path
  uses, so the two paths never diverge in what "official" governance
  means. `ScenarioService.evaluate_manual_sequential` dispatches to it,
  mirroring `evaluate_manual`'s existing dispatch pattern. Also fixed in
  this package: `core.optimization.validate_scenario_dependencies`'s
  `planning_semantics_fingerprint` staleness check was hard-coded to only
  recognise the steady-state engine's semantics as "current" - a
  sequential scenario would have appeared permanently stale the moment it
  was saved; now engine-aware. Candidate A fail-closed behaviour is
  inherited for free (calling into `core.sequential_simulation` means
  `CandidateAReplayNotSupportedError` propagates unchanged).
- Sequential-weekly manual scenario evaluation wired into the Scenario
  Planner UI (Work Package 5 part 2 of `Media-Mix-Lab: Coding LLM Next
  Steps Post PR262`, `pages/08_Scenario_Planner.py`): a "Manual plan
  evaluation method" radio (steady-state monthly / sequential weekly) on
  the "Edited plan and calculated result" tab only - the constrained and
  unconstrained-benchmark optimiser tabs remain steady-state-only. The
  sequential plan window always starts the Monday immediately following
  the market's last historical week, continuing the exact same weekly
  cadence with no gap - never the steady-state tab's user-chosen start
  month. Renders weekly and monthly incremental tables and short/long
  response-horizon metrics. Work Package 5 part 3 (2026-08-18) further
  builds a `terminal_future_context` (reusing the same already-
  acknowledged assumption set, no new consent gate) and renders the
  resulting `TerminalIncrementalResult` under a "Terminal carryover
  (informational)" heading, structurally separate from the plan-window
  tables above; an opt-in checkbox ("Show posterior uncertainty for this
  sequential plan", mirroring the steady-state tab's own opt-in pattern)
  passes `n_posterior_draws`/`trace` through and renders a plan-window-
  total mean/median/90% credible-interval summary from `result.
  posterior_weekly_incremental`. Work Package 5 part 4 (2026-08-18) adds
  save/export: `core.sequential_scenario_evaluation.sequential_scenario_
  to_dict` appends a `calculation_method="sequential_weekly"` dict to the
  SAME `scenarios` list a steady-state scenario is saved to - never a
  separate parallel list - so the existing `core.persistence` export/
  import path handles it with no persistence-layer change (confirmed by
  an explicit round-trip test), and `core.optimization.scenario_from_
  dict` gained a guard passing it through unchanged rather than applying
  steady-state legacy migration. Staleness reuses the same cost-mapping/
  counterfactual-policy check the steady-state path already had. Saved
  sequential scenarios render in a separate "Saved sequential-weekly
  scenarios" summary, since `compare_scenarios` requires a `predicted`
  DataFrame no sequential scenario dict carries. **Not yet implemented in
  this UI:** sequential-weekly optimisation - explicitly disclosed on the
  page, not silently absent. See Known bounded gaps below.
- Sequential Scenario Planner UI semantic-defect reconciliation (Work
  Package 0 part 2 of `Media-Mix-Lab: Coding LLM Next Steps After PR
  #267 and Latest PRD Validation Updates`, `pages/08_Scenario_Planner.py`,
  `core/planning/phasing.py`): the re-seating of the analyst's ordered
  monthly values onto real calendar months, the partial-first-month
  phasing, and the per-week cost-mapping conversion are now governed
  `core.planning.phasing` functions
  (`reseat_ordinal_monthly_plan_to_start_week`,
  `phase_monthly_series_from_partial_start_calendar_day_overlap_v1`,
  `phase_monetary_plan_from_partial_start_calendar_day_overlap_v1`) with
  their own unit tests - `core/planning/phasing.py` is no longer
  unchanged by this UI path. The sequential tab now blocks calculation
  until the analyst explicitly acknowledges, via checkbox, each of: the
  entered-month -> real-calendar-month reassignment (shown as a table
  whenever the two differ); holding any fitted exogenous control at its
  last observed value (exploratory, not an official forecast); and that
  no promotion is planned for the plan window - none of the three is an
  automatic page default any longer. Resolves via UI disclosure and
  explicit consent, not a new bridge-period/start-date business contract
  (the brief's own permitted alternative). No new future-control-input or
  promotion-schedule editor was built - those remain separate, larger UI
  features tracked as bounded gaps, not resolved here.
- Canonical Diagnostics evidence integration (WP1 part 2 and WP2 of
  `Media-Mix-Lab: Coding LLM Next Steps After PR #286`,
  `application/fold_refit_service.py`,
  `application/diagnostics_service.py`, `pages/06_Diagnostics.py`,
  `DiagnosticsArtefact` schema v8 at the time - now schema v9, see the
  WP2.11 bullet below): real per-fold PyMC re-fits behind
  leakage-safe historical validation, with a deeper point-in-time
  source-reconstruction path (`run_leakage_safe_fold_refit_from_sources`
  - fold-local `prepare_canonical_native_frame`/`assess_official_
  preparation` governed to each fold's own information cutoff, and
  `SourceVersion` upload-timing cross-checks that resolve `cannot_verify`
  rather than silently reusing a too-late revision; no durable
  historical-vintage byte store exists, and none is claimed), feeding one
  shared fold run into both the `historical_validation` and
  `structural_stability` evidence sections - never two divergent fits for
  one fold. The Diagnostics page now routes this action through the
  deeper from-sources path automatically whenever the project has its raw
  source tables and outcome definitions, and otherwise records and labels
  the weaker `coverage_metadata_only` tier explicitly (closed
  `RECONSTRUCTION_TIER_*` vocabulary in the `historical_validation`
  payload, part of the artefact fingerprint; reload restores the weaker
  tier for pre-tier artefacts, never the stronger) - the shallow path is
  never presented as the deep reconstruction. Schema v8 additionally
  renders posterior predictive metric
  distributions (`posterior_predictive_metric_distributions`, computed
  inline, no extra fit), graphical identification
  (`graphical_identification`, always carrying its disclaimer),
  latent-state identification (`latent_state_identification`,
  fail-closed, never a fabricated pass), and the experiment/calibration
  provenance display slots (`experiment_calibration`). The compiler
  blocking-error extensions reserved by `REQ-IDENT-001` Requirement 5 and
  `REQ-LATENT-001` Requirement 3 remain open, as do Candidate A's
  identifying anchor (`MD-021`) and the calibration statistical
  mechanism - all recorded in
  `docs/approved_requirements/` and `docs/decision_log.md`, not silently
  reclassified as implemented.
- Durable Experiment Evidence adoption (Work Package 2 of
  `Media-Mix-Lab: Coding LLM Next Steps After PR #291`,
  `application/experiment_service.py`, `core/persistence.py`,
  `pages/01_Data_Upload.py`, `pages/06_Diagnostics.py`): uploaded
  evidence rows now flow through an explicit analyst-reviewed adoption
  boundary into the governed registry - a row never auto-adopts, missing
  required fields fail closed, the registry is immutable (edits are new
  versions, never mutations), calibrating uses require a fully
  compatible caller-evidenced assessment plus explicit affected
  prior/likelihood identity, and a new use that would create a
  double-counted dependence fails closed without an explicit
  dependence-handling method. The registry persists through the project
  bundle (`config/experiments.json` under
  `EXPERIMENT_REGISTRY_SCHEMA_VERSION`, malformed records/orphaned
  uses/unrecognised future schema versions quarantined on import) and
  now populates the schema-v8 `experiment_calibration` Diagnostics
  section from the real saved registry - per experiment, never averaged,
  with a live staleness note when the registry changed after scorecard
  computation. No calibration mechanism exists or is implied; the
  calibrated-vs-uncalibrated comparison half of the Diagnostics section
  remains empty, and no model-fitting module reads the registry.
- Real UK Model A pre-fit-to-posterior remediation and hierarchy evidence
  (WP2.5-WP2.11, PRs #307-#321; all against the governed
  `window_role=historical_test_common_window`/`use_mode=historical_test_
  non_production` 2023-01-01 to 2025-04-06 candidate, no change to
  historical-test/non-production status): WP2.5 exposed prior-predictive
  component decomposition (`eta_trend`/`eta_season`/`eta_market`/
  `eta_promo`/`eta_controls` as named `pm.Deterministic` terms) and found
  raw controls dominating the linear predictor; WP2.6 produced the
  `control_sigma` sensitivity evidence; WP2.7 approved and implemented
  **`REQ-CONTROL-001`** (`docs/approved_requirements/REQ-CONTROL-001.md`):
  the two named continuous category-demand controls
  (`fh_category_demand_google_trends`, `dna_category_demand_google_trends`)
  must be standardised with coefficient prior `Normal(0, 0.20)`
  (`APPROVED_UK_MODEL_A_PRIOR_CONFIG`, now `scripts/run_uk_production_fit.
  py`'s default) - scoped to this candidate only, not a universal default.
  WP2.8 found neither the "4-chain geometry screen" nor "medium run"
  convergence-ladder stage ever had a governed sampler configuration
  anywhere in the repository; the analyst declined to invent one, keeping
  `REQ-PREFIT-001`'s existing short-screen-then-full-posterior workflow
  authoritative, then ran the real governed full Model A posterior
  (convergence, identification, fit, seasonality). WP2.9 fixed pre-fit
  fingerprints that were binding to `sha256("null")` instead of the real
  candidate/frame, added divergence-localisation/fit/temporal/
  identification/product-level evidence scripts (including PSIS-LOO/WAIC),
  and found `target_accept=0.95` (vs. the governed 0.90) reduces FH
  divergences 70 -> 13 uniformly but only reduces DNA's 53 -> 46
  non-uniformly - a split, not a universal, result - recorded in a
  certification decision package. WP2.10 diagnosed the outcome-level
  hierarchy (`sigma_pool[channel]`) as weakly identified - sitting at its
  `HalfNormal(0.3)` prior mean for nearly every channel, estimated from
  only 2-3 outcome groups each - evaluated single-outcome "Overall"
  robustness-comparator challengers (zero divergences but not
  segment-preserving), and audited CPA/ROI. WP2.11 repaired the fold-refit
  outcome-catalogue propagation defect (real folds were silently using a
  legacy `fh_new`/`fh_dna_cross_sell`/`fh_winback` catalogue instead of the
  candidate's real governed NBT outcomes), added the gated **H2** diagnostic
  hierarchy challenger under **`REQ-HIERARCHY-001`**
  (`docs/approved_requirements/REQ-HIERARCHY-001.md`,
  `prior_config["shared_pooling_scale"]=True`, one scalar
  `sigma_pool_global` replacing per-channel `sigma_pool[channel]`;
  diagnostic-only, not eligible for production-default consideration
  without a further analyst decision), added the Residual Explorer to
  `pages/06_Diagnostics.py`'s "In-sample fit & error metrics" tab (reading
  only the canonical `residual_series`/`shared_residual_evidence` evidence
  - `DiagnosticsArtefact` **schema v9**, `CURRENT_DIAGNOSTICS_SCHEMA_
  VERSION = 9` in `application/diagnostics_service.py`; a pre-v9 artefact's
  `residual_series` section loads as `not_computed`, never fabricated), and
  added a parameterised prepared-frame fold-refit backtest script
  (`scripts/run_uk_wp2_11_prepared_frame_backtest.py`,
  `--prior-config-mode current|h1_complete_pooling|h2_shared_pooling_
  scale`) plus reusable per-fold instrumentation built after that backtest
  ran silent for 6+ hours before a targeted probe found it: `core.
  fold_data_support` (per-fold, per-variable data-support report;
  `ready`/`review_recommended`/`blocked` framework present but never
  self-categorised - every `SupportThresholds` field defaults to `None`),
  `core.fit_progress` (rate-limited, always-flushed sampler progress/
  geometry reporter reading `core.models.fit_model`'s new optional
  `stats_callback`), and `core.source_model_reconciliation` (per-variable
  raw-source-vs-canonical-frame comparison: presence, row count, non-zero
  observations, active date range, downstream disappearance, percentage
  total change - deliberately no invented pass/fail threshold), all wired
  through a new optional `on_progress_line` parameter on
  `application.fold_refit_service` (default `None`, byte-for-byte
  unchanged behaviour for every existing caller). WP2.11 closes with
  `docs/wp2_11_hierarchy_decision_package_20260826.md`: full-posterior
  convergence evidence (current: 13 FH / 46 DNA divergences; H1: 0 FH / 35
  DNA; H2: 98 FH / 369 DNA; Overall robustness comparator: 0/0) shows H1 as
  the more numerically well-behaved segment-preserving challenger and H2 as
  clearly worse on both convergence and its own diagnostic purpose - but
  **no production hierarchy change is made or proposed as approved**, and
  the evidence is explicitly recorded as insufficient for a production
  decision: no out-of-sample fold-refit-backtest evidence exists for any
  candidate (the attempted `RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY` run
  was terminated after fold 1 - the smallest, earliest 72-week expanding
  window - showed several channels with as few as 2 non-zero weeks and
  real-NUTS geometry consistent with a strained posterior), and the current
  UK activity data is, as of 2026-08-26, under separate analyst review for
  suspected source-to-model mapping issues that this package explicitly
  does not treat as evidence for or against any hierarchy candidate. No
  `.mypy-baseline-count` change from this package (still 243, unchanged
  since WP2.11 items 2/6 above raised it 241 -> 243); no
  `docs/approved_requirements/index.json` change from this specific
  package (`REQ-HIERARCHY-001` was already indexed by WP2.11 items 2/6).

## Known bounded gaps

These are implementation or decision boundaries, not permission to invent
business or modelling definitions:

- The mixed-frequency conversion catalogue is deliberately narrow (see above).
  It is not a generic interpolation or imputation layer, and broader
  ragged-window or policy-backed method choices remain bounded gaps.
- Candidate A Search mediation/capacity status must be stated precisely, not
  as a single implemented/unimplemented flag:
  1. Search object governance (REQ-SEARCH-001): implemented.
  2. Candidate A formulation (REQ-SEARCH-002): approved for implementation
     and validation.
  3. Candidate A engine and graph/compiler capability: implemented
     (`core/search_capacity.py`), with synthetic and conditional recovery
     tests.
  4. Production integration boundary (WP1): implemented for the shared/joint
     hierarchical builder only (`build_fh_hierarchical_model(...,
     search_candidate_a=...)`, `application/model_fit_service.py`,
     `pages/05_Model_Training.py`). Market-specific (Model C) Candidate A
     integration is a documented follow-up, not yet available - requesting
     it raises a specific `ModelFitServiceError` rather than silently
     falling back to the ordinary builder.
  4a. Diagnostics evidence (Work Package 3): implemented. Posterior
     extraction (`core.search_capacity.
     extract_candidate_a_search_posterior_summary`) and a canonical
     `DiagnosticsArtefact` section (schema v7, `search_capacity`, rendered
     on a "Candidate A Search" Diagnostics tab) now exist. Two silent-
     correctness gaps were found and closed while building this: the
     Diagnostics page's model-rebuild helper and `core.attribution.
     compute_shapley_contributions`/`core.predict.predict_mu` (and
     therefore every downstream caller: canonical curves, the Scenario
     Planner, the optimiser, backtest) previously either rebuilt the wrong
     model or silently produced a `mu`/`mu_total` missing Candidate A's
     entire search-mediated pathway - both now fail closed with a specific
     exception instead (`ModelFitServiceError`/
     `CandidateAAttributionNotSupportedError`/
     `CandidateAReplayNotSupportedError`). This is the actual mechanism
     that keeps Results, official curves, the Scenario Planner, and
     optimisation correctly unavailable for Candidate A today - not a
     partial or approximate implementation of any of them.
  4b. Results, official curve generation, and Scenario Planner integration:
     **not yet implemented**, and not merely un-extracted - REQ-CURVE-001's
     canonical curve contract structurally excludes the search-mediated
     pathway from `meta.pathway_masks` by the approved graph-compiler
     design (REQ-SEARCH-002), and the NumPy replay (`predict_mu`) has no
     representation for a *counterfactual* Search demand/capture/cap state
     at a hypothetical scenario/curve spend point - a genuine modelling
     design question (see `docs/decision_log.md`, Work Package 3 entry).
     Work Package 7 (2026-08-18) produced a dedicated decision package,
     `docs/wp7_candidate_a_final_outcome_replay_decision_package.md`,
     laying out candidate approaches to the four sub-questions this
     requires (upstream-media input at a hypothetical spend point; the
     paid-search cap's counterfactual specification, since it is a fixed
     historical input with no observed value in a future/planned period;
     extrapolation policy outside the fitted spend/cap range; and
     posterior-uncertainty propagation through the cap's non-linear
     `min(...)` censoring) - none selected. Still not a mechanical
     extension until one is approved.
  5. Full joint posterior-recovery evidence (Work Package 2): a synthetic
     generator and evidence package now exist
     (`core/search_candidate_a_recovery.py`) - an independently-coded
     forward simulator (multiple channels, distinct adstock/saturation,
     direct-only and mediated channels, all three cap-binding regimes,
     multi-market, noisy observations), fast prior-predictive plausibility
     checks, a deterministic identification-sensitivity sweep, and a real
     `pm.sample` posterior-recovery suite against the *integrated*
     production model (`test_search_candidate_a_recovery_posterior.py`,
     `candidate-a-recovery` CI job, schedule/manual-only - real MCMC is too
     slow for blocking CI). This is interval-coverage evidence at a
     versioned, documented threshold (`CANDIDATE_A_RECOVERY_POLICY`,
     `wp2-v1`), not an official-use approval - it supplies one input to
     `core.search_capacity.candidate_a_use_gate`'s required evidence set,
     which still needs prior/posterior predictive validation beyond what
     this package covers, the counterfactual contract, and explicit human
     model approval before official Search fit eligibility exists.
  6. Search planning eligibility: disabled.
  7. Search-cap optimisation: disabled.

  Ragged market-specific predictor mathematics (`FR-MOD-015`) - explicitly
  reserved, not resolved, by `REQ-COVERAGE-001` §6 - now has a dedicated
  decision package, `docs/wp8_ragged_multi_market_predictor_decision_
  package.md` (Work Package 8, 2026-08-18), laying out three candidate
  treatments for a (market, channel) cell with no genuine coverage (a
  masked/marginalised likelihood term; restructuring `X_media`/`market_
  bounds` for genuinely ragged per-market columns; an explicit governed
  zero-fill convention) and a cross-cutting question about whether the
  answer should depend on the cell's recorded missingness reason - none
  selected. `core.market_data_capability.check_engine_capability`
  continues to report an unsupported request exactly as before. Moderated
  pathways and residual-interaction engine support remain decision-bound
  or unsupported, independent of Candidate A.
- The full-core mypy debt ceiling is `.mypy-baseline-count` = 243 (Work
  Package 4 of an earlier round closed the single largest repeated pattern
  - 34 occurrences of a `FHModelMeta.pathway_masks` Optional-narrowing gap
  now fixed via `FHModelMeta.resolved_pathway_masks`; Work Package 5 fixed
  `core.transformations.hill_function`'s parameter typing - `K`/`S` accept
  `Union[float, np.ndarray]`, matching how every multi-channel caller
  already invokes it - retiring 4 further pre-existing errors, taking the
  ceiling to 241; WP2.11 items 2/6 (H2 hierarchy challenger and Residual
  Explorer, PR #318) then raised it 241 -> 243 for its own new code); it is
  a ceiling, not a target - unchanged at 243 through WP2.11's later items.
  CI must fail if the measured count increases.
- The Scenario Planner *page*'s manual tab (`pages/08_Scenario_
  Planner.py`, WP5 part 2 of `...Post PR262`; parts 3-4, 2026-08-18) now
  offers a sequential-weekly method choice alongside the existing
  steady-state monthly approximation, renders terminal carryover and
  (opt-in) posterior uncertainty for it, and can save/export a sequential
  scenario (appended to the same `scenarios` list a steady-state scenario
  is - see Delivered foundation above for what it wires together). A real
  browser-lifecycle (Playwright) test for the sequential path remains not
  yet implemented - only Streamlit `AppTest` coverage exists for it. Both
  optimiser tabs (constrained and unconstrained-benchmark) and `core.
  optimization`'s objective still only offer the steady-state monthly
  approximation - a sequential-weekly method choice is not yet exposed
  there. Work Package 6 (2026-08-18) reconciled this into a formal
  requirement (`REQ-SCEN-004`) and produced a decision package
  (`docs/wp6_sequential_optimisation_decision_package.md`) rather than
  implementing it directly: `core.optimization.optimize_scenario`'s
  SLSQP search finite-differences an analytic, per-month objective
  potentially hundreds to low thousands of times per run, while the
  sequential kernel performs a full week-by-week state-transition
  simulation per call (no partial re-evaluation possible) - calling it
  directly inside that search loop is a materially more expensive
  computational problem, not a mechanical rewiring, and no decision has
  been made about which incremental-outcome quantity (short-horizon,
  long-horizon, or a combination) would even become the optimised
  scalar. Blocked pending review of that package - not a modelling or
  core-engineering gap resolvable by more coding. A real browser-
  lifecycle (Playwright) test for the manual sequential path also
  remains not yet implemented.
- Chronos-2 or another future exogenous forecasting integration is not yet
  implemented. Work Package 9 (2026-08-18) reconciled the broader governed
  future-assumption-bundle gap into a formal requirement (`REQ-FUTURE-001`)
  and produced a decision package (`docs/wp9_future_assumption_bundle_
  decision_package.md`) rather than implementing it directly: the bundle
  schema, the materiality-quantification/grading method (`VL-027`/
  `RP-024`), and whether/how Chronos-2 or another method integrates are
  all genuinely unresolved statistical/governance questions, not a
  mechanical wiring gap - `core.planning.future_context`'s existing per-
  control contract already accepts any caller-supplied future series, so
  no code change is needed merely to plumb a number through; the open
  questions are which bundle identity model, which materiality method,
  and which forecaster (if any) are approved. Blocked pending review of
  that package.
- A time-varying latent baseline (`AGENTS.md` future-variable-role #5) is
  not yet implemented - `core.hierarchical_model`/`core.market_specific_
  model` both define `intercept` as a single static per-market/outcome
  scalar. Work Package 10 (2026-08-18) reconciled this into a formal
  requirement (`REQ-BASELINE-001`) and produced a decision package
  (`docs/wp10_time_varying_baseline_decision_package.md`) rather than
  implementing it directly: this repository's own upstream-reference
  workflow surfaced that `pymc-marketing`'s closest built-in pattern
  (`time_varying_intercept`, a Gaussian Process) is documented by its own
  authors as unsuitable for forecasting beyond a short horizon - directly
  in tension with role #5's "projected... for planning" requirement.
  Whether a new baseline capability is even warranted beyond the existing
  deterministic trend/Fourier continuation, which statistical process
  would generate it, its `REQ-LATENT-001` identification strategy, and its
  forward-projection mechanism (if any) are all genuinely unresolved
  statistical questions, not an implementation gap. Blocked pending review
  of that package.
- Pathway-agnostic capacity/cap semantics (`AGENTS.md`'s "Capacity and
  cap invariants" section) are not yet implemented beyond Candidate A's
  own narrow Search pathway - `core.search_capacity`'s `cap_binding`
  field is a strict two-value boolean, while `AGENTS.md` requires four
  states (capped/uncapped/ambiguous/unavailable), and `REQ-GRAPH-001`'s
  own governed-edge-role table already states `capacity_constrained` is
  "unsupported for every other structure" beyond Candidate A's authorised
  Search shape. Work Package 11 (2026-08-18) reconciled this into a
  formal requirement (`REQ-CAP-001`) and produced a decision package
  (`docs/wp11_capacity_cap_semantics_decision_package.md`) rather than
  implementing it directly: what "ambiguous" and "unavailable"
  concretely mean, whether the contract is generalised into a shared
  module now or deferred until a second capacity-constrained pathway
  exists, and what cap-data governance beyond `core.search_objects`'s
  existing identity/versioning requires are all genuinely unresolved
  statistical/design questions, not a missing runtime guard. Blocked
  pending review of that package.
- Real UK data readiness is an operational step and must be run only by an
  authorised analyst with approved local data outside Git.

## Required implementation discipline

Future substantive work must use the task-specific brief and repository
authority hierarchy, preserve the existing governance and mathematical
contracts, keep model-input units distinct from monetary spend, and record
engine capability boundaries honestly. No real Ancestry data belongs in this
repository, browser fixture, log, screenshot, or generated artefact.
