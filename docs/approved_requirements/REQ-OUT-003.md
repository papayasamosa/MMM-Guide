# REQ-OUT-003: Family History Lifetime-Value Horizon and DNA Cross-Sell Window

## PRD source

Business-decision brief "Post-UI/UX Implementation Instructions: Approved
Business Decisions" (decision date 2026-08-29), Decision 1 ("Family
History outcome definitions").

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Target-state governance record only: it records two previously-undecided
numeric facts as approved governed values, and reaffirms an already-
implemented invariant. It does not itself implement the valuation
calculation that will consume the 48-month figure (Phase B, "48-month FH
valuation" per the brief's §7 implementation order) or the segment-
derivation logic that will consume the 120-day figure where derivation is
genuinely needed.

Depends on `REQ-OUT-001` (distinct, non-aliased outcome definitions) and
`REQ-NBT-001`/`REQ-NBT-002` (GSA/Net Bill Through separation), which this
record extends rather than replaces.

## Capability status before this record

Repository-wide search (code, tests, docs, fixtures) found **zero**
existing reference to a Family History LTR horizon of either 36 or 48
months, and **zero** existing reference to a 120-day (or any other)
DNA-cross-sell qualifying window. Both are first concrete numbers, not
corrections of a previously-wrong one — there was no prior "36-month"
assumption to correct in this repository.

## Requirement

### 1. Family History lifetime-value horizon: 48 months

The approved Family History lifetime revenue/value horizon is **48
months (4 years)** from the outcome's date basis (bill-through date for
GSA; original signup date for Net Bill Through, per `REQ-NBT-002`).
Any future FH lifetime-value/LTR calculation, label, or governed input
(including `core.outcome_valuation`'s weekly aggregate valuation record
under `REQ-ECON-002`, and `core.planning.value.ScenarioValueAssumptions`
under `REQ-ECON-003` Requirement 5) must use this horizon and must not
silently default to any other duration.

### 2. DNA cross-sell segment window: 120 days

A Family History subscription qualifies for the **DNA Cross-sell**
segment when the person purchased a DNA kit and took the FH subscription
within **120 days** of the DNA kit purchase. This is a governed business
rule, not a statistical estimate. Where the source system already
supplies the approved segment classification (New / Winback / DNA
Cross-sell), that supplied classification is authoritative and this
window must not be independently re-derived or overridden. Independent
derivation of the 120-day window from raw kit-purchase and subscription-
signup dates is only appropriate where the application genuinely needs
to derive the segment and the required source date fields are available
and governed — it must never be invented from partial or ambiguous
source data, and must fail closed (leave the segment unclassified/
blocked) rather than guess when the required dates are missing or
ambiguous.

### 3. No fourth segment

The three approved Family History segments remain exactly **New**,
**Winback**, and **DNA Cross-sell** (already governed vocabulary per
existing segment definitions). This record does not introduce, and no
future implementation may introduce, a fourth segment.

### 4. GSA and Net Bill Through remain both fittable, never aliased (reaffirmation)

This record reaffirms, and does not relax, `REQ-OUT-001`'s existing
prohibition on aliasing between distinct outcomes: GSA and Net Bill
Through must both remain available as explicit, selectable, non-aliased
outcome types for a Family History fit, per the business-decision
brief's Decision 1 ("GSA must remain available as an alternative
outcome" alongside Net Bill Through as "the preferred/main KPI at
present"). Net Bill Through being the currently preferred KPI (per
`REQ-NBT-002`) is a business preference about which outcome is fitted by
default for the current programme, not a technical constraint that GSA
is unavailable or aliased.

### 5. Selected outcome must be visible and consistently propagated

Per the brief's Decision 1 implementation requirements, the outcome
actually fitted (GSA or Net Bill Through) must be visible and consistent
across model setup, saved model metadata, results, scenario planning,
optimisation, exports, and audit records wherever relevant. This
repository's existing outcome-identity/fingerprint/approval architecture
(`REQ-OUT-001`, `REQ-OUT-002`, `core.outcomes.OutcomeDefinition`,
`core.outcome_approval`) already carries outcome identity through these
surfaces structurally; this record does not change that architecture,
but confirms it is the correct mechanism to satisfy this requirement —
no separate, parallel "selected outcome" flag should be invented.

### 6. Value/ROI calculation must be blocked, not guessed, on an LTR/outcome mismatch

If the 48-month LTR data cannot be safely matched to the fitted outcome
(for example, an LTR figure computed on a different outcome definition,
segment set, or date basis than the one actually fitted), the value/ROI
calculation must fail closed rather than substitute a guessed or
mismatched figure. `REQ-ECON-002`'s existing explicit, non-defaulted
denominator-linkage contract and `core.planning.value.
ScenarioValueAssumptions`'s existing eligible-outcome-id restriction
(WP2G) already implement exactly this fail-closed pattern for FH LTR
inputs; this record confirms both must be read as covering the 48-month
figure this record approves, once Phase B wires it in.

## Out of scope (not approved by this record)

- The actual valuation calculation code that consumes the 48-month
  figure (Phase B).
- Any source-system field mapping or derivation code for the 120-day DNA
  cross-sell window (Phase B, only if genuinely needed).
- Any change to which outcome (GSA or Net Bill Through) is the default
  for the current UK historical test — `REQ-NBT-002`'s existing scope is
  unchanged.

## Affected modules

None yet in this record — governance/documentation only. Anticipated
future affected modules (Phase B, not created by this record):
`ancestry_mmm/core/outcome_valuation.py`, `ancestry_mmm/core/planning/
value.py`, `ancestry_mmm/core/net_billthrough.py`, FH segment-derivation
code (if and when genuinely needed).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_req_out_003_stale_assumptions.py::test_no_36_month_fh_ltr_reference_in_active_code_or_docs`
- `ancestry_mmm/tests/test_req_out_003_stale_assumptions.py::test_no_fourth_fh_segment_defined`
- `ancestry_mmm/tests/test_req_out_003_stale_assumptions.py::test_gsa_and_net_bill_through_remain_distinct_metric_keys`
- `ancestry_mmm/tests/test_req_out_003_stale_assumptions.py::test_req_out_003_indexed_and_classified`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

None specific to this record's own scope (both numeric facts are
supplied directly by the business-decision brief, not left open). Phase
B's implementation of the valuation calculation and any genuinely-needed
segment-derivation code remain separately-scoped future work.

## Owner

Product / Analytics (business rule), Modelling / Platform engineering
(future implementation)

## Approval date

2026-08-30
