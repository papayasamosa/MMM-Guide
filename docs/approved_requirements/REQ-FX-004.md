# REQ-FX-004: FX Provider-Adapter Architecture and Ingestion Governance

## PRD source

`Ancestry_MMM_Governed_FX_Translation_Requirements_Addendum.md`, Section
7 ("Source hierarchy"), Section 9 ("API ingestion behaviour"), and
Section 17 ("Security and configuration") — reconciled by Work Package 7
of `Media-Mix-Lab Coding LLM Next Steps 2026-08-27`, under the same
2026-08-22 architecture approval cited by `REQ-FX-001`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-27). Target-state contract only — no specific
provider is selected or integrated by this record. Mirrors
`REQ-SCENGINE-001`'s own precedent of approving an adapter *pattern*
(capability resolution behind a `Protocol` boundary) without selecting or
adopting any concrete adapter.

## Capability status

Zero implementation. No `FXProvider` protocol, no provider adapter, and
no FX ingestion pipeline exists anywhere in this repository.

## Requirement

### 1. Provider-adapter interface, not a hard-coded source

FX rate retrieval must be implemented behind a provider-adapter interface
(`fetch_rates(currencies, start_date, end_date) -> list[FXRateRecord]`),
never a hard-coded call to one specific website or API. The provider must
be configurable per project and per rate purpose.

### 2. Recommended source hierarchy, not a mandated one

A recommended precedence — Finance-approved corporate rate feed first
(when Ancestry supplies one), an official public central-bank source for
analytical backfill and independent validation second, manual approved
upload third when an API cannot supply a required historical pair, and
never a silent fallback to an unapproved consumer converter — is approved
as *guidance for adapter design*, not as a selection of which adapter(s)
are actually built or enabled for this project (see "Explicitly
excluded").

### 3. Governed ingestion pipeline, not render-time calls

FX rates must never be fetched from a live API each time a chart or
report renders. Ingestion must follow an explicit staged flow: retrieve
source observations (on request or scheduled refresh) → validate
currencies, dates, and directions → normalise to canonical records
(`REQ-FX-002`) → calculate required cross-rates → materialise daily and
weekly rate tables → approve or accept the rate-set version → persist an
immutable snapshot → use only that snapshot in models, scenarios, and
reports. API responses must be cached and persisted, never re-fetched
per render.

### 4. Required ingestion controls

Every provider-adapter implementation must apply: a request timeout;
retry with exponential backoff; provider rate-limit handling; response
schema validation; duplicate-date detection; missing-period detection;
impossible-rate checks (e.g. non-positive or absurd-magnitude rates);
deterministic cross-rate tests (`REQ-FX-002` §3); a retrieval timestamp
and source-vintage/revision marker on every ingested record; and a hard
rule that no mutation of an already-approved historical rate set is ever
permitted through ingestion. A provider outage must never change an
existing model or report — an already-approved snapshot remains usable
regardless of current provider availability.

### 5. Credential security

API credentials must be supplied only through environment or secret
management, never persisted inside a project bundle, scenario JSON, log
output, version control, or a Streamlit session export. A persisted
project may contain provider *identity* (which provider was used) and
the retrieved rate *data*, but never provider secrets (API keys, bearer
tokens, account credentials).

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp7_governed_fx_finance_decision_package.md`. In summary, this
record does not approve:

- which provider(s) are actually integrated (the addendum names the
  European Central Bank Data API and Federal Reserve H.10/FRED data as
  "potential official adapters" only — neither is selected here);
- which source is authoritative for management reporting specifically
  (Section 20 item 3);
- whether Finance corporate rates override market-reference rates by
  policy, beyond the structural rule (Requirement 2 above) that they must
  never silently do so through ingestion (Section 20 item 4).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): a future `core.fx_provider` module
defining the `FXProvider` protocol, and a `data.fx_ingestion` pipeline
module once a concrete adapter is approved.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_governed_fx_authority_reconciliation.py::TestGovernedFXOverlayReconciled::test_req_fx_004_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp7_governed_fx_finance_decision_package.md`.

## Owner

Finance / Platform engineering (adapter architecture approved; provider
selection remains Finance-owned).

## Approval date

2026-08-27
