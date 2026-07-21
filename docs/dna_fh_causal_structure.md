# DNA / FH Causal Structure

Design record for how DNA-targeted media, DNA kit sales, and Family History acquisition relate to
each other in the joint model, and how the same effect is prevented from being counted twice in
DNA and FH value - the instruction document's section 4.3 requirement. See docs/outcomes.md for the
outcome schema this builds on, and docs/modelling_methodology.md for the base joint FH model.

## The pathways

Six distinct effects the instruction document asks to be distinguished:

1. **Direct media impact on DNA kit sales.** DNA-targeted media -> a DNA-product outcome (kit
   purchases from a new customer, or from an existing FH customer - `core.outcomes`). Modelled with
   full, undamped `beta[segment][DNA-channel]` response - the same weight `dna_segment` itself gets,
   via `FHModelMeta.direct_dna_segments` (see "Mechanics" below). This is DNA media's primary,
   intended effect.
2. **Direct media impact on FH GSAs.** Every channel's `beta[segment][channel]` response on the New
   and Winback FH segments, unchanged from the base joint model - non-DNA media, and DNA media
   through the halo pathway (next item).
3. **DNA media halo onto FH DNA cross-sell.** The existing halo mechanism
   (`docs/modelling_methodology.md`): DNA-targeted media's effect on the FH DNA-cross-sell segment
   is *also* full-weight (it is `dna_segment`, always a member of `direct_dna_segments`) - this
   predates the DNA/FH architecture work and is unchanged by it. DNA media's effect on *other* FH
   segments (New, Winback) is shrunk toward zero (`halo_strength`, partially pooled, "smaller effect
   elsewhere").
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

## Mechanics: `direct_dna_segments`

`FHModelMeta.dna_segment` (a single Family History segment) predates this work and is unchanged in
meaning. `FHModelMeta.direct_dna_segments` generalises the *mechanical* treatment: every segment in
this list gets DNA-targeted media's full, undamped `beta` response (`halo_strength = 1`, fixed, not
estimated); every segment *not* in this list gets the existing shrunk-toward-zero halo response
(`halo_strength_other`, `HalfNormal` prior, partially pooled). `dna_segment` is always a member,
whether or not the caller lists it explicitly - `_resolve_direct_dna_segments` enforces this.

A DNA-product segment (kit sales) is added to `direct_dna_segments` alongside `dna_segment`, not left
to fall into the shrunk "other segments" bucket:

```python
build_fh_hierarchical_model(frame, spec, direct_dna_segments=["DNA_CrossSell", "New Customer"])
```

`pages/04_Model_Config.py` computes this automatically from whatever DNA outcomes are mapped on
Structure (`core.outcomes.dna_kit_outcome_columns`) and stores it as `direct_dna_segments` in session
state; `pages/05_Model_Training.py` passes it straight through to whichever builder is fitting.
Every place that replays this halo logic outside PyMC - `core.predict`/`core.market_specific_predict`'s
`extract_posterior_params` (default-halo fallback), `steady_state_segment_response(_market_specific)`,
`generate_channel_curve`/`generate_market_channel_curve` - and `core.attribution`'s Shapley
decomposition (`_channel_log_terms`) all read `meta.direct_dna_segments` the same way, so a DNA
kit-sale segment is treated identically (full weight) everywhere its response is calculated or
attributed, not just in the fitted model itself.

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

## How double counting is avoided today

- Every segment - FH or DNA-product - has its own independent Negative-Binomial likelihood over its
  own outcome column. Nothing sums a DNA kit-sale count and an FH GSA count into one figure anywhere
  in the fitting or prediction code.
- `core.attribution.total_fh_contribution` gained a `segments` parameter specifically for this: pages
  that build a "total FH" view (Results & Curve Bank, Project Export) pass only the FH segments
  actually in the fit (`[s for s in meta.segments if s not in meta.direct_dna_segments or s ==
  meta.dna_segment]`, i.e. excluding DNA-product segments), so a kit-sale count is never summed into
  an "FH total" and reported as one meaningless combined unit. `segment_channel_summary`'s per-segment
  table is unaffected - a DNA segment's own contribution is shown in its own right, which is correct
  and desired.
- There is currently no cross-product **value** combination (e.g. "total business value across FH and
  DNA") - `OutcomeDefinition.value_weight` exists per outcome, but nothing sums FH value and DNA value
  together yet. That combination is future work (the instruction document's section 4.4, not part of
  this PR) and must apply the same "no shared effect counted in both" discipline documented here when
  it's built.

## Validation

Simulation-based recovery testing with a known direct DNA-media effect and a known (smaller) halo
effect was run offline (not a committed test - matches the precedent for Model C's original recovery
check, see docs/decision_log.md for why): a synthetic panel with `beta[DNA-channel]` deliberately set
much higher for a `direct_dna_segments` member than for an ordinary FH segment recovered that ordering
correctly - see the decision log entry for this PR for the exact result. The fast, non-MCMC parts
(the `direct_dna_segments` halo-shrinkage logic itself, at both the PyMC-graph-construction level via
`_resolve_direct_dna_segments` and the NumPy-replay level in `core.predict`/
`core.market_specific_predict`/`core.attribution`) are unit tested directly - see
`ancestry_mmm/tests/test_hierarchical_model.py`, `test_predict.py`, `test_market_specific_predict.py`,
`test_attribution.py`.
