# WP2.9: Model A certification diagnostics, sampler resolution, and
# product-level posterior outputs (2026-08-25)

Status: evidence for analyst review. **This document does not certify
Model A, and does not authorise Model B, Search mediation, optimisation,
or any separately fitted FH Overall / DNA Overall challenger model.** No
statistical specification changed to produce this evidence — control
scaling/`control_sigma`, media channel set, adstock priors, Hill K/S
priors, seasonality/Fourier priors, trend, pooling, causal graph,
sparse-channel treatment, and fold policy all remain exactly as frozen at
the WP2.7/WP2.8 state, except item 1's fingerprint-plumbing repair, which
is a governance-identity fix, not a modelling change.

All evidence below is real, computed against the actual UK historical
source pack. Scripts: `scripts/run_uk_wp2_9_divergence_localization.py`,
`scripts/run_uk_wp2_9_fit_and_temporal_diagnostics.py`,
`scripts/run_uk_wp2_9_product_level_totals.py`,
`scripts/run_uk_wp2_9_identification_business_impact.py` (PR #314).
Item 1's fingerprint repair is PR #313 (merged `385d1b0b`).

## Item 1: pre-fit fingerprint plumbing — repaired

`scripts/run_uk_prefit_governance.py` never passed `candidate_spec`/
`prepared_frame` through to `review_prefit_identifiability`, so
`candidate_spec_fingerprint`/`prepared_frame_fingerprint` resolved to
`sha256("null")` for every governed UK pre-fit run since WP2. Fixed by
passing the real `ModelSpec`/prepared frame through
(`ancestry_mmm/core/prefit_identifiability.py`,
`scripts/run_uk_prefit_governance.py`). `causal_graph_fingerprint`
legitimately stays at the null fingerprint: this candidate genuinely uses
no explicit causal graph override (`resolve_engine`'s `causal_graph is
None` branch — the default pathway-catalogue engine), so `None` is the
real value, not a defect. Added a fail-closed gate in
`official_submission_allowed`: a null/placeholder `candidate_spec_
fingerprint`/`prepared_frame_fingerprint` now blocks official submission
regardless of readiness or retained rationale — verified with new tests.

**Consequence honoured under existing staleness rules**: this is a
fit-relevant identity change (the fingerprints WP2.7/WP2.8's evidence was
recorded against are now provably different from the corrected ones —
`prefit_run_is_stale` will report `prepared_frame_fingerprint`/
`candidate_spec_fingerprint` mismatches). **The WP2.7/WP2.8 analyst
rationale was retained against evidence whose candidate-spec/prepared-
frame identity binding was not actually real at the time** — this is
recorded here transparently rather than retrospectively claimed as
stronger than it was. The WP2.8 posterior itself remains valid diagnostic
modelling evidence (the fingerprint defect was in the pre-fit *review*
identity binding, not in the fit that was actually run against the real
frame) — but re-retention of rationale against the corrected fingerprints
is a **pending action**, not yet done as part of WP2.9 (see "Outstanding
before certification" below).

## Item 2: WP2.8 divergence localisation

Real, not `<1%`-dismissed. Both products' divergences show a consistent
signature: they concentrate in the **hierarchical pooling geometry**
(`mu_channel`, `sigma_pool`), not in a single runaway channel.

**Family History** (70/8,000 divergent draws, by chain 17/14/16/23):
- Largest standardised shifts (divergent vs. non-divergent, Cohen's d):
  `mu_channel[uk_tv_sponsorship_linear]` d=0.54, `sigma_pool[18]` d=0.46,
  `decay_rate[uk_tv_sponsorship_linear]` d=0.46, `mu_channel[uk_bvod]`
  d=0.34, `hill_S[uk_brand_tv]` d=0.32. Boundary clustering is mild (2–20%
  of divergent draws sit beyond the whole posterior's 5%/95% tails per
  parameter — not extreme concentration at a hard boundary).
- Correlation-structure shift: `decay_rate[uk_brand_tv]` vs.
  `hill_K[uk_fh_performance_display]` flips from r=+0.36 (non-divergent)
  to r=−0.29 (divergent); `hill_S[circulation]` vs. `sigma_pool` flips
  from r=−0.18 to r=+0.39. Energy Cohen's d=0.16 (mild).
- **Channel-contribution stability** (matched divergent vs. non-divergent
  draw Shapley attribution): median contribution differs by up to
  **43.5%** (`uk_tv_sponsorship_linear`), 33.3% (`circulation`), 27.1%
  (`uk_fh_non_brand_search`), −23.4% (`uk_influencer`), −20.6%
  (`uk_fh_performance_social`).

**DNA Kit** (53/8,000 divergent draws, by chain 24/13/1/15):
- Largest shifts: `mu_channel[uk_dna_non_brand_search]` d=0.64,
  `mu_channel[uk_dna_affiliate]` d=0.59, `decay_rate[uk_dna_non_brand_
  search]` d=−0.45, `mu_channel[uk_bvod]` d=0.43, `trend_coef` d=0.41.
- Correlation shift: `hill_K[uk_tv_sponsorship_linear]` vs.
  `hill_S[uk_drtv]` flips from r=−0.37 to r=+0.45 (largest shift of
  either product).
- **Channel-contribution stability**: median differs by up to **77.9%**
  (`uk_dna_non_brand_search`), 26.2% (`uk_influencer`), −26.1%
  (`uk_dna_content_marketing`), 24.5% (`uk_dna_affiliate`).

**Answer to the actual question posed**: yes, the divergent-draw geometry
is materially different for several channels' reported contribution — up
to a 78% swing in median attributed volume for the single most-affected
channel (DNA non-brand search). This is evidence *against* treating the
divergences as immaterial noise, independent of any `<1%` draw-count
threshold. It does not by itself show *which* number (divergent-region or
non-divergent-region) is more correct — that is exactly the sampler
sensitivity question item 3 addresses.

## Item 3: sampler sensitivity at target_accept=0.95

**Status: fit running; see the follow-up decision package
(`docs/wp2_9_sampler_sensitivity_decision_package_20260825.md`, added
once both models' 0.95 fits complete) for the comparison.** Both
Family History and DNA Kit are running at `chains=4, draws=2000,
tune=1000, target_accept=0.95` — the repository's existing `--target-
accept` flag on the unmodified `scripts/run_uk_production_fit.py`, the
same flag WP2.7's short screen already used at 0.95 (real precedent, not
an invented configuration). Nothing else changed. Traces at
`D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-target-accept-
0.95-20260825\`.

## Item 4: Family History "New" fit diagnosis

- Observed: mean=2,578.7, median=2,509, std=473.9, **CV=0.184**,
  range=[1,693, 4,593], n=119 weekly observations.
- Model RMSE=455.6, MAE=344.5. **Mean-only baseline RMSE=471.9,
  MAE=356.9 — the model is only 3.44% better than a flat mean by RMSE**
  (3.45% by MAE). A diagnostic-only 52-week seasonal-naive baseline is
  markedly *worse* (RMSE=539.3, MAE=394.0, n=67 comparable weeks) — the
  model is not failing to beat a naive alternative; it is failing to
  explain much of this outcome's variance at all.
- Residual lag-1 autocorrelation=0.41 (matches WP2.8's own report).
- **Diagnosis**: the poor R² (0.068 at target_accept=0.90) is primarily
  driven by **low exploitable signal relative to noise in this specific
  outcome**, not by missed peaks/troughs or an obviously wrong baseline
  shape — the model barely outperforms a flat mean, so almost all of the
  outcome's modest variance is being treated as noise by every candidate
  predictor tried (media, controls, trend, season). Item 5's evidence
  below narrows this further: FH New's residuals move almost in lock-step
  with FH Winback's, pointing at a *shared* omitted driver rather than an
  FH-New-specific misspecification.
- Largest positive/negative residual weeks and the full actual-vs-
  predicted/residual series are in the evidence JSON
  (`wp2_9_fit_and_temporal_diagnostics_family_history.json`) for further
  analyst inspection; no single week dominates.

## Item 5: common unexplained temporal structure

**Family History**: residual correlation is r=**0.77** between FH New and
FH Winback, but only r=0.07 (New/DNA-cross-sell) and r=0.04
(DNA-cross-sell/Winback). 15 weeks show ≥2 outcomes simultaneously in
their own top/bottom residual decile — overwhelmingly New+Winback moving
together (e.g. 2023-01-29, 2023-07-30, 2023-08-06 both in the top decile
for both; 2023-02-05 both in the bottom decile). Per-outcome residual
correlation with trend/first-Fourier-term/first-control/total raw media
spend is small for all three outcomes (|r|<0.20) — the omitted structure
is not simply a mis-shaped version of an already-included covariate.

**DNA Kit**: residual correlation between DNA New and DNA Existing-FH-
customer is r=**0.96** — almost the same unexplained signal drives both
outcomes. 16 shared-extreme weeks. Per-outcome correlations with trend/
season/controls/media are again all small (|r|<0.06).

**Diagnosis**: both products show strong evidence of a **shared, product-
level omitted temporal/demand component** — for DNA, essentially a single
common factor (r=0.96) affecting both outcomes almost identically; for FH,
a strong but more selective one linking New and Winback specifically
(r=0.77) while leaving DNA-cross-sell nearly independent. Because the
correlation with the model's own trend/seasonality/control/media terms is
uniformly small, this looks like **inadequate baseline dynamics or a
missing common demand shock**, not a mis-specified shape of an existing
term. No remedy (autoregressive error, time-varying intercept, new
Fourier order, new control) was implemented or selected here per the
explicit instruction not to; this is reported as evidence supporting a
**future specification decision**, not an in-flight change.

## Item 6: PSIS-LOO/WAIC and backtest

**LOO/WAIC** (`core.diagnostics.predictive_density_summary`, no new
mechanism): Family History elpd_loo=−2,728.5 (se=18.5), p_loo=34.1,
elpd_waic=−2,727.9, p_waic=33.5, n=357 obs×outcome cells; DNA Kit
elpd_loo=−1,901.3 (se=17.4), p_loo=26.6, elpd_waic=−1,900.6, p_waic=26.0,
n=238 cells. Pareto-k: DNA has **zero** bad/very-bad k values across all
238 cells. FH has exactly **one** bad-but-not-very-bad k (0.77, against a
good-k threshold of 0.70) for FH Winback, out of 119 weeks — an isolated,
non-systemic flag, not a pattern. PPC 90% coverage: FH New 95.0%, FH
DNA-cross-sell 90.8%, FH Winback 94.1%, DNA New 93.3%, DNA Existing 90.8%
— all close to or slightly wide of nominal, no under-coverage concern.
Standard PSIS-LOO caveat applies and is preserved: this model has
adstock/trend/seasonality-induced temporal dependence, so leave-one-out's
exchangeability assumption is weaker here than for genuinely independent
observations — reported as evidence, not asserted as unconditionally
valid.

**Backtest — not run, documented limitation**: the repository's governed
leakage-safe fold-refit backtest
(`application.fold_refit_service.run_leakage_safe_fold_refit_from_
sources`) requires registered `SourceVersion` upload-timing events to
assess point-in-time reconstruction validity per fold
(`core.validation_folds.assess_fold_source_reconstruction`). This
standalone historical exercise loads a static source pack via `--pack-
dir` with no `SourceVersion` registration at all (confirmed: `grep
SourceVersion scripts/run_uk_production_fit.py` returns nothing) — there
is no real upload timeline to assess folds against. Running it would
require inventing SourceVersion registration data that does not exist for
this one-off exercise, which this work package was explicitly told not to
do. The lighter, non-leakage-safe `run_leakage_safe_fold_refit` (an
already-prepared-frame variant, `RECONSTRUCTION_TIER_COVERAGE_METADATA_
ONLY`) is a real, existing, applicable alternative that does not require
SourceVersion data — it was not run in this session because it requires
3 folds × 2 models of additional real NUTS refits (draws=500/tune=500/
chains=2 each), and this session's compute budget prioritised the
authorised target_accept=0.95 sensitivity fit (item 3) and the trace-
based analyses above it. **Recommended as the next actionable backtest
step if the analyst wants out-of-sample evidence** — feasible without any
new governance decision, just additional compute time.

## Item 7: does weak Hill/adstock identification affect business outputs?

Descriptive classification (median-split within each product's own
channel set, not a new pass/fail policy — every underlying number is
reported so the analyst can re-derive or override it):

**Family History** (19 channels, 0 well-identified): **10 class A**
(weakly identified transform, contribution relatively stable — `uk_avod`,
`uk_bvod`, `uk_drtv`, `uk_fh_affiliate`, `uk_fh_midfunnel_social`,
`uk_fh_non_brand_search`, `uk_fh_performance_display`, `uk_midfunnel_olv`,
`uk_podcast_audio`, `uk_radio`); **5 class B** (both uncertain —
`uk_brand_tv`, `uk_email`, `uk_fh_performance_social`, `uk_midfunnel_
display`, `uk_tv_sponsorship_linear`); **4 class C** (sparse, insufficient
support for a reliable curve — `circulation`, `uk_fh_content_marketing`,
`uk_influencer`, `uk_tv_sponsorship_vod`).

**DNA Kit** (18 channels, 0 well-identified): **9 class A** (`uk_avod`,
`uk_brand_tv`, `uk_dna_midfunnel_social`, `uk_dna_performance_display`,
`uk_drtv`, `uk_influencer`, `uk_midfunnel_olv`, `uk_podcast_audio`,
`uk_radio`); **6 class B** (`uk_bvod`, `uk_dna_affiliate`, `uk_dna_non_
brand_search`, `uk_email`, `uk_midfunnel_display`, `uk_tv_sponsorship_
linear`); **3 class C** (`circulation`, `uk_dna_content_marketing`,
`uk_tv_sponsorship_vod`).

**Notable internal-consistency check**: `uk_dna_performance_display` is
the one channel WP2.8 flagged as an identification *exception*
(`decay_rate` posterior/prior ratio 0.30, i.e. strongly data-driven, not
prior-driven). It is also the channel with the **lowest** contribution
relative interval width (0.80, vs. 1.7–3.6 for every other DNA channel)
and the **largest** median volume share (25.6%) — identification strength
and contribution stability agree exactly where WP2.8 already found a
strong identification signal, which is reassuring evidence that the
classification method is measuring something real rather than noise.

**CPA/ROI — not reported as reliable evidence.** `core.attribution.
outcome_channel_summary`'s existing convention treats `frame["X_media"]`
directly as spend for ROAS/CPA. Checking this candidate's `media_input_
specs` shows **no channel carries governed unit metadata**
(`_governed_units` returns `None` for all 19/18 channels), and the
computed per-draw ROI medians span roughly **six orders of magnitude**
across channels (e.g. FH: `uk_tv_sponsorship_linear` ROI≈64 vs.
`uk_fh_performance_social` ROI≈5.6e-5) — strong circumstantial evidence
that `X_media` mixes heterogeneous physical units (spend, impressions,
GRPs, clicks) across channels rather than uniform currency spend. Per the
explicit instruction not to fabricate CPA/ROI the governed contract does
not support, **these numbers are recorded in the raw evidence JSON for
audit but are not presented here as usable ROI/CPA evidence** — they
should not be shown to a marketer as comparable across channels until
governed per-channel spend units exist.

Volume contribution and share-of-contribution (unit-consistent within the
model's own outcome-count scale) remain valid and are reported in full in
`wp2_9_product_level_totals_{model}.json` and the item 7A section below.

## Item 7A: FH Overall and DNA Overall product-level totals

Computed within each posterior draw (summed outcome columns first, then
summarised) using the existing joint posterior's own `mu`/`alpha`
deterministics — no new model, no new likelihood.

| Metric | FH Overall | DNA Overall |
|---|---|---|
| R² | **0.383** | **0.600** |
| RMSE | 1,213.0 | 2,429.5 |
| MAE | 903.9 | 1,483.7 |
| MAPE | 14.4% | 38.5% |
| Bias | 34.5 | 28.3 |
| PPC 90% coverage | 84.0% | 83.2% |
| Residual lag-1 autocorr | 0.27 | 0.19 |
| Durbin-Watson | 1.47 | 1.60 |
| Baseline outcome (median) | 431,062 | 229,874 |
| Incremental outcome (median) | 299,983 | 273,161 |
| Reconciliation max abs diff | **4.7e-10** | **2.3e-10** |

**Product-level R² is dramatically higher than any individual constituent
segment** — FH Overall's 0.383 vs. FH New's 0.068 alone; DNA Overall's
0.600 vs. either DNA segment individually (WP2.8: DNA New 0.639, DNA
Existing 0.501 — DNA Overall sits between them, consistent with summing
two correlated-residual series). Reconciliation is exact to floating-
point tolerance for every draw, confirming the product-level series is
genuinely the posterior-draw sum of its constituents, not a re-derived
approximation.

**Stability comparison**: product-level channel-volume relative 90%
interval width (`(q95−q05)/q50`) is reported per channel alongside each
constituent segment's own relative width in the evidence JSON. Spot
check: for both products, several channels' product-level relative width
sits *between* (not uniformly below) the individual segments' widths —
aggregation reduces the noisiest segment's contribution to the total
signal-to-noise ratio proportionally, but with only 2–3 constituent
outcomes summed (not dozens), the reduction is real but modest rather
than dramatic. Full per-channel numbers are in
`wp2_9_product_level_totals_{model}.json`'s `stability_comparison` block
for analyst review — this is reported as descriptive evidence, not
reduced to a single pass/fail statement.

PPC coverage sits a few points below the 90% nominal target for both
products (84.0%/83.2%) — narrower than nominal, consistent with the
positive residual autocorrelation already reported (autocorrelated
residuals make a handful of consecutive weeks miss together rather than
independently), not evidence of a new problem beyond what item 5 already
surfaces.

## Item 8: seasonality (unchanged from WP2.7/WP2.8, retained as-is)

No seasonality specification change made in WP2.9. WP2.8's finding
stands: posterior seasonality amplitude is materially narrower than prior
for every outcome (the data is learning seasonality, not merely retaining
prior width). The DNA media/seasonality correlation (~0.35–0.45,
`eta_season` vs. `eta_channels`) from WP2.8 is retained as an open
identification caveat; item 5's cross-outcome residual-correlation
finding (DNA New/Existing r=0.96) is a *separate*, and stronger, signal
about DNA's temporal structure than the trend/season/media correlations
checked directly against residuals (all small, |r|<0.06) — the moderate
eta_season/eta_channels correlation does not appear to be the primary
driver of DNA's unexplained residual co-movement.

## Item 9: Circulation caveat — preserved

Circulation's approximately 106x positive max/median observation from
earlier work packages is **unchanged**: not winsorised, deleted, capped,
or replaced. It remains an explicit, open data-owner caveat. Circulation
is independently classified **class C** (insufficient empirical support
for a useful response curve) for both products in item 7's evidence,
consistent with — not contradicted by — this unresolved data caveat: a
channel with an unexplained extreme historical outlier is exactly the
kind of channel that should not be presented as having a well-estimated
response curve.

## Outstanding before certification (see the companion decision package)

1. Item 3's target_accept=0.95 comparison must complete before a
   certification recommendation can be made — divergences are real and
   material to reported contributions (item 2), so whether 0.95 resolves
   them without changing the substantive posterior is a live input to
   certification, not a formality.
2. The WP2.7/WP2.8 analyst rationale needs to be re-retained against the
   now-corrected `candidate_spec_fingerprint`/`prepared_frame_fingerprint`
   (item 1) — this is a short, mechanical re-run of the existing
   `record_prefit_analyst_review` mechanism, not a new decision, but it
   has not been done yet in this session.

See `docs/wp2_9_sampler_sensitivity_decision_package_20260825.md` (added
once item 3 completes) for the final certification recommendation
covering all ten items together.
