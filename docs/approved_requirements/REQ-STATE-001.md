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
6. **Full future recursion per posterior draw**, in two documented
   variants:
   - conditional on one shared, caller-supplied carry-in state
     (`simulate_sequential_outcomes_posterior`,
     `simulate_sequential_outcomes_posterior_market_specific`): every
     sampled posterior draw's own decay/Hill parameters run through the
     complete weekly recursion independently, but historical starting-
     adstock uncertainty is not propagated - only future-recursion
     uncertainty conditional on the shared state is;
   - **fully draw-consistent** (`simulate_sequential_outcomes_posterior_
     draw_consistent`, `simulate_sequential_outcomes_posterior_market_
     specific_draw_consistent`, Work Package 3): for every selected
     posterior draw, that draw's own parameters are used to reconstruct
     `SequentialCarryInState` from the historical frame *and* to run the
     future recursion, so early-horizon output reflects each draw's own
     historical adstock/saturation trajectory. Proven against the batch
     replay per draw (not merely per posterior mean), including a market
     that is not first in the fit's market list, and covered by a
     regression that fails if the evaluator were refactored to reuse one
     fixed carry-in state across draws
     (`ancestry_mmm/tests/test_sequential_simulation.py::
     TestEarlyHorizonUncertaintyRegression`).

   In both variants, aggregation (to a horizon, to monthly, to a summary
   statistic) is left to the caller - the kernel never aggregates first
   and calls the result posterior uncertainty.
7. **State provenance.** `SequentialCarryInState` is a typed, serialisable
   object precisely so a scenario or a report can record *which* starting
   state a given evaluation used, not just its numeric contents.
8. **Model/prediction-math reuse extends to both production-supported
   model types** (shared/Model A and market-specific/Model C) via the
   `_market_specific` function variants, including both posterior-
   evaluator variants in item 6.
9. **Historical-state resolution fails closed on malformed frame metadata**
   (`_resolve_and_validate_market_history`, Work Package 3): a
   `historical_frame` whose `market_bounds` length does not match the
   fit's market count, whose bounds fall outside `X_media`, or whose
   `market_bounds`/`market_idx` disagree about which rows belong to the
   requested market, raises rather than silently reconstructing carry-in
   state from the wrong market's history.

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
- A single shared, typed evaluation context binding model/posterior/
  market/calendar/historical-state/phasing/future-assumption/cost/
  counterfactual-policy identity together and requiring a candidate and
  reference pair be evaluated through the same one - `REQ-SCEN-001`
  (`core.sequential_evaluation_context`, Work Package 3).
- Application-layer integration (`application/scenario_service.py`,
  `pages/08_Scenario_Planner.py`, `core.optimization`'s objective) -
  a documented, not-yet-attempted follow-up (see
  `REPO_REVIEW_AND_NEXT_STEPS.md`, "Known bounded gaps").
- Sequential optimisation.

## Affected modules

- `ancestry_mmm/core/sequential_simulation.py`
- `ancestry_mmm/core/sequential_evaluation_context.py` (Work Package 3)
- `ancestry_mmm/core/transformations.py` (`initial_state` carry-in
  parameter)
- `ancestry_mmm/core/predict.py`, `ancestry_mmm/core/market_specific_predict.py`
  (`precomputed_sat_media` override)
- `ancestry_mmm/tests/test_sequential_simulation.py`
- `ancestry_mmm/tests/test_sequential_evaluation_context.py` (Work Package 3)

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Approved and implemented. State contract implemented and
verified for both production-supported model types, including fully
draw-consistent posterior evaluation and fail-closed historical-state
resolution (Work Package 3); Candidate A mediator state replay implemented
as a bounded diagnostic capability only. Application-layer integration is
a separate, not-yet-approved follow-up.
