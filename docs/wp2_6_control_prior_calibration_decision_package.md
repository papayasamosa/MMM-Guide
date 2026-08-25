# WP2.6 items 1 & 2: control-prior calibration decision package (2026-08-24)

Status: decision package. This document reports a bounded `control_sigma`
sensitivity grid and the per-control decomposition the analyst requested.
**It recommends candidate values and explains their substantive
implications; it does not select the production `control_sigma` value.**
The analyst's WP2.5 approval covers direction only ("continuous model
controls should use a governed standardised representation, with the
coefficient prior explicitly calibrated for the standardised scale") -
not an exact value, and is not permission to begin WP3 full-fit NUTS
sampling.

Evidence source: `scripts/run_uk_wp2_6_control_prior_calibration.py`, run
against the real approved UK source pack, prior-predictive sampling only
(no NUTS/MCMC, no observed data read by the sampler). Raw output is at
`D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-6-control-prior-
20260824\wp2_6_{model_name}.json`. No production code changed to produce
this evidence - both `core.control_scaling` (standardisation) and
`prior_config["control_sigma"]`/`prior_config["enable_control_scaling"]`
(the coefficient prior) already exist and are already gated off by
default; this script only exercises them via prior-predictive sampling.

## 1. Per-control decomposition

Each governed model has **exactly one** continuous control - there is no
column-selection question to resolve:

| Model | Control | Raw range | Raw mean / median | Raw std | n obs | Inferred type |
|---|---|---|---|---|---|---|
| Family History | `fh_category_demand_google_trends` | 45.0-96.0 | 58.6 / 57.0 | 7.37 | 119 | continuous_or_count_index |
| DNA Kit | `dna_category_demand_google_trends` | 40.0-100.0 | 49.3 / 47.0 | 9.95 | 119 | continuous_or_count_index |

Both are Google-Trends-style category-demand indices (integer-valued,
bounded roughly 0-100, `n_distinct` 26-28 across 119 weeks) - not binary/
event indicators, so the "do not auto-standardise binary controls"
constraint does not bind for either model; there is no other control
type present to misclassify. `governed_role` beyond the generic context/
external-factor domain classification is not recorded anywhere in
`docs/approved_requirements/` or `AGENTS.md` - this is descriptive, not a
gap this document proposes to fill.

**Before/after scaling, at the current default `control_sigma=0.5`, on
the log-link linear predictor's `eta_controls` component** (this is the
central WP2.5 finding, now directly reproduced and quantified):

| Model | Representation | eta_controls q05 | median | q95 |
|---|---|---|---|---|
| Family History | raw (unscaled), `control_sigma=0.5` | -48.69 | -0.475 | 48.86 |
| Family History | standardised, `control_sigma=0.5` | -0.663 | 0.001 | 0.665 |
| DNA Kit | raw (unscaled), `control_sigma=0.5` | -40.58 | -0.391 | 40.89 |
| DNA Kit | standardised, `control_sigma=0.5` | -0.543 | 0.001 | 0.545 |

On the raw (unscaled) representation, the same `Normal(0, 0.5)`
coefficient prior is applied to a control whose raw values range 40-100 -
so the 90% prior interval for `eta_controls` spans roughly ±40 to ±49 on
the *log* scale, i.e. multiplicative factors on `mu` of `exp(48.9) ~
3e21` at the extreme. This is not a subtle miscalibration; it is the
mechanism directly responsible for WP2.5's implausibly wide
prior-predictive `mu` ranges. Standardising the control (one unit = one
raw SD) brings the same prior's 90% interval down to a defensible
±0.54-0.66 on the log scale (multiplicative factor `exp(0.66) ~ 1.9x` at
the tail) - a sane, interpretable range. **This is strong, direct
confirmation that the analyst's approved remedy direction (governed
standardised representation with a prior calibrated for that scale) is
substantively correct and necessary**, independent of which exact
`control_sigma` is eventually chosen.

## 2. `control_sigma` sensitivity grid (standardised representation, both
models identical by construction)

