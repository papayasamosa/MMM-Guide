# REQ-LEAK-001: Leakage-Safe, Time-Respecting Historical Validation Folds

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-MOD-013`, `FR-VAL-014`, `FR-VAL-015`,
§26.7, §30), Part 6 v1.6 (§31.5, intro bullet 3, §35), and Part 7 v1.5 (§0.15
intro bullet 3, §3.11, §13.1, §13.4, §13.5 "Fold-local reconstruction and
leakage prevention", §39 blocking condition #11) — the coherent set of PRD
parts reconciled by Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps
Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17), per this repository's standard authority hierarchy. This
record translates the PRD's leakage-safety contract into a scoped repository
requirement; it does not itself implement the contract.

`core.diagnostics.expanding_window_backtest` already exists and performs a
date-sliced train/test split with a caller-supplied `fit_fold_fn`. It does
not itself reconstruct fold-local source vintages, publication lag,
preprocessing, or scaling — this record's contract is materially stronger
than that helper's current behaviour, and the helper must not be presented
as satisfying it merely because it performs a temporal split. No code in
this repository currently claims to satisfy the contract below.

## Capability status

Core contract implemented (Work Package 1, 2026-08-17):
`ancestry_mmm/core/validation_folds.py` provides `ValidationFold` (typed,
versioned fold manifest satisfying Requirement 1), `build_expanding_
window_folds` (the same boundary arithmetic `expanding_window_backtest`
uses internally, extracted into inspectable fold objects),
`assess_fold_source_reconstruction` (per-variable leakage assessment
against a `core.coverage.VariableCoverageMatrix`, reusing `core.
frequency_alignment.check_publication_leakage`/`check_definition_break_
crossing` rather than a second leakage-detection mechanism — satisfies
Requirements 2-4), and `leakage_safe_expanding_window_backtest` (refuses
to call `fit_fold_fn` for a fold whose assessment did not clear —
satisfies Requirement 3/5's "provable, not assumed" and "time-respecting,
never random-split" invariants).

`information_cutoff` defaults to a fold's own `train_end` — the
leakage-safe semantic requires asking "what was knowable exactly at the
end of this fold's training window", not "what do we know today with
every subsequent revision". A caller with a genuine point-in-time vintage
source may supply a different, later `information_cutoff` explicitly.

What this assessment can verify today is bounded by what `Variable
CoverageMatrix` metadata records: effective periods, publication lag,
definition breaks, and coverage-segment ambiguity (`unavailable_source`/
`unknown` states overlapping a fold's training window are reported as a
`cannot_verify` limitation, never silently treated as safe). It does
**not** yet rebuild the full model-ready `frame`/scaling/mixed-frequency
pipeline per fold from raw sources (Requirement 2's "scaling fit on
training data only", "lag/adstock/state initialisation" items remain a
contract for a future real-model-integration pass, not verified by
metadata alone) — this is recorded as an explicit remaining scope, not
silently claimed as done. `core.diagnostics.expanding_window_backtest`
itself is unchanged and still carries no leakage-safety claim.

Real-fold PyMC re-fitting now exists (Work Package 1 part 1 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #284`, 2026-08-18):
`ancestry_mmm/application/fold_refit_service.py::run_leakage_safe_fold_
refit` reimplements this module's own `build_expanding_window_folds`
+ `assess_fold_source_reconstruction` selection loop (so it fits only
folds this record's assessment already cleared) and, for each cleared
fold, calls the real production fit sequence exactly once — never a
fake `fit_fold_fn`. A tiny (draws=15/tune=15) fit runs in blocking CI
(`test_fold_refit_service.py`); a moderate (draws=200/tune=200) fit runs
schedule/manual-only (`test_fold_refit_service_recovery.py`, mirroring
`candidate-a-recovery`) — this record's own "measure before deciding
normal-CI vs. schedule/manual" open question is resolved operationally by
this split, not by a single all-or-nothing choice.

Still not wired: `DiagnosticsArtefact`/Diagnostics-page integration
(deferred so Work Package 2's structural-stability evidence — which
Requirement 6 says must share these same fold manifests — is designed
into the same schema/UI addition once, not twice); point-in-time
reconstruction of the raw source data itself (Work Package 1 part 2,
undelivered — `run_leakage_safe_fold_refit` still fits plain date-sliced
rows of a single already-prepared dataframe, exactly `leakage_safe_
expanding_window_backtest`'s own existing limitation; it does not select
a source *version* as of the fold's cutoff or re-run `core.
official_preparation`/`core.frequency_conversion` fold-locally from raw
sources — Requirement 2's "scaling fit on training data only" remains
moot regardless, since no scaler exists anywhere in the production path).

## Requirement

### 1. Fold as a first-class versioned object

A historical validation fold must be represented by a typed, versioned fold
manifest — not an ad hoc date slice computed inline — recording at minimum:

- fold ID and fold-manifest version;
- train window and test window (canonical-calendar week boundaries);
- the fold's information cut-off (the point-in-time boundary beyond which no
  information may be used);
- the model specification, outcome, and market/product/segment scope the
  fold applies to.

### 2. Fold-local reconstruction

For every historical fold, where the corresponding choice could otherwise
leak future information, the fold must reconstruct — using only information
that would have been available at its information cut-off — each of:

- source versions and revision vintages;
- publication lags and source availability;
- variable coverage/effective periods and missingness state (distinguishing
  observed-zero, missing, not-applicable, unavailable, and structural zero,
  consistent with `core.coverage`);
- scaling, normalisation, and other preprocessing state (any scaler or
  normaliser must be fit on the fold's training data only);
- native-frequency-to-model-frequency transformations and mixed-frequency
  alignment (`core.frequency_alignment`, `core.frequency_conversion`);
- effective-dated business definitions and mappings (cost mappings, activity
  definitions) in force at the cut-off;
- lag/adstock/state initialisation that depends on historical availability.

### 3. Leakage-safety is provable, not assumed

The validation system must retain enough metadata about each fold's
reconstruction to demonstrate that later source revisions, future outcome
values, or future-derived preprocessing statistics did not enter that fold.
A fold produced by a naive date slice with no such metadata must not be
labelled leakage-safe.

### 4. Explicit limitation when full reconstruction is impossible

If exact historical reconstruction is impossible for a fold — for example
because a source does not retain revision vintages — the limitation must be
recorded on the fold's own record, and that fold's validation result must
not be presented as fully leakage-safe.

### 5. Random row-level splitting is not a valid substitute

A time-series MMM validation fold must be time-respecting (rolling-origin,
blocked holdout, event holdout, or another approved time-respecting design).
Random row-level splitting must not be used to produce an artefact labelled
as a leakage-safe historical fold.

### 6. Separation from structural-stability use

A fold manifest produced under this record is the shared input consumed by
both predictive validation (this record) and structural-stability assessment
(`REQ-STAB-001`) — the two must not each derive their own, potentially
divergent, notion of what a historical fold reconstructed.

## Explicitly excluded (decision-required, not approved by this record)

The following remain open per the PRD's own decision registers and must not
be hard-coded from this record:

- the minimum source-vintage, publication-lag, and preprocessing evidence
  required to describe a fold as leakage-safe (Part 7 §48 `VL-023`);
- holdout design, horizon, and event/cap-state coverage requirements
  (Part 7 §48 `VL-002`);
- any specific numeric tolerance for fold-level reconciliation checks.

## Affected modules

- `ancestry_mmm/core/validation_folds.py` (`ValidationFold`,
  `VariableReconstructionAssessment`, `FoldReconstructionAssessment`,
  `build_expanding_window_folds`, `assess_fold_source_reconstruction`,
  `leakage_safe_expanding_window_backtest`)
- `ancestry_mmm/application/fold_refit_service.py` (new, Work Package 1
  part 1 — `fit_fold_with_real_model`, `run_leakage_safe_fold_refit`, the
  first real per-fold PyMC refit this record's contract ever drove)
- `ancestry_mmm/core/diagnostics.py` (unchanged — `expanding_window_
  backtest` remains a plain date-sliced backtest with no leakage-safety
  claim; verified by `TestLeakageSafeExpandingWindowBacktest::
  test_does_not_mutate_expanding_window_backtest`)
- `docs/approved_requirements/REQ-LEAK-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_validation_folds.py` (30 tests: fold
  construction/validation, fold-boundary and no-future-leakage-in-split
  blocking tests, per-variable leakage assessment across every status —
  safe, not-yet-effective, publication-lag risk, definition-break
  crossing, cannot-verify — and the key blocking test that a fold failing
  assessment never calls `fit_fold_fn`)
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_fold_refit_service.py` (blocking CI: real,
  tiny fit driven through this record's own leakage-safe fold selection
  loop, including the unsafe-fold-never-fit path)
- `ancestry_mmm/tests/test_fold_refit_service_recovery.py` (schedule/
  manual-only, run by the `fold-refit-recovery` CI job — Model C,
  the single-market fallback path, and two real fits)

## Migration impact

None. `core.validation_folds` and `application.fold_refit_service` are
additive modules with no persisted artefact today; no existing schema,
model, or persisted artefact changes.

## Unresolved decisions

- The minimum source-vintage/publication-lag/preprocessing evidence
  required to describe a fold as leakage-safe *for production use* (Part
  7 §48 `VL-023`) — this record reports what it can verify and what it
  cannot; the production threshold policy remains a separate decision.
- Whether/how to rebuild the full model-ready `frame`/scaling/mixed-
  frequency pipeline per fold from raw sources, beyond what `Variable
  CoverageMatrix` metadata can verify — Work Package 1 part 1 delivered
  real per-fold model refitting; point-in-time raw-source reconstruction
  (selecting a source *version* as of the fold's cutoff, fold-local
  `core.official_preparation`/`core.frequency_conversion` re-execution)
  remains undelivered (Work Package 1 part 2).
- `DiagnosticsArtefact`/Diagnostics-page schema and UI wiring — deferred
  to be designed jointly with Work Package 2's structural-stability
  evidence (Requirement 6), not built twice.
- Whether expensive real-fold PyMC recovery runs as schedule/manual CI
  evidence or normal-CI evidence — resolved operationally by Work
  Package 1 part 1's split: a tiny fit in blocking CI, a moderate fit
  schedule/manual-only (see Capability status).

## Owner

Modelling

## Approval date

2026-08-17
