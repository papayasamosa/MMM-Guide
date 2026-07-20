# Ancestry In-House MMM & Scenario Planning Tool

**Product & Technical Requirements Brief** - Prepared for: Claude Code build handoff | Version 1.0

This is the requirements brief `ancestry_mmm/` was built against. It is reproduced here (from the
original document) so the reasoning behind the app's structure - why segments are modelled jointly,
why the DNA halo pathway is explicit, why the scenario planner defaults to constrained rather than
unconstrained optimisation - stays with the code rather than living only in a chat history.

## 1. Purpose of this document

This brief sets out what the internal MMM and scenario planning tool needs to do for Ancestry, and
why. It draws on the Ancestry 2026 MMM RFP brief, prior model debriefs (mPHASIZE, 7 Stars), the
Ebiquity proposal, and a series of design conversations about model structure, scenario-planner
constraints, and application architecture.

The RFP describes MMMPact-style functionality - upload, transform, model, diagnose, plan, export -
as a useful reference shape. This tool does not need to replicate MMMPact exactly. It needs to do
whatever best serves Ancestry's actual planning, in-housing and governance needs, using the RFP and
the MMMPact concept only as a starting point, not a specification to satisfy literally.

Build for the analyst who inherits it, not the vendor who built it. Ancestry's own data scientist
must be able to operate, refresh and extend this independently after handover, with no ongoing
licence dependency.

Build for three FH segments and DNA halo, not a generic single-KPI MMM. New, DNA cross-sell and
Winback have materially different economics and must remain visible throughout - in the model, the
curves, and the planner.

Build for a living curve bank, not a one-off model output. Curves need to be stored, versioned, and
recalibrated as geo tests and in-platform incrementality results come in.

Build for planning under real constraints, not just an unconstrained optimum. Locked spend, phased
budgets, and commercial floors/ceilings are the normal way Ancestry will actually use this tool.

## 2. Business context this tool must serve

Ancestry's core FH measurement problem is that blended Family History figures hide three
acquisition paths with different media response, different promotional sensitivity, and different
value:

- **New to brand** - the most media-responsive segment; first-time subscribers with no prior
  Ancestry relationship.
- **DNA cross-sell (FH DNA)** - a high-value path driven heavily by DNA media, with a halo effect
  that must be quantified and tracked as DNA mix decisions change.
- **Winback** - lapsed subscribers with lower media sensitivity but strong promotional response.

Alongside this, the RFP identifies attribution distortion between brand and performance media, thin
curve granularity for cross-market synthesis, a Search-heavy mix that limits testing of new
channels, and DNA halo visibility as open measurement gaps. The tool's modelling layer needs to be
built with these specific gaps in mind rather than as a generic off-the-shelf MMM.

The wider measurement architecture also matters: MMM sits alongside geo-based incrementality
testing (run in-house by Ancestry) and in-platform incrementality experiments. The tool needs a
defined way for both to feed back into and recalibrate the curve bank over time - this is a
first-class workflow, not an afterthought.

## 3. Guiding principles

- **Transparency over black-box convenience.** Every coefficient, prior, transformation and curve
  must be inspectable and explainable to a non-technical marketing stakeholder.
- **Reproducibility over one-off scripts.** Every dataset transformation, model configuration and
  scenario must be recorded, versioned and replayable on refreshed data - not re-built by hand each
  cycle.
- **Segment-and-channel structure, not segment-only or channel-only.** Share what should genuinely
  be shared (adstock shape, saturation shape) and let what should differ, differ (segment response
  strength, promotional sensitivity, DNA halo).
- **Constrained planning as the default view.** The unconstrained optimum is a useful benchmark, not
  the primary output - Ancestry will plan against locked months, fixed channel totals and phased
  budgets.
- **No ongoing licence dependency.** Everything must run on infrastructure and open-source libraries
  Ancestry can own and operate (Streamlit, PyMC/PyMC-Marketing, pandas, ArviZ) with no proprietary
  platform lock-in.
- **Staged complexity.** Ship a robust core (shared channel curves, segment multipliers,
  baseline/seasonality/promo-driven monthly variation) before adding harder-to-justify refinements
  (media x context interactions).

## 4. Core goals - what the tool must be able to do

