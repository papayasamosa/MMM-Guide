# Future-assumption bundle architecture decision record (Decision 14 continuation)

## Why this record exists, and why it can now be written

`docs/wp9_future_assumption_bundle_decision_package.md` reserved its
bundle-schema (B1/B2/B3), materiality-grading (M1/M2/M3), and external-
forecaster-integration (F1/F2/F3) candidates from the coding agent. The
user's 2026-08-29 business-decision brief, confirmed in-session
2026-08-30, explicitly delegates the bundle/module architecture:
"The business semantics are in the instructions. Users should provide
things they actually control, especially planned activity and
promotions, while demand, seasonality and similar model-derived
assumptions should come from governed system/model forecasts rather
than manual guesses. The exact internal bundle/module architecture is an
implementation choice. Reconcile it with the work already in the
repo and document the resulting contract." This record makes that
selection.

## Decision B (bundle schema)

**Decision: B1 - a thin named wrapper around existing
`FutureContextResult`s.** A `FutureAssumptionBundle` is a small,
versioned dataclass holding a name/identity and a mapping of a
caller-chosen key (typically market, or market+scenario) to the
`FutureContextResult` already built for it by `core.planning.
future_context.build_future_context` (`REQ-SCEN-002`) - completely
unchanged. Bundle-level `is_decision_ready` is the logical AND of every
wrapped result's own property, matching `FutureContextResult`'s own
existing "any exploratory hold_last_observed excludes decision-ready
status" rule, generalised across every context the bundle wraps.

