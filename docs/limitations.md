# Limitations

## Data requirements

- Partial pooling shares statistical strength across markets; it cannot manufacture variation that
  isn't in the data. A market with genuinely flat spend over its whole history won't yield an
  identifiable curve no matter how much pooling is applied - it will just inherit the shared
  pattern with wide uncertainty, which is the correct behaviour, not a workaround.
- Market descriptors (`core.market_config.MarketDescriptors`) are entirely optional and currently
  purely informational - nothing in the fitting, prediction, curve, CPA or scenario code reads them
  (deliberately excluded from the model-specification fingerprint for the same reason - see
  `docs/decision_log.md`). Leaving them blank does not degrade anything today, but a future feature
  that uses them to explain curve parameters will only be as good as what's actually filled in.

## Funnel coherence (PR E.2)

- Family History sign-ups and GSAs are fitted as independent Negative-Binomial outcome equations, with
  nothing in the model enforcing `GSA <= sign-up` or estimating a sign-up-to-GSA conversion rate - the
  model can produce incoherent predictions (implied conversion outside `[0, 1]`, predicted GSAs
  exceeding predicted sign-ups) in some periods or scenarios, and no diagnostic warning is raised by
  the fitting process itself. `core.funnel.FunnelLink`/`funnel_coherence_diagnostics` (PR E.2) let an
  analyst declare a sign-up/GSA pair and surface these warnings after the fact (Diagnostics page) - this
  is detection, not prevention or correction. A constrained funnel model (`sign-ups model` +
  `conversion model conditional on sign-ups` + `GSA = sign-ups x conversion probability`) remains a
  documented future direction, deliberately not built until parallel-outcome diagnostics and
  identifiability work on real data motivates it (`docs/decision_log.md`).

## Identification limitations

- `decay[channel]` and `S[channel]` staying shared across markets (Model C's "initial production
  version" - see `docs/decision_log.md`) means the model cannot yet distinguish "this market's
  media carries over longer" from "this market's saturation point is higher" - both currently only
  show up through the shared parameters or the market-specific `K`.
- `beta[market, outcome, channel]` is built as an additive form (global + market deviation + outcome
  deviation) with no free market x outcome x channel interaction term - by design (`docs/decision_log.md`),
  not because an interaction was ruled out; it's a documented next step once diagnostics on real
  data motivate it.
- Simulation-based recovery testing (`core.simulation`) validates that the model *can* recover known
  ground truth under the assumed hierarchical structure - it cannot validate that this hierarchical
  structure is the correct one for real Ancestry data. Real-data model comparison
  (`docs/model_validation.md`) is still required before trusting the redesign in production. The
  offline recovery check run so far (`docs/decision_log.md`) used a small draw budget for speed and
  recovered correct market *ranking* with compressed magnitudes - a production draw count is needed
  to assess quantitative recovery, not just direction.
- The kit-sale-to-later-FH-conversion **pipeline effect** - a DNA kit purchase changing a customer's
  later likelihood of FH signup, distinct from DNA media's halo onto FH cross-sell - is deliberately
  **not modelled**: it would need person-level linkage this aggregate weekly-panel model doesn't have,
  and adding it without that risks double-counting against the existing halo pathway. Any real
  correlation is implicitly absorbed into the FH segments' own baseline/trend, not lost, but also not
  separately quantified - see `docs/dna_fh_causal_structure.md`.

## Transferred-curve limitations

- A market with no usable local evidence gets a **transferred estimate**, not a locally estimated
  curve - `core.evidence_tiers.classify_market_evidence` labels every Model C curve bank
  entry's `curve_status` accordingly (`docs/market_hierarchy.md` section 4, `docs/curve_bank.md`).
  The thresholds behind this classification (period counts, relative posterior uncertainty) are
  reasonable defaults, not validated against real Ancestry data yet - see the decision log entry
  recording them, and revisit once real-data model comparison results exist
  (`docs/model_validation.md`).
- `market_data_quality_status` is a coarse, pre-model, observation-count-only heuristic, still the
  only thing shown on the Market Descriptors page's market cards. It is not the same thing as the
  evidence-tier classification above and must not be presented to users as if it were - see the
  explicit warning in `docs/market_hierarchy.md` section 4.

## Inflation assumptions

- Media cost inflation calculations (`core.media_units.historical_cost_trend`) will only
  be as good as the historical cost-per-unit data available; a channel with sparse or noisy
  media-unit data will produce an unreliable cost-per-unit trend, and a single year of data gives no
  year-on-year inflation figure at all (returns `None`, not a guessed rate).
- `response_unit_curve` uses one constant average historical cost-per-unit across the whole curve's
  spend range, not a spend-level-varying relationship - see `docs/decision_log.md` and
  `docs/media_units_and_inflation.md` for why, and what a fuller treatment would need.
- The design principle that a future inflation assumption is never applied silently
  (`docs/media_units_and_inflation.md`) places the burden of choosing a reasonable assumption on the
  user - `equivalent_delivery`/`equivalent_response` always take the cost assumption as an explicit
  argument (a UI number input pre-filled with the historical average, editable) rather than baking
  one in; the tool surfaces the assumption in use, it does not validate that the assumption is
  correct.
- **Stale claim corrected (PR D audit):** this bullet previously said CPA's posterior uncertainty
  "is not assessed directly" and that per-draw curve generation "remains a documented future
  extension" - both wrong as of `core.uncertainty` (built for PR4, still current): a real credible
  interval on CPA does exist, via `generate_channel_curve_with_uncertainty`/
  `generate_market_channel_curve_with_uncertainty`, which re-run curve + `compute_cpa_by_product`
  once per sampled posterior draw and summarize the resulting distribution
  (`avg_cpa_mean`/`_median`/`_lower`/`_upper`, and `dna_avg_cpa_*` where applicable) - see the
  "Scope boundaries" section below, which already described this correctly; these two sections had
  drifted out of sync. `cpa_stability_flags` remains a separate, point-estimate-only proxy (flags
  curve regions too flat to trust a marginal number from) - it is not itself the credible interval,
  which is what the paragraph above conflated.

## Uncertainty in small markets

- By design, a small/weak-data market's posterior will be wide and will look similar to the shared
  distribution - this is the intended behaviour of partial pooling, not a bug, but it means small
  markets should not be over-interpreted as having a precisely known, differentiated curve.

## Correlated channels and measurement-definition changes

- Neither the current model nor the planned market-specific redesign explicitly models cross-channel
  correlation (e.g. TV and Search moving together) - highly correlated channels can produce
  unstable relative attribution between them, market-specific or not.
- Changing a channel's measurement definition (e.g. how impressions are counted) mid-history without
  flagging it will look like a change in that channel's effectiveness to the model, not a
  measurement artefact. There's no automated detection of this today.

## Scope boundaries

- Scenario planning (`core.optimization`, Scenario Planner) supports both Model A and Model C,
  including media-unit planning mode and CPA outputs. Shapley attribution is also available for
  both model types - Model C uses `core.market_specific_attribution`'s market-aware decomposition
  (each row's own market's `beta`/`hill_K`), not Model A's shared-curve implementation.
- Posterior uncertainty (`core.uncertainty`) for response curves and scenario outcomes is a
  subsample-and-summarize approximation: it re-runs the same point-estimate calculation once per
  sampled posterior draw (typically 20-200 draws out of several thousand, a speed/accuracy
  tradeoff) rather than using the entire posterior - see `docs/decision_log.md`.
- The Scenario Planner's optimiser always conserves total budget (`conserve_total_budget=True`). As a
  consequence, a true *marginal* CPA at the scenario level isn't meaningful (there's no net spend
  change to compute it against) - the planner reports a *product-aware average* CPA (current vs.
  optimised plan, Family History GSAs and DNA kits kept separate - never blended into one number)
  instead, which is well-defined even at fixed total spend; see `docs/decision_log.md`.
