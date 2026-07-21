# Limitations

## Data requirements

- Partial pooling shares statistical strength across markets; it cannot manufacture variation that
  isn't in the data. A market with genuinely flat spend over its whole history won't yield an
  identifiable curve no matter how much pooling is applied - it will just inherit the shared
  pattern with wide uncertainty, which is the correct behaviour, not a workaround.
- Market descriptors (`core.market_config.MarketDescriptors`) are entirely optional and, as of this
  PR, purely informational. Leaving them blank does not degrade anything today, but a future phase
  that uses them to explain curve parameters will only be as good as what's actually filled in.

## Identification limitations

- `decay[channel]` and `S[channel]` staying shared across markets (Model C's "initial production
  version" - see `docs/decision_log.md`) means the model cannot yet distinguish "this market's
  media carries over longer" from "this market's saturation point is higher" - both currently only
  show up through the shared parameters or the market-specific `K`.
- `beta[market, segment, channel]` is built as an additive form (global + market deviation + segment
  deviation) with no free market x segment x channel interaction term - by design (`docs/decision_log.md`),
  not because an interaction was ruled out; it's a documented next step once diagnostics on real
  data motivate it.
- Simulation-based recovery testing (`core.simulation`) validates that the model *can* recover known
  ground truth under the assumed hierarchical structure - it cannot validate that this hierarchical
  structure is the correct one for real Ancestry data. Real-data model comparison
  (`docs/model_validation.md`) is still required before trusting the redesign in production. The
  offline recovery check run so far (`docs/decision_log.md`) used a small draw budget for speed and
  recovered correct market *ranking* with compressed magnitudes - a production draw count is needed
  to assess quantitative recovery, not just direction.

## Transferred-curve limitations

- A market with no usable local evidence should get a **transferred estimate**, not a locally
  estimated curve, once the evidence-tier classification is surfaced in the UI - **this labelling is
  not built yet** (`docs/market_hierarchy.md` section 4); a fitted Model C makes the classification
  possible in principle (via `market_K_sigma`/`market_beta_sigma` and per-market posterior
  uncertainty) but nothing in the UI currently maps a market onto one of the three evidence tiers.
  Treat any market-specific curve today as unlabelled with respect to evidence strength - review
  `curve_plausibility_checks_market_specific`'s relative-uncertainty flags manually instead.
- `market_data_quality_status` is a coarse, pre-model, observation-count-only heuristic, still the
  only thing shown on the Market Descriptors page's market cards. It is not the same thing as the
  evidence-tier classification above and must not be presented to users as if it were - see the
  explicit warning in `docs/market_hierarchy.md` section 4.

## Inflation assumptions

- Media cost inflation calculations (Phase 3) will only be as good as the historical cost-per-unit
  data available; a channel with sparse or noisy media-unit data will produce an unreliable
  cost-per-unit trend.
- The design principle that a future inflation assumption is never applied silently
  (`docs/media_units_and_inflation.md`) places the burden of choosing a reasonable assumption on the
  user - the tool surfaces the assumption in use, it does not validate that the assumption is
  correct.

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

## Scope boundaries (this PR specifically)

- This PR (Phase 2) adds a new, fully separate market-specific model, prediction, and diagnostics
  path (`core.market_specific_model`, `core.market_specific_predict`,
  `core.market_specific_diagnostics`, `core.model_comparison`) alongside Model A - it does not
  modify Model A's model-building, prediction, diagnostics, curve bank, or optimisation code at all.
  Everything described as "Phase 3/4" in these docs remains a design record, not shipped
  functionality.
- The model-specification fingerprint (`core.fingerprint.fingerprint_model_spec`) now includes
  `model_type` ("shared" vs. "market_specific"), so switching model structure invalidates an
  existing approval. It still does **not** include market hierarchy, media-unit mappings, or
  currency settings from `market_spec_config` - approval invalidation does not yet react to changes
  in that data, since nothing downstream consumes it yet beyond Model C's core structure. This
  remains tracked as Phase 3 work (wiring `market_spec_config` into the model/fingerprint together),
  not an oversight.
- Curve bank storage, Shapley attribution, and Scenario Planner are Model-A-only; a market-specific
  model gets a read-only curve viewer instead, with a clear "not available yet" message where the
  Model-A-only features would otherwise appear (`docs/decision_log.md`).
