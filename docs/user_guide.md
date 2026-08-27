# User Guide

A step-by-step walkthrough of the app as it exists today. Written for a non-technical
user picking this up for the first time - each page also shows its own guidance inline
(purpose sentence + numbered steps at the top, "Next:" panel at the bottom).

The sidebar groups pages into five workflow areas - Data, Model Design, Fit & Validate,
Decision Support, Operations - in the order below. Steps marked *(optional)* are useful
workspaces, not required stops: Home and each page's own footer recommend the next
**required** step, skipping optional ones automatically when nothing needs your attention
there yet.

## Step 1: Data Sources

Load the built-in synthetic demo data to try the tool end-to-end, or upload your own
Outcomes / Activity and Media / Context and External Factors files (CSV or Excel), plus
optional Experiment Evidence. Each file needs a shared date column, and a market column
if you have more than one market. The page leads with source readiness and the
add/replace-source action; template downloads and the full source inventory follow.
Specialist Experiment Evidence and Named Events registry administration sit behind their
own "(advanced)" sections further down.

## Step 2: Prepare Data

Join your uploaded sources into one dataset. Add any clean-up steps you need - renaming
columns, changing a column's type, calculated columns, lagged variables, filling in
missing values, dropping columns you don't need. Every step you add is recorded and can
be replayed later on refreshed data. A recognised standard source pack skips this step
entirely - its tables are already model-input-ready.

## Step 3: Coverage & Gaps *(optional)*

Review each prepared model input's coverage and missingness by market before defining
model structure. Choose which inputs to treat as governed variables, declare each one's
frequency/variable class/source, build the coverage matrix, and propose/approve a
treatment for anything you want eligible for official (not just exploratory) use. Skip
this for an exploratory continuation; it becomes required before official preparation.

## Step 4: Activity Mapping

Give each model input a governed activity identity before model scope is selected: map
it explicitly to its physical column, and record its causal role, reporting channel,
delivery/Search objects and cost mapping separately from one another. This is required -
Model Structure reads governed activities from here, not raw column names.

## Step 5: Model Structure

Tell the tool which columns mean what: which markets to include, which governed
activities and outcomes are in scope, which column holds each segment's outcome
(New / DNA cross-sell / Winback), promo flags, other controls, and each segment's
lifetime value (LTV).

## Step 6: Causal Graph *(optional)*

Build a variable-level causal structure - nodes for interventions, mediators, outcomes
and controls, with edges carrying an explicit role and lag - and approve it. An approved
graph becomes the sole authoritative structural input to model compilation
(REQ-GRAPH-001); skip it and Model Setup falls back to the `MediaOutcomePathway`
catalogue configured on Model Structure exactly as before.

## Step 7: Market Context *(optional)*

For each market, a summary card shows its data coverage. Below that, you can optionally
record the market's currency and descriptive context (population, awareness,
penetration, maturity, ...) for reporting and future interpretation. Every field is
optional and can be filled in later.

## Step 8: Model Setup

Three distinct, unambiguously-owned concepts on one page: **Market scope and hierarchy**
is a read-only summary inherited from Model Structure (change markets/pooling exceptions
there, not here). **Response strategy** is your choice here between a single shared
curve per channel across all markets, or - once your project has at least 2 markets -
market-specific, partially-pooled curves. **Advanced response assumptions** (adstock,
saturation, pooling scales, cross-product priors, promo sensitivity) and **Sampling
settings** (MCMC draws/tune/chains/target-accept) are both tucked into their own
collapsed sections with reasonable defaults - most users won't need to open them. Click
"Prepare modelling frame" to finish this step.

## Step 9: Fit Model

Review the observation/market/segment/channel counts and the response strategy chosen
on the previous step, then start the fit. This runs a real Bayesian model fit and can
take from a few minutes to significantly longer depending on your data size and
hardware - you'll see live sampling progress. Once trained, you can optionally save the
fit's scorecard as a comparison candidate to review alongside other candidates on the
next step.

## Step 10: Model Comparison *(optional)*

Compare fitted candidates side by side - a shared-response fit, a single-market fit
(achieved by fitting with one market selected on Model Structure), and a market-specific
partially-pooled fit - before deciding which one to take forward to Model Diagnostics. A
market-specific model isn't adopted just for being more sophisticated; it should show
comparable-or-better prediction, credible market differentiation, and acceptable
diagnostics (`docs/model_validation.md`). Skip this when there's only one candidate to
review.

## Step 11: Model Diagnostics

