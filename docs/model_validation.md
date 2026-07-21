# Model Validation

## Model comparison workflow

Three candidates, compared before any partially-pooled model is adopted as the default:

| | Model A | Model B | Model C |
|---|---|---|---|
| Description | One fully shared curve across markets | Independent per-market models | Partially pooled, market-specific curves |
| Status today | Built and available (`core.hierarchical_model`) | Built and available (`core.model_comparison.slice_frame_to_market` + Model A's builder, no new model code) | Built and available (`core.market_specific_model`) |

Comparison criteria - status per item:

- out-of-sample predictive performance - **available** (`in_sample_fit` / `in_sample_fit_market_specific`; the existing expanding-window backtest also branches on model type, `pages/06_Diagnostics.py`)
- posterior predictive checks - **available** (`posterior_predictive_coverage`, reused unchanged for both model types)
- convergence diagnostics - **available** (`compute_model_diagnostics`, reused unchanged)
- parameter recovery on simulated data - **available, offline only** (see below; not a committed CI test, by design - see `docs/decision_log.md`)
- curve plausibility - **available** (`curve_plausibility_checks` / `curve_plausibility_checks_market_specific`)
- calibration to experiments - **available for Model A only** (curve bank calibration logging is not yet extended to Model C)
- stability when markets or periods are removed - *not automated*; possible manually via the backtest and per-market slicing
- uncertainty by market - **available** (Model C's per-market `hill_K`/`beta` posterior std; surfaced in `curve_plausibility_checks_market_specific`'s relative-uncertainty flag)
- business interpretability - assessed by the reviewer at approval time (`pages/06_Diagnostics.py`), not automated

Model C is not accepted merely for being more complex than A or B - it has to show better or
comparable prediction, credible market differentiation, stable curves, sensible shrinkage, and
acceptable diagnostics, per the redesign brief. `pages/12_Compare_Models.py` (workflow step 8) is
where fitted candidates are saved and compared side by side (`core.model_comparison.ModelComparisonCandidate`,
`candidates_to_dataframe`) - one candidate at a time, since fitting three real models behind a single
button would be slow and blocking.

## Simulation framework

`core.simulation.simulate_market_specific_panel` (see `ancestry_mmm/tests/test_simulation.py` for
its full behavioural contract) generates a synthetic panel with known ground truth:

- 3 default markets of different sizes (`default_markets()`): a large market (UK), a medium one
  (Australia), and a small, short-history "weak-data" market (`NewMarket`, 26 weeks vs. 104).
- Market-specific saturation points drawn around a market-scaled global mean:
  `log_K[market, channel] ~ Normal(log(channel.K * market.k_multiplier), market_k_sigma)`.
- Market- and segment-specific response strength, similarly hierarchical.
- Shared `decay[channel]` and `S[channel]` across markets (matching Model C's "initial production
  version" design in `docs/modelling_methodology.md`).
- Multiple segments (New, Winback, DNA cross-sell by default), each with its own baseline level and
  response multiplier.
- Media cost inflation over time per channel (`annual_inflation`), driving `spend = media_units x
  cost_per_unit(t)`.
- Both spend and physical media-unit columns per channel.

`SimulationResult.ground_truth` (a `SimulationGroundTruth`) carries every parameter used to generate
the panel - `market_K`, `market_beta`, `channel_decay`, `channel_S`, and the per-market/channel
`cost_per_unit` series - so a recovery test can fit the real hierarchical model against
`SimulationResult.panel` and compare the posterior to `SimulationResult.ground_truth` directly.

**Offline recovery check (not a committed test - see `docs/decision_log.md` for why):** a
3-market, 2-channel, 52-week synthetic panel fit with a small draw budget (150 tune, 150 draws, 2
chains) recovered the correct market ranking for both `hill_K` and `beta` (matching the simulation's
`k_multiplier`/`beta_multiplier` scaling), with positive rank/scale correlation against ground truth
(K: 0.72, beta: 0.67). Absolute magnitudes were compressed toward the pooled mean, as expected from
partial pooling under a small draw budget - this confirms the hierarchy is structurally sound
(market differentiation is recoverable in direction, not collapsed to a single shared value), not
tight quantitative recovery, which needs a production draw count to assess properly.

## Validation checklist (from the redesign brief - status per item)

1. UK and Australia produce different channel curves where supported. - **Built** (`core.market_specific_model`); confirmed directionally on simulated data (see above)
2. A smaller market is shrunk toward the shared channel distribution. - **Built**; confirmed on simulated data (`NewMarket`'s recovered K/beta compressed toward the pooled mean)
3. A strong market can move away from the pooled mean. - **Built**; confirmed on simulated data (UK's higher K/beta ranking preserved)
4. Segment responses differ within each market. - **Built**, and market-specific too (`beta[market, segment, channel]`)
5. Overall response equals the defined segment aggregation. - **Built** (`docs/segment_methodology.md`); Model C's `generate_market_channel_curve` follows the same rule (`overall_response` = sum of segment responses)
6. Spend curves and media-unit curves are internally consistent. - **Built** (`core.media_units.response_unit_curve` derives the media-unit curve directly from the spend curve, so they can't diverge - a documented single-cost-per-unit simplification, see `docs/decision_log.md`)
7. CPA is calculated correctly at every curve point. - **Built**: `core.media_units.compute_cpa`, unit-tested against hand-computed expected values (`tests/test_media_units.py`)
8. Marginal CPA differs from average CPA where expected. - **Built**: both reported together on every curve; `test_media_units.py` confirms they diverge as spend increases toward saturation
9. Media inflation changes required spend but not response to physical delivery. - **Built**: `equivalent_delivery`/`equivalent_response` keep media units and response fixed while only the spend side changes with the assumed cost-per-unit
10. Same-response and same-delivery scenarios work. - **Built**: `equivalent_delivery`/`equivalent_response` calculators on Results & Curve Bank, plus the Scenario Planner's media-unit planning mode, both built on the same `core.media_units` conversions
11. The Scenario Planner always uses the selected market's curve. - **Built**: `core.optimization` dispatches on `model_type` to the correct market-aware response function; confirmed with `test_optimization.py::TestModelTypeDispatch` (same spend plan, different markets, different predicted outcomes for Model C)
12. Transferred estimates are clearly labelled. - **Built**: every Model C curve bank entry carries a `curve_status` (`Locally estimated`/`Partially pooled`/`Transferred estimate`) from `core.evidence_tiers`, filterable in the curve bank history table (`docs/market_hierarchy.md` section 4, `docs/curve_bank.md`)
13. Approval is invalidated after model-relevant changes. - **Built**: `fingerprint_model_spec`'s hash payload covers `model_type`, the transformation recipe (`pipeline_steps`), and the calculation-relevant subset of `market_spec_config` (channel-to-media-unit mappings, per-market currency), on top of the existing data/spec/posterior/run binding - see `docs/decision_log.md` for the descriptive/model-relevant boundary
14. Project documentation is generated correctly. - **Built**: `core.report.build_report_sections`/`render_markdown`/`render_html` produce a reproducible Markdown + HTML report (objective, data, model, diagnostics, curve bank, scenarios, limitations, decision log pointer) from the project's actual current state, available on Project Export & Handover at any point in the workflow
15. Existing tests still pass. - **Enforced**: `uv run pytest ancestry_mmm/tests/ -q`
16. Ruff passes. - **Enforced**: `uv run ruff check ancestry_mmm`
17. GitHub Actions passes. - **Enforced by `.github/workflows/tests.yml`**
