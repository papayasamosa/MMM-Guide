# REQ-FORECAST-001: Downstream Forecast-Consequence Evidence

## PRD source

Ancestry MMM PRD Part 3 v1.7 (`FR-FCST-013`, §26.16), Part 6 v1.6 (intro
bullet 10, §26.7), Part 7 v1.5 (§0.15 intro bullet 9, §30.8, §39 blocking
condition #22, §48 `VL-027`), Part 9 v1.5 (§21.1–§21.7, §RP-024), and Part 10
v1.6 (`FCH-09`, §26.1, §26.4–§26.5, §26.11) — reconciled by Work Package 0 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). This record is separate from, and does not authorise,
Work Package 9's broader "governed future assumptions" scope in the
reconciled brief — it covers only the *consequence-assessment* contract for
an already-classified exogenous forecastable control.

No module in this repository currently distinguishes standalone forecast
accuracy from downstream MMM consequence for a future exogenous control.

## Capability status

Not yet implemented. Target-state contract only.

## Requirement

### 1. Two distinct evaluation axes

A future exogenous control's forecast must be evaluated on two separate
axes, never conflated:

1. standalone forecast quality and uncertainty (backtest accuracy,
   benchmark comparison against a simple method, interval calibration);
2. downstream consequence — how much plausible alternative forecast paths
   change the MMM's predicted outcome, incremental outcome, baseline,
   channel contribution, marginal CPA/ROI, response-curve interpretation,
   scenario ranking, or optimisation allocation.

The system must not assume a high-error forecast is automatically
decision-material, nor that a statistically accurate forecast is low-risk —
materiality depends on both forecast uncertainty and the model's sensitivity
to that variable.

### 2. Consequence-assessment method must match model structure

Depending on model structure, downstream consequence must be assessed
through one of: posterior scenario replay (preferred where the full model
can be replayed); an approved local sensitivity analysis; an approved
counterfactual replay; another validated method. A simple first-order
(additive-linear) approximation may be shown as an explanatory diagnostic
only where its assumptions hold, and must never be applied to a nonlinear
control, a mediated variable, a moderator, a capacity-constrained pathway, a
latent state, or a material interaction.

### 3. Unassessed is a valid, disclosed state

Where influence or consequence has not been evaluated, the system must
record and display `not_assessed`, `unsupported`, or another governed
status — never a fabricated risk score.

### 4. Recommendation-sensitivity disclosure

Where a future-variable path materially changes a decision-ready
recommendation, the system must expose: the affected decision; the
direction and magnitude of the change where supported; the relevant
uncertainty; whether recommendation status changes as a result; and whether
further forecast review or scenario stress-testing is required.

### 5. Role-conflict blocking (reaffirms existing future-role invariant)

This record's consequence evidence applies only to a variable correctly
classified as an exogenous forecastable control. An endogenous mediator
independently forecast, a latent baseline treated as an ordinary control, or
planned media forecast as exogenous remain blocking role-conflict errors
under the existing future-variable-role invariant (root `AGENTS.md`) — this
record does not relax that boundary.

## Explicitly excluded (decision-required, not approved by this record)

- how future-control influence and planning materiality are quantified or
  graded, and when forecast-consequence review becomes blocking (Part 7 §48
  `VL-027`; Part 9 §48 `RP-024`);
- Chronos-2 integration itself (Work Package 9 of the reconciled brief;
  Hugging Face MCP discovery only, no dependency introduced by this record).

## Affected modules (target)

- a future-assumption/forecast-consequence module (module TBD; depends on
  Work Package 9's future-role/bundle design, not yet implemented)
- `ancestry_mmm/pages/08_Scenario_Planner.py` (surface consequence evidence
  beside a future control)
- `docs/approved_requirements/REQ-FORECAST-001.md` (new)
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

- Materiality quantification/grading method (`VL-027`/`RP-024`).
- Relationship to the not-yet-approved governed future-assumption bundle
  (Work Package 9 of the reconciled brief; `docs/specification_authority.md`
  already lists "Future-assumption bundles" as "No approved requirement/
  decision yet").

## Owner

Modelling

## Approval date

2026-08-17
