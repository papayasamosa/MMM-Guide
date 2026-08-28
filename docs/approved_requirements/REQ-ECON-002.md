# REQ-ECON-002: Governed FH/DNA Weekly Aggregate Valuation Input Contract

## PRD source

Ancestry MMM PRD Part 1 §7.2 ("versioned outcome-definition registry");
Part 4 §14.3 ("commercial value layers applied to an earlier approved
outcome"); Part 5 §10.4 (`dim_value_definition`) — reconciled together
with the explicit business-decision brief "Outcome valuation and
time-varying ROI: approved business decisions" (2026-08-28), which
resolves items 1-8, 18, and 19 of that brief. This record does not
introduce new PRD content beyond what `docs/wp2_outcome_valuation_gap_
analysis.md` already catalogued; it reconciles the business decisions
that close most of `docs/wp2_outcome_valuation_decision_package.md`'s
D1, D2, D3, D6 (metadata-capture half only), D8 (source-classification
half), and D9.

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
This is the first of three records reconciling the outcome-valuation
architecture (`REQ-ECON-003` covers rate derivation and the posterior
join; `REQ-ECON-004` covers reporting period/aggregation/dimensions).
Target-state architecture contract — governs the **input data contract**
only. It does not itself implement any code (see WP2A in the governing
brief's implementation sequence).

**Explicitly still blocked, not approved by this record:** any FX
conversion policy (rate source, weekly vs. annual constant-dollar
convention, override policy) — see `REQ-FX-001` through `REQ-FX-006`
and `docs/wp7_governed_fx_finance_decision_package.md`, which remain the
sole authority for that question. This record requires only that
currency **identity** be captured and never inferred (Requirement 5) — a
"FX-neutral interface... already authorised," per the business-decision
brief's explicit instruction not to invent FX policy here.

## Capability status

Zero implementation. No `WeeklyOutcomeValue`-style object, no FH-LTR or
DNA-revenue input schema, and no denominator-linkage mechanism exists
anywhere in this repository. `OutcomeDefinition.value_weight`/
`value_currency` (`core/outcomes.py`) remains the only existing
per-outcome value concept, and it is a single constant scalar — this
record's object is additive to it (see `REQ-ECON-001`'s existing
backward-compatibility framing in `docs/wp2_outcome_valuation_gap_
analysis.md` §9), never a replacement.

## Requirement

### 1. Both FH and DNA are governed, distinct economic outcome/value measures in the existing Outcomes domain

Per the business decision: *"FH aggregate projected LTR belongs in the
governed Outcome dataset, alongside the existing FH outcome measures
such as GSAs and net bill-through counts. It should be represented as a
distinct economic outcome/value measure using the existing governed
outcome-data architecture wherever possible rather than creating an
unrelated parallel upload system."* The same principle applies to DNA
revenue by direct analogy (both are aggregate monetary totals valuing an
existing governed outcome). This resolves `docs/wp2_outcome_valuation_
decision_package.md`'s D9 domain-classification question:
`DOMAIN_OUTCOMES` (`REQ-DATAIN-001`) is the governed source domain for
both — no new fifth domain is introduced. FH and DNA valuation records
remain **structurally separate** (never a shared object), mirroring
`REQ-SEARCH-003`'s precedent of keeping FH and DNA identities distinct
even when their upstream shapes are analogous.

The PRD's own `value_rule_id`/`bridge_outcome_relationship` schema
fragment (Part 5 §8.5) remains referenced-but-undefined in the PRD suite
(confirmed by `docs/wp2_outcome_valuation_gap_analysis.md`'s direct
search) and is not populated by this record; this repository's own
governed contract below supersedes reliance on that undefined PRD stub.

### 2. FH weekly aggregate LTR contract

A governed FH valuation record is keyed `market × week × FH segment`,
where FH segment is one of the existing governed FH segments (New,
Winback, Cross-sell — AGENTS.md's "Fit the main Family History segments
separately: New, DNA cross-sell, Winback"), present only where that
segment exists in the current model. The record carries a single
`aggregate_projected_ltr` monetary total for that market/week/segment —
**never** a per-customer figure. Per the business decision: *"The
upstream business process calculates projected customer LTR using an
existing survival-analysis methodology and customer characteristics.
Those customer-level projected values are then summed into the weekly
segment totals supplied to this application. The application must treat
the supplied aggregate LTR as authoritative. It must NOT reproduce,
modify or replace the upstream LTR model."* This repository never
re-derives, back-calculates, or validates the upstream per-customer
projection methodology — the aggregate is accepted as an authoritative,
externally governed input, subject only to this record's own structural
validation (currency, grain, denominator linkage, missingness — below).

### 3. FH denominator linkage requires explicit reconciliation, never a default

Per the business decision: *"Before implementing this calculation,
reconcile the exact governed FH denominator with the existing outcome
contracts. The intended business outcome is the acquisition/bill-through
outcome corresponding to the supplied LTR cohort. Do not arbitrarily
substitute GSA merely because it is available."*

This record therefore requires every FH valuation record to declare an
explicit `denominator_outcome_id`, referencing an existing approved FH
`OutcomeDefinition` whose `metric_key` is in the acquisition/bill-through
class for the same market and segment. **No default denominator is
authorised by this record** — a dependent implementation must not
substitute GSA, sign-up, or NBT as a hard-coded universal default.
Which specific existing outcome_id is appropriate is a per-project
reconciliation exercise (the exact upstream LTR cohort definition varies
by supply), to be performed at implementation/configuration time — not
by this record, and not by inventing an answer. If that reconciliation
finds no existing approved FH outcome genuinely corresponds to the
supplied LTR cohort, implementation must stop and report the conflict
rather than force-fitting an available outcome, per the governing
brief's explicit instruction: *"If implementation reveals a contradiction
with existing approved authority, stop that affected workstream and
report the conflict rather than silently resolving it."*

### 4. DNA weekly aggregate revenue contract

A governed DNA valuation record is keyed `market × week × DNA segment`.
The initial governed segmentation is New versus Existing (`DNA_SEGMENT_
NEW` / `DNA_SEGMENT_EXISTING_FH`, `core/outcomes.py`), used where the
source data supports that split; per the business decision, finer
segmentation (e.g. sell/activate) is explicitly **not** required where
unsupported: *"Do not require finer revenue segmentation such as
sell/activate where the source data cannot support it."* The contract
must remain compatible with the existing governed `segment_dimension`
vocabulary (`SEGMENT_DIMENSIONS`, `core/outcomes.py`) rather than
hard-coding only the two literal New/Existing labels into calculation
logic — a future finer segmentation must be representable without a
schema change. The record carries a single `aggregate_dna_revenue`
monetary total representing "the actual summed revenue generated by
kits sold/ordered in the relevant segment during that week, including
the effect of differing prices, promotions and discounts" (business
decision, verbatim) — never a per-kit figure.

### 5. DNA denominator is kit orders

The governed denominator for DNA revenue is the existing DNA kit-order
outcome for the same market, week, and segment — resolved the same way
as Requirement 3 (an explicit `denominator_outcome_id` reference, never
an assumed or hard-coded identifier), reflecting the business decision's
explicit statement: *"The relevant economic denominator is DNA kit
orders."* Unlike the FH case, this denominator choice is not itself
ambiguous per the business decision (DNA kit orders is stated directly,
not left to reconciliation) — but the mechanism remains an explicit
reference field, not an inferred default, for architectural consistency
with Requirement 3 and to remain robust to a future DNA outcome
restructuring.

### 6. Governed weekly grain, reusing the existing canonical calendar

Both FH and DNA valuation records use the application's existing
canonical modelling week (`core.planning.phasing`/`core.frequency_
alignment`'s `CanonicalCalendar`) — never a second, independently defined
week. Per the business decision: *"Source systems may contain daily
records, but the application's input for this capability will be the
governed weekly aggregate. Use the existing canonical week/date
semantics. Do not introduce a second definition of a week."* A supplied
source at finer-than-weekly grain must be aggregated to the canonical
week before ingestion, not accepted at native grain.

### 7. Mandatory, never-inferred currency metadata

Every FH and DNA valuation record must carry an explicit, governed
currency identifier (reusing the existing ISO-3 currency vocabulary
already validated by `core.planning.value.CurrencyContext`). Per the
business decision: *"Values may be supplied either in local currency or
already translated into another reporting currency such as USD. Every
monetary input must therefore carry sufficient governed currency
metadata to identify its supplied currency. **Never infer currency from
market.**"* This record requires the field and its never-inferred
validation rule; it does **not** approve any conversion between the
supplied currency and any reporting currency — that remains blocked
pending Finance's FX policy decision (see "Approval and traceability"
above and `REQ-FX-001` through `REQ-FX-006`).

### 8. Fail-closed missingness, with an explicit zero/zero carve-out

Per the business decision: *"Missing valuation data must fail closed for
economic reporting. Do not silently forward-fill, interpolate or invent
LTR/revenue."* This record requires the ingestion contract to
distinguish, using the existing `REQ-COVERAGE-001` canonical
missingness-state vocabulary (`observed_zero`, `missing_expected`,
`not_applicable`, `unavailable_source`, `suppressed`, `estimated`,
`modelled`, `unknown`) rather than inventing a parallel vocabulary:

- **a missing valuation record** (no supplied value for a market/week/
  segment that should have one) — must block economic reporting for
  that cell, never silently interpolated or forward-filled;
- **a genuine observed zero outcome count** (the denominator outcome is
  structurally/observationally zero for that week/segment) — must be
  distinguishable from a missing record, using `observed_zero`;
- **a genuine zero monetary value** (the supplied aggregate LTR/revenue
  is itself legitimately zero) — likewise distinguishable, using
  `observed_zero` on the value side.

When the denominator outcome count is genuinely zero **and** the
corresponding modelled incremental outcome is also structurally/
observationally zero for that week/segment, the record must contribute
zero incremental economic value — this is not a division-by-zero error,
per the business decision: *"This should not automatically be treated as
corrupt data."* Any other case that would require dividing by a zero or
missing denominator (e.g. a non-zero incremental outcome with a
zero/missing denominator) must be surfaced as an explicit, attributable
validation failure — never guessed, defaulted, or silently suppressed.
User-facing coverage diagnostics disclosing this distinction are
required (deferred to the WP2A/WP2D implementation, not created by this
record).

### 9. Versioned, provenanced source data with existing staleness propagation

Per the business decision: *"Historical economic values normally remain
stable but may change if the upstream LTR methodology is revised and
historical periods are recomputed... Treat valuation inputs as governed/
versioned source data. Do not silently mutate historical model results
when a replacement file is uploaded. Existing model/results must retain
provenance to the valuation source version used. A new historical
valuation version may make existing economic outputs stale and require
recomputation/rerun according to existing project staleness rules."*
This record requires: an immutable version-history lineage per
market/week/segment record (mirroring `REQ-SEARCH-001`'s `new_search_
object_version` pattern — an edit is always a new version, never an
in-place mutation); a `source_version` field bound into the existing
single fingerprint/staleness mechanism (`REQ-STALE-001`), so a replaced
valuation file stales every dependent fit/curve/scenario/report through
the existing path, never a second invalidation mechanism; and retention
of which source version produced any already-computed economic output,
so historical results remain auditable against the version that
generated them.

### 10. Ownership captured as provenance, not hard-coded

Per the business decision: *"Finance is the business owner/stakeholder
for the economic values, with the underlying numbers produced/provided
through Analytics. Capture provenance using existing source/dictionary
governance rather than hard-coding organisational ownership into model
calculations."* This record requires the existing `source`/`owner`-style
provenance fields (mirroring `ActivityDefinition.source`/`MediaInputSpec.
source`) to record who supplied a valuation record; no calculation logic
anywhere may branch on organisational ownership.

## Out of scope (decision-required, not approved by this record)

- Which specific existing FH `outcome_id` is the correct
  acquisition/bill-through denominator for a given project's supplied
  LTR cohort (Requirement 3) — a per-project reconciliation task, not a
  universal default this record can supply.
- Any FX conversion policy — remains entirely blocked pending
  `docs/wp7_governed_fx_finance_decision_package.md` and Finance
  approval; this record authorises only currency **identification**
  metadata (Requirement 7).
- The rate-derivation formula (aggregate value / denominator count) and
  its join to posterior incremental outcomes — see `REQ-ECON-003`.
- Reporting-period aggregation, comparison, and dimension eligibility —
  see `REQ-ECON-004`.
- Any waterfall/decomposition method — remains gated behind a required
  calculation/design note per the governing business-decision brief,
  before any code or further authority record.

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (WP2A, not created by this record): `ancestry_mmm/core/outcomes.py`
or a new sibling module (e.g. `core/outcome_valuation.py`);
`ancestry_mmm/core/coverage.py` (missingness-state reuse);
`ancestry_mmm/core/persistence.py` (versioning/staleness);
`ancestry_mmm/core/fingerprint.py`; `ancestry_mmm/pages/01_Data_Upload.py`
(supply/review workflow, not built by this record).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_002_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_002_never_defaults_fh_denominator`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

The specific FH denominator outcome_id (Requirement 3, resolved at
implementation/configuration time per project, not by this record), and
all FX conversion policy (blocked, Finance-owned) — see
`docs/wp2_outcome_valuation_decision_package.md`.

## Owner

Finance (business ownership of the economic values) / Analytics
(production of the underlying numbers) / Modelling / Platform
engineering (architecture reconciliation).

## Approval date

2026-08-28
