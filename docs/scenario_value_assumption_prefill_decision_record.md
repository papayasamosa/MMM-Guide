# Scenario value-assumption optional pre-fill decision record (Decision 14 / WP2G reconciliation)

## Why this record exists

`REQ-FUTURE-001`'s 2026-08-30 addendum approved Decision 14's principle
("the analyst should not have to manually supply an assumption the
model, a governed system default, Finance data, or an approved forecast
method can already provide") and named a specific, narrow, Phase-D
reconciliation task: `core.planning.value.ScenarioValueAssumptions`
(WP2G, `REQ-ECON-003` Requirement 5) forces every FH-LTR/DNA-revenue
number to default to `0.0` with no historical pre-fill, by deliberate
original design (to avoid a *silent* default). The addendum's own text
requires both halves to survive: forward assumptions must stay governed
and explicit, never silently defaulted from history, AND unnecessary
manual entry should be reduced via an approved, optional, disclosed
default where one exists. This record resolves that reconciliation at
the computation-contract level.

This is a narrower, more specific task than `docs/wp9_future_assumption_
bundle_decision_package.md`'s reserved "future-assumption bundle"
architecture question (that package explicitly states "this is
intentionally not chosen by the coding agent" for the general-purpose
bundle data structure spanning arbitrary exogenous controls and external
forecasting methods) — this record does not touch that question at all.
It is scoped to exactly what `REQ-FUTURE-001`'s addendum named: an
optional pre-fill for one specific, already-existing UI input
(`ScenarioValueAssumptions`), sourced from one specific, already-
implemented historical computation (`REQ-ECON-002`/`003`'s
`core.outcome_valuation_rates.WeeklyValueRate` rate-derivation), which
is not itself decision-required territory.

## Decision required

### P1. What "the historical rate" means as a single forward suggestion

`derive_weekly_value_rates` produces a *series* of `WeeklyValueRate`
values (one per `market x week x segment` cell), not a single scalar.
Turning a series into one suggested forward value requires a choice.

**Candidate P1-A — a smoothed/windowed average (e.g. trailing 13 or 52
weeks).** Rejected for this record: choosing a specific averaging
window is itself a new, disclosable statistical judgement (why 13 weeks
and not 8 or 52?) that adds complexity without a clear business
justification, and risks smoothing over a genuine recent step-change in
value the analyst should see directly.

**Candidate P1-B — the most recent observed rate for that outcome_id's
market/segment.** The simplest, most transparent, most directly
inspectable choice: "the last time we actually measured this value, it
was X, observed for week Y" — the analyst can trivially verify this
claim against the underlying data themselves, unlike a multi-week
average whose exact window they would have to trust. This does not
invent any new smoothing/aggregation policy; it reuses exactly the
already-approved `WeeklyValueRate.value_per_unit` computation with no
new statistical step of its own.

**Decision: P1-B.** A future session may add a windowed-average
alternative later if a business reason emerges; this record does not
foreclose that, but does not implement it either.

### P2. Never silent, always overridable, always disclosed

Matching `REQ-FUTURE-001`'s addendum text exactly: the suggestion is
computed as a separate, clearly-labelled record
(`ScenarioValuePrefillSuggestion`) — never returned as, or silently
merged into, a `ScenarioValueAssumptions` instance itself. Applying a
suggestion (copying its `suggested_value` into the analyst's actual
input) remains an explicit, disclosed, overridable UI action for a
future integration pass — this record supplies only the suggestion
computation, not the application/UI wiring, mirroring this project's
established "contract now, wiring later" discipline (e.g. `core.
google_trends_anchor` does not wire its identifying constraint into
`core.search_capacity`).

### P3. Missing data produces no suggestion, never a fabricated one

An outcome_id/segment combination with no `WeeklyValueRate` at all in
the supplied history produces `None` (no suggestion), never a
fabricated `0.0` or an arbitrarily chosen fallback - consistent with
this repository's "missing is not zero" doctrine applied to a
suggestion rather than a required value.

## What this record does not decide

- `docs/wp9_future_assumption_bundle_decision_package.md`'s reserved
  future-assumption-bundle architecture question (untouched).
- The actual Scenario Planner page (`pages/*.py`) UI wiring that would
  show a suggestion and let the analyst accept or override it - a
  future integration pass, using this record's computation as its input.
- Any FX conversion across currencies for a suggested value - inherits
  `ScenarioValueAssumptions`'s own existing single-currency restriction
  unchanged.

## Implementation

`ancestry_mmm/core/planning/value_prefill.py`:

- `ScenarioValuePrefillSuggestion` — one suggested value, its currency,
  provenance (`source_week`, `source_market`, `source_segment`,
  `basis="most_recent_observed_rate"`), and a disclaimer that this is a
  suggestion only, never an applied value. Deliberately does NOT carry
  an `outcome_id` field: `WeeklyValueRate` (this suggestion's only
  input) has no `outcome_id` of its own — its key is
  `(valuation_kind, market, week, segment)` — so this module has no
  domain knowledge of which target `outcome_id` a given
  `valuation_kind`/`market`/`segment` cell should suggest a value for.
  That mapping (which outcome_id(s) in `ScenarioValueAssumptions` a
  given cell applies to) is caller-supplied, mirroring every other
  "this module has no domain knowledge of X" pattern already
  established in this repository (`CompatibilityAssessment`,
  `LatentStateIdentificationDeclaration`).
- `suggest_value_prefill` — P1-B/P3 for one `(valuation_kind, market,
  segment)` combination, from a supplied `Sequence[WeeklyValueRate]`.
  Returns the most-recent-week matching rate's value as a suggestion,
  or `None` if no rate matches at all.
- `suggest_value_prefills` — the same, batched over multiple
  `(valuation_kind, market, segment)` combinations, returning `None`
  per entry with no data, never raising for a partially-covered batch.

Tests: `ancestry_mmm/tests/test_scenario_value_prefill.py`.

## Owner and status

Owner: Modelling / Platform engineering (computation contract);
Product/UX sign-off on the actual Scenario Planner UI treatment (how a
suggestion is shown/accepted) not yet sought - separate integration
pass.

Status: implemented and tested, 2026-08-30. `REQ-FUTURE-001` addendum
(below) records this resolution; no change to WP2G's shipped UI.
