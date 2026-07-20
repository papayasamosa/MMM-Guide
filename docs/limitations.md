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

- `decay[channel]` and `S[channel]` staying shared across markets (Phase 2's "initial production
  version" - see `docs/decision_log.md`) means the model cannot yet distinguish "this market's
  media carries over longer" from "this market's saturation point is higher" - both currently only
  show up through the shared parameters or the market-specific `K`.
- Simulation-based recovery testing (`core.simulation`) validates that the model *can* recover known
  ground truth under the assumed hierarchical structure - it cannot validate that this hierarchical
  structure is the correct one for real Ancestry data. Real-data model comparison
  (`docs/model_validation.md`) is still required before trusting the redesign in production.

## Transferred-curve limitations

- A market with no usable local evidence gets a **transferred estimate**, not a locally estimated
  curve - explicitly labelled as such once Phase 2 exists (`docs/market_hierarchy.md` section 4).
  Transferred estimates are directional; they should not be used for precise budget-level decisions
  the way a locally-or-strongly-pooled curve can be.
- Phase 1's `market_data_quality_status` is a coarse, pre-model, observation-count-only heuristic.
  It is not the same thing as the Phase 2 curve-status classification and must not be presented to
  users as if it were - see the explicit warning in `docs/market_hierarchy.md` section 4.

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

- This PR (Phase 1) changes no modelling, transformation, schema, fingerprinting, approval,
  persistence-of-existing-fields, or scenario-optimisation behaviour. Everything described as
  "planned" or "Phase 2/3/4" in these docs is a design record, not shipped functionality.
- The model-specification fingerprint (`core.fingerprint.fingerprint_model_spec`) does **not** yet
  include market hierarchy, media-unit mappings, or currency settings - approval invalidation does
  not currently react to changes in the new `market_spec_config` data, since nothing downstream
  consumes it yet. This is intentional for Phase 1 and is tracked as Phase 2 work (extending the
  fingerprint alongside wiring the data into the model), not an oversight.
