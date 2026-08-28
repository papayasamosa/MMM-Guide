# REQ-ECON-005: Period-over-Period Contribution Waterfall Design Contract

## PRD source

Business-decision brief item 16 ("Contribution waterfall") of "Outcome
valuation and time-varying ROI: approved business decisions"
(2026-08-28); reconciled together with the required calculation/design
note this record approves, `docs/wp2f_contribution_waterfall_design_
note.md`.

## Approval and traceability

Approved for implementation by the business-decision brief cited above,
following the required design/calculation note the brief mandated
before any waterfall implementation. This record reconciles that
note's determinations into approved authority. It resolves D5 of
`docs/wp2_outcome_valuation_decision_package.md` (previously "scope
resolved, computation method still open, gated behind a required
design note") — the method is now approved. Target-state architecture
contract only. Zero implementation.

## Approval basis: why no decision package was required

`docs/wp2f_contribution_waterfall_design_note.md` proves that every
open question the business-decision brief posed for this capability is
resolved either by mathematical necessity or by a minimal, documented
generalisation of an already-approved, already-shipped convention
(`core.attribution.compute_shapley_contributions`, approved implicitly
by its existing production use and explicitly anticipated as extensible
by `REQ-CURVE-001` Approved Decision 3: *"Shapley... component
decompositions remain available as future alternatives, each requiring
its own approval"*). Reviewing and merging the design note **is** that
approval. No business, financial, or statistical policy choice of the
kind `docs/wp2_outcome_valuation_decision_package.md`'s other D-items
collect was required.

## Requirement

### 1. Scope: one market, one outcome (or approved outcome-group), never blended

The waterfall is computed for exactly one market and one outcome (or
approved outcome-group) at a time, per the design note §1 — mirroring
the existing shipped precedent (`contribution_waterfall`'s existing
market-masked UI caller) and `core.outcome_group_totals`'s established
one-outcome-at-a-time discipline.

### 2. Candidate A Search fits are out of scope

The waterfall inherits, unchanged, `compute_shapley_contributions`'s
and `predict_mu`'s existing `CandidateAAttributionNotSupportedError`/
`CandidateAReplayNotSupportedError` exclusions (design note §1, §12).
It is unavailable for a Candidate A fit until a separate, future,
explicitly-scoped decision extends those functions.

### 3. Component-allocation method: generalised Shapley over time-varying eta terms

The bridge decomposes `mu = exp(eta)` using the same Shapley
construction already shipped for channel attribution, generalised to
treat every genuinely time-varying additive `eta` term — `trend`,
`season` (Fourier), `promo`, `controls`, and each channel's existing
combined direct+halo term — as a co-equal player, starting from a
shared, period-invariant reference point `mu_reference =
exp(intercept + eta_market)` (design note §13.3's refinement of §5.2).
This inherits, unchanged, the existing "reconciliation convention, not
a uniquely identified causal decomposition" caveat `REQ-CURVE-001`
already establishes for the sibling eta-share convention.

### 4. Intercept and market offset are excluded from the bridge by construction

Per the design note §4/§13.3's proof: `intercept` and `eta_market` are
time-invariant for a fixed outcome/market and therefore contribute
exactly zero to any period-over-period delta. They are fused into the
shared Shapley reference point, never presented as separate bars, and
never computed as a "proven-zero" runtime check that could produce a
near-zero floating-point artefact.

### 5. No residual/unexplained term is required

Because the player list (Requirement 3) is exhaustive over every
additive `eta` term this repository's current model class produces
(design note §3, §6, §11), the bridge reconciles to zero residual by
construction. A residual/unexplained bar must never be presented in
ordinary operation. An internal, fail-closed reconciliation-error check
(`Outcome_B_total - Outcome_A_total - sum(bridge_contributions)`,
expected ≈0 within the Requirement 7 tolerance) must still be computed
and must block chart display if it fails — evidence of either a defect
or a future model change introducing an additive `eta` term this
record's player list does not yet know about.

### 6. Weekly-to-period aggregation and posterior uncertainty

Each period's weeks are resolved via `core.outcome_valuation_periods`
(WP2D-core) — never fabricated or scaled for a partial period. Posterior
uncertainty is propagated by evaluating both periods under the *same*
sampled `(chain, draw)` indices per draw (the existing paired-comparison
discipline `core.uncertainty.evaluate_scenario_with_uncertainty`
already establishes), summarised via the existing governed
`core.uncertainty.summarize_distribution` credible-interval convention
— no new interval method (design note §7).

### 7. Reconciliation quantity and invariant

The bridge is built entirely on posterior expected outcome (`mu`) —
never raw observed outcome, never posterior-predictive draws (design
note §10, resolved by mathematical necessity: only `mu` is the sum of
named additive components; both alternatives introduce an unavoidable,
business-uninterpretable sampling-noise residual). Every implementation
test must enforce:

```text
Outcome_A_total + sum_over_players(bridge_contribution(p)) == Outcome_B_total
```

via `np.testing.assert_allclose(..., rtol=1e-5, atol=1e-6)` — the exact
tolerance precedent already established by `tests/test_attribution.py`'s
existing single-period reconciliation test (design note §8).

### 8. Presentation ordering is cosmetic, never a reconciliation concern

Bar ordering (recommended default: positive contributors descending by
magnitude, then negative contributors ascending by magnitude) may be
adjusted by Product/UX without any re-approval of this record, since
reordering a sum never changes its value (design note §9).

## Out of scope (not approved by this record)

- Any actual `core`, `application`, or `pages` code — this is a design
  contract only. Implementation is WP2F implementation, a separate PR.
- Extending the waterfall to Candidate A fits.
- Any change to `compute_shapley_contributions` itself — the design
  note recommends a new, parallel function so the existing, approved,
  tested channel-only decomposition remains completely unchanged for
  its current callers.
- Any presentation/labelling wording beyond the cosmetic ordering
  recommendation above.

## Affected modules

None yet — target-state design contract only. Anticipated future
affected modules (WP2F implementation, not created by this record, per
the design note §14): a new trace-extraction function for the named eta
Deterministics; a new generalised-Shapley function parallel to (not
replacing) `core.attribution.compute_shapley_contributions`; a new
period-bridge orchestration function joining
`core.outcome_valuation_periods`, the new Shapley function, and
`core.uncertainty`; `ancestry_mmm/core/market_specific_attribution.py`
(the mirrored Model C path).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_005_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_req_econ_005_resolves_d5_without_a_residual`
- `ancestry_mmm/tests/test_outcome_valuation_roi_authority_reconciliation.py::TestOutcomeValuationAuthority::test_design_note_proves_reconciliation_is_order_independent`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

None specific to this record's own scope. `docs/wp2_outcome_valuation_
decision_package.md`'s D7 (FX conversion policy) remains open and
unrelated to this record's scope — the waterfall decomposes outcome
*volume*, never a monetary/FX-denominated quantity.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-28
