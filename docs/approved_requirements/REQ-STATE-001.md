# REQ-STATE-001: Sequential (weekly, state-transition) simulation state contract

## Approval and traceability

This record indexes engine capability that already exists and is tested:
`ancestry_mmm/core/sequential_simulation.py`, delivered as Work Package 5 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #253` and merged as PR #260
(`ef4744f1d587f061e8859cb26e24740325335de2`). Per this repository's standard
authority hierarchy ("1. the task-specific implementation brief"), that
brief was sufficient approval authority for WP0-WP5; this record now gives
the resulting state contract a permanent, indexed `REQ-*` identity so future
work (starting with monthly-to-weekly phasing and application integration)
has a stable requirement to cite, rather than an implementation brief that
will eventually be superseded by later work packages.

This record is retrospective: it does not authorise new behaviour. It
documents, as approved repository authority, the state contract the kernel
already implements and that `test_sequential_simulation.py`'s
golden-equivalence suite already proves.

## Approved contract

The sequential kernel sits **alongside**, and never replaces, the existing
steady-state monthly planner (`core.optimization`,
`core.predict.steady_state_outcome_response`). For a canonical model week
and a market:

1. **Starting state is reconstructed from real historical media**, never
   assumed zero and never assumed steady-state
   (`reconstruct_starting_state`, `reconstruct_starting_state_market_specific`).
   `SequentialCarryInState` carries this state (`to_adstock_state`,
   `to_dict`/`from_dict` for persistence) forward into the weekly recursion.
2. **No cross-market carryover.** Each market's carry-in state is
   reconstructed and simulated independently; the kernel has no mechanism
   for one market's adstock state to influence another's.
3. **An explicit weekly-plan input contract** (`WeeklyPlan`, validated in
   `__post_init__`) is the only way media enters the simulation for the
   plan window - the kernel never infers a weekly plan from a coarser
   (e.g. monthly) decision itself; that translation is a separate,
   dependent contract (`REQ-SCEN-002`). `zero_media_extension_plan`
   constructs a no-further-media reference plan for terminal-carryover
   evaluation.
4. **Existing math is reused, not reimplemented.**
   `core.transformations.geometric_adstock`/`geometric_adstock_matrix`
   gained a backward-compatible `initial_state` carry-in parameter;
   `core.predict.predict_mu`/`core.market_specific_predict.
   predict_mu_market_specific` gained a `precomputed_sat_media` override so
   every non-adstock eta term (baseline/market/trend/season/promo/controls,
   direct/cross-product pathway masking) is delegated to the same,
   already-tested code path used by the batch (steady-state-window) replay.
5. **Ending state and terminal continuation are structurally separate
   results**, never folded into the formal plan-window outcome:
   `simulate_sequential_outcomes`/`simulate_sequential_outcomes_market_specific`
   return `SequentialSimulationResult` for the plan window;
   `simulate_terminal_carryover`/`simulate_terminal_carryover_market_specific`
   evaluate the ending state's continuation under a zero-further-media
   reference plan, as a separate call.
6. **Full future recursion per posterior draw, conditional on one shared
   carry-in state.** `simulate_sequential_outcomes_posterior` runs every
   sampled posterior draw's own decay/Hill parameters through the complete
   weekly recursion independently; aggregation (to a horizon, to monthly,
   to a summary statistic) is left to the caller - the kernel never
   aggregates first and calls the result posterior uncertainty. This is
   *not* yet a fully draw-consistent posterior path: `carry_in` is one
   fixed `SequentialCarryInState` passed once and reused for every draw,
   so historical starting-adstock uncertainty (which itself depends on
   each draw's own decay/Hill parameters) is not propagated into the
   beginning of the future horizon - only future-recursion uncertainty
   conditional on that shared state is. See "Not yet covered by this
   record".
7. **State provenance.** `SequentialCarryInState` is a typed, serialisable
   object precisely so a scenario or a report can record *which* starting
   state a given evaluation used, not just its numeric contents.
8. **Model/prediction-math reuse extends to both production-supported
   model types** (shared/Model A and market-specific/Model C) via the
   `_market_specific` function variants.

## Candidate A boundary

`simulate_candidate_a_mediator_state_sequentially` provides a bounded,
explicitly diagnostic-only replay of Candidate A's demand/capture/cap
mediator state (`CandidateASequentialMediatorState`) - never the final
outcome. This does not create Search planning eligibility; Search planning
and cap optimisation remain governed separately (`REQ-SEARCH-002`) and
disabled. `predict_mu` still fails closed with a specific exception for a
Candidate A fit's outcome-level replay, exactly as it does in the ordinary
(non-sequential) path.

## Verification

`ancestry_mmm/tests/test_sequential_simulation.py`'s golden-equivalence
suite proves: splitting one continuous media series into a historical
prefix and a future plan, the sequential kernel's output over the future
suffix is bit-identical (`rtol=1e-10`) to `predict_mu`'s existing batch
replay over the whole series - covering adstock carry-in, Hill saturation,
the DNA cross-product/halo lag, and direct/halo reconciliation
simultaneously against already-shipped math. The exact-zero no-change
invariant (an unchanged candidate plan against its own reference produces
exact-zero incremental outcome) is covered by `REQ-SCEN-001`, which governs
the candidate/reference evaluation contract built on top of this state
contract.

## Not yet covered by this record

- How a monthly business plan is translated into a `WeeklyPlan` -
  `REQ-SCEN-002`.
- Draw-consistent reconstruction of historical carry-in state: a
  high-level evaluator that, per selected posterior draw, extracts that
  draw's own parameters, reconstructs `SequentialCarryInState` with those
  same parameters, and only then evaluates the future plan - so
  early-horizon output reflects each draw's own historical adstock/
  saturation trajectory, not one state shared across all draws. Not yet
  implemented; the existing fixed-carry-in `simulate_sequential_outcomes_
  posterior` remains available as a documented, explicitly conditional
  helper.
- A market-specific (Model C) equivalent of `simulate_sequential_outcomes_
  posterior`. Model C has full deterministic sequential replay
  (`simulate_sequential_outcomes_market_specific`,
  `reconstruct_starting_state_market_specific`), but no high-level
  draw-level posterior-array wrapper yet - only the shared/Model A path
  has one today.
- Application-layer integration (`application/scenario_service.py`,
  `pages/08_Scenario_Planner.py`, `core.optimization`'s objective) -
  a documented, not-yet-attempted follow-up (see
  `REPO_REVIEW_AND_NEXT_STEPS.md`, "Known bounded gaps").
- Sequential optimisation.

## Affected modules

- `ancestry_mmm/core/sequential_simulation.py`
- `ancestry_mmm/core/transformations.py` (`initial_state` carry-in
  parameter)
- `ancestry_mmm/core/predict.py`, `ancestry_mmm/core/market_specific_predict.py`
  (`precomputed_sat_media` override)
- `ancestry_mmm/tests/test_sequential_simulation.py`

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Approved and implemented. State contract implemented and
verified for both production-supported model types; Candidate A mediator
state replay implemented as a bounded diagnostic capability only.
Application-layer integration is a separate, not-yet-approved follow-up.
