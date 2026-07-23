# Canonical posterior curves and economics (G2A)

`core.canonical_curves` is the non-UI source of truth for response curves,
economics, governance views, and curve exports. Existing point-estimate curve
helpers remain available for compatibility, but new reporting and planning
work should consume this contract.

The draw table grain is:

```text
model_run_id x market x product x segment x outcome_id x metric_key
x channel x component_type x pathway_role x spend_point x posterior_draw
```

Each row carries spend and response units, response and marginal response,
current/observed/planning spend support, adstock, lag, Hill parameters,
coefficient and pathway strength, attribution/headline/planning flags,
evidence and identification labels, and extrapolation state.

Average CPA, marginal CPA, average ROI, and marginal ROI are calculated on
each posterior draw. Undefined results remain `NaN` and have explicit status
fields for zero spend, invalid response, near-zero marginal response, unit
errors, currency errors, and missing outcome value. Spend-unit scaling and
currency conversion occur before economics are calculated.

`aggregate_curve_draws` aggregates response draws first and only then
recomputes economics. `summarize_curve_draws` creates means, medians, and
credible intervals from those draw-level values. Summarised medians must
never be added. `canonical_governance_views` provides segment, product,
market, FH net-bill-through, direct, halo, headline, and planning views.
Family History net bill-through is selected by the stable
`fh_net_billthrough_count` metric key.

`export_canonical_curve_bank` writes draw and summary Parquet tables plus a
versioned JSON schema. This is the machine-readable hand-off for future G2
Results, year-on-year, and planning interfaces.

Year-on-year consumers must distinguish movement along a stable curve from
cost inflation, mix changes, context changes, and a genuinely modelled
parameter change. A change in annual CPA alone is not evidence that a
channel coefficient changed.
