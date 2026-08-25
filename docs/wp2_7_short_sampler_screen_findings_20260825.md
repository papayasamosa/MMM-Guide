# WP2.7 item 6: short Bayesian sampler screening stage findings (2026-08-25)

Status: screen evidence only. **This does not authorise the full WP3
production NUTS run.** Per `docs/approved_requirements/REQ-PREFIT-001.md`,
"a short screen does not establish production convergence." No media
prior, adstock, Hill saturation, pooling, channel selection, causal role,
or fold policy was changed to produce this evidence - the only
difference from the prior production default is REQ-CONTROL-001's
control-prior change, which is now that default.

Evidence source: `scripts/run_uk_wp2_7_short_sampler_screen.py`, run
against the real approved UK source pack. Sampler configuration is the
repository's own existing short-screen precedent (not invented for this
document): `--draws 100 --tune 150 --chains 2 --target-accept 0.95`,
matching `scripts/run_uk_transform_identifiability_experiment.py`'s CLI
defaults and the same configuration `docs/model_a_convergence_
remediation_20260822.md` already used for this exact purpose ("Family
History 2x100", "DNA 2x100"). Raw output (posterior trace + full
diagnostics JSON, no source rows) is at `D:\Ancestry-MMM\test-artifacts\
historical-model-a-wp2-7-short-sampler-screen-20260825\`.

**A note on how this evidence was produced**: the first attempt at this
screen ran under a pure-Python PyTensor fallback (this machine's C
compiler toolchain was missing Python development headers) and consumed
several hours of CPU time per model with no chain completions - a
genuine operational obstacle, not a modelling one. The analyst was
consulted mid-run; the chosen fix was to recreate this worktree's virtual
environment against a `uv`-managed CPython 3.12.13 build (which includes
headers), keeping the exact same dependency-lock resolution
(`pymc-marketing==0.19.4`, same `python_version >= '3.12'` branch the
project's `pyproject.toml` already pins). With native compilation
restored, both models' real short screens completed in **under four
minutes of sampling time combined**. This is a one-time local-environment
fix with no bearing on the deployed Streamlit app (which does not depend
on this worktree's `.venv` or this diagnostic script) and does not change
any modelling behaviour - `REQ-CONTROL-001`'s prior-config change is pure
NumPy/PyMC model definition, correct and portable regardless of whether
PyTensor compiles or falls back to pure Python.

## Headline convergence

| Model | R-hat max | ESS bulk min | ESS tail min | Divergences | BFMI (both chains) | Max tree depth observed | Draws at max tree depth |
|---|---|---|---|---|---|---|---|
| Family History | 1.191 | 9.0 | 13.7 | **0** | 1.073, 1.253 | 8 (of 10 configured) | 0 |
| DNA Kit | 1.089 | 54.7 | 30.6 | **0** | 0.974, 0.940 | 7 (of 10 configured) | 0 |

Neither model meets a production convergence bar (R-hat should be
<1.01, ESS should comfortably exceed 100 per chain for a real
production run) - this screen does not certify either model as fit-
ready, and is not intended to. But this is a materially different
picture from the pre-WP2.7 baseline recorded in `docs/model_a_
convergence_remediation_20260822.md`, which found (under a different
diagnostic-intervention configuration, at the same 2x100 draws):
Family History R-hat 2.55 with maximum-treedepth warnings and min ESS
2.59; DNA 100 divergences, maximum treedepth, R-hat 2.55, min ESS 2.62;
a later short Family History screen with 30 divergences and R-hat 3.59.
**This screen shows zero divergences for both models, no draws at
maximum tree depth for either model, and R-hat below 1.2 for both** -
a substantial, real improvement, though still short of convergence.

## Where the remaining pathology concentrates

Grouping every sampled parameter's R-hat by family (category-demand
control vs. Hill/adstock parameters, and sparse vs. non-sparse channels
per WP2.5's classification) directly answers the analyst's question:

| Model | Parameter group | n params | R-hat max | R-hat mean |
|---|---|---|---|---|
| FH | category-demand control (`control_coef`) | 1 | **1.025** | 1.025 |
| FH | all Hill/adstock (`hill_K`, `hill_S`, `decay_rate`, `mu_channel`) | 76 | **1.128** | 1.012 |
| FH | sparse-channel Hill/adstock | 24 | 1.128 | 1.016 |
| FH | non-sparse-channel Hill/adstock | 52 | 1.091 | 1.010 |
| DNA | category-demand control (`control_coef`) | 1 | **1.000** | 1.000 |
| DNA | all Hill/adstock | 72 | **1.045** | 1.008 |
| DNA | sparse-channel Hill/adstock | 20 | 1.034 | 1.005 |
| DNA | non-sparse-channel Hill/adstock | 52 | 1.045 | 1.009 |

**The category-demand control is now well-behaved** - R-hat 1.025 (FH)
and 1.000 (DNA), both comfortably better than every Hill/adstock group.
This is direct evidence that REQ-CONTROL-001's fix worked as intended:
the control is no longer a source of sampling pathology.

**The worst-converging individual parameters are all Hill/adstock**,
not concentrated specifically in sparse channels over non-sparse ones
(sparse and non-sparse group means are similar - FH: 1.016 vs. 1.010;
DNA: 1.005 vs. 1.009):

- FH worst: `decay_rate[uk_influencer]` (1.128, sparse/weak channel per
  WP2.5), `decay_rate[uk_bvod]` (1.091, not sparse),
  `mu_channel[uk_midfunnel_display]` (1.044, not sparse).
- DNA worst: `mu_channel[uk_brand_tv]` (1.045, not sparse),
  `decay_rate[uk_brand_tv]` (1.035, not sparse), `hill_S[uk_radio]`
  (1.034, sparse/weak channel per WP2.5).

**Conclusion: the remaining convergence pathology is a Hill/adstock
geometry issue, broadly distributed across both sparse and non-sparse
channels - not narrowly a sparse-channel problem, and not the
category-demand control.** This is consistent with `docs/model_a_
convergence_remediation_20260822.md`'s own root-cause analysis
("weakly identified Hill K/S and adstock parameters... competing to
explain the same limited time variation") and with WP2.5/WP2.6's
already-flagged, not-yet-resolved transformation-sensitivity/collinearity
findings. **No adstock, Hill saturation, or pooling change is made in
response to this finding** - per the analyst's explicit WP2.7 scope
boundary, this is reported for review, not acted on.

## Posterior predictive behaviour and residual diagnostics

In-sample fit (posterior mean vs. actual, on this short screen's draws
only - not a converged posterior):

| Model | Outcome | R-squared | MAPE % |
|---|---|---|---|
| FH | new | 0.019 | 13.1% |
| FH | dna_cross_sell | 0.459 | 20.9% |
| FH | winback | 0.297 | 26.4% |
| DNA | new_customer | 0.639 | 32.4% |
| DNA | existing_fh_customer | 0.498 | 40.2% |

Posterior-predictive 90%-credible-interval coverage is close to nominal
for every outcome (90.8%-93.3% observed against a 90% target) - the
predictive intervals are not badly miscalibrated even at this short,
non-converged screen.

Residual lag-1 autocorrelation is positive for every outcome (FH:
0.29-0.42; DNA: 0.16-0.22) with Durbin-Watson below 2 throughout
(0.95-1.67) - the model is leaving some temporal structure
unexplained, consistent with the known open trend/seasonality/media-
timing questions from WP2.5's fold-policy and transformation-sensitivity
findings, not a new finding introduced by this screen.

One plausibility flag per model, both for already-known very-weak-
support content-marketing channels (`uk_fh_content_marketing`,
`uk_dna_content_marketing`): each channel's fitted half-saturation point
sits far below its lowest observed non-zero spend, i.e. the channel
looks fully saturated across its entire (very sparse) observed range -
expected given WP2.5's sparse-channel review already flagged both as
very_weak support, not a new problem.

## What this does and does not establish

- **Establishes**: the control-prior fix (REQ-CONTROL-001) measurably
  improved sampler behaviour relative to the pre-WP2.7 baseline (zero
  divergences vs. up to 100; no max-treedepth hits vs. hitting the cap;
  R-hat below 1.2 vs. 2.55-3.59), and the category-demand control
  parameter itself is no longer a source of pathology.
- **Does not establish**: production convergence for either model. Both
  still fail standard convergence thresholds (R-hat, ESS), and the
  remaining pathology traces to Hill/adstock parameters this work
  package was explicitly scoped not to touch.
- **No WP3 full-fit NUTS run is authorised by this document.**

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.7 investigation. Status: short-screen evidence
supplied for review. No further sampler-configuration or model-geometry
change is made by this document.
