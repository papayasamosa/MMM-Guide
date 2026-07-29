"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 72B: Canonical diagnostics evidence. Each diagnostic is computed once
and stored in a schema-v2 DiagnosticsArtefact with full serialisable
payloads and explicit section statuses. No missing evidence is encoded as
zero. ValidationService reads metrics from this artefact rather than
recomputing them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import pandas as pd
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.diagnostics import (
    in_sample_fit,
    posterior_predictive_coverage,
    curve_plausibility_checks,
    expanding_window_backtest,
)
from ancestry_mmm.core.market_specific_diagnostics import (
    in_sample_fit_market_specific,
    curve_plausibility_checks_market_specific,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.predict import FHPosteriorParams, extract_posterior_params
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
)

# ---------------------------------------------------------------------------
# Section status
# ---------------------------------------------------------------------------

DiagnosticSectionStatus = Literal[
    "computed",
    "not_computed",
    "failed",
    "not_applicable",
]


@dataclass(frozen=True)
class DiagnosticSection:
    """A single diagnostics section with explicit status, payload and errors.

    Rules:
    - ``computed`` requires a non-None payload.
    - ``failed`` requires a non-blank error string.
    - ``not_computed`` explains why the section was skipped.
    - ``not_applicable`` explains why the section does not apply.
    - Missing evidence is never encoded as zero.
    """

    status: DiagnosticSectionStatus
    payload: Any = None
    error: str = ""
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == "failed" and not self.error:
            raise ValueError("Failed section must have a non-blank error string.")
        if self.status == "computed" and self.payload is None:
            raise ValueError("Computed section must have a non-None payload.")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "payload": self._serialize_payload(),
            "error": self.error,
            "warnings": list(self.warnings),
        }

    def _serialize_payload(self) -> Any:
        if isinstance(self.payload, pd.DataFrame):
            return json.loads(self.payload.to_json(orient="records", date_format="iso"))
        if isinstance(self.payload, pd.Series):
            return json.loads(self.payload.to_json(orient="index", date_format="iso"))
        return self.payload

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DiagnosticSection":
        return cls(
            status=d["status"],
            payload=d.get("payload"),
            error=d.get("error", ""),
            warnings=tuple(d.get("warnings", [])),
        )

    def fingerprint_payload(self) -> str:
        raw = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# DiagnosticsArtefact — schema v2
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DiagnosticsArtefact:
    """Immutable, fingerprinted artefact capturing diagnostics evidence.

    PR 72B: Schema v2 stores complete serialisable payloads in each
    diagnostics section rather than headline summaries only. The
    fingerprint covers every material piece of evidence.

    Schema-v1 artefacts loaded via ``from_dict`` are marked
    ``legacy_incomplete`` and cannot support a new official approval.
    """

    artefact_id: str = ""
    diagnostics_version: str = "2.0.0"
    schema_version: int = 2
    model_identity_fingerprint: str = ""
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    model_type: str = ""
    market_scope: str = ""

    # Diagnostics sections (each with explicit status)
    convergence: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    in_sample_fit: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    posterior_predictive: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    plausibility: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    identification: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    coefficient_stability: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    backtest: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )

    # Global warnings and errors
    global_warnings: Tuple[str, ...] = ()
    global_errors: Tuple[str, ...] = ()

    # Settings snapshot
    settings: Tuple[Tuple[str, str], ...] = ()

    # Legacy marker
    legacy_incomplete: bool = False

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint covering all material evidence."""
        payload = {
            "schema_version": self.schema_version,
            "diagnostics_version": self.diagnostics_version,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "evaluated_at": self.evaluated_at.isoformat(),
            "model_type": self.model_type,
            "market_scope": self.market_scope,
            "convergence": self.convergence.fingerprint_payload(),
            "in_sample_fit": self.in_sample_fit.fingerprint_payload(),
            "posterior_predictive": self.posterior_predictive.fingerprint_payload(),
            "plausibility": self.plausibility.fingerprint_payload(),
            "identification": self.identification.fingerprint_payload(),
            "coefficient_stability": self.coefficient_stability.fingerprint_payload(),
            "backtest": self.backtest.fingerprint_payload(),
            "global_warnings": sorted(self.global_warnings),
            "global_errors": sorted(self.global_errors),
            "settings": tuple(sorted(self.settings)),
            "legacy_incomplete": self.legacy_incomplete,
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Stable serialisation to a JSON-compatible dict."""
        return {
            "artefact_id": self.artefact_id,
            "diagnostics_version": self.diagnostics_version,
            "schema_version": self.schema_version,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "evaluated_at": self.evaluated_at.isoformat(),
            "model_type": self.model_type,
            "market_scope": self.market_scope,
            "convergence": self.convergence.to_dict(),
            "in_sample_fit": self.in_sample_fit.to_dict(),
            "posterior_predictive": self.posterior_predictive.to_dict(),
            "plausibility": self.plausibility.to_dict(),
            "identification": self.identification.to_dict(),
            "coefficient_stability": self.coefficient_stability.to_dict(),
            "backtest": self.backtest.to_dict(),
            "global_warnings": list(self.global_warnings),
            "global_errors": list(self.global_errors),
            "settings": list(self.settings),
            "legacy_incomplete": self.legacy_incomplete,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DiagnosticsArtefact":
        """Load from a dict. Supports schema v1 (legacy_incomplete)."""
        sv = d.get("schema_version", 1)
        if sv == 1:
            # Schema v1 → wrap summaries into sections, mark legacy_incomplete
            return cls._from_v1(d)
        if sv == 2:
            return cls(
                artefact_id=d.get("artefact_id", ""),
                diagnostics_version=d.get("diagnostics_version", "2.0.0"),
                schema_version=2,
                model_identity_fingerprint=d.get("model_identity_fingerprint", ""),
                evaluated_at=datetime.fromisoformat(d["evaluated_at"])
                if "evaluated_at" in d
                else datetime.now(timezone.utc),
                model_type=d.get("model_type", ""),
                market_scope=d.get("market_scope", ""),
                convergence=DiagnosticSection.from_dict(d.get("convergence", {})),
                in_sample_fit=DiagnosticSection.from_dict(d.get("in_sample_fit", {})),
                posterior_predictive=DiagnosticSection.from_dict(
                    d.get("posterior_predictive", {})
                ),
                plausibility=DiagnosticSection.from_dict(d.get("plausibility", {})),
                identification=DiagnosticSection.from_dict(d.get("identification", {})),
                coefficient_stability=DiagnosticSection.from_dict(
                    d.get("coefficient_stability", {})
                ),
                backtest=DiagnosticSection.from_dict(d.get("backtest", {})),
                global_warnings=tuple(d.get("global_warnings", [])),
                global_errors=tuple(d.get("global_errors", [])),
                settings=tuple(tuple(x) for x in d.get("settings", [])),
                legacy_incomplete=d.get("legacy_incomplete", False),
            )
        raise ValueError(f"Unsupported schema_version: {sv}")

    @classmethod
    def _from_v1(cls, d: Dict[str, Any]) -> "DiagnosticsArtefact":
        """Upgrade a schema-v1 dict to v2, marking it legacy_incomplete."""
        # Build summary-only sections from v1 fields
        convergence_payload = {
            "max_rhat": d.get("max_rhat", 0.0),
            "min_ess": d.get("min_ess", 0.0),
            "has_divergences": d.get("has_divergences", False),
        }
        ppc_payload = {
            "mean_ppc_coverage_pct": d.get("mean_ppc_coverage_pct", 0.0),
        }
        settings_raw = d.get("settings", [])
        if isinstance(settings_raw, list):
            settings_clean = tuple(
                tuple(x) if isinstance(x, (list, tuple)) else (str(x), "")
                for x in settings_raw
            )
        else:
            settings_clean = ()

        return cls(
            artefact_id=d.get("artefact_id", ""),
            diagnostics_version=d.get("diagnostics_version", "1.0.0"),
            schema_version=1,
            model_identity_fingerprint=d.get("model_identity_fingerprint", ""),
            evaluated_at=datetime.fromisoformat(d["evaluated_at"])
            if "evaluated_at" in d
            else datetime.now(timezone.utc),
            convergence=DiagnosticSection(
                status="computed", payload=convergence_payload
            ),
            in_sample_fit=DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Schema v1 did not persist in-sample fit rows.",
            ),
            posterior_predictive=DiagnosticSection(
                status="computed", payload=ppc_payload
            ),
            plausibility=DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Schema v1 did not persist plausibility issues.",
            ),
            identification=DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Schema v1 did not persist identification evidence.",
            ),
            coefficient_stability=DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Schema v1 did not persist coefficient stability.",
            ),
            backtest=DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Schema v1 did not persist backtest details.",
            ),
            global_warnings=tuple(d.get("global_warnings", [])),
            global_errors=tuple(d.get("global_errors", [])),
            settings=settings_clean,
            legacy_incomplete=True,
        )


