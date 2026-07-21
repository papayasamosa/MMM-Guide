# Market Hierarchy

The design record for how markets relate to each other in the target (Phase 2+) model. This is a
durable design document, not a description of what's fitted today - see `docs/modelling_methodology.md`
for the current-vs-target split, and `docs/decision_log.md` for why this is being built at all.

## 1. Why not one shared curve

The current model shares `decay`, `K`, and `S` across every market. That's a reasonable Phase-1
simplification but not a defensible end state: countries differ in population, addressable
audience, brand penetration, channel maturity, and spend levels aren't comparable across countries
- saturation can occur at very different spend levels in different markets. Forcing one curve
across all of that hides real differences a planner needs to see.

## 2. Why not independent per-market models either

The opposite failure mode - fitting every market completely independently - throws away
information. A market with three months of TV data shouldn't get an equally-confident, completely
unconstrained curve as a market with three years of it; it should look like the shared pattern,
with wide uncertainty, until its own data says otherwise.

## 3. Partial pooling: the actual answer

```
market_saturation[market, channel]
    ~ Normal(global_saturation[channel], market_sigma[channel])
```

- Larger markets can move away from the shared mean when the data supports it.
- Smaller markets stay closer to the shared distribution.
- Uncertainty is wider in weak markets - shrinkage is a *consequence* of the model, not a rule
  applied after the fact.
- No market is forced to be identical to another, but none is estimated in total isolation either.

**Built in Phase 2** as `core.market_specific_model.build_fh_market_specific_model` ("Model C") -
see `docs/modelling_methodology.md` for the exact parameterisation. `beta[market, segment, channel]`
follows the same partial-pooling idea, additively (`mu_channel + market_dev + segment_dev`, no free
interaction term).

## 4. Market evidence tiers

Every market, once a market-specific model exists, falls into one of three evidence tiers. A fitted
Model C (Phase 2) makes this classification possible in principle - `market_K_sigma`/
`market_beta_sigma` and each market's posterior uncertainty are the raw ingredients - but the tiers
below are not yet surfaced as a labelled UI classification; that's still planned (alongside curve
bank/CPA integration, Phase 3). **Until then, the Market Descriptors page's market cards still show
only the coarse, pre-model observation-count heuristic**
(`core.market_config.market_data_quality_status`), which is explicitly not the same thing as the
tiers below, and must never be presented as a curve-status label.

| Tier | Description | Behaviour |
|---|---|---|
| Strong local market | Enough periods, spend variation, identifiable channel movement, acceptable diagnostics. | Primarily driven by local evidence. |
| Smaller market with some local evidence | Some data, but not enough to stand alone. | `local evidence + partially pooled cross-market evidence`; more shrinkage, wider intervals. |
| No usable local evidence | Not enough data for a genuinely local curve. | A **transferred estimate** based on the global distribution, comparable markets, penetration, maturity, audience size, and channel costs - always labelled `Transferred estimate`, never presented as a locally estimated curve. |

`docs/curve_bank.md` describes how these tiers map onto curve bank entry status.

## 5. Market descriptors (Phase 1: stored; Phase 2+: used to explain curve parameters)

`core.market_config.MarketDescriptors` (Phase 1) captures, per market, all optional:

population, addressable audience, subscriber base, brand penetration, aided/unaided awareness,
market maturity, category penetration, historical acquisition volume, media cost index, average
product price, competitive intensity, language group, region, product availability, channel
availability.

In Phase 1 these are stored and displayed only (Market Descriptors page). A later phase may let them
explain market-level curve parameters, e.g.:

```
market saturation point
    = global channel saturation
    + penetration effect
    + maturity effect
    + audience-size effect
    + residual market deviation
```

This is deliberately not built until the simpler hierarchy (section 3) is validated - adding
predictors to an unvalidated hierarchy makes both harder to debug.

## 6. Currency and spend normalisation

Cross-market hierarchical priors must not compare raw nominal spend levels directly - a market's
spend in local currency, scaled by population or channel cost differences, is not on the same axis
as another market's. `core.market_config.MarketCurrency` (Phase 1) stores local currency, optional
reporting currency, and exchange-rate context per market. The actual scaling/normalisation choice
(spend relative to market mean, spend per addressable customer, standardised within-market spend,
...) is a Phase 2 modelling decision, to be recorded here once made - the saturation curve output
must still convert back into meaningful local units for reporting regardless of which normalisation
is used internally.
