# Search mediation and capacity decision package (WP3)

Status: decision support only. No production mediated or capacity-constrained
graph edge is enabled by this package.

## Decision required

The repository still needs an approved production formulation for:

```text
upstream media
    -> branded-search demand / latent demand
    -> Paid Search realised delivery under a cap
    -> captured demand and unmet demand
    -> final Family History outcome
```

The exact decision required after this package is merged is:

> Select and approve one production Search mediation/capacity formulation
> (or explicitly reject all candidates and request another package), including
> its estimand, observed/latent/decision/derived quantities, cap likelihood,
> effect decomposition, prior/hierarchy, identification evidence, required
> data, posterior/planning outputs, and failure-state policy.

This is intentionally not chosen by the coding agent. REQ-SEARCH-001 keeps
latent-demand estimation, cap equations, cap-hit probability, unmet demand,
and joint upstream-media/cap optimisation out of the current production
contract.

## Governed objects and quantities

The candidates use the existing Search identities; they do not collapse them
into `Brand Search`:

| Quantity | Status in a candidate | Meaning |
| --- | --- | --- |
| `search_demand` / branded-search demand | latent or observed proxy | Upstream intent signal; not spend or delivery |
| `paid_search_spend` | observed or planned decision | Currency paid to the channel |
| `paid_search_delivery` | observed; model output in the capacity path | Clicks/impressions delivered, distinct from spend and cap |
| `paid_search_cap` | decision/constraint, possibly observed | Delivery or budget ceiling; never guaranteed spend |
| `organic_search_capture` | observed capture path | Unpaid search capture of demand |
| `direct_navigation_capture` | observed capture path | Direct navigation capture of demand |
| final outcome | observed response | Approved versioned Family History outcome |
| residual Paid Search incrementality | derived output | Never a raw source variable; must not duplicate `core.brand_search` |

In the synthetic fixtures, `paid_search_cap` is an exposure cap. A separate
approved decision is still needed for monetary caps, time-varying schedules,
and spend-to-delivery translation. Realised delivery is generated under the
cap; it is not supplied as an analyst-overwritten planning input.

## Candidate formulations

The following are deliberately explicit candidates, not approved business
decisions. In all equations, `t` indexes the canonical modelling period,
`X_t` is upstream media after the approved adstock/saturation transformation,
`K_t` is a cap decision, `O_t` is organic capture, `R_t` is direct-navigation
capture, and `Y_t` is the approved outcome.

### Candidate A — structural latent demand with hard censoring

Demand and the unconstrained Paid Search opportunity are:

```text
eta_D,t = alpha_D + f_media(X_t) + f_controls(Z_t)
D_t     = exp(eta_D,t)
P*_t    = q_P,t D_t
P_t     = min(P*_t, K_t)
C_t     = O_t + R_t + P_t
U_t     = D_t - C_t
```

Here `D_t` is latent demand, `P*_t` is latent unconstrained Paid Search
capture, `P_t` is realised Paid Search delivery, `C_t` is captured demand, and
`U_t` is unmet demand. The reconciliation is a hard invariant:
`C_t + U_t = D_t`; it is not permission to treat `U_t` as realised response.

One outcome-scale candidate is:

```text
log(mu_t) = alpha_Y + g_direct(X_t) + beta_C C_t + g_controls(Z_t)
Y_t ~ NegativeBinomial(mu=mu_t, alpha_Y_dispersion)
```

`g_direct` is the direct upstream-media path. The realised indirect/mediated
effect is the change in `beta_C C_t` under a defined intervention. The
unconstrained potential is a separate diagnostic obtained by replacing `P_t`
with `P*_t`; the unmet potential is the difference between unconstrained and
realised outcome response. Therefore:

```text
realised total = direct + realised mediated/captured
unconstrained potential = realised total + unrealised unmet potential
```

No cap binding is allowed to imply that the whole cap is spent. If `K_t >
P*_t`, the cap is non-binding and raising it must not change `P_t`, `C_t`, or
the outcome. If `K_t < P*_t`, unused cap remains possible if the latent
opportunity is below the cap after all upstream allocation.

Observed quantities are `X_t`, spend, delivery, cap where available, organic
and direct capture where measured, and `Y_t`. `D_t`, `P*_t`, and `U_t` are
latent/derived. `K_t` is a decision or governed observed constraint, depending
on the use case.

