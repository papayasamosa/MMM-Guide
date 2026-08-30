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

## Addendum, 2026-08-30: Finance constant-dollar annual method approved as the DEFAULT (resolves part of `docs/wp7_governed_fx_finance_decision_package.md` items 1 and 6)

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 13) approves the following, at
the contract level only — no actual rate values are invented, and this
addendum does not implement any conversion code:

**New closed-vocabulary method: `finance_constant_dollar_annual`.** This
record's §1 method vocabulary gains an eighth value,
`finance_constant_dollar_annual`, distinct from the existing `finance_
budget_rate`/`finance_accounting_rate` tags (which remain reserved for
`docs/wp7_governed_fx_finance_decision_package.md` items 5 and 7's still-
open budget-planning/reconciliation questions). A rate tagged `finance_
constant_dollar_annual` must reference an `REQ-FX-002` rate record with
`frequency = "annual"` (this record's 2026-08-30 addendum) and applies
uniformly to every week within its financial year — it is not a
weekly/daily conversion method in the sense of this record's §§2-4 and
carries no observation-count/business-day-fallback logic (§5 does not
apply to it).

**`finance_constant_dollar_annual` is the approved DEFAULT governed FX
method for MMM outputs.** This resolves `docs/wp7_governed_fx_finance_
decision_package.md` item 6 ("default historical conversion method for
weekly spend") in a direction that package's own listed options did not
anticipate — not spend-weighted, arithmetic-average, or month-end, but a
single Finance-approved rate held constant across an entire financial
year, chosen specifically so MMM outputs stay consistent with Finance's
own constant-dollar reporting. This also resolves package item 1 (is USD
the group reporting currency?) — the business-decision brief's own
examples (GBP→USD, AUD→USD, "other local currencies → USD") confirm USD
as the target currency for this default method; `REQ-FX-001`'s group-
currency field should be set to USD when this default method is used,
though `REQ-FX-001` §1 itself is not amended by this addendum (a market
could still report in a non-USD currency for a purpose that does not use
this default method).

**Optional market-rate/API mode stays secondary and must never silently
mix with Finance-mode results.** Per Decision 13's own text, a
time-varying (preferably weekly) market-rate/API mode may be built as an
alternative, explicitly selectable method — it does not replace
`finance_constant_dollar_annual` as the default, and a single output must
never combine Finance constant-dollar figures and market-API figures
without an explicit, governed conversion path between them (this
reinforces, and does not relax, this record's existing §1 "unrecognised
or unapproved method must fail closed, never silently fall back"
invariant).

**The selected FX method must always be visible in relevant outputs**,
per `REQ-FX-006`'s existing reporting contract — this addendum does not
change that record, only confirms `finance_constant_dollar_annual` is
now one of the methods `REQ-FX-006` must be able to label. The same
policy must be shared by historical outcome valuation, multi-market
reporting, Scenario Planner, and Optimiser, per `REQ-FX-005`'s existing
future-assumption/scenario-translation contract — again confirmed, not
amended, by this addendum.

**Still genuinely open** (unaffected by this addendum): `docs/wp7_
governed_fx_finance_decision_package.md` items 2, 3, 4, 5, 7, 8, 9, 10,
11, and 12 — including, notably, item 7 (which specific method governs
*budget-planning* future assumptions — this addendum's new method is the
default for MMM *historical/reporting* consistency with Finance, not
necessarily the same choice for forward budget planning, which remains a
separate, still-open Finance decision) and item 8 (constant-currency
basis for year-on-year decomposition — this addendum's annual method is
a candidate input to that decomposition but does not itself select
prior-year/current-year/budget-rate as the constant-currency basis). The
actual Finance rate table remains external and Finance-supplied; this
addendum invents no rate value.
