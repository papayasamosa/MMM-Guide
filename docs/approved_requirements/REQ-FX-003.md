# REQ-FX-003: Historical Conversion-Method Vocabulary

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`, Section
6 ("Historical conversion policy": daily source spend, weekly source
spend, spend-weighted weekly conversion, weekends/holidays, Finance
override) — reconciled by Work Package 7 of `Media-Mix-Lab Coding LLM
Next Steps 2026-08-27`, under the same 2026-08-22 architecture approval
cited by `REQ-FX-001`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27). Target-state contract only. Mirrors
`REQ-COVERAGE-001`'s own precedent for `core.frequency_conversion`: this
record approves the closed *method vocabulary* and the structural rules
governing how a method may be applied — it does not select which method
is the production default for any variable, market, or purpose. The
conversion-method registry this record anticipates starts genuinely
empty, exactly as `REQ-COVERAGE-001`'s did.

## Capability status

Zero implementation. No FX conversion-method vocabulary, weekly-average
computation, spend-weighting, or business-day fallback logic exists
anywhere in this repository.

## Requirement

### 1. Closed conversion-method vocabulary

A historical FX conversion must be tagged with exactly one method from a
closed, versioned vocabulary: `observed_daily`, `daily_spend_weighted_
weekly_average`, `business_day_weekly_average`, `previous_business_day`,
`finance_budget_rate`, `finance_accounting_rate`, `manual_approved_rate`.
An unrecognised or unapproved method must fail closed, never silently
fall back to a different method.

### 2. Daily source spend, converted per day

Where spend is available daily, each day's spend must be converted at
that day's own rate before being summed into the canonical MMM week —
never assumed uniform within the week by converting a weekly total at a
single rate.

### 3. Weekly source spend, arithmetic weekly average

Where only weekly spend is available, the conversion must use the
arithmetic mean of the published business-day rate observations that
fall within the canonical week, and must retain the observation count and
missing-day status alongside the converted value. This is an explicit
uniform-within-week assumption, not treated as equivalent to a true daily
conversion.

### 4. Spend-weighted weekly conversion where both are available

Where daily spend and daily rates are both available, the preferred
method computes `sum(daily source spend × daily FX rate)` directly,
rather than applying one unweighted weekly-average rate to a weekly
total; the effective weekly rate this implies must remain derivable and
auditable (`weekly converted spend / weekly source spend`).

### 5. Weekends, holidays, and missing observations fail closed

For a transaction-date conversion falling on a non-trading day, the
method must use the latest available previous business-day rate,
labelled explicitly as `previous_business_day`, retaining the actual
source observation date used. For a weekly average, missing business-day
observations must never be interpolated silently; the number of available
observations must be checked against an approved minimum, and a shortfall
must block or warn rather than proceed silently.

### 6. Finance override rates are governed, separate rate sets

A Finance-supplied corporate accounting rate, budget rate, month-end
rate, or hedged contract rate must be stored as its own governed rate set
(`REQ-FX-002`) under its own method tag (`finance_budget_rate`/`finance_
accounting_rate`), and must never overwrite a market-reference rate set.
A caller must be able to select the rate purpose explicitly (historical
marketing analysis, financial reconciliation, budget planning, constant-
currency comparison) rather than one method serving every purpose by
default.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp7_governed_fx_finance_decision_package.md`. In summary, this
record does not approve:

- which method is the production default for weekly-spend conversion
  (the addendum's Section 20 item 5 leaves "daily-spend-weighted, weekly
  average or month-end" as an open Finance question);
- the approved minimum business-day-observation count below which a
  weekly average blocks rather than warns;
- which rate is used for budget planning specifically, or how hedged
  contracts are handled (Section 20 items 6 and 9).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): a future FX-conversion executor
analogous to `core.frequency_conversion.execute_frequency_conversion`,
reusing `REQ-FX-001`/`REQ-FX-002`'s data model.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_003_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (method vocabulary approved; default
method selection and minimum-observation threshold remain Finance-owned).

## Approval date

2026-08-27
