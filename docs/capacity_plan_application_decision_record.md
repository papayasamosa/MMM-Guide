# Decision record: capacity-limit plan application (generalised wiring, Decision 18)

**Resolves:** the "wiring `CapacityLimitDefinition` into the Scenario
Planner/Optimiser UI (a separate integration pass, `REQ-OPT-001`'s own
scope)" item `REQ-CAP-001`'s 2026-08-30 addendum explicitly named as
still open after the cap-hit vocabulary/module-sharing resolution
(`docs/capacity_cap_semantics_decision_record.md`). Does not reopen S1-S3
or G1-G3, both already resolved by that record.

## Context

`core.capacity` (commit `55a14078`) implements the governed vocabulary
and object shape but nothing in this repository applies a
`CapacityLimitDefinition` to an actual candidate plan. `REQ-OPT-001`
Requirement 4 requires capacity constraints to be "usable together" with
the money/percentage constraint vocabulary "by the same optimisation
run," with the result disclosing "which constraints of either kind were
binding."

## Decisions made

1. **Two entry points, not one**, mirroring the existing split between
   report-only evidence and optimiser-facing bounds: `classify_
   capacity_limit_binding` (report-only, reuses `classify_cap_hit_
   status` unchanged) for Scenario Planner disclosure; `apply_capacity_
   limits_to_bounds` (mutates a scipy bounds list, the same shape `core.
   optimization_constraint_vocabulary.resolve_governed_constraints`
   produces) for the Optimiser. Both read one governed source
   (`CapacityLimitDefinition`) - never two independently diverging
   representations, per Decision 18's own instruction.
2. **`spend_limit` applies directly**; `availability_toggle` forces a
   `(0, 0)` bound when off (a fact, not an analyst choice - disclosed
   distinctly from an ordinary zero-spend constraint, matching `core.
   optimization_constraint_vocabulary`'s identical discipline);
   `fixed_commitment`/`delivery_exposure_limit`/`bounded_range` (all
   non-money-denominated) are applied to spend bounds **only** when the
   caller supplies an explicit `unit_to_spend_rate` for that specific
   limit - never inferred, never a default rate. Absent one, the limit
   is disclosed as advisory-only, never silently dropped.
3. **`bounded_range`'s schema gap**: `CapacityLimitDefinition.value_by_
   period` carries one scalar per period, which cannot represent a
   paired min+max range on its own. This record's own implementation
   choice (disclosed, not a business fact): the scalar is the range's
   upper value; an optional `metadata["min_value_by_period"]` mapping
   (same period-keyed shape) may supply the paired lower value. Absent
   that key, the limit behaves as upper-only - always disclosed
   explicitly in the resulting `CapacityBoundsDisclosure`, never
   silently assumed to also carry a floor. A future decision may instead
   split `bounded_range` into two `CapacityLimitDefinition`s (a spend/
   exposure floor plus a ceiling) if that proves clearer in practice;
   this record does not foreclose that.
4. A limit whose `applies_to` channel is not present in the candidate
   plan's channel list is a documented no-op (not an error) - a capacity
   limit legitimately exists for channels outside any one specific
   plan's scope.

## What this record does not do

- Modify `core.capacity`, `core.optimization`, or `core.optimization_
  constraint_vocabulary` - purely additive.
- Wire this module into `pages/08_Scenario_Planner.py` or `core.
  optimization.optimize_scenario` itself - a future UI/optimiser
  integration pass, consistent with every prior Phase C/E module.
- Invent any unit-to-spend conversion rate - every non-money application
  requires one supplied by the caller.

## Verification

`ancestry_mmm/tests/test_capacity_plan_application.py` (15 tests) - all
passing, including a case proving a non-money limit is never silently
treated as a spend cap absent a supplied rate, and a case proving
`zero_spend`-shaped outcomes (`availability_toggle` off) remain
distinguishable in the disclosure from an ordinary spend constraint.
