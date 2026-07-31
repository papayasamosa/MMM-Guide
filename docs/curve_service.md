# Official curve authority service (PR 93B, REQ-CURVE-001)

`ancestry_mmm.application.curve_service` is the one path in this repository
that may label a response curve *official*. It does not change how curves
are calculated — `core.canonical_curves.generate_canonical_curve_draws`
remains the single calculation source of truth, unchanged by this module,
and it remains directly callable, ungated, for exploratory use. What this
module adds is the governance layer REQ-CURVE-001 requires around that
calculation before an artifact may be treated as official.

`core.curve_bank.CurveBankEntry` and the current Streamlit UI
(`07_Results_Curve_Bank.py`) are untouched by this module. Migrating them is
separate, later, approved work (PR 93C/93D/93E) — see
`docs/curve_authority_gap_analysis.md` section 7.

## Why a new module, not a patch to `canonical_curves.py`

`generate_canonical_curve_draws(governance_mode="official")`'s one governance
check (approved `ActivityDefinition`s for a monetary curve) is only run when
the caller supplies `activity_definitions` — omitting that optional argument
silently skips it. That is the exact defect REQ-CURVE-001 documents. Rather
than patch that function's optional-argument shape (which every existing
caller, including this repository's own tests, would then have to migrate
in lockstep), `CurveService` adds a governance-enforcing layer in front of
it whose own parameters are *not* optional:

- `CurveGovernanceEvidence` — every field required (`ModelIdentity`,
  `ModelApproval`, `ThresholdPolicy`, `ApprovalReadiness`,
  `DiagnosticsArtefact`, `OutcomeDefinition`, `OutcomeApproval`,
  `ActivityDefinition`s). Omitting any one of them is a `TypeError` at
  construction, not a silently-skipped check.
- `CurveService.generate_official_curve(evidence=..., **draw_kwargs)` —
  validates the full chain (reusing existing hard-gate primitives:
  `require_matching_approval`, `readiness_matches_current_evidence`,
  `require_outcome_approval`, `activity_by_model_input`) before calling
  `generate_canonical_curve_draws(governance_mode="official",
  activity_definitions=...)` itself. The activity-approval check is now
  unconditional for every (market, channel) in scope — not scoped only to
  monetary curves the way `canonical_curves.py`'s own check is, and not
  skippable by omission.
- `CurveService.generate_exploratory_curve(**draw_kwargs)` — no governance
  evidence accepted at all, returns `ExploratoryCurveResult`, a distinct
  type from `OfficialCurveArtifact` a caller cannot mistake for an official
  result.

## Persisted artifact

`OfficialCurveArtifact` wraps the draws/summaries DataFrames plus:

- `governance_chain_fingerprint` — a single fingerprint binding model
  identity, approval, policy, readiness, diagnostics, outcome approval, and
  activity-definitions evidence together.
- `planning_eligible: Dict[(market, channel), bool]` — derived from the
  draws' existing, never-fabricated `planning_support_eligible` column
  (itself `observed_support_status == SUPPORT_AVAILABLE`); missing support
  makes a (market, channel) ineligible, never silently eligible.
- `curve_generator_version` and `schema_version` — an explicit, per-artifact
  version, distinct from `canonical_curves.py`'s own module-level export
  schema string.

`export_curve_artifact`/`import_curve_artifact`/`load_all_curve_artifacts`
persist this as `official_curve_draws.parquet` +
`official_curve_summaries.parquet` + `official_curve_manifest.json` per
artifact directory:

- A manifest declaring a newer `schema_version` than this code supports is
  rejected cleanly (`ValueError`), not guessed at.
- A missing/corrupt file raises `MalformedCurveArtifactError` — never a
  silent skip (contrast with `core.curve_bank.load_all_entries()`).
- Unknown manifest fields are preserved through import/export, never
  filtered out the way `CurveBankEntry.from_dict()` filters to known
  dataclass fields.
- `load_all_curve_artifacts` returns `(artifacts, audit_entries)` — every
  malformed file becomes an audit finding, not a disappearance.

## What this PR does not do

No change to `canonical_curves.py`, `curve_bank.py`, `outcome_approval.py`,
`activities.py`, `approval.py`, `validation_policy.py`, `media_costs.py`, or
any Streamlit page. Nothing in this repository currently calls
`CurveService` — wiring it into UI/optimisation/export paths is later,
separately-approved work.
