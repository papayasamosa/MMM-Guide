"""Real per-fold PyMC refit orchestration wired into the leakage-safe fold
contract (REQ-LEAK-001 §"rebuilding the full model-ready frame... per
fold" follow-on; Work Package 1 part 1 of `Media-Mix-Lab: Coding LLM Next
Steps After PR #284`).

`core.validation_folds.leakage_safe_expanding_window_backtest` and
`core.structural_stability.assess_structural_stability` were both built on
a deliberate "the caller supplies the fold-local computation" contract -
but until this module, nothing in this repository ever called either one
with a real fit. `core.validation_folds`'s own test suite only exercises
`fit_fold_fn` with a fake; `core.structural_stability`'s only ever
compares manually-constructed `FoldParameterSnapshot`s. The one place a
real per-fold PyMC refit already existed was `pages/06_Diagnostics.py`'s
"Out-of-sample accuracy" backtest closure - wired to the plain,
non-leakage-safe `core.diagnostics.expanding_window_backtest`, and
producing only R²/MAPE, no structural-stability evidence.

This module reuses that same real-fit sequence (`data.prepare_fh_modeling_
frame` -> `application.model_fit_service.build_model_for_spec` ->
`core.models.fit_model` -> `core.predict.extract_posterior_params` /
`core.market_specific_predict.extract_market_specific_posterior_params` ->
`predict_mu` / `predict_mu_market_specific`) - never a second, simplified
validation-only model engine - but drives it through the leakage-safe fold
contract instead, and additionally extracts a `FoldParameterSnapshot` per
fold so real structural-stability evidence becomes possible.

`core.validation_folds.leakage_safe_expanding_window_backtest`'s public
`fit_fold_fn` contract is `(train_df, test_df) -> (r2_by_outcome,
mape_by_outcome)` - deliberately unchanged here, since it is an existing,
separately tested public contract. That contract has no way to pass a
fold's `fold_id` through to the callback, which a `FoldParameterSnapshot`
requires. Rather than widen that tested contract's shape (with knock-on
effects for its existing callers/tests) or fit every fold twice (once for
the tested helper's r2/mape row, once more for a snapshot - doubling
sampling cost and risking two divergent fits reporting inconsistent
numbers for the same fold), this module reimplements the same fold
selection loop `leakage_safe_expanding_window_backtest` uses internally
(`build_expanding_window_folds` + `assess_fold_source_reconstruction`,
both already public), so the real fit happens exactly once per accepted
fold and the resulting `results_df` row shape stays identical.

Candidate A: out of scope. `application.model_fit_service.build_model_for_
spec` is called here without a `causal_graph`, which deterministically
resolves to the ordinary engine (`resolve_engine`'s own contract - a graph
is required to route anywhere else) - this mirrors the Diagnostics page's
existing backtest, which explicitly refuses to run at all when the
project's fitted engine is Candidate A (no fold has the Search
observations needed to rebuild its demand/capture chain). Callers of this
module must apply that same guard before invoking it for a Candidate
A-engine project; this module has no way to detect that from `df`/`spec`
alone.

Deliberately out of scope for Work Package 1 part 1 (see the module
docstring's "part 2" reference in `docs/decision_log.md`):

- Point-in-time reconstruction of the raw source data itself (selecting
  the source *version* that existed as of a fold's information cutoff,
  re-running `core.official_preparation`/`core.frequency_conversion`
  fold-locally from raw sources). `df`/`test_df` here are still plain
  date-sliced rows of whatever single dataframe the caller supplies -
  exactly `leakage_safe_expanding_window_backtest`'s own existing
  limitation, unchanged by this module.
- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics page.
- Any real-NUTS-per-fold CI cost decision beyond "callers choose their own
  draws/tune/chains budget" - normal-CI callers should use a small budget
  (this module changes no CI job); a schedule/manual job using a realistic
  budget is a separate follow-up.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Tuple

import numpy as np
import pandas as pd

from ancestry_mmm.application.model_fit_service import (
    MODEL_TYPE_MARKET_SPECIFIC,
    MODEL_TYPE_SHARED,
    build_model_for_spec,
)
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import (
    FHPosteriorParams,
    extract_posterior_params,
    predict_mu,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.structural_stability import FoldParameterSnapshot
from ancestry_mmm.core.uncertainty import sample_draw_indices
from ancestry_mmm.core.validation_folds import (
    FoldReconstructionAssessment,
    ValidationFold,
    assess_fold_source_reconstruction,
    build_expanding_window_folds,
)
from ancestry_mmm.data import prepare_fh_modeling_frame

# Decision-driving structural quantities this module extracts into a
# FoldParameterSnapshot - a curated subset, not every fitted parameter
# (mirrors core.structural_stability's own "adstock decay, saturation
# shape, media response coefficients, baseline behaviour, hierarchy
# parameters" framing). Array-valued parameters (e.g. gamma_fourier) are
# not flattened here - a per-Fourier-index point comparison is low signal
# for structural-stability review and not part of the module's documented
# scope.


def _flatten_shared_params(params: FHPosteriorParams) -> Dict[str, float]:
    flat: Dict[str, float] = {}
    for channel, value in params.decay_rate.items():
        flat[f"adstock_decay__{channel}"] = float(value)
    for channel, value in params.hill_K.items():
        flat[f"hill_K__{channel}"] = float(value)
    for channel, value in params.hill_S.items():
        flat[f"hill_S__{channel}"] = float(value)
    for outcome_id, by_channel in params.beta.items():
        for channel, value in by_channel.items():
            flat[f"beta__{channel}__{outcome_id}"] = float(value)
    for outcome_id, value in params.intercept.items():
        flat[f"intercept__{outcome_id}"] = float(value)
    for outcome_id, value in params.trend_coef.items():
        flat[f"trend_coef__{outcome_id}"] = float(value)
    for outcome_id, value in params.promo_coef.items():
        flat[f"promo_coef__{outcome_id}"] = float(value)
    for market, by_outcome in params.market_offset.items():
        for outcome_id, value in by_outcome.items():
            flat[f"market_offset__{market}__{outcome_id}"] = float(value)
    return flat


def _flatten_market_specific_params(
    params: FHMarketSpecificPosteriorParams,
) -> Dict[str, float]:
    flat: Dict[str, float] = {}
    for channel, value in params.decay_rate.items():
        flat[f"adstock_decay__{channel}"] = float(value)
    for channel, value in params.hill_S.items():
        flat[f"hill_S__{channel}"] = float(value)
    for market, by_channel in params.hill_K.items():
        for channel, value in by_channel.items():
            flat[f"hill_K__{market}__{channel}"] = float(value)
    for market, beta_by_outcome in params.beta.items():
        for outcome_id, by_channel in beta_by_outcome.items():
            for channel, value in by_channel.items():
                flat[f"beta__{market}__{channel}__{outcome_id}"] = float(value)
    for outcome_id, value in params.intercept.items():
        flat[f"intercept__{outcome_id}"] = float(value)
    for outcome_id, value in params.trend_coef.items():
        flat[f"trend_coef__{outcome_id}"] = float(value)
    for outcome_id, value in params.promo_coef.items():
        flat[f"promo_coef__{outcome_id}"] = float(value)
    for market, offset_by_outcome in params.market_offset.items():
        for outcome_id, value in offset_by_outcome.items():
            flat[f"market_offset__{market}__{outcome_id}"] = float(value)
    return flat


def _fold_metrics(
    test_frame: Dict[str, Any], outcome_ids: List[str], mu_test: np.ndarray
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Identical R²/MAPE calculation to `pages/06_Diagnostics.py`'s
    existing `fit_fold` closure, extracted verbatim rather than
    reimplemented, so this module's evidence is never a second,
    numerically-divergent way of measuring the same thing."""
    r2_by_seg: Dict[str, float] = {}
    mape_by_seg: Dict[str, float] = {}
    for i, oid in enumerate(outcome_ids):
        actual, pred = test_frame["Y"][:, i], mu_test[:, i]
        ss_res = ((actual - pred) ** 2).sum()
        ss_tot = ((actual - actual.mean()) ** 2).sum()
        r2_by_seg[oid] = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
        mask = actual != 0
        mape_by_seg[oid] = (
            float((abs((actual[mask] - pred[mask]) / actual[mask])).mean() * 100)
            if mask.any()
            else float("nan")
        )
    return r2_by_seg, mape_by_seg


