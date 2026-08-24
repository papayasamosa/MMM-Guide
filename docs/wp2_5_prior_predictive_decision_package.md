# UK Model A prior-predictive decision package (Work Package 2.5)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.
No production prior was changed to produce the evidence in this
document.

## Decision required

WP2's real UK governed pre-fit evidence (`docs/model_a_convergence_
remediation_20260822.md`'s successor evidence run, 2026-08-24) found the
prior-predictive outcome-scale distribution implausibly wide for every
fitted outcome: q95 predictions around 1.2-1.25 billion against observed
weekly outcomes in the thousands, for both the Family History and DNA
kit joint/shared hierarchical models. A human analyst reviewed this
evidence and did not approve the candidate for WP3 production sampling,
directing a bounded diagnostic investigation (this package) before any
further step.

The exact decision required after this package is reviewed is:

> Select and approve one production remedy for the log-linear-predictor
> term(s) identified below as dominating the implausible prior-predictive
> tail (or explicitly reject all candidates and request another
> package). This is a production statistical-prior change and is not
> made by this package or by the coding agent that produced it.

## Evidence: which term dominates

`core.diagnostics.prior_predictive_summary` gained an additive, opt-in
`component_var_names` parameter (WP2.5) that samples each named additive
term of `core.hierarchical_model.build_fh_hierarchical_model`'s
log-linear predictor `eta` from the model's own declared priors,
alongside `y_obs` - a pure read-only exposure (`pm.Deterministic`
wrapping of quantities the model already computes; no prior, coefficient,
or computed value changes). Run against the real approved UK source pack
(`D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3`,
`scripts/run_uk_wp2_5_diagnostics.py`), the per-component prior-predictive
quantile ranges (500 draws, seed 20260824) were:

| Component | Family History q05 / q95 | DNA kit q05 / q95 |
|---|---|---|
| `intercept` | 6.02 / 9.24 | 5.85 / 9.30 |
| `eta_trend` | -0.48 / 0.50 | -0.48 / 0.50 |
| `eta_season` | -1.14 / 1.14 | -1.15 / 1.15 |
| `eta_market` | 0 / 0 | 0 / 0 |
| `eta_promo` | 0 / 0 | 0 / 0 |
| `eta_channels` | 0.38 / 1.11 | 0.33 / 1.02 |
| **`eta_controls`** | **-50.4 / 49.5** | **-42.0 / 41.6** |
| `mu` (outcome scale) | 1e-06 / 1e+09 | 1e-06 / 1e+09 |
| `alpha` (NegBinom dispersion) | 3.6 / 46.6 | 3.5 / 44.4 |

`eta_market` and `eta_promo` are exactly zero for this run (a single-market
UK fit with an all-zero promotion input at this window - both correctly
resolve to deterministic zero, not a finding). Every other component's
prior-predictive range is modest (`intercept` is well-calibrated at
`log(mean(Y))` by construction; `eta_trend`/`eta_season`/`eta_channels`
are all within roughly ±1 log-unit). `eta_controls` is the outlier by a
wide margin - a swing of roughly ±50 log-units, against `mu = exp(eta)`,
easily explains a q95 in the billions once combined with the other
terms and the clip at `1e9`.

This is on the *log* (eta) scale, additively comparable across
components (they sum to `eta` before `mu = exp(eta)`); it is not itself
a claim about which raw control variable is responsible, only that the
controls block as a whole is the dominant term.

## Why this is a modelling and governance question, not an engineering one

`eta_controls` (`core.hierarchical_model`'s `control_coef` block, both
the outcome-level and shared-control contributions) uses a fixed
`Normal(0, control_sigma=0.5)` coefficient prior applied to the
**raw, unscaled** control values by default. Work Package 1 of this same
coding programme found and gated an *unconditional* centring/scaling
step for controls (`core.control_scaling.fit_control_scaling`) off by
default, specifically because turning it on silently changes the
coefficient prior's implied meaning with no compensating recalibration
and no existing approval (`AGENTS.md`: "Standardising a predictor while
leaving the same coefficient prior is not automatically a prior-neutral
numerical reparameterisation"). That WP1 fix correctly restored this
repository's pre-existing production default (raw, unscaled controls)
rather than inventing new unapproved statistical policy.

This package's evidence shows that pre-existing default *itself* now has
a real, measurable problem: a `Normal(0, 0.5)` prior applied to a raw
category-demand/context control whose observed magnitude is large (e.g.
weekly category-demand counts, which - unlike a 0-1 indicator - are not
naturally order-one) implies enormous swings in `eta` at the prior stage,
because the prior was never calibrated against that control's actual
scale. Both the "leave raw controls unscaled" status quo and "turn
scaling on with the same prior" (WP1's already-rejected default) share
the same underlying defect from different directions: neither
recalibrates the prior to the actual chosen representation. Deciding
which control(s) are responsible, and which remedy is appropriate, is a
statistical-prior decision requiring domain judgement about what an
"effect per unit of category demand" (or per standard deviation, or per
some other governed unit) should plausibly look like - not something
inferable from this diagnostic alone.

## Candidate remedies

None of the following is selected, approved, or implemented by this
package.

1. **Enable the existing gated control-scaling switch
   (`prior_config["enable_control_scaling"] = True`) *and* recalibrate
   `control_sigma` for the standardised representation.** Centring/
   scaling alone (without a prior change) is not prior-neutral (see
   above); this option requires deliberately choosing a new
   `control_sigma` appropriate to "effect per unit-SD", with a stated
   justification, not merely flipping the existing off-by-default
   switch.
2. **Keep raw controls, but derive `control_sigma` from each control's
   own observed scale** (e.g. a per-control prior SD proportional to
   `1 / typical_magnitude`, computed at build time similarly to how
   `intercept_mu` is already derived from `log(mean(Y))`). Keeps the
   "effect per raw unit" interpretation but requires a governed,
   documented derivation rule rather than one global constant.
3. **Keep the current default entirely unchanged**, on the basis that
   this is prior-predictive-only evidence (no posterior, no data
   likelihood involved) and a wide prior-predictive tail alone does not
   necessarily block a well-identified posterior once the likelihood is
   engaged - accepting the wide prior-predictive geometry as tolerable
   for this candidate.
4. **A different, explicitly-justified control-prior family** (e.g.
   regularising/shrinkage priors, or bounding `eta` more tightly upstream
   of the existing numerical `1e9` clip) if domain review determines
   neither (1) nor (2) is appropriate.

## What this package does not decide

- It does not identify *which specific control column(s)* dominate the
  `eta_controls` swing - that would require per-control component
  draws, not requested by this pass, and is a natural follow-up once a
  remedy direction is chosen.
- It does not claim the wide prior-predictive tail by itself proves the
  candidate cannot converge in a full posterior fit - `docs/model_a_
  convergence_remediation_20260822.md`'s existing divergence evidence
  (6 Family History / 14 DNA divergences on the current reference
  geometry) is separate evidence, already recorded, not restated here.
- It does not change `control_sigma`, `enable_control_scaling`, or any
  other `prior_config` default.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.5 investigation. Status: evidence supplied, decision
pending. `core.hierarchical_model.build_fh_hierarchical_model`'s control
prior remains unchanged pending review.
