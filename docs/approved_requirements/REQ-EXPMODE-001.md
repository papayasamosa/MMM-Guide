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

Core registry and evidence-mode contract implemented (Work Package 4,
2026-08-18): `ancestry_mmm/core/experiments.py` provides `ExperimentRecord`
(Requirement 1) — an immutable, versioned experiment record whose
`experiment_id`/`experiment_version` lineage/version identity follows
exactly the same pattern already established by `core.causal_graph`
(`graph_id`/`graph_version`) and `core.search_objects`
(`search_object_id`/`search_object_version`): `new_experiment_version`
and `current_experiment_versions` mirror `core.search_objects.new_
search_object_version`/`current_search_object_versions`. `ExperimentTo
ModelUse` enforces exactly one governed evidence mode per use
(Requirement 2's closed four-value vocabulary); `prior_calibration`
and `likelihood_calibration` each require their affected prior/
likelihood-term name and version to be recorded, or construction
raises. `CompatibilityAssessment`/`assess_experiment_compatibility`
implement Requirement 3's per-dimension compatibility record across
all nine listed dimensions — this module has no domain knowledge of
what makes two markets or channel definitions compatible, so every
dimension's compatibility is caller-supplied evidence, never inferred.
`build_calibrating_use` is the only way to construct a calibrating use
and is fail-closed: it raises if `CompatibilityAssessment.is_fully_
compatible` is `False`, directly implementing "an incompatible
experiment must not calibrate automatically." `validate_no_double_
counted_dependence` implements Requirement 2's double-counting rule —
flags any experiment used via two different calibrating modes against
the same model unless every such use records a
`dependence_handling_method`. `ExperimentProvenanceReport`/`build_
provenance_report` implement Requirement 6: every contributing
experiment's evidence mode, estimand, version, and uncertainty
individually; the module offers no function that collapses this list,
so an average can only ever be added alongside it, never instead of it.

Registering an `ExperimentRecord`/`ExperimentToModelUse` cannot
silently calibrate a model (Requirement 2's fail-closed intent) because
nothing in this repository yet reads this registry to build a model —
`core.search_capacity`, `core.pathways`, and every other model-fitting
module are untouched by this record.

Not yet implemented: any specific likelihood-calibration or
prior-calibration statistical mechanism (explicitly reserved by this
record's own "Explicitly excluded" section for a future decision-support
package using Context7/official PyMC/PyMC-Marketing sources, per the
PRD-authority instruction governing this program — do not guess an
unresolved statistical decision); `core.persistence` export/import
wiring for the registry; and `REQ-CALIB-001`'s dependent
calibrated-versus-uncalibrated comparison contract (separate record).

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

## Affected modules

- `ancestry_mmm/core/experiments.py` (new — `ExperimentRecord`,
  `ExperimentToModelUse`, `CompatibilityAssessment`, `assess_experiment_
  compatibility`, `build_calibrating_use`, `validate_no_double_counted_
  dependence`, `ExperimentProvenanceReport`, `build_provenance_report`,
  `new_experiment_version`, `current_experiment_versions`)
- `ancestry_mmm/core/persistence.py` (not yet touched — export/import
  wiring for the experiment registry is deferred)
- `docs/approved_requirements/REQ-EXPMODE-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_experiments.py` (30 tests: record validation/
  round-trip/versioning mirroring `core.search_objects`'s lineage
  pattern; compatibility-assessment dimension coverage; evidence-mode
  validation including both calibration modes' required affected-target
  fields; the fail-closed `build_calibrating_use` gate for a fully
  compatible and an incompatible experiment; the double-counting rule
  across matching/non-matching models and with/without a recorded
  dependence-handling method; and the per-experiment provenance report,
  including a missing-record `KeyError` and cross-model filtering)
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None to persisted artefacts or model-fitting code — this module is
additive and standalone, with no export/import wiring yet.

## Unresolved decisions

- Likelihood-calibration statistical mechanism (Work Package 4
  decision-support package, not this record).
- Experiment-registry persistence schema and versioning scheme.

## Owner

Modelling

## Approval date

2026-08-17
