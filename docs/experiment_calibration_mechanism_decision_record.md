# Experiment calibration mechanism decision record (Decision 11)

## Why this record exists

`REQ-EXPMODE-001` implements the experiment evidence-mode/provenance
registry (`core.experiments`) but explicitly excludes "any specific
likelihood-calibration formula or statistical mechanism," naming a
future decision-support package "using Context7/official PyMC/
PyMC-Marketing sources" as the required path before any production
default is chosen. Decision 11 of the "Post-UI/UX Implementation
Instructions: Approved Business Decisions" brief ("experiments should
inform priors/calibration, not just post-hoc comparison") is exactly
that trigger. This record is that decision-support package.

It resolves: which PyMC-Marketing mechanism (if any) is the approved
calibration mechanism for a `likelihood_calibration`-mode experiment,
and the governed data contract mapping this repository's
`ExperimentRecord` into that mechanism's required input shape.

It explicitly does **not**:

- implement the actual PyMC-Marketing model-fitting call
  (`mmm.add_lift_test_measurements(...)`) inside any real model-building
  code (`core.search_capacity`, `core.pathways`, `core.hierarchical_
  model`, or any other fitting module) - mirrors every other Phase B/C
  step's scope boundary: this is a materially statistical change to a
  real fit requiring its own prior-predictive/synthetic-recovery
  validation, and this repository's model-fitting modules must remain
  untouched by an experiment registry per `REQ-EXPMODE-001`'s own
  existing "registering an experiment must never silently calibrate a
  model" invariant;
