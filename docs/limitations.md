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

- A market with no usable local evidence gets a **transferred estimate**, not a locally estimated
  curve - `core.evidence_tiers.classify_market_evidence` (Phase 3a) labels every Model C curve bank
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

- Media cost inflation calculations (`core.media_units.historical_cost_trend`, Phase 3b) will only
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
- CPA's posterior uncertainty is not assessed directly (curves are point estimates only, as they've
  been since Phase 2) - `cpa_stability_flags` is a point-estimate proxy (flags curve regions that are
  too flat to trust a marginal number from), not a credible interval on CPA itself. A real
  uncertainty band on CPA needs per-draw curve generation, which remains a documented future
  extension.

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

- This PR (Phase 3c) extends scenario planning (`core.optimization`, Scenario Planner) to Model C and
  wires in media-unit planning mode and CPA outputs - it does not touch Model A's or Model C's
  model-building, prediction, diagnostics, model comparison, or curve bank code. **Shapley
  attribution remains Model-A-only** (it would misread Model C's market-indexed parameters) - this is
  the one piece of the original Phase 2 restriction still in place; everything else that was blocked
  for market-specific models (curve bank saving in Phase 3a, Scenario Planning in this phase) is now
  built.
- The Scenario Planner's optimiser always conserves total budget (`conserve_total_budget=True`) -
  this predates Phase 3c and wasn't changed by it. As a consequence, a true *marginal* CPA at the
  scenario level isn't meaningful (there's no net spend change to compute it against) - the planner
  reports a *blended average* CPA (current vs. optimised plan) instead, which is well-defined even at
  fixed total spend; see `docs/decision_log.md`.
- Media-unit planning mode converts to/from spend using one average historical cost-per-unit per
  channel (same simplification as Results & Curve Bank's response-unit curve, Phase 3b) - not a
  spend-level-varying relationship. `SpendConstraint` (locked cells, floors, bounded movement) still
  operates in spend terms only; there's no dedicated "locked media units" constraint type.
- CPA/inflation are not first-class optimiser objectives - "minimise CPA," "maintain response/
  delivery under inflation" from the original redesign brief aren't built; `objective` remains
  `"value"` or `"volume"`, with `avg_cpa` reported as an output metric only.
- Media-unit curve bank entries (`input_type="media_unit"`, Phase 3a/3b) are only auto-saved for a
  market-specific fit - a shared curve's cost-per-unit context is inherently market-specific with no
  single market to attribute it to, so it's shown in the UI (for a chosen reference market) but not
  persisted for Model A (`docs/decision_log.md`).
- The model-specification fingerprint (`core.fingerprint.fingerprint_model_spec`) still does **not**
  include market hierarchy, media-unit mappings, or currency settings from `market_spec_config` -
  approval invalidation does not yet react to changes in that data. This remains tracked as future
  work (wiring `market_spec_config` into the model/fingerprint together), not an oversight.
- CPA has no credible interval - point estimates only, same as the curves it's computed from; see the
  "Inflation assumptions" section above.
- Evidence-tier thresholds (`core.evidence_tiers`, Phase 3a) are reasonable defaults, not yet
  validated against real Ancestry data - see `docs/decision_log.md`.
