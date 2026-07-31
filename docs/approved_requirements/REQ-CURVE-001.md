# REQ-CURVE-001: Official response curve authority and evidence contract

**Status:** approved for implementation (approved 2026-07-31 via PR 94B).
**Decision date:** approved 2026-07-31.
**Revision history:**
- PR 93A created this record as a draft (merged as PR #93, commit `877add6`).
- PR 94A corrected the draft in response to the five post-merge review findings on
  `papayasamosa/MMM-Guide#93` and additional defects identified during re-review (merged as
  PR #95, commit `ccd0dcf`); the record stayed `draft` through PR 94A.
- PR 94B (this record) records the approval of the corrected requirement and of the human
  decisions in the "Approved decisions" section, and registers the currently-implemented
  acceptance tests in `docs/approved_requirements/index.json`.

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
  (Governance chain, below) **and a current, matching outcome approval for
  `curve_publication`** (`core.outcome_approval.OUTCOME_USES`, verified against the current
  live approval state at the time of creation and revalidated at every later official use).
  Being eligible for a diagnostic or fitting use (`model_fit`, `technical_reporting`) does
  **not** make a curve official; official status is a distinct, separately granted property
  that is never implied by a diagnostic use alone. Every downstream use
  (`headline_reporting`, `planning`, `optimisation`, `external_distribution`,
  `technical_reporting`) remains independently gated and is never granted automatically by
  `curve_publication`.
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
  (`component_type`), allocated to components by a **named, versioned, persisted, and tested
  component-allocation convention** (the current implementation uses incremental-eta share;
  see `component_response_allocation_method="incremental_eta_share"` in
  `core.canonical_curves`). Under a nonlinear inverse link, eta-share allocation is a
  reconciliation convention, not a uniquely identified causal decomposition of outcome-scale
  response; component rows must never be described as uniquely identified causal direct or
  halo effects. A component curve reconciles back to the channel-total curve under the
  approved convention and carries no cost/CPA/ROI unless an explicit
  `ComponentCostAllocation` exists.
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
  governed-future-assumptions work named in the task brief (PR 96A/96B). Defined here only so
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
follow-on PR 95A/95B, not this record). No other function may produce an artifact labelled or
persisted as an official response curve.

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

- **General rule:** business response must be calculated through the fitted model's
  **approved inverse link** — the full outcome-scale prediction function — never a log-scale
  proxy. The rule is stated in terms of the approved inverse link so that it remains
  outcome-agnostic; it must not hard-code one model family's link as a permanent
  cross-model invariant.
- **Current model family (not a permanent invariant):** the fitted count models use a log
  link, so for them the approved inverse link is `mu = exp(eta)`. Any future approved outcome
  model with a different link uses its own approved inverse link; this record does not
  authorise one and does not treat `exp` as universal.
- The log-scale media/eta contribution (`beta × pathway_strength × Hill(media input)`,
  stored as `media_eta_contribution`) must be kept separate from, and never presented as, an
  incremental outcome count, for every link.
- Draw-level calculation must occur before any posterior summarization
  (`aggregate_curve_draws`/`summarize_curve_draws` consume the draws DataFrame as input; they
  must never precede it).
- Direct, cross-product (halo), and channel-total response must reconcile exactly under the
  approved, versioned component-allocation convention (currently incremental-eta share; see
  Definitions) or within an explicitly tested, documented tolerance. Reconciliation under
  the convention is not, by itself, a claim of a unique causal decomposition of
  outcome-scale response.

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
- **Corrected current-state claim:** `core.canonical_curves.CurveReferenceContext` carries
  market, trend, Fourier seasonality, promotions, controls, outcome controls, other-channel
  media input, counterfactual value/axis, mode, and reference period, and its
  `__post_init__` validates the *values that are present* (finite, non-negative, enum
  checks). It does **not** verify that every fitted promotion, common-control,
  outcome-control, Fourier, market, and other-channel input is represented — an empty or
  partial mapping is accepted, and `steady_state_outcome_response`
  (`core.predict`, L425-488) silently substitutes defaults (`trend→1.0`,
  `fourier→zeros`, `promo→0.0`, `controls→0.0`, `outcome_controls→0.0`) for missing keys.
  The existence of the context class is therefore **not** complete reference-context
  coverage; completeness is a separate, required validation (below).
- **Draft proposed requirement (complete coverage):**
  1. The official application service must validate reference-context keys against the exact
     fitted model metadata and parameter structure before any official curve is generated.
  2. Every fitted promotion, common control, outcome-specific control, Fourier term, market,
     and other-channel input must be covered by the reference context.
  3. A zero is allowed only when it is explicitly persisted as a governed value or covered by
     an explicitly governed omission policy — never as the by-product of a silent
     `.get(key, 0.0)` default.
  4. Missing keys must fail closed before curve generation.
  5. Extra unknown keys must fail or be surfaced as a schema mismatch, not silently ignored.
  6. Context fingerprints must bind both key names and values (a context with the same values
     under a different key set is a different context).
  7. Future acceptance tests must cover missing, extra, partial, and explicitly-zero context
     values (see Testing requirements).
- Two fields must be added or explicitly bound by the new application-service layer, since
  `CurveReferenceContext` itself does not carry them: **model/posterior identity** (currently
  only a separate `model_run_id` argument to `generate_canonical_curve_draws`, not part of
  the context object or its persisted metadata) and an explicit **outcome definition +
  version** binding (currently resolved elsewhere in the pipeline, not stamped onto the
  reference context).
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
- **Current implemented behaviour (corrected from the PR 93A draft):** a planning-support
  flag **already exists**. Every canonical draw row already carries
  `planning_support_eligible` (computed as `observed_support_status == SUPPORT_AVAILABLE`)
  and `planning_blocked_reason` (`""` when eligible, else `"observed_support_missing"`); the
  repository's own `test_missing_support_is_unknown_and_blocks_planning`
  (`ancestry_mmm/tests/test_canonical_curves.py`) verifies that missing support makes the
  field false. Missing support therefore does **not** need a new flag.
- **Known implementation gap (the real gap):** downstream enforcement is incomplete — no
  planning or optimisation consumer currently reads `planning_support_eligible`/
  `planning_blocked_reason`. The official application service and every planning and
  optimisation consumer must enforce the existing `planning_support_eligible` value, and
  must require a non-empty `planning_blocked_reason` whenever eligibility is false.
- **Draft proposed requirement:** do **not** introduce a duplicate `planning_eligible` field
  (or equivalent) unless a later approved migration explicitly replaces the existing
  contract. Aggregation and persistence must preserve the strictest eligibility state across
  component rows and posterior draws (any row/draw ineligible ⇒ aggregated result
  ineligible).

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
- **Channel-total economics remain authoritative** regardless of whether a component
  allocation convention is available. Component allocation is a reporting decomposition and
  must never substitute for, or override, channel-total counterfactual response and
  channel-level CPA/ROI. A separate approved method (and separate approval) is required
  before any component row may be labelled a causal direct, indirect, mediated, or
  constrained effect.

## Governance chain

A new official curve must require — not merely optionally accept — and persist matching
evidence for:

```text
ModelIdentity, ModelApproval, ThresholdPolicy, ApprovalReadiness, DiagnosticsArtefact,
approved outcome definition and a current, matching outcome approval for curve_publication,
approved activity definitions, pathway governance, cost mapping (when monetary), currency
and FX (when monetary or multi-market), reference context, support, curve generator version
```

- **Official status requires `curve_publication`:** an artifact may be classified as an
  official response curve only when there is a current, matching outcome approval for
  `curve_publication` (active, fingerprint-matching, in scope, and valid as a record),
  verified at creation time against the live approval state and revalidated at every later
  official use. `model_fit` or `technical_reporting` approval alone never creates official
  status, because those uses cover fitting and diagnostic evidence, not publication
  authority.
- **`curve_publication` is not a proxy for downstream use:** it authorises the artifact's
  existence and publication as an official curve; it does **not** automatically grant
  `planning`, `optimisation`, `headline_reporting`, or `external_distribution`. Each of
  those uses remains independently gated on its own current, matching approval and any
  additional governance the use requires.
- **Gap to close (the central finding of this record):** as of this review,
  `generate_canonical_curve_draws(governance_mode="official")` does not reference
  `ModelApproval`, `ThresholdPolicy`, `ApprovalReadiness`, or `DiagnosticsArtefact` at all,
  and its one activity-approval check is skipped entirely whenever the caller omits the
  `activity_definitions` argument — the default call produces an "official" curve with no
  activity-governance check performed. **Omitting an optional argument must never bypass an
  official governance gate.** The new application-service layer (follow-on PR 95A/95B) must
  make every element of this chain a required input for an official curve, verified before
  `generate_canonical_curve_draws` is invoked, not an optional pass-through.
- Cost mapping and currency/FX are already unconditionally required when applicable (see
  Media-input and monetary rules) — this is the one part of the current chain that already
  meets this bar and must not regress.
- Curve generator version: the current export stamps a module-level schema string
  (`"G2A.2-1"`) and `CurveReferenceContext`/`MediaInputSupport`/`MonetarySpendSupport` each
  carry their own field-level `schema_version`, but no single per-artifact "curve generator
  version" ties calculation logic version to the persisted rows. The new schema (PR 95A) must
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
- **Historical artifact integrity (reproducibility):** the persisted artifact must carry
  immutable evidence proving what was true when it was created — see "Historical artifact
  integrity and current official-use authorization" below. This makes the artifact
  reproducible without re-querying mutable live session state.
- **Current official-use authorization is separate:** historical integrity is not proof that
  the artifact is currently authorised. At every later official use, the system must
  revalidate the artifact against current governance state (current threshold policy,
  current outcome approval for the requested use, current activity approval, current
  staleness, revocation/expiry, and the requested reporting/planning/optimisation/
  distribution use). A historically valid artifact may become stale, expired, revoked, or
  ineligible for a specific use.
- Context fingerprints must bind both key names and values (see Reference-context contract).
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

## Historical artifact integrity and current official-use authorization

Two distinct validations are required. They answer different questions and neither implies
or rewrites the other.

### Historical artifact integrity (reproducibility)

The persisted artifact must contain immutable evidence proving what was true **when it was
created**:

```text
model identity
approval snapshot and fingerprint
threshold-policy snapshot and fingerprint
readiness snapshot and fingerprint
diagnostics snapshot and fingerprint
outcome definition and approval snapshot
activity and pathway governance snapshot
context, support, cost, currency, and generator versions
creation timestamp
```

This is what makes the artifact re-provable without consulting mutable live session state. It
is necessary for historical reproducibility and auditing.

### Current official-use authorization

At every later official use, the system must also validate the artifact against **current**
governance state, including:

```text
current threshold policy
current outcome approval and the requested use
current activity approval
current model or artifact staleness rules
current revocation or expiry state
requested reporting, planning, optimisation, or distribution use
```

The existing repository pattern for current-use outcome validation is
`core.outcome_approval` (`is_active`, `require_outcome_approval`,
`find_matching_outcome_approval`) and `core.approval.require_matching_approval` for
model-level approval/readiness/policy binding; the official service must apply the same
live-state discipline to curve artifacts.

### Rules

1. Historical integrity does not imply current authorization.
2. Current authorization does not rewrite historical evidence.
3. A historically valid artifact may become stale, expired, revoked, or ineligible for a
   specific use.
4. The use-time gate must fail closed when current governance cannot be resolved.
5. Persist both creation-time evidence status and current-use status as separate concepts
   (see Artifact status and lifecycle).

## Artifact status and lifecycle (separate from outcome-approval status)

**Current implemented behaviour:** `legacy_unapproved` is a value of
`OUTCOME_APPROVAL_STATUSES` (`core.outcome_approval`, L104-111) and describes the status of an
*outcome approval record* (e.g. created by `legacy_unapproved_approval()` on legacy bundle
import). The curve-bank side labels pre-Phase-3a run-level files with `curve_status =
CURVE_STATUS_LEGACY` / `legacy_format = True`, which is a curve-format/evidence label, not an
outcome-approval status.

**Draft proposed requirement (do not conflate the two vocabularies):**

1. Do not assume an outcome-approval status (such as `legacy_unapproved`) is automatically the
   correct artifact-lifecycle vocabulary. Artifact status and outcome-approval status are
   separate concepts and must not be collapsed into one enum.
2. Define or propose separate, explicitly named concepts for:
   - **artifact format and migration status** — e.g. legacy format, current schema version,
     migrated;
   - **historical evidence integrity** — the immutable creation-time snapshot is complete
     and internally consistent (see "Historical artifact integrity and current official-use
     authorization");
   - **current authorization status** — whether the artifact is currently authorised for
     official use against live governance (may be authorised, stale, expired, revoked,
     ineligible);
   - **requested-use eligibility** — the specific use (reporting, planning, optimisation,
     distribution) currently being requested.
3. The exact artifact-status vocabulary requires human approval before implementation; this
   record stays draft on this point until then.
4. This PR does **not** add a new production status enum. It only records the required
   separation.
5. Legacy bundle loadability must be preserved: pre-existing `CurveBankEntry` parameter
   records and pre-Phase-3a run-level curve files remain loadable and usable for their
   existing purposes, and canonical exports created before the full approval chain exists must
   never become "official" through missing-field defaults or through the mere fact that
   `governance_mode="official"` was passed at the time.

## Publication and use

Eligibility must be defined and enforced separately for each use already defined in
`core.outcome_approval.OUTCOME_USES`:

```text
model_fit, technical_reporting, headline_reporting, curve_publication, planning,
optimisation, value_layer, external_distribution
```

- **Official status requires `curve_publication`.** An artifact is classified as an official
  response curve only with a current, matching outcome approval for `curve_publication`
  (see Governance chain).
- **Every downstream use stays independently gated.** `headline_reporting`, `planning`,
  `optimisation`, `external_distribution`, and `technical_reporting` each require their own
  current, matching approval for that specific use, plus any additional governance that use
  requires. `curve_publication` must not automatically grant `planning` or `optimisation`
  (or any other downstream use).
- **Diagnostic uses never create official status.** `model_fit` or `technical_reporting`
  approval alone does not make a curve official.
- **Exploratory and diagnostic rendering remains separately allowed** where the existing use
  policy permits it (e.g. `model_fit`/`technical_reporting`-style internal diagnostics).
  Exploratory curves are never eligible for `curve_publication`, `headline_reporting`,
  `planning`, `optimisation`, `value_layer`, or `external_distribution` without first being
  regenerated through the authoritative official path.
- A curve being computed does not make it eligible for any use. Eligibility is derived from
  the governance chain (above), not asserted by the caller.

## Testing requirements

**Registered now (PR 94B):** the currently-implemented invariant tests that REQ-CURVE-001
locks in are registered in `docs/approved_requirements/index.json`'s `required_tests` (see
the index entry). These are real, collectable nodes in `ancestry_mmm/tests/test_canonical_curves.py`.

**Future coverage (must not be registered until the code exists):** the acceptance tests for
not-yet-written code (official artifact schema, CurveService, complete reference-context
validation, `planning_support_eligible` downstream enforcement, current-use revalidation,
etc.) must be created by the PR 95A-95F implementation plans and only then added to
`docs/approved_requirements/index.json`'s `required_tests`. This record deliberately does
not create test node IDs for not-yet-written code, per the requirements-index conformance
test
(`ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`),
which requires every listed node to be real and collectable.

Required future coverage areas:

```text
shared model curves; market-specific curves; model-input curves; monetary curves;
multi-market FX; reference contexts (including missing, extra, partial, and explicitly-zero
context values — acceptance tests required by the Reference-context contract);
counterfactuals; support and extrapolation; planning_support_eligible downstream enforcement
(planning/optimisation consumers blocked when eligibility is false, with a non-empty
planning_blocked_reason; aggregation/persistence preserving the strictest eligibility state);
component reconciliation under the approved allocation convention; channel economics;
posterior aggregation; approval-chain mismatch (official curve blocked when any governance
element is missing, including when activity_definitions is omitted entirely and when a
curve_publication approval is missing or stale); current-use revalidation (a historically
valid artifact blocked once current governance is stale/expired/revoked); historical
artifact-integrity round-trip; artifact status and outcome-approval status kept separate;
malformed-file audit (no silent skip); UI exploratory-vs-official labelling; project export
and import (round-trip)
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

PR 94A (this record) revises this draft to address the five review findings added to
`papayasamosa/MMM-Guide#93` after its merge (official status requires `curve_publication`;
approved inverse link rather than universal `exp`; complete reference-context coverage;
reuse of the existing `planning_support_eligible` field; separation of historical
reproducibility from current-use authorization) and the additional defects identified during
re-review (eta-share allocation is a versioned convention, not a unique causal decomposition;
artifact status is separate from outcome-approval status; overstated current-state claims
corrected). This revision is a correction of the draft, not an approval.

