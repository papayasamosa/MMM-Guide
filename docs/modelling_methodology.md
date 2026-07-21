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

## Market-specific model - "Model C" (Phase 2 - built)

`ancestry_mmm.core.market_specific_model.build_fh_market_specific_model` builds Model C: structurally
identical to Model A above (same likelihood, DNA halo pathway, promo/control/trend/seasonality
terms, market baseline pooling) except for two parameters:

```
Global channel pattern
    -> Market-specific channel curve
        -> Segment-specific response within each market
```

- **Response strength:** `beta[market, segment, channel]`, built as the simplest identifiable
  additive form on the log scale - `log_beta[market, segment, channel] = mu_channel[channel] +
  market_dev[market, channel] + segment_dev[segment, channel]` - deliberately with **no free
  market x segment x channel interaction term**, per the redesign brief's own "start simple"
  guidance. Both `market_dev` and `segment_dev` are hierarchically pooled (non-centered
  parameterisation: `sigma * z_offset`, `sigma ~ HalfNormal`).
- **Saturation point:** `K[market, channel]`, on the log scale:
  `log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])`, implemented as
  `hill_K = global_hill_K * exp(market_K_sigma * z_market)` - a Gamma-distributed global anchor
  (same prior family as Model A's `K`) with a log-normal market deviation. Market-specific and
  partially pooled - this is the single biggest structural change from Model A.
- **Adstock decay:** `decay[channel]` stays shared across markets in this first production version,
  per the redesign brief's own preference ("adstock is difficult to estimate, so do not make it
  highly flexible in the first implementation unless simulation and diagnostics support it").
  `decay[market, channel]` with strong pooling is a documented next step, not a Phase 2 commitment
  (`docs/decision_log.md`).
- **Hill slope:** `S[channel]` stays shared, same reasoning; `S[market, channel]` only once
  diagnostics/simulation recovery justify it.
- **Baseline:** `market_offset[market, segment]` - unchanged from Model A (already market-specific
  there via the existing market pooling mechanism).

Model A (`build_fh_hierarchical_model`) is untouched and remains fully available side by side - both
models share the same `frame`/`spec` inputs and `FHModelMeta` return type. Model C needs its own
posterior-extraction and NumPy curve-replay module (`core.market_specific_predict`,
`FHMarketSpecificPosteriorParams`) since `hill_K` and `beta` carry an extra market dimension; the
scorecard equivalent is `core.market_specific_diagnostics.compute_scorecard_market_specific`.
Requires at least 2 markets - partial pooling across a single market is meaningless.

Curve bank storage, Shapley attribution (`core.market_specific_attribution`, market-aware - each
row uses its own market's `beta`/`hill_K` rather than Model A's shared curve), and Scenario Planner
are all available for Model C. Market-specific curves can be reviewed via a dedicated curve viewer
(Results & Curve Bank) using `core.market_specific_predict.generate_market_channel_curve`, with an
optional per-draw posterior uncertainty band (`core.uncertainty`).

## Priors

Current priors (`utils/config.py::DEFAULT_FH_PRIORS`, editable on Model Configuration) are the
starting point for the shared, channel-level components in both Model A and Model C. Model C adds
market-level hyperpriors on top: `market_K_sigma_prior`, `market_beta_sigma_prior` (both
`HalfNormal`, default scale 0.3).

## Model comparison (Phase 2 - built, see `docs/model_validation.md`)

Three candidate structures can be compared before a partially-pooled model is adopted:
Model A (one shared curve), Model B (independent per-market models - achieved by fitting Model A's
existing builder against a single-market-sliced frame, `core.model_comparison.slice_frame_to_market`
- no new model-building code needed), Model C (partially pooled, market-specific,
`core.market_specific_model`). `core.model_comparison.ModelComparisonCandidate` records one fitted
candidate's scorecard at a time (fitting three real models behind one button would be slow and
blocking); `pages/12_Compare_Models.py` is where candidates are saved and compared side by side. The
partially pooled model isn't accepted merely for being more sophisticated - it has to show
comparable-or-better prediction, credible market differentiation, stable curves, sensible shrinkage,
and acceptable diagnostics.

## Model identity and approval

`core.fingerprint.fingerprint_model_spec` includes `model_type` ("shared" or "market_specific") in
its hash payload, so switching model structure - even with identical spec/priors/DNA lag -
invalidates any existing approval, same as changing the data or specification would.
