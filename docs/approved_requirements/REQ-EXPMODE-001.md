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

`DiagnosticsArtefact`/Diagnostics-page provenance display now exists (Work
Package 2 of `Media-Mix-Lab: Coding LLM Next Steps After PR #286`,
canonical Diagnostics evidence integration, 2026-08-18): schema v8 adds
the `experiment_calibration` section — computed inline in
`DiagnosticsService.evaluate()` when the caller supplies an
`ExperimentProvenanceReport` (`build_provenance_report`'s own output,
unchanged and reused verbatim via its `to_dict()`; every entry retains
its own estimand/uncertainty, never averaged) — but this is a display
slot only, not a registry: this repository still has no durable adoption/
persistence workflow that gets an `ExperimentRecord`/`ExperimentToModelUse`
into a live project's session state in the first place (that workflow is
a separate work package). `pages/06_Diagnostics.py` therefore always
shows `not_applicable`/`not_computed` for this section today, with an
explicit "no experiment evidence... registered" message — never blank,
never a fabricated pass.

Durable adoption/persistence workflow now complete (Work Package 2 of
`Media-Mix-Lab: Coding LLM Next Steps After PR #291`, 2026-08-19):
`application.experiment_service` is the explicit analyst-reviewed adoption
boundary — an uploaded source row never becomes an `ExperimentRecord` by
itself; the analyst completes every required field at adoption (missing
fields fail closed, never fabricated), the registry is immutable
(edits are new versions via `new_registered_experiment_version`, never
mutations), and re-adoption of differing content raises. Evidence-mode
adoption is explicit per model use (`register_model_use`): calibrating
modes require a caller-evidenced `CompatibilityAssessment`
(`build_calibrating_use` fails closed on incompatibility), explicit
affected prior/likelihood identity, and a `dependence_handling_method`
whenever a new use would create a double-counted dependence —
`validate_no_double_counted_dependence`'s violation list gates
construction. `validation_only`/`diagnostic_comparison` uses need no
compatibility assessment and cannot alter fitting because no
model-fitting module reads the registry — no calibration computation
exists anywhere. The registry persists through the project bundle
(`config/experiments.json` under `EXPERIMENT_REGISTRY_SCHEMA_VERSION`,
`core.persistence.resolve_imported_experiments` quarantines malformed
records, orphaned uses, and unrecognised future schema versions) and
populates the Diagnostics `experiment_calibration` section from the real
saved registry (`provenance_for_model`, per experiment, never averaged,
with a live staleness note when the registry changed after scorecard
computation). The adoption/review UI lives on `pages/01_Data_Upload.py`;
model-use declaration and provenance render on `pages/06_Diagnostics.py`.
AppTest and browser-journey coverage exercise both.

Not yet implemented: any specific likelihood-calibration or
prior-calibration statistical mechanism (explicitly reserved by this
record's own "Explicitly excluded" section for a future decision-support
package using Context7/official PyMC/PyMC-Marketing sources, per the
PRD-authority instruction governing this program — do not guess an
unresolved statistical decision); the calibrated-versus-uncalibrated
comparison half of the Diagnostics section therefore remains empty
(`REQ-CALIB-001`, separate record, no mechanism exists to produce its
artefact).

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
- `ancestry_mmm/application/diagnostics_service.py` (Work Package 2 —
  `DiagnosticsArtefact` schema v8 `experiment_calibration` section,
  computed inline in `evaluate()`; display-slot only, no registry)
