# Data Requirements

## Panel structure

One row per `date x market`, with segment outcomes as separate columns (wide format) - this is
what `core.schema.ModelSpec` and the transform pipeline assume today, and what
`core.simulation.simulate_market_specific_panel` generates for testing. An equivalent long format,
if ever needed, would have to be implemented consistently across the whole pipeline rather than
mixed with the wide format.

## Minimum fields

```
date
market
New outcome column
DNA cross-sell outcome column
Winback outcome column
channel spend columns
channel response-unit columns   (optional per channel, Phase 1 onward - see docs/media_units_and_inflation.md)
promotions                       (optional, per segment)
controls                         (optional, global or segment-specific)
```

## Optional market descriptors (Phase 1 onward)

```
population, addressable audience, subscriber base, brand penetration, aided/unaided awareness,
market maturity, category penetration, historical acquisition volume, media cost index,
average product price, competitive intensity, language group, region,
product availability, channel availability
```

Stored via `core.market_config.MarketDescriptors` - see `docs/market_hierarchy.md` section 5 for
what each is for and when it's actually used vs. just displayed.

## Validation

The existing pipeline validates structural completeness (`data.validate_modeling_frame`) and schema
consistency (`ModelSpec.validate`). The market-specific redesign adds market-level data-quality
checks that every market should pass before being planned against with confidence:

- sufficient time coverage
- acceptable missingness
- spend variation
- outcome variation
- comparable frequency across markets
- correctly mapped currency
- correctly mapped delivery metrics (where a media-unit mapping exists)

**Phase 1 status:** `core.market_config.market_data_quality_status` implements a coarse,
observation-count-only version of the first check (sufficient time coverage) as a placeholder shown
on the Market Context page's market cards. The rest of this checklist is not yet automated -
Phase 2 territory, once there's a fitted model to validate diagnostics against.

## Where this data comes from in the app today

1. **Data Sources** - raw sources (Outcomes / Activity and Media / Context and External Factors),
   or the synthetic demo.
2. **Prepare Data** - join + ordered, replayable transforms.
3. **Coverage & Gaps** (optional for exploratory work) - per-variable missingness/coverage review
   and treatment, required before official preparation.
4. **Activity Mapping** - governed activity identity, causal role, source mapping and reporting
   channel per model input, including per-market response-unit/unit-type/currency/cost-basis
   mapping where available.
5. **Model Structure** - markets, segment outcome mapping, governed activities, promo columns,
   controls, LTV.
6. **Market Context** (optional) - per-market currency and descriptor capture.

Activity Mapping's media-unit fields and Market Context are additive: nothing before or after them
in the pipeline changes behaviour based on whether they're filled in.
