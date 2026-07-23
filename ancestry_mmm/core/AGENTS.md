# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/core`.

The root `AGENTS.md` also applies.

## Core modelling policy

Core code must be framework-independent and testable without Streamlit.

Before editing adstock, saturation, priors, response curves, attribution, calibration, hierarchy, or optimisation:

1. inspect the current `pymc-labs/pymc-marketing` public implementation
2. inspect relevant examples and tests
3. document the gap
4. use upstream public APIs where they satisfy the Ancestry requirement
5. add numerical compatibility tests for custom equivalents

## Current custom-model reality

The current application contains custom PyMC model builders for Ancestry's multi-outcome, pathway-governed structure.

Do not replace these blindly with a stock single-outcome MMM.

Preserve:

- multiple FH segment outcomes
- DNA outcomes
- market hierarchy
- direct and cross-product pathway components
- component-specific lag and governance
- NBT semantics
- unpooled markets
- outcome-specific controls
- saved-project compatibility

Where PyMC Marketing does not directly support this structure, use it as an implementation and validation reference rather than forcing the business problem into an unsuitable API.

## PyMC Marketing alignment targets

Prioritise upstream comparison for:

- `GeometricAdstock` and other supported adstock transformations
- saturation transformations such as logistic or Hill-style alternatives
- transformation configuration and priors
- multidimensional MMM patterns
- lift-test calibration
- posterior predictive utilities
- contribution and response-curve methods
- budget optimisation APIs
- time-varying parameters where relevant

For each custom equivalent, add or maintain an alignment test or documented reason for divergence.

## Media input versus monetary spend

Never assume `X_media` is monetary spend.

Maintain separate concepts:

- `media_input`
- `media_input_unit`
- `local_spend`
- `local_currency`
- `reporting_currency_spend`
- cost-per-media-unit mapping
- FX conversion

A monetary curve requires a mapping such as:

```text
spend -> media input -> adstock -> saturation -> eta -> outcome
```

The mapping may vary by:

- market
- channel
- period
- supplier/platform
- inventory conditions

Do not use one global `spend_unit_scale` as a substitute for channel-specific cost mappings.

## Curves and economics

For log-link count models:

```text
incremental_response =
mu(with plan) - mu(counterfactual plan)
```

Use the full prediction function and explicit reference context.

Keep:

- outcome-scale incremental response
- log-scale eta contribution

as separate fields.

Marginal response should be calculated through the full model using a tested analytic derivative or a stable finite difference.

Channel economics:

- count channel cost once
- combine all eligible direct and halo responses before channel CPA/ROI
- do not output component CPA without explicit cost allocation

Portfolio marginal economics require an explicit allocation direction.

Curves must store:

- reference context
- counterfactual
- model-input axis
- monetary axis if available
- support provenance
- current-spend definition
- governance view
- uncertainty
- extrapolation status

## Steady-state versus sequential

Label steady-state curves and planner outputs explicitly.

At steady state, a fixed lag does not change the final plateau, but it changes response timing.

Do not use steady-state curves to answer:

- 0-3 month response
- 3-12 month response
- terminal carryover
- month-by-month optimisation

Those require sequential impulse-response simulation.

## Partial pooling

Do not alter hierarchy without:

- simulated recovery tests
- convergence checks
- out-of-sample comparison
- prior sensitivity
- identification assessment

Document the pooling structure by parameter class.

## Brand Search

Do not let diagnostic mediation code enter headline ROI or optimisation.

A production mediator model requires:

- explicit causal graph
- direct and indirect effects
- temporal structure
- uncertainty
- hierarchy
- measurement considerations
- identification tests

## Numerical reconciliation

Maintain tests proving consistency between:

- PyMC deterministics
- NumPy replay
- counterfactual curves
- attribution
- planning response
- scenario evaluation

Set and document numerical tolerances.

## Persistence boundaries

Dataclasses and model metadata written to bundles must have:

- explicit schema versions
- JSON-safe forms
- migrations
- round-trip tests

Do not persist opaque private objects when a stable portable representation is available.