# ---------------------------------------------------------------------------
# DiagnosticsInput & DiagnosticsResult
# ---------------------------------------------------------------------------


@dataclass
class DiagnosticsInput:
    """Typed input for diagnostics evaluation.

    PR 72B: Includes explicit data and spec fields for backtest so the
    service does not pass an empty DataFrame or FHModelMeta as ModelSpec.
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
    # Backtest support
    backtest_folds: int = 0
    fit_fold_fn: Optional[Callable] = None
    min_train_frac: float = 0.6
    # Canonical data for backtest: raw chronological DataFrame + model spec
    raw_model_dataframe: Optional[pd.DataFrame] = None


@dataclass
class DiagnosticsResult:
    """Structured diagnostics output with governance-relevant metadata.

    PR 72B: The ``diagnostics_artefact`` is the authoritative evidence
    container (schema v2). Legacy summary fields are retained for
    backward compatibility but derived from the artefact.
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
    diagnostics_version: str = "2.0.0"
    diagnostics_artefact: Optional[DiagnosticsArtefact] = None

    @property
    def convergence_ok(self) -> bool:
        """Backward-compatible property."""
        return self.max_rhat < 1.05 and self.min_ess > 200 and not self.has_divergences


# ---------------------------------------------------------------------------
# DiagnosticsService
# ---------------------------------------------------------------------------


