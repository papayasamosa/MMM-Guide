# WP2.9 item 3 and item 10: sampler sensitivity result and Model A
# certification decision package (2026-08-25)

Companion to `docs/wp2_9_certification_evidence_20260825.md` (items 1, 2,
4–9). This document completes item 3 (the target_accept=0.95 comparison)
and item 10 (the final certification decision package). **This is a
decision package, not a certification** — it identifies the one
remaining choice that requires analyst input rather than making it.

## Item 3: target_accept=0.95 sampler sensitivity — a split result

Both models: `chains=4, draws=2000, tune=1000`, `scripts/run_uk_
production_fit.py` unmodified, identical statistical specification.
Traces at `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-
target-accept-0.95-20260825\`. Comparison:
`scripts/run_uk_wp2_9_sampler_sensitivity_comparison.py`.

| | Family History | DNA Kit |
|---|---|---|
| Divergences 0.90 → 0.95 | **70 → 13** (−81%) | **53 → 46** (−13%) |
| Divergences by chain, 0.90 | 17, 14, 16, 23 | 24, 13, 1, 15 |
| Divergences by chain, 0.95 | 3, 2, 4, 4 | 15, 7, 6, 18 |
| R-hat max 0.90 → 0.95 | 1.0031 → 1.0029 | 1.0027 → 1.0029 |
| ESS bulk min 0.90 → 0.95 | 1,821.5 → 1,332.2 | 3,297.8 → 2,181.6 |
| BFMI (min across chains) 0.90 → 0.95 | 0.946 → 0.895 | 0.897 → 0.875 |
| Max tree depth 0.90 → 0.95 | 6 → 6 | 6 → **8** |
| Mean acceptance rate 0.90 → 0.95 | ~0.89 → ~0.94 | ~0.90 → ~0.94 |
| Fit R² (all outcomes) | unchanged to 3 d.p. | unchanged to 3 d.p. |
| Largest channel-contribution shift | 16.2% (`uk_midfunnel_display`) | 20.2% (`uk_midfunnel_olv`) |

**Family History**: 0.95 **materially and uniformly** reduces divergences
across all four chains (81% reduction), with R-hat/fit metrics essentially
unchanged and ESS still comfortably healthy (1,332 minimum). BFMI dips
slightly but stays well above any concerning level. This matches the
"materially reduces divergences while leaving the substantive posterior
effectively unchanged" pattern the brief asks about — a genuine candidate
for adopting 0.95, **with the caveat** that individual channel
contributions still shift by double-digit percentages for a handful of
channels (not "effectively unchanged" at that granularity).

**DNA Kit**: 0.95 **does not resolve** the divergence pattern. The
reduction is small (13%) and **not uniform** — chain 3 went from 1
divergence to 6, chain 4 from 15 to 18; only chains 1–2 clearly improved.
Tree depth increased from 6 to 8 (using more of the 10-deep budget, not
less), and BFMI also dipped. This is the signature of geometry that
step-size tuning alone does not fix — consistent with item 2's finding
that both products' divergences concentrate in the **hierarchical
pooling** parameters (`mu_channel`/`sigma_pool`), which are already
non-centre-parameterised (`z_offset`) — i.e., the standard first-line fix
for a hierarchical funnel is already in place, and residual divergence at
0.95 suggests the funnel is a genuine feature of this specific
hierarchy/data combination, not a parameterisation bug fixable by a
sampler-config change alone.

**Per the brief's explicit instruction, this result does not justify
increasing target_accept, tune, draws, or tree depth further for DNA** —
the correct next step for DNA, if pursued, is a geometry-remediation
review (e.g. re-examining `sigma_pool`'s prior or the pooling structure
itself), not another sampler-parameter escalation. This is flagged as an
open item below, not implemented.

## Item 10: certification decision package

### Sampling
- WP2.8's divergences are real geometry, concentrated in hierarchical
  pooling parameters, and materially shift specific channels' reported
  contribution (up to 78% for DNA `uk_dna_non_brand_search`, 44% for FH
  `uk_tv_sponsorship_linear`) — not immaterial noise.
- target_accept=0.95 **materially reduces** FH's divergences (81%,
  uniform across chains) without changing fit/R² and with ESS remaining
  healthy. It **does not materially reduce** DNA's divergences (13%,
  non-uniform, with worse tree-depth/BFMI trade-offs).
- Changing target_accept did **not** materially alter either product's
  substantive posterior fit (R² unchanged to 3 decimal places for every
  outcome), though a handful of individual channels' median attributed
  contribution shifted 12–20% between the two configurations.
- **Recommendation for analyst decision**: 0.95 is a defensible candidate
  replacement for 0.90 for **Family History** specifically. It is not a
  fix for **DNA Kit**, whose residual divergence pattern needs a
  geometry-remediation decision, not further sampler escalation, if the
  analyst wants it resolved rather than accepted as a disclosed
  limitation.

### Model fit
- FH New's low R² (0.068 at 0.90) is not a convergence artefact — it
  persists at 0.95 (0.065) — and mainly reflects **low exploitable signal
  relative to a mean-only baseline** (model RMSE only 3.4% better than
  flat mean) rather than a specific failure to capture peaks/troughs or a
  wrong baseline shape.
- FH New's attribution should be treated with real caution given this,
  but is not necessarily unusable: FH Overall (the product-level total,
  item 7A) achieves R²=0.383, a materially more useful fit for the
  quantities a marketer would actually consult.
- DNA segments individually fit reasonably (R² 0.50–0.64); DNA Overall
  achieves R²=0.600.

### Temporal structure
- Strong evidence of a **common, product-level omitted temporal/demand
  component**: FH New/Winback residuals correlate at r=0.77; DNA New/
  Existing residuals correlate at r=0.96 (almost a single shared factor).
  Correlation with the model's own trend/seasonality/control/media terms
  is uniformly small (|r|<0.20 for every outcome), so this is not simply
  a mis-shaped existing covariate.
- **A future specification change is warranted** to investigate this
  (the brief explicitly prohibits selecting or implementing one now —
  random-walk/AR error, time-varying intercept, new Fourier order, and
  new controls were all correctly not attempted in this work package).

### Identification
- Zero channels in either product are "well identified" on decay/Hill
  K/Hill S by WP2.8's own ratio (>0.7 posterior/prior std ratio counts as
  weakly identified) — this is now cross-checked against contribution
  stability rather than left as a bare statistical fact:
  - **FH**: 10/19 channels class A (weak transform, stable contribution),
    5/19 class B (both uncertain), 4/19 class C (insufficient support:
    `circulation`, `uk_fh_content_marketing`, `uk_influencer`,
    `uk_tv_sponsorship_vod`).
  - **DNA**: 9/18 class A, 6/18 class B, 3/18 class C (`circulation`,
    `uk_dna_content_marketing`, `uk_tv_sponsorship_vod`).
  - `uk_dna_performance_display` is the one channel with genuinely strong
    data-driven identification (WP2.8's decay_rate ratio 0.30) and it
    independently has the most stable contribution (lowest relative
    interval width) and largest volume share of any DNA channel — a real
    consistency check that the classification is measuring something
    meaningful.
- **Channel-level CPA/ROI is not certified as reliable evidence** for
  either product: no channel carries governed spend-unit metadata, and
  computed ROI spans roughly six orders of magnitude across channels
  (e.g. FH `uk_tv_sponsorship_linear`≈64 vs. `uk_fh_performance_social`
  ≈5.6e-5), strong evidence `X_media` mixes heterogeneous physical units
  rather than uniform currency spend.

### Product totals
- **FH Overall**: R²=0.383, RMSE=1,213.0, MAE=903.9, MAPE=14.4%,
  bias=34.5, PPC 90% coverage=84.0%, residual lag-1 autocorr=0.27,
  DW=1.47. Baseline (median)=431,062; incremental (median)=299,983.
- **DNA Overall**: R²=0.600, RMSE=2,429.5, MAE=1,483.7, MAPE=38.5%,
  bias=28.3, PPC 90% coverage=83.2%, residual lag-1 autocorr=0.19,
  DW=1.60. Baseline (median)=229,874; incremental (median)=273,161.
- Reconciliation (per-draw sum of segment contributions = product-level
  total) is exact to floating-point tolerance (≤4.7e-10) for both
  products — the aggregation is genuine, not approximate.
- Product-level fit is **substantially more usable** than any individual
  segment (FH Overall 0.383 vs. FH New's 0.068 alone), consistent with
  summing correlated-but-imperfectly-correlated residual series
  partially cancelling idiosyncratic noise. Channel-level contribution
  stability at the product level is descriptively reported per-channel
  (not uniformly better or worse than every segment) in the evidence
  JSON — a modest, not dramatic, stabilisation given only 2–3
  constituent outcomes are summed.

### Governance
- **Fingerprints are now real and content-derived** for `candidate_spec_
  fingerprint`/`prepared_frame_fingerprint` (PR #313); `causal_graph_
  fingerprint` legitimately remains the null-fingerprint constant for
  this no-explicit-graph candidate. A fail-closed gate now blocks
  official submission if either required fingerprint is unbound.
- **Analyst rationale is correctly re-bound** to the corrected evidence
  identity (`scripts/run_uk_wp2_9_retain_analyst_rationale.py`); both
  models confirm `readiness=review_recommended`, `official_submission_
  allowed=True`, superseding the WP2.8 retention that was bound to a
  null-hash identity.
- **Circulation remains an unresolved data caveat** — unchanged,
  uncapped, unwinsorised, undeleted, and independently corroborated by
  its own class-C (insufficient response-curve support) classification
  in both products.
- The governed leakage-safe fold-refit backtest could not be validly run
  (no `SourceVersion` registration exists for this static historical
  pack) — documented as a limitation, not fabricated.

### Certification

**Model A can be certified for the bounded UK historical exercise as
diagnostic/exploratory evidence, with explicit, named exclusions —
contingent on one analyst decision about DNA's residual divergence.**

**What can be certified now:**
- The governed pre-fit → full-posterior → post-fit evidence chain is now
  correctly identity-bound (item 1 fixed) and the analyst rationale is
  correctly retained against real evidence.
- Convergence is good for both products by R-hat/ESS/BFMI (item 5's WP2.8
  numbers), and item 2/3's divergence analysis shows the residual
  divergences are a known, localised (hierarchical pooling), and now
  quantified geometry feature — not an unexamined black box.
- FH Overall and DNA Overall (item 7A) are ready to serve as the
  top-level marketer-facing view, with segment-level results available
  beneath them, reconciliation verified.
- Channel-level volume/share attribution is usable **with the explicit
  class A/B/C caveats already attached per channel** — class A/B channels
  may be shown with appropriate uncertainty framing; class C channels
  (`circulation`, `uk_fh_content_marketing`/`uk_dna_content_marketing`,
  `uk_influencer` (FH only), `uk_tv_sponsorship_vod`) should **not** be
  presented as having a reliable response curve.

**What remains uncertain / explicitly excluded from certification:**
- Channel-level CPA/ROI (no governed spend units — not certified for any
  channel in either product).
- FH New's segment-level attribution specifically (R²=0.068, essentially
  a mean-baseline-level fit) — usable only with strong caveats; prefer
  FH Overall for anything user-facing.
- The common omitted temporal component (item 5) is a known, unaddressed
  gap — any forward-looking claim (scenario/forecast) inherits this
  uncertainty beyond what the model's own credible intervals show.
- Hill/adstock saturation and carryover interpretation for any single
  channel remain weakly identified everywhere — reported, not resolved.

**The smallest decision required before broader certification**: whether
DNA Kit's residual divergence at target_accept=0.95 (46/8,000, non-
uniform across chains) is accepted as a disclosed, bounded limitation for
this historical exercise, or whether it triggers a geometry-remediation
review of the DNA hierarchical pooling parameterisation before DNA-side
evidence (particularly DNA Kit's individual-channel contributions, which
shift up to 78% between divergent and non-divergent posterior regions) is
used for anything beyond internal diagnostic review. This is a judgement
call about acceptable risk for a **bounded historical, non-production**
exercise, not a technical question this work package can resolve on its
own — flagged here for the analyst rather than decided.

## What was not done (per explicit instruction)

Model B, Search mediation, optimisation, a separately fitted FH Overall
challenger model, and a separately fitted DNA Overall challenger model
were **not started**. This document stops at Model A certification
evidence for analyst review.
