# REQ-FX-005: Future FX Assumptions, Model Treatment, and Scenario/Optimisation Translation

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`, Section
10 ("Historical and future FX are different objects"), Section 11
("Model treatment"), and Section 12 ("Scenario and optimisation
treatment") — reconciled by Work Package 7 of `Media-Mix-Lab Coding LLM
Next Steps 2026-08-27`, under the same 2026-08-22 architecture approval
cited by `REQ-FX-001`. Extends the already-approved `REQ-FUTURE-001`
(governed future-assumption bundles) to the FX-specific case; does not
duplicate or supersede it.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27). Target-state contract only — no future-rate
method default, and no specific cross-market resource identity, is
selected by this record. Depends on `REQ-FX-001`/`REQ-FX-002`'s data
model and on `REQ-FUTURE-001`'s general future-assumption-bundle
contract, which this record specialises for FX rather than replaces.

## Capability status

Zero implementation. No `FutureFXAssumption` contract, no typed
cross-market currency resource, and no FX-aware scenario/optimisation
translation exists anywhere in this repository. `core.optimization`'s
existing budget/constraint machinery has no currency-typed resource
concept today.

## Requirement

### 1. Future FX rates are assumptions, never a silently substituted live rate

A future/planning exchange rate is a governed assumption object, never
the current live spot rate substituted automatically for an official
scenario. A `FutureFXAssumption` must record: identity (`assumption_id`,
`scenario_id`), the currency pair and date range it applies to, a method
from a closed vocabulary (`finance_budget_rate`, `latest_observed`,
`trailing_average`, `manual_fixed`, `forward_curve`), the rate value,
optional source-rate-set/lookback-window provenance, and approval
metadata. The UI must display the chosen future FX assumption alongside
any scenario result it affects.

### 2. Model treatment: cost translation is never response transformation

For every channel, cost translation (transaction spend → local reporting
spend → USD/group reporting spend → model-currency spend) must remain
structurally separate from response transformation (delivery quantity →
fitted model input). Rules: use a governed delivery quantity as the
fitted response input where it is the better causal exposure measure;
use spend in the explicit model currency only when spend itself is the
fitted input; never pool raw multi-currency values as though they share
a unit (restates `REQ-FX-001` §5 in the model-treatment context); never
treat an FX conversion as media-cost inflation — the two must remain
separately attributable; and retain the FX-rate-set fingerprint in the
prepared model data and model-run identity, so that changing the model
FX-rate set makes the prepared data, fit, curves, and downstream official
artefacts stale (staleness mechanics per `REQ-FX-002`/`REQ-FX-006`).

### 3. Within-market planning translation

A user may enter and constrain a plan in the market reporting currency.
The planner must translate it into the model or group currency using the
selected future FX assumption, and must display both the local-currency
plan value and its consolidated equivalent alongside the specific FX
assumption used (currency pair, name/vintage of the assumption) — never
only the converted figure with the assumption left implicit.

### 4. Cross-market optimisation requires a typed currency resource

A cross-market budget must never sum mixed local currencies directly. A
typed resource construct must express the group-currency total (e.g. a
resource identified by its unit as `"currency"` and an explicit
`currency` field), with every local decision variable carrying an
explicit FX translation into that resource before the optimiser runs.
Local contractual constraints (e.g. a market-specific committed-spend
minimum) may remain expressed in local currency alongside the
group-currency total. The optimiser must validate every conversion before
solving, never silently coercing mismatched currencies.

### 5. Scenario persistence

Every scenario carrying a monetary value must retain: local monetary
inputs; group/USD-equivalent values; the FX assumption or historical
rate-set identifier used; the FX-rate-set fingerprint; the rate method;
the source; and the conversion-date policy applied. A changed FX
assumption or rate set makes the scenario's economics stale (mirrors
`REQ-FX-002` §2's immutable-rate-set staleness trigger).

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp7_governed_fx_finance_decision_package.md`. In summary, this
record does not approve:

- which future-FX method is the production default for any market or
  purpose;
- the specific typed-resource identifier(s)/naming convention used in
  `core.optimization` for a cross-market currency-typed resource;
- any concrete future-rate value, forward curve, or budget-rate source.

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): `core.planning.future_context`
(future FX assumption alongside other future-control assumptions),
`core.optimization` (typed currency resource and cross-market validation).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_005_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (architecture approved; default future-FX
method and resource-naming convention remain Finance/engineering-owned
respectively).

## Approval date

2026-08-27
