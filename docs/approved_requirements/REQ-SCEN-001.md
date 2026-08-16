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
   identity between the two results; passing consistent `meta`/`params`/
   carry-in to both `simulate_sequential_outcomes` calls is the caller's
   responsibility.
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
5. **Posterior draw propagation.** `simulate_sequential_outcomes_posterior`
   runs every sampled posterior draw through the full weekly recursion
   independently and returns the complete per-draw array
   (`shape (n_draws, n_weeks, n_outcomes)`) - it does not aggregate.
   Aggregation (mean/median/credible interval) is the caller's job,
   performed on the draw axis after the full path exists for every draw -
   never per-component before this array exists, and never by simulating
   only posterior means and calling the result posterior uncertainty.

## Approved contract (application level - not yet built)

The following extend the kernel-level contract above to
application-facing scenario evaluation. They are approved for
implementation, not yet implemented:

6. **Monthly aggregation only after weekly evaluation.** An application
   presenting a monthly-grain result must sum/aggregate the already-computed
   weekly outcomes - it must never independently apply an annual or
   monthly curve to a coarser grain and call that "sequential."
7. **Steady-state and sequential are distinct, always-labelled methods.**
   An application offering both the existing steady-state monthly
   approximation (`core.optimization`, `core.predict.
   steady_state_outcome_response`) and this sequential contract must never
   allow the method to be ambiguous - each evaluation result must record
   which method produced it, and a UI must label both, per
   `REQ-SCEN-002`/`REQ-SCEN-003` and this repository's `docs/decision_log.md`
   entry for WP5.
8. **Candidate/reference plans share the same phasing policy** (see
   `REQ-SCEN-002`) unless a difference in phasing itself is an explicit,
   recorded scenario decision.

## Not yet covered by this record

- The monthly-to-weekly phasing that produces the `WeeklyPlan` inputs to
  this contract in an application context - `REQ-SCEN-002`.
- Response-horizon and terminal-carryover reporting semantics -
  `REQ-SCEN-003`.
- Any specific application/UI (`application/scenario_service.py`,
  `pages/08_Scenario_Planner.py`) or optimiser objective wiring - separate,
  not-yet-approved follow-up work packages.
- Candidate A final-outcome sequential replay - blocked pending the
  counterfactual-replay decision recorded against `REQ-SEARCH-002`.

## Affected modules

- `ancestry_mmm/core/sequential_simulation.py`
  (`compute_incremental_outcome`, `simulate_sequential_outcomes_posterior`)
- `ancestry_mmm/tests/test_sequential_simulation.py`

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Kernel-level contract (items 1-5) approved and implemented.
Application-level contract (items 6-8) approved for implementation by this
record; not yet implemented - see `REQ-SCEN-002`/`REQ-SCEN-003` for the
dependent contracts that must exist first, and `REPO_REVIEW_AND_NEXT_STEPS.md`
("Known bounded gaps") for current application-layer status.
