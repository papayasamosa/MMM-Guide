# DNA / FH Causal Structure

Design record for how DNA-targeted media, DNA kit sales, and Family History acquisition relate to
each other in the joint model, and how the same effect is prevented from being counted twice in
DNA and FH value - the instruction document's section 4.3 requirement. See docs/outcomes.md for the
outcome schema this builds on, and docs/modelling_methodology.md for the base joint FH model.

**`outcome_id`, not segment, is the model's identity dimension throughout this document (PR E - see
docs/decision_log.md and docs/outcomes.md).** Every `FHModelMeta` field and function below that used
to be keyed/named by segment (`FHModelMeta.segments`, `dna_segment`, `direct_dna_segments`,
`kit_only_segments`, `halo_eligible_segments`) is now keyed/named by outcome_id
(`FHModelMeta.outcome_ids`, `dna_outcome_id`, `direct_dna_outcome_ids`, `kit_only_outcome_ids`,
`halo_eligible_outcome_ids`) - this is what makes it possible for a Family History **sign-up** and a
Family History **GSA** to share one customer segment while remaining two independent outcome_ids, each
with its own independent direct/halo classification below.

## The pathways

Six distinct effects the instruction document asks to be distinguished:

1. **Direct media impact on DNA kit sales.** DNA-targeted media -> a DNA-product outcome (kit
   purchases from a new customer, or from an existing FH customer - `core.outcomes`). Modelled with
   full, undamped `beta[outcome_id][DNA-channel]` response against `dna_direct_media` (the channel's
   own adstocked + saturated series, no extra lag) - via `FHModelMeta.direct_dna_outcome_ids` (see
   "Mechanics" below). This is DNA media's primary, intended effect, and it is a **genuinely separate
   media input** from the halo pathway below, not the same lagged series scaled by a multiplier of
   one (see "Mechanics" for why that distinction matters and what changed).
2. **Direct media impact on FH GSAs.** Every channel's `beta[outcome_id][channel]` response on the
   New and Winback FH outcomes, unchanged from the base joint model - non-DNA media, and DNA media
   through the halo pathway (next item).
3. **DNA media halo onto FH DNA cross-sell.** The existing halo mechanism
   (`docs/modelling_methodology.md`), now genuinely a *second* pathway rather than a special case of
   the first: DNA-targeted media's effect on the FH DNA-cross-sell outcome can have **both** a direct
   component (item 1's full weight, since `dna_outcome_id` is always a `direct_dna_outcome_ids`
   member) and a delayed/halo component (this item, `halo_strength`, estimated, regularised toward
   zero by default) - the data decides the split, rather than the model assuming one. DNA media's
   effect on *other* FH outcomes (New, Winback) is halo-only, shrunk toward zero the same way.
4. **Kit-sales or DNA-customer pipeline effects on later FH conversion.** Explicitly **not modelled**
   - see "What is deliberately out of scope" below.
5. **Promotional price effects.** Reused, not reinvented: `ModelSpec.promo_cols` /
   `segment_control_cols` are keyed by segment name generically, so a DNA-product segment gets its
   own promo/price treatment exactly like an FH segment does, including the structured promotion
   calendar (`core.promotions.PromotionEvent`) for DNA promotions specifically. Promo/price terms are
   additive and structurally separate from the media terms in the linear predictor (`eta`) for every
   segment - a promotion is never absorbed into a channel's media coefficient, whichever way the
   promo series was built.
6. **Baseline cross-sell propensity.** Each segment's own `intercept` - a DNA segment's baseline
   level is estimated independently of any FH segment's, the same partial-pooling machinery already
   used for `market_offset`/`trend_coef`/`gamma_fourier`.

## Mechanics: two separate media inputs, not one lagged series and a multiplier

**This section describes the current design.** An earlier version of this mechanism represented
"direct" purely by fixing a DNA-kit segment's `halo_strength` at `1.0` while still routing it through
the *same* `dna_lag_weeks`-lagged media series every halo segment used - which meant a kit-sale
segment's fitted response (and its Shapley attribution) was actually computed against media from
`dna_lag_weeks` ago, not the current week, even though it was labelled "direct". A post-merge
correctness review caught this (it is not a true separation of the two pathways - see
docs/decision_log.md for the review and the fix) and it was corrected to the design below.