### 4.1 Data ingestion and transformation

- Upload weekly (or daily) media, sales/GSA, promotion, pricing, DNA-activity and control data from
  CSV/Excel/Parquet, with support for multiple source files (media, outcomes, controls) joined on
  date and geography.
- Provide an editable, auditable transformation layer - renaming, type changes, joins, calculated
  columns, lagged variables, missing-value handling and event/promo flags - recorded as an ordered,
  replayable pipeline rather than applied silently to the raw data.
- Support defining markets (UK, Australia, Canada) and FH segments (New, DNA cross-sell, Winback) as
  explicit structural dimensions, not just filter values.
- Include a validation step that flags likely modelling problems before fitting - low variation in a
  channel, high collinearity between channels, sparse segments/geographies, and hierarchy
  combinations that are likely to be weakly identified.

### 4.2 Modelling

The modelling core should follow a joint, hierarchical structure rather than three unrelated
per-segment models or a single blended model:

- One outcome model per market covering all three FH segments jointly (e.g. Negative Binomial on
  weekly GSAs by segment and geography), so segment estimates are internally consistent rather than
  three disconnected fits.
- Shared channel-level adstock and saturation curves, with segment-specific response multipliers
  estimated through partial pooling - segments borrow strength from each other where data is thin,
  and diverge where the data supports it.
- An explicit DNA halo pathway: DNA-targeted media as a lagged input into the DNA cross-sell
  equation (and, where evidence supports it, a smaller effect elsewhere), including DNA kit pricing
  and DNA promotional activity.
- Segment-specific promotional sensitivity (Winback in particular), rather than a single generic
  promotion flag applied uniformly.
- Monthly/seasonal variation driven by baseline demand, promotions, adstock carryover and
  saturation - with channel response curves held stable by default (Option 1). Media x context
  interactions (e.g. TV x WDYTYA, Search x DNA promotion) are an optional Stage 2 enhancement, added
  only where there is enough independent variation to identify them and where the effect is
  business-plausible.
- Support for a geographic hierarchy (UK / Australia / Canada) with partial pooling by default, and
  the ability to configure a specific market as unpooled where it is structurally too different to
  share strength with the others (e.g. a materially less mature market).
- Brand and performance media handled within the same framework, so always-on brand contribution to
  downstream conversion is not collapsed into last-click-style attribution.
- Model configuration should be interface-driven (choose hierarchy, adstock form, saturation form,
  priors) rather than requiring the analyst to hand-edit model code for routine changes.

### 4.3 Diagnostics and validation

- A model scorecard rather than a single headline R-squared: training fit, out-of-sample / rolling
  forecast accuracy, MCMC convergence (R-hat, divergences, effective sample size), residual checks,
  and posterior-predictive fit.
- ROI and saturation-curve plausibility checks, with the ability to flag channel effects that look
  implausible relative to business expectation.
- A structured way to compare model output against geo-test and in-platform incrementality-test
  results, and to record whether they agree - this comparison is part of the curve bank calibration
  workflow, not a side analysis.

### 4.4 Results and the curve bank

- Channel-level response and saturation curves, parametrised (not just plotted), exportable in a
  form suitable for cross-market synthesis where a market does not have a full model build.
- Segment-level and total-FH contribution views: total FH impact of a channel, plus which segment
  that impact falls into and what that segment is worth (LTV-weighted), so both "how many sign-ups"
  and "what kind of sign-up" questions can be answered.
- Versioned curve storage, so a curve bank entry can be traced to the model run, data window and
  calibration event (geo test / in-platform test) that produced or last updated it.
- Contribution waterfalls, ROAS/CPA by channel and segment, and uncertainty bands throughout - not
  point estimates presented as certainties.

### 4.5 Scenario planning and optimisation

This is the module Ancestry will use on an ongoing basis after handover, so it needs to support how
budgets are actually planned, not just produce a mathematically optimal allocation:

- **Manual scenario mode**: edit monthly/channel spend directly and see predicted outcomes update,
  by segment and in total.
- **Constrained optimisation mode**: lock specific channel-month cells (e.g. committed TV bookings),
  hold a channel's annual total fixed while letting timing move, fix a month's total while letting
  channel mix move, cap movement from the current plan (e.g. +/-20%), and protect minimum spend
  during defined periods (e.g. DNA promotional windows). Constraints should be settable at the cell,
  channel, month, quarter, product or funnel level.
