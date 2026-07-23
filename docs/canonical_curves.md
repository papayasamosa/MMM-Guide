# Outcome-scale counterfactual curves and economics (G2A.1)

`core.canonical_curves` is the non-UI source of truth for posterior curves,
economics, governance views, reconciliation, and curve exports.

## Response definition

The model uses a log link:

```text
mu = exp(eta)
```

Consequently, `beta × pathway_strength × Hill(spend)` is a contribution to
`eta`; it is not an incremental outcome count. The canonical draw table keeps
that quantity as `media_eta_contribution` and defines business response as:

```text
incremental_response =
mu(selected channel spend, explicit reference context)
- mu(counterfactual channel spend, same reference context)
```

Both means are calculated through the normal shared or market-specific NumPy
prediction function. The explicit `CurveReferenceContext` stores market,
trend, Fourier seasonality, promotions, controls, outcome controls,
other-channel spend, counterfactual spend, context mode, and reference period.
Supported modes are recent average, period average, specific week, specific
scenario, and steady-state reference.

Marginal outcome response is a scale-aware finite difference through the same
prediction function. The draw table records its method and delta.

## Economics

Component rows are a response decomposition. The channel's outcome-scale
incremental response is allocated across simultaneous direct and halo
components by incremental-eta share so the decomposition reconciles exactly.
No component CPA or ROI is calculated without a cost-allocation method.
An explicit `ComponentCostAllocation` may supply analyst-governed shares;
the allocation ID, method, and share are then stored with component economics.

`aggregate_curve_draws` aggregates components for one channel, counts channel
spend once, then calculates draw-level average/marginal CPA and ROI. It rejects
cross-channel aggregation. Whole-plan marginal economics require an explicit
`portfolio_path_id` and `PortfolioPerturbation` allocation direction.

## Support and currency

Observed support must come from the prepared frame or an approved support
table. Hill K is never used as observed support. Missing support produces:

```text
observed_support_status = missing
is_extrapolated = unknown
planning_support_eligible = false
```

Current spend supports latest complete week, last-4-week average,
last-13-week average, selected-period average, and uploaded plan definitions,
with the method and reference period stored in every curve.

Multi-market curves require explicit ISO local currencies, an ISO reporting
currency, an FX as-of date, and every necessary conversion rate. Local spend,
reporting-currency spend, and FX metadata are retained.

## Grain, summaries, and export

The component draw grain is:

```text
model_run_id × reference_context_id × market × product × segment
× outcome_id × metric_key × channel × component_type × pathway_role
× spend_point × posterior_draw
```

Totals are formed from posterior draws before `summarize_curve_draws` creates
means, medians, and intervals. `export_canonical_curve_bank` writes draw and
summary Parquet tables plus a versioned JSON schema.

The engine records exact counterfactual-prediction reconciliation and can
attach matched attribution reconciliation errors. Any historical attribution
comparison must use the same market, spend, context, counterfactual, and
governance assumptions.

Year-on-year consumers must still distinguish movement along a stable curve
from cost inflation, mix, context, and genuinely modelled parameter change.
