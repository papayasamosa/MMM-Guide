# WP2.10 items 4, 5, 8, 9: overall challenger models, four-view
# comparison, and final decision package (2026-08-25)

Companion to `docs/wp2_10_remediation_evidence_20260825.md` (items 1, 2,
3, 6, 7). This document covers the independently fitted FH Overall / DNA
Overall challenger models and the final WP2.10 decision package. **This
is a decision package, not a certification decision** - it answers what
the evidence shows and identifies what remains for the analyst; it does
not certify Model A, and does not authorise Model B, Search mediation,
optimisation, or replacing the segment-level Model A candidates.

## Items 4/5: FH Overall and DNA Overall challenger models

Constructed by summing the constituent raw segment outcome columns at
each week, before modelling (`scripts/run_uk_wp2_10_overall_challenger.py`
- see that script's own docstring for the full construction, DNA-halo-
pathway-routing, and outcome-hierarchy-removal rationale). Real, full
governed posteriors: `chains=4, draws=2000, tune=1000, target_accept=
0.90` (the currently approved default, not 0.95), `prior_config["pooled_
beta_reference"]=True` (an existing, pre-dating-this-work-package gate -
with only one outcome there is nothing to hierarchically pool across, so
`sigma_pool`/`z_offset` are correctly absent rather than left as
unidentifiable free parameters).

### Convergence - clean, in both products

| | FH Overall challenger | DNA Overall challenger |
|---|---|---|
| R-hat max | 1.0024 | 1.0028 |
| ESS min | 3,519.8 | 3,789.5 |
| **Divergences** | **0** | **0** |

**This is the central finding of items 4/5.** Both challengers - built
from the exact same channels, media transforms, controls, trend,
seasonality, and causal DNA-halo routing as their segment counterparts,
differing only in having one outcome instead of three (FH) or two (DNA)
and therefore no outcome-level pooling layer - sample with **zero
divergences** at the full governed configuration. The segment models show
70 (FH, 0.90) / 13 (FH, 0.95) and 53 (DNA, 0.90) / 46 (DNA, 0.95)
divergences under otherwise identical conditions. This is strong,
direct evidence (not merely consistent with item 2's inference from
`sigma_pool` sitting at its prior) that **the outcome-level hierarchy
itself is the source of the remaining sampler geometry problem** in both
products - not the media transforms, not the controls, not the causal
routing, all of which are unchanged between the segment and challenger
models.

### Fit - the challengers fit somewhat worse than the posterior-derived aggregate

| | FH Overall challenger | DNA Overall challenger |
|---|---|---|
| R² | **0.249** | **0.546** |
| MAPE | 15.4% | 38.9% |
| (for comparison) posterior-derived Overall R² (WP2.9) | 0.383 | 0.600 |

Both challengers fit **worse** than their posterior-derived counterparts,
despite (or perhaps because of) having no outcome hierarchy to borrow
strength from. This is mechanistically sensible: the segment model fits
each outcome's own baseline/trend/season/control terms separately, and
those per-outcome terms - even though the channel-level pooling layer
they sit alongside is weakly identified - still let each segment's
idiosyncratic level and shape contribute to a better joint fit before
being summed; the single-outcome challenger has exactly one set of
baseline/trend/season/control terms for the whole merged series and
cannot use that extra flexibility. Clean geometry and better fit are not
the same thing, and this work package does not treat them as such.

### Channel attribution - broadly similar for most channels, materially different for the one channel WP2.8/WP2.9/item 2 already flagged as differently-identified

Largest disagreements (challenger vs. WP2.9's posterior-derived Overall,
median channel volume contribution):

**FH Overall**: `uk_fh_midfunnel_social` +28.8%, `uk_fh_content_marketing`
+27.4%, `uk_midfunnel_display` +22.2%, `uk_radio` +17.6%,
`uk_tv_sponsorship_linear` -15.5%. Every other channel differs by less.

