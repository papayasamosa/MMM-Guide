# REQ-FX-001: Currency-Concept Separation and Canonical Monetary Record

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md` (a
separate, non-numbered document in the local PRD traceability set;
carries no Part number or Cross-Document Coherent version of its own —
`docs/specification_authority.md`), Sections 1-3 ("Requirement",
"Currency concepts", "Canonical monetary record") — reconciled by Work
Package 7 of `Media-Mix-Lab Coding LLM Next Steps 2026-08-27`. The
addendum's own header states `**Status:** Proposed requirements and
technical design`; the *architecture* it describes was separately
approved as the normative product/architecture contract for FX semantics
by the analyst decision response of 2026-08-22
(`docs/specification_authority.md`'s "Current PRD source authority"
section), while every Finance-owned operational choice named in the
addendum's own Section 20 remains explicitly deferred — see "Explicitly
excluded" below.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27), reconciling the 2026-08-22 analyst approval of
the FX addendum's architecture. Target-state contract only — no currency
list, no default group/model currency, and no rounding/precision policy
is selected by this record.

## Capability status

Zero implementation. No `MonetaryObservation`-shaped record, no
transaction/market/group/model currency field separation, and no
governed currency-concept vocabulary exists anywhere in this repository.
`core.media_costs`/`core.market_config` currently carry cost mappings
without this explicit four-currency separation.

## Requirement

### 1. Four distinct currency concepts, never one ambiguous field

Every cost-bearing observation must be able to express four distinct
currency roles, each independently named and never conflated:

- **transaction currency** — the currency the source system, platform,
  agency, or invoice actually records the spend in;
- **market reporting currency** — the currency normally used by
  stakeholders in that market (a market may still contain transactions in
  more than one transaction currency, so this must remain a separate
  field, not inferred from the market);
- **group reporting currency** — the currency used for consolidated
  Ancestry reporting, a project-level governed setting, never a
  hard-coded literal;
- **model currency** — the explicit, versioned currency used when a
  monetary amount is passed into a model or cross-market optimisation,
  which may differ from group reporting currency and must stay distinct
  from a non-monetary fitted response input (impressions, GRPs, clicks,
  sends, or another delivery measure) where that delivery quantity is
  itself the response input.

### 2. Original amount is never overwritten

`transaction_amount`/`transaction_currency` must never be replaced or
mutated by a downstream conversion. Every conversion adds a new,
separately named field; none removes or rewrites the source value.

### 3. Canonical monetary record shape

A canonical monetary record must retain, per cost-bearing observation:
identity (`observation_id`, `market`, `channel`, `activity_id`,
`period_start`/`period_end`); the original transaction amount and
currency; the market-reporting, group-reporting, and model-currency
amounts (each nullable until conversion has run); the specific FX-rate
identifier used for each of those three conversions
(`market_fx_rate_id`/`group_fx_rate_id`/`model_fx_rate_id` — see
`REQ-FX-002` for the rate-record/rate-set contract those identifiers
resolve against); and source provenance (`source_system`,
`source_record_id`).

### 4. Decimal precision for persisted monetary calculation

Persisted monetary calculations must use exact decimal arithmetic, not
binary floating point. A float conversion may occur only at the
numerical-model boundary (where the modelling engine itself requires
it), never for the persisted canonical record.

### 5. Model-currency pooling boundary

Where spend itself (not a delivery quantity) is the fitted response
input across more than one market, it must be translated to one governed
model currency before partial pooling or shared-curve estimation — raw
amounts in different transaction currencies must never be pooled as
though they shared a unit.

## Explicitly excluded (decision-required, not approved by this record)

See the new decision package `docs/wp7_governed_fx_finance_decision_
package.md`, Section 20 of the addendum in full. In summary, this record
does not approve:

- whether `USD` is definitely the Ancestry group reporting currency;
- what `CSD` means in any referenced document, or that it is a typo;
- the specific market-to-reporting-currency mapping (the addendum's own
  GBP/EUR/CAD/AUD/USD table is stated as a "suggested initial mapping,
  subject to approval");
- rounding precision for any persisted monetary calculation;
- the initial set of currencies/markets in scope.

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): a future `core.fx`/`core.
monetary_record` module analogous in spirit to `core.coverage`'s
`SourceVersion`/`VariableCoverageRecord` identity pattern, and
`core.media_costs`/`core.market_config` integration points once a
governed currency mapping exists.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_001_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (architecture approved; currency/market
scope and rounding policy remain Finance-owned).

## Approval date

2026-08-27



## Addendum, 2026-08-30 (Phase D): architecture implemented (Decision 13 build-out)

Per the user's explicit 2026-08-30 authorisation (see wp7's updated
text), `ancestry_mmm/core/fx_currency.py` now implements this record's
`MonetaryObservation` canonical monetary record: the four distinct
currency roles, the original transaction amount/currency never
overwritten, Python `Decimal` for persisted amounts (Requirement 4),
and the three FX-rate-identifier fields resolving against
`REQ-FX-002`. Full detail in
`docs/governed_fx_contract_implementation_decision_record.md`. No
currency list, default group/model currency, or rounding policy is
invented - every item under "Explicitly excluded" above remains
exactly as open as before this addendum, and Finance ownership of those
items is unchanged.
