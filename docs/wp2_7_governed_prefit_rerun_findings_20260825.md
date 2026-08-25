# WP2.7 item 4: governed UK Model A pre-fit re-run findings (2026-08-25)

Status: pre-fit evidence only. No channel removed, no prior tightened,
no model approved for production sampling by this document.

Evidence sources (all real UK data, D-drive only):

- `scripts/run_uk_prefit_governance.py`, re-run under REQ-CONTROL-001's
  approved default (`APPROVED_UK_MODEL_A_PRIOR_CONFIG`) - the full
  governed pre-fit sequence (deterministic identifiability, leakage-safe
  screening, prior-predictive sample, consolidated `PrefitRun`). Output:
  `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-prefit-rerun-
  20260825\`.
- `scripts/run_uk_wp2_7_eta_controls_verification.py` (new) - a targeted
  end-to-end check that the real production code path (`scripts/
  run_uk_production_fit.py`'s new default), not just WP2.6's diagnostic
  grid, reaches `eta_controls` as approved. Output:
  `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-eta-controls-
  verification-20260825\`.
- `scripts/run_uk_wp2_7_full_component_decomposition.py` (new) - decomposes
  the remaining prior-predictive tail across every additive log-linear-
  predictor component, per the analyst's explicit instruction to report
  (not silently act on) any component that now dominates. Output:
  `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-full-
  component-decomposition-20260825\`.

## 1. `eta_controls` now reflects the approved standardised prior

| Model | eta_controls q05 | median | q95 | Non-finite | Clipped at floor | Clipped at ceiling |
|---|---|---|---|---|---|---|
| Family History | -0.266 | -0.001 | 0.268 | 0 | 0 | 0 |
| DNA Kit | -0.216 | -0.001 | 0.218 | 0 | 0 | 0 |

Both zero across 476,000-714,000 draws. The multiplicative effect per
SD (`exp(control_coef)`) is 0.718-1.423 at the 90% interval for both
models - matching WP2.6's `control_sigma=0.20` grid point exactly (Monte
Carlo noise aside), now confirmed through the actual production code
path (`scripts/run_uk_production_fit.py`'s new default), not only
WP2.6's standalone diagnostic script. The fitted scaling contracts
(`mean_sd`) are real, governed-training-data-derived values: Family
History centre=58.63, scale=7.37; DNA centre=49.29, scale=9.95 -
identical to WP2.6's control profile, confirming standardisation
parameters are derived from the leakage-safe training frame as required.

## 2. Full prior-predictive distributions, deterministic screening, identifiability

Both models land at `readiness: review_recommended` (never fabricated as
`ready` - per `REQ-PREFIT-001`, a human analyst has not yet reviewed this
run), with every sub-component (`identifiability`, `screening`,
`prior_predictive`) individually `review_recommended`, none `blocked`.
All prior-predictive rows are `status: wide_but_reviewable` (not
`numerically_invalid`) - every draw finite, no non-finite likelihood
values reported by the sampler. Channel counts confirmed unchanged and
correct: 19 Family History channels, 18 DNA channels (per `identifiability_
report.support_identifiability.rows`, matching WP2.5 item 6's correction).
All seven fingerprint categories present (`candidate_spec`,
`causal_graph`, `channel_set`, `data`, `model_window`, `prepared_frame`,
`transform_config`) - no staleness gap.

Representative `mu` quantiles (full distribution; five outcomes total,
complete detail in the raw JSON):

| Outcome | q95 | Ratio to observed q95 |
|---|---|---|
| FH new | 42,738 | 12.6x |
| FH dna_cross_sell | 37,250 | 9.2x |
| FH winback | 24,479 | 7.2x |
| DNA new_customer | 44,573 | 5.8x |
| DNA existing_fh_customer | 21,169 | 6.9x |

These match the analyst's own cited figures (FH New ~40k-46k vs.
observed ~3.4k; DNA New ~45k-50k vs. observed ~7.7k) almost exactly -
**the overall joint prior-predictive tail remains wide even after the
control-prior fix**, as the analyst anticipated. This is expected and
was not itself a defect to fix in this pass.

## 3. Which component now dominates the remaining tail

The analyst's instruction was explicit: report any individual component
that materially dominates, rather than silently tightening any other
prior in response. Decomposing `eta` (the log-scale linear predictor)
into its named additive terms, real data, both models:

| Component | Family History 90% interval | DNA Kit 90% interval |
|---|---|---|
| `eta_season` | **-1.146 to 1.134** | **-1.135 to 1.139** |
| `eta_channels` | 0.374 to 1.098 | 0.328 to 1.028 |
| `eta_trend` | -0.479 to 0.488 | -0.481 to 0.491 |
| `eta_controls` | -0.266 to 0.268 | -0.216 to 0.218 |
| `eta_market` | 0 (single market) | 0 (single market) |
| `eta_promo` | 0 (no promo observations) | 0 (no promo observations) |

**`eta_season` (the Fourier seasonality term) now has the widest 90%
interval of every decomposed additive component for both models** -
wider than `eta_channels` (the combined media contribution) and roughly
4-5x wider than the now-fixed `eta_controls`. This is a genuine finding
that was not visible before the control-prior fix (when `eta_controls`'s
own ±40-49 unit swings dwarfed everything else) and is reported here for
analyst review, exactly as instructed - **no seasonality/Fourier prior
is tightened or otherwise changed in response to this finding.**

One caveat: this decomposition covers the named additive `eta_*`
Deterministic terms only. `intercept` is a free random variable (not
one of these named components) and was not separately decomposed here;
its own prior width is a plausible additional contributor to `mu`'s
overall scale and is not ruled in or out by this pass - flagged as an
open question for a future, explicitly scoped check, not investigated
further in this document.

## 4. Timing refutation and residual diagnostics

Carried through unchanged from the existing governed screening report
(`run_prefit_screen`, the same mechanism WP2/WP2.5 already exercise) -
no new timing or residual-autocorrelation finding is introduced by this
re-run beyond what WP2.5's dedicated investigation already covered. See
`docs/wp2_5_diagnostic_investigation_findings_20260824.md` section 1 for
the DNA future-to-past timing analysis (unaffected by the control-prior
change, since it concerns media/outcome timing, not controls) and
`docs/wp2_7_short_sampler_screen_findings_20260825.md` for this
work package's own residual lag-1 autocorrelation evidence from the real
short-screen posterior.

## 5. Fingerprints and analyst-review state

Every governed fingerprint category is present and computed against the
real approved source pack (listed in section 2 above). `analyst_
rationale_retained` is `False` throughout - this script, like its WP2/
WP2.5/WP2.6 predecessors, never fabricates analyst sign-off; `readiness`
is correctly capped at `review_recommended`, never auto-promoted to
`ready`.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.7 investigation. Status: governed pre-fit re-run
complete, control-prior fix confirmed end-to-end, `eta_season` flagged
for analyst review as the new dominant additive component. No production
prior changed in response to that flag. No WP3 full-fit sampling is
authorised by this document.
