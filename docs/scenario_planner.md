# Scenario Planner

## Today (Phase 3c - built)

`pages/08_Scenario_Planner.py` requires a market selection and an approved, fingerprint-matching
model before it will evaluate or optimise anything (`core.optimization.evaluate_scenario` /
`optimize_scenario` both call `require_matching_approval` first). Manual, constrained, and
unconstrained-benchmark planning modes work for **either model type**:

- **Shared-curve model (Model A):** every market plans against the same curve; only market
  baselines (`market_offset`) differ by market.
- **Market-specific model (Model C):** the selected market's own fitted `hill_K`/`beta` drive the
  plan - `core.optimization` dispatches to `steady_state_segment_response_market_specific` instead
  of the Model A version based on `model_type`, with identical planning math (constraints, bounds,
  the optimiser objective) either way, since both response functions share the same
  `(market, spend_by_channel, meta, params, reference_context) -> {segment: rate}` contract. The
  planner shows each planned channel's evidence tier (`docs/market_hierarchy.md` section 4) for the
  selected market in an expander, so a planner can see when they're planning against a transferred
  estimate rather than a locally estimated curve.

Required controls (additions to what existed before Phase 3c in **bold**):

market, segment or overall, planning period, **spend or media-unit mode**, channel, current spend,
planned spend, **current media units, planned media units, cost-per-unit assumption**, minimum and
maximum spend, locked spend, total budget, objective.

- **Spend or media-unit mode:** the spend plan editor can display/accept physical media units
  instead of currency for any channel with a media-unit mapping (Channel & Media Units) and a valid
  historical cost-per-unit - built on `core.media_units`'s conversion functions, the same average-
  historical-cost-per-unit simplification Results & Curve Bank's response-unit curve uses. The plan
  is always stored in spend terms internally; media-unit mode only changes what the editor
  displays/accepts, with the cost-per-unit assumption in use always shown, never applied silently.
  Channels without a mapping stay in spend terms regardless of mode.

Output additions: product-aware `avg_cpa` (Family History GSAs) and, where the model has DNA-kit
segments, `dna_avg_cpa` (DNA kits) on every predicted-outcomes row and as "current plan vs this
optimised/theoretical-optimum plan" metrics on each result panel - never a blended total-spend /
(FH-GSAs-plus-DNA-kits) number (`docs/dna_fh_causal_structure.md`).

`objective` is explicit (`core.optimization.VALID_OBJECTIVES`): `"fh_gsa"` (default - maximise
Family History GSAs), `"dna_kits"` (maximise DNA kit sales - only offered where the model has
DNA-kit segments), `"expected_value"` (LTV-weighted total value, requires `ltv`), or
`"weighted_mix"` (an analyst-supplied per-segment weight dict - not yet exposed in this UI, core
support only). There is no generic "maximise volume" objective - it would silently combine Family
History GSAs and DNA kit sales into one meaningless total (the instruction document's audit-
confirmed defect this replaced; see `docs/decision_log.md`). A segment outside the chosen
objective's scope contributes 0 to it, never an implicit 1.

**Not built in this phase:**

- Locked media units, minimum/maximum media units as their own constraint types (`SpendConstraint`
  still operates in spend terms only - convert a media-unit target to spend via
  `core.media_units.equivalent_delivery` first).
- "Minimise CPA," "maintain response under inflation," "maintain delivery under inflation" as
  distinct optimiser objectives - `avg_cpa`/`dna_avg_cpa` are reported as output metrics, not
  (yet) optimisation targets in their own right.
- `"weighted_mix"` and per-segment `target_segments` (e.g. "maximise FH New" only) are implemented
  in `core.optimization` but not yet exposed as UI controls on this page - the radio only offers
  `"fh_gsa"`/`"dna_kits"`/`"expected_value"`.
- Marginal CPA as a scenario-level metric - the planner's optimiser always conserves total budget
  (`conserve_total_budget=True`), so there's no net spend change to compute a meaningful marginal
  CPA against; the product-aware *average* CPA of the current vs. optimised allocation is the
  metric that is actually well-defined here (see `docs/decision_log.md`).

The core rule stays: **the planner never silently substitutes another market's curve, and never
silently applies a future inflation assumption** - both are always visible in the UI when in effect.

## What's built toward this so far

Phase 1 added the Channel & Media Units page (optional per-channel spend/media-unit mapping) and
Market Descriptors page (currency, context). Phase 2 added the market-specific model. Phase 3b added
`core.media_units`'s CPA/media-unit/inflation calculations. Phase 3c (this work) wired all of it
into the planner itself: market-type dispatch in `core.optimization`, the media-unit planning mode,
the evidence-tier panel, and the blended-CPA outputs described above.
