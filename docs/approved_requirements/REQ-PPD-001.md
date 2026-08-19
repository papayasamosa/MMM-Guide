# REQ-PPD-001: Posterior Predictive Metric Distributions

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-VAL-013`, intro bullet on line 27), Part 7
v1.5 (§0.15 intro bullet 1, §3.9, §4.1, §12.1, §12.6, §45.1, §48 `VL-021`),
and Part 9 v1.5 (§26.4, §28.2, §45 item 22, §49 item 56, §RP-021) —
reconciled by Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps Post
PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17).

`core.diagnostics.error_metrics_by_outcome` (approved under `REQ-VAL-001`,
already implemented) computes MAE, RMSE, sMAPE, WAPE, and bias from the
posterior-mean prediction — a single point-metric value per outcome. No
module in this repository currently computes any of these metrics per
posterior predictive draw and retains the resulting distribution. This
record's contract is additive to `REQ-VAL-001`'s existing point-metric
evidence, not a replacement for it.

## Capability status

Core contract implemented (Work Package 2, 2026-08-17):
`core.diagnostics.posterior_predictive_metric_distributions` (Model A) and
`core.market_specific_diagnostics.posterior_predictive_metric_
distributions_market_specific` (Model C) compute, per outcome, the
per-draw distribution of MAE/RMSE/sMAPE/WAPE/bias from `trace.
posterior["mu"]` (the same posterior-draw-stacking convention `posterior_
predictive_coverage` already uses), alongside the existing posterior-mean
point value reused unchanged from `error_metrics_by_outcome`/`error_
metrics_by_outcome_market_specific` — the two computations can never
silently diverge because the point value is passed through, not
recomputed. Each metric gets five columns (`{metric}_point`, `_mean`,
`_median`, `_lower`, `_upper`) satisfying Requirement 4's artefact-content
list, plus `draw_count` and `credible_mass`. The draw-level mechanics are
shared between Model A/C via a private `_posterior_predictive_metric_
distributions_core` helper (`mu`'s shape does not depend on market-
specificity), so the two model types can never silently diverge in how
the distribution itself is computed — only in which point-metric function
supplies the comparison value.

sMAPE's percentage-metric safeguard (Requirement 3) is handled per draw:
observations where both actual and predicted are exactly zero are masked
out of that draw's sMAPE rather than producing a 0/0 artefact, mirroring
the existing scalar `_smape` helper's own safeguard.

`DiagnosticsArtefact`/Diagnostics-page integration now complete (Work
Package 2, canonical Diagnostics evidence integration, 2026-08-18):
`ancestry_mmm/application/diagnostics_service.py` schema v8 adds the
`posterior_predictive_metric_distributions` section, computed inline in
`DiagnosticsService.evaluate()` for both Model A and Model C from the same
trace/frame/meta/params already used for `error_metrics` (no extra fit) —
landed together with `REQ-STAB-001`'s structural-stability evidence and
`REQ-IDENT-001`/`REQ-LATENT-001`/`REQ-EXPMODE-001`/`REQ-CALIB-001` in one
coherent schema/UI addition, as originally deferred, not built twice.
`pages/06_Diagnostics.py` renders the section as its own table, separate
from every other evidence dimension. An artefact computed before schema v8
upgrades this section to `not_computed` (never a fabricated payload) — see
`DiagnosticsArtefact.from_dict`'s v7→v8 migration path.

## Requirement

### 1. Three distinct analytical objects

The system must distinguish, and never give an interchangeable label to:

1. a metric (MAE, RMSE, sMAPE, WAPE, bias, or another approved metric)
   calculated once from the posterior-mean (or posterior-median) prediction
   — the existing `REQ-VAL-001` evidence;
2. the distribution of that same metric calculated independently across
   posterior predictive draws, summarised by an approved central tendency
   (mean or median) and an approved interval;
3. the posterior predictive interval for the outcome itself.

For a non-linear metric such as RMSE, the metric of the posterior mean is
not generally equal to the posterior mean of the metric — these are
genuinely different numbers, not two views of the same number.

### 2. Where meaningful, retain the metric distribution

Where a predictive metric is meaningful for the selected outcome and can
validly be evaluated per posterior predictive draw, the validation artefact
should retain the metric's distribution across draws (or another approved
uncertainty-aware representation), not only the posterior-mean point value.
The point metric may be retained as a secondary diagnostic; it must not
silently replace the uncertainty-aware evidence.

### 3. Percentage-metric safeguards

Percentage-error metrics (e.g. MAPE, sMAPE) require an explicit review path
where the observed outcome can approach or equal zero, consistent with the
existing sMAPE/WAPE rationale already recorded in `REQ-VAL-001`.

### 4. Artefact contents

Where a posterior predictive metric distribution is retained, the artefact
must record: metric name and version; outcome/market/product/segment scope;
observation window; posterior predictive source; draw count or approximation
method; the point metric from the posterior-mean prediction where retained;
the distribution's mean/median; an approved interval summary; exclusions or
numerical safeguards applied; comparison baseline where applicable.

### 5. Reporting must preserve the distinction

The reporting layer must not relabel the interval around a metric
distribution as though it were the posterior predictive interval for the
outcome itself, and must not use one ambiguous label (e.g. "model
uncertainty") for more than one of the three objects in Requirement 1.

## Explicitly excluded (decision-required, not approved by this record)

- which predictive metrics require posterior predictive distributions
  versus another uncertainty-aware form, the approved interval summary, and
  the role of the posterior-mean point metric (Part 7 §48 `VL-021`; Part 9
  §48 `RP-021`);
- any specific credible-interval width (e.g. "90%"/"95%") — not stated
  anywhere in the source PRD parts and must not be defaulted from this
  record.

## Affected modules

- `ancestry_mmm/core/diagnostics.py` (new: `posterior_predictive_metric_
  distributions`, `_posterior_predictive_metric_distributions_core`)
- `ancestry_mmm/core/market_specific_diagnostics.py` (new:
  `posterior_predictive_metric_distributions_market_specific`)
- `ancestry_mmm/application/diagnostics_service.py` (Work Package 2 —
  `DiagnosticsArtefact` schema v8 `posterior_predictive_metric_
  distributions` section, computed inline in `evaluate()`)
- `ancestry_mmm/pages/06_Diagnostics.py` (Work Package 2 — wired, rendered
  as its own table separate from every other evidence dimension)
- `docs/approved_requirements/REQ-PPD-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_posterior_predictive_metric_distributions.py`
  (10 tests: expected columns/draw-count, point value reused unchanged
  from `error_metrics_by_outcome*`, the metric-of-the-mean vs. mean-of-
  the-metric distinction under noise, credible-interval bounding, and the
  zero-noise-collapses-to-a-point sanity check, for both Model A and
  Model C)
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestSchemaV8Migration`
  and `TestSchemaV8FreshArtefact` (Work Package 2 — migration, round trip,
  fingerprint coverage for all six new schema-v8 sections)
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestEvaluatePosteriorPredictiveMetricDistributions`
  (Work Package 2 — Model A and Model C, wired into `evaluate()`)
- `ancestry_mmm/tests/test_diagnostics_wp2_evidence_apptest.py::test_scorecard_computes_posterior_predictive_metric_distributions`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

Resolved (Work Package 2): `DiagnosticsArtefact` schema v7 → v8. An
artefact computed before schema v8 upgrades this section to `not_computed`
with an explicit "added in schema v8" message — never a fabricated
payload. No change to any other already-computed section.

## Unresolved decisions

- Which metrics in the existing `error_metrics_by_outcome` set (MAE, RMSE,
  sMAPE, WAPE, bias) get a draw-level distribution in the first
  implementation versus remaining point-only, pending `VL-021`/`RP-021` —
  this implementation computes all five for every outcome; the PRD's own
  decision registers, not this record, govern which ones are officially
  required.
- `DiagnosticsArtefact`/Diagnostics-page schema and UI wiring — **resolved**
  (Work Package 2, see Capability status above). The approved threshold/
  materiality policy questions above remain open; this record's evidence
  is exposed for human review, not gated by an invented threshold.

## Owner

Modelling

## Approval date

2026-08-17