Selected over B2 (rejected: would couple `FutureContextResult`'s
single-market/single-window build function to a cross-window bundling
concept it was never designed to know about, forcing every existing
caller - `core.sequential_scenario_evaluation`,
`pages/08_Scenario_Planner.py` - to supply bundle identity even when no
genuine multi-context bundle is in play) and B3 (rejected: a
fingerprint-keyed registry with no wrapper object avoids inventing a new
type, but wp9's own text notes it "raises its own sub-question of where
such a registry would live and whether it needs its own persistence/
export contract, not addressed by this package" - i.e. it defers MORE
open questions than B1 does, the opposite of what "reconcile it with the
work already in the repo" asks for). B1 reuses `core.planning.
future_context` entirely unchanged and directly answers "what a bundle
is" without leaving new persistence/registry-location questions open.

## Decision M (materiality quantification and grading)

**Decision: M3 - disclosed, ungraded consequence evidence only; no
materiality score or blocking/non-blocking verdict field, ever.**
Directly matches this program's own already-established precedent
(`core.calibration_comparison`'s explicit ban on a verdict/
recommendation field, `REQ-CALIB-001` Requirement 3, enforced by a test
scanning every dataclass field for a forbidden verdict-shaped name) -
this record applies the identical discipline here rather than inventing
a new one. Rejected M1 (a fixed/configurable effect-size threshold -
wp9's own text flags this "requires approving a specific threshold and
its business justification - an explicit business/statistical judgement
call this package does not make," and risks the "one frozen number"
brittleness `AGENTS.md` cautions against elsewhere) and M2 (decision-
ranking-change detection - requires a comparison set of candidate
plans that "may not always be available," a structural precondition
this record cannot guarantee).

This resolves the DISCLOSURE CONTRACT only - `REQ-FORECAST-001`'s own
consequence-assessment MECHANISM (posterior scenario replay, local
sensitivity, counterfactual replay) is "not yet implemented, target-
state contract only" per that record's own "Capability status," so
there is nothing yet to grade even ungraded. This record ensures that
whenever that mechanism is eventually built, its evidence attaches to a
bundle without ever collapsing into a fabricated single score - mirrors
exactly how `REQ-CALIB-001`'s comparison contract was built years before
any calibration mechanism existed to populate it.

## Decision F (external-forecaster integration)

**Decision: F1 - no production external-forecaster integration now;
explicit-future-path or hold_last_observed only, exactly as `core.
planning.future_context` already supports, unchanged.** This is the
disclosed, low-risk default for this pass, not a permanent rejection.
Two considerations support F1 specifically at this time: first, the
user's own business framing ("demand, seasonality and similar model-
derived assumptions should come from governed system/model forecasts
rather than manual guesses") is **already satisfied today** for demand/
seasonality specifically - `core.planning.future_context`'s existing
deterministic trend/Fourier continuation already IS a governed,
model-derived forecast for those two variables, requiring no manual
entry and no new forecaster dependency (confirmed by this session's own
earlier Decision 14/WP2G reconciliation work, and by `REQ-FUTURE-001`'s
own prior addendum). Second, F2/F3 (Chronos-2 or a method-agnostic
forecaster interface) both "require the same backtest/provenance
decisions... before any registered method's output is trustworthy" per
wp9's own text - a substantial new validation workstream (a new
dependency subject to this repository's upstream-reference policy, a
backtest-accuracy contract, and `AGENTS.md`'s existing future-variable-
role boundary that a forecaster may only ever serve an exogenous
control or cost/translation series, never an endogenous mediator or
latent baseline) that is not itself "bundle architecture" and should not
be rushed inside this record's narrower scope.

## What this record does not decide

- Any actual Chronos-2 (or other) forecaster integration - remains
  explicitly future work (F2/F3), not rejected, not attempted here.
- The specific numeric materiality threshold M1/M2 would need, should a
  future business decision select either over M3.
- `REQ-FORECAST-001`'s own consequence-assessment mechanism itself - a
  separate, substantial modelling workstream.
- Any persistence (`core.persistence`), UI (`pages/08_Scenario_
  Planner.py`), or diagnostics-page wiring for a bundle - this record
  supplies the governed data-structure contract only, consistent with
  every other Phase B/C/D step's "declare the contract, defer UI/
  persistence wiring" scope boundary already established in this
  repository.

## Implementation

`ancestry_mmm/core/planning/future_assumption_bundle.py` (new):

- `FutureAssumptionBundle` - the B1 wrapper: `bundle_id`,
  `bundle_version`, `context_by_key: Mapping[str, FutureContextResult]`,
  computed `is_decision_ready` (AND across every wrapped context),
  `fingerprint()` (a hash of every wrapped context's own existing
  `fingerprint()`, never re-hashing raw content the wrapped result
  already fingerprints).
- `new_bundle_version`/`current_bundle_versions` - the same lineage-
  identity pattern already established by `core.search_objects`/`core.
  experiments`/`core.capacity`.
- `summarise_bundle_control_provenance` - a flat, deduplicated view
  across every wrapped context's `control_assumptions`, distinguishing
  which controls (across the whole bundle) are `EXPLICIT_ASSUMPTION`
  (analyst-supplied, i.e. "things they actually control") versus
  `HOLD_LAST_OBSERVED_ASSUMPTION` (exploratory-only) - directly serving
  Decision 14's own "users should provide things they actually control...
  everything else should come from governed defaults" framing at the
  bundle level, not only per-context.
- `FUTURE_ASSUMPTION_BUNDLE_MATERIALITY_POLICY = "M3_disclosed_ungraded_evidence_only"`,
  `EXTERNAL_FORECASTER_INTEGRATION_POLICY = "F1_no_production_integration"` -
  governed constants recording the M/F resolutions. No dataclass field
  anywhere in this module is named or shaped like a verdict/
  recommendation/materiality score - enforced by a dedicated regression
  test scanning every dataclass field, mirroring `core.calibration_
  comparison`'s own established test.

This module does not modify `core.planning.future_context`,
`core.persistence`, or any `pages/*.py` UI - it is additive, standalone,
and read-only with respect to `FutureContextResult`.

Tests: `ancestry_mmm/tests/test_future_assumption_bundle.py`.

## Owner and status

Owner: Data Science / Platform engineering (bundle schema); Modelling
(materiality-grading and forecaster-integration policy, not re-decided
by this record beyond the disclosed defaults above). Status: implemented
and tested, 2026-08-30, per the user's explicit 2026-08-30 authorisation
delegating this architecture selection (see wp9's updated text).