`FHModelMeta.dna_outcome_id` (a single Family History outcome_id) predates this work in intent -
originally `dna_segment` - and is unchanged in meaning, renamed for PR E's outcome_id-as-identity
redesign. Which outcome_id it resolves to used to be inferred by substring-matching outcome_ids for
`"dna"` when not passed explicitly - PR E.1 removed that fallback (a DNA-product kit-sale outcome_id
like `dna_new_kit` also contains "dna", making the heuristic genuinely ambiguous once DNA-product
outcomes exist in the same catalogue) in favour of an explicit, validated `ModelSpec.
fh_dna_cross_sell_outcome_id` config field (`core.outcomes.validate_fh_dna_cross_sell_outcome_id`) -
the model builders now raise if a fit has DNA-targeted channels and no `dna_outcome_id` is resolvable,
rather than guessing. See `docs/outcomes.md`'s "Explicit FH DNA cross-sell target" section.
`FHModelMeta.direct_dna_outcome_ids` lists every outcome_id that gets a **direct** pathway
from DNA-targeted media - `dna_outcome_id` is always a member, whether or not the caller lists it
explicitly (`_resolve_direct_dna_outcome_ids` enforces this); DNA-product kit-sale outcome_ids are the
other members once mapped. Two properties on `FHModelMeta` classify outcome_ids for this purpose:

- `kit_only_outcome_ids` - `direct_dna_outcome_ids` minus `dna_outcome_id`: outcome_ids with **only**
  a direct pathway (a kit sale isn't a delayed response onto itself, so there is no halo term to
  estimate).
- `halo_eligible_outcome_ids` - every outcome_id except the kit-only ones: outcome_ids with **only** a
  halo pathway (ordinary FH outcomes not in `direct_dna_outcome_ids` at all), except `dna_outcome_id`,
  which is the one outcome_id that can have **both** simultaneously.

Both PyMC builders (`build_fh_hierarchical_model`, `build_fh_market_specific_model`) construct two
genuinely separate media inputs from the DNA channel(s)' saturated series:

```python
dna_direct_media = sat_media[:, dna_channel_idx]                              # no extra lag
dna_halo_media = _market_grouped_lag(dna_direct_media, market_bounds, dna_lag_weeks)  # further-lagged
```

and route each segment through whichever input(s) apply to it, each with its own coefficient:

```python
eta_dna_direct = dot(dna_direct_media, beta[:, dna_idx].T) * has_direct[None, :]   # has_direct: fixed 0/1 mask
eta_dna_halo   = dot(dna_halo_media,   beta[:, dna_idx].T) * halo_strength[None, :] # estimated, HalfNormal, 0 for kit-only
eta_channels = eta_nondna + eta_dna_direct + eta_dna_halo
```

`beta[outcome_id][DNA-channel]` (the same partial-pooled response-strength parameter every other
channel uses) is reused for both terms - an outcome_id's underlying sensitivity to DNA media is one
number; which media reaches it, and whether an extra (regularised) halo multiplier applies on top,
is what differs by outcome_id. `has_direct` is a fixed structural mask (`direct_dna_outcome_ids`
membership), not a random variable - there's nothing to estimate about *whether* an outcome_id has a
direct pathway, only how strong it is (`beta`, already estimated). `halo_strength` is `HalfNormal`
(regularised toward zero, "smaller/delayed effect" is the default assumption) and is fixed at exactly
`0` (not estimated at all) for `kit_only_outcome_ids` - reported as a first-class parameter for every
outcome_id, so `0` there is a genuine, inspectable statement ("no halo pathway"), not a placeholder.

Concretely, per outcome_id:

| Outcome kind | Direct term (`dna_direct_media`) | Halo term (`dna_halo_media`) |
|---|---|---|
| Kit-only (e.g. `dna_new_kit`) | `beta * dna_direct_media` | none (fixed at 0) |
| `dna_outcome_id` (e.g. `fh_dna_crosssell`) | `beta * dna_direct_media` | `beta * halo_strength * dna_halo_media` (estimated) |
| Ordinary FH outcome (e.g. `fh_winback`) | none | `beta * halo_strength * dna_halo_media` (estimated) |

