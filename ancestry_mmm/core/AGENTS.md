# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/core`.

The root `AGENTS.md` also applies, including its outcome-registry, pathway-taxonomy, Search-object, capacity/cap, future-variable-role, and requirements-authority rules. This file adds core-modelling-specific detail; it must not restate a weaker version of the root business rules.

## Requirements authority

Core modelling code must implement the supplied approved model specification. When a business definition or causal structure is not present in the implementation brief or repository-controlled requirements (see root `AGENTS.md`'s requirements authority), stop and request clarification rather than inferring it from an external product document.

## Core modelling policy

Core code must be framework-independent and testable without Streamlit.

Before editing adstock, saturation, priors, response curves, attribution, calibration, hierarchy, or optimisation:

1. inspect the current `pymc-labs/pymc-marketing` public implementation
2. inspect relevant examples and tests
3. document the gap
4. use upstream public APIs where they satisfy the Ancestry requirement
5. add numerical compatibility tests for custom equivalents

## Current implementation versus approved invariant versus target capability

When describing core behaviour, distinguish:

- **current implemented behaviour** — what the code does today
- **approved invariant** — a business or mathematical rule established by an approved requirements record that must never be violated (e.g. never aliasing NBT to GSA, never treating a cap as realised spend)
- **target platform capability** — a capability described in an approved implementation brief or requirements manifest but not yet built (e.g. the full capacity-constrained two-stage model, DNA halo, Chronos-2 integration)
- **backward-compatibility/migration requirement** — a rule that exists only to keep old saved projects loadable

Do not describe a current implementation choice (e.g. today's custom single-outcome-per-call model builders, or a project's markets currently being fit unpooled) as if it were a permanent invariant. Do not describe a target capability as already delivered.

## Current custom-model reality

The current application contains custom PyMC model builders for Ancestry's multi-outcome, pathway-governed structure.

Do not replace these blindly with a stock single-outcome MMM.

Preserve:

- multiple FH segment outcomes
- DNA outcomes
- market hierarchy (see root `AGENTS.md` — pooling choice is per approved use case, not fixed to unpooled)
- direct and cross-product pathway components
- component-specific lag and governance
- approved, versioned outcome semantics (see root `AGENTS.md`) and compatibility with existing saved projects that reference a legacy outcome label
- outcome-specific controls
- saved-project compatibility

Where PyMC Marketing does not directly support this structure, use it as an implementation and validation reference rather than forcing the business problem into an unsuitable API. See root `AGENTS.md`'s engine-capability boundary: record whether a given capability is native, extension-based, linked, planner-approximated, experimental, or unsupported.

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

## Capacity-constrained / censored pathway semantics

For an approved lower-funnel (or other) capacity-constrained pathway, keep the following objects distinct — never collapse two of them into one variable:

- `U_t` — upstream media and other demand-generating activity
- `X^L_t` — lower-funnel-stage controls
- `L*_t` — latent unconstrained lower-funnel demand/desired delivery (a model output, never a raw observed fact)
- `C_t` — observed budget, delivery, or operational cap
- `L_t` — realised lower-funnel spend/delivery (also a model output when demand is capacity-constrained, not a user-entered value)
- `X^Y_t` — final-outcome-stage controls
- `Y_t` — final commercial outcome

Conceptually:

```text
L*_t = f_L(U_t, X^L_t, baseline_L, adstock_L, saturation_L)
L_t  = g(L*_t, C_t, cost_t, epsilon_L_t)
Y_t  = f_Y(U_t, L_t, X^Y_t, baseline_Y, adstock_Y, saturation_Y)
```

This is a conceptual contract, not one mandated likelihood. The censoring/capacity mechanism (Tobit/censored continuous, censored count, hurdle/selection, deterministic cap mapping with uncertain latent demand, or a platform-specific opportunity/capture model) is chosen per approved model specification, but must satisfy:

- cap and realised-delivery units reconcile
- capped, uncapped, and ambiguous periods are identified and exposed, not silently pooled
- within-period cap changes are handled or explicitly excluded
- cap status is never derived using future information
- the mechanism can be simulated under a new, counterfactual cap

The lower-funnel stage and the final-outcome stage must support separate candidate specifications for baseline/trend, time-varying intercept, seasonality, promotions, price, macro/category controls, competitor variables, media transformations, and likelihood — a control appropriate for `L*_t` may be a bad control for `Y_t`, and vice versa.

Valid estimation patterns: joint Bayesian estimation of both stages; sequential posterior propagation (fit Stage 1, pass posterior draws — not point estimates — into Stage 2, preserving draw alignment); or an approximate planning emulator verified against the full model on key scenarios. A point-estimate plug-in without an explicit, documented approximation-error acknowledgement is not sufficient for a production total-effect uncertainty claim.

## Search decomposition

The model must distinguish, per the root `AGENTS.md`'s Search object model: branded-search demand, Paid Search spend and delivery, Paid Search cap/capacity, organic/direct navigation, and residual Paid Search incrementality. A variable named `brand_search` cannot enter the model until it is assigned one of these roles.

## Direct, mediated, and constrained-effect reconciliation

For upstream channel `j` on an approved pathway, derive where supported:

- **direct effect** — impact on `Y_t` not operating through the selected mediator
- **mediated effect** — impact through `L*_t` and realised `L_t`
- **total (realised) effect** — direct plus mediated effect under the specified cap: `total = direct + mediated`
- **unconstrained potential effect** — total effect under a counterfactual non-binding cap, only if identification supports it
- **unmet effect** — `unconstrained potential − realised total`, only when the unconstrained potential is itself identified

State explicitly whether other media, costs, baseline, and caps are held fixed or jointly varied when reporting an effect. Require:

- no double counting across direct, mediated, halo, and interaction components (the same effect must never appear simultaneously as direct upper-funnel contribution, mediated lower-funnel contribution, a generic upper×lower interaction, and a post-model Search-cost reattribution)
- posterior-draw-level reconciliation before any summary statistic
- the total effect reconciles to its approved components within numerical/posterior tolerance
- channel spend is counted once unless an explicit cost-allocation rule exists
- no component CPA or ROI without an approved cost allocation
- no claim of mediation from a post-hoc reallocation — legacy reattribution views (e.g. prior "Google Tax" adjustments) may be reproduced as a labelled comparison view, never as the production result

Do not weaken the existing log-link, counterfactual-response, monetary-mapping, or posterior-aggregation safeguards below when extending them to a linked/capacity-constrained pathway.

## Structural pathway before residual interaction

When a plausible causal mechanism is known (mediation, capacity constraint, cross-product halo, promotion moderation), model it directly before adding a generic interaction. A residual interaction represents only the incremental joint response remaining after structural pathways, common controls, adstock, and saturation have been represented — it must use strong shrinkage/hierarchical regularisation (prior expectation near zero absent experiment or strong domain evidence) and requires: a stated mechanism, directional expectation, time ordering, minimum support, a structural-overlap check (it does not duplicate a mediator, capacity, halo, or moderation term), an out-of-sample comparison, a stability test, and explicit approval.

## Endogenous-state generation and latent-baseline projection

- An endogenous funnel state (mediator) used in forward simulation must be generated by the approved causal model from the proposed plan — not independently forecast — for every ordinary scenario. An analyst override is a labelled stress test that must retain and display the model-generated reference path alongside it, never silently replace it.
- The time-varying intercept/latent baseline must be projected from its own fitted statistical process. It may be stress-tested, but must not be converted into an ordinary external-forecast (e.g. Chronos-2) target merely because it varies over time.
- Where a mediator has both an exogenous and a media-driven component, that decomposition (`M_t = M_t^{exogenous} + M_t^{media-driven}`) must be explicit, identified, and validated — not asserted.

## Uncertainty propagation for linked stages

Where a linked/capacity-constrained model's stages are estimated sequentially, propagate Stage 1 posterior draws into Stage 2 rather than plugging in point estimates, and quantify any approximation error against a fuller draw-based calculation. Do not claim full joint posterior uncertainty for a linked total effect while actually inserting a point-estimate mediator forecast into Stage 2, unless that approximation is explicitly documented and governed.

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

A curve expressed in an approved downstream outcome (see root `AGENTS.md`'s outcome registry) must additionally identify: outcome definition and version, analysis as-of date, maturity method, observed-versus-expected-final component, attribution from initial acquisition to the downstream outcome, and short-/long-term window. The label "Net Bill Through curve" must never be used as a default placeholder.

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

Document the pooling structure by parameter class. Market-specific estimation, partial pooling, no pooling, and governed curve/prior transfer are all legitimate choices per approved use case (see root `AGENTS.md`) — do not treat "all markets unpooled" as a permanent architectural constraint.

## Brand Search / demand-capture mediation

Do not let diagnostic mediation code enter headline ROI or optimisation.

A production mediator model requires:

- explicit causal graph
- direct and indirect effects
- temporal structure
- uncertainty
- hierarchy
- measurement considerations
- identification tests

Label any current Search demand-capture treatment as a sensitivity analysis (see root `AGENTS.md`'s Search object model) until the above is satisfied — do not describe it as production mediation or as a capacity-constrained model.

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