class DiagnosticsService:
    """Application service for model diagnostics.

    PR 72B: Computes each diagnostic once. The artefact stores complete
    payloads with explicit section statuses. No missing evidence is
    encoded as zero.
    """

    def evaluate(self, diag_input: DiagnosticsInput) -> DiagnosticsResult:
        """Run diagnostics and return a structured result with a schema-v2 artefact."""
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

        # --- 1. Convergence (single authoritative calculation) ---
        convergence_sec: DiagnosticSection
        try:
            max_rhat, min_ess, divergence_count = self._check_convergence(
                diag_input.trace
            )
            has_div = divergence_count > 0
            # Same convergence formula as the (now removed) duplicate check
            # previously embedded in compute_scorecard()/DiagnosticsResult.
            # convergence_ok - not a new/invented threshold.
            converged = max_rhat < 1.05 and min_ess > 200 and not has_div
            convergence_payload = {
                "max_rhat": max_rhat,
                "min_ess": min_ess,
                "has_divergences": has_div,
                "divergences": divergence_count,
                "converged": converged,
            }
            convergence_sec = DiagnosticSection(
                status="computed",
                payload=convergence_payload,
            )
        except Exception as exc:
            errors.append(f"Convergence check failed: {exc}")
            max_rhat, min_ess, has_div = float("nan"), float("nan"), True
            divergence_count, converged = 0, False
            convergence_payload = {
                "max_rhat": max_rhat,
                "min_ess": min_ess,
                "has_divergences": has_div,
                "divergences": divergence_count,
                "converged": converged,
            }
            convergence_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

        # --- 2. In-sample fit (single authoritative calculation - does not
        # recompute convergence/PPC/plausibility the way compute_scorecard()
        # does internally) ---
        fit_sec: DiagnosticSection
        fit_records: List[Dict[str, Any]] = []
        try:
            if diag_input.model_type == "market_specific":
                market_fit_params = extract_market_specific_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                fit_df = in_sample_fit_market_specific(
                    diag_input.frame, diag_input.meta, market_fit_params
                )
            else:
                shared_fit_params = extract_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                fit_df = in_sample_fit(
                    diag_input.frame, diag_input.meta, shared_fit_params
                )
            fit_records = fit_df.to_dict(orient="records")
            fit_sec = DiagnosticSection(
                status="computed",
                payload=fit_records,
            )
        except Exception as exc:
            errors.append(f"In-sample fit computation failed: {exc}")
            fit_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 3. PPC coverage (single authoritative calculation) ---
        ppc_sec: DiagnosticSection
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
            ppc_sec = DiagnosticSection(
                status="computed", payload=ppc_details.to_dict(orient="records")
            )
        except Exception as exc:
            errors.append(f"PPC coverage failed: {exc}")
            ppc_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 4. Curve plausibility (single authoritative calculation) ---
        plaus_sec: DiagnosticSection
        plausibility: List[Dict[str, str]] = []
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
            plaus_sec = DiagnosticSection(
                status="computed",
                payload=plausibility,
            )
        except Exception as exc:
            warnings.append(f"Plausibility checks failed: {exc}")
            plaus_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 5. Identification (not computed by default) ---
        ident_sec = DiagnosticSection(
            status="not_computed",
            payload=None,
            error="Identification not requested. Call identification_diagnostics() separately.",
        )

        # --- 6. Coefficient stability (not computed by default) ---
        stab_sec = DiagnosticSection(
            status="not_computed",
            payload=None,
            error="Coefficient stability not requested. Call posterior_coefficient_stability() separately.",
        )

        # --- 7. Backtest ---
        bt_sec: DiagnosticSection
        backtest_results = None
        if diag_input.backtest_folds > 0 and diag_input.fit_fold_fn is not None:
            bt_df = diag_input.raw_model_dataframe
            if bt_df is None:
                bt_df = (
                    diag_input.frame
                    if isinstance(diag_input.frame, pd.DataFrame)
                    else None
                )
            if bt_df is None:
                bt_sec = DiagnosticSection(
                    status="failed",
                    payload=None,
                    error="Backtest requested but no raw DataFrame available.",
                )
            else:
                try:
                    backtest_results = expanding_window_backtest(
                        bt_df,
                        diag_input.meta,
                        diag_input.fit_fold_fn,
                        n_folds=diag_input.backtest_folds,
                        min_train_frac=diag_input.min_train_frac,
                    )
                    bt_sec = DiagnosticSection(
                        status="computed",
                        payload=backtest_results.to_dict(orient="records"),
                    )
                except Exception as exc:
                    bt_sec = DiagnosticSection(
                        status="failed", payload=None, error=str(exc)
                    )
        else:
            bt_sec = DiagnosticSection(
                status="not_computed",
                payload=None,
                error="Backtest not requested (backtest_folds <= 0 or no fit_fold_fn).",
            )

        # --- Build fingerprinted artefact ---
        identity_fp = (
            diag_input.model_identity.fingerprint()
            if diag_input.model_identity is not None
            else ""
        )

        artefact = DiagnosticsArtefact(
            artefact_id=uuid.uuid4().hex,
            diagnostics_version="2.0.0",
            schema_version=2,
            model_identity_fingerprint=identity_fp,
            evaluated_at=datetime.now(timezone.utc),
            model_type=diag_input.model_type,
            convergence=convergence_sec,
            in_sample_fit=fit_sec,
            posterior_predictive=ppc_sec,
            plausibility=plaus_sec,
            identification=ident_sec,
            coefficient_stability=stab_sec,
            backtest=bt_sec,
            global_warnings=tuple(warnings),
            global_errors=tuple(errors),
            settings=(
                ("credible_mass", str(diag_input.credible_mass)),
                ("predictive_replications", str(diag_input.predictive_replications)),
                ("random_seed", str(diag_input.random_seed)),
                ("model_type", diag_input.model_type),
            ),
            legacy_incomplete=False,
        )

        # Assemble the displayed scorecard from the same canonical sections
        # computed above - never a separate compute_scorecard() call, so the
        # displayed values and the artefact's values can never diverge.
        scorecard = {
            "convergence": convergence_payload,
            "in_sample_fit": fit_records,
            "ppc_coverage": ppc_details.to_dict(orient="records")
            if ppc_details is not None
            else [],
            "plausibility_flags": plausibility,
        }

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
            diagnostics_version="2.0.0",
            diagnostics_artefact=artefact,
        )

    @staticmethod
    def _check_convergence(trace: az.InferenceData) -> tuple[float, float, int]:
        """Extract raw convergence metrics from the trace: max R-hat, min
        ESS, and the divergence count (0 if no divergences or no
        sample_stats) - the single authoritative convergence calculation
        reused for both the artefact and the displayed scorecard."""
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

        divergence_count = 0
        if hasattr(trace, "sample_stats") and "diverging" in trace.sample_stats:
            divergence_count = int(trace.sample_stats["diverging"].values.sum())

        return max_rhat, min_ess, divergence_count