Because both models have exactly one standardised continuous control and
`control_coef`'s prior-predictive distribution is `exp(Normal(0,
control_sigma))` with no other frame-dependent structure, the
multiplicative-effect-per-SD quantiles come out numerically identical
for Family History and DNA Kit (Monte Carlo estimates over
238,000-357,000 draws; the small difference in draw count is a residual
of each model's chain-count configuration, not a data difference):

| `control_sigma` | q01 | q05 | median | q95 | q99 | Clipped at ceiling (1e9) |
|---|---|---|---|---|---|---|
| 0.05 | 0.894 | 0.918 | 0.997 | 1.082 | 1.114 | 0 |
| 0.10 | 0.798 | 0.843 | 0.994 | 1.170 | 1.242 | 0 |
| 0.20 | 0.637 | 0.710 | 0.989 | 1.369 | 1.542 | 0 |
| 0.30 | 0.509 | 0.599 | 0.984 | 1.601 | 1.916 | 0 |
| **0.50 (current default)** | 0.324 | 0.425 | 0.973 | 2.192 | 2.955 | 0 |
| 1.00 | 0.105 | 0.181 | 0.946 | 4.806 | 8.731 | 17 (FH) / 15 (DNA) |

Interpretation: "multiplicative change in `mu` for a +1 standard-
deviation move in the standardised control." At `control_sigma=0.05`, a
one-SD move in category demand implies at most an 8-11% change in
outcome volume at the 5th/95th percentile - a fairly tight prior belief.
At the current default `0.5`, the 90% interval is a 0.43x-2.19x
multiplicative range - already wide for what is, substantively, a
secondary context control rather than a primary media channel. At `1.0`,
the interval widens to 0.18x-4.81x, and this is the only grid point
where any prior-predictive `mu` draws hit the numerical ceiling clip
(1e9) - 17 of 357,000 draws for Family History, 15 of 238,000 for DNA
Kit (both ~0.005-0.006%, small in proportion but a genuine, non-zero
pathology signal that only appears at this end of the grid).

**Full `mu` quantiles per outcome, and their ratio to observed scale**
(representative grid points; full detail for all six points and all five
outcomes is in the raw JSON):

| Model | Outcome | sigma | mu q05 | mu q50 | mu q95 | median/observed-median | q95/observed-q95 | max/observed-max |
|---|---|---|---|---|---|---|---|---|
| FH | new | 0.1 | 572 | 4,944 | 40,072 | 1.97x | 11.9x | 172x |
| FH | new | 0.5 | 503 | 4,946 | 46,054 | 1.97x | 13.6x | 4,427x |
| FH | new | 1.0 | 389 | 4,912 | 62,368 | 1.96x | 18.4x | 299,132x |
| FH | dna_cross_sell | 0.5 | 437 | 4,343 | 40,730 | 2.27x | 10.1x | 2,851x |
| FH | winback | 0.5 | 283 | 2,737 | 27,404 | 2.19x | 8.1x | 1,476x |
| DNA | new_customer | 0.1 | 671 | 5,294 | 44,845 | 2.71x | 5.8x | 76.5x |
| DNA | new_customer | 0.5 | 592 | 5,326 | 49,729 | 2.72x | 6.4x | 2,786x |
| DNA | new_customer | 1.0 | 474 | 5,310 | 62,469 | 2.71x | 8.1x | 77,769x |
| DNA | existing_fh_customer | 0.5 | 242 | 2,454 | 22,469 | 2.58x | 7.3x | 596x |

Two patterns worth the analyst's attention:

- **The median-scale ratio is essentially flat across the whole grid**
  (FH new: 1.96x-1.97x; DNA new_customer: 2.71x-2.72x) - because the
  standardised control's coefficient prior is zero-mean, so the median
  prior-predictive outcome barely moves regardless of `control_sigma`.
  This is expected and reassuring: the control_sigma choice mainly
  governs *tail width*, not central tendency, which is the correct
  qualitative behaviour for a secondary context control.
- **The `max`-to-observed-`max` ratio explodes at higher `control_sigma`**
  (172x -> 4,427x -> 299,132x for FH new_customer across 0.1 -> 0.5 ->
  1.0), driven by the extreme upper tail interacting multiplicatively
  with the model's other components (media, seasonality) rather than the
  control alone - this ratio should not be read as "the control causes a
  299,132x outcome," but as a signal of how much a wide control prior
  can amplify an already-wide joint prior-predictive tail. All of these
  ratios are large in absolute terms at every grid point (even at
  `sigma=0.05` the model's overall prior-predictive tail is wide,
  consistent with WP2.5's broader finding that this is a joint,
  multi-component phenomenon, not solely a control-prior problem) - the
  grid isolates *how much worse the control prior specifically makes it*,
  not whether the overall prior is fully resolved by this document alone.

## Candidate values and their implications (not a selection)

- **`control_sigma` in the 0.05-0.2 range**: tightest tail behaviour,
  zero ceiling-clipping at every grid point checked, multiplicative
  effect per SD bounded within roughly 0.64x-1.54x at the 99th
  percentile. Implication: a strong prior belief that category demand
  has a modest, bounded influence relative to media and seasonality.
  Defensible if the analyst's substantive view is that this control
  should function as a mild adjustment, not a competing driver.
- **`control_sigma = 0.3`**: intermediate; 99th-percentile effect bounds
  roughly 0.51x-1.92x, still zero clipping observed in this grid.
- **`control_sigma = 0.5` (current default)**: 99th-percentile effect
  bounds roughly 0.32x-2.96x, zero clipping observed in this grid, but
  the widest point with zero clipping and the point immediately before
  clipping starts to appear.
- **`control_sigma = 1.0`**: the only point where numerical ceiling-
  clipping was observed (a small but genuine pathology - 0.005-0.006% of
  draws), and the tail effect bound reaches roughly 0.10x-8.7x at the
  99th percentile - implying category demand could plausibly move the
  outcome by nearly an order of magnitude on its own under the prior,
  which is difficult to justify substantively for a secondary context
  control alongside 18-19 media channels.

This document does not recommend a single value on the analyst's behalf.
The evidence supports treating **0.5 as an upper bound worth
reconsidering downward** (it is the last clipping-free point, but its
99th-percentile tail is already wide for a secondary control) rather
than a starting point to widen further; values below roughly 0.2-0.3
would be the more conservative, tail-safe candidates if the analyst's
intent is that this control should have materially less prior
flexibility than the channel-level media parameters.

## Governance and scope

No `prior_config` default changed in production code. No channel
removed, pooled, or retransformed. `enable_control_scaling` remains
gated off by default; this evidence supports (but does not itself
authorise) flipping that default as part of a future, explicitly
approved change once the analyst selects a `control_sigma`. This
document is diagnostic/prior-predictive-only and does not authorise WP3
full-fit NUTS sampling.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.6 investigation and who holds final authority over the
selected `control_sigma` value and the decision to enable standardised
control scaling in production. Status: grid and decomposition supplied
for review; no value selected; no WP3 authorisation implied.
