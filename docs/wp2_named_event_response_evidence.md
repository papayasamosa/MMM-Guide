# WP2: named-event response evidence (decision support)

Decision support only. No candidate approach below is enabled, selected,
or implemented by this package. No statistical response method is
approved by any requirement record, and nothing in `ancestry_mmm/**`
imports the evaluation code.

- Runner: `scripts/wp2_named_event_response/run_evaluation.py`
  (deterministic synthetic DGP grid, candidates S1-S5, metrics; `--smoke`
  mode for a reduced budget).
- Machine-readable results: `docs/wp2_named_event_response_results.json`
  (46 records: 32 main-grid single-market, 6 multi-market, 4 holdout,
  2 wrong-window, 1 oracle-fixed-profile, 1 wide-prior).
- Recorded CI run that produced these results: workflow `Tests` run
  `32349484897` (workflow_dispatch on branch
  `claude/wp2-named-event-evidence`, head `40e4ac7f`, job
  "Named-event response evidence", 2026-08-20).

## Pinned runtime

Python 3.12.3, PyMC 5.28.5, PyTensor 2.38.3, ArviZ 0.23.4, NumPy 2.4.6,
SciPy 1.18.0 (recorded inside `results.json`).

## Upstream references consulted

- Context7, library `/pymc-devs/pymc` (queried 2026-08-20): official
  PyMC documentation for `pm.Deterministic` and dims handling in custom
  model graphs. The evaluation uses only core PyMC/PyTensor
  distributions, `pm.sample`, and explicit PyTensor expressions - no
  PyMC-Marketing transformation API is consumed here, so no
  PyMC-Marketing behaviour is being measured.
- All event encodings obey the `REQ-EVENT-001` invariants: factual
  occurrence dates are never shifted, media adstock is never run
  backwards, and the event term is structurally separate from media,
  promotion and seasonality in every candidate.

## Method

Weekly grain, 156 weeks, three media channels (geometric adstock,
retention 0.7, Hill saturation), smooth two-harmonic Fourier
seasonality, linear trend, optional promotion term, Normal observation
noise (sigma 1.5). Every candidate shares the identical non-event
specification, so differences in the metrics are attributable to the
event encoding alone.

Scenarios (deterministic seeds): contemporaneous; anticipatory;
post-event; anticipatory+post-event; event+promotion; event+media
burst; event+seasonal peak; sparse repeats (3 occurrences); and a
multi-market scenario (two markets, shared and market-specific
structural variants as simplified Model A / Model C analogues).

Candidates measured:

- S1 fixed governed profile - fixed generic normal reference profile,
  one estimated scale.
- S2 low-dimensional parametric kernel - discretised normal kernel with
  estimated centre, width and amplitude.
- S3 regularised distributed basis - cubic B-spline over the lead/lag
  window, coefficients shrunk by a shared half-normal scale prior.
- S4 unconstrained weekly dummies - independent coefficients per
  relative week (the PRD-discouraged reference).
- S5 partially pooled basis - market-specific spline coefficients with a
  shared mean (multi-market only).

Sampling: NUTS, 300 tune / 300 draws, 2 chains, target_accept 0.9.

## Recorded observations (all figures are evidence, never verdicts)

1. Timing recovery: S2/S3/S4 recover the event shape and amplitude well
   on adequate-repeat scenarios (event RMSE 0.23-0.54; amplitude ratios
   roughly 0.6-1.1). S1's generic fixed profile consistently
   under-recovers amplitude (ratios 0.07-0.29): its shape cannot adapt
   to the true timing, and its `Normal(1, 0.5)` scale prior strongly
   shrinks the estimate - the prior-sensitivity evidence below confirms
   the prior, not the fixed-shape idea itself, is a large part of this.
2. Wrong-window sensitivity: fitting S2 with a contemporaneous-only
   support window on the anticipatory scenario degrades event RMSE from
   0.30 to 0.90; S4 degrades similarly (0.93). The support window is a
   material modelling decision.
3. Sparse repeats: with 3 occurrences, S2-S4 over-recover amplitude
   (ratios 1.3-1.7) relative to adequate repeats - consistent with the
   PRD's direction that flexible profiles need recurrence support.
4. Separation: on event+seasonal-peak the aligned peak is partially
   absorbed into the event/seasonality terms for all candidates
   (amplitude ratios 0.9-1.7; event RMSE ~1.6-1.9) - separation from an
   aligned seasonal bulge remains hard, exactly the case Part 7 says
   must stay exploratory.
5. Leakage: maximum media-coefficient bias across candidates is modest
   (roughly 0.11-0.51 across scenarios) and smallest for the
   regularised/pooled encodings.
6. Prior sensitivity: doubling the S2 width/amplitude prior scales on
   the anticipatory scenario changes event RMSE from 0.30 to 0.30 -
   low sensitivity at adequate repeats (sensitivity must be re-checked
   for sparse repeats before any decision).
7. Multi-market: the pooled S5 spline and shared S2 both recover well
   (RMSE ~0.27); S5's r-hat (1.09) sits at the edge of the recorded
   diagnostic threshold - a borderline case to watch, not a failure.
8. Computation: per-fit wall time 6-39 seconds on the CI runner; the
   full 46-fit grid completed inside the 90-minute job budget.

Two records carry `diagnostic_warning` (S5 pooled r-hat 1.092; S2
wrong-window divergence count) - recorded as-is.

## What this evidence does not do

- It does not select or rank a production method. A human decision is
  still required for the response structure, kernel/basis family,
  priors, pooling/heterogeneity, family-specific support windows,
  validation thresholds and planning-eligibility thresholds (see
  `docs/wp2_named_event_statistical_method_decision_package.md`).
- It does not validate against real UK data (real UK end-to-end data
  validation remains DEFERRED pending authorised source-data
  availability) and is not proof of real-UK identification.
- It does not run inside any optimisation loop, and it changes no
  production modelling code.

## Limitations

Synthetic Normal-noise DGP with a simplified media structure; single
chain only in `--smoke` mode (r-hat not computable there, recorded as
null); no negative-binomial scenario; S2's kernel is symmetric (skewed
timing shapes are not represented); fold/stability runs use fixed
seeds only.
