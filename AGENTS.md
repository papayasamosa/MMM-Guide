# AGENTS.md

## Scope

These instructions apply to the whole `papayasamosa/MMM-Guide` repository.

More specific `AGENTS.md` files under `ancestry_mmm/core`, `ancestry_mmm/pages`, and `ancestry_mmm/tests` add rules for those areas. The most specific applicable file takes precedence, but no nested instruction may weaken the business definitions, mathematical-correctness requirements, or governance rules in this root file.

## Product objective

Build an internal, transparent, resumable Bayesian MMM application for Ancestry that can be operated without an ongoing vendor licence.

The application must support:

- data upload, validation, transformation, and provenance
- saved project bundles that can be downloaded and re-uploaded later
- separate Family History New, DNA cross-sell, and Winback outcomes
- DNA kit outcomes
- hierarchical and partially pooled market/segment models
- direct, cross-product halo, exploratory, mediated-diagnostic, and excluded pathways
- net bill-through as the primary Family History marketing outcome
- Brand Search sensitivity analysis
- posterior response curves
- average and marginal CPA and ROI
- response horizons
- year-on-year comparison
- constrained scenario planning
- later brand-health and DNA purchase-composition modules

Model correctness takes priority over interface breadth.

## Business definitions that must not drift

### Family History

The primary marketing outcome is weekly Family History net bill-through count attributed to original signup week.

Keep separate:

- net bill-through count
- signup count
- net bill-through rate
- finance-date GSA count
- revenue/value

Never use a rate as a CPA denominator. Never silently alias NBT to GSA.

Fit the main Family History segments separately:

- New
- DNA cross-sell
- Winback

Totals may be calculated from draw-level segment outcomes after fitting.

### DNA

Fit total DNA kit sales first unless separate self/gift composition is demonstrably identifiable.

Do not classify every unactivated kit as gifted.

Future categories may include:

- self-activated
- gifted-activated
- mature unactivated
- immature unactivated
- unknown linkage
- cancelled/returned

### Brand Search

Do not treat Brand Search as fully incremental by default.

Maintain explicit alternatives:

- direct-channel benchmark
- excluded sensitivity
- assumption-based demand-capture reallocation
- experiment-calibrated incrementality
- genuine fitted mediation only when a valid causal model exists

A post-hoc reallocation is not fitted mediation.

## PyMC and PyMC Labs reference policy

This project is built with PyMC and should be informed by the PyMC Labs ecosystem.

Primary upstream references:

1. `pymc-labs/pymc-marketing`
   - MMM model architecture
   - public transformation APIs
   - geometric and delayed adstock
   - saturation functions
   - priors and model configuration
   - multidimensional/hierarchical MMM patterns
   - posterior predictive checks
   - contributions and attribution
   - response curves
   - lift-test calibration
   - budget optimisation
   - time-varying media and intercept functionality where relevant
2. `pymc-labs/mmm-param-recovery`
   - use only if the repository currently exists and is publicly accessible
   - synthetic-data design
   - identifiability and parameter recovery
   - recovery of adstock, saturation, and media coefficients
   - do not invent or rely on this repository if it cannot be verified
3. `pymc-labs/CausalPy`
   - quasi-experimental and causal-impact functionality
   - synthetic control
   - interrupted time series
   - counterfactual analysis
   - use only where the task is genuinely quasi-experimental
4. `pymc-devs/pymc`
   - PyMC model, distribution, dimensions, sampling, and computational APIs
   - use for core probabilistic-programming questions
5. Other `pymc-labs` repositories
   - inspect only when their purpose clearly matches the task
   - do not assume every repository in the organisation is relevant or production-ready

Official repositories, current documentation, examples, changelogs, and tests are the preferred sources. Do not rely on memory for current APIs.

## Required upstream-reference workflow

Before creating or changing modelling functionality:

1. Identify the closest relevant PyMC Marketing, PyMC, CausalPy, or verified PyMC Labs implementation.
2. Inspect its current public API, documentation, examples, tests, and supported version.
3. Record the exact upstream reference in the PR description or a project alignment document:
   - repository
   - version or commit
   - module/class/function
   - example or test consulted
