# Glossary

The in-app glossary (`ancestry_mmm.utils.display.GLOSSARY`, shown via the "Glossary" expander on
several pages) covers the core modelling/planning terms. This is the same set, plus the
market-specific-redesign terms that aren't in the app yet because the functionality they describe
isn't built yet.

## Core terms (also in-app)

- **Adstock** - how the effect of media spend carries over and decays in the weeks after it occurs.
- **Saturation** - how each extra unit of spend produces a smaller incremental effect as spend
  increases.
- **Partial pooling** - segments or markets share information with each other, borrowing strength
  where data is thin, without being forced to be identical.
- **Posterior** - the updated distribution of a parameter's plausible values after the model has
  seen the data.
- **Prior** - the model's starting assumption about a parameter's plausible values before seeing the
  data.
- **Response curve** - the relationship between spend (or physical delivery) on a channel and its
  modelled effect.
- **Contribution** - the modelled portion of an outcome attributed to a specific channel or driver.
- **Incremental outcome** - the extra outcome caused by spend, over and above what would have
  happened anyway.
- **Scenario** - a specific spend plan and its predicted outcomes, saved for comparison.
- **Constraint** - a rule the optimiser must respect when proposing a spend plan, e.g. a locked cell
  or spend floor.
- **Approval** - a reviewer's sign-off on a specific fitted model, required before it can be used
  for planning; invalidated automatically the moment the data, specification, or posterior it was
  approved against changes.
- **Curve Bank** - a versioned store of an approved model's response curves and segment parameters.

## Market-specific redesign terms

- **Market-specific curve** - a response curve (`K`, `S`, `decay`, `beta`) estimated separately for
  one market, rather than shared across all markets.
- **Hierarchical prior (market level)** - the mechanism by which a market-specific parameter is
  drawn around a shared global mean rather than fitted in total isolation, e.g.
  `log_K[market, channel] ~ Normal(global_log_K[channel], market_K_sigma[channel])`.
- **Shrinkage** - the degree to which a market's estimate is pulled toward the shared distribution;
  larger in weak-data markets, smaller in strong-data markets.
- **Locally estimated (curve status)** - a market has enough of its own data for a curve to be
  primarily driven by local evidence.
- **Transferred estimate (curve status)** - a market has no usable local evidence; its curve is
  based on the global distribution and comparable markets, and must always be labelled as such.
- **Market descriptor** - optional context about a market (population, penetration, maturity,
  awareness, ...) that may explain why its curve parameters differ from another market's.
- **Media unit** - a physical measure of delivery (impressions, GRPs, TVRs, clicks, reach, ...) as
  opposed to spend.
- **Cost per unit** - `spend / media_units`, tracked over time to separate media cost inflation from
  media effectiveness.
- **Media inflation** - the tendency for the same physical delivery to cost more spend over time,
  independent of whether the audience's response to that delivery has changed.
- **Average CPA** - `spend / incremental outcomes` at a given spend level.
- **Marginal CPA** - `change in spend / change in incremental outcomes` between two spend levels;
  diverges from average CPA near saturation.
- **Equivalent delivery** - the spend required next period to buy the same physical delivery
  (media units) as today, given expected future cost per unit.
- **Equivalent response** - the physical delivery required to produce the same modelled response as
  today, converted to spend via the cost-per-unit relationship.
- **Model comparison (A/B/C)** - the three candidate model structures compared before adopting a
  partially-pooled market-specific model: A (one shared curve), B (independent per-market models),
  C (partially pooled, market-specific).
- **Ground truth (simulation)** - the known, generator-side parameter values (`K`, `beta`, `decay`,
  `S`, cost-per-unit) used to produce a synthetic dataset, against which a fitted model's posterior
  can be checked for recovery.
