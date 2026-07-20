# Model Validation

## Model comparison workflow (Phase 2 deliverable)

Three candidates, compared before any partially-pooled model is adopted as the default:

| | Model A | Model B | Model C |
|---|---|---|---|
| Description | One fully shared curve across markets | Independent per-market models | Partially pooled, market-specific curves |
| Status today | **This is what's currently fitted** (`core.hierarchical_model`) | Not implemented | Not implemented - the redesign's target |

Comparison criteria (all Phase 2, none automated yet):

- out-of-sample predictive performance
- posterior predictive checks
- convergence diagnostics
- parameter recovery on simulated data (see below - this is what the simulation framework is for)
- curve plausibility
- calibration to experiments
- stability when markets or periods are removed
- uncertainty by market
- business interpretability

Model C is not accepted merely for being more complex than A or B - it has to show better or
comparable prediction, credible market differentiation, stable curves, sensible shrinkage, and
acceptable diagnostics, per the redesign brief.

## Simulation framework (Phase 1 - built)

`core.simulation.simulate_market_specific_panel` (see `ancestry_mmm/tests/test_simulation.py` for
its full behavioural contract) generates a synthetic panel with known ground truth:

- 3 default markets of different sizes (`default_markets()`): a large market (UK), a medium one
  (Australia), and a small, short-history "weak-data" market (`NewMarket`, 26 weeks vs. 104).
- Market-specific saturation points drawn around a market-scaled global mean:
  `log_K[market, channel] ~ Normal(log(channel.K * market.k_multiplier), market_k_sigma)`.
- Market- and segment-specific response strength, similarly hierarchical.
- Shared `decay[channel]` and `S[channel]` across markets (matching the Phase 2 "initial production
  version" design in `docs/modelling_methodology.md`).
- Multiple segments (New, Winback, DNA cross-sell by default), each with its own baseline level and
  response multiplier.
- Media cost inflation over time per channel (`annual_inflation`), driving `spend = media_units x
  cost_per_unit(t)`.
- Both spend and physical media-unit columns per channel.

`SimulationResult.ground_truth` (a `SimulationGroundTruth`) carries every parameter used to generate
the panel - `market_K`, `market_beta`, `channel_decay`, `channel_S`, and the per-market/channel
`cost_per_unit` series - so a Phase 2 recovery test can fit the real hierarchical model against
`SimulationResult.panel` and compare the posterior to `SimulationResult.ground_truth` directly.

**What Phase 1 does not do:** actually fit anything against this simulated data. The framework only
generates the fixture; recovery testing needs the Phase 2 model to exist first.

## Validation checklist (from the redesign brief - status per item)

1. UK and Australia produce different channel curves where supported. - *Phase 2*
2. A smaller market is shrunk toward the shared channel distribution. - *Phase 2* (simulation fixture ready)
3. A strong market can move away from the pooled mean. - *Phase 2* (simulation fixture ready)
4. Segment responses differ within each market. - **Already true today**, market dimension pending
5. Overall response equals the defined segment aggregation. - **Already true today** (`docs/segment_methodology.md`)
6. Spend curves and media-unit curves are internally consistent. - *Phase 3*
7. CPA is calculated correctly at every curve point. - *Phase 3*
8. Marginal CPA differs from average CPA where expected. - *Phase 3*
9. Media inflation changes required spend but not response to physical delivery. - *Phase 3*
10. Same-response and same-delivery scenarios work. - *Phase 3*
11. The Scenario Planner always uses the selected market's curve. - *Phase 3* (planner already requires a market selection today, but the curve itself isn't market-specific yet)
12. Transferred estimates are clearly labelled. - *Phase 2* (curve status labels, `docs/curve_bank.md`)
13. Approval is invalidated after model-relevant changes. - **Already true today** for data/spec/posterior/run; extending the fingerprint to cover market hierarchy/media-unit/inflation config is Phase 2 (`docs/decision_log.md`)
14. Project documentation is generated correctly. - *Phase 4* (`docs/` exists from Phase 1; the reproducible report generator is Phase 4)
15. Existing tests still pass. - **Enforced this PR**: `uv run pytest ancestry_mmm/tests/ -q`
16. Ruff passes. - **Enforced this PR**: `uv run ruff check ancestry_mmm`
17. GitHub Actions passes. - **Enforced by `.github/workflows/tests.yml`**, added in a prior PR
