# REQ-EXPMODE-001: Experiment Evidence Modes and Provenance

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-EXP-001`–`FR-EXP-003`, `FR-EXP-007`), Part
6 v1.6 (intro bullets 6–7, §22.1–§22.4), Part 7 v1.5 (§0.15 intro bullets
6–7, §28.1–§28.4, §39 blocking condition #14, §48 `VL-024`), and Part 10 v1.6
(`FCH-06`, `FCH-08`, §20.5–§20.6) — reconciled by Work Package 0 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). This record creates the evidence-mode/provenance
contract only. It does not approve a likelihood-calibration formula — see
"Explicitly excluded" below and `REQ-CALIB-001`.

Experiment Evidence exists in this repository as an input data domain (per
the standing repository authority described in the reconciled brief), but no
module currently declares a governed evidence mode for an experiment-to-model
relationship, and no calibration mechanism exists.

## Capability status

Not yet implemented. Target-state contract only.

## Requirement

### 1. Immutable, versioned experiment records

An experiment record (geo test, holdout, pause test, lift study, or another
approved design) is immutable and versioned once registered, and must
capture at minimum: experiment identity and version; design and dates;
scope (market/product/segment); estimand; treatment quantity or spend where
relevant; the observed effect estimate and its uncertainty; method; source;
evidence status; known limitations; and any recorded overlap or dependence
with other registered experiments.

### 2. Exactly one governed evidence mode per use

Every experiment-to-model relationship must declare exactly one governed
evidence mode for that specific use:

- `validation_only` — compared against model predictions but must not alter
  fitting;
- `prior_calibration` — informs a named prior; the affected prior and its
  version must be recorded;
- `likelihood_calibration` — contributes a likelihood or calibration
  observation-model term; the term and its version must be recorded;
- `diagnostic_comparison` — non-fitting evidence.

Uploading or registering an experiment must never silently calibrate a
model. A separate approved method may permit the same experiment to appear
in more than one downstream diagnostic, but the same evidence must never be
counted twice in the posterior through incompatible calibration routes
(e.g. simultaneously as an informative prior and an independent likelihood
term) unless an approved statistical method explicitly accounts for that
dependence.

### 3. Compatibility assessment before any calibrating use

Before an experiment may be used in `prior_calibration` or
`likelihood_calibration` mode, the system must assess and record
compatibility across: outcome; estimand; market/segment/product; channel or
activity definition; treatment; counterfactual where material; spend/
delivery range; time horizon; and effect scale. An incompatible experiment
must not calibrate automatically. Compatibility may be local (one market or
spend range) rather than global.

### 4. Multiple experiments retain individual identity

Where multiple compatible experiments are approved to contribute to
calibration, each must retain its own estimand, uncertainty, scope, and
provenance. Experiments must not be forced into one manually averaged
estimate solely for implementation convenience. If experiments are
statistically dependent, overlap in treatment or observation periods, or
otherwise share uncertainty, that dependence must be modelled, approximated
explicitly, or used as a reason not to combine them as independent evidence
terms.

### 5. Conflict handling

When experiment and model evidence conflict, the system must support
recording: definition/timing review; external-validity assessment;
treatment-support inspection; prior/specification sensitivity; a
calibrated-versus-uncalibrated comparison (`REQ-CALIB-001`); and an explicit
decision. The system must never silently override one with the other.

### 6. UI/reporting provenance

The interface must show, per experiment-to-model use: the selected evidence
mode; the compatible estimand; experiment version; uncertainty; and — where
several experiments contribute separately — each experiment's provenance
individually. The UI must not collapse separate likelihood evidence terms
into an unexplained average solely for display convenience; a compact
portfolio summary may be shown in addition to, never instead of,
experiment-level evidence.

## Explicitly excluded (decision-required, not approved by this record)

- the evidence-mode taxonomy's edge cases, multi-experiment
  likelihood-calibration conditions, dependence treatment, and
  double-counting rules beyond Requirements 2 and 4 above (Part 7 §48
  `VL-024`);
- any specific likelihood-calibration formula or statistical mechanism —
  Work Package 4 of the reconciled brief requires a decision-support package
  using Context7/official PyMC/PyMC-Marketing sources before any production
  default is chosen.

## Affected modules (target)

- a new experiment-registry domain module (module TBD; likely
  `ancestry_mmm/core/experiments.py`)
- `ancestry_mmm/core/persistence.py` (export/import the experiment registry)
- `docs/approved_requirements/REQ-EXPMODE-001.md` (new)
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

- Likelihood-calibration statistical mechanism (Work Package 4
  decision-support package, not this record).
- Experiment-registry persistence schema and versioning scheme.

## Owner

Modelling

## Approval date

2026-08-17