Compute the scorecard, then work through the review flow the page leads with: the
top-line trust state and domain-health rail, the primary blocking concern if any, the
full diagnostic detail tabs (convergence, in-sample fit, PPC coverage, plausibility,
identification, Candidate A Search where applicable), then Validation readiness and
Model approval. Nine further specialised evidence sections (prior predictive check,
PSIS-LOO/WAIC, backtest, funnel-coherence, posterior predictive distributions,
historical validation, graphical identification, latent-state identification,
experiment & calibration evidence) are grouped under one collapsed "Specialised
evidence" area below approval - available for deeper investigation, never required to
approve. Approval is what unlocks Results & Response Curves' governed planning path and
Scenario Planner, and is tied to this exact model (including which response strategy
you chose), so retraining or changing any upstream setting invalidates it automatically.

## Step 12: Results & Response Curves

For a shared-response model: review channel and segment contributions, DNA halo
strength, and the contribution waterfall, then a channel curve viewer. For a
market-specific model: the same total/segment/waterfall views are available
market-by-market (or aggregated across markets), computed with each market's own
`beta`/`hill_K` rather than a shared curve, plus each market's own channel curve viewer.
Either curve viewer shows CPA (average and marginal) alongside the spend curve, and -
where you've mapped a channel to a physical delivery column on Activity Mapping - a
response-unit curve, historical cost-per-unit trend, and calculators for "how much to
spend to buy N units" and "what response would N units produce." An optional posterior
uncertainty band (re-running the curve once per sampled posterior draw) is available for
either model type, at the cost of extra computation time.

## Step 13: Planning Curves

The curve viewer on Results & Response Curves renders directly from the fitted trace
and current session state - useful for exploration, but not itself a governed artefact:
nothing pins it to a specific approval, and it disappears when the session ends. This
page (`CurveService.create_official_artifact`, REQ-CURVE-001) is the separate,
deliberate act of turning that fitted evidence into a governed, fingerprinted curve
artefact - re-validating the full governance chain (model approval, outcome approval,
activity definitions, threshold policy) before writing anything, then persisting the
result under the official curve artifact store. Generate an **official model-input
curve** (response on the model's native input scale) and, wherever a governed cost
mapping and currency/FX evidence exist, an **official monetary curve** (response
against spend, in the market's reporting currency). Every artefact carries fingerprints
over its governance inputs, so a later consumer (Results & Response Curves, project
export, a saved scenario) can prove it is still current rather than silently reusing
stale evidence - see `docs/curve_bank.md` and `docs/approved_requirements/REQ-CURVE-001.md`.

## Step 14: Scenario Planner

Two evaluation methods are available for the editable spend plan: **steady-state
monthly** (approximates each month independently at its adstock steady state; the only
method the constrained/unconstrained optimiser tabs use) and **sequential weekly**
(continues from this market's own historical fitted state, models real week-by-week
carryover, and reports short/long response horizons plus terminal carryover - manual-tab
only in this release). Choose a market and planning window; for a market-specific model,
an expander shows each planned channel's evidence tier (local/pooled/transferred) for
that market. Edit a spend plan directly (manual mode) - in spend or, for any channel
you've mapped to a physical delivery column, in media units instead - or add constraints
(locked cells, spend floors, bounded movement) and let the optimiser suggest an
allocation. Every result shows a blended average CPA (current plan vs. this one),
alongside total predicted value or volume. An unconstrained benchmark is also available
for comparison - it's a theoretical optimum, not a recommended plan. An optional
posterior uncertainty view re-runs the scenario once per sampled posterior draw and
summarizes the resulting distribution (mean/median/90% interval) alongside the
probability the current plan actually outperforms the current/baseline plan, paired
draw-for-draw so the comparison isn't inflated by independently-resampled noise.

## Step 15: Export & Recovery

Build a downloadable project bundle (Parquet + JSON + NetCDF - all open formats) so your
work is never only sitting in a browser session. Import a previous bundle to pick up
where you left off. Build an Excel summary of curves and contributions for portability,
or a reproducible project report (Markdown + HTML) covering objective, data, model,
diagnostics, curve bank, scenarios, and known limitations in one document - available at
any point in the workflow, not only once every step is complete.

## What's coming next

Market-specific curves can now be reviewed, diagnosed, saved to the curve bank with
their own evidence-tier labelling, and planned against in Scenario Planner - including
CPA, media-unit planning mode, inflation calculators, Shapley attribution (market-aware),
and posterior uncertainty for both curves and scenario outcomes. See
`docs/project_objectives.md` for the full phased plan and `docs/limitations.md` for what's
deliberately still out of scope (CPA/inflation as optimiser objectives, media-unit spend
constraints, and more).
