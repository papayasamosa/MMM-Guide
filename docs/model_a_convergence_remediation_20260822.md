# Model A convergence remediation — UK historical test

Status: diagnostic remediation complete; no production fit certified.

## Business question and estimand

The approved UK historical test asks whether the PyMC joint/shared hierarchical
MMM can identify media response for the three Family History NBT segments and,
separately, the two DNA kit NBT segments over the canonical Sunday–Saturday
window `2023-01-01` through `2025-04-06`, retaining 51 weeks of pre-window media
history for adstock carry-in.

The estimand is the posterior incremental outcome count on the original NBT
count scale under the approved media intervention, after the full log-link,
adstock, saturation, controls, seasonality, trend, and outcome hierarchy. It is
not a coefficient or a log-scale linear-predictor contribution.

## Evidence and root cause

The progressive diagnostic ladder identified the first material failure at the
media-response transform: the standardized linear and adstock-only stages
produced zero acceptance and divergences, while the Hill-saturation stage
removed the immediate numerical failure but saturated the tree-depth budget.
Adding the outcome-level shared hierarchy then worsened the geometry, especially
for Family History. The full raw-input model reached maximum treedepth and had
very low effective sample sizes in both products.

The evidence is consistent with a combination of:

- heterogeneous physical-input scales and sparse/flighted channels;
- weakly identified Hill `K`/`S` and adstock parameters, particularly for
  channels with only a handful of active weeks;
- outcome-level hierarchical response deviations in a one-market, three- or
  two-outcome fit; and
- trend, Fourier seasonality, weekly category-demand control, and media timing
  competing to explain the same limited time variation.

The UK frame has one market, 119 target rows, 51 retained history rows, 19 FH
channels / 18 DNA channels, and no active promotion observations. The current
fit graph had no active or exploratory cross-product pathway cells, so those
terms were not the source of the observed geometry.

## Diagnostic interventions

The following implementation changes are intentionally limited to technical
geometry remediation and are not an approval to alter the business model:

1. An all-zero promotion input now creates a deterministic zero `promo_coef`
   instead of a prior-only free random variable.
2. An optional `K_reference="nonzero_median"` uses the prepared frame's
   positive-week median as the weak Hill-scale reference for sparse flighted
   inputs.
3. An optional lognormal prior for `sigma_pool` removes the excessive near-zero
   tail of the half-normal pooling-scale prior while preserving the shared
   hierarchical response structure.

The candidate prior predictive check narrowed the near-zero pooling-scale tail,
but did not remove the high outcome-count tail. The candidate full-fit screens
were still invalid: Family History 2×100 had zero divergences but maximum-tree
warnings, R-hat 2.55 and minimum ESS 2.59; DNA 2×100 had 100 divergences,
maximum treedepth, R-hat 2.55 and minimum ESS 2.62. A later short Family History
screen also had 30 divergences and R-hat 3.59. These are diagnostic runs only.

## Engine and validation boundary

All runs used PyMC 5.28.5, PyTensor 2.38.3, and NUTS through the D-drive
MinGW-w64 compiler. No JAX, NumPyro, BlackJAX, PathMC, or Meridian fallback was
used. The local pinned PyMC/PyTensor APIs and source were inspected because the
configured Context7 MCP reference was unavailable in this environment; the
repository's required upstream-reference workflow therefore remains a follow-up
for any further material model-algebra change.

The 4-chain geometry screen, medium run, full convergence run, posterior
validation, attribution, and Search mediation Model B were not started because
the approved computational gate failed. Increasing treedepth or changing the
sampler would conceal rather than resolve this blocker.

## Reproducibility

Diagnostic artefacts are outside Git at:

`D:\Ancestry-MMM\test-artifacts\historical-model-a-convergence-20260822\`

The fresh branch was created from merged `origin/main` commit
`3f9e62983e414024f34571b8b3342b900280387e`. No real data, posterior artefact,
compiler binary, or PyTensor cache is part of the repository change.