**Priors and hierarchy.** A possible implementation would use a positive
hierarchical prior for media response and capture rates, market/segment random
effects with partial pooling, a positive outcome response prior, and a
separate over-dispersion prior. These are candidate prior families only; the
production prior scale and pooling choice require approval and prior-predictive
checks.

**Identification/data support.** It needs cap variation, periods where the cap
is demonstrably non-binding, a governed cap-hit rule, enough upstream media
variation, and evidence separating organic/direct capture from Paid Search.
Without uncapped support, `D_t` and `P*_t` are weakly separated from `K_t`.
Without capture observations or experiments, direct and mediated effects can
remain observationally confounded.

**Posterior/planning outputs.** Required outputs are posterior draws for
`D_t`, `P*_t`, `P_t`, `C_t`, `U_t`, direct, realised mediated, unconstrained,
and total effects, plus cap-hit probability and binding status. Planning must
propagate posterior uncertainty through a proposed cap and must not overwrite
model-generated realised delivery.

**Graph/compiler representation.** It needs `search_demand` as a latent
`demand_capture` node, Paid Search spend as an intervention, the cap as
`capacity_or_cap`, organic/direct capture as distinct demand-capture nodes,
and explicit mediated/capacity edges into delivery and outcome. The current
compiler supports direct and cross-product-halo structures only; this
representation is therefore currently unsupported and must fail closed.

**Computation/failure states.** Joint latent states and censored likelihood
terms increase sampling cost and can produce funnels at low cap variation.
Block official use for missing/ambiguous cap provenance, no cap support, no
non-binding periods, unresolved capture mapping, definition breaks, failed
reconciliation, or an unsupported engine capability.

### Candidate B — probabilistic capture with cap-aware censoring

This candidate separates latent opportunity from stochastic capture:

```text
eta_D,t = alpha_D + f_media(X_t) + f_controls(Z_t)
D_t     ~ LogNormal(eta_D,t, sigma_D)
P*_t    ~ CaptureDistribution(D_t, q_t)
q_t     = logistic(eta_q,t)
P_t     = min(P*_t, K_t)
C_t     = O_t + R_t + P_t
U_t     = D_t - C_t
Y_t     ~ NegativeBinomial(mu_t, alpha_Y_dispersion)
```

`CaptureDistribution` must be selected in the approved model specification;
it could be a count model with an explicit cap/censoring likelihood, but this
package does not prescribe one. A cap-hit observation must contribute the
appropriate tail probability rather than be treated as an exact realised
count. A non-binding cap must remain a no-op in the counterfactual response
curve.

This formulation can represent noisy delivery, partial capture, and binding
probability more naturally than Candidate A, but it adds a latent stochastic
layer and requires more information to identify `q_t`, `D_t`, and cap effects.
It needs the same explicit direct/realised-mediated/unmet decomposition and
the same `C_t + U_t = D_t` reconciliation.

**Priors/hierarchy.** Candidate prior families are hierarchical demand and
capture intercepts/slopes, a positive or bounded cap-response scale, and a
separate dispersion prior. Market and segment pooling must be declared per
parameter; amplitude-only pooling must not be described as independent curves.

**Identification/data support.** It needs repeated cap-hit/non-hit regimes,
delivery/cap measurement with publication timing, and ideally experiments or
quasi-experiments that move upstream media independently of cap policy. A
single deterministic cap schedule cannot identify the stochastic capture
distribution.

**Posterior/planning outputs.** In addition to Candidate A outputs, planning
needs posterior predictive cap-hit and unused-cap probabilities, latent
delivery quantiles, and uncertainty-propagated captured/unmet demand. The
optimizer must receive cap decisions and return realised delivery as an
output.

**Graph/compiler and computation.** The same typed nodes and additional
mediated/capacity edges are required. A custom PyMC linked model and likely
custom likelihood/test machinery would be needed; standard MMM composition
alone is insufficient. Sampling cost and multimodality are higher than
Candidate A, especially with sparse cap hits.

**Failure states.** Block when cap-hit status is unavailable, the cap is
always binding or always non-binding, the delivery metric changes definition,
the censoring likelihood cannot be validated, or posterior predictive checks
fail to reproduce the observed cap-hit/delivery distribution.

### Candidate C — reduced-form benchmark / diagnostic sensitivity

The benchmark fits an outcome model with observed delivery and a cap-hit
indicator, for example:

```text
log(mu_t) = alpha_Y + b_X X_t + b_P P_t + b_H I(P_t ~= K_t) + g_controls(Z_t)
Y_t ~ NegativeBinomial(mu_t, alpha_Y_dispersion)
```

