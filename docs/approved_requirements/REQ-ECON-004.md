# REQ-ECON-004: Historical Economic Reporting Period, Aggregation, Comparison, and Dimension Contract

## PRD source

Ancestry MMM PRD Part 5 §31.1 (`dim_comparison_period`); Part 9 §8.2,
§10.1 (headline context and reportable dimensions) — reconciled together
with the explicit business-decision brief "Outcome valuation and
time-varying ROI: approved business decisions" (2026-08-28), which
resolves items 13, 14, and 15 of that brief, and confirms item 16's
scope (see "Explicitly not covered" below).

## Approval and traceability

Approved for implementation by the business-decision brief cited above.
Depends on `REQ-ECON-003` (the weekly `incremental_value`/ROI series this
record aggregates and compares). Target-state architecture contract for
WP2D (historical Results UI) and WP2E (explicit period comparison) of
the governing brief's implementation sequence. Zero implementation.

## Requirement

### 1. Supported reporting-period grains

Historical ROI/economic reporting must support: monthly, quarterly,
yearly, and total selected date range. This resolves `docs/wp2_outcome_
valuation_decision_package.md`'s D10 (standard reporting periods): the
approved period set is exactly these four, plus arbitrary custom ranges
via "total selected date range where useful" — not a closed enum of
named fiscal periods only.

### 2. Calendar-year, standard calendar-quarter convention

Per the business decision: *"Ancestry uses calendar years and standard
calendar quarters: Q1 Jan-Mar, Q2 Apr-Jun, Q3 Jul-Sep, Q4 Oct-Dec."* No
fiscal-year offset or non-standard quarter boundary may be introduced
without a separate approved decision.

### 3. Partial periods use actual included weeks — never scaled or annualised

Per the business decision: *"Partial selected periods must use the
actual included weeks. Do not annualise or scale partial periods to full
periods."* This resolves `docs/wp2_outcome_valuation_decision_package.md`'s
D6 (aggregation weighting) in favour of a variant of candidate D6-B:
whole-week bucketing by the week's governed canonical-calendar
membership, with **no day-overlap fractional splitting and no scaling
correction** — a week belongs to exactly the period its canonical week
falls in, and a period containing fewer weeks than a full month/quarter/
year simply reports the sum over those actual weeks, never an
extrapolated or annualised full-period estimate. This is a narrower,
simpler rule than `REQ-SCEN-002`'s `calendar_day_overlap_v1` day-overlap
convention (which remains approved and unchanged for its own,
forward-planning phasing purpose) — this record does not reuse
day-overlap for historical reporting aggregation, since the business
decision explicitly forecloses scaling/annualising partial periods.

### 4. Aggregation happens after weekly valuation, never before

Consistent with `REQ-ECON-003` Requirement 3: a monthly, quarterly,
yearly, or custom-range economic figure is the sum of already-computed
weekly `incremental_value(draw, week, segment)` rows for the weeks in
scope, aggregated per draw before any posterior summarisation. This
record's aggregation step never recomputes a rate from period-level
totals.

### 5. Explicit, user-selected period comparison

Per the business decision: *"Results must ultimately support explicit
user-selected period comparisons... The user should be able to select
the periods being compared rather than being restricted to an
automatically chosen previous period."* This resolves the ambiguity
`docs/wp2_outcome_valuation_gap_analysis.md` flagged around the PRD's
existing `dim_comparison_period` (Part 5 §31.1), which supports only two
fixed, pre-configured comparison periods: the governed contract must
instead let the user choose **any** two eligible periods of a comparable
grain (e.g. Q1 2025 vs. Q1 2026, or 2025 vs. 2026), not a single
system-chosen prior period. A comparison must expose, where each measure
is valid for the periods and scope selected: the underlying outcome
count, incremental contribution/value, spend, and ROI — never fewer
fields than needed to make the comparison interpretable on its own.

### 6. Reporting-dimension hierarchy, gated by existing attribution support

Per the business decision: *"Target economic reporting hierarchy is:
Total → Product → Segment → Funnel layer → Channel. Activity-level ROI
is not required. Only expose a level where existing governed attribution
genuinely supports allocation at that level. Do not manufacture segment,
funnel or channel economics by dividing totals using arbitrary
allocation rules."* This governs both the historical Results UI (WP2D)
and any future comparison view (WP2E): a level in this hierarchy is
exposed only when an existing, already-approved attribution/allocation
mechanism supports it for the outcome and scope in question (e.g.
`REQ-CURVE-001`'s channel-total-authoritative rule, or an approved
`ComponentCostAllocation`) — never a newly invented pro-rata split
introduced merely to populate a reporting cell. Where the required
allocation does not exist, the report must state that the level is
unavailable for that scope, never silently omit the row or fabricate a
number.

## Explicitly not covered (item 16 of the business-decision brief)

The period-over-period **contribution waterfall** (business-decision
item 16) is a distinct capability from this record's period-aggregation
and comparison contract: it decomposes the *change in outcome volume*
between two periods into model-supported components (channels,
base/intercept, seasonality, controls/context, residual as needed for
reconciliation) — it is not an economic (value/ROI/FX) decomposition,
and its component list/method/ordering remain unresolved pending the
required calculation/design note the business-decision brief mandates
before any implementation (WP2F). This record's period-comparison
contract (Requirement 5) supplies the two periods a waterfall would
compare, but does not itself define or approve the waterfall's
computation.

## Out of scope (decision-required, not approved by this record)

- The period-over-period contribution waterfall's computation method —
  gated behind a required design note (WP2F), not this record.
- Any FX conversion applied to a reporting-currency view.
- Component-level (channel/funnel/segment) economics where no approved
  allocation exists (Requirement 6 states the gating rule; it does not
  retroactively approve any specific allocation).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (WP2D/WP2E, not created by this record):
`ancestry_mmm/core/reporting_rollups.py`, `ancestry_mmm/core/outcome_group_totals.py`
(a new calendar-period aggregation function, analogous to but distinct
from these modules' existing outcome-group aggregation);
`ancestry_mmm/pages/07_Results_Curve_Bank.py` (period selector, comparison
view).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_004_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_004_forbids_partial_period_scaling`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_004_excludes_the_waterfall`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

The waterfall computation method (gated behind a required design note),
and any FX conversion policy — see `docs/wp2_outcome_valuation_decision_package.md`.

## Owner

Modelling / Product / Platform engineering

## Approval date

2026-08-28
