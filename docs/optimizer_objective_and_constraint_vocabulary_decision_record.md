# Decision record: optimiser objective-kind and constraint-kind vocabulary implementation

**Resolves:** the Phase E implementation-architecture questions
`REQ-OPT-001` explicitly defers ("Phase E implementation work, not a
business decision"), per the user's 2026-08-29/30 authorisation to
proceed with research-based technical resolution on Decision 16/18's
already-approved business requirements. Does **not** reopen any business
question `REQ-OPT-001`, `REQ-SCEN-004`, or `docs/wp6_sequential_
optimisation_decision_package.md` reserved.

## Context

`REQ-OPT-001` approves a closed objective-kind vocabulary (`maximise_
outcome`, `maximise_revenue`, `maximise_profit`, `maximise_roi`,
`minimise_cpa`) and an extended constraint-kind vocabulary, but leaves
open:

1. How each objective kind's economic-input precondition is actually
   checked (Decision 16: "do not offer an objective if the required
   economic inputs are missing").
2. Whether the five new constraint kinds are implemented as a new
   `SpendConstraint` variant or a parallel structure.

## Options considered - objective-kind gating

- **Modify `core.optimization.resolve_planning_objective`/`_objective_
  weight` directly** to add the five kinds. Rejected: these are large,
  governance-critical, heavily tested functions (`_objective_weight`
  alone documents nine confirmed historical defects it exists to
  prevent regressing). Adding new branches here carries meaningfully
  higher regression risk for zero necessary reason, and every prior
  Phase C/E item in this project (capacity, named-event response,
  baseline, tractability, future-assumption bundle) chose the same
  additive-and-standalone path for the same reason.
- **A new, additive gating module that calls the real, unmodified
  `resolve_planning_objective`** (chosen). `maximise_outcome` and
  `maximise_revenue` are validated by literally invoking the production
  function and turning any `ValueError` into a structured result -
  the two can never silently diverge. `maximise_revenue` is not a new,
  separately-invented value definition: `expected_value`'s existing
  precondition (a value weight + shared currency for every target
  outcome) already *is* the "valid, governed value definition for every
  included outcome" Decision 16 requires, since `OutcomeDefinition.
  value_weight` already represents governed FH-LTR/DNA-kit revenue
  (confirmed against `core.planning.value.ScenarioValueAssumptions`'s
  own documented semantics).
- **`maximise_profit`**: a repository-wide grep for `profit|margin|cogs`
  (case-insensitive) across `ancestry_mmm/core` found zero hits of a
  governed profit/margin/COGS definition. There is no valid economic
  input to compute profit from today. Unconditionally blocking this
  kind, with the reason disclosed verbatim, is the only honest
  implementation - inventing a proxy (e.g. treating revenue as profit)
  would violate Decision 16's own "never silently substituted with a
  proxy value" instruction.
- **`maximise_roi`/`minimise_cpa`**: gated on every considered channel
  being cost-bearing, reusing `core.activities.ActivityDefinition.
  is_cost_bearing` (`economic_treatment in {"paid_media_cost",
  "fully_loaded_cost", "campaign_cost"}`) rather than inferring paid/
  non-paid status from a channel name - consistent with `REQ-
  ACTIVITY-001`'s "never inferred from names" principle and Decision 7's
  existing SEO/no-spend-ROI prohibition. When no activity taxonomy is
  supplied, these objectives are blocked (cost-bearing status cannot be
  verified) rather than assumed paid-by-default.

Implementation: `ancestry_mmm/core/optimization_objective_vocabulary.py`.

## Options considered - constraint-kind schema

- **New `SpendConstraint` variant fields** (e.g. adding `min_value`/
  `max_value`/`absolute_delta` directly to the existing dataclass and
  new `elif` branches in `build_bounds_and_constraints`). Rejected for
  the same regression-risk reason as above: `build_bounds_and_
  constraints` is exercised by the optimiser's full existing test suite,
  and REQ-OPT-001 itself explicitly declines to decide this, naming it
  Phase E implementation work.
- **A parallel `GovernedSpendConstraint` structure** (chosen): a new,
  closed ten-kind vocabulary (`no_constraint`, `fixed_absolute_spend`,
  `minimum_spend`, `maximum_spend`, `spend_range`, `percentage_change_
  from_reference`, `absolute_change_from_reference`, `zero_spend`,
  `required_minimum_activity`, `unavailable`). Kinds with a direct,
  exact existing equivalent (`fixed_absolute_spend`, `minimum_spend`,
  `percentage_change_from_reference`, `zero_spend`) translate into real
  `core.optimization.SpendConstraint` instances and are resolved by the
  unmodified, already-tested `build_bounds_and_constraints`. Kinds with
  no existing equivalent (`maximum_spend`, `spend_range`, `absolute_
  change_from_reference`, `unavailable`) are applied as a direct
  bounds-tightening pass on that function's own output shape (the same
  `List[Tuple[float, float]]` scipy bounds list), so a caller can use
  every kind in one optimisation run without `core.optimization.py`
  changing at all.
- **`required_minimum_activity`** (Decision 16's own text: "distinct
  from a spend floor - a non-monetary activity minimum") is never
  silently treated as a money bound. It is applied only when the caller
  supplies an explicit `unit_to_spend_rate`; absent that, it is
  disclosed as advisory-only. No unit-to-spend conversion rate is
  invented by this module.
- **`zero_spend` vs `unavailable`**: both numerically collapse to a
  forced `(0, 0)` bound (scipy bounds have no third value), but the
  governed disclosure output keeps them fully distinguishable audit
  facts throughout - the same "collapse the number, never the
  disclosure" pattern `core.capacity`'s cap-hit vocabulary already
  established for the identical problem (a supplied cap of zero vs. no
  cap value at all).
- **Requirement 5 (infeasibility)**: `resolve_governed_constraints`
  reports any cell where the resolved lower bound exceeds the upper
  bound in `infeasible_cells`, rather than silently clamping or
  dropping a constraint.

Implementation: `ancestry_mmm/core/optimization_constraint_vocabulary.py`.

## What this record does not do

- Rewire `core.optimization.optimize_scenario`'s SLSQP call sites to
  actually use these vocabularies in a production run, or wire the
  sequential-weekly kernel (`REQ-SCEN-004`'s own "still not resolved"
  item) - a separate, substantial engineering integration requiring its
  own end-to-end validation, consistent with every prior Phase C/E
  module in this project.
- Invent any numeric default (a percentage-change bound, an activity
  floor, a unit-to-spend rate) - none exists in either new module.
- Decide the combination/weighting rule when constraints of different
  kinds disagree beyond bounds-tightening (min/max are simply taken;
  no weighting is needed for bounds, only for a scalar objective, which
  this record does not touch).

## Verification

`ancestry_mmm/tests/test_optimization_objective_vocabulary.py` (13
tests) and `ancestry_mmm/tests/test_optimization_constraint_vocabulary.py`
(22 tests) - all passing. Every existing `test_optimization.py` test
(the module both new modules delegate to) re-verified unchanged and
passing.