- `ancestry_mmm/pages/06_Diagnostics.py` (Work Package 2 — wired)
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
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestEvaluateExperimentCalibration`
  (Work Package 2 — not_applicable with no evidence; provenance report
  computed and entries kept individually separate, never averaged; round
  trip/fingerprint)
- `ancestry_mmm/tests/test_diagnostics_wp2_evidence_apptest.py::test_scorecard_reports_not_applicable_latent_state_and_experiment_sections`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None to `core.experiments` itself or model-fitting code — this module
remains additive and standalone, with no export/import wiring yet.
Resolved (Work Package 2): `DiagnosticsArtefact` schema v7 → v8 adds a
display slot for this record's provenance report; an artefact computed
before schema v8 upgrades this section to `not_computed` with an explicit
"added in schema v8" message.

## Unresolved decisions

- Likelihood-calibration statistical mechanism (Work Package 4
  decision-support package, not this record).
- Experiment-registry persistence schema and versioning scheme.
- The durable source-to-governed adoption workflow that would let a real
  project supply this Diagnostics section's `ExperimentProvenanceReport`
  in the first place — out of scope for Work Package 2 (UI/schema wiring
  only); a separate work package.

## Owner

Modelling

## Approval date

2026-08-17

## Addendum, 2026-08-30 (Phase C): calibration mechanism resolved for likelihood_calibration (Decision 11)

This record's own "Explicitly excluded"/"Unresolved decisions" sections
named "any specific likelihood-calibration formula or statistical
mechanism" as requiring "a decision-support package using Context7/
official PyMC/PyMC-Marketing sources before any production default is
chosen." Decision 11 of the business-decision brief ("experiments
should inform priors/calibration, not just post-hoc comparison") is
that trigger. This addendum records the resulting resolution: full
decision record in
`docs/experiment_calibration_mechanism_decision_record.md`;
implementation in `ancestry_mmm/core/experiment_lift_test_mapping.py`.

**Resolved, for `likelihood_calibration` only:** PyMC-Marketing's own
official, documented `MMM.add_lift_test_measurements(df_lift_test)` API
is the approved calibration mechanism — confirmed via Context7 against
PyMC-Marketing's own documentation repository to calibrate a
saturation-curve likelihood/observation-model term specifically,
matching this record's own `likelihood_calibration` evidence-mode
definition exactly. `ExperimentRecord` gained one new field
(`baseline_exposure_level`, `EXPERIMENT_REGISTRY_SCHEMA_VERSION` 1 -> 2)
to carry the "x" (baseline exposure level) PyMC-Marketing's official row
shape requires alongside `treatment_quantity` (-> `delta_x`),
`observed_effect_estimate` (-> `delta_y`), and `effect_uncertainty`
(-> `sigma`, now required strictly positive for a lift-test row
specifically). `build_lift_test_calibration_row`/`build_lift_test_
calibration_rows` map a fully compatible, likelihood-calibration-mode
experiment into this exact row shape, fail-closed (never silently
substituting a default, and independently re-verifying compatibility
rather than trusting a supplied `ExperimentToModelUse` blindly, since
that type can be constructed directly without going through
`build_calibrating_use`'s own gate).

The same schema bump additionally adds three governance fields the
prior Phase B handoff flagged as missing:
`strategy_or_tactic_tested`, `post_adoption_outcome_tracked`, and
`applicability_period_start`/`applicability_period_end` — all optional,
backward-compatible, not required by the lift-test mapping itself but
relevant to Decision 11's broader governance intent.

**Still not resolved:**

- `prior_calibration`'s mechanism — no equally well-established,
  officially-documented PyMC-Marketing mechanism for directly informing
  a named prior from an experiment was found in the queried
  documentation; a future session may need to search further or treat
  this as a still-open, separate decision;
- the actual `add_lift_test_measurements(...)` call inside any real
  model-fitting code — `core.search_capacity`, `core.pathways`, and
  every other model-building module remain untouched by this addendum,
  preserving this record's own "registering an experiment must never
  silently calibrate a model" invariant; wiring this in for real is a
  separate, materially statistical follow-up requiring its own
  validation;
- `config/experiments.json` — still does not exist anywhere in this
  repository, so the schema bump required no live registry migration.

No `application`/`pages` code changes accompany this addendum beyond
the additive `ExperimentRecord` fields; no model-fitting module is
touched.
