# PyMC Marketing alignment

Status: G2A.5, reviewed 2026-07-24.

The product claim is: **Built in PyMC and informed by PyMC Marketing.**

This repository does not claim to be a wrapper around PyMC Marketing. Its
multi-outcome Family History/DNA pathway model, governed direct/halo
decomposition, and project-bundle workflow are custom PyMC code. PyMC
Marketing is the public implementation and validation reference wherever its
semantics match.

## Version reference

The reproducible Python 3.12 environment is pinned to:

- Python 3.12 (`.python-version` and `runtime.txt`)
- PyMC 5.28.5
- PyTensor 2.38.3
- ArviZ 0.23.4
- PyMC Marketing 0.19.4

Python 3.11 uses PyMC Marketing 0.19.2 because that is the compatible locked
resolution for the supported interpreter range. The numerical core pins are
shared across both supported interpreters.

Official references inspected for this alignment:

- [GeometricAdstock](https://www.pymc-marketing.io/en/stable/api/generated/pymc_marketing.mmm.components.adstock.GeometricAdstock.html)
- [geometric_adstock transformer](https://www.pymc-marketing.io/en/stable/api/generated/pymc_marketing.mmm.transformers.geometric_adstock.html)
- [multidimensional MMM](https://www.pymc-marketing.io/en/latest/api/generated/pymc_marketing.mmm.mmm.html)
- [budget optimizer](https://www.pymc-marketing.io/en/stable/api/generated/pymc_marketing.mmm.budget_optimizer.html)
- [allocation assessment and risk-aware utilities](https://www.pymc-marketing.io/en/stable/notebooks/mmm/mmm_allocation_assessment.html)
- [lift-test calibration](https://www.pymc-marketing.io/en/stable/api/generated/pymc_marketing.mmm.lift_test.html)

## Alignment matrix

| Area | Upstream reference | Repository implementation | Status |
|---|---|---|---|
| Geometric adstock | `GeometricAdstock` / `geometric_adstock`, with lag length, normalization, axis/dimension and convolution mode | Recursive geometric carryover in NumPy and PyTensor, reset at market boundaries | Numerically aligned for unnormalised finite histories when upstream lag length covers the history; compatibility test maintained |
| Adstock normalization | Finite-lag weights normalized by their sum | Infinite-geometric scale convention, multiplying by `1 - alpha` | Intentional divergence; retained for fitted-model continuity and documented in transformation tests |
| Saturation | Public saturation components, including Hill-family transforms | Explicit `x**S / (K**S + x**S)` Hill response in NumPy and PyTensor | Conceptually aligned; custom parameter naming and pathway integration |
| Priors | Component-level configurable PyMC priors | Custom hierarchical priors for the multi-outcome pathway model | Informed by upstream; not API-equivalent |
| Multidimensional modelling | Named dimensions for channels, controls and other model dimensions | Explicit market, outcome, channel, pathway and control dimensions | Aligned design principle; custom likelihood and hierarchy |
| Attribution | Posterior contribution facilities around an MMM | Outcome-scale counterfactual and Shapley implementations with direct/halo governance | Intentional custom implementation |
| Response curves | Posterior response transformations | Outcome-scale steady-state counterfactual curves | Custom, with explicit representative-context semantics |
| Non-monetary inputs | Optimizer supports monetary budgets converted through channel `cost_per_unit` | Governed market × activity inputs; only cost-bearing decisions use market × channel × context mappings, while response-only quantities remain non-monetary | Aligned principle, broader governance/persistence contract |
| Calibration | Lift-test measurements and cost-per-target calibration | Existing calibration records and custom pathway/model workflow | Informed by upstream; direct API adoption deferred |
| Optimization | `BudgetOptimizer` evaluates posterior response distributions and supports channel masks, `cost_per_unit`, constraints, and custom/risk-aware utilities | Typed incremental objectives, activity-aware constraints, explicit counterfactual policies, mixed economics, and paired posterior re-evaluation of candidate versus current plan | Semantically aligned; custom implementation retained for multi-outcome pathways and governed mixed-input plans |

## Media input and money

The model input is the quantity supplied to adstock and saturation. It may be
spend, impressions, clicks, GRPs, or another delivery unit. A global scaling
factor is not a cost model.

`core.media_costs` therefore stores explicit market/channel input metadata and
governed market/channel/context mappings between local-currency spend and model
input. Model-input response curves are always permitted. Monetary CPA, ROI,
and monetary optimization require an approved mapping effective for the
selected context and date.

Monetary marginal response stores both terms in the chain:

`d outcome / d reporting currency`
`= d outcome / d media input`
`× d media input / d local currency`
`÷ reporting-currency units per local-currency unit`.

Direct and halo views remain response decompositions. They do not inherit
channel cost economics unless a separately governed component-cost allocation
exists.

## G2A.5 optimizer gap analysis

The upstream optimizer is the reference for optimizing posterior response
distributions rather than a single fitted coefficient vector. Its optimizable
mask is analogous to this repository's activity-level planning eligibility,
and `cost_per_unit` is analogous to an approved cost mapping. Its custom
utilities and risk measures are the reference for future decision-risk
extensions.

Direct adoption is not currently appropriate because this product must resolve
several Ancestry-specific contracts before evaluating an allocation:

- market × activity governance and multi-outcome direct/halo pathways;
- monetary decisions separated from response-only quantity assumptions;
- an explicit, persisted counterfactual policy for demand capture, mediators,
  controls, events, and fixed activity;
- metric-specific incremental CPA and ROI with structured economics coverage;
- project-bundle approval, fingerprints, and invalidation behavior.

The local optimizer therefore remains custom, but candidate and current plans
are re-evaluated on paired posterior draws and persist the exact planning
objective, counterfactual policy, scenario plan, and governance fingerprints.

## Change control

When the pinned PyMC Marketing version changes:

1. Review the public adstock, saturation, multidimensional MMM, calibration,
   and optimizer APIs plus release notes.
2. Run the upstream numerical compatibility tests.
3. Update this matrix with adopted changes or explicit divergences.
4. Regenerate the lockfile and run the full repository gates.