`pages/04_Model_Config.py` computes `direct_dna_outcome_ids` automatically from whatever DNA outcomes
are mapped on Structure (`core.outcomes.dna_kit_outcome_columns`) and stores it in session state;
`pages/05_Model_Training.py` passes it straight through to whichever builder is fitting. Every place
that replays this logic outside PyMC - `core.predict`/`core.market_specific_predict`'s `predict_mu`,
`steady_state_segment_response(_market_specific)`, `generate_channel_curve`/
`generate_market_channel_curve` - and `core.attribution`/`core.market_specific_attribution`'s Shapley
decomposition (`_channel_log_terms`) construct the same `dna_direct_media`/`dna_halo_media` split and
mask the halo term to `halo_eligible_outcome_ids` defensively (not merely trusting a fitted model's
`halo_strength` to already be `0` for a kit-only outcome_id - a kit-only outcome_id structurally
cannot pick up a halo contribution in the replay code, regardless of what's in a given `params`
object).
The steady-state functions (`steady_state_segment_response`, `generate_channel_curve`, and their
Model C equivalents) hold spend constant, so `dna_direct_media` and `dna_halo_media` converge to the
same value there (a lag of a constant series is that same constant) - the two terms' *weights*
(`has_direct` + `halo_strength`) still add correctly, they just can't be told apart by which media
series moved, since neither does.

## What is deliberately out of scope: the kit-to-FH pipeline effect

A plausible additional pathway is that buying a DNA kit changes a customer's likelihood of later
becoming (or converting) an FH customer - a "pipeline" effect distinct from DNA media's halo onto FH
cross-sell. **This is not modelled.** Two reasons:

- **Data**: establishing it needs person-level linkage between a DNA kit purchase and a later FH
  signup, which this aggregate weekly-panel model (counts per market/segment/week, no individual
  customer identifiers) cannot support. Modelling it anyway, from aggregate correlation alone, risks
  fabricating a causal claim the data can't actually justify.
- **Double counting risk if done carelessly**: if this pipeline effect were added *and* the DNA halo
  onto FH cross-sell were left as-is, the same underlying phenomenon (DNA activity driving FH
  cross-sell) could plausibly be counted through two different pathways - the direct halo term and an
  indirect kit-driven term - without a principled way to apportion how much belongs to each without
  person-level data to distinguish them.

Any real correlation between kit purchases and later FH signups that exists in the data is not lost -
it's implicitly absorbed into the FH segments' own fitted baseline/trend/seasonality, which is honest
(it reflects what the aggregate data shows) rather than being asserted as an explicit, separately
quantified causal pathway. This is a documented limitation, not a silent gap - see docs/limitations.md.

## Forward-looking pathway catalogue and DNA purchase-type segmentation (PR F)

The direct/halo pathway structure above is the only causal statement this codebase's *fitted model*
makes - `dna_channels`/`direct_dna_outcome_ids` remain what the PyMC builders actually read. PR F adds
`core.pathways.MediaOutcomePathway`, an explicit, persisted, fingerprinted catalogue of every
`(channel, target_outcome_id)` relationship this project believes exists (a primary direct effect, a
trusted cross-product effect, a speculative/exploratory one not yet trusted for planning, or an
explicitly excluded one) - schema, validation and drift detection only, not yet read by any fitting
code. See `docs/media_outcome_pathways.md` for the full design record, including how this catalogue is
designed to target the roadmap's expanded future outcome set (Family History net bill-through count,
finance-date GSA, and DNA purchase-type outcomes below) without assuming every FH KPI is a GSA or every
DNA KPI is a generic kit-sale total.

A related roadmap item reclassifies DNA kit purchases by the relationship between the purchasing and
activating account (`self_activated`/`gifted_activated`/`unactivated`) rather than only
new-customer-vs-existing-FH-customer. **The most important caveat, carried through every layer of this
future work:** an unactivated kit is not definitively a gift - it may be a self-purchase never
activated, a gift not yet received, a delayed activation, or a linkage failure. `unactivated` is always
kept as its own atomic category; a `gift_or_unactivated` roll-up is only ever an explicitly labelled
reporting assumption, never silently substituted for the atomic category. See
`docs/media_outcome_pathways.md` for the full classification/censoring design and `docs/limitations.md`
for why this is not yet implemented.

## How double counting is avoided today

- Every outcome_id - FH or DNA-product - has its own independent Negative-Binomial likelihood over its
  own outcome column. Nothing sums a DNA kit-sale count and an FH GSA count into one figure anywhere
  in the fitting or prediction code - and, since PR E, this holds even when two outcome_ids share a
  customer *segment* (e.g. a Family History sign-up and GSA both on segment "New"): each still has
  its own independent likelihood, keyed on `outcome_id`, never on `segment`.