@dataclass(frozen=True)
class FoldRefitOutcome:
    """One accepted fold's real-fit result: the R²/MAPE row data
    `leakage_safe_expanding_window_backtest` would have produced, plus the
    `FoldParameterSnapshot` that helper's contract has no way to carry."""

    fold_id: str
    r2_by_outcome: Mapping[str, float]
    mape_by_outcome: Mapping[str, float]
    snapshot: FoldParameterSnapshot


def fit_fold_with_real_model(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    spec: ModelSpec,
    *,
    fold_id: str,
    model_type: str = MODEL_TYPE_SHARED,
    dna_lag_weeks: int = 4,
    prior_config: Any = None,
    draws: int = 500,
    tune: int = 500,
    chains: int = 2,
    cores: int = 1,
    target_accept: float = 0.9,
    posterior_draw_subsample: int = 100,
    random_seed: int = 42,
) -> FoldRefitOutcome:
    """Refit the real production model on `train_df`, evaluate it on
    `test_df`, and extract a genuine `FoldParameterSnapshot` - the same
    real-fit sequence `pages/06_Diagnostics.py`'s existing backtest
    closure uses (`build_model_for_spec` -> `fit_model` ->
    `extract_*_posterior_params` -> `predict_mu*`), reused rather than
    reimplemented, routed through `application.model_fit_service` (the
    governed dispatch point) instead of calling the builders directly.

    `posterior_draw_subsample` mirrors `core.uncertainty.sample_draw_
    indices`'s own documented approximation: re-running the parameter
    extraction once per sampled `(chain, draw)` pair is exact for that
    draw, subsampled (not every draw) for speed - the same trade-off
    `core.uncertainty` already makes for per-draw scenario/curve
    uncertainty.
    """
    train_frame = prepare_fh_modeling_frame(train_df, spec)
    is_market_specific = (
        model_type == MODEL_TYPE_MARKET_SPECIFIC and len(train_frame["markets"]) >= 2
    )
    resolved_model_type = (
        MODEL_TYPE_MARKET_SPECIFIC if is_market_specific else MODEL_TYPE_SHARED
    )

    fit_result = build_model_for_spec(
        frame=train_frame,
        model_spec=spec,
        model_type=resolved_model_type,
        dna_lag_weeks=dna_lag_weeks,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=prior_config,
    )
    trace = fit_model(
        fit_result.model,
        draws=draws,
        tune=tune,
        chains=chains,
        cores=cores,
        target_accept=target_accept,
        random_seed=random_seed,
    )

    test_frame = prepare_fh_modeling_frame(test_df, spec)
    if is_market_specific:
        market_specific_point_params = extract_market_specific_posterior_params(
            trace, fit_result.meta
        )
        mu_test = predict_mu_market_specific(
            test_frame, fit_result.meta, market_specific_point_params
        )
        point_values = _flatten_market_specific_params(market_specific_point_params)
    else:
        shared_point_params = extract_posterior_params(trace, fit_result.meta)
        mu_test = predict_mu(test_frame, fit_result.meta, shared_point_params)
        point_values = _flatten_shared_params(shared_point_params)

    r2_by_outcome, mape_by_outcome = _fold_metrics(
        test_frame, fit_result.meta.outcome_ids, mu_test
    )

    draws_by_param: Dict[str, List[float]] = defaultdict(list)
    for at in sample_draw_indices(
        trace, n_draws=posterior_draw_subsample, seed=random_seed
    ):
        if is_market_specific:
            market_specific_draw_params = extract_market_specific_posterior_params(
                trace, fit_result.meta, at=at
            )
            draw_point_values = _flatten_market_specific_params(
                market_specific_draw_params
            )
        else:
            shared_draw_params = extract_posterior_params(trace, fit_result.meta, at=at)
            draw_point_values = _flatten_shared_params(shared_draw_params)
        for name, value in draw_point_values.items():
            draws_by_param[name].append(value)

    snapshot = FoldParameterSnapshot(
        fold_id=fold_id,
        point_values=point_values,
        draws={name: tuple(values) for name, values in draws_by_param.items()},
    )
    return FoldRefitOutcome(
        fold_id=fold_id,
        r2_by_outcome=r2_by_outcome,
        mape_by_outcome=mape_by_outcome,
        snapshot=snapshot,
    )


