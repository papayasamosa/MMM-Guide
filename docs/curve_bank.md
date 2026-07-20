# Curve Bank

## Today

Each curve bank entry (`core.curve_bank.CurveBankEntry`) stores one model run's shared curves and
segment parameters: model run ID, data/spec/posterior fingerprints, approver, approval timestamp,
diagnostics reviewed, notes, known limitations, plus the fitted `beta`, `K`, `S`, decay, halo
strength, etc. Entries are rejected at creation time (`core.approval.require_matching_approval`) if
the approval doesn't match the exact model being saved - not just "an approval exists somewhere."
Legacy entries (pre-dating fingerprint-bound approval) import and display fine but are visibly
marked `legacy_approval = True`.

Because today's model shares curves across markets, there is currently **one set of curves per run**,
not one per market.

## Planned redesign (Phase 2-3)

One curve bank record per relevant curve, not per run:

```
model_run_id, market, channel, segment_or_overall, curve_type, input_type, currency, unit_type
```

Model metadata per record: `beta`, `K`, `S`, `decay`, posterior uncertainty, approval metadata, data
fingerprint, model specification fingerprint, posterior fingerprint (fingerprinting already exists
for the whole model - see `docs/decision_log.md`; extending it to cover per-record market/curve
identity is part of this work).

Evidence metadata per record: local data strength, pooling strength, number of periods, spend
variation, delivery variation, and a **curve status**, one of:

- `Locally estimated`
- `Partially pooled`
- `Transferred estimate`
- `Legacy`
- `Unapproved`

These map directly onto the market evidence tiers in `docs/market_hierarchy.md` section 4 - a
market-specific curve is never displayed as `Locally estimated` unless the model that produced it
actually estimated it locally with sufficient data, and `Transferred estimate` must never be
presented as if it were locally estimated.

Planned UI: filter by market, channel, segment, curve status, model run, currency, unit type.

## What Phase 1 adds toward this

Nothing to the curve bank itself yet - `core.market_config` and the two new pages exist to capture
the market/currency/media-unit context this redesign will attach to each curve record once Phase 2's
market-specific model produces curves to attach it to. The curve bank's actual storage format
doesn't change until then.
