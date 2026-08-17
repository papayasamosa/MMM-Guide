# REQ-SCEN-001: Sequential scenario evaluation contract

## Approval and traceability

Depends on `REQ-STATE-001` (the sequential state contract). This record
indexes the candidate/reference evaluation contract already implemented by
`ancestry_mmm/core/sequential_simulation.py` (WP5, PR #260) at the kernel
level, and additionally approves - per this repository's task-specific-brief
authority ("`Media-Mix-Lab: Coding LLM Next Steps Post WP5`", 2026-08-16) -
its extension to application-layer scenario evaluation (`REQ-SCEN-002`
phased plans feeding this same contract), which is not yet built.

## Approved contract (kernel level - implemented)

1. **Same simulator, same non-decision assumptions.** A candidate and a
   reference plan must be evaluated with the same `meta`/posterior
   `params`/starting carry-in state, differing only in the decision being
   varied (the media plan, or an explicitly-varied cost assumption).
   `compute_incremental_outcome` structurally guards market/period/outcome
   identity between the two results only; it cannot see whether the two
   results were actually built from the same model/posterior/historical-
   state/phasing/future-assumption/cost/counterfactual-policy identity.
   `core.sequential_evaluation_context.SequentialEvaluationContext` /
   `require_matching_context` / `compute_incremental_outcome_with_context`
   (Work Package 3) close that gap: a typed, fingerprintable context object
   naming every one of those identities, with a guard that raises
   `MismatchedSequentialEvaluationContextError` unless a caller explicitly
   names which field is allowed to differ (e.g. a deliberately varied cost
   assumption). Prefer `compute_incremental_outcome_with_context` over
   calling `compute_incremental_outcome` directly once candidate/reference
   contexts exist.
2. **Incremental outcome is always `candidate outcome - reference outcome`**
   (`compute_incremental_outcome`, shape `(n_weeks, n_outcomes)`).
3. **Exact-zero no-change invariant.** An identical candidate and reference
   plan must produce a result within numerical tolerance of zero. This is
   release blocking (`test_sequential_simulation.py::
   test_no_change_scenario_invariant_is_zero`) and must remain release
   blocking for every consumer built on top of this contract.
4. **Both production-supported model types.** Model A (shared/joint
   hierarchical) and Model C (market-specific, partially pooled) are both
   supported via the `_market_specific` function variants.
5. **Posterior draw propagation**, in two documented variants (see
   `REQ-STATE-001` item 6 for the full description): conditional on a
   shared, caller-supplied carry-in state
   (`simulate_sequential_outcomes_posterior`,
   `..._market_specific`), or fully draw-consistent, reconstructing
   historical carry-in per draw from that same draw's own parameters
   (`simulate_sequential_outcomes_posterior_draw_consistent`,
   `..._market_specific_draw_consistent`, Work Package 3). Both return the
   complete per-draw array (`shape (n_draws, n_weeks, n_outcomes)`) - never
   aggregated internally. Aggregation (mean/median/credible interval)
   remains the caller's job, performed on the draw axis after the full
   path exists for every draw - never per-component before this array
   exists, and never by simulating only posterior means and calling the
   result posterior uncertainty.

## Approved contract (application level)

The following extend the kernel-level contract above to
application-facing scenario evaluation. Items 6-8 are implemented at the
application-*service* level (Work Package 5 of `...Post PR262`,
`core.sequential_scenario_evaluation.evaluate_manual_scenario_sequential`,
`application.scenario_service.ScenarioService.evaluate_manual_sequential`).
The manual "Sequential weekly" tab on `pages/08_Scenario_Planner.py` (WP5
part 2) is the first Streamlit UI consumer - constrained/unconstrained
optimisation remain steady-state-only (see "Not yet covered" below):

6. **Monthly aggregation only after weekly evaluation.** An application
   presenting a monthly-grain result must sum/aggregate the already-computed
   weekly outcomes - it must never independently apply an annual or
   monthly curve to a coarser grain and call that "sequential." Implemented:
   `SequentialScenarioEvaluationResult.monthly_incremental` is computed by
   grouping already-evaluated `weekly_incremental` rows by month and
   summing, never by an independent monthly calculation.
7. **Steady-state and sequential are distinct, always-labelled methods.**
   An application offering both the existing steady-state monthly
   approximation (`core.optimization`, `core.predict.
   steady_state_outcome_response`) and this sequential contract must never
   allow the method to be ambiguous - each evaluation result must record
   which method produced it. Implemented at the service level:
   `SequentialScenarioEvaluationResult.calculation_method` and
   `.planning_semantics` (always `SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_
   SEMANTICS`, never the steady-state constant) record this unconditionally,
   including in exploratory mode - unlike the steady-state path, which
   only stamps `planning_semantics` in official mode, this contract's own
   method-labelling requirement applies regardless of governance mode.
   Implemented in the UI (WP5 part 2): the "Manual plan evaluation method"
   radio on `pages/08_Scenario_Planner.py` is the single source of truth
   for which method a given rerun uses, never inferred or silently
   switched.
8. **Candidate/reference plans share the same phasing policy** (see
   `REQ-SCEN-002`) unless a difference in phasing itself is an explicit,
   recorded scenario decision. Enforced at the evaluation-service level via
   `core.sequential_evaluation_context.SequentialEvaluationContext`/
   `compute_incremental_outcome_with_context` (Work Package 3): candidate
   and reference are evaluated through the exact same context object,
   structurally guaranteeing identical phasing/future-assumption/cost/
   counterfactual-policy identity unless a field is explicitly named as
   allowed to differ.

## Not yet covered by this record

- The monthly-to-weekly phasing that produces the `WeeklyPlan` inputs to
  this contract in an application context - `REQ-SCEN-002` (phasing itself
  implemented, WP1; wiring it to build the `WeeklyPlan`/`FutureContextResult`
  inputs `evaluate_manual_scenario_sequential` consumes is implemented for
  the manual-plan path by `pages/08_Scenario_Planner.py` (WP5 part 2), and
  by tests - not yet by the optimiser tabs).
- Scenario persistence/staleness for a saved sequential scenario
  (`core.persistence`, `core.scenario_governance`) - not yet implemented;
  `validate_scenario_dependencies`'s `planning_semantics_fingerprint`
  check is engine-aware as of Work Package 5 (recognises both
  `CURRENT_PLANNING_EVALUATION_SEMANTICS` and `SEQUENTIAL_WEEKLY_
  PLANNING_EVALUATION_SEMANTICS` as current), but no save/load path for a
  `SequentialScenarioEvaluationResult` exists yet.
- Optimiser objective wiring for the sequential contract - both the
  constrained and unconstrained-benchmark tabs on
  `pages/08_Scenario_Planner.py` remain steady-state-only; a separate,
  not-yet-approved follow-up work package.
- Terminal incremental carryover and posterior uncertainty in the UI - the
  service/core APIs support both, but the WP5 part 2 manual tab does not
  yet render either (explicitly disclosed in the UI, not silently absent).
- Candidate A final-outcome sequential replay - blocked pending the
  counterfactual-replay decision recorded against `REQ-SEARCH-002`.
  Inherited for free by this record's implementation: calling into
  `core.sequential_simulation`'s functions means `CandidateAReplayNotSupportedError`
  propagates through `evaluate_manual_scenario_sequential` exactly as it
  does through `core.predict.predict_mu`, with no separate gate required.

## Affected modules

- `ancestry_mmm/core/sequential_simulation.py`
  (`compute_incremental_outcome`, `simulate_sequential_outcomes_posterior`
  and its draw-consistent/Model C variants)
- `ancestry_mmm/core/sequential_evaluation_context.py` (Work Package 3)
- `ancestry_mmm/core/sequential_scenario_evaluation.py` (Work Package 5 -
  application-level items 6-8)
- `ancestry_mmm/application/scenario_service.py`
  (`SequentialManualScenarioInput`, `ScenarioService.
  evaluate_manual_sequential`, Work Package 5)
- `ancestry_mmm/core/optimization.py` (`validate_scenario_dependencies`'s
  `planning_semantics_fingerprint` check made engine-aware, Work Package 5)
- `ancestry_mmm/tests/test_sequential_simulation.py`
- `ancestry_mmm/tests/test_sequential_evaluation_context.py` (Work Package 3)
- `ancestry_mmm/tests/test_sequential_scenario_evaluation.py`,
  `ancestry_mmm/tests/test_scenario_service_sequential.py` (Work Package 5)
- `ancestry_mmm/pages/08_Scenario_Planner.py`,
  `ancestry_mmm/tests/test_scenario_planner_apptest.py` (Work Package 5
  part 2 - manual-tab UI wiring)

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Kernel-level contract (items 1-5) approved and implemented.
Application-level contract (items 6-8) implemented at the service level
(Work Package 5) and, for the manual-plan path only, in the Streamlit UI
(Work Package 5 part 2) - see `REQ-SCEN-002`/`REQ-SCEN-003` for the
dependent contracts, and `REPO_REVIEW_AND_NEXT_STEPS.md` ("Known bounded
gaps") for current application-layer status (optimiser wiring, terminal/
posterior UI, persistence).
