# User Guide

A step-by-step walkthrough of the app as it exists today (11 steps). Written for a non-technical
user picking this up for the first time - each step's page also shows this same guidance inline
(purpose sentence + numbered steps at the top, "Next:" panel at the bottom).

## Step 1: Data Upload

Load the built-in synthetic demo data to try the tool end-to-end, or upload your own media/
outcomes/controls files (CSV or Excel). Each file needs a shared date column, and a market column
if you have more than one market.

## Step 2: Transform Pipeline

Join your uploaded sources into one dataset. Add any clean-up steps you need - renaming columns,
changing a column's type, calculated columns, lagged variables, filling in missing values, dropping
columns you don't need. Every step you add is recorded and can be replayed later on refreshed data.

## Step 3: Structure: Segments & Markets

Tell the tool which columns mean what: which markets to include, which column holds each segment's
outcome (New / DNA cross-sell / Winback), which columns are media channels, which of those are
DNA-targeted, promo flags, other controls, and each segment's lifetime value (LTV).

## Step 4: Channel & Media Units *(new, optional)*

For each channel, in each market, you can optionally record which column measures physical
delivery (impressions, GRPs, clicks, ...), what type of unit it is, its currency, and how its cost
is normally quoted (CPM, cost per GRP, ...). Skip this entirely if you don't have this information -
nothing else in the tool requires it yet.

## Step 5: Market Descriptors *(new, optional)*

For each market, a summary card shows how much data you have and how many channels have a
media-unit mapping. Below that, you can optionally record the market's currency and context
(population, awareness, penetration, maturity, ...). Skip this too if you don't have it yet.

## Step 6: Model Configuration

Review the markets and pooling detected from your structure. Adjust the adstock, saturation, and
pooling priors if you have reason to - the defaults are reasonable starting points for most data.
Advanced MCMC sampling settings (draws, tune, chains) are tucked into an "Advanced settings"
expander - most users won't need to touch them. Click "Prepare modelling frame" to finish this
step.

## Step 7: Model Training

Review the observation/market/segment/channel counts, then start the fit. This runs a real Bayesian
model fit and can take from a few minutes to significantly longer depending on your data size and
hardware - you'll see live sampling progress.

## Step 8: Diagnostics

Compute the scorecard: convergence, in-sample fit, posterior predictive coverage, and plausibility
flags. Once you're satisfied the model is trustworthy, approve it here - approval is what unlocks
the curve bank and Scenario Planner, and is tied to this exact model, so retraining or changing any
upstream setting invalidates it automatically.

## Step 9: Results & Curve Bank

Review channel and segment contributions, DNA halo strength, and the contribution waterfall. Once
the model is approved, save its curves to the curve bank as a versioned, traceable entry. You can
also log geo-test or in-platform calibration results against any saved entry.

## Step 10: Scenario Planner

Choose a market and a planning window. Edit a spend plan directly (manual mode), or add
constraints (locked cells, spend floors, bounded movement) and let the optimiser suggest an
allocation. An unconstrained benchmark is also available for comparison - it's a theoretical
optimum, not a recommended plan.

## Step 11: Project Export & Handover

Build a downloadable project bundle (Parquet + JSON + NetCDF - all open formats) so your work is
never only sitting in a browser session. Import a previous bundle to pick up where you left off.
Build an Excel summary of curves and contributions for handover.

## What's coming next

Steps 4-5 exist today purely to capture data; nothing downstream uses it yet. Once the
market-specific model lands (Phase 2), the same data drives market-specific curves, and Phase 3
adds CPA/media-unit reporting and inflation-aware scenario planning on top. See
`docs/project_objectives.md` for the full phased plan.
