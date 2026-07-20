# Media Units and Inflation

Design record for spend-vs-delivery modelling and media cost inflation. **Phase 1 status: data
capture only** (`core.market_config.ChannelMediaUnitConfig`, Channel & Media Units page). None of
the calculations below are implemented yet - that's Phase 3.

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

## Planned calculations (Phase 3)

### Spend curve vs. response-unit curve

Two related views per market/channel, not just a relabelled x-axis:

- **Spend curve:** spend -> incremental response, with posterior mean, credible interval, current
  spend, recommended spend, saturation point, marginal and average response, CPA and marginal CPA
  at each spend level.
- **Response-unit curve:** physical delivery (impressions/GRPs/TVRs/clicks) -> incremental response,
  using the actual observed or modelled spend-to-delivery relationship - not a relabelling of the
  spend axis. Requires `cost_per_unit = spend / media_units`, tracked by date/market/channel.

### CPA

```
Average CPA  = Spend / Incremental outcomes
Marginal CPA = Change in spend / Change in incremental outcomes
```

Both reported together (they diverge meaningfully near saturation); CPA is never computed where
incremental response is zero or negative, and a clear warning is shown where posterior uncertainty
makes CPA unstable.

### Media inflation

- **Historical cost relationship:** `cost_per_unit = spend / media_units`, tracked by date, market,
  channel - year-on-year inflation, indexed cost trend, nominal vs. inflation-adjusted spend.
- **Equivalent delivery:** "how much would I need to spend next year to buy the same GRPs/
  impressions?" - `required_spend = target_media_units x expected_future_cost_per_unit`.
- **Equivalent response:** "how many GRPs/impressions are required to produce the same modelled
  response?" - solve on the response-unit curve, then convert to spend via the cost-per-unit
  relationship.
- **Scenario planner integration:** plan in spend or physical units; convert between them using
  observed historical cost relationships, user-entered assumptions, or scenario-specific overrides.
  The interface must always show which cost assumption is in use - a future inflation assumption is
  never applied silently.

## Currency

`core.market_config.MarketCurrency` (Phase 1) stores local currency, an optional reporting currency,
and exchange-rate context per market. The model works in local-market spend/delivery; cross-market
priors must not compare raw nominal spend without a scale treatment (`docs/market_hierarchy.md`
section 6). Converting to a common reporting currency for display is a Phase 3 UI concern, not a
modelling one - the fitted curve stays in local units.
