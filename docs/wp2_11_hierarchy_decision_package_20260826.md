# WP2.11 Segment-Hierarchy Decision Package (2026-08-26)

## Purpose

This package completes the evidence gathering authorised by WP2.11
(`docs/decision_log.md`, `REQ-HIERARCHY-001`) for whether the current
Model A per-channel response-strength hierarchy (`sigma_pool[channel]`)
should remain the production default, move to **H1** (complete pooling of
channel response strength across outcomes), move to **H2** (one shared
scalar `sigma_pool_global`), or require another explicitly approved
option.

**This package makes no production decision.** It records the evidence
gathered, states what is and is not yet available, and recommends what
evidence is still needed. A hierarchy-default change requires a separate,
explicit analyst decision record.

## Candidate identities

All four candidates below were fit from the same governed frame:
`RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY`-eligible historical UK pack,
`window_role=historical_test_common_window`,
`use_mode=historical_test_non_production`, 2023-01-01 through 2025-04-06
(119-week estimation window,
`docs/specification_authority.md`), `APPROVED_UK_MODEL_A_PRIOR_CONFIG` as
the shared base prior configuration, identical outcome catalogue
(`fh_gsa_new` / `fh_gsa_dna_cross_sell` / `fh_gsa_winback` for family
history; the DNA kit catalogue for `dna_kit`), identical causal graph
(`None` — no mediation structure engaged for either product's Model A
fit), identical media/outcome pathways, activity definitions, and NBT
completeness metadata, and identical transformations. `coverage_matrix_
fingerprint` `4c118bbe2a5e9a6b510f3c59e5acc582adc88495674febb485294eb53
0970092` is shared across the recorded H1/H2 production-fit reports,
confirming the candidates were fit against the same governed coverage
matrix, not independently re-derived data.

| Candidate | Mechanism | Prior-config flag | Status |
|---|---|---|---|
| **Current** | Per-channel `sigma_pool[channel]` hierarchy (production default) | none set (baseline `APPROVED_UK_MODEL_A_PRIOR_CONFIG`) | Certified production default, unchanged by this package |
| **H1** | Complete pooling of channel response strength across outcomes — outcomes remain separate, only the response-strength hierarchy is removed | `pooled_beta_reference=True` | Authorised segment-preserving challenger (WP2.11 Decision 3) |
| **H2** | One shared scalar `sigma_pool_global` replaces per-channel `sigma_pool[channel]`; `z_offset[outcome,channel]` stays free | `shared_pooling_scale=True` | Authorised diagnostic-only challenger, requires a further analyst decision before any production use (`REQ-HIERARCHY-001`) |
| **Overall challenger** | WP2.10's single combined-outcome challenger per product | — | Retained as a robustness comparator only, per WP2.11's explicit instruction; not a segment-preserving candidate |

Full posterior fits used `chains=4, draws=2000, tune=1000,
target_accept=0.9` (current used `target_accept=0.95` in the recorded
comparison run below — noted, not silently normalised away). Every fit
ran in this environment's pure-Python PyTensor fallback (no C compiler
available; `g++`/`gcc` absent from `PATH`), confirmed not to bias
convergence diagnostics themselves, only wall-clock time.

## Reconstruction tier and its limitation

**No out-of-sample fold-refit backtest evidence is available for any
candidate in this package.** This is a genuine, disclosed gap, not an
oversight:

- The historical pack has no registered `SourceVersion` upload-timing
  history, so `POINT_IN_TIME_SOURCE_RECONSTRUCTION` cannot be validly run
  against it (WP2.9/WP2.10 finding, unchanged). Only the weaker
  `RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY` prepared-frame fold-refit
  tier was ever in scope here.
