# WP2.10: Model A final remediation evidence (2026-08-25)

Status: evidence for analyst review, in progress. Items 1, 2, 3 (context-
check step), and 7 are complete below with real numbers. Items 4, 5, 6,
8, and the final item 9 decision package are added once the corresponding
background fits/backtests complete (challenger models, prepared-frame
backtest). No statistical specification of the governed segment Model A
candidates changed. No production sampler default changed.

## Item 1: divergence localisation on the `target_accept=0.95` traces

Reused `scripts/run_uk_wp2_9_divergence_localization.py` unchanged,
pointed at the WP2.9 `target_accept=0.95` traces
(`D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-target-accept-
0.95-20260825\`) instead of the 0.90 traces - same method, same channel-
level Shapley contribution comparison, no new code.

**Family History (13 divergent draws)**: largest median contribution
shifts (divergent vs. non-divergent) - `uk_fh_non_brand_search` **+85.9%**,
`circulation` **+73.7%**, `uk_brand_tv` **+63.5%**, `uk_email` **-60.9%**,
`uk_fh_affiliate` **+48.3%**.

**DNA Kit (46 divergent draws)**: `uk_dna_non_brand_search` **+487.7%**,
`uk_tv_sponsorship_linear` **-66.5%**, `uk_brand_tv` **-53.9%**,
`uk_tv_sponsorship_vod` **+52.3%**, `uk_influencer` **-47.0%**.

**Answer to the direct question, for both products**: no. The remaining
divergent region at 0.95 still occupies materially different attribution
territory for several channels - if anything the *proportional* shifts
are as large or larger than at 0.90 for the worst-affected channel in
each product, though the smaller divergent-draw counts (13, 46) make
these percentage estimates noisier than the 0.90 estimates (70, 53
divergent draws) - a caveat reported transparently, not smoothed over.
No numerical materiality tolerance was invented; these are the actual
differences for analyst interpretation. **This directly fails the
condition in item 1's own brief for recommending formal 0.95 adoption**
("if FH's remaining divergent region no longer has meaningful
contribution differences") - it still does, so no such recommendation is
made for Family History, consistent with the analyst's own decision 2
(0.95 remains provisional, pending exactly this check).

Full per-parameter localisation (boundary clustering, correlation-
structure shifts, energy/tree-depth/acceptance-rate conditioned on
divergence) is in `wp2_10_divergence_localization_{model}.json`
(same schema as WP2.9's, now for the 0.95 traces).

## Item 2: hierarchical pooling geometry

`core.hierarchical_model.build_fh_hierarchical_model`'s partial-pooling
layer: `log_beta[o, c] = mu_channel[c] + sigma_pool[c] * z_offset[o, c]`,
non-centred, one `sigma_pool[c] ~ HalfNormal(0.3)` per channel
(`dims=("outcome","channel")`, `n_outcomes` = 3 for FH, 2 for DNA).

**Mechanistic explanation (why the funnel remains weakly identified)**:
a hierarchical variance parameter's identifiability improves with the
number of groups it pools across. With only 2-3 outcome groups per
channel, `sigma_pool` has very little data to move it away from its
prior. This is not a hypothesis - it is directly visible in the fitted
posterior: **every channel's `sigma_pool` posterior mean sits at
0.24-0.26 for both products (one exception below), essentially
identical to `HalfNormal(0.3)`'s own prior mean of 0.239** (`0.3 *
sqrt(2/pi)`). The non-centred parameterisation (already in use) removes
the classic `mu`/`sigma` correlation funnel but cannot manufacture
identifying information the data does not contain with this few groups.

**Which channel/outcome combinations produce the strongest pooling
tension**: FH's top 5 by `sigma_pool` - `uk_podcast_audio`,
`uk_fh_midfunnel_social`, `uk_midfunnel_display`, `uk_influencer`,
`uk_midfunnel_olv` (all still ~0.24-0.25, barely distinguishable from
each other or from the prior). DNA's top 5 - `uk_dna_performance_display`
(**0.445 - the one genuine exception**, see below),
`uk_dna_non_brand_search`, `uk_tv_sponsorship_linear`, `circulation`,
`uk_dna_affiliate` (0.25-0.26, at the prior-dominated cluster like FH).

**Sparse channels do not disproportionately drive the funnel**: mean
`sigma_pool` for sparse vs. non-sparse channels is statistically
indistinguishable in both products (FH: 0.237 sparse vs. 0.240 non-
sparse; DNA: 0.238 sparse vs. 0.257 non-sparse) - directly refuting the
"sparse channels dominate the pooling tension" hypothesis.

**How different are the fitted per-outcome channel effects, in practice**:
`fitted_beta_max_over_min_ratio_across_outcomes` (the actual multiplicative
channel effect the model uses, `exp(log_beta)`, compared across outcomes)
is 1.02-1.14 for nearly every channel in both products - the model
behaves almost like full pooling in practice for nearly every channel,
regardless of the nominal partial-pooling structure, because `sigma_pool`
is prior-dominated. **`uk_dna_performance_display` is the one real
exception in both this metric and its own `sigma_pool`**: it has the
highest `sigma_pool` (0.445, genuinely above the prior-dominated cluster)
and is independently the one channel WP2.8/WP2.9 already flagged as
strongly data-identified (`decay_rate` posterior/prior std ratio 0.30)
and the channel with the most stable, largest-share contribution in item
7A's product-level totals - three independent pieces of evidence agreeing
that this specific channel's two DNA outcomes genuinely differ, while
every other channel's genuinely doesn't (or the data cannot tell).

**Diagnostic short-screen comparison of gated pooling-prior alternatives**
(`prior_config["pooled_beta_reference"]` - complete pooling, and
`prior_config["pooling_sigma_prior_distribution"]=="lognormal"` - an
alternative `sigma_pool` prior family with no mass at exactly zero; both
already existed in `core.hierarchical_model` before this work package,
gated off by default; short-screen configuration matches
`scripts/run_uk_wp2_7_short_sampler_screen.py`'s own precedent -
`draws=100, tune=150, chains=2, target_accept=0.95`):
[results in `wp2_10_pooling_diagnostic_screens_{model}.json` once the
background run completes].

**Candidate concepts assessed, not selected** (per the brief): stronger
`sigma_pool` regularisation would have little effect since `sigma_pool`
is already sitting at its prior for nearly every channel - the prior
itself, not insufficient shrinkage toward it, is the binding constraint.
The lognormal alternative (no mass at exactly zero) is the more
mechanistically motivated candidate, since NUTS divergences in a
funnel-shaped posterior concentrate precisely where the variance
parameter approaches zero - see the diagnostic screen result above for
whether it actually changes divergence behaviour. Complete pooling
(`pooled_beta_reference=True`) would simply formalise what the fitted
model already does in practice for every channel except
`uk_dna_performance_display` - not selected as a production change here,
but directly informing item 4/5's single-outcome challenger model design
(which uses this exact gate, since a single outcome has no groups to
partially pool across at all).

## Item 3 (context-check step): does existing governed context explain
## the shared residual correlation?

WP2.9's finding stands unchanged: FH New/Winback residual correlation
r=0.77; DNA New/Existing residual correlation r=0.96; per-outcome
residual correlation with the model's own trend/season/controls/media is
uniformly small (|r|<0.20).

**Checked against every context variable already present in the UK
source pack** (`context_and_external_factors_data_native_preserved.xlsx`,
30 `variable_id`s - only the two category-demand Google Trends series are
currently wired in as production controls; the other 28 are `role=
"diagnostic"` in the pack's own `variable_dictionary` - competitor web
visits, UK CPIH/mortgage-rate/petrol-price/unemployment macro series,
competitor brand-search interest, and brand-awareness survey data -
present in the pack but explicitly not yet reviewed for a causal role).
Aligned to the weekly model grid by as-of/forward-fill for this
diagnostic correlation check only (not the governed frequency-alignment
pipeline, since nothing is being added to the model).

**Strongest correlations found**: FH New residual vs.
`findmypast_brand_search_interest_google_trends` (a **competitor's**
brand-search interest) r=**0.47**; FH DNA-cross-sell vs. MyHeritage
brand-search interest r=0.17; FH Winback vs. Ancestry's own brand-search
interest r=0.26; DNA New vs. the same Findmypast series r=**-0.27**; DNA
Existing vs. the same series r=-0.24.

**This does not explain the shared factor**: the same competitor
variable is the top hit for both FH New and DNA New/Existing, but at
very different (and for DNA, opposite-signed) strengths, and FH's own
strongly-correlated partner outcome (Winback, r=0.77 with New) shows its
*own* strongest correlation with a different variable (Ancestry's own
brand search) at a much weaker r=0.26 - no single already-present context
variable accounts for the much stronger *within-product* shared factor.
Calendar events (`events` sheet, 79 UK bank-holiday/observance dates)
were checked directly against each product's largest positive/negative
residual weeks: most large-residual weeks have **no** nearby event at all
(e.g. FH New's 2023-01-29, 2023-07-30, 2024-07-28), and the one
recurring pattern found (Christmas week appearing as both a positive
residual week in one year and adjacent-week negative residual in another)
looks like a within-holiday-period shape mismatch, not a clean single-
event explanation.

**Conclusion**: no omitted-event, pricing, or already-available-context
explanation was found. This is reported as a negative result, not
grounds to add any of these variables to the model (several are
explicitly flagged in the pack's own documentation as potentially
downstream of media or causally unreviewed) - the shared factor remains
genuinely unexplained by anything already governed and available.

**Dynamic-baseline mechanism comparison**: `docs/wp10_time_varying_
baseline_decision_package.md` (Work Package 10, PR #283, 2026-08-18) and
its target-state requirement `docs/approved_requirements/REQ-BASELINE-
001.md` already cover exactly this gap - a genuinely unresolved analyst
decision, not newly discovered here. That package's Candidate T2 ("latent
random-walk baseline with explicit process choice") is the closest match
to this work package's own suggested "Gaussian random walk or similarly
regularised dynamic baseline" mechanism. **No gated diagnostic
implementation of any time-varying-baseline mechanism exists anywhere in
the current repository** (confirmed: no `time_varying`/`GaussianRandomWalk`/
`random_walk`/`latent_baseline` symbol anywhere in `ancestry_mmm/`) -
REQ-BASELINE-001 explicitly forecloses implementing any candidate,
including as a diagnostic, before the analyst selects one ("this record
does not approve an implementation... three genuinely unresolved
questions block any implementation"). Per this work package's own
instruction ("if implementing a new hierarchy would require new model
algebra or an unapproved statistical choice, do not implement it... 
produce a decision package instead"), **no new dynamic-baseline code was
written**. This work package's new evidence (the specific 0.77/0.96
residual correlations, the context-variable negative result, the
calendar-event negative result) is added as fresh supporting evidence to
the existing WP10/REQ-BASELINE-001 decision point rather than duplicating
it - see the final decision package for the consolidated recommendation.

## Item 6: prepared-frame fold-refit backtest - genuinely blocked, not forced

Attempted `application.fold_refit_service.run_leakage_safe_fold_refit`
(the `RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY` tier WP2.9 identified as
usable without fabricated SourceVersion history) against the real
Family History segment Model A candidate. It failed deterministically,
not from a transient issue:

```
ValueError: dna_outcome_id 'fh_net_billthrough_count_dna_cross_sell' is
not one of the model's outcome_ids: ['fh_new', 'fh_dna cross-sell', 'fh_winback']
```

**Root cause**: `fit_fold_with_real_model` (the real-refit engine
`run_leakage_safe_fold_refit` calls once per fold) builds each fold's
frame via `prepare_fh_modeling_frame(train_df, spec)` with **no explicit
`outcomes=` argument** - `data.preprocessor.prepare_fh_modeling_frame`
therefore falls back to `core.outcomes.resolve_outcome_definitions`'s
legacy migration path (`fh_outcomes_from_spec(spec.segment_outcomes,
...)`), which derives its own outcome_ids directly from `segment_outcomes`
keys (`fh_new`, `fh_dna cross-sell`, `fh_winback`) - **not** the real
governed catalogue's outcome_ids (`fh_net_billthrough_count_new`, etc.)
that the actual production fit uses (`scripts/run_uk_production_fit.py`
always passes `outcomes=model_outcomes` explicitly). `core.
hierarchical_model.build_fh_hierarchical_model` then fails validating
`dna_outcome_id` against this legacy, non-matching outcome_id list.

This is a genuine, pre-existing incompatibility between the fold-refit
backtest infrastructure and the current `OutcomeDefinition`-catalogue-
based Model A specification (predating WP2.10) - not a transient failure,
and not something this work package's brief authorises fixing by
changing `fit_fold_with_real_model`'s tested contract ("run this existing
backtest if it can be used **without changing its governed semantics**").
A separate single-fold DNA attempt (whose spec does not set a
`dna_outcome_id`, so it does not hit this exact check) instead hit an
unrelated C++ compile error from the shared MinGW toolchain while two
other real fits were compiling concurrently on this machine - not chased
further given the FH leg's failure already establishes the blocking issue
structurally, independent of any transient compile condition.

**Not forced, not fabricated.** The smallest fix, if the analyst wants
this backtest tier usable for the current catalogue-based candidates, is
a small, scoped change to `fit_fold_with_real_model`'s signature (accept
an optional `outcomes: list[OutcomeDefinition] | None = None` override,
defaulting to today's behaviour so no existing caller/test is affected) -
not implemented here, since it changes an existing, separately-tested
governed function's contract and is itself a decision point about that
function's scope, not a routine engineering fix to make within this
already-large work package.

## Item 7: CPA/ROI data-contract audit - resolved, not a blocker

WP2.9 concluded CPA/ROI could not be certified because `core.
prefit_identifiability`'s `_governed_units`/`media_input_specs` helper
returned no unit metadata for any channel. **This audit found that
conclusion was incomplete**: real, governed spend data already exists in
the UK source pack, just not wired into that helper or into `core.
attribution`/`core.media_units`.

`activity_data_approved_metadata_and_structural_zeros.xlsx`'s
`activity_dictionary` sheet has, per `activity_id`: `model_input_column`/
`model_input_measure`/`model_input_unit` (the model's actual causal
input - impressions, GRPs, clicks, admissions, or circulation for every
channel except `uk_dna_affiliate`/`uk_fh_affiliate`, which already use
spend as the model input) and a **separate** `spend_column`/`currency`
field. Verified against the real weekly `activity_data` sheet:
**27 of 28 channels have real, populated GBP spend data** (non-zero row
counts and totals for every `activity_id` checked). The sole exception is
`email` (`uk_email`): `spend_column` is blank in the dictionary and the
weekly data confirms zero populated spend rows - `sends` (a volume count)
is the only measure available for that channel.

**This resolves the "same column" false constraint** `outcome_channel_
summary`'s existing ROAS/CPA formula currently assumes (`frame["X_media"]`
used directly as spend) - the model's causal input and the governed spend
figure are legitimately different columns for 26 of 28 channels, and the
data to bind them correctly already exists.

**Smallest implementation plan** (not implemented in this work package -
this is data-contract remediation for `core.attribution`/`core.
media_units`, independent of the modelling work above):

1. Extend whatever loads `media_input_specs`/`_governed_units` (currently
   returns `None` for every channel per WP2.9's own check) to also read
   each channel's `spend_column`/`currency` from the activity dictionary
   already present in the adopted source pack, alongside the existing
   `model_input_unit` it already resolves for the causal input.
2. Thread a per-channel spend series (separate from `X_media`) into the
   frame the same way `X_media`/controls already are, so `core.
   attribution.outcome_channel_summary` and `core.media_units.
   compute_cpa_by_product` can multiply channel volume by the real spend
   series instead of `X_media`, only where a governed spend column and
   currency exist.
3. For `uk_email` specifically, CPA/ROI must remain unsupported (`NaN`,
   as `outcome_channel_summary` already does for missing LTV) until a
   real spend figure is supplied for that channel - do not substitute
   `sends` or any other volume measure as a spend proxy.
4. This is a genuinely new production code path (touches attribution's
   spend contract) - it should go through this repository's normal
   requirement/decision process before implementation, not be silently
   added; flagged here as the smallest concrete next step, not decided
   or implemented by this document.

Modelling work continued independently of this data-contract
investigation, per the brief.