4. Perform a gap analysis:
   - what upstream already supports
   - what Ancestry uniquely requires
   - why custom code is still necessary
5. Prefer supported public APIs and composition over copying private internals.
6. Do not reimplement upstream functionality without a documented reason.
7. When custom behaviour is required, add:
   - equivalence tests where behaviour should match upstream
   - divergence tests where Ancestry intentionally differs
   - parameter-recovery or simulation tests where applicable
8. Re-check compatibility whenever PyMC or PyMC Marketing versions change.

## Claim policy

Do not claim that the application is "built on PyMC Marketing" merely because `pymc-marketing` appears in dependencies.

Use the following language until the code actually uses supported PyMC Marketing APIs in material modelling paths:

> Built in PyMC and informed by PyMC Marketing.

The stronger claim:

> Built on PyMC Marketing.

is allowed only when the repository:

- imports and uses supported PyMC Marketing public APIs in production modelling paths, or
- has a documented compatibility layer with tested numerical equivalence for the relevant PyMC Marketing transformations and model behaviours.

Maintain `docs/pymc_marketing_alignment.md` with an honest feature-by-feature mapping.

## Dependency policy

Pin compatible versions of:

- Python
- PyMC
- PyTensor
- ArviZ
- PyMC Marketing

Do not leave PyMC Marketing at an unrestricted lower-bound-only dependency.

For any version change:

- review upstream changelogs
- run the full compatibility suite
- update the alignment document
- record migration implications for saved projects and posterior artefacts

## Architecture

PyMC and PyMC Marketing are modelling dependencies, not the application architecture.

Keep separate:

- Streamlit pages
- framework-independent modelling services
- data preparation
- persistence
- scenario planning
- exports

Core logic must be callable without Streamlit so it can later be exposed through FastAPI and used by a React frontend.

Do not import Streamlit from `ancestry_mmm/core`.

## Mathematical rules

- The fitted count model uses a log link, so linear-predictor media terms are not outcome counts.
- Business response must be calculated on the outcome scale through the full link function.
- CPA and ROI must use incremental outcome counts or value, not log-scale eta contributions.
- Posterior draws must be aggregated before posterior summaries.
- Do not add independently summarised medians.
- Do not calculate whole-plan marginal economics without a defined budget perturbation direction.
- Do not assign full channel spend to several pathway components unless an explicit cost-allocation rule exists.
- Distinguish model-input units from monetary spend.
- Do not assume every channel's model input is currency. TV may use TVRs, other channels may use impressions, clicks, GRPs, or spend.
- Monetary response curves require a governed market/channel/time cost mapping from spend to model input.
- Do not fabricate observed support from a posterior saturation parameter.

## Model hierarchy

Make parameter pooling explicit.

Document which parameters are:

- fully pooled
- partially pooled
- market-specific
- segment-specific
- channel-specific
- unpooled

Do not describe the model as having fully independent segment curves when only response amplitude varies by segment.

## Governance

Keep separate:

- fitted in model
- visible in analyst attribution
- approved for headline reporting
- eligible for planning

Evidence status is not reporting approval.

Exploratory and mediated-diagnostic pathways are planning-disabled by default.

Stale models must not drive official reporting or planning.

## Persistence

A saved project should preserve, where applicable:

- raw or durable source data
- transformed data
- transformation history
- model-ready data
- outcomes
- pathways
- controls and promotions
- priors
- pooling settings
- NBT metadata
- Brand Search configuration
- model metadata
- posterior artefacts
- diagnostics
- curve outputs
- approvals
- scenarios
- workflow checkpoint
- schema and app versions
- fingerprints

Changes to persistence require migration and round-trip tests.

## Required PR discipline

For every substantive modelling PR:

- state the business question
- state the mathematical estimand
- state the output scale and units
- cite upstream references
- explain custom deviations
- add tests
- run CI
- state remaining limitations honestly

Keep PRs narrow. Do not mix model-algebra changes with a large UI redesign.
