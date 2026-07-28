"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 51B: Supports Model A (shared) and Model C (market-specific) scorecards.
No hard-coded convergence thresholds — thresholds come from policy.
One authoritative PPC calculation (not double-counted).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams


@dataclass(frozen=True)
class DiagnosticsArtefact:
    """Immutable, fingerprinted artefact capturing diagnostics evidence.

    PR 56F: Binds model identity, convergence metrics, scorecard, PPC,
    plausibility, identification diagnostics, and backtest results into
    a single auditable proof. The ``fingerprint()`` is derived from all
    fields, so any change in diagnostics invalidates the artefact.
    """

    artefact_id: str = ""
    diagnostics_version: str = "1.0.0"
    model_identity_fingerprint: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    max_rhat: float = 0.0
    min_ess: float = 0.0
    has_divergences: bool = False
    mean_ppc_coverage_pct: float = 0.0
    scorecard_fields: tuple[str, ...] = field(default_factory=tuple)
    plausibility_issues: int = 0
    identification_condition_number: float = 0.0
    backtest_folds: int = 0
    backtest_mean_mape: Optional[float] = None
    settings: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    schema_version: int = 1

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of this artefact."""
        payload = {
            "artefact_id": self.artefact_id,
            "diagnostics_version": self.diagnostics_version,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "evaluated_at": self.evaluated_at.isoformat(),
            "max_rhat": self.max_rhat,
            "min_ess": self.min_ess,
            "has_divergences": self.has_divergences,
            "mean_ppc_coverage_pct": self.mean_ppc_coverage_pct,
            "scorecard_fields": sorted(self.scorecard_fields),
            "plausibility_issues": self.plausibility_issues,
            "identification_condition_number": self.identification_condition_number,
            "backtest_folds": self.backtest_folds,
            "backtest_mean_mape": self.backtest_mean_mape,
            "settings": tuple(sorted(self.settings)),
            "schema_version": self.schema_version,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass
class DiagnosticsInput:
    """Typed input for diagnostics evaluation.

    PR 56F: Includes explicit ``model_identity`` so the diagnostics
    artefact can be bound to the exact model run.
    """

    trace: az.InferenceData
    frame: Dict[str, Any]
    meta: FHModelMeta
    model_type: str = "shared"  # "shared" for Model A, "market_specific" for Model C
    model_identity: Optional[ModelIdentity] = None
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

    PR 56F: Includes a ``diagnostics_artefact`` that captures the complete
    evidence in a fingerprinted, auditable form.
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
    diagnostics_artefact: Optional[DiagnosticsArtefact] = None

    @property
    def convergence_ok(self) -> bool:
        """Backward-compatible property. Note: thresholds should come
        from a validation policy, not this property."""
        return self.max_rhat < 1.05 and self.min_ess > 200 and not self.has_divergences


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
                scorecard={},
                max_rhat=float("nan"),
                min_ess=float("nan"),
                has_divergences=False,
                mean_ppc_coverage_pct=float("nan"),
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
                    diag_input.trace,
                    diag_input.frame,
                    diag_input.meta,
                    roi_bounds=diag_input.roi_bounds,
                )
            else:
                scorecard = compute_scorecard(
                    diag_input.trace,
                    diag_input.frame,
                    diag_input.meta,
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
                diag_input.trace,
                diag_input.frame,
                diag_input.meta,
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
                    diag_input.trace,
                    diag_input.meta,
                    diag_input.frame,
                    roi_bounds=diag_input.roi_bounds,
                )
            else:
                plausibility = curve_plausibility_checks(
                    diag_input.trace,
                    diag_input.meta,
                    diag_input.frame,
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
                    diag_input.frame
                    if isinstance(diag_input.frame, pd.DataFrame)
                    else pd.DataFrame(),
                    diag_input.meta,  # spec-like object
                    diag_input.fit_fold_fn,
                    n_folds=diag_input.backtest_folds,
                    min_train_frac=diag_input.min_train_frac,
                )
            except Exception as exc:
                warnings.append(f"Backtest failed (non-fatal): {exc}")

        # --- Build fingerprinted artefact ---
        identity_fp = (
            diag_input.model_identity.fingerprint()
            if diag_input.model_identity is not None
            else ""
        )
        backtest_mean_mape = None
        if backtest_results is not None and not backtest_results.empty:
            try:
                backtest_mean_mape = float(backtest_results["mape"].mean())
            except (KeyError, TypeError, ValueError):
                pass
        artefact = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version="1.0.0",
            model_identity_fingerprint=identity_fp,
            evaluated_at=datetime.now(timezone.utc),
            max_rhat=max_rhat,
            min_ess=min_ess,
            has_divergences=has_div,
            mean_ppc_coverage_pct=mean_ppc,
            scorecard_fields=tuple(sorted(scorecard.keys())) if scorecard else (),
            plausibility_issues=len(
                [w for w in warnings if w.startswith("[") and "plausibility" not in w]
            ),
            identification_condition_number=0.0,
            backtest_folds=diag_input.backtest_folds,
            backtest_mean_mape=backtest_mean_mape,
            settings=(
                ("credible_mass", str(diag_input.credible_mass)),
                ("predictive_replications", str(diag_input.predictive_replications)),
                ("random_seed", str(diag_input.random_seed)),
                ("model_type", diag_input.model_type),
            ),
            schema_version=1,
        )

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
            diagnostics_artefact=artefact,
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
