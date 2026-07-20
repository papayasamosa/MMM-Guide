# Scenario Planner

## Today

`pages/08_Scenario_Planner.py` already requires a market selection and an approved, fingerprint-
matching model before it will evaluate or optimise anything (`core.optimization.evaluate_scenario` /
`optimize_scenario` both call `require_matching_approval` first). Manual, constrained, and
unconstrained-benchmark planning modes all exist. What it *doesn't* do yet is use a market-specific
curve for that market - because the model itself doesn't fit one (`docs/modelling_methodology.md`).
Selecting "Australia" today still evaluates against the same shared curve "UK" would use.

## Planned redesign (Phase 3)

Required controls (additions to what exists today in **bold**):

market, segment or overall, planning period, **spend or media-unit mode**, channel, current spend,
planned spend, **current media units, planned media units, cost-per-unit assumption, inflation
assumption**, minimum and maximum spend, locked spend, **locked media units**, total budget,
objective.

Supported objectives (additions in **bold**): maximise incremental outcome, minimise CPA,
maximise value, reach target response, **maintain response under inflation, maintain delivery under
inflation**.

Output additions: CPA, marginal CPA, media units, cost per unit, **and which market-specific curve
source was used** - local, pooled, or transferred (`docs/market_hierarchy.md` section 4) - so a
planner can see when they're planning against a transferred estimate rather than a locally
estimated curve.

The core rule stays: **the planner never silently substitutes another market's curve, and never
silently applies a future inflation assumption** - both must be visible in the UI when in effect.

## What Phase 1 adds toward this

The Channel & Media Units page (optional per-channel spend/media-unit mapping) and Market
Descriptors page (currency, context) capture inputs the Phase 3 planner will need for the
spend-vs-media-unit mode and inflation assumptions. The planner itself is unchanged in this PR.
