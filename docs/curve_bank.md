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

## Planned redesign (Phase 3b)

`input_type`/`unit_type`/`currency` exist on every entry today but are only populated for spend
curves (`input_type="spend"`, `unit_type=None`) - `docs/media_units_and_inflation.md`'s
response-unit curves, CPA and marginal CPA at each curve point, and cost-per-unit tracking are
Phase 3b work that will populate the remaining fields and add `curve_type` variants beyond the
plain response curve.

## What's built toward this so far

Phase 1 added `core.market_config` and the Channel & Media Units / Market Descriptors pages to
capture the market/currency/media-unit context this redesign attaches to each curve record. Phase 2
added the market-specific model itself (`core.market_specific_model`, "Model C"). Phase 3a (this
work) redesigned the curve bank to per-curve records, added evidence-tier classification
(`core.evidence_tiers`), and wired both Model A and Model C into curve bank saving - Shapley
attribution remains Model-A-only (it would misread Model C's market-indexed parameters), but curve
bank storage no longer requires it.
