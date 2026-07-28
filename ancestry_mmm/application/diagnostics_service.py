"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 51B: Supports Model A (shared) and Model C (market-specific) scorecards.
No hard-coded convergence thresholds — thresholds come from policy.
One authoritative PPC calculation (not double-counted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.diagnostics import (
    compute_scorecard,
    posterior_predictive_coverage,
    curve_plausibility_checks,
    expanding_window_backtest,
)
from ancestry_mmm.core.market_specific_diagnostics import (
    compute_scorecard_market_specific,
    curve_plausibility_checks_market_specific,
)
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams


@dataclass
class DiagnosticsInput:
    """Typed input for diagnostics evaluation."""
    trace: az.InferenceData
    frame: Dict[str, Any]
    meta: FHModelMeta
    model_type: str = "shared"  # "shared" for Model A, "market_specific" for Model C
    params: Optional[FHPosteriorParams | FHMarketSpecificPosteriorParams] = None
    roi_bounds: Optional[Dict[str, tuple[float, float]]] = None
    credible_mass: float = 0.9
    predictive_replications: int = 1
    random_seed: Optional[int] = None
    # Backtest support — when backtest_folds > 0, a backtest is run.
    # Requires a fit_fold_fn that fits the model on train and predicts test.
    backtest_folds: int = 0
    fit_fold_fn: Optional[Any] = None
    min_train_frac: float = 0.6


@dataclass
class DiagnosticsResult:
    """Structured diagnostics output with governance-relevant metadata.

    No hard-coded thresholds. Convergence metrics are raw values; callers
    apply policies.
    """
    scorecard: Dict[str, Any]
    max_rhat: float
    min_ess: float
    has_divergences: bool
    mean_ppc_coverage_pct: float
    ppc_details: Optional[pd.DataFrame] = None
    backtest_results: Optional[pd.DataFrame] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    diagnostics_version: str = "1.0.0"

    @property
    def convergence_ok(self) -> bool:
        """Backward-compatible property. Note: thresholds should come
        from a validation policy, not this property."""
        return (self.max_rhat < 1.05 and self.min_ess > 200
                and not self.has_divergences)


class DiagnosticsService:
    """Application service for model diagnostics.

    Dispatches to the correct scorecard based on ``model_type``.

    Usage::

        service = DiagnosticsService()
        result = service.evaluate(input_data)
        if result.errors:
            # handle errors
    """

    def evaluate(self, diag_input: DiagnosticsInput) -> DiagnosticsResult:
        """Run diagnostics and return a structured result.

        Does not access Streamlit session state, mutate global state, or
        render any UI.
        """
        errors: List[str] = []
        warnings: List[str] = []

        if diag_input.trace is None:
            errors.append("No posterior trace provided.")
            return DiagnosticsResult(
                scorecard={}, max_rhat=float("nan"), min_ess=float("nan"),
                has_divergences=False, mean_ppc_coverage_pct=float("nan"),
                errors=errors,
            )

        # --- Convergence diagnostics (raw values, no thresholds) ---
        try:
            max_rhat, min_ess, has_div = self._check_convergence(diag_input.trace)
        except Exception as exc:
            errors.append(f"Convergence check failed: {exc}")
            max_rhat, min_ess, has_div = float("nan"), float("nan"), True

        # --- Scorecard (dispatch by model type) ---
        try:
            if diag_input.model_type == "market_specific":
                scorecard = compute_scorecard_market_specific(
                    diag_input.trace, diag_input.frame, diag_input.meta,
                    roi_bounds=diag_input.roi_bounds,
                )
            else:
                scorecard = compute_scorecard(
                    diag_input.trace, diag_input.frame, diag_input.meta,
                    roi_bounds=diag_input.roi_bounds,
                )
        except Exception as exc:
            errors.append(f"Scorecard computation failed: {exc}")
            scorecard = {}

        # --- PPC coverage (single authoritative calculation) ---
        ppc_details = None
        mean_ppc = float("nan")
        try:
            ppc_details = posterior_predictive_coverage(
                diag_input.trace, diag_input.frame, diag_input.meta,
                credible_mass=diag_input.credible_mass,
                predictive_replications=diag_input.predictive_replications,
                random_seed=diag_input.random_seed,
            )
            mean_ppc = float(ppc_details["coverage_pct"].mean())
        except Exception as exc:
            errors.append(f"PPC coverage failed: {exc}")

        # --- Curve plausibility ---
        try:
            if diag_input.model_type == "market_specific":
                plausibility = curve_plausibility_checks_market_specific(
                    diag_input.trace, diag_input.meta, diag_input.frame,
                    roi_bounds=diag_input.roi_bounds,
                )
            else:
                plausibility = curve_plausibility_checks(
                    diag_input.trace, diag_input.meta, diag_input.frame,
                    roi_bounds=diag_input.roi_bounds,
                )
            for issue in plausibility:
                warnings.append(
                    f"[{issue.get('level', 'info')}] "
                    f"{issue.get('channel', '?')}: {issue.get('message', '')}"
                )
        except Exception as exc:
            warnings.append(f"Plausibility checks failed: {exc}")

        # --- Backtest (only when folds > 0 and a fit function is provided) ---
        backtest_results = None
        if diag_input.backtest_folds > 0 and diag_input.fit_fold_fn is not None:
            try:
                backtest_results = expanding_window_backtest(
                    diag_input.frame if isinstance(diag_input.frame, pd.DataFrame)
                    else pd.DataFrame(),
                    diag_input.meta,  # spec-like object
                    diag_input.fit_fold_fn,
                    n_folds=diag_input.backtest_folds,
                    min_train_frac=diag_input.min_train_frac,
                )
            except Exception as exc:
                warnings.append(f"Backtest failed (non-fatal): {exc}")

        return DiagnosticsResult(
            scorecard=scorecard,
            max_rhat=max_rhat,
            min_ess=min_ess,
            has_divergences=has_div,
            mean_ppc_coverage_pct=mean_ppc,
            ppc_details=ppc_details,
            backtest_results=backtest_results,
            warnings=warnings,
            errors=errors,
        )

    @staticmethod
    def _check_convergence(trace: az.InferenceData) -> tuple[float, float, bool]:
        """Extract raw convergence metrics from the trace.

        Returns ``(max_rhat, min_ess, has_divergences)`` — raw values,
        no thresholds applied.
        """
        rhat = az.rhat(trace, var_names=["mu", "beta", "hill_K", "alpha"])
        ess = az.ess(trace, var_names=["mu", "beta", "hill_K", "alpha"])

        max_rhat = float("-inf")
        for var_data in rhat.values():
            if hasattr(var_data, "values"):
                max_rhat = max(max_rhat, float(var_data.values.max()))

        min_ess = float("inf")
        for var_data in ess.values():
            if hasattr(var_data, "values"):
                min_ess = min(min_ess, float(var_data.values.min()))

        has_div = False
        if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
            has_div = bool(trace.sample_stats["diverging"].values.any())

        return max_rhat, min_ess, has_div
