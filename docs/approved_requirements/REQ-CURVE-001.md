# REQ-CURVE-001: Official response curve authority and evidence contract

**Status:** approved for implementation
**Decision date:** 2026-07-31

## Decision

The repository will have exactly one authoritative calculation path for new *official*
response curves, and one distinctly-typed, non-official *exploratory* path. A curve's
official status is a structural property of which service produced and persisted it, never
an unchecked caller-supplied flag, and never the by-product of omitting an optional argument.

This decision does not select a business outcome definition, causal role, approval policy,
cost rule, FX rule, counterfactual value, support rule, or planning eligibility rule beyond
what already exists as approved repository requirements (`REQ-OUT-001`, `REQ-OUT-002`,
`REQ-USE-001`, `REQ-STALE-001`, `REQ-VAL-001`, `REQ-NBT-001`, `REQ-PLAN-001`) — it defines the
*authority and evidence contract a curve must satisfy*, reusing those existing rules rather
than restating or reinterpreting them.

See `docs/curve_authority_gap_analysis.md` for the full evidence base, source citations, and
compared architecture options this decision is drawn from.

## Definitions

- **Official response curve** — an evaluated, posterior-draw response curve, produced by the
  single authoritative calculation path (`core.canonical_curves.generate_canonical_curve_draws`
  or its successor), whose persisted artifact carries a complete, verifiable governance chain
  (Governance chain, below) and is eligible for at least one of the publication/use categories
  in `core.outcome_approval.OUTCOME_USES`.
- **Exploratory curve** — any curve — whether from the canonical calculation in
  `governance_mode="exploratory"` or from the point-estimate generators
  (`core.predict.generate_channel_curve`, `core.market_specific_predict.generate_market_channel_curve`)
  — that has not satisfied the full governance chain. Structurally and visibly distinct from
  an official curve; never eligible for the official-use publication categories without
  revalidation.
- **Fitted parameter snapshot** — a `core.curve_bank.CurveBankEntry` (or equivalent): a small
  set of fitted Hill/decay/beta point estimates for one (market, channel,
  segment-or-overall). Not an evaluated curve. Never described, labelled, or presented as an
  "official response curve" without the qualifier "parameter snapshot."
- **Canonical evaluated curve artifact** — the persisted output of the authoritative
  calculation path: one row per posterior draw × spend point × market × channel × component,
  plus the full reference-context, counterfactual, support, cost/currency, and governance
  metadata needed to reproduce and audit it.
- **Model-input curve** — a curve whose horizontal axis is the model's own fitted media-input
  unit (`curve_type="model_input"` in `core.canonical_curves`), not a monetary quantity.
  Available without cost/currency data.
- **Monetary curve** — a curve whose horizontal axis is local spend, produced by mapping
  model-input quantities through an approved, effective `core.media_costs.MediaCostMapping`
  (`curve_type="monetary"`). Requires a resolved cost mapping unconditionally, in every
  governance mode.
- **Channel-total curve** — the full incremental response for one channel, summed across
  every simultaneous component (direct + cross-product/halo).
- **Component curve** — one decomposed piece of a channel-total curve
  (`component_type`), allocated by incremental-eta share; reconciles exactly back to the
  channel-total curve; carries no cost/CPA/ROI unless an explicit `ComponentCostAllocation`
  exists.
- **Portfolio curve** — a whole-plan marginal-economics view requiring an explicit
  `portfolio_path_id` and `PortfolioPerturbation` allocation direction; never an implicit or
  default aggregation across channels.
- **Steady-state curve** — a curve computed by holding trend, seasonality, promotion, and
  controls at explicit reference values and varying only the channel(s) under study
  (`"curve_method": "steady_state"`). This is the only curve method currently implemented by
  either curve system in this repository.
- **Sequential curve** — a curve that evolves the model's dynamic (carry-in/adstock) state
  week over week rather than holding it at a steady-state reference. Not implemented by
  either curve system today; explicitly out of scope for this requirement and deferred to the
  PR 94A/94B governed-future-assumptions work named in the task brief. Defined here only so
  that a future curve can be unambiguously labelled steady-state or sequential and never left
  ambiguous.
- **Reference context** — the complete, explicit, persisted set of assumptions
  (`core.canonical_curves.CurveReferenceContext`) a curve is evaluated under: market, trend,
  seasonality, promotions, controls, outcome controls, other-channel media input, context
  mode, and reference period. No implicit zero, historical mean, or unstated default may
  stand in for an explicit reference-context field.
