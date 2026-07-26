# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/pages`.

The root `AGENTS.md` also applies, including its outcome-registry, pathway-taxonomy, Search-object, capacity/cap, future-variable-role, and requirements-authority rules.

## Requirements authority

Pages must render the contracts supplied by core and repository-controlled requirements. They must not create new business labels, default outcomes, pathway meanings, approval rules, or scenario semantics from free-text interpretation.

## Thin UI rule

Streamlit pages are presentation and orchestration layers.

Do not implement model equations, CPA/ROI calculations, transformations, attribution, curve logic, or optimisation directly in a page.

Pages should call tested functions from `ancestry_mmm/core`.

## Portability

Write page workflows so the same core services can later be called by:

- FastAPI
- a React frontend
- batch jobs
- notebooks

Do not make Streamlit session state the only durable source of truth.

## Required labels

Every stakeholder output must label:

- outcome, its definition version, and approval status (never assume a pre-populated Net Bill Through default — see root `AGENTS.md`)
- segment
- market
- model type
- governance view
- reference context
- counterfactual
- steady-state or sequential method
- average or marginal metric
- channel-total or whole-plan scope
- currency
- uncertainty interval
- identification status
- extrapolation status

Where the output involves a future/planning variable, additionally label its **future-variable role** and **provenance** (manual, uploaded, prior-year, Chronos-2, another external forecast, generated endogenously, projected latent state, or fixed assumption).

Where the output involves a capacity-constrained pathway, additionally show, side by side rather than as one blended number: entered/recommended cap, expected realised spend or delivery, expected unused cap, cap-hit probability/state, latent demand, captured demand, and unmet demand where identified.

Where the output involves a linked pathway, show direct, mediated, and total effects separately (plus unconstrained-potential/unmet effect only where identified) — never present a single blended "funnel synergy" number without stating which of these it is.

Avoid generic labels such as:

- Contribution
- ROI
- CPA
- Curve

without the relevant scope.

## Outcome selection

The outcome selector must read from the approved outcome-definition registry (see root `AGENTS.md`), never assume or pre-populate Net Bill Through. For the selected outcome, show its formal definition, product/segment scope, event/date basis, source system, as-of and maturity rule (where applicable), reconciliation status, and which uses it is approved for (modelling, reporting, scenario planning, optimisation) independently of one another.

## Future-variable role UI

Every planning variable must show its one primary future role (planned decision, exogenous forecastable control, cost/translation assumption, endogenous funnel state, latent baseline state, fixed business assumption, historical diagnostic only, or not used in planning) and restrict the source-selection control to that role's allowed sources.

Block, as a blocking error rather than a warning:

- a planned decision sourced from Chronos-2 or another external forecast
- an endogenous mediator independently assigned an external forecast (a labelled stress-test override is allowed, but must retain and display the model-generated reference path alongside it)
- a latent baseline configured as an ordinary external-forecast target
- a lower-funnel cap and its expected realised spend entered as though they were the same decision

## Cap versus realised-spend UI

For any capacity-constrained/capped channel, the scenario/planning grid must keep cap and expected realised spend as visibly distinct fields. Expected realised spend must be read-only unless the scenario is explicitly defined in delivery terms rather than cap terms. Show cap-hit probability and expected unused cap alongside them, never implying that raising a non-binding cap guarantees additional spend or outcome.

## Curve UI

Do not display monetary CPA/ROI unless a valid monetary mapping exists.

When model input is not spend, show:

- model-input response curve
- media-input unit
- cost mapping status

and block monetary economics until cost mapping is supplied.

Direct and halo charts may show response decomposition. Do not show direct-only or halo-only CPA unless cost allocation is explicit.

A curve expressed in an approved downstream outcome must show the outcome definition/version and as-of date; it must never default to a "Net Bill Through" label before that outcome is approved.

## Search and demand-capture UI

Present the full-funnel Search object model as separate, explicitly labelled fields (branded-search demand, Paid Search spend, Paid Search delivery, Paid Search cap, organic/direct traffic, residual incrementality) rather than one generic "Brand Search" control or output.

Present demand-capture alternatives side by side:

- platform-reported
- raw MMM association
- excluded sensitivity
- assumption-adjusted
- experiment-calibrated

Do not display the OLS prototype, or any post-hoc reallocation, as production mediation.

## Save and resume

Any page that changes durable analysis state must:

- update the project state through shared persistence services
- invalidate stale downstream artefacts
- preserve a workflow checkpoint
- surface what must be rerun

Do not silently retain approval after a fit, pathway, data, transformation, outcome-definition, capacity/cap-rule, or future-variable-role change.

## Error handling

Block rather than guess when:

- the selected outcome's definition, maturity, or reconciliation status is incomplete for the requested use (modelling, reporting, planning, optimisation)
- currencies are missing
- cost mappings are missing
- observed support is missing for planning
- a capacity/cap rule is missing or a cap and realised delivery do not reconcile
- a future-variable role is missing or in conflict with its assigned source
- model and project fingerprints disagree
- governance review is incomplete

Apply the labels and fields above to the outputs where they are actually relevant — do not require every screen to show every field regardless of context.
