# REQ-SEARCH-002: Candidate A Search mediation and capacity engine

## Approval and traceability

This record implements the user-approved Search decision dated 2026-08-15.
Candidate A is the first production Search mediation/capacity formulation.
Candidate B is deferred. Candidate C remains a diagnostic/sensitivity
benchmark only. This approval authorises implementation and validation; it
does not approve Search estimates for official planning or optimisation.

This record depends on the governed Search identities in REQ-SEARCH-001 and
the graph-authoritative compiler in REQ-GRAPH-001. It supersedes only
REQ-SEARCH-001's deferred decision about the Search mathematics; it does not
change that record's object separation or provenance rules.

## Approved estimand and formulation

For each approved outcome definition, market, and period, Candidate A models
the Search state in this order:

```text
upstream media and approved controls
    -> latent branded-search demand D_t
    -> unconstrained Paid Search opportunity P*_t
    -> realised Paid Search delivery P_t under cap K_t
    -> captured demand C_t
    -> approved final outcome Y_t
```

The first implementation uses the structural hard-cap relationship
`P_t = min(P*_t, K_t)` after an approved spend-to-delivery or delivery-unit
translation. Organic Search capture and direct-navigation capture remain
separate quantities. The model must enforce, for every posterior draw and
counterfactual period:

```text
captured demand C_t = organic_t + direct_navigation_t + paid_t
unmet demand U_t = D_t - C_t >= 0
C_t + U_t = D_t
```

The cap is a capacity/decision constraint, never guaranteed spend or
delivery. Raising a cap that is not binding has no effect on realised
delivery, captured demand, or the final outcome. `P*_t`, `P_t`, `K_t`, and
`U_t` are distinct outputs. Unrealised potential is diagnostic only and is
never added to realised contribution.

The selected final-outcome likelihood and link are the existing approved
outcome contract: the current count path uses a Negative Binomial likelihood
with a log link. Candidate A adds a linked Search contribution to that
outcome predictor; it does not create a Search-specific final-outcome
likelihood or assume Net Bill Through is the default outcome.

Direct upstream-media effects remain a separate pathway. The realised
mediated Search effect is calculated from explicit outcome-scale
counterfactual predictions, and total realised media effect reconciles to
direct plus realised mediated effect at posterior-draw level before any
summary. Organic and direct-navigation capture may not be pooled with Paid
Search capture or counted twice.

## Governed objects and graph compiler scope

The implementation must consume the separate governed objects from
REQ-SEARCH-001: branded-search demand, Paid Search spend, Paid Search
delivery, Paid Search cap, organic Search capture, direct-navigation capture,
and residual Paid Search incrementality as a model output. A generic
`Brand Search`/`brand_search` variable is invalid.

The graph compiler may accept only the Candidate A structure explicitly
identified by the implementation's typed Search object bindings: upstream
intervention to branded-demand mediation, branded-demand to Paid Search
capture mediation, branded-demand to Paid Search capacity constraint, the
separate organic/direct capture relationships, and a separate direct
upstream-media-to-outcome pathway. The ordinary PyMC hierarchical engine
continues to reject mediated and capacity-constrained structures. Candidate
A is a separate, explicitly selected linked PyMC engine capability. Other
mediated, moderated, residual-interaction, or capacity structures continue
to fail closed.

## Hierarchy, priors, and engine boundary

Market and outcome parameters use the existing model's explicit pooling
architecture. Candidate A must record whether each demand, capture, and
outcome parameter is pooled, partially pooled, market-specific, or unpooled.
The initial linked implementation uses partial pooling where the existing
outcome architecture uses partial pooling; a different choice requires a
new approved decision.

Prior scales are configuration, not unexplained constants. A Candidate A
fit is not eligible for official use until prior-predictive checks and noisy
simulation-recovery evidence justify the selected scales and pooling
strength. The engine is custom linked PyMC code informed by the public
PyMC-Marketing MMM APIs; it must not claim that PyMC-Marketing natively
implements this bespoke censored Search graph.

## Identification and governance gates

Identification diagnostics must fail closed for official use when any of the
following is true: cap provenance is unresolved; the cap-to-delivery mapping
is unresolved; capture mappings are unresolved or collide; cap variation is
insufficient; non-binding support is inadequate; binding/non-binding status
cannot be separated; or a market is too sparse for the declared hierarchy.
Weak or absent cap variation is not repaired with a prior or a posterior
saturation parameter. A strong final-outcome fit does not make a weak Search
mediator eligible.

Candidate A remains exploratory/directional by default. Planning and Search
cap optimisation are disabled until all of the following are present and
approved: noisy parameter-recovery evidence, prior/posterior predictive
validation, identification diagnostics, consistency with scenario and
counterfactual contracts, and explicit model approval. Search-cap
optimisation is disabled by this record.

## Required evidence

The synthetic and model tests must cover cap never binding, sometimes
binding, frequently binding, upstream media changing latent demand,
organic/direct capture, high observed Paid Search association with low causal
incrementality, non-binding cap increases, weak/absent cap variation, and
sparse market support. Tests must prove posterior-draw reconciliation,
outcome-scale direct/mediated/total effects, cap binding probability and
unused capacity, and no double counting.

## Upstream references and gap analysis

The implementation is aligned to the pinned dependencies and the following
public references:

- PyMC `v5.28.5`, `pymc/distributions/censored.py` (`Censored`) and
  `pymc/distributions/discrete.py` (`NegativeBinomial`):
  https://github.com/pymc-devs/pymc/tree/v5.28.5/pymc/distributions
- PyMC-Marketing `v0.19.4`, public MMM implementation and transformations:
  https://github.com/pymc-labs/pymc-marketing/tree/0.19.4/pymc_marketing/mmm

Those upstream APIs provide Bayesian sampling, count likelihoods, adstock,
saturation, priors, posterior prediction, curves, calibration, and standard
optimisation. They do not provide this repository's governed Search object
bindings, the Candidate A latent-demand/capacity reconciliation, the
multi-stage causal graph compiler, or the fail-closed Search identification
and planning gates. Those pieces are custom, with equivalence and divergence
tests at the repository boundary.

## Affected modules

- `ancestry_mmm/core/search_capacity.py`
- `ancestry_mmm/core/search_decision_package.py`
- `ancestry_mmm/core/graph_model_compiler.py`
- `ancestry_mmm/core/causal_graph.py`
- `ancestry_mmm/core/persistence.py`
- `ancestry_mmm/core/hierarchical_model.py` or the selected linked-engine
  adapter boundary
- `docs/pymc_marketing_alignment.md`
- `docs/decision_log.md`

## Owner and status

**Owner:** Data Science / Platform engineering.

**Status:** Approved for implementation on 2026-08-15; planning and
optimisation eligibility remain disabled pending evidence and explicit model
approval.
