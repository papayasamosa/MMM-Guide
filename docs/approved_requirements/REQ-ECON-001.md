# REQ-ECON-001: Governed CPA/ROI Arithmetic and Value-Join Contract

## PRD source

Ancestry MMM PRD Part 6 v1.11 §24.1/§24.2 ("Average incremental
economics"); Part 8 v1.6 §3.3, §8.1, §8.2, §8.5 ("Average and marginal
metrics"); Part 4 v1.8 §14.3 ("Maturity alternatives"); Part 5 v1.6
§12.4 ("Platform diagnostic metrics") — reconciled as part of the
outcome-valuation/joined-ROI authority, architecture and gap-analysis
package (2026-08-28). Unlike the Search/SEO and FX overlays, this
content is not a newer focused overlay layered on an older baseline — it
is already-current, already-consistent content within the parts'
present versions as recorded in `docs/specification_authority.md`, so no
new version-history overlay section is required to reconcile it.

## Approval and traceability

Approved for implementation by the task-specific analysis brief that
produced `docs/wp2_outcome_valuation_gap_analysis.md` and
`docs/wp2_outcome_valuation_decision_package.md` (2026-08-28). This
record reconciles two narrow, unambiguous, already-implemented
invariants — the CPA/ROI arithmetic formula and the value-join
principle — into approved repository authority. It does not approve,
select, or imply any definition of what the *value* operand in the ROI
formula actually is (source, timing, currency, or attachment to a
specific outcome) — that remains entirely open, tracked by
`docs/wp2_outcome_valuation_decision_package.md`.

This record was created after explicitly checking whether the PRD
supports a `(revenue - spend) / spend` (net-of-investment) alternative
ROI definition: it does not. Part 6 §24.2 and Part 8 §8.1/§8.2/§8.5 state
the same value/cost ratio consistently, and no PRD passage anywhere
states or implies the net-of-investment form (confirmed by direct
search across all 11 parts and the FX addendum). The existing codebase
already implements the ratio form consistently across three independent
modules (see "Capability status" below).

## Capability status

Already substantively implemented and internally consistent — this
record locks in existing behaviour as a required contract, the same
pattern `REQ-CURVE-001`'s "Mathematical contract" section and
`REQ-ENGINE-001` already established for other already-true facts.
Verified sites:

- `core/canonical_curves.py:789-840` (`_economic_values`):
  `average_cpa = spend / response`; `average_roi = response *
  value_per_response / spend`; `marginal_cpa = 1.0 / marginal_response`;
  `marginal_roi = marginal_response * value_per_response`.
- `core/attribution.py:261-326,472-487` (`outcome_channel_summary`,
  `calculate_roi`): `cpa = total_spend / vol`; `value = vol * weight`;
  `value_roas = value / total_spend`.
- `core/optimization.py:2130-2326`: `avg_cpa = total_spend /
  incremental_fh_gsa` (and per-outcome variants); `value =
  monthly_outcome_by_id[oid] * ltv[oid]`; `whole_plan_incremental_roi =
  incremental_total_value / total_spend`.

Twelve verbatim formula instances across these three modules all follow
the identical pattern with no contradiction. None of them defaults a
missing value weight to 0 or 1 — every site fails closed (`value_status`
tri-state disclosure, `"not configured" / "partial" / "complete"`) — an
existing invariant this record also locks in (Requirement 4).

## Requirement

### 1. CPA formula

Average CPA must be computed as:

```text
average_cpa = (approved cost scope) / (incremental approved outcome)
```

Marginal CPA must be computed as the inverse of marginal incremental
response at the declared decision point:

```text
marginal_cpa = 1 / marginal_response
```

CPA never requires a value operand — it is a pure cost/outcome-count
ratio, unaffected by any decision made in
`docs/wp2_outcome_valuation_decision_package.md`.

### 2. ROI formula

Average ROI must be computed as:

```text
average_roi = (incremental approved value) / (approved cost scope)
            = incremental_outcome * value_per_unit / spend
```

Marginal ROI must be computed as:

```text
marginal_roi = marginal_response * value_per_unit
```

This is a value/cost ratio (mathematically equivalent to what marketing
practice commonly calls ROAS), never a net-of-investment `(value -
cost) / cost` figure. Any future UI or report label choosing between
"ROI" and "ROAS" terminology is a presentation decision, not an
arithmetic one, and is out of scope for this record (see
`docs/wp2_outcome_valuation_decision_package.md`, D0's terminology
note).

### 3. Value is joined to, never presented as, the incremental outcome

A supplied or configured value (`value_per_unit`, `value_weight`, `ltv`,
or any future week/segment-varying successor) is multiplied against an
already-computed incremental *outcome count* — it is never itself
treated as, substituted for, or reported as the incremental outcome.
Platform-reported, attributed, or raw-observed revenue/conversion
figures remain diagnostic and comparison-only and must never be
represented as the MMM's incremental outcome or incremental value (Part
5 §12.4, quoted verbatim: *"Platform-reported conversions, CPA, ROAS and
attributed revenue may be retained for comparison and diagnostics, but
they must not be represented as the MMM incremental outcome."*). This
reconciles and formalises the same principle AGENTS.md's "Mathematical
rules" section and `REQ-OUT-001` already establish generically
("outcome registry, not a fixed primary outcome"; distinct measures
never treated as synonyms).

### 4. Fail-closed value-weight disclosure

A missing value weight/mapping for a targeted outcome must never
silently default to `0` or `1`. The existing tri-state disclosure
(`value_status`: `"not configured" / "partial" / "complete"`) is the
required contract; any future week/segment-varying value mechanism must
preserve this fail-closed discipline rather than substituting an
implicit default for a missing week or segment.

### 5. Channel-total economics remain authoritative

Consistent with `REQ-CURVE-001`'s existing "Economics" section: a
component-level CPA or ROI (direct vs. halo vs. any future decomposed
piece) requires an explicit, approved cost/value allocation and must
never substitute for, or override, channel-total CPA/ROI. This record
does not change `REQ-CURVE-001`'s existing contract; it is cited here
only to confirm the arithmetic in Requirements 1-2 composes correctly
with that existing rule at the channel-total level.

### 6. Draw-level calculation, aggregated before summary

Both CPA and ROI must be calculated per posterior draw (and, once
approved, per week) before any aggregation or summarisation — consistent
with AGENTS.md's "Posterior draws must be aggregated before posterior
summaries" and "Do not add independently summarised medians." This
record does not change that existing rule; it confirms the ROI/CPA
formulas above are computed within, not around, that discipline.

## Out of scope (decision-required, not approved by this record)

See `docs/wp2_outcome_valuation_decision_package.md` in full. In
summary, this record does not approve:

- what `value_per_unit` represents for Family History (projected LTR's
  definition, or which FH outcome it attaches to) — D1;
- what `value_per_unit` represents for DNA (revenue's attachment to
  orders/kits/outcomes, or which segment axes it varies by) — D2;
- missing-week imputation policy — D3;
- future-value extrapolation policy — D4;
- any waterfall/economic-decomposition accounting method — D5;
- reporting-period aggregation weighting for partial periods — D6;
- FX policy for a value/revenue series, as distinct from the
  already-approved spend-side FX architecture (`REQ-FX-001` through
  `REQ-FX-006`) — D7;
- treatment of value uncertainty when a value series varies — D8;
- the source-pack domain classification of a supplied weekly value
  series, and the content of the PRD-referenced-but-undefined
  `value_rule` object — D9;
- standard reporting periods and the exact YoY decomposition method
  underlying any of the four independently-worded PRD copies of that
  question — D10.

## Affected modules

None. This record locks in existing behaviour; it changes no code.
Anticipated future affected modules (not created by this record, once
D1-D10 above are resolved): `ancestry_mmm/core/canonical_curves.py`,
`ancestry_mmm/core/attribution.py`, `ancestry_mmm/core/optimization.py`,
`ancestry_mmm/core/outcomes.py`, `ancestry_mmm/core/planning/value.py`.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_canonical_curves.py::test_matches_normal_prediction_function_exactly`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_001_indexed_and_implemented`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_001_reconciles_the_ratio_form_not_net_of_investment`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record — it reconciles already-true, already-implemented
behaviour into approved authority.

## Unresolved decisions

D1 through D10 in `docs/wp2_outcome_valuation_decision_package.md`. None
of them affects the arithmetic this record approves; all of them affect
what is fed into it.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-28
