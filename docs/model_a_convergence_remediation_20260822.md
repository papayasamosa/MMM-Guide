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

**WP2.8 reconciliation (2026-08-25):** "4-chain geometry screen" and
"medium run" above were originally envisaged as intermediate stages
between a short probabilistic screen and the full posterior. A
repository-wide review conducted for WP2.8 (docs, scripts, `docs/
approved_requirements/`, `docs/decision_log.md`, and the complete git
history of this document) confirmed neither stage was ever given a
governed or reproducible sampler configuration (draws/tune/chains/
target_accept) anywhere - they exist only as the descriptive names in
the sentence above, unchanged since this document was first written.
The approved `docs/approved_requirements/REQ-PREFIT-001.md` workflow
does not require them either: it goes directly from "optional short/
approximate probabilistic screening" to "full production PyMC
posterior." The analyst reviewed this finding
(`docs/wp2_8_missing_sampler_configuration_decision_package_20260825.md`)
and decided **not** to formalise new intermediate sampler
configurations solely to implement this historical wording. These two
stage names are retained here as a record of what was originally
envisaged, but are not mandatory workflow gates and require no REQ
record to skip. `REQ-PREFIT-001`'s own governed sequence - candidate
specification, static readiness, deterministic pre-fit, analyst review,
prior predictive, optional short screen, full posterior, post-fit
validation - remains authoritative.

## Work Package 1 correction (2026-08-24): undocumented control-scaling reconciled

This PR's own diff also added an unconditional, always-on control/outcome-
control centring-and-scaling step (`core.control_scaling.fit_control_
scaling`, called unconditionally from `core.hierarchical_model.build_fh_
hierarchical_model`) that this document did not mention alongside the three
interventions listed above. Standardising a control while leaving its
coefficient prior (`Normal(0, control_sigma)`) unchanged is not a
prior-neutral reparameterisation — it changes the prior's implied meaning
from "effect per raw unit" to "effect per unit-SD" with no compensating
recalibration, and no `docs/approved_requirements/REQ-*` record or
`docs/decision_log.md` entry approved it as a production change.

This has been corrected: control scaling now follows exactly the same
gated, default-off contract as the three interventions above and the other
undocumented gated switches noted below (`core.hierarchical_model.
_resolve_control_scaling`, `prior_config["enable_control_scaling"]`,
default `False`). With the default off, `X_controls`/`outcome_controls`
pass through unscaled and the coefficient prior's implied meaning is
unchanged from this repository's pre-existing behaviour. A consequent
non-neutral missing-control default in `core.predict.steady_state_
outcome_response` (a raw-value-0.0-then-centred default for a control
absent from a reference/scenario context, rather than the documented
"reference/recent-average levels" — the scaled value 0.0) was fixed in
`core.control_scaling.apply_control_mapping_scaling` at the same time;
it was reachable only when the scaling experiment was enabled, so this
fix is a correctness improvement to that diagnostic path, not a change
to the current production default.

The same review additionally found `media_input_scale_method`,
`K_reference="nonzero_median"` (already listed above as intervention 2),
`fixed_decay_rate`/`fixed_hill_K`/`fixed_hill_S`, and `pooled_beta_
reference` all live inside `build_fh_hierarchical_model` itself, each
correctly gated off by default and reachable only from `scripts/run_uk_
transform_identifiability_experiment.py` (a self-identified diagnostic
harness) — never from `application.model_fit_service`, the production
entry point. `media_input_scale_method="positive_median"` is verified as
a genuine numerical reparameterisation (the Hill ratio `x/K` is scale-
invariant, and the Gamma prior on `K` rescales within its own family, so
the induced prior on original-units `K` is unchanged). The remaining
switches change production statistical behaviour if ever enabled and
have no citable approval; they are recorded here as existing,
inert-by-default diagnostic tooling rather than removed, consistent with
this document's own framing of the three listed interventions - but any
future change turning one on by default requires the same authority
this document itself lacks for control scaling.

## Reproducibility

Diagnostic artefacts are outside Git at:

`D:\Ancestry-MMM\test-artifacts\historical-model-a-convergence-20260822\`

The fresh branch was created from merged `origin/main` commit
`3f9e62983e414024f34571b8b3342b900280387e`. No real data, posterior artefact,
compiler binary, or PyTensor cache is part of the repository change.
