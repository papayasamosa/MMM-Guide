# REQ-FUTURE-001: Governed Future-Assumption Bundle

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-FCST-013`, §26.16), Part 6 v1.6 (intro
bullet 10, §26.7), Part 7 v1.5 (§0.15 intro bullet 9, §30.8, §39 blocking
condition #22, §48 `VL-027`), Part 9 v1.5 (§21.1–§21.7, §RP-024), and Part 10
v1.6 (`FCH-09`, §26.1, §26.4–§26.5, §26.11) — the same source material
`REQ-FORECAST-001` already reconciled for its narrower consequence-
assessment contract. This record reconciles that same PRD material's
broader "governed future assumptions" scope, named but not authorised by
`REQ-FORECAST-001`'s own "Approval and traceability" section, into
repository authority.

## Approval and traceability

Reconciled into repository authority by Work Package 9 of `Media-Mix-Lab:
Coding LLM Next Steps After PR #267 and Latest PRD Validation Updates`
(2026-08-18), per this repository's standard authority hierarchy. Depends
on `AGENTS.md`'s "Future-variable roles" section (the six-role taxonomy:
planned decision variable, exogenous forecastable control, cost/
translation assumption, endogenous funnel state, latent baseline state,
fixed business assumption) and `core.planning.future_context` (`REQ-SCEN-
002`), which already implements the per-control explicit/hold-last-
observed contract for one plan window's exogenous controls and
promotions, but has no bundle-level object: no versioned, approved,
named collection of every future-role assignment for a scenario, no
single decision-readiness rollup across controls, cost/translation
assumptions, and any future external-forecaster output together, and no
place for `REQ-FORECAST-001`'s consequence evidence to attach once
produced.

This record reconciles that already-flagged gap (`docs/specification_
authority.md`: "Future-assumption bundles — No approved requirement/
decision yet") into a formal requirement record — it does **not** approve
an implementation. Three genuinely unresolved questions block any
implementation and are recorded below as decision-required, per this
program's own governing instruction: do not implement directly from an
unapproved gap, and if a genuine statistical/causal/business/governance
decision is required, create a decision package and stop that workstream
rather than guessing. See `docs/wp9_future_assumption_bundle_decision_
package.md`.

## Capability status

Not yet implemented. Blocked pending the decision package referenced
above — this is a target-state contract only, reconciling PRD-level
authority that a governed future-assumption bundle object must eventually
exist, without approving any specific bundle schema, materiality-grading
method, or external-forecaster integration.

## Requirement (target state - not yet approved for implementation)

### 1. A bundle is a named, versioned collection of future-role assignments

Mirroring `core.causal_graph`/`core.search_objects`/`core.experiments`'s
existing immutable-and-versioned lineage pattern, a future-assumption
bundle must collect every future-role assignment relevant to one scenario/
plan window (exogenous forecastable controls, cost/translation
assumptions, and any approved external-forecaster output) into one
identified, versioned object — never several independently-tracked
assumptions with no shared identity an analyst or reviewer can audit as a
whole.

### 2. Decision-readiness rolls up, never silently improves

`core.planning.future_context.FutureContextResult.is_decision_ready` is
already `False` whenever any one control used `hold_last_observed`
(`REQ-SCEN-002`). A bundle wrapping multiple such contexts (or adding
externally-forecast series) must roll this up the same way — decision-
ready only if every constituent assumption is, never a bundle-level
override that marks the whole as ready when a part is not.

### 3. Consequence evidence attaches per bundle, not per ad-hoc call

Once `REQ-FORECAST-001` is implemented, its two-axis (standalone accuracy
vs. downstream consequence) evidence for a future exogenous control must
be attachable to the specific bundle version it was assessed against —
never floating evidence with no fixed relationship to the exact future
path it evaluated.

### 4. Role-conflict blocking is inherited, not re-decided

`AGENTS.md`'s "Future-variable roles" rules (a mediator must not also be
an independent future control without an approved joint decomposition; a
latent baseline must not be a Chronos/external-forecast target; invalid
role/source combinations are blocking errors) apply unchanged to every
assignment inside a bundle. This record does not relax or restate that
boundary — it is inherited exactly as it already stands.

## Explicitly excluded (decision-required, not approved by this record)

- **The bundle schema itself.** Whether a bundle is a new module wrapping
  one or more `FutureContextResult`s, an extension of `FutureContextResult`
  itself, or a separate registry object referencing them by fingerprint,
  is not decided by this record.
