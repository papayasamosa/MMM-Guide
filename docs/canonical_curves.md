# Outcome-scale counterfactual curves and economics (G2A.2)

`core.canonical_curves` is the non-UI source of truth for posterior curves,
economics, governance views, reconciliation, and curve exports.

## Response definition

The model uses a log link:

```text
mu = exp(eta)
```

Consequently, `beta × pathway_strength × Hill(media input)` contributes to
`eta`; it is not an incremental outcome count. The canonical draw table keeps
that quantity as `media_eta_contribution` and defines business response as:

```text
incremental_response =
mu(selected channel media input, explicit reference context)
- mu(counterfactual channel media input, same reference context)
```

Both means are calculated through the normal shared or market-specific NumPy
prediction function. The explicit `CurveReferenceContext` stores market,
trend, Fourier seasonality, promotions, controls, outcome controls,
other-channel media input, counterfactual axis value, context mode, and
reference period. Supported modes are recent average, period average, specific
week, specific scenario, and steady-state reference.

Marginal outcome response is a finite difference through the same prediction
function. The draw table records its method and media-input delta.

## Economics

Component rows are a response decomposition. The channel's outcome-scale
incremental response is allocated across simultaneous direct and halo
components by incremental-eta share so the decomposition reconciles exactly.
No component CPA or ROI is calculated without a cost-allocation method. An
explicit `ComponentCostAllocation` may supply analyst-governed shares; its ID,
method, and share are stored with component economics.

`aggregate_curve_draws` aggregates components for one channel and counts
channel spend once. It calculates draw-level average/marginal CPA and ROI only
for a monetary curve backed by an approved effective cost mapping. It rejects
cross-channel aggregation. `counterfactual_incremental_cpa` names spend and
response relative to the configured counterfactual; `average_cpa_scope`
distinguishes zero from nonzero counterfactuals.

Whole-plan marginal economics require an explicit `portfolio_path_id` and
`PortfolioPerturbation` allocation direction. Direct and halo governance views
are response-only unless a separately governed component cost allocation
exists. The former `market` view is named `market_channel_metric` because
channel remains in its grain.

## Media input, support, and currency

`curve_type=model_input` varies the quantity supplied to adstock/saturation and
is available without cost data. `curve_type=monetary` maps local spend through
an approved `core.media_costs` mapping before prediction. Identity, fixed
cost-per-unit, piecewise-linear, and uploaded-plan mappings are supported at
market × channel × cost-context grain.

Monetary marginal response records both `d outcome / d media input` and
`d media input / d local currency`, then applies FX to obtain
`d outcome / d reporting currency`.

Observed support must come from the prepared frame or an approved support
table. Hill K is never used as observed support. Missing support produces:

```text
observed_support_status = missing
is_extrapolated = unknown
planning_support_eligible = false
```

Current support can use latest complete week, last-4-week average,
last-13-week average, selected-period average, or an uploaded plan. Its method
and reference period are stored in every curve.

Multi-market monetary curves require explicit ISO local currencies, an ISO
reporting currency, an FX as-of date, and every necessary conversion rate.
Local spend, reporting-currency spend, and FX metadata are retained.

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
attach matched attribution reconciliation errors. Historical attribution
comparison must use the same market, input, context, counterfactual, and
governance assumptions. Every curve is labelled `steady_state` and as a
representative context rather than historical attribution.

Year-on-year consumers must still distinguish movement along a stable curve
from cost inflation, mix, context, and genuinely modelled parameter change.