- select a `prior_calibration` mechanism (no equally well-established,
  officially-documented PyMC-Marketing mechanism for directly informing
  a *prior* from an experiment was found - see "What this record does
  not decide" below);
- invent any specific calibration formula beyond what PyMC-Marketing's
  own documented API already defines.

## Sources consulted

Queried directly via the Context7 MCP tool against PyMC-Marketing's
official documentation repository (`/pymc-labs/pymc-marketing`), not
from general training-data recall alone:

1. **`skills/mmm-modeling/SKILL.md`** and
   **`skills/mmm-modeling/references/liftest_calibration.md`**: confirm
   `MMM.add_lift_test_measurements(df_lift_test)` as PyMC-Marketing's
   own official, documented API for calibrating an MMM with experimental
   lift-test evidence — called after `build_model()` and before `fit()`,
   producing a "calibrated" model directly comparable to an
   "uncalibrated" one built from the identical configuration.
2. **`docs/source/notebooks/mmm/mmm_roas.ipynb`** and
   **`docs/source/notebooks/mmm/mmm_geolift_calibration.ipynb`**: confirm
   the exact required row shape for `df_lift_test`: `channel` (the
   channel column name being calibrated), `x` (the baseline
   spend/exposure level the channel was at immediately before the
   tested delta was applied — required because saturation curves are
   non-linear, so the same `delta_y` implies a different marginal effect
   depending on where on the curve the test started), `delta_x` (the
   size of the tested spend/exposure change), `delta_y` (the observed
   incremental effect, i.e. the experiment's lift estimate), `sigma`
   (the lift estimate's uncertainty), and optionally `date`/`geo`. A
   direct quote from the geo-lift notebook: "the lift test must utilize
   the same saturation function as the MMM to ensure consistency between
   the experimental results and the model parameters" — i.e. this
   mechanism calibrates the *saturation-curve likelihood term*
   specifically, matching `REQ-EXPMODE-001`'s own `likelihood_
   calibration` evidence-mode definition ("contributes a likelihood or
   calibration observation-model term") precisely, not `prior_
   calibration`.

No equally well-documented, official PyMC-Marketing mechanism for
directly informing a named *prior* (as opposed to contributing a
likelihood/calibration observation-model term) from an experiment was
found in the queried documentation — `prior_calibration`'s mechanism
therefore remains unresolved by this record (see below).

## What this record does not decide

- The `prior_calibration` mechanism (no official PyMC-Marketing
  precedent found; a future session should search further or treat this
  as a separate, still-open decision).
- Any code change to actually call `add_lift_test_measurements` inside
  a real model build.
- The specific compatibility-dimension evidence for any real experiment
  (`REQ-EXPMODE-001` Requirement 3 already requires this to be
  caller-supplied, never inferred, and this record does not change that).

## Decision required

### C1. Which PyMC-Marketing mechanism to adopt for `likelihood_calibration`

**Decision: adopt `MMM.add_lift_test_measurements`'s documented
`df_lift_test` row shape as the approved target contract.** It is
official, well-documented, purpose-built for exactly this use case
(experiment-informed MMM calibration), and its semantics
(channel/x/delta_x/delta_y/sigma) map cleanly onto fields
`ExperimentRecord` already has or needs.

### C2. What `ExperimentRecord` is missing to build a valid row

Mapping the official row shape onto `ExperimentRecord`'s existing
fields:

- `delta_x` -> `treatment_quantity` (already exists: "treatment quantity
  or spend where relevant," Requirement 1);
- `delta_y` -> `observed_effect_estimate` (already exists);
- `sigma` -> `effect_uncertainty` (already exists, and Requirement 1
  already requires it to be non-negative — this record additionally
  requires it to be strictly positive for a lift-test row specifically,
  since a zero-uncertainty pseudo-observation would give the calibration
  term infinite/degenerate weight);
- `date` -> derivable from `start_date`/`end_date` (already exists);
- `channel` -> not a structured field on `ExperimentRecord` today
  (`channel_or_activity_definition` exists only as a
  `COMPATIBILITY_DIMENSIONS` assessment-dimension *name*, not a value
  stored on the record itself) — this record does NOT add a new field
  for it, since the actual model's channel-column identity is a
  property of the specific MMM being calibrated, not of the experiment;
  the mapping function below requires the caller to supply it explicitly
  per calibration attempt;
- `x` (baseline exposure level) -> **missing**. This record adds
  `baseline_exposure_level: Optional[float] = None` to `ExperimentRecord`
  (schema v1 -> v2, additive/backward-compatible) to carry it.

### C3. Governance fields Phase A/B's own handoff flagged as missing

The prior Phase B handoff separately named three schema gaps not
directly required by the lift-test mapping itself but relevant to
Decision 11's broader "informs priors/calibration" governance intent:
`strategy_or_tactic_tested` (what was actually tested — a creative,
targeting, or budget-level change — since "the experiment" alone does
not disambiguate this), `post_adoption_outcome_tracked` (whether the
tested change, once adopted into always-on activity, has had its
real-world outcome tracked afterward — informs whether the calibrating
evidence is still fresh), and `applicability_period_start`/
`applicability_period_end` (the period during which this experiment's
finding is considered still valid for calibration — distinct from
`start_date`/`end_date`, which record when the experiment itself ran).
All three are added as optional, backward-compatible fields in the same
schema v2 bump.

## Implementation

`ancestry_mmm/core/experiments.py` (modified, additive only):
`ExperimentRecord` gains `baseline_exposure_level`,
`strategy_or_tactic_tested`, `post_adoption_outcome_tracked`,
`applicability_period_start`, `applicability_period_end` (all
`Optional`, all default `None`/absent) — `EXPERIMENT_REGISTRY_SCHEMA_
VERSION` bumped 1 -> 2. No `config/experiments.json` file exists in this
repository yet, so no live persisted registry required migration.

`ancestry_mmm/core/experiment_lift_test_mapping.py` (new): implements
C1/C2.

- `LiftTestCalibrationRow` — the governed row shape matching
  PyMC-Marketing's official `df_lift_test` schema exactly
  (`channel`/`x`/`delta_x`/`delta_y`/`sigma`/`date`).
- `build_lift_test_calibration_row` — fail-closed mapping from an
  `ExperimentRecord` + `ExperimentToModelUse` + `CompatibilityAssessment`
  into one `LiftTestCalibrationRow`. Raises `ValueError` (never silently
  substitutes a default) unless: `use.evidence_mode ==
  "likelihood_calibration"`; `compatibility.is_fully_compatible` is
  `True` (re-verified independently here, never assumed merely because
  `use` exists — `ExperimentToModelUse` can technically be constructed
  without going through `build_calibrating_use`'s own gate); `record.
  baseline_exposure_level` and `record.treatment_quantity` are both
  supplied (not `None`); `record.effect_uncertainty > 0`.
- `build_lift_test_calibration_rows` — the same, over a supplied
  sequence, skipping nothing silently (raises on the first invalid
  entry rather than dropping it).

Tests: `ancestry_mmm/tests/test_experiment_lift_test_mapping.py`, and
`ExperimentRecord`'s new fields are covered by additions to
`ancestry_mmm/tests/test_experiments.py`.

## Production adapter addendum, 2026-09-01

The repository's production builders are intentionally raw PyMC and do not
instantiate `pymc_marketing.MMM`. To finish the approved integration without
duplicating the whole model architecture, the production path now composes
the same lift-test observation-model semantics through
`attach_lift_test_calibration_terms` in
`core.experiment_lift_test_mapping`.

The adapter is intentionally narrower than the upstream API: it requires an
explicit `ModelLiftTestCalibrationInput` outcome id, accepts only a direct
primary channel/outcome cell, treats `x` and `delta_x` as prepared model-input
units, uses the existing Hill response and outcome-scale log link, and adds a
Gamma observation term for strictly positive observed lift. This is a
documented custom divergence, not a claim of full PyMC-Marketing API
equivalence. Any temporal/adstock translation, signed-effect likelihood, and
`prior_calibration` mechanism remain out of scope and fail closed.

`build_model_for_spec` and Model Training now pass compatible registry rows
into both raw-PyMC builders. A specific experiment record is still external
data: no calibration is applied when no valid record, use, assessment, and
explicit target are present.

## Owner and status

Owner: Modelling / Platform engineering (mapping contract);
Data Science sign-off on actually invoking
`add_lift_test_measurements` inside a real model build not yet sought
(separate, materially statistical follow-up).

Status: implemented and tested, 2026-08-30. `REQ-EXPMODE-001` addendum
(below) records this resolution at the requirement level;
`prior_calibration`'s mechanism remains unresolved.