- **Materiality quantification/grading method (`VL-027`/`RP-024`).**
  Inherited unresolved from `REQ-FORECAST-001`'s own "Unresolved
  decisions" — how much forecast uncertainty or downstream consequence
  becomes decision-material, and when forecast-consequence review becomes
  blocking rather than advisory, is not decided by this record either.
- **External-forecaster integration (Chronos-2 or another method).**
  `AGENTS.md` permits Chronos-2 "or another method" for exogenous
  controls and cost/translation series only — which method, if any, is
  approved for production use, how its output enters a bundle's explicit-
  future-path contract (`core.planning.future_context`'s existing
  `explicit_future` mapping already accepts any caller-supplied series,
  forecast-derived or not — no code change is required merely to accept
  one), and what forecast-provenance disclosure a bundle must carry when
  it does, are not decided by this record. No dependency on any external
  forecasting library is introduced by this record.

## Affected modules (target - not yet touched)

- a future-assumption-bundle module (module TBD; depends on the schema
  decision above, not yet implemented)
- `ancestry_mmm/core/planning/future_context.py` (read-only reference for
  this record — the existing per-control contract this future bundle
  object would need to wrap or extend, not itself modified by this record)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (surface bundle-level
  decision-readiness alongside a scenario, not yet touched)
- `docs/wp9_future_assumption_bundle_decision_package.md` (new)
- `docs/approved_requirements/REQ-FUTURE-001.md` (this record)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No code changes accompany this record.

## Unresolved decisions

- The bundle schema (wrapper, extension, or referencing registry).
- Materiality quantification/grading method (`VL-027`/`RP-024`), inherited
  unresolved from `REQ-FORECAST-001`.
- External-forecaster integration: method selection, provenance
  disclosure, and interaction with the existing `hold_last_observed`
  convention.

All three are recorded in `docs/wp9_future_assumption_bundle_decision_
package.md` with candidate approaches and their tradeoffs - none selected
by this coding pass.

## Owner

Modelling

## Approval date

2026-08-18

## Addendum, 2026-08-30: manual-entry-reduction principle approved; WP2G reconciliation task recorded

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 14, "Future planning should
require only assumptions the user actually controls") approves a
governing *principle* for this record's eventual bundle schema and for
`core.planning.value.ScenarioValueAssumptions` (WP2G, `REQ-ECON-003`
Requirement 5). This addendum records the principle and a named
reconciliation task; it does not itself change the bundle schema
decision (still open, see "Unresolved decisions" above) or any code.

**Approved principle.** The analyst should not have to manually supply
an assumption the model, a governed system default, Finance data, or an
approved forecast method can already provide — specifically: expected
demand, future seasonality, baseline growth, exchange rates, and
individual future prices/values. The analyst *should* continue to
supply: planned marketing activity, promotion periods, and explicit
governed overrides. This confirms, and does not change, what this
repository already does correctly: `core.planning.future_context`
already deterministically auto-continues trend/Fourier seasonality terms
(never asked manually); `REQ-FX-005`'s future-FX-assumption contract
already exists (implementation blocked on Finance, per that record and
`docs/wp7_governed_fx_finance_decision_package.md`, not on this
principle). This addendum does not create a demand-forecasting
capability where none exists — where an approved forecasting method does
not yet exist (baseline/demand — `REQ-BASELINE-001`, still
decision-required), the analyst is not required to guess merely because
the forecast engine is unfinished, per Decision 14's own text, but no
substitute forecast is invented by this addendum either.

**Named reconciliation task (Phase D, not this record, not this pass):**
WP2G (`4eb91f80`, 2026-08-28) implemented `ScenarioValueAssumptions` so
that every FH-LTR/DNA-revenue number defaults to `0.0` and requires
explicit analyst entry every time, by deliberate design, with automatic
pre-filling from historical valuation explicitly rejected as a
considered alternative (to avoid a *silent* default). This sits in
tension with this addendum's principle of reducing unnecessary manual
entry via "an approved average value/price assumption... rather than
asking for every individual price." Both halves of Decision 14's own
text are simultaneously true and must both survive a future
reconciliation: (a) forward assumptions must stay governed and explicit,
never silently defaulted from history, and (b) unnecessary manual data
entry should be reduced via approved defaults where the business
decision supports them, with every assumption still disclosed in the
final plan. The reconciliation — adding an **optional**, governed,
overridable, explicitly-disclosed pre-fill for `ScenarioValueAssumptions`
sourced from `REQ-ECON-002`/`REQ-ECON-003`'s existing historical
rate-derivation contract, never mandatory and never silent — is Phase D
implementation work, not approved or implemented by this addendum. No
change to WP2G's shipped UI or defaults accompanies this record.
