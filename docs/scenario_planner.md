# Scenario Planner

## Today

`pages/08_Scenario_Planner.py` already requires a market selection and an approved, fingerprint-
matching model before it will evaluate or optimise anything (`core.optimization.evaluate_scenario` /
`optimize_scenario` both call `require_matching_approval` first). Manual, constrained, and
unconstrained-benchmark planning modes all exist - for a **shared-curve model (Model A)**.

Since Phase 2, a market-specific model (Model C, `docs/modelling_methodology.md`) can be fit and
approved, but the planner deliberately **blocks entirely** for `model_type == "market_specific"`
with a message pointing back to the Results & Curve Bank curve viewer, rather than silently
evaluating one market's posterior mean through code built for `FHPosteriorParams`'s Model-A-only
shape (`docs/decision_log.md`). Selecting "Australia" for a *shared-curve* model still evaluates
against the same curve "UK" would use, since Model A has no market-specific curve to select.

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

## What's built toward this so far

Phase 1 added the Channel & Media Units page (optional per-channel spend/media-unit mapping) and
Market Descriptors page (currency, context), capturing inputs the Phase 3 planner will need for the
spend-vs-media-unit mode and inflation assumptions. Phase 2 added the market-specific model the
planner will eventually plan against, plus the block described above - the planner's actual
evaluation/optimisation logic is otherwise unchanged.
