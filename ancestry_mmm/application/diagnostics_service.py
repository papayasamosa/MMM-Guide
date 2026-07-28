"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 6: Separates diagnostic execution from Streamlit page rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.diagnostics import (
    compute_scorecard,
    posterior_predictive_coverage,
    in_sample_fit,
    curve_plausibility_checks,
    expanding_window_backtest,
)
from ancestry_mmm.core.predict import FHPosteriorParams, extract_posterior_params


@dataclass
class DiagnosticsInput:
    """Typed input for diagnostics evaluation."""
    trace: az.InferenceData
    frame: Dict[str, Any]
    meta: FHModelMeta
    params: Optional[FHPosteriorParams] = None
    roi_bounds: Optional[Dict[str, tuple[float, float]]] = None
    backtest_folds: int = 3
    credible_mass: float = 0.9
    predictive_replications: int = 1
    random_seed: Optional[int] = None


@dataclass
class DiagnosticsResult:
    """Structured diagnostics output with governance-relevant metadata."""
    scorecard: Dict[str, Any]
    convergence_ok: bool
    has_divergences: bool
    max_rhat: float
    min_ess: float
    mean_ppc_coverage_pct: float
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    diagnostics_version: str = "1.0.0"


class DiagnosticsService:
    """Application service for model diagnostics.

    Usage::

        service = DiagnosticsService()
        result = service.evaluate(input_data)
        if result.errors:
            # handle errors
            ...
    """

    def evaluate(self, diag_input: DiagnosticsInput) -> DiagnosticsResult:
        """Run the full diagnostics scorecard and return a structured result.

        Does not access Streamlit session state, mutate global state, or
        render any UI.
        """
        errors: List[str] = []
        warnings: List[str] = []

        # Validate inputs
        if diag_input.trace is None:
            errors.append("No posterior trace provided.")
            return DiagnosticsResult(
                scorecard={},
                convergence_ok=False,
                has_divergences=False,
                max_rhat=float("nan"),
                min_ess=float("nan"),
                mean_ppc_coverage_pct=float("nan"),
                errors=errors,
            )

        # Compute convergence diagnostics
        try:
            convergence = self._check_convergence(diag_input.trace)
        except Exception as exc:
            errors.append(f"Convergence check failed: {exc}")
            convergence = {"max_rhat": float("nan"), "min_ess": float("nan"), "has_divergences": True}

        # Compute full scorecard
        try:
            scorecard = compute_scorecard(
                diag_input.trace,
                diag_input.frame,
                diag_input.meta,
                roi_bounds=diag_input.roi_bounds,
            )
        except Exception as exc:
            errors.append(f"Scorecard computation failed: {exc}")
            scorecard = {}

        # PPC coverage
        try:
            ppc_result = posterior_predictive_coverage(
                diag_input.trace,
                diag_input.frame,
                diag_input.meta,
                credible_mass=diag_input.credible_mass,
                predictive_replications=diag_input.predictive_replications,
                random_seed=diag_input.random_seed,
            )
            mean_ppc = float(ppc_result["coverage_pct"].mean())
        except Exception as exc:
            errors.append(f"PPC coverage failed: {exc}")
            ppc_result = pd.DataFrame()
            mean_ppc = float("nan")

        # Curve plausibility
        try:
            plausibility = curve_plausibility_checks(
                diag_input.trace,
                diag_input.meta,
                diag_input.frame,
                roi_bounds=diag_input.roi_bounds,
            )
            for issue in plausibility:
                warnings.append(f"[{issue.get('level', 'info')}] {issue.get('channel', '?')}: {issue.get('message', '')}")
        except Exception as exc:
            warnings.append(f"Plausibility checks failed: {exc}")

        return DiagnosticsResult(
            scorecard=scorecard,
            convergence_ok=(
                convergence.get("max_rhat", float("inf")) < 1.05
                and convergence.get("min_ess", 0) > 200
                and not convergence.get("has_divergences", True)
            ),
            has_divergences=convergence.get("has_divergences", True),
            max_rhat=convergence.get("max_rhat", float("nan")),
            min_ess=convergence.get("min_ess", float("nan")),
            mean_ppc_coverage_pct=mean_ppc,
            warnings=warnings,
            errors=errors,
        )

    def _check_convergence(self, trace: az.InferenceData) -> dict:
        """Extract convergence diagnostics from the trace."""
        import arviz as az

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

        # Check for divergences
        has_div = False
        if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
            has_div = bool(trace.sample_stats["diverging"].values.any())

        return {
            "max_rhat": max_rhat,
            "min_ess": min_ess,
            "has_divergences": has_div,
        }
