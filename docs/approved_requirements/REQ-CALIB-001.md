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

Core comparison contract implemented (Work Package 4, second record,
2026-08-18): `ancestry_mmm/core/calibration_comparison.py` resolves this
record's own "whether calibrated-model identity extends `core.
model_identity` or introduces a parallel calibration-identity object"
open question by reusing `core.model_identity.ModelIdentity` directly —
`CalibratedVsUncalibratedComparisonArtefact` and `CalibrationEventRecord`
both reject construction if the calibrated and uncalibrated
`ModelIdentity` instances match (`ModelIdentity.matches`), directly
enforcing Requirement 1: a calibrated model is a new, separately
versioned model identity, never an in-place mutation.
`CalibrationComparisonMetric` generically represents Requirement 2's
comparison dimensions (posterior predictive performance, historical
holdout, media/structural parameters, adstock/saturation, baseline,
hierarchy, posterior uncertainty, response curves, marginal economics,
planning/optimisation consequences) by caller-supplied name and value —
this module has no domain knowledge of how to compute any specific one
of them. `difference` is descriptive only; there is no threshold, pass/
fail, or "calibration preferred" field anywhere in the module
(Requirement 3), verified by an explicit test that scans every dataclass
field for a forbidden verdict-shaped name.
`ExperimentAgreementComparison` reports each compatible experiment's
calibrated-versus-uncalibrated agreement individually, mirroring `core.
experiments`'s own "never collapsed into an average" pattern.
`CalibrationEventRecord` implements Requirement 5: resolved-prior-
conflict, materially-changed-decision, uncertainty-change (closed
three-value vocabulary), and improved/worsened validation dimensions and
new limitations are all caller-supplied, structured facts for a human
reviewer to record — never a judgement this module computes itself,
mirroring `core.structural_stability`'s established pattern.

A `DiagnosticsArtefact`/Diagnostics-page slot for this record's comparison
artefact now exists (Work Package 2 of `Media-Mix-Lab: Coding LLM Next
Steps After PR #286`, canonical Diagnostics evidence integration,
2026-08-18): schema v8's `experiment_calibration` section carries an
optional `CalibratedVsUncalibratedComparisonArtefact` payload (this
record's own `to_dict()`, unchanged) alongside `REQ-EXPMODE-001`'s
experiment-provenance payload — two clearly separated keys under one
section, never merged into one score. This is a display slot only: no
calibration mechanism exists to *produce* a
`CalibratedVsUncalibratedComparisonArtefact` for a real project yet, so
this half of the section is always `None`/`not_applicable` today, exactly
as before this wiring — the requirement's own core contract
(`assemble_calibration_comparison`) remains untouched and uncoupled from
any specific statistical mechanism. (Work Package 2 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #291`, 2026-08-19, now
populates the *experiment-provenance* half of the section from the real
saved registry — see `REQ-EXPMODE-001`'s Capability status; this record's
comparison half is unchanged and remains empty until an approved
calibration mechanism exists.)

Not yet implemented: the material-change criteria that trigger
mandatory review (Part 7 `VL-025`, Part 9 `RP-023`); any specific
comparison tolerance or threshold; computing any comparison metric
itself; and keeping calibrated/uncalibrated versions "separately visible
and directly comparable" in curves/planning/reports (Requirement 4) — the
Diagnostics-page display slot above is a read-only evidence view, not
this Requirement 4 obligation, which remains a separate curves/planning/
reports UI item. No calibration statistical mechanism exists or is
implied — `REQ-EXPMODE-001`'s own deferred decision-support-package
question remains open.

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

## Affected modules

- `ancestry_mmm/core/calibration_comparison.py` (new —
  `CalibrationComparisonMetric`, `ExperimentAgreementComparison`,
  `CalibratedVsUncalibratedComparisonArtefact`,
  `assemble_calibration_comparison`, `CalibrationEventRecord`)
- `ancestry_mmm/core/model_identity.py` (read-only consumer of
  `ModelIdentity`/`ModelIdentity.matches` — no changes to this module)
- the experiment-registry module introduced by `REQ-EXPMODE-001` (not
  yet coupled — `ExperimentAgreementComparison` uses a plain
  `experiment_id` string, not a hard import, to avoid a premature
  dependency)
- `ancestry_mmm/application/diagnostics_service.py` (Work Package 2 —
  `DiagnosticsArtefact` schema v8 `experiment_calibration` section carries
  an optional `CalibratedVsUncalibratedComparisonArtefact`, computed
  inline in `evaluate()`; display-slot only, no calibration mechanism)
- `ancestry_mmm/pages/06_Diagnostics.py` (Work Package 2 — wired, the
  comparison view is a read-only evidence display, never a curves/
  planning/reports "separately visible" integration — Requirement 4
  remains open)
- `docs/approved_requirements/REQ-CALIB-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_calibration_comparison.py` (14 tests: metric/
  experiment-agreement validation and round-trip; the comparison
  artefact's fail-closed rejection of identical calibrated/uncalibrated
  identities; assembly from caller-supplied evidence; an explicit scan
  proving no dataclass field on the artefact suggests an automatic
  verdict or recommendation; the calibration-event record's identity
  check, closed uncertainty-change vocabulary, `None`-means-
  not-yet-assessed semantics, and full round-trip)
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestEvaluateExperimentCalibration`
  (Work Package 2 — the shared `experiment_calibration` section's
  not_applicable default and computed-with-evidence path; this record's
  own comparison-artefact payload uses the identical wiring)
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None to `core.calibration_comparison` itself or model-fitting code — this
module remains additive and standalone. Resolved (Work Package 2):
`DiagnosticsArtefact` schema v7 → v8 adds a display slot for this
record's comparison artefact; an artefact computed before schema v8
upgrades this section to `not_computed` with an explicit "added in schema
v8" message. Curves/planning/reports Requirement 4 wiring remains
unimplemented.

## Unresolved decisions

- Material-change thresholds (`VL-025`/`RP-023`).
- Whether calibrated-model identity extends `core.model_identity` or
  introduces a parallel calibration-identity object — **resolved**:
  reuses `core.model_identity.ModelIdentity` directly (see "Capability
  status" above).

## Owner

Modelling

## Approval date

2026-08-17
