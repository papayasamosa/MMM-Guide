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

Not yet implemented. Target-state contract only.

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

## Affected modules (target)

- `ancestry_mmm/core/diagnostics.py` (extend; `expanding_window_backtest`
  must not be presented as satisfying this contract until extended)
- a new fold-manifest domain object (module TBD at implementation time)
- `docs/approved_requirements/REQ-LEAK-001.md` (new)
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

None. No existing schema, model, or persisted artefact changes as a result
of this record.

## Unresolved decisions

- Fold-manifest schema and storage location (new module vs. extending
  `core.diagnostics`).
- Whether expensive real-fold PyMC recovery runs as schedule/manual CI
  evidence or normal-CI evidence, per the brief's own guidance that this
  should be justified by measured normal-CI runtime.

## Owner

Modelling

## Approval date

2026-08-17
