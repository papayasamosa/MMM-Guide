# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/tests`.

The root `AGENTS.md` also applies.

## No untested modelling changes

Every model, transformation, attribution, curve, economics, hierarchy, or optimiser change requires tests.

Tests must validate the mathematical estimand, not only column presence.

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

### NBT

Test:

- upload validation
- wide and long input parity
- completeness metadata
- weekly anchor
- missing and duplicate weeks
- negative/fractional values
- segment totals
- NBT CPA and ROI on the outcome scale

### Persistence and migrations

Test full round trips for:

- pre-fit
- fitted
- approved
- curves
- scenarios
- legacy migrations

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
- recovery tests where relevant
- persistence/migration tests
- resumability tests

Do not weaken or delete a failing test merely to make CI green without documenting why the previous expectation was wrong.
