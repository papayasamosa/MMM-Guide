# REQ-FX-006: FX Reporting, Currency-Labelled Economics, and Year-on-Year Translation Decomposition

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`, Section
13 ("Reporting"), Section 14 ("Year-on-year decomposition"), and Section
15 ("Persistence and staleness") — reconciled by Work Package 7 of
`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`, under the same
2026-08-22 architecture approval cited by `REQ-FX-001`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27). Target-state contract only. Extends
`AGENTS.md`'s existing "Mathematical rules" (outcome-scale, posterior-
aggregated business response) with an FX-specific reporting and
decomposition contract; does not restate or weaken those existing rules.

## Capability status

Zero implementation. No local/USD/constant-currency reporting toggle, no
currency-labelled CPA/ROI, and no FX component in year-on-year
decomposition exists anywhere in this repository. `core.canonical_curves`
already carries ISO local/reporting currency and dated FX governance for
curve economics (per `REPO_REVIEW_AND_NEXT_STEPS.md`'s "Completed
foundation" record of the G2A.2 delivery), which this record extends to
reporting and year-on-year views rather than replaces.

## Requirement

### 1. Every monetary report supports four currency views

A monetary report must be able to render: the original transaction
currency; the market reporting currency; the USD/group reporting
currency; and a constant-currency comparison. The currency selector must
never recalculate from a live API — it must read only the scenario or
model's persisted FX snapshot (`REQ-FX-002`'s immutable rate set).

### 2. CPA/ROI labels always carry their currency

Every CPA/ROI figure must display its currency explicitly (e.g. "Average
CPA (GBP)", "Marginal ROI (USD)"). An unqualified currency symbol must
never be shown when more than one currency is present in the same
report context.

### 3. Year-on-year decomposition separates operational performance from translation

Year-on-year reporting must support three distinct views, each answering
a different question, never conflated into one number: a **local-
currency view** (each period's own local spend/values — did marketing
become more or less efficient for the market team?); a **reported-USD
view** (each period's historical translation rate — what did Ancestry
report in USD each period?); and a **constant-currency USD view**
(both periods recalculated using one approved reference-rate set,
normally the comparison period or budget rate — what would the change
have been without exchange-rate movement?).

### 4. FX is one explicit, separately attributed decomposition component

A year-on-year CPA/ROI decomposition must carry FX translation as its
own explicit component, distinct from and never merged into media-price
inflation, alongside the other already-governed components (underlying
response/effectiveness, spend/saturation, channel/product/segment mix,
timing/carryover, promotions/price, capacity, external conditions, and
definition change).

### 5. Persisted FX dependency and staleness triggers

A model, curve, scenario, and report must persist its FX dependency
identity: historical FX-rate-set ID and fingerprint, market/group/model
reporting currencies, future FX assumption ID and fingerprint (where
applicable), and the conversion policy applied. Staleness must follow: a
changed historical rate set stales the prepared data, model, curve,
scenario, and report; a changed future FX assumption stales scenario and
recommendation economics; a changed reporting-currency *selection* alone
is a presentation change only, never a staleness trigger; and a changed
conversion policy stales every dependent calculation.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp7_governed_fx_finance_decision_package.md`. In summary, this
record does not approve:

- which reference-rate set is used for the constant-currency view by
  default (prior-year, current-year, or budget rate — Section 20 item 7);
- rounding/display precision for any reported currency figure (Section
  20 item 8).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): `core.report`, `core.
reporting_rollups`, and `core.canonical_curves`'s existing currency
governance, extended for the local/USD/constant-currency toggle and the
year-on-year FX decomposition component.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_006_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (reporting contract approved;
constant-currency reference-rate default and display precision remain
Finance-owned).

## Approval date

2026-08-27