- Media-unit planning mode converts to/from spend using one average historical cost-per-unit per
  channel (same simplification as Results & Curve Bank's response-unit curve) - not a
  spend-level-varying relationship. `SpendConstraint` (locked cells, floors, bounded movement) still
  operates in spend terms only; there's no dedicated "locked media units" constraint type.
- CPA/inflation are not first-class optimiser objectives - "minimise CPA," "maintain response/
  delivery under inflation" from the original redesign brief aren't built; `objective` is explicit
  (`core.optimization.VALID_OBJECTIVES`: `"fh_gsa"`, `"fh_signups"`, `"dna_kits"`, `"weighted_mix"`,
  `"expected_value"` - no generic "maximise volume" that would mix FH GSAs, FH sign-ups and DNA kits),
  with `whole_plan_cost_per_fh_gsa`/`_fh_signup`/`_dna_kit` (PR E.2 - explicit spend-scope naming, see
  `docs/media_units_and_inflation.md`) reported as output metrics only. `"weighted_mix"`
  and per-outcome `target_outcome_ids` are implemented in `core.optimization` but not yet exposed as
  UI controls on the Scenario Planner page. Every objective validates its `target_outcome_id`s
  (existence, metric match, `include_in_optimisation` eligibility - PR E.2) before scoring anything;
  `"weighted_mix"` additionally rejects raw-unit mixes across different `unit`s unless the caller
  explicitly passes `assume_value_scaled_weights=True`.
- `evaluate_scenario`'s `value`/`total_value` are `None` (not raw predicted units) whenever no `ltv`
  mapping is supplied at all, carrying an explicit `value_status` (`"not configured"`/`"partial"`/
  `"complete"`) rather than ever presenting a raw volume count as if it were priced (PR E.2). Mixing
  `value_currency`s across priced outcomes raises rather than silently summing across currencies.
- The Scenario Planner refuses to plan (`st.stop()`) when the current outcome catalogue has
  calculation-relevant drift from the fitted model's catalogue, even with an approval whose fingerprint
  still matches the trace (PR E.2, `core.outcomes.has_blocking_drift`) - every other page shows drift
  informationally only.
- Media-unit curve bank entries (`input_type="media_unit"`) are only auto-saved for a
  market-specific fit - a shared curve's cost-per-unit context is inherently market-specific with no
  single market to attribute it to, so it's shown in the UI (for a chosen reference market) but not
  persisted for Model A (`docs/decision_log.md`).
- The model-specification fingerprint (`core.fingerprint.fingerprint_model_spec`) includes the
  transformation recipe (`pipeline_steps`) and the calculation-relevant subset of
  `market_spec_config` (channel-to-media-unit mappings, per-market currency) - approval invalidation
  reacts to changes there. It deliberately does **not** include market descriptors (population,
  awareness, etc.), since nothing downstream reads them; see `docs/decision_log.md` for the exact
  boundary.
- Evidence-tier thresholds (`core.evidence_tiers`) are reasonable defaults, not yet
  validated against real Ancestry data - see `docs/decision_log.md`.