PR 94B (this record) records the approval of the corrected requirement and the approved
decisions below (2026-07-31) and registers the currently-implemented acceptance tests in the
requirements index. Approval does not change any substantive content of the PR 94A corrected
draft; it authorises the follow-on implementation work (PR 95A-95F, then 96A/96B, 97A).

## Approved decisions

Approved 2026-07-31 via PR 94B. The decisions follow the positions recorded in the PR 94A
corrected draft; each is recorded here for traceability.

1. **`curve_publication` is mandatory for official artifact status.** Official status
   requires a current, matching outcome approval for `curve_publication`; downstream uses
   (headline reporting, planning, optimisation, external distribution, technical reporting)
   stay separately gated; `model_fit`/`technical_reporting` alone never create official
   status; exploratory/diagnostic rendering remains allowed per the existing use policy.
2. **Option B remains the preferred architecture** (`docs/curve_authority_gap_analysis.md`):
   `CurveBankEntry` remains a fitted-parameter snapshot registry; a separate canonical
   evaluated artifact becomes the official curve.
3. **Component-allocation convention:** incremental-eta share
   (`component_response_allocation_method="incremental_eta_share"`) is approved as the
   current **reporting decomposition convention** — named, versioned, persisted, and tested
   — and is **not** labelled a unique causal decomposition. Channel-total economics remain
   authoritative. A separate approved method (and separate approval) is still required before
   any component row may be labelled a causal direct, indirect, mediated, or constrained
   effect. Shapley and explicit-counterfactual component decompositions remain available as
   future alternatives, each requiring its own approval.
4. **Artifact lifecycle / current-use status vocabulary** (Work package G): four separate
   concepts — artifact format and migration status; historical evidence integrity; current
   authorization status; requested-use eligibility — kept distinct from
   `OUTCOME_APPROVAL_STATUSES`. No production status enum is added by this record; the
   vocabulary is realised by the follow-on implementation (PR 95D) against these concepts.
5. **Exploratory monetary curves always require approved cost mappings.** A monetary curve
   — official or exploratory — requires a resolved, effective `MediaCostMapping`;
   explicitly labelled draft cost assumptions are not used for monetary curves.
6. **Revalidation scope:** every official use (reporting, planning, optimisation,
   distribution) is revalidated against current governance at the time of use. Historical
   exports remain loadable and viewable after approval expiry/revocation but are clearly
   labelled not-current/stale and are never eligible for official use without revalidation.