**DNA Overall**: `uk_dna_performance_display` **-69.7%** (challenger
20,973 vs. posterior-derived 69,238 - by far the largest disagreement of
either product), `uk_tv_sponsorship_linear` -37.2%, `uk_tv_sponsorship_
vod` +35.4%, `uk_radio` +34.2%, `uk_midfunnel_olv` +27.9%.

**`uk_dna_performance_display` is the single most informative
disagreement in this entire work package.** It is independently: (a) the
one channel WP2.8 found genuinely data-identified (`decay_rate`
posterior/prior std ratio 0.30, far below every other channel's ~1.0);
(b) the one channel item 2 found with a `sigma_pool` genuinely above the
prior-dominated cluster (0.445 vs. ~0.24-0.26 everywhere else); (c) the
channel with by far the largest and most stable volume share in the
posterior-derived DNA Overall total (25.6% share, lowest relative
interval width of any DNA channel). All three pieces of independent
evidence say this channel's two DNA outcomes (New, Existing) genuinely
have different effects - which is exactly what collapsing them into one
challenger outcome discards, and exactly why the challenger's estimate
for this one channel moves the most. This is not noise; it is the
challenger model doing precisely what removing a genuinely-informative
hierarchy layer would be expected to do.

## Item 8: comparing the four product-level views

**Family History**: three segment outcomes (WP2.7/WP2.8/WP2.9) - FH New
R²=0.068 alone, but strong shared residual correlation with Winback
(r=0.77, item 3); posterior-derived FH Overall (WP2.9, item 7A) - R²=
0.383, exact per-draw reconciliation to the segments; independently
fitted FH Overall challenger (this document) - R²=0.249, clean geometry
(0 divergences), channel attribution broadly similar (within ~15-29%) to
the posterior-derived total for every channel.

**DNA**: two segment outcomes (WP2.8/WP2.9) - both fit reasonably (R²
0.50-0.64) but share a near-single residual factor (r=0.96, item 3) and
53/46 divergences (0.90/0.95); posterior-derived DNA Overall (WP2.9) -
R²=0.600, exact reconciliation; independently fitted DNA Overall
challenger (this document) - R²=0.546, clean geometry (0 divergences),
channel attribution broadly similar for most channels but **materially
different (-69.7%) for `uk_dna_performance_display`**.

**Do not average the two methods** (per the brief) - they answer
different questions. The posterior-derived Overall totals are the
segment model's own internally consistent aggregate (exact reconciliation,
inherits the segment model's per-outcome flexibility, inherits its
divergence-associated geometry). The independently fitted challengers are
a genuinely different model (no outcome hierarchy, single baseline/
trend/season) that trades that per-outcome flexibility for clean sampler
geometry, at the cost of somewhat worse fit and one materially different
channel estimate in DNA specifically. Where they agree (most channels,
both products, within ~15-30%), that agreement is itself evidence the
segment-level hierarchy's channel-level attribution is not solely an
artefact of its own divergent geometry. Where they disagree sharply
(`uk_dna_performance_display`), the disagreement is well-explained by a
real, independently-corroborated identification difference, not treated
as an unexplained anomaly.