This can be useful as a benchmark or sensitivity view, and it is closer to
the currently supported direct compiler path. It cannot recover latent demand,
unmet demand, or a structural indirect effect. A post-hoc reallocation of
observed Paid Search association is not fitted mediation. It must therefore
remain diagnostic-only and planning/optimisation-disabled for the Search
capacity question.

## Synthetic recovery evidence

`ancestry_mmm.core.search_decision_package` provides deterministic forward
fixtures for six required regimes:

- cap never binds;
- cap sometimes binds;
- cap binds heavily;
- upstream media moves demand while cap limits capture;
- organic/direct channels absorb demand;
- demand and delivery are correlated while generator direction is known, with
  a high-association/low-incremental-capture case.

The tests verify:

1. Search object identities remain separate and latent/derived quantities are
   not presented as raw source columns.
2. `captured + unmet = latent` in every period.
3. Candidate A recovers latent demand, realised delivery, captured demand,
   unmet demand, and total outcome effect exactly under the known noiseless
   generator.
4. A raised cap that remains non-binding creates no additional delivery or
   captured demand.
5. Heavy binding produces positive unmet potential without adding it to the
   realised total effect.
6. High Paid Search association can coexist with low incremental capture
   response.

This is contract-level forward recovery, not a posterior parameter-recovery
study. It deliberately does not claim that any candidate is identified in
real UK data, does not select a production candidate, and does not enable
Search edges in the model compiler. The next approved implementation package
must add noisy simulation, posterior recovery, prior-predictive checks,
identification diagnostics, and engine-specific numerical validation for the
selected formulation.

## Upstream alignment and gap analysis

The repository's locked modelling dependencies are PyMC 5.28.5, PyTensor
2.38.3, ArviZ 0.23.4, and PyMC-Marketing 0.19.2 on Python 3.11 / 0.19.4 on
Python 3.12. The following official upstream references were consulted:

- [PyMC `Censored` source at v5.28.5](https://github.com/pymc-devs/pymc/blob/v5.28.5/pymc/distributions/censored.py)
  and its [API documentation](https://www.pymc.io/projects/docs/en/latest/api/distributions/censored.html),
  which provide censored likelihood semantics and require a distribution with
  `logcdf`; the implementation cautions that continuous censored
  distributions are likelihoods and need care for sampling.
- [PyMC `NegativeBinomial` API](https://www.pymc.io/projects/docs/en/v5.24.0/api/distributions/generated/pymc.NegativeBinomial.html),
  which supports a count outcome through `mu` and over-dispersion `alpha`.
- [PyMC-Marketing 0.19.2 MMM package](https://github.com/pymc-labs/pymc-marketing/tree/0.19.2/pymc_marketing/mmm)
  and [0.19.4 MMM package](https://github.com/pymc-labs/pymc-marketing/tree/0.19.4/pymc_marketing/mmm),
  including their public [0.19.2 MMM implementation](https://github.com/pymc-labs/pymc-marketing/blob/0.19.2/pymc_marketing/mmm/mmm.py)
  and [0.19.4 MMM implementation](https://github.com/pymc-labs/pymc-marketing/blob/0.19.4/pymc_marketing/mmm/mmm.py).

**What upstream supports:** standard Bayesian MMM construction, public media
transformations, priors, posterior prediction, response/curve analysis,
lift-test calibration, and budget optimisation.

**What remains custom:** a multi-stage Search graph with a latent demand
state, distinct organic/direct capture, a cap/censoring mechanism, posterior
direct/mediated/unmet decomposition, cap-hit probability, reconciliation, and
planning/compiler governance. Neither the current repository compiler nor
the pinned PyMC-Marketing MMM API is treated as natively providing those
bespoke semantics. The eventual implementation should use supported public
PyMC/PyMC-Marketing composition where it fits, with an explicit custom linked
model and equivalence/divergence/recovery tests for the remaining structure.

## Governance and implementation gate

Candidate evidence status is exploratory/decision-support only. It does not
change:

- which pathways are fitted, attributable, headline-approved, planning-
  eligible, or optimisation-eligible;
- the existing compiler fail-closed behavior for mediated/capacity edges;
- Search-object persistence, fingerprints, or model identity;
- the approved outcome registry or value definitions.

After this package is merged, implementation stops until the production
formulation decision above is recorded in an approved repository decision
record and a scoped implementation brief authorises the selected likelihood,
graph representation, posterior outputs, and planning/optimisation status.
