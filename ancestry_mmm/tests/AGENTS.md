# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/tests`.

The root `AGENTS.md` also applies, including its outcome-registry, pathway-taxonomy, Search-object, capacity/cap, future-variable-role, and requirements-authority rules.

## Requirements authority

Every business-critical test should identify the repository requirement, decision record, schema contract, or implementation-brief acceptance criterion it enforces. Do not derive a new expected behaviour directly from an external PRD passage during implementation.

## No untested modelling changes

Every model, transformation, attribution, curve, economics, hierarchy, or optimiser change requires tests.

Tests must validate the mathematical estimand, not only column presence.

Keep test requirements proportional to the code actually affected. Do not require expensive parameter-recovery, capacity-recovery, or full-suite runs for an unrelated documentation-only change — but do not weaken the gates below for a substantive modelling change either.

## Required test classes

### Upstream compatibility

Where custom behaviour is intended to match PyMC Marketing:

- pin the upstream version
- compare numerical output with the supported upstream API
- test representative edge cases
- document intentional differences

### Parameter recovery

Use synthetic data with known ground truth to test recovery of:

- media coefficients
- adstock
- saturation
- segment effects
- market effects
- direct and halo pathways
- time-varying effects where introduced

Assess bias, interval coverage, and practical recovery, not only whether sampling runs.

### PyMC parity

Prove consistency between:

- PyMC deterministic terms
- NumPy replay
- posterior prediction
- curve counterfactuals
- attribution
- planning-only response
- scenario evaluation

Cover shared and market-specific models.

### Economics

Test:

- outcome-scale response under the full link
- non-zero baseline
- market offsets
- seasonality
- promotions
- controls
- other-media context
- model-input versus spend mapping
- channel-specific costs
- currency conversion
- direct plus halo
- channel spend counted once
- no component CPA without allocation
- marginal finite differences
- portfolio perturbation vectors
- zero and near-zero response
- support and extrapolation
- posterior-draw aggregation before summary

### Outcome registry

Test, for any approved outcome (not only Net Bill Through):

- an unapproved or undefined outcome cannot be selected for modelling, reporting, planning, or optimisation
- no two outcome labels (e.g. GSA, Gross Bill Through, Bill Through, Net Bill Through) are silently treated as synonyms or as a fixed conversion sequence without an explicit approved relationship
- upload validation, wide/long input parity, and completeness metadata for the outcome's own source data
- weekly (or otherwise approved) anchor, missing/duplicate periods, negative/fractional values
- segment totals reconcile to the registered outcome definition

### Net Bill Through (conditional)

Only where NBT is the approved, selected outcome for a given model/report/scenario, additionally test:

- the approved event/date/cohort/maturity/exclusion/reconciliation definition is enforced, not inferred from column presence
- right-censoring: an immature cohort is treated as censored, not as a zero
- expected-final-versus-observed reconciliation and calibration by cohort age
- NBT CPA and ROI on the outcome scale, using the same governance rules as any other approved outcome (never a raw rate as a CPA denominator)

Do not hard-code an NBT-specific test path that runs unconditionally regardless of which outcome a project has approved.

### Capacity, censoring, and cap-aware behaviour

Where an approved pathway is capacity-constrained, test:

- latent-demand recovery on simulated data with known cap sensitivity
- binding-cap intervention: realised delivery and captured demand respond as expected
- non-binding-cap intervention: raising the cap has negligible/no artificial effect
- upstream-only intervention: increasing upstream media can increase latent demand
- cap-only intervention: behaves differently from an upstream-only change
- joint upstream-and-cap intervention: evaluated jointly, not as two independent single-variable changes
- captured demand plus unmet demand reconciles to latent demand under the approved definition
- realised spend/delivery remains within the cap under the approved tolerance
- recommended cap and expected realised spend remain numerically and semantically distinct outputs

### Effect reconciliation

Test:

- direct plus mediated effect reconciles to total (realised) effect where defined
- direct, mediated, halo, and residual-interaction effects are not double-counted against each other
- channel cost is counted once
- posterior draws are reconciled before interval summaries
- a sequential/linked-stage model propagates Stage 1 posterior draws into Stage 2 rather than substituting a point estimate, with approximation error quantified where an emulator/approximation is used

### Future-variable role safety

Test:

- an endogenous mediator cannot be independently assigned a Chronos-2 (or other external) forecast as its ordinary source
- a latent baseline cannot be configured as an ordinary external-forecast target
- a lower-funnel cap cannot be accepted as though it were realised spend
- every invalid role/source combination blocks execution rather than warning and proceeding

### Scenario and planner semantics

Test:

- **no-change scenario**: reproduces the approved reference prediction within documented numerical tolerance, and does not alter endogenous states merely because the scenario engine was invoked
- fast-curve/emulator planning mode versus full posterior/dynamic simulation are compared over a governed validation grid, with approximation error quantified; do not label the fast mode equivalent to the full model without that evidence; block or warn outside the validated region

### Persistence and migrations

Test full round trips for:

- pre-fit
- fitted
- approved
- curves
- scenarios
- legacy migrations, including projects saved before the outcome registry, capacity/cap schema, or future-variable-role schema existed

Verify fingerprints, workflow checkpoint, stale-fit blocking, and schema migration.

### UI

Use Streamlit AppTests for:

- blocking conditions
- labels
- migration review
- save/resume
- stale-state warnings
- governance views

## CI gate

A modelling PR is incomplete until all of the following pass:

- unit tests
- Ruff
- Streamlit AppTests
- PyMC graph/parity tests
- recovery tests where relevant (including capacity/censoring recovery for a capacity-constrained pathway change)
- persistence/migration tests
- resumability tests

Do not weaken or delete a failing test merely to make CI green without documenting why the previous expectation was wrong.