- **Counterfactual** — the explicit alternative media-input value (and axis type) a curve's
  incremental response is measured against, persisted alongside every draw, never an
  unstated or implicit zero.
- **Observed support** — the media-input or spend range actually present in the fitted data
  for a (market, channel), typed (`MediaInputSupport`/`MonetarySpendSupport`) and never
  derived from a saturation parameter (Hill K is not observed support).
- **Planning support** — a distinct, separately governed range describing what input values
  are considered eligible for planning/optimisation use, which may differ from observed
  support and must not silently inherit it without being explicitly recorded as having done
  so.

## Single source of authority

The repository has one authoritative calculation path for producing new official response
curves: `core.canonical_curves.generate_canonical_curve_draws` (and its aggregation/summary
functions), invoked exclusively through a new application-service governance layer (scoped in
PR 93B/93C, not this record). No other function may produce an artifact labelled or persisted
as an official response curve.

`core.curve_bank.CurveBankEntry` and the point-estimate generators
(`core.predict.generate_channel_curve`, `core.market_specific_predict.generate_market_channel_curve`)
remain loadable and usable for their existing purposes (calibration tracking, evidence-tier
display, the current UI's exploratory viewer) but must never be presented as the authoritative
evaluated curve without migration and independent verification against the authoritative path.

## Mathematical contract

Required, and already satisfied by `core.canonical_curves.generate_canonical_curve_draws` as
of this review (this section locks in the existing contract; it does not change it):

```text
incremental_response = mu(selected input, explicit reference context)
                      - mu(counterfactual input, same explicit reference context)
```

- The full outcome-scale prediction function must be used (`mu = exp(eta)`), never a
  log-scale proxy.
- The log-scale media/eta contribution (`beta × pathway_strength × Hill(media input)`,
  stored as `media_eta_contribution`) must be kept separate from, and never presented as, an
  incremental outcome count.
- Draw-level calculation must occur before any posterior summarization
  (`aggregate_curve_draws`/`summarize_curve_draws` consume the draws DataFrame as input; they
  must never precede it).
- Direct, cross-product (halo), and channel-total response must reconcile exactly (component
  rows sum to the channel total by construction, via eta-share allocation) or within an
  explicitly tested, documented tolerance.

Any future change to this mathematical contract is out of scope for this record and requires
its own reviewed requirement.

## Reference-context contract

Every official curve must persist:

```text
market, outcome definition and version, analysis as-of date, model and posterior identity,
other-channel inputs, trend/baseline assumption, seasonality assumption, promotion
assumption, control assumptions, reference period or scenario, counterfactual value and
axis, steady-state or sequential semantics
```

- No implicit zero, historical mean, or unstated default may substitute for an explicit
  reference-context field.
- `core.canonical_curves.CurveReferenceContext` already covers market, trend, Fourier
  seasonality, promotions, controls, outcome controls, other-channel media input,
  counterfactual value/axis, mode, and reference period. Two fields must be added or
  explicitly bound by the new application-service layer, since `CurveReferenceContext` itself
  does not carry them: **model/posterior identity** (currently only a separate
  `model_run_id` argument to `generate_canonical_curve_draws`, not part of the context object
  or its persisted metadata) and an explicit **outcome definition + version** binding
  (currently resolved elsewhere in the pipeline, not stamped onto the reference context).
- Every row must be labelled steady-state or sequential; today this is unconditionally
  `"steady_state"` (see Definitions), which is correct only because sequential does not yet
  exist — this label must remain explicit, not silently hardcoded, once sequential curves are
  introduced.

## Support and extrapolation

Required, separately governed:

```text
observed support, planning support, current input definition, support source,
support period, extrapolation status
```

- Hill K must never be used as observed support (already true; keep true).
- Missing support must not be fabricated (already true — missing support yields `NaN` fields
  and `SUPPORT_MISSING` status, never invented numbers).
- **Gap to close:** missing or incomplete support currently produces `NaN` economics fields
  but does not itself set an explicit "official planning eligibility" flag consumed
  downstream by planning/optimisation gates. The new application-service layer must derive
  and persist an explicit `planning_eligible: bool` (or equivalent) computed from support
  completeness, so that missing support blocks official planning eligibility structurally,
  not only by producing `NaN` values a downstream caller might not check.

## Media-input and monetary rules

- Model-input curves must state their fitted unit (`MediaInputSpec`); `unit_scale` is
  descriptive metadata only — values must already be in the fitted numeric unit.
- Monetary curves must use a governed, market-, channel-, and time-specific cost mapping
  (`core.media_costs.MediaCostMapping`, resolved and validated as effective as of a stated
  date) — already enforced unconditionally by `generate_canonical_curve_draws` in both
  governance modes; this record locks that behavior in as a requirement rather than an
  incidental implementation detail.
- A global spend-scaling factor must never substitute for a channel-specific cost mapping.
- Multi-market or currency-converted curves must persist local currency, reporting currency,
  FX rate, FX source, and FX as-of date — already enforced by `_currency_metadata()`; this
  record locks that behavior in.

## Economics

- Channel cost must be counted exactly once (already true: `incremental_spend` is the
  channel-level total; component allocations are fractions of that same total, never
  additional cost).
- Direct and cross-product response must be combined before any channel-level CPA/ROI is
  computed (already true via component reconciliation to the channel total before
  `_economic_values`).
- No component-level CPA or ROI may be computed without an explicit, approved cost
  allocation (already true — component economics are `ECONOMICS_COMPONENT_COST_UNALLOCATED`
  by default).
- Portfolio marginal economics require an explicit perturbation direction
  (`PortfolioPerturbation.allocation_direction`, sum-to-one, already enforced).
- Average and marginal economics must remain clearly, separately labelled (already true:
  `average_cpa`/`marginal_cpa` are distinct fields with distinct status flags).
- The counterfactual scope (zero vs. nonzero) must be recorded (already true:
  `average_cpa_scope` distinguishes this per `docs/canonical_curves.md`).

## Governance chain

A new official curve must require — not merely optionally accept — and persist matching
evidence for:

```text
ModelIdentity, ModelApproval, ThresholdPolicy, ApprovalReadiness, DiagnosticsArtefact,
approved outcome definition and allowed use, approved activity definitions, pathway
governance, cost mapping (when monetary), currency and FX (when monetary or multi-market),
reference context, support, curve generator version
```

- **Gap to close (the central finding of this record):** as of this review,
  `generate_canonical_curve_draws(governance_mode="official")` does not reference
  `ModelApproval`, `ThresholdPolicy`, `ApprovalReadiness`, or `DiagnosticsArtefact` at all,
  and its one activity-approval check is skipped entirely whenever the caller omits the
  `activity_definitions` argument — the default call produces an "official" curve with no
  activity-governance check performed. **Omitting an optional argument must never bypass an
  official governance gate.** The new application-service layer (PR 93B/93C) must make every
  element of this chain a required input for an official curve, verified before
  `generate_canonical_curve_draws` is invoked, not an optional pass-through.
- Cost mapping and currency/FX are already unconditionally required when applicable (see
  Media-input and monetary rules) — this is the one part of the current chain that already
  meets this bar and must not regress.
- Curve generator version: the current export stamps a module-level schema string
  (`"G2A.2-1"`) and `CurveReferenceContext`/`MediaInputSupport`/`MonetarySpendSupport` each
  carry their own field-level `schema_version`, but no single per-artifact "curve generator
  version" ties calculation logic version to the persisted rows. The new schema (PR 93B) must
  add this.
- Exploratory generation must remain structurally and visibly non-official: the new
  application-service layer must return a distinctly-typed result (or an unambiguous,
  non-optional discriminator field verified by tests, not just a `governance_mode` string a
  caller can ignore) so downstream code cannot mistake an exploratory result for an official
  one by accident.

## Persistence schema

Required for the new official artifact:

- An explicit, per-artifact schema version (not only the current module-level
  `"G2A.2-1"` string).
- JSON-safe metadata (already the pattern used for `CurveReferenceContext` fields that get
  `json.dumps`-serialized before reaching Parquet — extend this pattern consistently).
- Portable draw and summary tables (Parquet, as today, or an equivalent portable format).
- Deterministic fingerprints binding the governance chain to the artifact (extending
  `activity_definitions_fingerprint`/`monetary_governance_fingerprint`, made unconditional
  rather than only-present-when-`activity_rows`-non-empty).
- Migrations and round-trip tests: **gap to close** — `core.canonical_curves` currently has
  no import/round-trip function at all (export-only). The new schema must add one.
- The official artifact must be able to re-prove its evidence chain without relying on
  mutable live session state — i.e., the persisted fingerprints/metadata must be sufficient
  on their own, not dependent on re-querying a live `ModelApproval`/`ThresholdPolicy` object
  that could have since changed.
- Unknown future fields or schema versions must not be silently discarded. **Gap to close:**
  `CurveBankEntry.from_dict()` currently filters to `{f for f in cls.__dataclass_fields__}`
  and silently drops unrecognized keys (`ancestry_mmm/core/curve_bank.py` L115-126) — the new
  official-artifact loader must not repeat this pattern; unknown fields must be preserved or
  the record must be flagged, not quietly truncated.
- Malformed files must produce an audit result, not disappear silently. **Gap to close:**
  `core.curve_bank.load_all_entries()` currently catches
  `(json.JSONDecodeError, KeyError, TypeError)` and `continue`s with no logging, exception, or
  user-visible warning (L433-445). The new official-artifact loader must instead follow the
  repository's own existing pattern in
  `ancestry_mmm/application/validation_service.py::MalformedArtefactEvidenceError` — fail the
  gate closed and surface an auditable result, never a silent skip.

## Legacy migration

- **Pre-Phase-3a run-level curve files** — already correctly expanded and labelled
  `curve_status = CURVE_STATUS_LEGACY` / `legacy_format = True` by
  `curve_bank._expand_legacy_entry()`. This behavior is retained; it must continue to label
  fabricated-default numeric fields (missing values defaulted to `0.0`) as legacy, never as a
  verified estimate.
- **Current `CurveBankEntry` parameter records** — remain loadable and usable for their
  existing purposes (Single source of authority, above); must never be presented as an
  official evaluated curve under this contract.
- **Canonical exports created before the full approval chain exists** (i.e., anything
  produced by `generate_canonical_curve_draws(governance_mode="official")` before PR 93C
  closes the activity-governance-by-omission gap) — must be re-classified, on migration, as
  `legacy_unapproved`, reusing the status value already defined in
  `core.outcome_approval.OUTCOME_APPROVAL_STATUSES` (L104-111), rather than a new bespoke
  label. They must not become "official" through missing-field defaults or through the mere
  fact that `governance_mode="official"` was passed at the time.
- **Saved exploratory curves** — remain loadable and clearly labelled exploratory; never
  auto-promoted to official status by any later change to defaults.

## Publication and use

Separate eligibility must be defined and enforced, per curve, for each use already defined in
`core.outcome_approval.OUTCOME_USES`:

```text
model_fit, technical_reporting, headline_reporting, curve_publication, planning,
optimisation, value_layer, external_distribution
```

A curve being computed does not make it eligible for every use. Official eligibility for each
use must be derived from the governance chain (above), not asserted by the caller. Exploratory
curves are never eligible for any use beyond `model_fit`/`technical_reporting`-style internal
diagnostics without first being regenerated through the authoritative official path.

## Testing requirements (for the follow-on implementation PRs, not this record)

The following future test coverage must be identified by the PR 93B/93C/93D/93E
implementation plans before it is added to `docs/approved_requirements/index.json`'s
`required_tests`. This record deliberately does not create test node IDs for
not-yet-written code, per the requirements-index conformance test
(`ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`),
which requires every listed node to be real and collectable.

Required future coverage areas:

```text
shared model curves; market-specific curves; model-input curves; monetary curves;
multi-market FX; reference contexts; counterfactuals; support and extrapolation;
component reconciliation; channel economics; posterior aggregation;
approval-chain mismatch (official curve blocked when any governance element is missing,
including when activity_definitions is omitted entirely); legacy migration
(legacy_unapproved classification); malformed-file audit (no silent skip);
UI exploratory-vs-official labelling; project export and import (round-trip)
```

## Owner

Product / Analytics + Platform engineering (governance chain implementation)

## Affected modules (future PRs; none changed by this record)

- `ancestry_mmm/core/canonical_curves.py`
- `ancestry_mmm/core/curve_bank.py`
- `ancestry_mmm/core/outcome_approval.py`
- `ancestry_mmm/application/` (new curve application-service module)
- `ancestry_mmm/pages/07_Results_Curve_Bank.py`
- `ancestry_mmm/components/charts.py`

## Human traceability

Derived from the task-specific implementation brief "MMM-Guide Coding LLM Next Steps" (PR 93A
mandate: define the official curve authority and evidence contract), 2026-07-31. Motivated by
the governance gap documented in the maintainer's own description of
`papayasamosa/MMM-Guide#87` (merged 2026-07-30): *"`core.canonical_curves.py`'s separate
`governance_mode="official"` gate (activity/cost-mapping only, no `ModelApproval` binding at
all) is a larger, more ambiguous redesign question ... noted as a remaining limitation, not
addressed here."* Full supporting evidence: `docs/curve_authority_gap_analysis.md`.