- A current-hierarchy prepared-frame fold-refit run (`scripts/run_uk_
  wp2_11_prepared_frame_backtest.py --prior-config-mode current`,
  `n_folds=3`) was started 2026-08-26 and **terminated before completion**
  after a targeted single-fold probe found:
  - **Inadequate per-variable data support in fold 1's training window**
    (the smallest, earliest expanding-window slice, 72 weeks): several
    channels had as few as 2 non-zero weeks out of 72
    (`uk_fh_content_marketing`, `uk_influencer`, `uk_radio`); several more
    had fewer than 25 (`uk_podcast_audio`=5, `uk_tv_sponsorship_vod`=5,
    `uk_fh_midfunnel_social`=8, `uk_midfunnel_display`=10, `uk_midfunnel_
    olv`=17, `uk_tv_sponsorship_linear`=23, `uk_avod`=24, `circulation`=25).
  - **Sampler geometry consistent with a stiff/strained posterior** on
    that same fold: a short real-NUTS probe (draws=20, tune=30, chains=1)
    showed tree depth pinned at 8-9 (near the default max of 10), a step
    size frozen at 0.00946 across the whole tuning phase, and a mean of
    ~396 gradient evaluations per draw (up to 511) — none of this was a
    literal divergence in the short probe, but the pattern is the
    signature NUTS produces when compensating for difficult curvature
    with tiny steps and long trajectories.
  - Both findings are properties of **this fold's own truncated training
    window**, not of the candidate hierarchy being tested — the same
    fold-1 slice would affect every candidate's fold-refit fit equally,
    since it is the fold-construction/data layer, not the hierarchy
    parameterisation, that produces it.
- **The current UK activity data is, as of 2026-08-26, under separate
  analyst review** for suspected upstream source-to-model mapping issues
  that could plausibly explain some of the sparse-channel findings above.
  Per that explicit instruction, this package does **not** treat the
  fold-1 finding as evidence against any hierarchy candidate, does **not**
  derive a support threshold from it, and does **not** revise the
  fold-construction/minimum-training-window policy from it. It is
  recorded here purely as a disclosed reconstruction-tier limitation:
  *no fold-refit backtest evidence exists for any candidate in this
  package*, and none should be assumed.
- New per-fold data-support and live sampler-geometry instrumentation
  (`core.fold_data_support`, `core.fit_progress`, wired into
  `application.fold_refit_service` via a new optional `on_progress_line`
  parameter) now exists so that, once the data review concludes, a
  re-attempted fold-refit backtest will report this evidence live instead
  of the run needing to be probed and terminated blind, as happened here.

## Sampler geometry and convergence evidence (full posterior fits)

Source: `D:\Ancestry-MMM\test-artifacts\wp2_11_convergence_comparison.json`,
computed directly from each candidate's saved `posterior.nc` trace via
`az.rhat`/`az.ess`/`az.bfmi` and the trace's own `sample_stats`. All runs
`n_chain=4, n_draw=2000`.

### Family History (`family_history`)

| Candidate | Divergences (by chain) | R-hat max | ESS bulk min | ESS tail min | BFMI min | Mean tree depth | Mean accept rate |
|---|---|---|---|---|---|---|---|
| Current (`target_accept=0.95`) | 13 (3,2,4,4) | 1.0029 | 1332.2 | 1456.9 | 0.895 | 6.00 | 0.9468 |
| H1 | **0** (0,0,0,0) | 1.0031 | 1266.5 | 1773.7 | 0.9526 | 5.06 | 0.9032 |
| H2 | 98 (18,63,16,1) | 1.0068 | 823.8 | 354.6 | 0.9058 | 5.97 | 0.8845 |
| Overall challenger | 0 (0,0,0,0) | 1.0024 | 3519.8 | 4106.5 | 0.9063 | 5.00 | 0.9054 |

### DNA kit (`dna_kit`)

| Candidate | Divergences (by chain) | R-hat max | ESS bulk min | ESS tail min | BFMI min | Mean tree depth | Mean accept rate |
|---|---|---|---|---|---|---|---|
| Current (`target_accept=0.95`) | 46 (15,7,6,18) | 1.0029 | 2181.6 | 1095.0 | 0.8755 | 5.99 | 0.9422 |
| H1 | 35 (**0,34,0,1**) | 1.0062 | 989.1 | 366.4 | 0.868 | 4.99 | 0.8956 |
| H2 | 369 (63,77,149,80) | 1.0094 | 525.8 | 131.8 | 0.8509 | 5.97 | 0.8200 |
| Overall challenger | 0 (0,0,0,0) | 1.0028 | 3789.5 | 3561.8 | 0.9513 | 4.31 | 0.9087 |