- **Unconstrained benchmark mode**: shown for comparison only, clearly labelled as the theoretical
  optimum rather than the recommended plan, since it will typically ignore contractual and
  operational realities.
- Scenario definitions and results saved and re-loadable, so a scenario can be revisited, adjusted
  and re-compared later rather than being lost at the end of a session.
- Optimisation objective should be able to run on total value (LTV-weighted across segments), not
  just raw GSA volume, given the segments differ materially in worth.

### 4.6 Project persistence and handover

- A downloadable, re-importable project package so an analyst can pause and resume work without
  needing a live server session: transformed data and raw data as Parquet, transformation and
  scenario definitions as JSON, and the fitted model posterior as NetCDF (ArviZ InferenceData).
- An ordered, inspectable transformation history, so refreshed weekly data can be re-run through the
  same pipeline rather than rebuilt from scratch each cycle.
- Export to the formats Ancestry stakeholders actually consume - PowerPoint summaries, Excel
  data/curve exports, and the underlying project file for the data science team.
- No dependency on a paid third-party modelling platform or licence at any point in this workflow -
  open-source libraries only, consistent with the RFP's handover criteria.

## 5. Non-functional requirements

- Runs as a Streamlit application; session state used for in-session interactivity only, never as
  the system of record - the exportable project package is the durable store.
- Long-running model fitting (PyMC/NUTS sampling) must not block the interface indefinitely; show
  progress and sampling diagnostics as the model runs.
- Every transformation, model configuration and scenario constraint is human-readable (JSON/plain
  config), so a non-author can review and understand what was done.
- Clear separation between shared/pooled parameters and segment- or market-specific parameters in
  both the model code and the results UI, so the "what's shared vs. what's allowed to differ" logic
  is never hidden.
- Designed to be extended market-by-market (UK first, then Australia and Canada) without
  re-architecting the tool.

## 6. Suggested phasing

| Phase | Scope |
|---|---|
| **Phase 1 - Core** | Data upload + transformation pipeline; joint hierarchical FH model (shared curves, segment multipliers, DNA halo, promo-by-segment) for UK; diagnostics scorecard; parametrised curve export. |
| **Phase 2 - Planning** | Scenario planner with manual, constrained and unconstrained-benchmark modes; constraint types (locked cells, fixed channel/month totals, bounded movement); scenario save/reload. |
| **Phase 3 - Persistence & handover** | Full project export/import (Parquet + JSON + NetCDF); PowerPoint/Excel export; refresh workflow for new weekly data replaying the saved pipeline. |
| **Phase 4 - Extend** | Australia and Canada markets; geo/in-platform test calibration workflow feeding the curve bank; optional Stage 2 media x context interactions where justified by data. |

## 7. Explicitly out of scope for this build

- Modelling every month as having its own uniquely estimated media effectiveness - monthly
  variation should come from baseline, seasonality, promotions, adstock and saturation, not a
  separate coefficient per month.
- Media x context interaction effects beyond a small, business-justified set - this is a Stage 2
  addition, not part of the core model.
- Splitting a single total-FH outcome into segments via a fixed-share/multinomial approach -
  segments should be modelled jointly as correlated outcomes, since marketing can grow one segment
  without a corresponding trade-off in another.
- Any managed-service or vendor-hosted modelling dependency - the tool must be fully operable by
  Ancestry post-handover.

---

*Note for build: this brief describes intent and required capability, not a literal file/module
spec. Translate each goal into whatever Streamlit pages, PyMC model structure and storage layout
best achieve it - the existing MMM Studio codebase (`app.py`, `models.py`, `transformations.py`,
`optimization.py`, `attribution.py`) is a reasonable starting point to extend rather than replace.*

## What `ancestry_mmm/` actually built against this brief

See the "Ancestry FH MMM & Scenario Planner" section of the top-level `README.md` for what's
implemented (Phase 1 core + the scenario planner + basic persistence) versus explicitly deferred
(PowerPoint export, real AU/CA market builds, a live geo-test/in-platform-test feed, Stage 2
media x context interactions).
