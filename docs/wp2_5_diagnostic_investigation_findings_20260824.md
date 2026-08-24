# UK Model A WP2.5 diagnostic investigation findings (2026-08-24)

Status: findings and recommendations only. No channel was removed,
aggregated, pooled, or given a different transform/prior. No production
adstock, pooling, or fold-policy default was changed. No candidate
remedy below is selected or implemented.

This document covers four of the five items in the analyst-directed
WP2.5 bounded diagnostic investigation; the prior-predictive finding has
its own dedicated `docs/wp2_5_prior_predictive_decision_package.md`.
Evidence source: `scripts/run_uk_wp2_5_diagnostics.py`, run against the
real approved UK source pack (2026-08-24); raw output (aggregate
statistics only, no source rows) is at `D:\Ancestry-MMM\test-artifacts\
historical-model-a-wp2-5-diagnostics-20260824\`.

## 1. DNA future-to-past investigation

`core.prefit_screening.build_prefit_screening_report`'s timing-refutation
now reports `incremental_future_media_r2` per fold/outcome/transform
variant (WP2.5): `future_media_r2` (a surrogate fit on baseline features
plus *future*-shifted media) minus that identical fold's own
`baseline_context_only_r2` (baseline features alone, same train/test
split) - isolating whether the raw future-media R2 reflects genuine
incremental signal or is already explained by shared baseline/
seasonality.

**Fold 3 (the mature fold, 82 training weeks) - the most trustworthy
evidence - shows the concern is largely explained by shared baseline,
not by future media itself:**

| Outcome | Transform | future_media_r2 | baseline_context_only_r2 | incremental |
|---|---|---|---|---|
| DNA New Customer | T1 | 0.687 | 0.616 | **0.071** |
| DNA New Customer | T2 | 0.599 | 0.616 | -0.017 |
| DNA Existing FH Customer | T1 | 0.456 | 0.583 | -0.127 |
| DNA Existing FH Customer | T2 | 0.363 | 0.583 | -0.219 |

The raw `future_media_r2` values (0.687, 0.456) are the ones the analyst
cited as concerning; once compared against this identical fold's own
baseline-only performance (already 0.616 / 0.583 - the baseline model
alone explains most of the variance), the *incremental* contribution
attributable specifically to future media is small (T1) or negative
(every other transform variant, T2-T6, for both outcomes). This is
consistent with shared trend/seasonality/category-demand context
explaining the apparent "future predicts past" pattern, not a genuine
future-media leakage or timing defect, on the fold with the most
training history.

**Folds 1 and 2 show larger incremental values, but are lower-confidence
evidence** - see the fold-policy finding (§4) for why: fold 1 is an
explicit stress test (8 training weeks; baseline itself is deeply
negative-R2, so a large "incremental" delta there compares two badly-
fitting models rather than demonstrating real signal) and fold 2 (45
weeks) has a near-zero baseline R2 (0.006-0.02), meaning there is very
little baseline signal for future media to be incremental *over* - a
different, weaker kind of evidence than fold 3's case where the
baseline is already a reasonably good fit.

**Recommendation:** treat the mature-fold result as reassuring but not
dispositive. Before any further step that would depend on DNA media
timing, still verify: date alignment between DNA media activity and DNA
outcome observations (an off-by-one-week or campaign-end-vs-payment-date
mismatch would show exactly this fold-3 pattern - explained by shared
seasonality because the "future" shift accidentally re-aligns two
already-correlated series); whether category-demand context and DNA
promotions/events share the same seasonal calendar as DNA media
(plausible, and would also produce this pattern); and whether campaign/
source timing metadata (already-adopted `SourceVersion` records) shows
any known lag convention. None of this was found to be a defect by this
pass - it is recorded as the residual open question, not resolved.

## 2. Transformation sensitivity

Isolating the mature fold's (fold 3) own per-transform-variant surrogate
performance (mean test RMSE across outcomes, lower is better):

| Transform | Family History RMSE | DNA RMSE |
|---|---|---|
| T1 | 0.323 | 0.532 |
| T2 | 0.322 | 0.607 |
| T3 | 0.359 | 0.695 |
| T4 | 0.360 | 0.726 |
| T5 | 0.380 | 0.774 |
| T6 | 0.418 | 0.842 |

Confirmed: T1/T2 (the lightest-adstock transform variants in the bounded
screening grid) materially outperform heavier-adstock variants on the
mature fold for both products, monotonically for DNA. Candidate
explanations, none of which this pass distinguishes conclusively:

- **Weak empirical support for flexible/extended carryover** - consistent
  with §3's sparse-channel evidence: several channels have few active
  weeks, which mechanically limits how much a longer adstock decay can
  be identified from this window regardless of the true underlying
  process.
- **Collinearity between adstock variants** - a heavier-decay transform
  of the same raw channel is, by construction, smoother/more
  autocorrelated than a lighter one; on a short window this can make the
  heavier variant harder for a regularised surrogate to distinguish from
  the trend/seasonality terms it competes with, inflating its test RMSE
  independent of the true carryover length. This screen does not
  separately test this hypothesis (would require an explicit
  variance-inflation or nested-model comparison, not currently
  instrumented).
- **Model/feature scaling** - `core.prefit_screening.build_prefit_
  screening_report` already standardises every feature (`StandardScaler`
  inside the ridge/elastic-net pipeline) before fitting, so raw-scale
  differences between transform variants are not the direct explanation,
  though scaling interacts with regularisation strength in ways this
  screen does not isolate.
- **Genuine short-lived response** - plausible on its own merits for a
  performance-marketing UK media mix with a large non-brand/lower-funnel
  share, and would be a legitimate finding rather than an artefact.

**Recommendation:** if a production transformation change (e.g.
constraining the default adstock decay prior, or preferring T1/T2-like
transform families for specific channels) is to be proposed, it should
go through a dedicated decision package once the collinearity hypothesis
specifically has been tested (not attempted in this pass) - this finding
alone does not yet distinguish "the data says carryover is short" from
"the data cannot see carryover past ~1-2 weeks regardless of the truth."
No adstock prior is changed by this document.

## 3. Sparse-channel review

Every channel the analyst named as identification-sensitive is confirmed
present with the exact cited active-week count:

| Channel | Active weeks (cited, confirmed) | Distinct positive values | Positive max/median ratio | Support status |
|---|---|---|---|---|
| DNA Content Marketing | 2 | 2 | 1.36 | very_weak |
| FH Content Marketing | 6 | 6 | 6.05 | very_weak |
| Influencer | 12 | 12 | 7.10 | weak |
| Radio | 13 | 13 | 8.19 | weak |
| TV Sponsorship VOD | 16 | 13 | 6.51 | weak |
| Circulation | 25 | 15 | **105.97** | weak |
| FH Midfunnel Social | 20 | 20 | 5.58 | weak |

All seven channels are retained; none is removed, aggregated, pooled, or
given a simplified transform or tightened prior by this document -
consistent with the review's instruction and with `core.
prefit_identifiability`'s own contract (support classification is
diagnostic-only, never a channel-selection gate).

**Circulation's positive max-to-median ratio (105.97) is a genuine
outlier** - every other flagged channel's ratio is in the 1.4-8.2 range.
A single week's positive circulation value being roughly 106x the median
of its own positive weeks is consistent with several distinct
possibilities this pass does not distinguish: a genuine one-off
circulation spike (e.g. a large print/distribution event), a unit or
aggregation inconsistency for one source row, or a data-entry/mapping
defect. **Recommendation:** the analyst or a data owner should inspect
the raw circulation source values directly (this diagnostic pass
deliberately never surfaces raw source rows) to determine which case
applies before circulation's evidence is relied upon for any purpose
beyond this diagnostic review.

**Recommended candidate treatment (not applied):** for the very_weak
channels (DNA Content Marketing, FH Content Marketing) specifically,
governed partial pooling of the response/transform parameters toward a
same-product parent or comparable-channel group (rather than a fully
independent channel-specific parameter) is the most likely eventual
direction if a production change is warranted - consistent with `core.
hierarchical_model`'s existing partial-pooling machinery for other
dimensions - but this is not decided, proposed as an approved change, or
implemented here.

## 4. Fold-policy review

The governed expanding-window fold manifest for this evidence run
(`core.prefit_screening.build_leakage_safe_folds`, `min_train_periods=8`
default):

| Fold | Train weeks | Test weeks |
|---|---|---|
| prefit-fold-1 | **8** | 37 |
| prefit-fold-2 | 45 | 37 |
| prefit-fold-3 | 82 | 37 |

Fold 1's 8-week training window is barely more than the `min_train_periods`
default floor itself, for an 18-channel (Family History) / 19-channel
(DNA, including the DNA-specific channel) weekly model. With that few
training weeks and that many channels, most channels necessarily have
zero or near-zero variation within the training window alone - this
fold cannot meaningfully separate 18-19 channels' worth of signal
regardless of the true underlying process, and its own evidence (§1)
shows a deeply negative baseline R2, consistent with this being an
inherent property of the fold, not a candidate-specific finding.

**Recommendation: treat fold 1 as a stress test (does the screen fail
gracefully / report evidence honestly under adversarial conditions),
never as production-representative evidence, for any model of this
channel count.** Whether the governed fold policy's `min_train_periods`
default should be raised for production pre-fit assessment (as opposed
to this diagnostic screen, which intentionally exercises the existing
default) is itself a governance question - a defensible minimum should
probably scale with channel/parameter count rather than being one fixed
constant, but that is a judgement call requiring its own approved
record. **This document does not change `min_train_periods` or
`core.prefit_screening.PREFIT_FOLD_POLICY_VERSION`.** Any change to the
formal fold policy belongs in a `docs/approved_requirements/REQ-*`
record or decision package of its own, not a silent default change.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.5 investigation. Status: findings supplied for
review. No WP3 full-fit sampling is authorised by this document.
