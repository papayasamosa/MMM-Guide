# REQ-PLANACT-001: Planned Marketing Activity and Promotion-Period Future Inputs

## PRD source

Business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (decision date 2026-08-29), Decision 14
("Future planning should require only assumptions the user actually
controls") - specifically its own text: "The analyst *should* continue
to supply: planned marketing activity, promotion periods, and explicit
governed overrides." Reconciled into `REQ-FUTURE-001`'s 2026-08-30
addendum as an approved principle, but not, until this record, given its
own requirement/implementation - a genuine gap this session's
investigation confirmed (see `docs/planned_activity_and_promotion_
inputs_decision_record.md`).

## Approval and traceability

Approved for implementation by the business-decision brief cited above,
via `REQ-FUTURE-001`'s already-approved addendum. This record and its
implementation are new (2026-08-31), created under the same "read
business decision text, confirm no reservation, write REQ + decision
record + implement + test" discipline used throughout Phases A-E of this
project. Depends on `REQ-SCEN-002` (`core.planning.future_context`'s
existing per-control explicit-future contract, which this record's
`materialize_promo_future` feeds into unchanged).

## Capability status

Implemented (2026-08-31): `ancestry_mmm/core/planning/planned_
activity.py`. `PromotionPeriod` (start/end week, per-outcome intensity)
plus `materialize_promo_future` deterministically expand one or more
declared promotion periods into the exact `promo_future` mapping shape
`core.planning.future_context.build_future_context` already requires -
verified by a real end-to-end test calling the actual, unmodified
`build_future_context`, not a parallel unused contract. `PlannedActivity`
is a lightweight, disclosure-only record of a scheduled campaign's timing
and label; it introduces no new regressor - a planned activity's actual
effect on a plan remains carried entirely by the existing spend-by-week
plan (`REQ-ACTIVITY-001`), which already satisfies Decision 14's
"planned marketing activity" half. `PlannedActivityAndPromotionInputs` is
a governed, versioned, fingerprint-bearing bundle of both record types.

Not yet implemented: any `pages/08_Scenario_Planner.py` UI wiring letting
an analyst enter a `PromotionPeriod`/`PlannedActivity` directly (a future
integration pass); any coupling with `core.planning.future_assumption_
bundle.FutureAssumptionBundle` (left completely unchanged by this
record, consistent with that module's own separately-resolved
architecture).

## Requirement

### 1. Promotion periods are a structured, dated future input

An analyst must be able to declare a promotion as a start week, an end
week, a per-outcome intensity, and a label/description - never required
to hand-construct a per-week value array for every week in a plan
window merely to express one contiguous promotion.

### 2. Promotion periods materialise deterministically into the existing contract

A declared set of promotion periods must expand, deterministically and
without any new statistical mechanism, into `core.planning.future_
context.build_future_context`'s existing `promo_future` shape
(`{outcome_id: {week_label: value}}`) - every `(outcome_id, week)` not
covered by any promotion defaults to `0.0`, never a hold-last-observed
relaxation (`REQ-SCEN-002`'s existing rule for promotions is inherited
unchanged).

### 3. Overlap is disclosed, never silently combined without a stated rule

Where two or more declared promotion periods cover the same outcome and
week, the combination rule actually used (sum, max, or an explicit
rejection) must be an explicit, named parameter - never an unstated
default a caller cannot discover.

### 4. Planned activity remains disclosure-only

A `PlannedActivity` record names a scheduled future campaign's timing
and label for audit purposes only. It must never be read as, or
converted into, a new regressor, causal pathway, or fitted mechanism -
its declared timing is informational, and any actual effect on a plan
continues to come entirely from the plan's own spend-by-week values.

## Explicitly excluded (decision-required, not approved by this record)

- Any specific overlap-combination rule as approved business policy -
  `"sum"` is offered as this record's own disclosed implementation
  default, not asserted as the one correct interpretation.
- Any Scenario Planner UI wiring for entering these inputs directly.
- Any coupling with `core.planning.future_assumption_bundle` - a
  separate, already-resolved architecture this record does not reopen.

## Affected modules

- `ancestry_mmm/core/planning/planned_activity.py` (new -
  `PromotionPeriod`, `PlannedActivity`, `PlannedActivityAndPromotionInputs`,
  `materialize_promo_future`)
- `ancestry_mmm/core/planning/future_context.py` (read-only reference -
  `build_future_context`'s existing `promo_future` contract, not itself
  modified)
- `docs/planned_activity_and_promotion_inputs_decision_record.md` (new)
- `docs/approved_requirements/REQ-PLANACT-001.md` (this record)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_planned_activity.py` (15 tests: `PromotionPeriod`/
  `PlannedActivity` validation and round-trip, bundle duplicate-id
  rejection and fingerprint stability, `materialize_promo_future`'s
  range-filling/overlap-policy behaviour, and a real end-to-end call
  into the unmodified `build_future_context`)
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record - `core.planning.future_context` and `core.
planning.future_assumption_bundle` are both completely unchanged.

## Unresolved decisions

- Whether `"sum"` should become approved overlap policy, or a different
  rule is preferred - not a blocking question (a caller may already
  select `"max"`/`"reject_overlap"` explicitly).
- Scenario Planner UI wiring - future integration work.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-31