**Reading the DNA H1 per-chain pattern** (0, 34, 0, 1): the divergences
are concentrated almost entirely in one chain, not spread evenly across
all four. This is more consistent with a localised mode-switching episode
in that one chain than with a uniform funnel affecting the whole
posterior geometry — but this is a descriptive read of the pattern, not a
statistical test, and is recorded as an open item rather than a resolved
finding (see "Unresolved items" below).

### `sigma_pool_global` posterior (H2)

H2's diagnostic purpose was to test whether the per-channel pooling
constraint is genuinely over-parameterised, and whether
`uk_dna_performance_display` in particular would show real heterogeneity
once every channel's `z_offset` is free to differ per outcome without a
channel-specific exception (WP2.11 Decision 3's explicit instruction:
"let H2 determine from the likelihood whether that channel's `z_offset`
values genuinely differ"). The recorded z-offset evidence found:

- Both DNA outcomes' `z_offset` values for `uk_dna_performance_display`
  showed **similar sign and similar magnitude** under H2 — i.e. H2 did
  **not** recover a genuine divergence between the two outcomes for that
  channel, which was the specific heterogeneity finding H2 was built to
  test for.
- Geometry evidence above (98 FH divergences, 369 DNA divergences — both
  large increases over the current hierarchy) indicates H2's single
  shared-scale parameterisation makes sampling **materially harder**, not
  easier, for both products.

Taken together, H2 both (a) failed to demonstrate the specific
heterogeneity preservation it was designed to test for, and (b)
substantially worsened sampler geometry on both products. Per WP2.11's
own instruction ("do not choose a winner solely because it removes
divergences" / by symmetry, a candidate that *adds* divergences without
compensating benefit is disfavoured on the same logic), H2's evidence
does not support even provisional preference over the current hierarchy,
independent of any production-default question.

## Predictive fit, residual structure, and contribution stability

Not separately re-derived in this package beyond what the convergence
comparison and each candidate's own saved `posterior_summary.csv` /
`overall_outcome_posterior_summary.csv` already record
(`D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-11-*-20260826\`).
A dedicated per-candidate fit-metric/contribution/residual-structure
comparison table (WP2.11 item 3's originally scoped "one comparison table
… per product across all listed evidence categories") is **not yet
assembled** — this is recorded as remaining work, not silently skipped
(see "What evidence is still needed" below).

## What each candidate's evidence supports

- **Current hierarchy**: the certified production default. Retains its
  own documented divergence finding (13 FH / 46 DNA) as an open,
  previously-recorded issue (`docs/model_a_convergence_remediation_
  20260822.md`) — this package does not newly certify or decertify it.
- **H1**: fully resolves FH's divergent geometry (13 → 0) and
  substantially, though not completely, improves DNA's (46 → 35, with
  the localised per-chain pattern noted above). Marginally lower ESS on
  FH than the current hierarchy but still comfortably above usable
  thresholds. The strongest convergence case of the two segment-
  preserving challengers.
- **H2**: substantially worse convergence on both products, and does not
  recover the specific `uk_dna_performance_display` heterogeneity it was
  built to test for. The evidence does not support H2 as a preferred
  segment-preserving alternative to the current hierarchy or to H1.
- **Overall challenger**: cleanest convergence of all four (0 divergences,
  highest ESS on both products) but is explicitly a robustness comparator
  only — it collapses outcomes into one combined series and is not a
  segment-preserving candidate, so it cannot answer the same question H1/
  H2 were built to answer (WP2.11's explicit instruction).

## What evidence argues against each candidate

- **Current hierarchy**: unresolved divergences on both products.
- **H1**: DNA's 35 remaining divergences (not zero) and the localised,
  not-yet-explained per-chain concentration.
- **H2**: worse geometry on both products; fails its own diagnostic
  purpose.
- **Overall challenger**: not a segment-preserving structure, so its
  clean convergence cannot be read as evidence about the FH/DNA-segment
  hierarchy question at all — it answers a different question.

## Unresolved identification / data-support limitations

1. Why DNA's H1 divergences concentrate in one chain (0, 34, 0, 1) is not
   explained by evidence gathered so far — plausibly a localised
   mode-switching episode, but not confirmed.
2. No fold-refit / out-of-sample backtest evidence exists for any
   candidate (see "Reconstruction tier and its limitation" above) —
   in-sample convergence and fit evidence alone cannot establish
   predictive validity, and WP2.11 explicitly prohibits choosing a winner
   on in-sample evidence alone.
3. The current UK activity data is under separate review for suspected
   source-to-model mapping issues. Any evidence in this package that
   ultimately traces back to affected channels (sparse-support channels
   named above) may need to be revisited once that review concludes.
4. Item 3's full per-product, per-candidate comparison table (fit
   metrics, residual structure, contribution stability) is not yet
   assembled.

## Is the evidence sufficient for a production-default decision?

**No.** Convergence/geometry evidence alone establishes that H1 is the
more numerically well-behaved segment-preserving challenger relative to
H2, and materially better than the current hierarchy on FH divergences
specifically. It does **not** establish predictive validity, residual
behaviour, or contribution stability — WP2.11 explicitly prohibits
selecting a hierarchy on convergence/in-sample evidence alone, and no
out-of-sample evidence exists yet for any candidate. A production-default
decision should wait for:

- resolution of the current UK activity-data review, since several of
  the sparse-support channels implicated in the fold-refit-backtest
  limitation could affect that evidence once it becomes available;
- a completed fold-refit backtest run (now instrumented for live
  visibility) for the current hierarchy and, at minimum, H1;
- the item-3 comparison table (fit metrics, residual structure,
  contribution stability) across all four candidates;
- an explanation (or at least a bounded characterisation) of DNA's H1
  per-chain divergence concentration.

## The exact production change each option would require

- **Retain current hierarchy**: no code change. The existing, previously
  recorded FH/DNA divergence finding remains open and uncertified.
- **Adopt H1**: set `pooled_beta_reference=True` as the production prior
  configuration for Model A (`core.hierarchical_model.
  build_fh_hierarchical_model`) — an existing, already-implemented
  mechanism; the change is a governed prior-configuration default switch,
  not new modelling code. Would require: an approved decision record
  authorising the production-default change, re-running the full
  official-submission pre-fit/diagnostics/approval workflow against the
  new default, and updating `docs/specification_authority.md`'s
  production-hierarchy description.
- **Adopt H2**: currently not eligible for this question at all —
  `REQ-HIERARCHY-001` authorises H2 as diagnostic-only, and this
  package's own evidence (worse geometry on both products, failure to
  recover the target heterogeneity) does not support proposing it for
  production-default consideration.

## Affected REQ records and tests

- `REQ-HIERARCHY-001` (`docs/approved_requirements/REQ-HIERARCHY-001.md`)
  — governs H2's diagnostic-only status; unaffected by this package
  (no promotion proposed).
- No change to `docs/approved_requirements/index.json` from this package.
- `ancestry_mmm/tests/test_hierarchical_model.py`'s
  `TestSharedPoolingScaleHierarchyChallenger` and the existing
  `pooled_beta_reference` coverage remain the production-code test
  authority for both challenger mechanisms; unchanged by this package.

## Recommendation

Do not change the production Model A hierarchy default at this time.
H1 is, on the evidence gathered so far, the more promising
segment-preserving challenger and merits continued evidence-gathering
once the current UK activity-data review concludes and a working
fold-refit backtest run can complete. H2 should not be advanced further
as a segment-preserving production candidate on the evidence in this
package; its diagnostic-only status under `REQ-HIERARCHY-001` is
unaffected. This workstream stops here pending: the data review, a
completed fold-refit backtest, the item-3 comparison table, and an
explicit human decision record before any production-default change.