- The direct and halo pathways are structurally separate additive terms (`eta_dna_direct` +
  `eta_dna_halo`, see "Mechanics" above) built from two different media series - an outcome_id either
  isn't in `direct_dna_outcome_ids` (direct term contributes exactly `0`) or isn't in
  `halo_eligible_outcome_ids` (halo term contributes exactly `0`), so there is no way for the same
  media-week's effect on the same outcome_id to be counted through both terms at once. `dna_outcome_id`
  is the one exception by design (both terms genuinely apply), and its two terms use disjoint media
  inputs (`dna_direct_media` vs. `dna_halo_media`) even then - see
  `ancestry_mmm/tests/test_predict.py::TestPredictMuDirectHaloSeparation` and its Model C/attribution
  equivalents for the tests proving this directly (a spend spike's direct-week and lagged-week
  responses are checked to land on disjoint weeks, and `dna_outcome_id`'s response at each of those
  weeks is checked to exactly equal the corresponding single-pathway outcome_id's).
- `core.attribution.total_fh_contribution` takes an `outcome_ids` parameter specifically for this:
  pages that build a "total FH GSA" view (Results & Curve Bank, Project Export) pass
  `core.outcomes.fh_gsa_outcome_ids(meta)` - PR E.1 replaced the earlier "every outcome_id that isn't a
  DNA-product outcome" filter (which would have silently folded a distinct FH sign-up outcome into the
  same total as the GSA outcome) with an explicit `product=Family History, metric=GSA` selector, so a
  kit-sale count *and* a sign-up count are both kept out of the GSA total, never summed into it and
  reported as one meaningless combined unit. `outcome_channel_summary`'s per-outcome_id table (renamed
  from `segment_channel_summary`) is unaffected - a DNA or sign-up outcome's own contribution is shown
  in its own right, which is correct and desired.
- There is currently no cross-product **value** combination (e.g. "total business value across FH and
  DNA") - `OutcomeDefinition.value_weight` exists per outcome, but nothing sums FH value and DNA value
  together yet. That combination is future work (the instruction document's section 4.4, not part of
  this PR) and must apply the same "no shared effect counted in both" discipline documented here when
  it's built.

## Validation

**Direct/halo separation (current design).** Simulation-based recovery testing was run offline (not a
committed test - matches the precedent for Model C's original recovery check, see docs/decision_log.md
for why) with a synthetic panel where the ground truth genuinely separates the two pathways: kit sales
respond only to the *current* week's DNA media, an ordinary FH halo segment (Winback) responds only to
a *lagged* week's, and the FH DNA-cross-sell segment responds to **both** (a larger direct weight, a
smaller delayed weight) - the case this design is specifically for. Fit with a real (350 tune/350
draws, 2 chains) MCMC run, the model correctly recovered:

- The kit-only segment's `halo_strength` fixed at **exactly `0.0`** (not approximately - it's not
  estimated at all for this segment, by construction) with a positive, substantial recovered `beta`
  (2.95) tracking the true unlagged relationship.
- The FH DNA-cross-sell segment recovering **both** components: a positive, substantial `beta` (1.70,
  the direct term) *and* a meaningfully nonzero `halo_strength` (0.33, the delayed term) - proving the
  dual-pathway estimation genuinely works with real (MCMC, not just NumPy-replay) inference, not only
  on paper.
- The ordinary halo-only segment (Winback) still recovering a meaningfully nonzero `halo_strength`
  (0.49), unaffected by the direct/halo split for segments that don't have a direct pathway at all.

See the decision log entry for this PR for the exact synthetic ground truth and full result. The fast,
non-MCMC parts (the direct/halo construction itself, at both the PyMC-graph-construction level and the
NumPy-replay/attribution level, including the four required invariants - kit response doesn't inherit
the halo lag, FH halo does, changing the lag doesn't move the direct kit response, direct+halo add
without double counting) are unit tested directly and committed - see
`ancestry_mmm/tests/test_hierarchical_model.py`, `test_predict.py::TestPredictMuDirectHaloSeparation`,
`test_market_specific_predict.py::TestPredictMuMarketSpecificDirectHaloSeparation`,
`test_attribution.py::TestShapleyDirectHaloSeparation`,
`test_market_specific_attribution.py::TestShapleyMarketSpecificDirectHaloSeparation`.
