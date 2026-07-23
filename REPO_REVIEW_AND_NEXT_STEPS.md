# Ancestry MMM Critical Repository Review and Coding-LLM Next Steps

## Repository baseline

Repository:

```text
papayasamosa/MMM-Guide
```

Current head reviewed:

```text
12de7f29c61cae48f0479b9b5b4f122d8bc60514
```

Latest commit:

```text
Update MMM guide content and supporting files
```

No GitHub Actions workflow run was returned for the exact current head.

---

# 1. Executive assessment

The latest push fixes the prior outcome-scale defect. The canonical curve
engine now calculates:

```text
incremental response =
mu(selected channel input)
-
mu(counterfactual channel input)
```

It also introduces explicit reference contexts, full-model counterfactual
prediction, finite-difference marginal response, channel-total economics,
component cost-allocation controls, portfolio perturbations, observed-support
requirements, configurable current-spend definitions, currency/FX governance,
attribution reconciliation, and stronger tests.

The remaining central issue is that the fitted model input may be spend,
TVRs/GRPs, impressions, clicks, sessions, insertions, or another exposure
unit. A single global scale cannot safely convert those inputs to money.

The required next step is PR G2A.2: separate model-input response curves from
monetary spend-response curves, introduce governed market/channel/time cost
mappings, and document/test PyMC Marketing alignment.

Do not move to response-horizon UI, year-on-year UI, or a dynamic planner
before this core contract is complete.

---

# 2. Completed foundation

The reviewed head provides:

- outcome-scale counterfactual curves through the normal prediction functions
- context-dependent response for baseline, promotion, seasonality, other
  media, and market effects
- scale-aware numerical marginal response
- reconciling direct/halo response decomposition
- component economics only with explicit cost allocation
- channel-total economics that count cost once
- explicit portfolio marginal direction
- actual support governance rather than support inferred from Hill K
- ISO local/reporting currency and dated FX governance
- draw-level authoritative exports and posterior summaries
- migration-review support for legacy pathway governance

---

# 3. Critical issues addressed by G2A.2

## 3.1 Model input is not necessarily spend

Separate:

```text
media_input
media_input_unit
local_spend
local_currency
reporting_currency_spend
```

Define cost mappings at market × channel × period or cost context. If no valid
mapping exists, allow model-input response curves, show their unit, suppress
monetary CPA/ROI, and block monetary optimisation.

## 3.2 A global scale is insufficient

Channels may be represented in currency, currency thousands, TVRs, millions
of impressions, clicks, or other units. Unit identity and scale must be
channel- and market-specific.

## 3.3 Costs vary by context

The same amount of money may buy a different media quantity by market, period,
platform, or plan. Cost context must distinguish changes in media price from
changes in response.

## 3.4 Direct and halo economics

Direct and halo governance views must be response/value decompositions by
default. They must not imply allocated CPA/ROI without explicit component cost
allocation.

## 3.5 View and metric naming

The view formerly called `market` retains channel grain and should be named
`market_channel_metric`. `average_cpa` relative to a nonzero counterfactual is
counterfactual incremental CPA and must carry that scope explicitly.

## 3.6 Representative steady state

A curve evaluated at average trend, promotion, and Fourier values is a
representative steady-state curve. It is not automatically historical weekly
contribution, annual incremental outcome, or Shapley attribution.

## 3.7 PyMC Marketing alignment

The honest product description is:

```text
Built in PyMC and informed by PyMC Marketing
```

Document alignment for adstock, saturation, priors, multidimensional
structure, attribution, curves, calibration, and optimisation. Pin compatible
versions and add numerical compatibility or documented-divergence tests.

## 3.8 CI and resumability

Exact-head CI must pass on the merge candidate. Public resumability should be
covered across upload, transform, configure, fit, approve, curve creation,
save/restore, scenario creation, and restore again.

---

# 4. PR G2A.2 required implementation

## A. Media-input metadata

For every market/channel input, store:

- media input column
- media input unit
- unit scale
- input kind (spend or exposure)
- whether a cost mapping is required
- source
- effective period

## B. Governed cost mappings

Provide:

```text
spend_to_media_input
media_input_to_spend
marginal_cost_per_media_input
marginal_media_input_per_currency
```

at market × channel × cost context grain.

Initial methods:

1. identity spend
2. fixed cost per unit
3. piecewise-linear
4. uploaded plan

Governance fields:

- mapping ID and method
- source
- market and channel
- currency
- effective period
- assumptions
- approval status

## C. Explicit curve types

Model-input curve:

```text
media input -> incremental outcome
```

This remains available when the model is valid.

Monetary curve:

```text
spend -> media input -> incremental outcome
```

This is available only with a valid mapping.

## D. Monetary marginal response

Calculate and store:

```text
d outcome / d currency
=
d outcome / d media input
×
d media input / d currency
```

## E. Governance corrections

- Direct/halo views are response-only unless component costs are allocated.
- Rename `market` to `market_channel_metric`.
- Store `counterfactual_incremental_cpa` and counterfactual scope.
- Store curve type and explicit steady-state interpretation.

## F. PyMC Marketing alignment files

Add:

```text
AGENTS.md
ancestry_mmm/core/AGENTS.md
ancestry_mmm/pages/AGENTS.md
ancestry_mmm/tests/AGENTS.md
docs/pymc_marketing_alignment.md
```

Inspect current official transformation, multidimensional MMM, prior,
contribution, response-curve, optimiser, and lift-calibration APIs before
changing related production code.

## G. Required tests

Cover:

1. spend-input identity mappings
2. fixed-cost exposure mappings
3. impressions and other input units
4. channel-specific scales
5. different market and period costs
6. piecewise costs
7. marginal conversion
8. model-input curves without costs
9. blocked monetary economics without mappings
10. NBT CPA, marginal CPA, and ROI
11. FX combined with media cost
12. direct/halo response-only views
13. counterfactual CPA scope
14. persistence and legacy migration
15. PyMC Marketing numerical compatibility
16. save/re-upload/resume
17. all unit, Ruff, Streamlit AppTest, parity, persistence, migration, and
    resumability gates on the exact merge candidate

---

# 5. Following phases

After G2A.2:

- G2B: sequential response horizons using impulse-response simulation
- G2C: year-on-year decomposition of spend/saturation, media cost, channel
  mix, segment/product mix, context, and explicitly modelled parameter change
- G2D: decision-ready stakeholder UI
- G3: business-ready monetary planner
- G4: sequential monthly planner with carryover and terminal effects

---

# 6. Exact implementation instruction

> Review `papayasamosa/MMM-Guide` at commit
> `12de7f29c61cae48f0479b9b5b4f122d8bc60514` or later. Implement PR G2A.2
> only. Retain the corrected outcome-scale counterfactual curve engine. Do not
> start the response-horizon UI, year-on-year UI, or dynamic planner. Separate
> model media input from monetary spend. Add explicit market/channel
> media-input metadata and a governed cost-mapping interface supporting
> identity spend, fixed cost per unit, piecewise-linear, and uploaded-plan
> mappings, with market, channel, currency, context, effective period, source,
> assumptions, and approval metadata. Generate model-input curves without
> cost data but suppress CPA, ROI, and monetary optimisation until a valid
> mapping exists. Apply mappings before the outcome-scale predictor for
> monetary curves and calculate monetary marginal response through both the
> mapping and MMM. Support different units, market costs, and cost contexts.
> Make direct and halo views response-only without component cost allocation.
> Rename the channel-grain market view, label counterfactual CPA scope, and
> label steady-state representative context. Add the supplied AGENTS files,
> PyMC Marketing alignment documentation, compatible version pins, numerical
> compatibility/divergence tests, persistence/migration coverage, and public
> save/re-upload/resume coverage. Require all tests, Ruff, AppTests, parity,
> curve/cost, persistence/migration, and resumability gates to pass in GitHub
> Actions on the exact merge candidate.
