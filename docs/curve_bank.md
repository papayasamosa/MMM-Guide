# Curve Bank

## Today (Phase 3a - built)

Each curve bank entry (`core.curve_bank.CurveBankEntry`) is one *curve* - a
(market, channel, segment-or-overall) combination - not one model run:

```
model_run_id, market, channel, segment_or_overall, curve_status, input_type, currency, unit_type
```

Per-record model metadata: `decay_rate`, `hill_K`, `hill_S`, `beta`, `halo_strength` (DNA channels
only), approval metadata (approver, timestamp, notes, limitations, diagnostics reviewed), data
fingerprint, model specification fingerprint, posterior fingerprint (`core.fingerprint` - a run's
fingerprints are the same across every entry it produced). Entries are rejected at creation time
(`core.approval.require_matching_approval`) if the approval doesn't match the exact model being
saved - not just "an approval exists somewhere." `make_entries` (plural - one call produces every
curve a run's worth) requires a matching `ModelApproval` and, for a market-specific fit, an
`evidence_tiers` mapping (`core.evidence_tiers.classify_all_markets`).

`curve_status` is one of:

- `Shared` - a Model A curve. **Not one of the three tiers below** - a shared curve has no
  market-specific evidence to report, so labelling it `Locally estimated`/`Partially pooled`/
  `Transferred estimate` (all inherently about *market* evidence strength) would be actively
  misleading. This is a deliberate addition beyond the originally planned enum - see
  `docs/decision_log.md`.
- `Locally estimated` / `Partially pooled` / `Transferred estimate` - a Model C curve's evidence
  tier for that specific market and channel (`docs/market_hierarchy.md` section 4), computed from
  the fitted posterior's own uncertainty plus how many periods that market has, not asserted by the
  user.
- `Legacy` - expanded from a pre-Phase-3a, one-JSON-per-run file at load time (see below); always
  `market=None` since the old format predates market-specific curves entirely.

An "Overall" row per (market, channel) sums that channel's `beta` across every segment - valid
because response is linear in `beta` (`beta x saturation`), so summing betas before multiplying by
the shared saturation curve equals summing per-segment responses.

Every model run's approval is still verified once per save (not per curve) and applies identically
to every entry that save produces. Legacy entries (pre-dating fingerprint-bound approval) still
import and display fine, marked `legacy_approval = True`; entries from before this per-curve
redesign import and display fine too, marked `legacy_format = True`.

The curve bank history table on Results & Curve Bank filters by market, channel, segment, and curve
status - the rest of the planned filter set (model run, currency, unit type) is available as
columns today; dedicated filter widgets for them are a small follow-up, not a structural gap.

## Media-unit entries (Phase 3b - built)

`input_type` is `"spend"` (every entry) or `"media_unit"` (Phase 3b,
`core.curve_bank.make_media_unit_entries`) - a mirrored entry for a (market, channel) that has a
media-unit mapping (`core.market_config.ChannelMediaUnitConfig`) and a computable historical
cost-per-unit (`core.media_units.historical_cost_trend`). A media-unit entry carries the same
`beta`/`hill_K`/`hill_S`/`decay_rate` as its spend counterpart (the curve parameters themselves
don't change - see `docs/media_units_and_inflation.md` for why the media-unit axis is a derived
rescaling, not an independently fitted curve) plus `unit_type`, `currency`, and `cost_per_unit`
(the average historical cost-per-unit the media-unit axis was derived from).

**Only built for market-specific (Model C) saves.** A shared (Model A) curve has no single market to
attribute a cost-per-unit relationship to - cost-per-unit is inherently a market-level fact even
though the curve itself is shared - so Results & Curve Bank still shows a Model A curve's
media-unit context for a chosen reference market, but doesn't persist it to the curve bank
(`docs/decision_log.md`).

The curve bank history table on Results & Curve Bank filters by market, channel, segment, and curve
status - `input_type`, `currency`, `unit_type`, and `cost_per_unit` are all available as columns
today; dedicated filter widgets for `input_type` are a small follow-up, not a structural gap.

## What's built toward this so far

Phase 1 added `core.market_config` and the Channel & Media Units / Market Descriptors pages to
capture the market/currency/media-unit context this redesign attaches to each curve record. Phase 2
added the market-specific model itself (`core.market_specific_model`, "Model C"). Phase 3a redesigned
the curve bank to per-curve records and added evidence-tier classification (`core.evidence_tiers`).
Phase 3b (this work) added CPA, response-unit curves, and media-unit curve bank entries
(`core.media_units`, `core.curve_bank.make_media_unit_entries`). Shapley attribution and the
Scenario Planner remain Model-A-only (Phase 3c).
