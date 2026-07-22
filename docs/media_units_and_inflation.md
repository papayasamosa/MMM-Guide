# Media Units and Inflation

Design record for spend-vs-delivery modelling and media cost inflation. Phase 1 built the data
capture (`core.market_config.ChannelMediaUnitConfig`, Channel & Media Units page); Phase 3b built the
calculations against it (`core.media_units`); Phase 3c wired those calculations into the Scenario
Planner (`docs/scenario_planner.md`).

## Why spend alone isn't enough

Spend is not always the only, or the most meaningful, exposure variable. A channel may require more
spend over time to buy the same delivery even when the underlying response *to delivery* hasn't
changed at all - that's media cost inflation, and it's a completely different thing from media
effectiveness. Conflating the two makes a channel look like it's "getting worse" when it's actually
just getting more expensive to buy the same reach.

## Data model (Phase 1 - built)

`ChannelMediaUnitConfig`, one per (market, channel):

```
market
channel
spend_column
response_unit_column   (optional - e.g. impressions, GRPs, TVRs, clicks, reach)
unit_type               (optional - free text, suggestions: Impressions, Clicks, GRPs, TVRs, Reach,
                          Frequency, Insertions, Spots, Circulation, Video views, Completed views)
currency
cost_basis              (optional - e.g. CPM, CPC, Cost per GRP, Cost per TVR)
date_frequency
```

A channel can be spend-only (no `response_unit_column`) - the mapping is optional per (market,
channel), not required to use the rest of the app.

## Calculations (Phase 3b - built, `core.media_units`)

### Spend curve vs. response-unit curve

Two related views per market/channel:

- **Spend curve:** spend -> incremental response, per segment and overall - the same
  `generate_channel_curve` (Model A) / `generate_market_channel_curve` (Model C) curve DataFrames
  the curve bank already uses, now with `compute_cpa`'s average/marginal CPA columns added.
  Posterior mean only - **credible intervals on curves (and therefore on CPA) remain a documented
  future extension**, not built in Phase 3b (`docs/decision_log.md`); `cpa_stability_flags` is a
  point-estimate proxy that flags where the curve is too flat to trust a marginal CPA number from,
  not a substitute for real posterior-uncertainty bands.
- **Response-unit curve:** `response_unit_curve` divides the spend axis by an average historical
  `cost_per_unit` (`extract_cost_per_unit_series` + `historical_cost_trend`, from the raw
  spend/response-unit columns `ChannelMediaUnitConfig` maps). **This is an explicit, documented
  simplification**: it assumes one constant cost-per-unit across the whole curve's spend range
  rather than an independently observed spend-to-delivery relationship at every spend level (which
  would need a *modelled* cost-per-unit-vs-spend relationship, not just its historical average) -
  see the decision log entry recording this trade-off and what a fuller treatment would need.

### CPA

```
Average CPA  = Spend / Incremental outcomes
Marginal CPA = Change in spend / Change in incremental outcomes
```

Both reported together (`core.media_units.compute_cpa`) - they diverge meaningfully near
saturation. Left blank (never computed) wherever response, or the change in response between
consecutive curve points, is zero or negative. `cpa_stability_flags` warns where the curve is flat
enough that marginal CPA would be highly sensitive to small changes in the fitted curve (see above
for what this proxy is and isn't).

### Media inflation

- **Historical cost relationship:** `core.media_units.extract_cost_per_unit_series` computes
  `cost_per_unit = spend / media_units` by date for one (market, channel);
  `historical_cost_trend` aggregates it to year-on-year inflation and an indexed cost trend
  (base = 100 at the first year with data).
- **Equivalent delivery:** `equivalent_delivery(target_media_units, expected_future_cost_per_unit)` -
  `required_spend = target_media_units x expected_future_cost_per_unit`. The cost assumption is
  always an explicit function argument, never inferred silently.
- **Equivalent response:** `equivalent_response(target_media_units, cost_per_unit, curve_df)` -
  converts the target to an equivalent spend level and interpolates the existing spend curve at
  that point, rather than re-deriving the Hill curve's math - works identically for a Model A or
  Model C curve.
- **Curve bank integration:** `core.curve_bank.make_media_unit_entries` mirrors a run's
  `input_type="spend"` curve bank entries into `input_type="media_unit"` entries (same `beta`/`K`/
  `S`/`decay_rate` - only the x-axis interpretation differs, applied at curve-generation time) for
  every (market, channel) with a media-unit mapping and a valid cost-per-unit history. Only built
  for market-specific (Model C) saves - a shared (Model A) curve has no single market to attribute
  its cost-per-unit context to, so its media-unit context is shown in the UI (a chosen reference
  market) but not persisted to the curve bank; see `docs/decision_log.md`.
- **Scenario planner integration (Phase 3c - built):** the spend plan editor can display/accept
  physical media units for any mapped channel (converted to/from spend via the same average
  historical cost-per-unit), and `core.optimization` now dispatches to the correct model type's
  steady-state response function so the planner works for a market-specific fit too, not just Model
  A. **Not built:** locked/min/max media-unit constraint types (still spend-only in
  `SpendConstraint`), and CPA/inflation as first-class optimiser objectives ("minimise CPA,"
  "maintain response/delivery under inflation") - `avg_cpa`/`dna_avg_cpa` are reported as output
  metrics on every scenario, not yet optimisation targets themselves. What *is* built: an explicit
  `objective` (`core.optimization.VALID_OBJECTIVES`) - `"fh_gsa"`, `"dna_kits"`, `"weighted_mix"`,
  `"expected_value"` - with no generic "maximise volume" that would silently combine FH GSAs and
  DNA kits. Marginal CPA at the scenario level was considered and deliberately not built: the
  planner always conserves total budget, so there's no net spend change to compute a marginal CPA
  against - the *product-aware average* CPA (FH GSAs and DNA kits kept separate) of the current vs.
  optimised allocation is the well-defined metric shown instead (`docs/decision_log.md`).

## Currency

`core.market_config.MarketCurrency` (Phase 1) stores local currency, an optional reporting currency,
and exchange-rate context per market. The model works in local-market spend/delivery; cross-market
priors must not compare raw nominal spend without a scale treatment (`docs/market_hierarchy.md`
section 6). Converting to a common reporting currency for display remains a later-phase UI concern,
not a modelling one - the fitted curve stays in local units; `core.curve_bank.CurveBankEntry.currency`
already carries the local currency per curve, but no reporting-currency conversion is built.
