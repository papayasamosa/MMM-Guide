"""Application boundary for reusable pre-fit identifiability evidence."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from ancestry_mmm.core.prefit_identifiability import (
    PriorPredictiveThresholdPolicy,
    SupportThresholdPolicy,
    build_prefit_identifiability_report,
    build_prefit_fingerprints,
    prefit_diagnostic_freshness,
)


def review_prefit_identifiability(
    data: pd.DataFrame,
    channels: Sequence[str],
    *,
    product: str,
    model_name: str,
    date_col: str | None = None,
    market_col: str | None = None,
    target_start: str | pd.Timestamp | None = None,
    target_end: str | pd.Timestamp | None = None,
    units: Mapping[str, Any] | None = None,
    transform_config: Mapping[str, Any] | None = None,
    posterior_evidence: Mapping[str, Any] | None = None,
    recovery_evidence: Mapping[str, Any] | None = None,
    prior_predictive: Mapping[str, Any] | None = None,
    support_threshold_policy: SupportThresholdPolicy | Mapping[str, Any] | None = None,
    prior_predictive_threshold_policy: PriorPredictiveThresholdPolicy
    | Mapping[str, Any]
    | None = None,
    candidate_spec: Any = None,
    prepared_frame: Any = None,
    causal_graph: Any = None,
) -> dict[str, Any]:
    """Compute a serialisable review for the current model-ready input.

    The service deliberately accepts a plain DataFrame and configuration
    payloads.  It has no Streamlit dependency and therefore can be called by
    uploads, readiness runners, tests, or a future API adapter.
    """

    return build_prefit_identifiability_report(
        data,
        channels,
        product=product,
        model_name=model_name,
        date_col=date_col,
        market_col=market_col,
        target_start=target_start,
        target_end=target_end,
        units=units,
        transform_config=transform_config,
        posterior_evidence=posterior_evidence,
        recovery_evidence=recovery_evidence,
        prior_predictive=prior_predictive,
        support_threshold_policy=support_threshold_policy,
        prior_predictive_threshold_policy=prior_predictive_threshold_policy,
        candidate_spec=candidate_spec,
        prepared_frame=prepared_frame,
        causal_graph=causal_graph,
    )


def current_prefit_fingerprint_set(
    data: pd.DataFrame,
    *,
    channels: Sequence[str],
    date_col: str | None,
    market_col: str | None,
    target_start: str | pd.Timestamp | None,
    target_end: str | pd.Timestamp | None,
    transform_config: Mapping[str, Any] | None,
    candidate_spec: Any = None,
    prepared_frame: Any = None,
    causal_graph: Any = None,
) -> dict[str, str]:
    """Return the current input identity for a persisted review."""

    return build_prefit_fingerprints(
        data,
        channels=channels,
        date_col=date_col,
        market_col=market_col,
        target_start=target_start,
        target_end=target_end,
        transform_config=transform_config,
        candidate_spec=candidate_spec,
        prepared_frame=prepared_frame,
        causal_graph=causal_graph,
    )


def assess_prefit_freshness(
    report: Mapping[str, Any], current_fingerprints: Mapping[str, str]
) -> dict[str, Any]:
    """Return current/stale state without changing the stored evidence."""

    return prefit_diagnostic_freshness(report, current_fingerprints)