@dataclass(frozen=True)
class LeakageSafeFoldRefitResult:
    """Same row shape as `core.validation_folds.
    leakage_safe_expanding_window_backtest`'s `results_df` (`fold_id`,
    `train_end`, `test_end`, `outcome_id`, `r_squared`, `mape_pct`,
    `leakage_safe`, `skipped_reason`), plus the real `FoldParameterSnapshot`
    per fold that was actually fit - the evidence
    `core.structural_stability.assess_structural_stability` needs."""

    results_df: pd.DataFrame
    folds: Tuple[ValidationFold, ...]
    assessments: Tuple[FoldReconstructionAssessment, ...]
    snapshots: Tuple[FoldParameterSnapshot, ...]


def run_leakage_safe_fold_refit(
    df: pd.DataFrame,
    spec: ModelSpec,
    coverage_matrix: VariableCoverageMatrix,
    *,
    model_type: str = MODEL_TYPE_SHARED,
    n_folds: int = 3,
    min_train_frac: float = 0.6,
    dna_lag_weeks: int = 4,
    prior_config: Any = None,
    draws: int = 500,
    tune: int = 500,
    chains: int = 2,
    cores: int = 1,
    target_accept: float = 0.9,
    posterior_draw_subsample: int = 100,
    random_seed: int = 42,
) -> LeakageSafeFoldRefitResult:
    """Leakage-safe, real-PyMC-refit counterpart to `core.validation_
    folds.leakage_safe_expanding_window_backtest`: builds the same typed
    fold manifests, assesses each against `coverage_matrix` before
    fitting anything (refusing to fit a fold the assessment did not
    clear, exactly like the helper this reimplements the selection loop
    of), and for every fold that clears, fits the real production model
    exactly once via `fit_fold_with_real_model` - producing both the
    R²/MAPE evidence and a genuine `FoldParameterSnapshot` from the same
    fit, never two divergent fits for the same fold.
    """
    folds = build_expanding_window_folds(
        df, spec.date_col, n_folds=n_folds, min_train_frac=min_train_frac
    )
    assessments = tuple(
        assess_fold_source_reconstruction(fold, coverage_matrix) for fold in folds
    )

    dates = pd.to_datetime(df[spec.date_col])
    rows: List[Dict[str, Any]] = []
    snapshots: List[FoldParameterSnapshot] = []

    for fold, assessment in zip(folds, assessments):
        test_df = df[
            (dates > pd.Timestamp(fold.train_end))
            & (dates <= pd.Timestamp(fold.test_end))
        ]
        if test_df.empty:
            continue

        if not assessment.is_leakage_safe:
            rows.append(
                {
                    "fold_id": fold.fold_id,
                    "train_end": fold.train_end,
                    "test_end": fold.test_end,
                    "outcome_id": None,
                    "r_squared": None,
                    "mape_pct": None,
                    "leakage_safe": False,
                    "skipped_reason": (
                        "fold failed leakage-safety assessment - see the "
                        "returned FoldReconstructionAssessment for this "
                        "fold_id"
                    ),
                }
            )
            continue

        train_df = df[dates <= pd.Timestamp(fold.train_end)]
        outcome = fit_fold_with_real_model(
            train_df,
            test_df,
            spec,
            fold_id=fold.fold_id,
            model_type=model_type,
            dna_lag_weeks=dna_lag_weeks,
            prior_config=prior_config,
            draws=draws,
            tune=tune,
            chains=chains,
            cores=cores,
            target_accept=target_accept,
            posterior_draw_subsample=posterior_draw_subsample,
            random_seed=random_seed,
        )
        snapshots.append(outcome.snapshot)
        for oid in outcome.r2_by_outcome:
            rows.append(
                {
                    "fold_id": fold.fold_id,
                    "train_end": fold.train_end,
                    "test_end": fold.test_end,
                    "outcome_id": oid,
                    "r_squared": outcome.r2_by_outcome[oid],
                    "mape_pct": outcome.mape_by_outcome[oid],
                    "leakage_safe": True,
                    "skipped_reason": None,
                }
            )

    return LeakageSafeFoldRefitResult(
        results_df=pd.DataFrame(rows),
        folds=folds,
        assessments=assessments,
        snapshots=tuple(snapshots),
    )
