# AGENTS.md

## Scope

These instructions apply to `ancestry_mmm/pages`.

The root `AGENTS.md` also applies.

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

- outcome and unit
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

Avoid generic labels such as:

- Contribution
- ROI
- CPA
- Curve

without the relevant scope.

## Curve UI

Do not display monetary CPA/ROI unless a valid monetary mapping exists.

When model input is not spend, show:

- model-input response curve
- media-input unit
- cost mapping status

and block monetary economics until cost mapping is supplied.

Direct and halo charts may show response decomposition. Do not show direct-only or halo-only CPA unless cost allocation is explicit.

## Brand Search UI

Present alternatives side by side:

- platform-reported
- raw MMM association
- excluded sensitivity
- assumption-adjusted
- experiment-calibrated

Do not display the OLS prototype as production mediation.

## Save and resume

Any page that changes durable analysis state must:

- update the project state through shared persistence services
- invalidate stale downstream artefacts
- preserve a workflow checkpoint
- surface what must be rerun

Do not silently retain approval after a fit, pathway, data, or transformation change.

## Error handling

Block rather than guess when:

- NBT completeness fails
- currencies are missing
- cost mappings are missing
- observed support is missing for planning
- model and project fingerprints disagree
- governance review is incomplete
