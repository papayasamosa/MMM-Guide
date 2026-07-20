# Modelling Methodology

## Current model (what's actually fitted today)

`ancestry_mmm.core.hierarchical_model.build_fh_hierarchical_model` builds and
`ancestry_mmm.core.models.fit_model` fits, via PyMC/NUTS, a joint hierarchical model with:

- **Likelihood:** Gaussian on log-transformed segment outcomes (see `core/models.py`,
  `core/transformations.py::log_transform`).
- **Adstock:** geometric adstock per channel, `decay[channel]` - shared across markets and segments
  (`core/transformations.py::geometric_adstock_matrix`, `pt_geometric_adstock_matrix`).
- **Saturation:** Hill function per channel, `K[channel]`, `S[channel]` - shared across markets and
  segments (`core/transformations.py::hill_function`, `pt_hill_function`).
- **Hierarchy / pooling:** segment response strength and DNA halo strength are partially pooled
  across the three FH segments via `pooling_sigma_prior`; markets are partially pooled by default,
  with an explicit per-market "unpooled" override (`ModelSpec.unpooled_markets`).
- **Segment effects:** each segment has its own intercept, trend coefficient, promo sensitivity, and
  channel response strength (`beta[segment, channel]`), drawn from a shared distribution.
- **DNA halo:** an explicit `halo_strength[segment]` pathway - fixed at 1.0 for the DNA cross-sell
  segment, partially pooled toward zero for other segments, so DNA-targeted media's effect on
  non-DNA segments is estimated, not assumed.
- **Controls:** global (all-segment) and segment-specific numeric controls, plus Fourier seasonality
  and a linear trend per segment.
- **Uncertainty:** full posterior via MCMC (not a point estimate); diagnostics (R-hat, ESS,
  divergences) gate whether the fit is trusted at all before approval is even offered.
- **Fitting process:** `core.models.fit_model` runs NUTS via `pm.sample`, single-core so live
  progress can be shown in the UI (`pages/05_Model_Training.py`).
- **Diagnostics:** convergence, in-sample fit, posterior predictive coverage, and curve/ROI
  plausibility flags (`core/diagnostics.py::compute_scorecard`), plus an optional expanding-window
  backtest.
- **Approval rules:** a model can only be approved after its scorecard is computed; approval is
  bound (via SHA-256 fingerprints) to the exact data, specification, and posterior it was reviewed
  against, and is automatically invalidated the instant any of those three changes
  (`core/approval.py`, `core/fingerprint.py`).

The key limitation this redesign addresses: **`decay`, `K`, `S`, and (indirectly, through the
shared `K`/`S`) the saturation shape are identical across every market.** Only segment-level
response (`beta[segment, channel]`) and the DNA halo already vary within a market. Two markets with
very different audience sizes, media costs, and channel maturity are forced onto the same curve.

## Target model (Phase 2 onward - see `docs/market_hierarchy.md`)

```
Global channel pattern
    -> Market-specific channel curve
        -> Segment-specific response within each market
```

- **Response strength:** `beta[market, segment, channel]`, hierarchically pooled across markets and
  segments (not independent, not forced identical).
- **Saturation point:** `K[market, channel]`, on the log scale:
  `log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])`. Market-specific
  and partially pooled - this is the single biggest structural change.
- **Adstock decay:** `decay[channel]` stays shared across markets in the first production version of
  Phase 2, per the redesign brief's own preference ("adstock is difficult to estimate, so do not
  make it highly flexible in the first implementation unless simulation and diagnostics support
  it"). `decay[market, channel]` with strong pooling is a documented next step, not a Phase 2
  commitment.
- **Hill slope:** `S[channel]` stays shared initially, same reasoning; `S[market, channel]` only
  once diagnostics/simulation recovery justify it.
- **Baseline:** `baseline[market, segment]` - already effectively how segment intercepts work today,
  extended to vary by market too.

## Priors

Current priors (`utils/config.py::DEFAULT_FH_PRIORS`, editable on Model Configuration) stay as the
starting point for the shared, channel-level components. Phase 2 adds market-level hyperpriors
(`market_K_sigma`, market-level `beta` pooling strength) rather than replacing what exists.

## Model comparison (Phase 2 deliverable, see `docs/model_validation.md`)

Three candidate structures get compared before the partially-pooled model is adopted as the default,
per the redesign brief: Model A (one shared curve - today's model), Model B (independent per-market
models), Model C (partially pooled, market-specific). The partially pooled model isn't accepted
merely for being more sophisticated - it has to show comparable-or-better prediction, credible
market differentiation, stable curves, sensible shrinkage, and acceptable diagnostics.
