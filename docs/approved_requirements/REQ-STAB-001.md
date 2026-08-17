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

Not yet implemented. Target-state contract only.

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

## Affected modules (target)

- `ancestry_mmm/core/diagnostics.py` (extend `DiagnosticsArtefact` with a new
  additive structural-stability section)
- `ancestry_mmm/pages/06_Diagnostics.py` (render predictive vs. structural
  stability separately)
- `docs/approved_requirements/REQ-STAB-001.md` (new)
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

None yet. Implementation will require an additive `DiagnosticsArtefact`
schema bump following the existing pattern (schema v2 → v3 → v4 → v5
precedent in `REQ-VAL-001`).

## Unresolved decisions

- Whether real-fold PyMC re-estimation for structural-stability evidence
  runs in normal CI or is schedule/manual evidence (cost-dependent; measure
  before deciding).
- The structured artefact's exact shape (deferred to implementation; must
  remain a structured per-quantity record, never one composite score, per
  Requirement 3).

## Owner

Modelling

## Approval date

2026-08-17
