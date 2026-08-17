# REQ-CALIB-001: Calibrated-Versus-Uncalibrated Model Comparison

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-EXP-006`, `FR-EXP-008`, §26.15), Part 6
v1.6 (intro bullet 8, §22.6), Part 7 v1.5 (§0.15 intro bullet 8, §28.5–§28.6,
§39 blocking condition #15, §48 `VL-025`), Part 9 v1.5 (§24.3, §24.4,
§RP-023), and Part 10 v1.6 (`FCH-07`, §24.5, §24.7, §23.9) — reconciled by
Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Depends on `REQ-EXPMODE-001` (an experiment must already
declare a `likelihood_calibration` or `prior_calibration` evidence mode
before this record's comparison becomes relevant).

No calibration mechanism exists in this repository yet; this record governs
the comparison contract that must exist before any future calibration
mechanism may become official.

## Capability status

Not yet implemented. Target-state contract only.

## Requirement

### 1. Calibration produces a new immutable model identity

Any calibrated model is a new, separately versioned model/spec/run — never
an in-place mutation of the model it was calibrated from. The uncalibrated
model must remain an immutable, audit-visible comparison artefact, following
the same immutability pattern already established for `CausalGraph`
versions (`REQ-GRAPH-001` §2) and validation policies (`REQ-VAL-001`).

### 2. Comparison is required before official use

Before a calibrated model may be approved for reporting, curves, planning,
or optimisation, the system must compare the calibrated and uncalibrated
models on, as applicable: posterior predictive performance; historical
holdout performance; agreement with each compatible experiment; media/
structural parameters and effects; adstock and saturation; baseline
behaviour; hierarchy parameters; posterior uncertainty; response curves;
selected marginal economics; and material planning or optimisation
consequences.

### 3. Closer agreement with an experiment is not automatically preferred

Calibration is not automatically preferred merely because it moves the model
closer to an experimental point estimate. The calibrated model must still
pass the relevant predictive, causal, structural-stability, and
decision-use validation gates that would apply to any other candidate model
— improved agreement with one experiment must not automatically justify
material instability elsewhere.

### 4. Both models remain separately visible and comparable

Curves, planning assets, and reports must keep the calibrated and
uncalibrated versions separately visible and directly comparable — never
presenting only the calibrated result once approved. This mirrors the
existing "no-change test" invariant (a candidate identical to the reference
must reproduce the reference exactly) applied to the calibration boundary
instead of a scenario boundary.

### 5. Material-change review

The system must record, for each calibration event: whether calibration
resolved a prior conflict; whether it materially changed a decision; whether
it increased or reduced uncertainty; whether it improved or worsened other
validation dimensions; and any new limitation introduced.

## Explicitly excluded (decision-required, not approved by this record)

- the material-change criteria that trigger mandatory calibrated-versus-
  uncalibrated review before curves, planning, or recommendations may use a
  calibrated model (Part 7 §48 `VL-025`; Part 9 §48 `RP-023`);
- any specific comparison tolerance or pass/fail threshold.

## Affected modules (target)

- the experiment-registry module introduced by `REQ-EXPMODE-001`
- `ancestry_mmm/core/model_identity.py` (calibrated model identity/versioning)
- `ancestry_mmm/pages/06_Diagnostics.py` (calibrated-vs-uncalibrated
  comparison view)
- `docs/approved_requirements/REQ-CALIB-001.md` (new)
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

None yet.

## Unresolved decisions

- Material-change thresholds (`VL-025`/`RP-023`).
- Whether calibrated-model identity extends `core.model_identity` or
  introduces a parallel calibration-identity object.

## Owner

Modelling

## Approval date

2026-08-17
