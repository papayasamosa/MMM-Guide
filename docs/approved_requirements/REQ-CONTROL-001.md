# REQ-CONTROL-001: Standardised category-demand control prior for the current UK Model A candidate

**Status:** approved for implementation
**Decision date:** 2026-08-25
**Scope:** the current UK Model A candidate's continuous category-demand controls only (`fh_category_demand_google_trends` for Family History, `dna_category_demand_google_trends` for DNA Kit), as fit by `scripts/run_uk_production_fit.py` - the 2023-01-01 through 2025-04-06 common-window exercise that `REQ-PREFIT-001.md` explicitly designates `historical_test` / `non_production`. This record authorises a statistical-configuration decision (the coefficient prior and representation for these named controls) for that candidate; it does not change the candidate's `historical_test`/`non_production` status.

## Decision

The analyst reviewed the WP2.6 control-prior calibration evidence
(`docs/wp2_6_control_prior_calibration_decision_package.md`) and approved:

1. The named continuous category-demand controls above must be
   standardised (centred, unit-SD) before modelling, using
   `ancestry_mmm.core.control_scaling.fit_control_scaling`'s existing
   `mean_sd` method - no new scaling implementation.
2. Their coefficient prior on that standardised scale is
   **`Normal(0, 0.20)`** - i.e. `prior_config["control_sigma"] = 0.20`
   with `prior_config["enable_control_scaling"] = True`.
3. Standardisation parameters (centre, scale) must be derived from the
   model's own training data using the existing governed leakage-safe
   pipeline (the frame `scripts/run_uk_production_fit.py` already
   builds via `prepare_fh_modeling_frame` before any fit) - never from
   an external or held-out source.
4. Scaling parameters must be retained with the fitted model
   (`FHModelMeta.control_scaling`/`outcome_control_scaling`, already
   persisted via `ancestry_mmm/core/persistence.py`'s `model_meta.json`)
   and reused, unchanged, for posterior prediction, attribution,
   scenario simulation and replay - never refit at prediction time.
5. **This decision does not extend to any binary/event control.** No
   binary/event control exists in the current governed frame for either
   model; if one is added in future, standardising it requires its own
   approved requirement - this record does not authorise that by
   implication, and `scripts/run_uk_production_fit.py`'s
   `_validate_approved_control_scaling_scope` fails closed
   (`FitGateError`) if `enable_control_scaling` is ever on for a frame
   whose `control_names` include anything outside
   `APPROVED_STANDARDISED_CONTROL_NAMES`, or whose `outcome_controls`
   is non-empty (outcome-level controls share the same
   `_resolve_control_scaling` gate but were never reviewed by this
   decision).
6. **`control_sigma=0.20` is not a universal prior.** It applies only to
   the two named controls in scope above, only via
   `scripts/run_uk_production_fit.py`'s
   `APPROVED_UK_MODEL_A_PRIOR_CONFIG`. `ancestry_mmm/core/
   hierarchical_model.py`'s own fallback defaults
   (`control_sigma=0.5`, `enable_control_scaling=False`) are
   deliberately left unchanged, so every other caller of
   `_resolve_control_scaling` (any other model, market, or future
   control) keeps its pre-existing default-off behaviour unless and
   until its own approved requirement says otherwise.

## Rationale

Evidence (`docs/wp2_6_control_prior_calibration_decision_package.md`):
under the standardised representation, `control_sigma=0.20` gives
approximately a 0.71x-1.37x 90% multiplicative prior interval for a
one-standard-deviation movement in category demand, and approximately
0.64x-1.54x at the 1st/99th percentiles - meaningful flexibility without
letting the context control dominate the log predictor. The raw
(unscaled) representation produced approximately ±40 to ±49 log-unit
`eta_controls` swings at the same nominal prior and is rejected outright,
not merely tightened. `control_sigma=0.5` is unnecessarily broad for a
secondary contextual variable (99th-percentile bound ~0.32x-2.96x, wider
than warranted for this role). `control_sigma=1.0` produced measurable
numerical ceiling-clipping (17/357,000 Family History draws,
15/238,000 DNA draws) and is rejected.

## Approved production change

- `scripts/run_uk_production_fit.py`'s `main()` now defaults
  `prior_config` to `APPROVED_UK_MODEL_A_PRIOR_CONFIG =
  {"control_sigma": 0.20, "enable_control_scaling": True}` when no
  `--prior-config` override is supplied.
- `_validate_approved_control_scaling_scope` (new) enforces the scope
  boundary in item 5/6 above at frame-build time, before any fit.
- No change to `ancestry_mmm/core/control_scaling.py` (the scaling
  mechanism itself is unchanged - only when it is invoked, for this
  candidate, changes).
- No change to media priors, adstock, Hill saturation, pooling, channel
  selection, causal roles, or fold policy.

## Affected modules

- `scripts/run_uk_production_fit.py`
- `ancestry_mmm/core/hierarchical_model.py` (docstring only - clarifies
  the now-existing, scoped approval; the gated, default-off contract
  itself is unchanged)
- `ancestry_mmm/core/control_scaling.py` (consumed, not modified)
- `ancestry_mmm/core/predict.py` (consumed, not modified - already
  replays `meta.control_scaling`/`outcome_control_scaling`
  unconditionally at prediction/scenario time)
- `ancestry_mmm/core/persistence.py` (consumed, not modified - already
  persists `FHModelMeta` including the scaling contract)

## Required tests

- The approved production prior config equals
  `{"control_sigma": 0.20, "enable_control_scaling": True}`.
- The approved standardised-control allowlist equals exactly the two
  named controls above.
- The scope guard is a no-op when `enable_control_scaling` is off.
- The scope guard passes for the approved controls with empty
  `outcome_controls`.
- The scope guard raises `FitGateError` for any control name outside
  the approved allowlist.
- The scope guard raises `FitGateError` when `outcome_controls` is
  non-empty.

## Human traceability

Derived from the analyst's WP2.7 instruction (2026-08-25), which reviewed
and approved candidate remedy direction 1 and the `control_sigma=0.20`
grid point from `docs/wp2_6_control_prior_calibration_decision_package.md`
(itself derived from the analyst's WP2.6 instruction reviewing
`docs/wp2_5_prior_predictive_decision_package.md`).
