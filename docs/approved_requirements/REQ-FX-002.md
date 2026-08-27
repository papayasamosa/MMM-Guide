# REQ-FX-002: FX-Rate Record and Immutable FX-Rate-Set Governance

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`, Sections
4-5 ("FX-rate record", "FX-rate set") and Section 8 ("ECB cross-rate
calculation") — reconciled by Work Package 7 of `Media-Mix-Lab Coding LLM
Next Steps 2026-08-27`, under the same 2026-08-22 architecture approval
cited by `REQ-FX-001`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27). Target-state contract only — no rate provider,
no rate set, and no cross-rate derivation path is selected by this
record. Depends on `REQ-FX-001`'s currency-concept vocabulary (a rate
record's `source_currency`/`target_currency` are instances of that
vocabulary).

## Capability status

Zero implementation. No `FXRateRecord`, `FXRateSet`, immutable-rate-set
versioning, or cross-rate derivation exists anywhere in this repository.

## Requirement

### 1. FX-rate record shape and direction convention

A single FX-rate observation must record: a stable `rate_id`; the rate
date; `source_currency`/`target_currency`; the rate itself, with a fixed,
unambiguous direction convention (`target amount = source amount × rate`
— never inferred from a provider's own display label, which varies by
source); the rate's frequency (`daily`/`weekly`/`monthly`); the rate
*method* from the closed vocabulary `REQ-FX-003` governs; provider
identity and the provider's own series/observation identifiers;
retrieval timestamp and source vintage; and, where the rate is a derived
cross-rate, an explicit `is_derived_cross_rate` flag plus its
`derivation_path`.

### 2. Rate sets are versioned and immutable once used

Historical calculations must depend on a versioned, immutable `FXRateSet`
— identity (`rate_set_id`, `name`, `provider`, `base_or_reference_
currency`), coverage (`start_date`/`end_date`), provenance (`retrieved_
at`, `rate_policy`), a `records_fingerprint` over its constituent rate
records, and approval metadata (`approval_status`, `approved_by`,
`approved_at`). Once a model or official scenario uses a rate set, later
API calls or refreshes must never mutate that set in place — a refreshed
or revised download creates a new version and a new fingerprint,
following the same "immutable identity, new version on change" pattern
`core.coverage.SourceVersion` already establishes for source data.

### 3. Cross-rate derivation must be explicit and tested

Where a provider publishes rates only against one reference currency
(e.g. the ECB's EUR-denominated series), a derived cross-rate between two
non-reference currencies must be computed via the reference currency
(`B per A = (B per EUR) / (A per EUR)`), recorded with
`is_derived_cross_rate=true` and an explicit `derivation_path` tuple
naming every currency hop, and verified by deterministic direction/
round-trip identity tests — never silently assumed correct from a
provider's raw response shape.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp7_governed_fx_finance_decision_package.md`. In summary, this
record does not approve:

- which provider(s) supply FX rates for any purpose (Finance-approved
  corporate feed, official public central-bank source, or manual upload —
  the addendum's Section 7 source hierarchy is a recommendation, not a
  selection; see `REQ-FX-004` for the adapter architecture this record
  depends on but does not itself select a provider for);
- which specific rate set is authoritative for any given purpose
  (historical marketing analysis, financial reconciliation, budget
  planning, or constant-currency comparison).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): a future `core.fx` module holding
`FXRateRecord`/`FXRateSet` alongside `REQ-FX-001`'s `MonetaryObservation`.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_002_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (architecture approved; provider and
rate-set selection remain Finance-owned).

## Approval date

2026-08-27
