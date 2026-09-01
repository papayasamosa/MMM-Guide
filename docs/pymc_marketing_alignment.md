# PyMC Marketing alignment

Status: G2A.5 / Candidate A Search engine plus observed-mediator historical
capability and raw-PyMC lift-test adapter, reviewed 2026-09-01.

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

Context7's official PyMC-Marketing documentation was also queried for the
lift-test API. The indexed reference was `/pymc-labs/pymc-marketing` version
0.18.1; the repository remains pinned to 0.19.4 and the public method shape
was verified against the installed package separately.
- [PyMC v5.28.5 Censored distribution](https://github.com/pymc-devs/pymc/blob/v5.28.5/pymc/distributions/censored.py)
- [PyMC v5.28.5 NegativeBinomial distribution](https://github.com/pymc-devs/pymc/blob/v5.28.5/pymc/distributions/discrete.py)
- [PyMC v5.28.5 NUTS implementation](https://github.com/pymc-devs/pymc/blob/v5.28.5/pymc/step_methods/hmc/nuts.py)

For the 2026-08-20 UK readiness fit, the NUTS implementation's documented
diagnostic response was applied: unresolved post-tuning divergences remain a
validation blocker, and the remedial runs raise `target_accept` to 0.99 (DNA)
and 0.995 (Family History) while retaining the same PyMC model and
likelihood.  This is sampler adaptation, not a change to the business
estimand or production engine.

## Alignment matrix

| Area | Upstream reference | Repository implementation | Status |
|---|---|---|---|
| Geometric adstock | `GeometricAdstock` / `geometric_adstock`, with lag length, normalization, axis/dimension and convolution mode | Recursive geometric carryover in NumPy and PyTensor, reset at market boundaries | Numerically aligned for unnormalised finite histories when upstream lag length covers the history; compatibility test maintained |
| Adstock normalization | Finite-lag weights normalized by their sum | Infinite-geometric scale convention, multiplying by `1 - alpha` | Intentional divergence; retained for fitted-model continuity and documented in transformation tests |
| Saturation | Public saturation components, including Hill-family transforms | Explicit `x**S / (K**S + x**S)` Hill response in NumPy and PyTensor | Conceptually aligned; custom parameter naming and pathway integration |
| Media-domain scaling | Public MMM examples use documented input-domain conventions for adstock/saturation priors | Optional fixed positive-support-median per-channel numerical reparameterisation, persisted in `FHModelMeta` and replayed before adstock/Hill; raw media units and governed cost mappings remain unchanged | `CORE_PYMC_CUSTOM`; algebraically equivalent to the raw-domain response when `K` is transformed with the same scale |
| Transform/hierarchy identifiability ladder | Public adstock/saturation components and configurable priors | Diagnostic-only C0-C5 switches for fixed reference transforms and pooled-beta comparison, with support/recovery/divergence evidence persisted by `run_uk_transform_identifiability_experiment.py` | `CORE_PYMC_CUSTOM`; not a production default and cannot change channel scope, causal roles, or governance eligibility |
| Priors | Component-level configurable PyMC priors | Custom hierarchical priors for the multi-outcome pathway model | Informed by upstream; not API-equivalent |
| Multidimensional modelling | Named dimensions for channels, controls and other model dimensions | Explicit market, outcome, channel, pathway and control dimensions | Aligned design principle; custom likelihood and hierarchy |
| Control scaling | `MMM` exposes explicit control columns and scaling configuration for numerical model inputs | Model A standardizes raw context controls with a persisted mean/SD contract, replayed consistently in prediction and attribution; source units remain preserved | Custom numerical adaptation around the PyMC model; required because the hierarchical control block otherwise dominates the initial gradient |
| Attribution | Posterior contribution facilities around an MMM | Outcome-scale counterfactual and Shapley implementations with direct/halo governance | Intentional custom implementation |
| Response curves | Posterior response transformations | Outcome-scale steady-state counterfactual curves | Custom, with explicit representative-context semantics |
| Non-monetary inputs | Optimizer supports monetary budgets converted through channel `cost_per_unit` | Governed market × activity inputs; only cost-bearing decisions use market × channel × context mappings, while response-only quantities remain non-monetary | Aligned principle, broader governance/persistence contract |
| Calibration | `MMM.add_lift_test_measurements(df_lift_test)` with `channel`, `x`, `delta_x`, `delta_y`, `sigma` | `core.experiment_lift_test_mapping` maps governed experiment rows and composes a direct-primary, positive-lift Gamma observation term into the raw-PyMC Model A/Model C builders | `CORE_PYMC_CUSTOM`; semantically aligned for the supported scope, not a full `MMM` API wrapper; temporal/adstock and signed-effect calibration remain unsupported |
| Optimization | `BudgetOptimizer` evaluates posterior response distributions and supports channel masks, `cost_per_unit`, constraints, and custom/risk-aware utilities | Typed incremental objectives, activity-aware constraints, explicit counterfactual policies, mixed economics, and paired posterior re-evaluation of candidate versus current plan | Semantically aligned; custom implementation retained for multi-outcome pathways and governed mixed-input plans |
| Sequential optimisation | PyMC-Marketing budget-optimisation examples provide the upstream planning comparison, but do not provide this repository's carry-in-aware weekly replay contract | `core.optimization` uses `SequentialOptimisationContext` and the existing `core.sequential_simulation` kernel for T1 point-estimate SLSQP search with the O1 full plan-window objective; posterior uncertainty remains a separate sequential evaluation | `CORE_PYMC_CUSTOM`; exact weekly replay is required for carryover, phasing, controls, events, and terminal response, so the steady-state optimizer and sequential optimizer are explicit evaluation methods |
| Search mediation/capacity | PyMC `Censored`/`NegativeBinomial` primitives and PyMC-Marketing MMM transformations | `core.search_capacity` Candidate A linked latent-demand, hard-cap, capture-reconciliation and outcome-scale counterfactual contract; typed graph compiler extension | Custom linked PyMC engine; not native PyMC-Marketing. Candidate C is diagnostic-only, Candidate B is deferred, and Search planning/optimisation remain disabled |
| Observed Search mediation | PyMC `NegativeBinomial` likelihoods and named dimensions | `core.search_preparation` and `core.observed_mediation` retain separate FH/DNA spend and click identities, explicit coverage/structural-zero evidence, mediator-specific transform namespaces, and graph validation before the observed delivery model is built | Custom PyMC capability; not PyMC-Marketing-native. It does not fabricate branded demand, cap, organic/direct capture, or spend/delivery equivalence; historical use remains validation/sensitivity-only until identification and source gates pass |
| Sequential simulation | `GeometricAdstock`'s finite `l_max`-truncated convolution; forward-simulation notebooks prime that window by prepending `l_max` "warm-up" periods into the same array (no explicit carry-in state parameter) | `core.sequential_simulation`: an explicit `initial_state` carry-in scalar threaded through the repository's own already-divergent infinite-horizon recursive `geometric_adstock` (see the "Adstock normalization" row above), reconstructed from real historical media, never a warm-up-window prepend | Intentional divergence, consistent with the pre-existing infinite-horizon adstock divergence already recorded above - a warm-up-prepend would truncate the decay to a finite window not present in what was actually fit. Numerical equivalence with the existing batch replay is tested directly (`test_sequential_simulation.py::TestGoldenEquivalence`) |

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
