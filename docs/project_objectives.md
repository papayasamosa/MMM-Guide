# Project Objectives

## Why this application exists

Ancestry's in-house MMM and scenario-planning tool (see `docs/ancestry_fh_mmm.md` for the full
original requirements brief) started as a joint hierarchical model across three Family History
acquisition paths - **New**, **DNA cross-sell**, **Winback** - sharing one response curve per
channel across every market. That was sufficient to stand the tool up end-to-end, but it doesn't
answer a question the business actually has: *does TV work the same way in the UK as it does in
Australia?* A single shared curve can't say.

This redesign (tracked from this PR onward - see `docs/decision_log.md`) exists to answer that
question without throwing away what already works: the three-segment structure, the DNA halo
pathway, the curve bank, and constrained scenario planning all stay. What changes is that channel
response curves become **market-specific**, estimated with partial pooling so smaller markets
borrow strength from larger ones instead of either being forced to match them exactly or fitted
alone with no support.

## Who it is for

- **Ancestry's in-house data scientist/analyst** - the primary, ongoing operator. Must be able to
  run, refresh, and extend the tool without vendor dependency (per `docs/ancestry_fh_mmm.md`
  section 1).
- **Marketing/media planners** - consumers of the Scenario Planner and curve outputs, generally
  through the analyst rather than the raw model.
- **Whoever reviews and approves a fitted model** before its curves reach planning - the model
  approval workflow exists specifically so this is a named, accountable step, not implicit trust in
  a dashboard number.

## What business decisions this supports

- Channel budget allocation **within** a market (e.g. "should UK TV spend go up or down next
  quarter").
- Channel budget allocation **across** markets, once market-specific curves exist - today the tool
  can only say "here's the shared curve," not "here's what changes if we move budget from Australia
  to the UK."
- Whether a smaller or newer market's curve is trustworthy enough to plan against, or should be
  treated as directional only (`docs/market_hierarchy.md` section 4).
- CPA and marginal CPA at different spend levels, in both spend and physical media-unit terms
  (`docs/media_units_and_inflation.md`) - once Phase 3 lands.
- Whether apparent spend growth is buying more delivery, or just paying more for the same delivery
  (media cost inflation, `docs/media_units_and_inflation.md`).

## Scope

### In scope (current build, all phases)

- New, DNA cross-sell, Winback as explicit, always-visible segments.
- The DNA halo pathway (DNA-targeted media affecting non-DNA segments).
- A versioned, traceable curve bank with model-run-bound approval.
- Constrained scenario planning (locked cells, floors, bounded movement) as the primary planning
  mode, with an unconstrained benchmark shown for comparison only.
- Market-specific response curves with partial pooling (this redesign, Phase 2 onward).
- Spend- and physical-media-unit curves, CPA at both, and media cost inflation tracking (Phase 3).
- A portable, re-importable project bundle as the system of record (not Streamlit session state).

### Out of scope (explicitly, per `docs/ancestry_fh_mmm.md` and the redesign brief)

- Stage 2 media x context interactions.
- Fully independent per-market models as the default (available only as a documented comparison
  baseline - Model B in `docs/model_validation.md`).
- Automating currency conversion decisions - the tool stores exchange-rate context but does not
  silently convert or apply inflation assumptions without the assumption being visible in the UI.
- PowerPoint export (Excel + the project bundle cover handover).

## Current markets and segments

- **Markets (synthetic demo):** UK, Australia, Canada. Real markets are whatever the imported data
  defines - the model places no upper bound on market count, but partial pooling assumes markets
  share enough structure to be worth pooling (see `docs/market_hierarchy.md`).
- **Segments:** New, DNA cross-sell (`DNA_CrossSell`), Winback - fixed at these three by
  `core.schema.DEFAULT_SEGMENTS`, though the schema allows renaming/remapping the underlying outcome
  columns.

## Expected outputs

- A scorecard-gated, approved, fingerprint-bound fitted model (existing).
- Segment-level and (once Phase 2 lands) market-specific response curves in the curve bank.
- CPA and marginal-CPA tables by spend and by physical media unit (Phase 3).
- Constrained and unconstrained scenario comparisons, market-aware (Phase 3 extends the existing
  planner to require a market selection and use that market's own curve).
- A reproducible project report (Markdown + HTML, Phase 4) covering objective, data, model,
  diagnostics, curves, scenarios, limitations and the decision log in one document.
