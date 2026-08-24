"""Application boundary for deterministic pre-fit surrogate evidence."""

from __future__ import annotations

from typing import Any, Mapping

from ancestry_mmm.core.prefit_screening import (
    build_prefit_screening_report,
    record_prefit_analyst_review,
)


def run_prefit_screen(
    frame: Mapping[str, Any],
    *,
    transform_config: Mapping[str, Any] | None = None,
    n_folds: int = 3,
    min_train_periods: int = 8,
    fingerprints: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Run the read-only leakage-safe pre-fit surrogate screen.

    This boundary keeps the deterministic screen callable without Streamlit
    and makes its evidence contract explicit for future readiness runners or
    API adapters.
    """

    return build_prefit_screening_report(
        frame,
        transform_config=transform_config,
        n_folds=n_folds,
        min_train_periods=min_train_periods,
        fingerprints=fingerprints,
    )


def save_prefit_analyst_review(
    report: Mapping[str, Any], rationale: str
) -> dict[str, Any]:
    """Retain review text while keeping official eligibility fail-closed."""

    return record_prefit_analyst_review(report, rationale)
