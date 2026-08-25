# WP2.8 items 4-10: governed full UK Model A posterior findings (2026-08-25)

Status: evidence for analyst review. **This document does not authorise
Model B, Search mediation, optimisation, or any overall-product
challenger model.** No statistical specification was changed to produce
this evidence - control scaling/`control_sigma`, media channel set,
adstock priors, Hill K/S priors, seasonality/Fourier priors, trend,
pooling, causal graph, sparse-channel treatment, and fold policy all
remain exactly as frozen at the WP2.7 state.

Evidence source: `scripts/run_uk_production_fit.py` (the real, unmodified
governed production entrypoint - 4 chains x 2000 draws x 1000 tune x
target_accept=0.9, REQ-CONTROL-001's approved control-prior already the
production default) run against the real approved UK source pack for
both Family History and DNA Kit, followed by `scripts/run_uk_wp2_8_full_
posterior_evaluation.py` (new diagnostic script) against the saved
traces. Raw output (posterior traces + full evidence JSON, no source
rows) is at `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-
full-posterior-20260825\` (traces) and `D:\Ancestry-MMM\test-artifacts\
historical-model-a-wp2-8-full-posterior-evaluation-20260825\` (evidence).

## 1. Full convergence assessment (item 5)

| Metric | Family History | DNA Kit | WP2.7 short screen (FH / DNA) |
|---|---|---|---|
| R-hat max | **1.0031** | **1.0027** | 1.191 / 1.089 |
| ESS bulk min | **1,821.5** | **3,297.8** | 9.0 / 54.7 |
| ESS tail min | **1,555.0** | **2,750.2** | 13.7 / 30.6 |
| Divergences (of 8,000 post-tuning draws) | 70 (0.88%) | 53 (0.66%) | 0 / 0 |
| Divergences by chain | 17, 14, 16, 23 | 24, 13, 1, 15 | n/a (2 chains, 0 each) |
| BFMI by chain | 0.96, 0.99, 0.98, 0.95 | 0.97, 1.00, 0.94, 0.90 | 1.07/1.25 (FH), 0.97/0.94 (DNA) |
| Max tree depth observed (of 10 configured) | 6 | 6 | 8 (FH) / 7 (DNA) |
| Draws at max tree depth | 0 (all chains) | 0 (all chains) | 0 |
| Mean acceptance rate by chain | 0.89, 0.87, 0.90, 0.89 | 0.89, 0.90, 0.93, 0.87 | n/a |

**This is materially better geometry than the short screen, and clearly
does not meet item 9's stop criteria.** No widespread divergences (both
well under 1% of draws, spread across all four chains rather than
concentrated in one), no repeated maximum-tree-depth saturation (zero
draws hit the cap in every chain), no pathological BFMI (all values
0.90-1.00, far above the ~0.3 concern threshold), and no severe chain
separation - chain-wise posterior means for `alpha` and `intercept` are
essentially identical across all four chains for both models (e.g. FH
`alpha`: 20.43/20.54/20.54/20.48; DNA `intercept`: 6.867/6.874/6.869/
6.875). **Per item 10, this evidence proceeds directly to the complete
post-fit validation package below - it does not trigger item 9's
bounded remediation decision package.**

R-hat distribution (all parameters, both models) sits in a tight band
around 1.000-1.002 at every percentile up to q99 (FH q99=1.0021, DNA
q99=1.0017) - the max values above are not driven by a broad tail of
poorly-converged parameters, but by a small number of individual
parameters (see below).

### Parameter-family summary

| Family | FH R-hat max / mean | FH ESS bulk min | DNA R-hat max / mean | DNA ESS bulk min |
|---|---|---|---|---|
| Controls (`control_coef`) | 1.0002 / 1.0002 | 9,457 | 1.0000 / 1.0000 | 8,462 |
| Media coefficients (`beta`) | 1.0018 / 1.0005 | 3,344 | 1.0013 / 1.0004 | 4,179 |
| Decay/adstock (`decay_rate`) | 1.0016 / 1.0006 | 2,243 | 1.0027 / 1.0007 | 5,409 |
| Hill K | 1.0017 / 1.0005 | 4,795 | 1.0016 / 1.0006 | 4,945 |
| Hill S | 1.0031 / 1.0005 | 7,135 | 1.0011 / 1.0002 | 6,321 |
| Trend | 1.0006 / 1.0002 | 3,537 | 1.0005 / 1.0005 | 5,434 |
| Seasonality (`gamma_fourier`) | 1.0021 / 1.0006 | 8,092 | 1.0012 / 1.0005 | 6,432 |
| Hierarchy/pooling | 1.0025 / 1.0006 | 4,459 | 1.0020 / 1.0005 | 3,298 |
| Sparse-channel Hill/adstock | 1.0017 / 1.0005 | 2,243 | 1.0027 / 1.0007 | 5,409 |
| Non-sparse-channel Hill/adstock | 1.0031 / 1.0005 | 4,382 | 1.0014 / 1.0004 | 4,945 |

Every family converges comfortably by standard thresholds (R-hat <1.01,
ESS in the thousands) for both models. Controls converge the best of
any family (consistent with REQ-CONTROL-001's fix); no family stands
out as materially worse than the others on convergence grounds alone -
the worst individual R-hat values (FH `hill_S[uk_fh_performance_
social]`=1.0031; DNA `decay_rate[circulation]`=1.0027) are isolated
single parameters, not family-wide problems. The lowest-ESS individual
parameters in both models are `sat_media`/`eta_channels`/`eta_primary`
entries at specific (observation, channel) pairs - expected for
downstream deterministic transforms tied to particular data points, and
still comfortably above 1,800 effective draws even at the worst point.

## 2. Identification as well as convergence (item 6)

**Good R-hat/ESS here does not mean every parameter is identified.**
Comparing each parameter's posterior standard deviation to its own
prior standard deviation (a ratio near 1.0 means the data barely moved
the parameter from its prior; a ratio well below 1.0 means the data
substantially narrowed it):

| Parameter family | Posterior/prior std ratio - typical range | Interpretation |
|---|---|---|
| `decay_rate` (adstock), both models, nearly every channel | **0.75-1.5** (median close to 1.0) | **Essentially prior-driven for almost every channel** - the data is not meaningfully updating carryover length for the great majority of channels |
| `hill_K`, both models, nearly every channel | **0.75-1.2** | Same pattern - weakly identified saturation half-point for almost every channel |
| `hill_S`, both models, nearly every channel | **0.83-1.17** | Same pattern - weakly identified saturation slope for almost every channel |
| `control_coef` (category demand), Family History | **0.069** | **Strongly identified** - posterior is ~7% as wide as the prior |
| `control_coef` (category demand), DNA | **0.188** | **Strongly identified** - posterior is ~19% as wide as the prior |

**One partial exception**: DNA's `decay_rate[uk_dna_performance_
display]` narrows to ratio 0.300 - genuinely identified, unlike every
other Hill/adstock parameter in either model.

**This is the central identification finding of WP2.8**: the category-
demand control - the parameter REQ-CONTROL-001 specifically
recalibrated - is now sharply learned from the data, exactly as
intended. **Hill/adstock (carryover length and saturation shape)
remains weakly identified across almost the entire channel set for
both products, despite excellent R-hat/ESS.** This distinguishes the
two possible explanations for WP2.7's Hill/adstock sampler difficulty:
it is not (or not only) a sampling-difficulty problem that a properly
sized run resolves - with 4x the chains and 20x the post-tuning draws
of the short screen, the geometry converges cleanly, but the *posterior
content* for these parameters remains close to the prior for nearly
every channel. This is a **weak-identification finding, not a sampler
pathology finding** - no divergence or tree-depth signature is attached
to specific Hill/adstock channels distinctly from the rest of the
model (see section 1's family table - Hill/adstock families' R-hat/ESS
are unremarkable relative to every other family). Per the analyst's
explicit instruction, **wide-but-valid uncertainty is reported here as
uncertainty, not treated as a defect to fix** - no transformation is
simplified and no prior is tightened in response to this finding.

## 3. Full posterior predictive and fit validation (item 7)

| Outcome | R² | MAPE % | MAE | RMSE | Bias | PPC 90% coverage |
|---|---|---|---|---|---|---|
| FH New | **0.068** | 12.8% | 344.5 | 455.6 | -167.3 | 95.0% |
| FH DNA cross-sell | 0.461 | 20.9% | 472.8 | 662.2 | -138.7 | 90.8% |
| FH Winback | 0.303 | 26.5% | 441.3 | 684.2 | -104.2 | 94.1% |
| DNA New customer | 0.639 | 32.3% | 924.3 | 1,553.0 | -190.5 | 93.3% |
| DNA Existing FH customer | 0.501 | 39.9% | 525.7 | 911.3 | -79.8 | 90.8% |

**FH New's R² is 0.068 - materially unchanged from the short screen's
0.019, now with a fully converged posterior (R-hat 1.0031, ESS 1,821+
for every parameter).** Per the analyst's explicit instruction, this is
reported as a genuine model-fit/specification issue, not adjusted by
changing media coefficients. All five outcomes show a small negative
bias (model under-predicts on average, -80 to -191 units against means
of 1,374-2,866), consistent in direction across every outcome for both
products. Posterior-predictive 90% interval coverage is close to
nominal everywhere (90.8%-95.0%) - the *interval* calibration is
reasonable even where the *point* fit (R²) is poor, which is possible
when uncertainty is wide enough to still bracket the truth.

**Residual lag-1 autocorrelation remains positive for every outcome**,
essentially unchanged from the short screen: FH 0.29-0.42 (Durbin-
Watson 1.00-1.38), DNA 0.15-0.22 (Durbin-Watson 1.52-1.68). This
persists after full convergence, confirming it is temporal structure
the model is not capturing (omitted baseline/trend/seasonality
interaction, or media-timing structure) rather than a short-screen
sampling artefact. **This is flagged as a model-specification question
for analyst review, not remediated here** - per the explicit
instruction not to adjust media effects to improve fit.

One plausibility flag per model (unchanged from WP2.7): `uk_fh_content_
marketing` and `uk_dna_content_marketing`'s fitted half-saturation
points sit far below their lowest observed non-zero spend - both are
already-known very-weak-support channels (WP2.5), not a new finding.

## 4. Seasonality (item 8)

WP2.7 found `eta_season` was the widest individual additive
prior-predictive component. The seasonality specification was not
changed for this run, per instruction.

| Outcome | Prior amplitude (median) | Posterior amplitude (median) | Narrowing |
|---|---|---|---|
| FH New | 2.299 | **0.336** | ~6.8x narrower |
| FH DNA cross-sell | 2.297 | **0.807** | ~2.8x narrower |
| FH Winback | 2.292 | **0.895** | ~2.6x narrower |
| DNA New customer | 2.301 | **1.469** | ~1.6x narrower |
| DNA Existing FH customer | 2.288 | **1.694** | ~1.4x narrower |

**Posterior seasonality is materially narrower than its prior for every
outcome in both models** - most dramatically for FH New (~6.8x), least
for DNA (~1.4-1.6x). Amplitude here is the implied seasonal
log-multiplier's peak-to-trough range over the observed window
(`fourier @ gamma_fourier`), at the posterior/prior mean level.

Correlation between each outcome's mean `eta_season` time series and
`eta_trend`/`eta_controls`/`eta_channels`:

| Comparison | Family History (range across 3 outcomes) | DNA (range across 2 outcomes) |
|---|---|---|
| vs. `eta_trend` | -0.038 to 0.175 | -0.162 to -0.140 |
| vs. `eta_controls` | -0.136 to 0.019 | 0.124 to 0.134 |
| vs. `eta_channels` | -0.132 to 0.123 | **0.354 to 0.449** |

Family History shows only weak correlation between seasonality and any
other component (all \|r\| < 0.18). **DNA shows a moderate positive
correlation between seasonality and media effects specifically (0.35-
0.45)** - worth the analyst's attention as a candidate explanation for
part of DNA's own residual structure, but not strong enough on its own
to indicate the seasonality specification is broken, and not acted on
here. Per the explicit instruction, no seasonality change is made and
no statistical decision package is produced - this finding does not
meet the bar of "medium-run evidence indicates the seasonality
specification itself is problematic."

## 5. Failure-behaviour decision (item 9) and next step (item 10)

Section 1 above establishes the full run's geometry as healthy by
every stated criterion. **Item 9's stop condition is not triggered.**
Per item 10, this document is the complete post-fit validation evidence
package for both Family History and DNA Kit Model A. **Model B, Search
mediation, optimisation, and any overall-product challenger model are
explicitly not started.** This document stops here for analyst review.

The open, reported-not-fixed findings for the analyst's attention are:

1. Hill/adstock (decay, Hill K, Hill S) remain weakly identified across
   almost every channel in both products - technically converged, not
   meaningfully learned from the data.
2. FH New's fit remains very poor (R²=0.068) after full convergence -
   a specification question, not a convergence question.
3. Positive residual autocorrelation persists across every outcome in
   both products after full convergence.
4. DNA's seasonality shows a moderate positive correlation with media
   effects (0.35-0.45) not seen in Family History.

None of these were acted on in this pass, per the analyst's explicit
instructions to report rather than remediate from this evidence alone.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.8 investigation. Status: full-posterior evidence
supplied for review for both models. No WP3-scale decision (Model B,
Search mediation, optimisation, or challenger models) is authorised by
this document.
