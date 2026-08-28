# REQ-ECON-003: Historical Valuation Rate-Derivation, Posterior Join, and Forward-Assumption Contract

## PRD source

Ancestry MMM PRD Part 4 §14.3 ("commercial value layers applied to an
earlier approved outcome"); Part 5 §12.4 ("platform-reported... must not
be represented as the MMM incremental outcome") — reconciled together
with the explicit business-decision brief "Outcome valuation and
time-varying ROI: approved business decisions" (2026-08-28), which
resolves items 1, 4, 9, 12, and 17 of that brief.

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Depends on `REQ-ECON-001` (the CPA/ROI arithmetic and value-join
principle this record's outputs feed) and `REQ-ECON-002` (the governed
weekly input records this record's rate derivation consumes). Target-
state architecture contract for the **calculation engine** — governs
WP2B (historical rate derivation), WP2C (posterior join and uncertainty),
and WP2G (forward/scenario assumption join) of the governing brief's
implementation sequence. Zero implementation.

## Requirement

### 1. Weekly segment-level rate derivation

For a historical week and segment, the value-per-outcome rate is
derived as:

```text
value_per_unit(market, week, segment) =
    aggregate_value(market, week, segment) / denominator_count(market, week, segment)
```

where `aggregate_value` is the governed FH LTR or DNA revenue total
(`REQ-ECON-002`) and `denominator_count` is the corresponding governed
outcome count (the reconciled FH acquisition/bill-through outcome, or
DNA kit orders). This rate is a **derived, not supplied**, quantity — it
is never itself uploaded or hand-entered for historical data.

### 2. Zero-denominator and missingness semantics

Per `REQ-ECON-002` Requirement 8's fail-closed missingness contract:

- If `denominator_count` is genuinely zero (an `observed_zero`
  denominator) and the corresponding modelled incremental outcome for
  that week/segment is also structurally/observationally zero, the
  derived incremental economic value for that week/segment is zero — not
  computed via division, and not an error.
- If `aggregate_value` or `denominator_count` is missing (not merely
  zero), the rate is undefined for that week/segment and any dependent
  economic figure covering it must be blocked/flagged, never
  interpolated or defaulted.
- Any case where a non-zero incremental outcome coincides with a zero or
  missing denominator must fail closed with a specific, attributable
  validation error — never silently suppressed, defaulted to a prior
  week's rate, or approximated.

### 3. Draw-level join, weekly grain first

For every posterior draw and every week, the incremental economic value
is:

```text
incremental_value(draw, week, segment) =
    incremental_outcome_count(draw, week, segment) * value_per_unit(week, segment)
```

computed **before** any temporal aggregation. Per the business decision:
*"Economic calculations must happen at the lowest valid weekly grain
before temporal aggregation... Never calculate historical quarterly/
yearly economic value by multiplying total incremental outcomes by a
simple average LTR/revenue rate."* A reporting-period total is
`Σ_week incremental_value(draw, week, segment)` over the weeks in scope
— never `total_incremental_outcome(draw, segment) *
average_rate(segment)`. This is the same draw-level-then-aggregate
discipline `REQ-ECON-001` Requirement 6 and AGENTS.md's "Posterior draws
must be aggregated before posterior summaries" already require; this
record confirms it applies identically along the additional weekly-rate
dimension.

### 4. Supplied values are fixed inputs; only posterior uncertainty propagates

Per the business decision: *"Supplied historical LTR and DNA revenue are
fixed business inputs. They do not contain uncertainty distributions. Do
not manufacture uncertainty around those supplied values. MMM posterior
uncertainty must, however, propagate through economic calculations. For
every posterior draw: incremental outcome draw × fixed weekly economic
rate."* This resolves `docs/wp2_outcome_valuation_gap_analysis.md` §5 in
favour of the "fixed-value treatment" candidate (D8 in `docs/wp2_
outcome_valuation_decision_package.md`): `value_per_unit(week, segment)`
is a single scalar per week/segment, identical across every posterior
draw for that week — only `incremental_outcome_count(draw, week,
segment)` varies by draw. The resulting `incremental_value` and ROI
distributions must be summarised using the existing governed posterior
interval convention (`core.uncertainty.summarize_distribution`'s central
credible-interval convention), never a newly invented standard-deviation-
based interval.

### 5. Forward/scenario valuation requires an explicit assumption, never extrapolation

Per the business decision: *"Do NOT extrapolate historical economic
values automatically. Scenario Planner must require an explicit future
economic-value assumption when ROI/value outputs are requested."* This
resolves `docs/wp2_outcome_valuation_decision_package.md`'s D4
(future-value extrapolation) in favour of candidate D4-A (no
extrapolation; explicit assumption required for every planned week/
segment). For Family History, the assumption is an LTR value per
relevant FH outcome, "preferably by segment," restricted to whichever
subscription/GSA/bill-through relationship the existing governed outcome
contracts make valid for the project (never an ad hoc relationship
invented for planning). For DNA, the assumption is an average revenue
per kit, either segment-specific or one overall value applied across
eligible segments — both representations must be supported, not just
one.

This extends the existing `ManualScenarioInput.ltv`/`OutcomeValueMapping`
scalar mechanism (`core/planning/value.py`) rather than replacing it:
a forward assumption is functionally the degenerate (project-supplied,
analyst-declared) case of the same `value_per_unit` concept
Requirement 1 derives from historical data, applied through the
identical join in Requirement 3. Forward assumptions must be:

- explicit and analyst-supplied — never a carried-forward historical
  rate, and never silently defaulted;
- clearly and separately labelled from observed historical economic
  data in every UI/report surface that shows both;
- persisted as part of the scenario definition itself (not a session-only
  value), so that re-loading a saved scenario reproduces the same
  economic result — mirroring `REQ-SCEN-001`'s existing reproducibility
  contract for other scenario inputs.

### 6. No component-level economics without an approved allocation

Consistent with `REQ-CURVE-001`'s and `REQ-ECON-001`'s existing "channel-
total economics remain authoritative" rule: this record's rate
derivation and join operate at the outcome/segment level; producing a
component-level (e.g. per-channel) economic figure still requires an
explicit, approved cost/value allocation exactly as `REQ-CURVE-001`
already requires — this record does not relax that existing rule.

## Out of scope (decision-required, not approved by this record)

- The exact FH denominator outcome_id (`REQ-ECON-002` Requirement 3).
- Any FX conversion applied to `aggregate_value` before or after rate
  derivation — remains entirely blocked pending Finance's FX policy
  decision.
- Reporting-period aggregation of the resulting weekly `incremental_
  value` series into month/quarter/year/custom views, and any period
  comparison — see `REQ-ECON-004`.
- Any waterfall/decomposition method.

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (WP2B/WP2C/WP2G, not created by this record):
`ancestry_mmm/core/canonical_curves.py`, `ancestry_mmm/core/attribution.py`,
`ancestry_mmm/core/optimization.py` (extending the existing scalar
`value_per_response`/`ltv` lookups to the week-indexed rate from
Requirement 1); `ancestry_mmm/core/uncertainty.py` (reuse, not
extension, of `summarize_distribution`); `ancestry_mmm/core/planning/value.py`
(forward-assumption schema extension); `ancestry_mmm/application/scenario_service.py`;
`ancestry_mmm/pages/08_Scenario_Planner.py`.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_003_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_003_requires_weekly_grain_before_aggregation`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_003_fixes_value_uncertainty_treatment`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

The exact FH denominator outcome_id, and all FX conversion policy — see
`docs/wp2_outcome_valuation_decision_package.md`.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-28
