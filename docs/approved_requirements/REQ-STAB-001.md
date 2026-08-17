# REQ-STAB-001: Structural Stability Evidence Across Time-Respecting Folds

## PRD source

Ancestry MMM PRD Part 6 v1.6 (intro bullet 9, §31.5, §35, §38 AC-27), Part 7
v1.5 (§0.15 intro bullets 2 & 10, §3.10, §13.4, §13.6, §13.7, §31.5, §39
blocking condition #10), and Part 9 v1.5 (§26.5, §26.10, §RP-022) —
reconciled by Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post
PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Depends on `REQ-LEAK-001` for the shared fold-manifest
contract this record's stability comparison runs across.

Current `core.diagnostics`/`core.identification_diagnostics` compute
posterior coefficient variation, condition number, and sensitivity on a
single fit. No module in this repository currently re-estimates a model
across time-respecting historical folds and compares decision-driving
structural quantities across them.

## Capability status

Core contract implemented (Work Package 2 part 2, 2026-08-17):
`ancestry_mmm/core/structural_stability.py` provides `FoldParameterSnapshot`
(one fold's decision-driving parameter point values and, where available,
posterior draws — Requirement 3's "preserve uncertainty per fold"),
`ParameterFoldComparison` (the per-parameter comparison across every fold
that reported it, exposing only a plain descriptive `point_range` — never
a threshold, pass/fail verdict, or materiality judgement), and
`StructuralStabilityArtefact`/`assess_structural_stability` (the
structured, per-parameter comparison across folds, satisfying
Requirement 3's "never one opaque aggregate health score"). A missing
parameter in one fold's snapshot is recorded as an explicit limitation,
never silently dropped or backfilled.

This module does not itself re-fit a model per fold — the caller supplies
each fold's parameter snapshot (a real per-fold re-fit, an injected/fake
extraction for fast contract tests, or another approved method), mirroring
`core.validation_folds`'s own established pattern from Work Package 1 of
"the caller supplies the fold-local computation, this module only
assembles and compares the result". `FoldParameterSnapshot.fold_id` is
intended to match a `core.validation_folds.ValidationFold.fold_id`
(verified by an integration test), satisfying Requirement 6's "the two
records share one notion of what a historical fold is".

Requirement 4 (automatic interpretation of instability — genuine
evolution vs. weak identification vs. data-definition change vs. leakage
artefact vs. misspecification) is explicitly **not** automated by this
module; that judgement remains a human reviewer's, informed by this
evidence.

Not yet wired: `DiagnosticsArtefact`/Diagnostics-page integration. Unlike
`REQ-PPD-001` (which only needs a single existing trace/frame/meta/params
call and could be wired into `DiagnosticsService.evaluate()` today), this
record's evidence structurally requires multiple folds' *already re-
estimated* parameter values as input — and no real per-fold re-estimation
pipeline exists yet in this repository (the same expensive, unresolved
"real-fold PyMC recovery" question `REQ-LEAK-001` already recorded, not
newly introduced here). Wiring an artefact section that can only ever be
populated by a caller manually assembling synthetic snapshots would not
be genuine evidence integration. The schema/UI work for both `REQ-PPD-
001` and this record remains a coherent follow-up once a real multi-fold
re-estimation path exists to feed it.

## Requirement

### 1. Predictive stability and structural stability are separate evidence dimensions

A model must not be described as "stable" merely because its predictive
error is stable across folds. The validation and reporting layers must
distinguish, as separate, independently-computed and independently-reported
evidence:

- predictive-performance stability (out-of-sample metric behaviour across
  folds);
- structural-parameter and effect stability (movement of decision-driving
  quantities across folds).

### 2. Decision-driving quantities in scope

Where historical support permits and the quantity is material to
attribution, curve publication, planning, or optimisation, structural
stability must be assessed for the applicable subset of:

- adstock decay/carryover parameters;
- saturation shape and scale (e.g. Hill K/S) parameters;
- media response coefficients or outcome-scale effects;
- baseline/trend and latent-baseline-state behaviour;
- hierarchy and pooling parameters;
- direct, mediated, halo, and constrained-total effect allocation;
- selected marginal CPA/ROI or incremental-response quantities at governed
  reference points;
- response-curve descriptors.

### 3. Posterior uncertainty is preserved across folds

The fold-to-fold comparison must preserve posterior uncertainty per fold —
it must not reduce each fold to a single point estimate when the posterior
distributions materially overlap or differ. A structured, per-quantity
artefact is required; this record does not approve one opaque aggregate
health score.

### 4. Interpretation, not automatic penalty

Instability across folds does not automatically invalidate every use of the
artefact. The artefact must record the most plausible interpretation
(genuine evolution in response; weak identification; insufficient support;
prior dependence; data-definition change; leakage/preprocessing artefact;
model misspecification) and the resulting permitted-use consequence. A model
may remain reporting-eligible while being restricted from curve publication,
planning, or optimisation when the unstable quantity is material to the
forward-looking use but not to the approved reporting use.

### 5. Reporting separation

The reporting layer must show fold-by-fold or window-by-window posterior
movement for the applicable decision-driving quantities, and must not
present a green predictive-validation gate as implying that structural
stability also passed (`REQ-P9-G03`/`REQ-P9-G04` equivalent contract).

### 6. Schema evolution

Any new `DiagnosticsArtefact` section this record's implementation adds must
follow the repository's existing additive-schema pattern (`REQ-VAL-001`): an
older artefact without this section is marked `not_computed`, never
retroactively fabricated; an unrecognised future schema version fails
closed.

## Explicitly excluded (decision-required, not approved by this record)

- minimum fold support, parameter/effect classes, materiality rules, and
  permitted-use consequences for time-slice structural instability (Part 7
  §48 `VL-022`);
- the default decision-driving parameter/effect classes and plain-language
  status labels shown in reporting (Part 9 §48 `RP-022`);
- any specific numeric instability threshold.

## Affected modules

- `ancestry_mmm/core/structural_stability.py` (new —
  `FoldParameterSnapshot`, `ParameterFoldComparison`,
  `StructuralStabilityArtefact`, `assess_structural_stability`)
- `ancestry_mmm/core/diagnostics.py` (not yet touched — `DiagnosticsArtefact`
  schema extension deferred, see Capability status)
- `ancestry_mmm/pages/06_Diagnostics.py` (not yet wired — deferred)
- `docs/approved_requirements/REQ-STAB-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_structural_stability.py` (18 tests: snapshot/
  comparison/artefact construction and round-trip; a stable parameter
  reporting a near-zero range; a synthetic drifting parameter reporting
  its full range with no threshold applied; independent multi-parameter
  comparison; a missing-parameter-in-one-fold limitation; posterior draws
  preserved per fold rather than reduced to a point; an explicit check
  that no `status`/`verdict`/`pass`/`fail`/`stable`/`unstable` field
  exists in the serialised comparison; and an integration test proving
  fold IDs from `core.validation_folds.build_expanding_window_folds` flow
  through unchanged)
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None yet. `core.structural_stability` is a new, additive module with no
persisted artefact today; `DiagnosticsArtefact` is not yet touched.

## Unresolved decisions

- Whether real-fold PyMC re-estimation for structural-stability evidence
  runs in normal CI or is schedule/manual evidence (cost-dependent;
  measure before deciding) — unchanged from `REQ-LEAK-001`'s own open
  question; not resolved by this record either.
- `DiagnosticsArtefact`/Diagnostics-page schema and UI wiring for both
  this record and `REQ-PPD-001` — deferred until a real multi-fold
  re-estimation pipeline exists to supply genuine `FoldParameterSnapshot`
  evidence (see Capability status).
- The minimum fold-support, parameter/effect classes, materiality rules,
  and permitted-use consequences for time-slice structural instability
  remain Part 7 `VL-022`'s open decision, not approved here.

## Owner

Modelling

## Approval date

2026-08-17