**Class A/B/C channels** (WP2.9's identification-vs-contribution-
stability classification): the challenger comparison does not show a
clean pattern of "class A channels agree, class C channels disagree" -
e.g. FH's largest disagreements (`uk_fh_midfunnel_social`, `uk_fh_
content_marketing`) are WP2.9 class A/C channels respectively, while
several class B channels (`uk_brand_tv`, `uk_email`) show smaller
challenger-vs-posterior-derived disagreement than that. The one clean,
mechanistically-explained pattern is `uk_dna_performance_display`
specifically (the sole channel WP2.9 flagged as genuinely well-
identified), not a broader class-based rule - reported as such rather
than forcing a pattern the evidence does not support.

## Item 9: final WP2.10 decision package

1. **Are FH's remaining 13 divergences at 0.95 materially relevant to
   attribution?** Yes. Median channel-contribution differences between
   the remaining divergent and non-divergent draws are as large as
   +85.9% (`uk_fh_non_brand_search`), proportionally similar to or larger
   than at 0.90, despite the much smaller divergent-draw count (a
   genuine small-sample caveat on the exact percentages, not on the
   qualitative conclusion).
2. **Should FH formally adopt `target_accept=0.95`?** Not yet, on this
   evidence alone - item 1's own stated condition for recommending
   adoption ("no longer has meaningful contribution differences") is not
   met. However, items 4/5 add a materially different consideration: the
   FH Overall challenger shows the *outcome hierarchy*, not the sampler
   step size, is the dominant source of FH's divergence geometry. A
   0.90-vs-0.95 sampler change treats a symptom; it does not address
   what items 4/5 identify as the actual cause.
3. **What specifically causes the DNA pooling geometry?** Two
   convergent, independent pieces of evidence: (a) item 2's fitted
   `sigma_pool` sits at its `HalfNormal(0.3)` prior mean for nearly every
   channel, mechanically explained by DNA having only 2 outcome groups
   per channel for that variance parameter to be identified from; (b)
   item 5's DNA Overall challenger - identical in every respect except
   having no outcome hierarchy - converges with zero divergences. The
   outcome-level partial-pooling layer is the cause, not the media
   transforms, controls, or causal routing (all unchanged between the
   two models).
4. **Does the independently fitted DNA Overall model eliminate that
   geometry?** Yes, completely: 0 divergences, R-hat 1.0028, ESS 3,789.5,
   at the full `chains=4/draws=2000/tune=1000/target_accept=0.90`
   configuration that produces 53 divergences in the segment model.
5. **Does the independently fitted FH Overall model broadly corroborate
   posterior-derived FH Overall attribution?** Broadly, yes, for most
   channels (within ~15-29%), but its own fit is meaningfully worse
   (R²=0.249 vs. 0.383) - a partial corroboration, not a clean
   validation. Treat the posterior-derived total as the primary FH
   Overall view for now; the challenger corroborates its channel ranking
   and rough magnitudes without matching its fit quality.
6. **Does the independently fitted DNA Overall model broadly corroborate
   posterior-derived DNA Overall attribution?** For most channels, yes
   (within ~15-35%); for `uk_dna_performance_display` specifically, no
   (-69.7%) - and that specific disagreement is well-explained by three
   independent pieces of prior evidence (this is the one genuinely
   well-identified DNA channel), not an unexplained anomaly.
7. **What explains the common residual temporal component?** Not
   resolved - checked against every governed context variable already in
   the UK source pack (30 variables) and the 79-event UK calendar; no
   single already-available series explains the within-product shared
   residual factor (FH New/Winback r=0.77; DNA New/Existing r=0.96).
   This remains a genuine specification gap.
8. **Which dynamic-baseline remedy, if any, has the strongest evidence?**
   None was implemented or newly proposed - `docs/wp10_time_varying_
   baseline_decision_package.md`/`REQ-BASELINE-001` (2026-08-18) already
   cover this exact gap and explicitly require an analyst decision before
   any implementation, including as a diagnostic. This work package's new
   evidence (the specific correlation values, the negative context/event
   check) is added to that existing decision point; Candidate T2 (a
   random-walk-style process) remains the closest conceptual match to
   this work package's own suggested mechanism, but selecting it is
   exactly the decision REQ-BASELINE-001 reserves for the analyst.
9. **Does that remedy improve residual behaviour without merely
   absorbing media signal?** Not evaluated - no remedy was implemented,
   per item 8's answer.
10. **What does the prepared-frame backtest say about out-of-sample
    performance?** Nothing yet - genuinely blocked, not forced. The
    existing `run_leakage_safe_fold_refit` mechanism's internal frame
    construction is incompatible with the current `OutcomeDefinition`-
    catalogue-based Model A candidates (a pre-existing, structural
    incompatibility, not a WP2.10 regression - see `docs/wp2_10_
    remediation_evidence_20260825.md` item 6 for the exact error and the
    smallest fix, not implemented here).
11. **Which channels can support attribution but not reliable response
    curves?** Unchanged from WP2.9's item 7 classification: FH's
    `circulation`, `uk_fh_content_marketing`, `uk_influencer`, `uk_tv_
    sponsorship_vod` (class C); DNA's `circulation`, `uk_dna_content_
    marketing`, `uk_tv_sponsorship_vod` (class C).
12. **Which channels should remain internal-only?** The class-C channels
    above, plus (new in this work package) DNA's `uk_dna_performance_
    display` for any *product-level/Overall* attribution specifically -
    its individual-outcome effects are real and well-identified, but its
    *aggregated* contribution is highly sensitive to which aggregation
    method is used (segment-hierarchy-derived vs. independently-fitted
    single-outcome), so an Overall-level figure for this one channel
    should be flagged as method-sensitive rather than presented as a
    single settled number.
13. **What is required to enable governed CPA/ROI?** Not a data gap -
    real, populated GBP spend data already exists for 27 of 28 channels
    (`uk_email` is the sole exception). What is required is a small,
    scoped code change binding that spend data into `core.attribution`/
    `core.media_units` as a field separate from the model's causal input
    (`X_media`, which is impressions/GRPs/clicks/etc. for most channels,
    not spend) - see `docs/wp2_10_remediation_evidence_20260825.md` item
    7 for the smallest implementation plan. Not implemented here; this is
    itself a governance decision about touching attribution's existing
    contract, not a routine fix.
14. **Can FH Model A (segment) now be certified for the bounded
    historical exercise?** Not yet. Items 4/5's evidence reframes WP2.9's
    open question: FH's divergences are now understood to originate in
    the outcome hierarchy specifically, and a same-configuration
    challenger without that hierarchy converges cleanly but fits worse
    and shows some channel-level disagreement. Certifying the segment
    model's individual-channel attribution without resolving (or at
    least formally accepting) this hierarchy-driven geometry would repeat
    exactly the DNA situation the analyst already declined to accept as
    a disclosed limitation.
15. **Can DNA segment Model A now be certified for the bounded historical
    exercise?** No, unchanged from the analyst's decision 1, now further
    substantiated: item 5 shows conclusively that the outcome hierarchy
    - not sampler tuning, not the media/control specification - produces
    DNA's divergent geometry, and that geometry is associated with up to
    a 78% (0.90) / 488% (0.95, smaller-sample) attribution swing for
    `uk_dna_non_brand_search` specifically and a 69.7% aggregation-method
    disagreement for `uk_dna_performance_display`. DNA segment-level
    individual-channel attribution remains internal diagnostic evidence.
16. **Can FH Overall and DNA Overall be used as the principal marketer-
    facing diagnostic views?** The posterior-derived versions (WP2.9)
    remain the better candidate for this role today - better fit than
    either segment average or the challenger, exact reconciliation to the
    segments, and now cross-checked (broadly, not perfectly) against an
    independently-fitted model with clean geometry. They should be
    presented as **diagnostic**, not certified, views, with the specific
    channel-level caveats above (especially `uk_dna_performance_display`'s
    method-sensitivity) attached.
17. **Is any statistical specification decision required before moving
    to Model B?** Yes, at least one, and it is now more specific than
    WP2.9 left it: whether to (a) accept the segment-level outcome
    hierarchy's divergence-associated geometry as a disclosed limitation
    for both products (matching the analyst's already-stated rejection of
    exactly this for DNA), (b) adopt the single-outcome/no-hierarchy
    structure demonstrated cleanly by the Overall challengers as the
    production form for individual-channel attribution (accepting its
    somewhat worse fit and loss of per-segment nuance), or (c) pursue a
    different hierarchy reparameterisation not yet tested (e.g. a shared
    `sigma_pool` across channels, or the lognormal alternative at full
    scale rather than only the short screen this work package could run).
    This is exactly the kind of governance decision this work package is
    directed not to make unilaterally.

## What was not done (per explicit instruction)

Model B, Search mediation, optimisation, and any replacement of the
segment-level Model A candidates with the Overall challengers were **not
started**. No production sampler default changed. No dynamic-baseline
mechanism was implemented, even as a diagnostic. No CPA/ROI plumbing
change was implemented.
