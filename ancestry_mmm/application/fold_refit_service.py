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

Candidate A is supported when the caller supplies the fit-pinned Search
observation payload and approved Search-object mapping. The fold helper
slices those rows by exact `(period, market)` identity and passes the fold's
cap-aware Search inputs into the same production model builder. Legacy
array-only Candidate A payloads fail closed because their row ordering cannot
be proven safe for a fold. Ordinary projects continue to use the unchanged
non-Search path.

Work Package 1 part 2 (`Media-Mix-Lab: Coding LLM Next Steps After PR
#286`) added `run_leakage_safe_fold_refit_from_sources`: unlike
`run_leakage_safe_fold_refit` above, it never slices one already-prepared
dataframe. It accepts the project's raw native per-source tables and
registered `core.coverage.SourceVersion` upload events, and for each fold
that clears assessment, re-runs `core.official_preparation.
prepare_canonical_native_frame` and `core.frequency_alignment.
assess_official_preparation` *fold-locally* - governed to the fold's own
training window and information cutoff - so a later source revision,
publication, or mapping/alignment decision genuinely cannot enter an
earlier fold's training reconstruction. It reuses `fit_fold_with_real_
model` for the actual fit (never a second, divergent fit sequence) and
`assess_fold_source_reconstruction`/`build_expanding_window_folds` for
fold selection (never a second leakage-detection mechanism) - the same
"caller supplies the fold-local computation" reuse pattern
`run_leakage_safe_fold_refit` already established, extended one layer
earlier in the pipeline. See its own docstring for the exact scope
boundary on what "point-in-time" can and cannot mean given what this
repository's data model retains.

Deliberately out of scope for Work Package 1 part 1 (see the module
docstring's "part 2" reference in `docs/decision_log.md`):

- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics page.
- Any real-NUTS-per-fold CI cost decision beyond "callers choose their own
  draws/tune/chains budget" - normal-CI callers should use a small budget
  (this module changes no CI job); a schedule/manual job using a realistic
  budget is a separate follow-up.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import time

import numpy as np
import pandas as pd

from ancestry_mmm.application.model_fit_service import (
    MODEL_TYPE_MARKET_SPECIFIC,
    MODEL_TYPE_SHARED,
    build_model_for_spec,
)
from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.core.coverage import SourceVersion, VariableCoverageMatrix
from ancestry_mmm.core.frequency_alignment import (
    alignment_specs_from_coverage_matrix,
    assess_official_preparation,
)
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
    predict_mu_market_specific,
)
from ancestry_mmm.core.fit_progress import (
    FoldFitContext,
    SamplingProgressReporter,
    format_fold_fit_context_line,
)
from ancestry_mmm.core.fold_data_support import fold_support_report
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.named_event_fit_inputs import NamedEventFitInputs
from ancestry_mmm.core.official_preparation import (
    OfficialPreparationDataError,
    build_official_capability_report,
    prepare_canonical_native_frame,
)
from ancestry_mmm.core.net_billthrough import NetBillthroughCompletenessMetadata
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.predict import (
    FHPosteriorParams,
    extract_posterior_params,
    predict_mu,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_objects import SearchObjectDefinition
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    slice_candidate_a_fit_inputs,
)
from ancestry_mmm.core.structural_stability import FoldParameterSnapshot
from ancestry_mmm.core.uncertainty import sample_draw_indices
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
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


def _fold_local_net_billthrough_metadata(
    metadata: Any, df: pd.DataFrame, spec: ModelSpec
) -> Any:
    """`NetBillthroughCompletenessMetadata.model_start_week`/
    `model_end_week` must exactly bound the frame being validated
    (`core.net_billthrough.validate_supplied_net_billthrough`: "coverage
    must exactly match the configured model window"). A caller's
    `net_billthrough_metadata` describes the *full* candidate's window;
    each fold's train/test slice covers a different, shorter window, so
    the full-candidate metadata can never validate a fold's frame as-is.
    Every other field (`data_as_of_date`, `latest_complete_net_
    billthrough_week`, `maturity_rule_description`, `source_owner`,
    `metric_key`, `date_basis`, `unit`, `aggregation_type`) is genuinely
    fold-independent and is carried through unchanged - only the window
    bounds are re-derived from this fold's own slice."""
    if metadata is None:
        return None
    resolved = (
        metadata
        if isinstance(metadata, NetBillthroughCompletenessMetadata)
        else NetBillthroughCompletenessMetadata.from_dict(metadata)
    )
    dates = pd.to_datetime(df[spec.date_col])
    return replace(
        resolved,
        model_start_week=dates.min().strftime("%Y-%m-%d"),
        model_end_week=dates.max().strftime("%Y-%m-%d"),
    )


def fit_fold_with_real_model(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    spec: ModelSpec,
    *,
    fold_id: str,
    model_type: str = MODEL_TYPE_SHARED,
    dna_lag_weeks: int = 4,
    outcomes: Optional[Sequence[OutcomeDefinition]] = None,
    dna_outcome_id: Optional[str] = None,
    direct_dna_outcome_ids: Optional[Sequence[str]] = None,
    causal_graph: Optional[CausalGraph] = None,
    media_outcome_pathways: Optional[Sequence[Any]] = None,
    activity_definitions: Optional[Sequence[Any]] = None,
    net_billthrough_metadata: Any = None,
    prior_config: Any = None,
    draws: int = 500,
    tune: int = 500,
    chains: int = 2,
    cores: int = 1,
    target_accept: float = 0.9,
    posterior_draw_subsample: int = 100,
    random_seed: int = 42,
    on_progress_line: Optional[Callable[[str], None]] = None,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
    named_event_replay_inputs: Optional[NamedEventFitInputs] = None,
    named_event_replay_inputs_factory: Optional[
        Callable[
            [Mapping[str, Any], Sequence[Tuple[str, int]]],
            Optional[NamedEventFitInputs],
        ]
    ] = None,
    candidate_a_fit_inputs: Optional[CandidateASearchFitInputs] = None,
    search_objects: Optional[
        Sequence[SearchObjectDefinition | Mapping[str, Any]]
    ] = None,
) -> FoldRefitOutcome:
    """Refit the real production model on `train_df`, evaluate it on
    `test_df`, and extract a genuine `FoldParameterSnapshot` - the same
    real-fit sequence `pages/06_Diagnostics.py`'s existing backtest
    closure uses (`build_model_for_spec` -> `fit_model` ->
    `extract_*_posterior_params` -> `predict_mu*`), reused rather than
    reimplemented, routed through `application.model_fit_service` (the
    governed dispatch point) instead of calling the builders directly.

    `outcomes`/`dna_outcome_id`/`direct_dna_outcome_ids`/`causal_graph`/
    `media_outcome_pathways`/`net_billthrough_metadata` (WP2.11 item 4)
    all default to `None`, which preserves this function's exact
    pre-existing behaviour: `prepare_fh_modeling_frame` falls back to its
    own legacy `segment_outcomes`-derived catalogue, and `dna_outcome_id`
    resolves to `spec.fh_dna_cross_sell_outcome_id` exactly as before. A
    caller holding the real governed `OutcomeDefinition` catalogue for the
    candidate being backtested (its real `outcome_id`s, DNA routing, and
    pathway catalogue - not a second, re-derived approximation of them)
    should pass all of them explicitly so each fold is fit with the same
    fit-relevant outcome semantics as the actual candidate, not a
    legacy/incompatible stand-in (WP2.10 found `fit_fold_with_real_model`
    silently reconstructing `fh_new`/`fh_dna cross-sell`/`fh_winback`-style
    legacy ids instead of the real governed NBT outcome_ids in exactly
    this way). When any NBT-metric outcome is present in the resolved
    catalogue, `core.hierarchical_model.build_fh_hierarchical_model`'s own
    completeness gate requires real `net_billthrough_metadata` - passing
    `None` for it while passing real NBT outcomes will fail closed with a
    clear validation error, not silently skip the check.

    `posterior_draw_subsample` mirrors `core.uncertainty.sample_draw_
    indices`'s own documented approximation: re-running the parameter
    extraction once per sampled `(chain, draw)` pair is exact for that
    draw, subsampled (not every draw) for speed - the same trade-off
    `core.uncertainty` already makes for per-draw scenario/curve
    uncertainty.

    `on_progress_line` defaults to `None`, preserving this function's exact
    pre-existing silent behaviour. A caller that supplies it (e.g. a
    fold-refit backtest script driven from a terminal) gets one line before
    sampling starts (training window, observation count, model-build time -
    `core.fit_progress.FoldFitContext`) and periodic lines during sampling
    carrying the real NUTS geometry for this specific fold's fit (step size,
    tree depth, divergences - `core.fit_progress.SamplingProgressReporter`),
    never only `(n_done, n_total)`. This exists because a real fold-refit run
    can legitimately take hours per fold when a fold's training slice has
    much weaker per-variable data support than the full candidate (see
    `core.fold_data_support`) - a caller must never be left with no way to
    tell "still working, here is why it is slow" apart from "silently stuck",
    which is exactly what happened in the WP2.11 item-5 backtest incident
    this module's instrumentation was added to prevent from recurring.
    """
    resolved_dna_outcome_id = (
        dna_outcome_id
        if dna_outcome_id is not None
        else spec.fh_dna_cross_sell_outcome_id
    )
    resolved_outcomes = list(outcomes) if outcomes is not None else None
    resolved_direct_dna_outcome_ids = (
        list(direct_dna_outcome_ids) if direct_dna_outcome_ids is not None else None
    )
    resolved_media_outcome_pathways = (
        list(media_outcome_pathways) if media_outcome_pathways is not None else None
    )
    resolved_activity_definitions = (
        list(activity_definitions) if activity_definitions is not None else None
    )
    candidate_train_inputs = None
    candidate_test_inputs = None
    if candidate_a_fit_inputs is not None:
        candidate_train_inputs = slice_candidate_a_fit_inputs(
            candidate_a_fit_inputs,
            periods=pd.to_datetime(train_df[spec.date_col]).dt.strftime("%Y-%m-%d"),
            markets=train_df[spec.market_col].astype(str),
        )
        candidate_test_inputs = slice_candidate_a_fit_inputs(
            candidate_a_fit_inputs,
            periods=pd.to_datetime(test_df[spec.date_col]).dt.strftime("%Y-%m-%d"),
            markets=test_df[spec.market_col].astype(str),
        )

    if on_progress_line is not None:
        outcome_cols = (
            [o.source_column for o in resolved_outcomes] if resolved_outcomes else []
        )
        support = fold_support_report(
            train_df,
            spec.date_col,
            spec.channels,
            spec.control_cols,
            outcome_cols,
            fold_id=fold_id,
        )
        on_progress_line(
            f"[{fold_id}] data-support: {len(support.variables)} variables, "
            f"training {support.train_start}..{support.train_end}"
        )
        for v in support.variables:
            on_progress_line(f"[{fold_id}]   {v.summary_line()}")

    train_frame = prepare_fh_modeling_frame(
        train_df,
        spec,
        outcomes=resolved_outcomes,
        media_outcome_pathways=resolved_media_outcome_pathways,
        activity_definitions=resolved_activity_definitions,
        net_billthrough_metadata=_fold_local_net_billthrough_metadata(
            net_billthrough_metadata, train_df, spec
        ),
    )
    is_market_specific = (
        model_type == MODEL_TYPE_MARKET_SPECIFIC and len(train_frame["markets"]) >= 2
    )
    resolved_model_type = (
        MODEL_TYPE_MARKET_SPECIFIC if is_market_specific else MODEL_TYPE_SHARED
    )

    _build_start = time.monotonic()
    fit_result = build_model_for_spec(
        frame=train_frame,
        model_spec=spec,
        model_type=resolved_model_type,
        dna_lag_weeks=dna_lag_weeks,
        dna_outcome_id=resolved_dna_outcome_id,
        direct_dna_outcome_ids=resolved_direct_dna_outcome_ids,
        causal_graph=causal_graph,
        search_objects=(
            list(search_objects)
            if search_objects is not None
            else (
                candidate_train_inputs.search_objects if candidate_train_inputs else ()
            )
        ),
        candidate_a_fit_inputs=candidate_train_inputs,
        prior_config=prior_config,
        named_event_fit_inputs=named_event_fit_inputs,
    )
    _build_seconds = time.monotonic() - _build_start

    stats_callback = None
    if on_progress_line is not None:
        train_dates = pd.to_datetime(train_df[spec.date_col])
        on_progress_line(
            format_fold_fit_context_line(
                FoldFitContext(
                    fold_id=fold_id,
                    model_label=resolved_model_type,
                    train_start=str(train_dates.min().date())
                    if not train_dates.empty
                    else None,
                    train_end=str(train_dates.max().date())
                    if not train_dates.empty
                    else None,
                    n_obs=len(train_df),
                    build_seconds=_build_seconds,
                )
            )
        )
        stats_callback = SamplingProgressReporter(
            fold_id=fold_id, model_label=resolved_model_type, emit=on_progress_line
        )

    trace = fit_model(
        fit_result.model,
        draws=draws,
        tune=tune,
        chains=chains,
        cores=cores,
        target_accept=target_accept,
        random_seed=random_seed,
        stats_callback=stats_callback,
    )

    test_frame = prepare_fh_modeling_frame(
        test_df,
        spec,
        outcomes=resolved_outcomes,
        media_outcome_pathways=resolved_media_outcome_pathways,
        activity_definitions=resolved_activity_definitions,
        net_billthrough_metadata=_fold_local_net_billthrough_metadata(
            net_billthrough_metadata, test_df, spec
        ),
    )
    resolved_named_event_replay_inputs = named_event_replay_inputs
    if (
        resolved_named_event_replay_inputs is None
        and named_event_replay_inputs_factory is not None
    ):
        resolved_named_event_replay_inputs = named_event_replay_inputs_factory(
            test_frame,
            tuple(fit_result.meta.named_event_response_definitions_at_fit),
        )
    if is_market_specific:
        market_specific_point_params = extract_market_specific_posterior_params(
            trace, fit_result.meta
        )
        mu_test = predict_mu_market_specific(
            test_frame,
            fit_result.meta,
            market_specific_point_params,
            named_event_fit_inputs=resolved_named_event_replay_inputs,
        )
        point_values = _flatten_market_specific_params(market_specific_point_params)
    else:
        shared_point_params = extract_posterior_params(trace, fit_result.meta)
        mu_test = predict_mu(
            test_frame,
            fit_result.meta,
            shared_point_params,
            named_event_fit_inputs=resolved_named_event_replay_inputs,
            candidate_a_paid_search_cap=(
                candidate_test_inputs.paid_search_cap
                if candidate_test_inputs is not None
                else None
            ),
        )
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
    `core.structural_stability.assess_structural_stability` needs.

    `reconstruction_tier` records which reconstruction produced this run's
    evidence (`core.validation_folds.RECONSTRUCTION_TIER_*`): the deep
    `run_leakage_safe_fold_refit_from_sources` path is
    `source_version_aware_fold_local`; the dataframe-slicing
    `run_leakage_safe_fold_refit` path is `coverage_metadata_only`. It is
    evidence provenance - a caller must never present one tier's evidence
    as the other's, and reload must never upgrade a stored weaker tier."""

    results_df: pd.DataFrame
    folds: Tuple[ValidationFold, ...]
    assessments: Tuple[FoldReconstructionAssessment, ...]
    snapshots: Tuple[FoldParameterSnapshot, ...]
    reconstruction_tier: str = RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY


def _fold_row(
    fold: ValidationFold,
    *,
    outcome_id: Optional[str],
    r_squared: Optional[float],
    mape_pct: Optional[float],
    leakage_safe: bool,
    skipped_reason: Optional[str],
) -> Dict[str, Any]:
    """The single row shape both `run_leakage_safe_fold_refit` and
    `run_leakage_safe_fold_refit_from_sources` build (Work Package 1 part
    2's own instance of the "shared fold orchestration" reduction the
    module docstring/`docs/decision_log.md` describe) - kept identical to
    `core.validation_folds.leakage_safe_expanding_window_backtest`'s row
    shape so every caller of any of the three functions can treat
    `results_df` uniformly."""
    return {
        "fold_id": fold.fold_id,
        "train_end": fold.train_end,
        "test_end": fold.test_end,
        "outcome_id": outcome_id,
        "r_squared": r_squared,
        "mape_pct": mape_pct,
        "leakage_safe": leakage_safe,
        "skipped_reason": skipped_reason,
    }


def run_leakage_safe_fold_refit(
    df: pd.DataFrame,
    spec: ModelSpec,
    coverage_matrix: VariableCoverageMatrix,
    *,
    model_type: str = MODEL_TYPE_SHARED,
    n_folds: int = 3,
    min_train_frac: float = 0.6,
    dna_lag_weeks: int = 4,
    outcomes: Optional[Sequence[OutcomeDefinition]] = None,
    dna_outcome_id: Optional[str] = None,
    direct_dna_outcome_ids: Optional[Sequence[str]] = None,
    causal_graph: Optional[CausalGraph] = None,
    media_outcome_pathways: Optional[Sequence[Any]] = None,
    activity_definitions: Optional[Sequence[Any]] = None,
    net_billthrough_metadata: Any = None,
    prior_config: Any = None,
    draws: int = 500,
    tune: int = 500,
    chains: int = 2,
    cores: int = 1,
    target_accept: float = 0.9,
    posterior_draw_subsample: int = 100,
    random_seed: int = 42,
    on_progress_line: Optional[Callable[[str], None]] = None,
    named_event_fit_inputs_factory: Optional[
        Callable[[Mapping[str, Any]], Optional[NamedEventFitInputs]]
    ] = None,
    named_event_replay_inputs_factory: Optional[
        Callable[
            [Mapping[str, Any], Sequence[Tuple[str, int]]],
            Optional[NamedEventFitInputs],
        ]
    ] = None,
    candidate_a_fit_inputs: Optional[CandidateASearchFitInputs] = None,
    search_objects: Optional[
        Sequence[SearchObjectDefinition | Mapping[str, Any]]
    ] = None,
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

    `outcomes`/`dna_outcome_id`/`direct_dna_outcome_ids`/`causal_graph`/
    `media_outcome_pathways`/`activity_definitions`/`net_billthrough_
    metadata` (WP2.11 item 4) all default to `None`, preserving this
    function's exact pre-existing behaviour for every caller that does
    not pass them - see `fit_fold_with_real_model`'s docstring for what
    each one does and why a caller backtesting the real governed
    candidate (rather than an ad hoc/test spec) should supply them.

    `on_progress_line` (also `None` by default) is passed straight through
    to `fit_fold_with_real_model` for every fold - see its docstring.
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
                _fold_row(
                    fold,
                    outcome_id=None,
                    r_squared=None,
                    mape_pct=None,
                    leakage_safe=False,
                    skipped_reason=(
                        "fold failed leakage-safety assessment - see the "
                        "returned FoldReconstructionAssessment for this "
                        "fold_id"
                    ),
                )
            )
            continue

        train_df = df[dates <= pd.Timestamp(fold.train_end)]
        named_event_fit_inputs = None
        if named_event_fit_inputs_factory is not None:
            train_frame_for_named_events = prepare_fh_modeling_frame(train_df, spec)
            named_event_fit_inputs = named_event_fit_inputs_factory(
                train_frame_for_named_events
            )
        outcome = fit_fold_with_real_model(
            train_df,
            test_df,
            spec,
            fold_id=fold.fold_id,
            model_type=model_type,
            dna_lag_weeks=dna_lag_weeks,
            outcomes=outcomes,
            dna_outcome_id=dna_outcome_id,
            direct_dna_outcome_ids=direct_dna_outcome_ids,
            causal_graph=causal_graph,
            media_outcome_pathways=media_outcome_pathways,
            activity_definitions=activity_definitions,
            net_billthrough_metadata=net_billthrough_metadata,
            prior_config=prior_config,
            draws=draws,
            tune=tune,
            chains=chains,
            cores=cores,
            target_accept=target_accept,
            posterior_draw_subsample=posterior_draw_subsample,
            random_seed=random_seed,
            on_progress_line=on_progress_line,
            named_event_fit_inputs=named_event_fit_inputs,
            named_event_replay_inputs_factory=named_event_replay_inputs_factory,
            candidate_a_fit_inputs=candidate_a_fit_inputs,
            search_objects=search_objects,
        )
        snapshots.append(outcome.snapshot)
        for oid in outcome.r2_by_outcome:
            rows.append(
                _fold_row(
                    fold,
                    outcome_id=oid,
                    r_squared=outcome.r2_by_outcome[oid],
                    mape_pct=outcome.mape_by_outcome[oid],
                    leakage_safe=True,
                    skipped_reason=None,
                )
            )

    return LeakageSafeFoldRefitResult(
        results_df=pd.DataFrame(rows),
        folds=folds,
        assessments=assessments,
        snapshots=tuple(snapshots),
        reconstruction_tier=RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    )


def run_leakage_safe_fold_refit_from_sources(
    sources: Mapping[str, pd.DataFrame],
    spec: ModelSpec,
    coverage_matrix: VariableCoverageMatrix,
    outcomes: Sequence[OutcomeDefinition | Mapping[str, Any]],
    *,
    governed_frequency: str = "weekly",
    source_versions: Sequence[SourceVersion | Mapping[str, Any]] = (),
    activity_definitions: Sequence[ActivityDefinition | Mapping[str, Any]] = (),
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
    pipeline_steps: Sequence[Mapping[str, Any]] = (),
    dna_outcome_id: Optional[str] = None,
    direct_dna_outcome_ids: Optional[Sequence[str]] = None,
    causal_graph: Optional[CausalGraph] = None,
    media_outcome_pathways: Optional[Sequence[Any]] = None,
    net_billthrough_metadata: Any = None,
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
    on_progress_line: Optional[Callable[[str], None]] = None,
    named_event_fit_inputs_factory: Optional[
        Callable[[Mapping[str, Any]], Optional[NamedEventFitInputs]]
    ] = None,
    named_event_replay_inputs_factory: Optional[
        Callable[
            [Mapping[str, Any], Sequence[Tuple[str, int]]],
            Optional[NamedEventFitInputs],
        ]
    ] = None,
    candidate_a_fit_inputs: Optional[CandidateASearchFitInputs] = None,
) -> LeakageSafeFoldRefitResult:
    """Point-in-time source reconstruction (REQ-LEAK-001 §"rebuilding the
    full model-ready frame ... per fold", Work Package 1 part 2): unlike
    `run_leakage_safe_fold_refit`, this function never slices one
    already-prepared dataframe. `sources` are the project's raw native
    per-source tables (the same shape `core.official_preparation.
    prepare_canonical_native_frame` and `application.uk_readiness` already
    use), keyed by `source_id`.

    For every candidate fold, this function:

    1. Assesses per-variable leakage-safety against `coverage_matrix` and
       `source_versions` (`core.validation_folds.
       assess_fold_source_reconstruction` - unchanged, reused, never a
       second leakage-detection mechanism).
    2. Assesses fold-local *official-preparation readiness* - governed to
       the fold's own training window (`governed_start=fold.train_start`,
       `governed_end=fold.train_end`) and information cutoff
       (`as_of=fold.effective_information_cutoff`) - via `core.
       frequency_alignment.assess_official_preparation`, the same
       governance function `application.official_preparation_service.
       review_official_preparation` already uses for a live project. A
       fold whose training window would require a mixed-frequency
       conversion, definition-break bridge, or coverage decision not yet
       resolved/approved as of its own cutoff is not leakage-safe, exactly
       like an unsupported method staying blocked for a live project.
    3. Only for a fold that clears both checks: re-runs `core.
       official_preparation.prepare_canonical_native_frame` fold-locally,
       once for the training window (`[fold.train_start, fold.train_end]`)
       and once for the held-out test window
       (`[fold.test_start, fold.test_end]`) - never one join clipped after
       the fact. The test window is *not* point-in-time-restricted: it is
       the already-realised ground truth this fold's holdout prediction is
       scored against (exactly as `run_leakage_safe_fold_refit`'s own
       `test_df` already is today's data, unmodified), not training input.
    4. Fits the real production model exactly once via `fit_fold_with_
       real_model` on the two fold-locally reconstructed frames - reused
       unchanged, never a second, divergent fit sequence.

    Scope boundary (see also `core.validation_folds.
    assess_fold_source_reconstruction`'s own docstring): `sources` is
    whatever single per-source-id table the caller currently has adopted
    (e.g. `data.source_pack_adoption.adopted_model_input_sources`'s
    output) - this repository's data model does not retain a separate,
    independently queryable table *per historical `SourceVersion`*, only
    that version's own upload-event identity (checksum/filename/size/
    `uploaded_at`). A fold whose relevant coverage record pins a
    `SourceVersion` uploaded after the fold's own cutoff is therefore
    always assessed `cannot_verify` and never fit - this function cannot
    (and does not attempt to) reconstruct what an earlier vintage's actual
    values would have been from data this repository does not separately
    retain. That is the explicit, honest limitation REQ-LEAK-001
    requirement 4 requires, not a defect: never substitute today's later
    revision and call it historically valid.

    `outcomes`/`activity_definitions`/`search_objects`/`pipeline_steps`
    resolve consumed variables and alignment specs exactly once (structural
    to `spec`, not fold-dependent) via `core.official_preparation.
    build_official_capability_report`/`core.frequency_alignment.
    alignment_specs_from_coverage_matrix` - the same functions a live
    project's official-preparation review already calls, never a second,
    parallel resolution.
    """
    date_col = spec.date_col
    market_col = spec.market_col
    resolved_source_versions = tuple(
        item if isinstance(item, SourceVersion) else SourceVersion.from_dict(item)
        for item in source_versions
    )
    # WP2.11 item 4: the real governed OutcomeDefinition catalogue this
    # function already receives for capability/consumed-variable
    # resolution below was never actually forwarded into the per-fold
    # `fit_fold_with_real_model` call - each fold silently refit against
    # `prepare_fh_modeling_frame`'s legacy `segment_outcomes`-derived
    # fallback catalogue instead (different outcome_ids, different
    # metric/unit semantics, no NBT completeness gate). Normalised once
    # here and passed through below so every fold fits the exact same
    # outcome identity as the real candidate this function was told about.
    resolved_outcomes = tuple(
        item
        if isinstance(item, OutcomeDefinition)
        else OutcomeDefinition.from_dict(item)
        for item in outcomes
    )

    capability_report = build_official_capability_report(
        spec,
        outcomes,
        coverage_matrix,
        activity_definitions=activity_definitions,
        search_objects=search_objects,
        pipeline_steps=pipeline_steps,
    )
    consumed_variable_ids = tuple(
        item.variable_id for item in capability_report.consumed_variables
    )
    alignment_specs = alignment_specs_from_coverage_matrix(
        coverage_matrix,
        target_frequency=governed_frequency,
        consumed_variable_ids=consumed_variable_ids,
    )

    calendar_dates = pd.concat(
        [pd.to_datetime(source[date_col]) for source in sources.values()],
        ignore_index=True,
    )
    calendar_df = pd.DataFrame({date_col: sorted(calendar_dates.unique())})
    folds = build_expanding_window_folds(
        calendar_df, date_col, n_folds=n_folds, min_train_frac=min_train_frac
    )

    rows: List[Dict[str, Any]] = []
    snapshots: List[FoldParameterSnapshot] = []
    assessments: List[FoldReconstructionAssessment] = []

    for fold in folds:
        assessment = assess_fold_source_reconstruction(
            fold, coverage_matrix, resolved_source_versions
        )
        assessments.append(assessment)

        preparation = assess_official_preparation(
            coverage_matrix,
            governed_start=fold.train_start,
            governed_end=fold.train_end,
            governed_frequency=governed_frequency,
            as_of=fold.effective_information_cutoff,
            consumed_variable_ids=consumed_variable_ids,
            capability_evidence=capability_report.to_dict(),
        )

        if not assessment.is_leakage_safe or not preparation.ready:
            reasons = []
            if not assessment.is_leakage_safe:
                reasons.append(
                    "fold failed leakage-safety assessment - see the "
                    "returned FoldReconstructionAssessment for this fold_id"
                )
            if not preparation.ready:
                reasons.append(
                    f"fold-local official preparation was not ready as of "
                    f"{fold.effective_information_cutoff} "
                    f"(status={preparation.status!r}): {preparation.reason}"
                )
            rows.append(
                _fold_row(
                    fold,
                    outcome_id=None,
                    r_squared=None,
                    mape_pct=None,
                    leakage_safe=False,
                    skipped_reason=" ".join(reasons),
                )
            )
            continue

        try:
            train_prepared = prepare_canonical_native_frame(
                sources,
                date_col=date_col,
                market_col=market_col,
                governed_start=fold.train_start,
                governed_end=fold.train_end,
                governed_frequency=governed_frequency,
                pipeline_steps=pipeline_steps,
                alignment_specs=alignment_specs,
                consumed_variable_ids=consumed_variable_ids,
            )
            test_prepared = prepare_canonical_native_frame(
                sources,
                date_col=date_col,
                market_col=market_col,
                governed_start=fold.test_start,
                governed_end=fold.test_end,
                governed_frequency=governed_frequency,
                pipeline_steps=pipeline_steps,
                alignment_specs=alignment_specs,
                consumed_variable_ids=consumed_variable_ids,
            )
        except OfficialPreparationDataError as exc:
            rows.append(
                _fold_row(
                    fold,
                    outcome_id=None,
                    r_squared=None,
                    mape_pct=None,
                    leakage_safe=False,
                    skipped_reason=(f"fold-local official preparation raised: {exc}"),
                )
            )
            continue

        if test_prepared.frame.empty:
            rows.append(
                _fold_row(
                    fold,
                    outcome_id=None,
                    r_squared=None,
                    mape_pct=None,
                    leakage_safe=False,
                    skipped_reason="fold's held-out test window has no rows",
                )
            )
            continue

        outcome = fit_fold_with_real_model(
            train_prepared.frame,
            test_prepared.frame,
            spec,
            fold_id=fold.fold_id,
            model_type=model_type,
            dna_lag_weeks=dna_lag_weeks,
            outcomes=resolved_outcomes,
            dna_outcome_id=dna_outcome_id,
            direct_dna_outcome_ids=direct_dna_outcome_ids,
            causal_graph=causal_graph,
            media_outcome_pathways=media_outcome_pathways,
            activity_definitions=activity_definitions,
            net_billthrough_metadata=net_billthrough_metadata,
            prior_config=prior_config,
            draws=draws,
            tune=tune,
            chains=chains,
            cores=cores,
            target_accept=target_accept,
            posterior_draw_subsample=posterior_draw_subsample,
            random_seed=random_seed,
            on_progress_line=on_progress_line,
            named_event_fit_inputs=(
                named_event_fit_inputs_factory(
                    prepare_fh_modeling_frame(train_prepared.frame, spec)
                )
                if named_event_fit_inputs_factory is not None
                else None
            ),
            named_event_replay_inputs_factory=named_event_replay_inputs_factory,
            candidate_a_fit_inputs=candidate_a_fit_inputs,
            search_objects=search_objects,
        )
        snapshots.append(outcome.snapshot)
        for oid in outcome.r2_by_outcome:
            rows.append(
                _fold_row(
                    fold,
                    outcome_id=oid,
                    r_squared=outcome.r2_by_outcome[oid],
                    mape_pct=outcome.mape_by_outcome[oid],
                    leakage_safe=True,
                    skipped_reason=None,
                )
            )

    return LeakageSafeFoldRefitResult(
        results_df=pd.DataFrame(rows),
        folds=folds,
        assessments=tuple(assessments),
        snapshots=tuple(snapshots),
        reconstruction_tier=RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
    )
