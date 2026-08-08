"""
Diagnostics service — provides model diagnostics and scorecard evaluation
without Streamlit dependencies.

PR 72B: Canonical diagnostics evidence. Each diagnostic is computed once
and stored in a fingerprinted DiagnosticsArtefact (schema v3, see
``CURRENT_DIAGNOSTICS_SCHEMA_VERSION`` below - schema v2 at PR 72B's
original introduction) with full serialisable payloads and explicit
section statuses. No missing evidence is encoded as zero. ValidationService
reads metrics from this artefact rather than recomputing them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

import pandas as pd
import arviz as az

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.diagnostics import (
    error_metrics_by_outcome,
    in_sample_fit,
    posterior_predictive_coverage,
    curve_plausibility_checks,
    expanding_window_backtest,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.market_specific_diagnostics import (
    error_metrics_by_outcome_market_specific,
    in_sample_fit_market_specific,
    curve_plausibility_checks_market_specific,
    residual_temporal_diagnostics_market_specific,
)
from ancestry_mmm.core.identification_diagnostics import (
    channel_spend_correlation_matrix,
    design_matrix_condition_number,
    identification_report,
    posterior_coefficient_stability,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.predict import FHPosteriorParams, extract_posterior_params
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    extract_market_specific_posterior_params,
)

# ---------------------------------------------------------------------------
# Diagnostics version authority (Work Package 1)
# ---------------------------------------------------------------------------
#
# Single source of truth for the current diagnostics schema/calculation
# identity. Every current-code default and every newly-evaluated result
# must use these constants rather than a separately hardcoded literal -
# that drift (``DiagnosticsArtefact`` defaulting to "3.0.0",
# ``DiagnosticsResult`` defaulting to "2.0.0", ``evaluate()`` stamping
# "3.1.0") is exactly what let a direct construction or an error/no-trace
# result silently carry an obsolete version distinct from what a
# successful ``evaluate()`` call produces.
#
# Historical persisted evidence is never rewritten: ``DiagnosticsArtefact.
# from_dict`` keeps its own historical fallbacks ("1.0.0" for schema v1,
# "2.0.0" for schema v2) exactly as before - those describe what a
# *pre-existing* artefact was actually computed as, not what current code
# should default to.
CURRENT_DIAGNOSTICS_SCHEMA_VERSION = 3
CURRENT_DIAGNOSTICS_VERSION = "3.1.0"

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
# DiagnosticsArtefact — schema v3
# ---------------------------------------------------------------------------


def _validate_diagnostics_schema_version(raw: Any) -> int:
    """Strict `schema_version` validation for `DiagnosticsArtefact.from_dict`
    (Work Package 2 corrective fix, mirroring
    `core.search_objects._validate_search_object_schema_version`). Plain
    `==`/`in` dispatch is not validation: `bool` is an `int` subclass in
    Python (`True == 1`), and `float`/`int` compare equal when numerically
    equal (`2.0 in (2, 3)`), so either would previously have silently
    masqueraded as a genuine integer schema version. Only an actual `int`
    (never `bool`) that is `>= 1` is accepted here; whether a given integer
    value is a *supported* version is decided by the dispatch that calls
    this, not here.
    """
    if isinstance(raw, bool) or type(raw) is not int:
        raise ValueError(
            f"DiagnosticsArtefact schema_version must be an integer, got "
            f"{raw!r} (type={type(raw).__name__})"
        )
    if raw < 1:
        raise ValueError(f"DiagnosticsArtefact schema_version must be >= 1, got {raw}")
    return raw


@dataclass(frozen=True)
class DiagnosticsArtefact:
    """Immutable, fingerprinted artefact capturing diagnostics evidence.

    PR 72B: Schema v2 stores complete serialisable payloads in each
    diagnostics section rather than headline summaries only. The
    fingerprint covers every material piece of evidence.

    REQ-VAL-001 (UK-pilot evidence expansion): Schema v3 adds
    ``error_metrics`` (MAE/RMSE/sMAPE/WAPE/bias per outcome_id -
    core.diagnostics.error_metrics_by_outcome) and
    ``residual_diagnostics`` (lag-1 autocorrelation/Durbin-Watson per
    outcome_id - core.diagnostics.residual_temporal_diagnostics) as
    additional, purely additive evidence sections alongside the existing
    seven - neither introduces a blocking threshold (evidence computation
    and approval policy remain separate; an approved policy decides
    thresholds later, per REQ-VAL-001's "Requirements discipline").

    Work Package 2 corrective fix: ``residual_diagnostics``'s underlying
    calculation (``core.diagnostics.residual_temporal_diagnostics`` / the
    market-specific equivalent) changed from one row per outcome_id
    (computed by concatenating every market's residuals - which formed an
    invalid cross-market lag pair at each market boundary) to one row per
    market x outcome_id, computed within each market's own chronological
    slice. ``schema_version`` stays 3 - the section's serialized *shape* is
    still a list of JSON-safe records, so this is not a structural schema
    break requiring a new migration - but ``DiagnosticsService.evaluate()``
    now stamps newly-computed artefacts with ``diagnostics_version
    "3.1.0"`` (bumped from ``"3.0.0"``) to record the calculation change.
    An already-persisted artefact with ``diagnostics_version "3.0.0"``
    remains loadable exactly as-is (``from_dict`` never reinterprets a
    stored payload) - its ``residual_diagnostics`` rows are outcome-only,
    computed by the pre-fix concatenated method, and must never be silently
    treated as if they were produced by the market-safe method.

    Note: ``diagnostics_version`` is a whole-artefact string, not a
    per-section calculation identifier - it changes whenever a computed
    artefact's *calculation methodology* changes materially enough to be
    worth distinguishing from prior evidence, the same role it already
    played when schema v3 was introduced (``diagnostics_version`` and
    ``schema_version`` were bumped together then). ``fingerprint()``'s
    formula/key set is unchanged - ``diagnostics_version`` was already one
    of its hashed fields, so bumping it is itself evidence-content drift
    (a readiness bound to a "3.0.0" artefact already fails to match a
    freshly-recomputed "3.1.0" fingerprint), not a special exemption from
    the ordinary fingerprint mechanism.

    Work Package 1: this class's ``diagnostics_version``/``schema_version``
    field defaults now come from the module-level ``CURRENT_DIAGNOSTICS_
    VERSION``/``CURRENT_DIAGNOSTICS_SCHEMA_VERSION`` constants rather than a
    separately hardcoded literal, so a directly-constructed artefact (e.g.
    a test fixture, or ``evaluate()``'s no-trace/error result via
    ``DiagnosticsResult``'s matching default) can never silently diverge
    from what a successful ``evaluate()`` call stamps. Imported/historical
    artefacts are unaffected - ``from_dict`` keeps its own explicit
    historical fallbacks.

    Schema-v1 artefacts loaded via ``from_dict`` are marked
    ``legacy_incomplete`` and cannot support a new official approval.
    Schema-v2 artefacts are upgraded to v3 with ``error_metrics``/
    ``residual_diagnostics`` marked ``not_computed`` (that evidence simply
    did not exist yet when they were computed) - v2 was already complete
    for the sections it claimed, so it is *not* marked
    ``legacy_incomplete``: an artefact predating an additive evidence
    category is a different thing from one that silently dropped evidence
    it claimed to have (the v1 case).
    """

    artefact_id: str = ""
    diagnostics_version: str = CURRENT_DIAGNOSTICS_VERSION
    schema_version: int = CURRENT_DIAGNOSTICS_SCHEMA_VERSION
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
    error_metrics: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    residual_diagnostics: DiagnosticSection = field(
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
            "error_metrics": self.error_metrics.fingerprint_payload(),
            "residual_diagnostics": self.residual_diagnostics.fingerprint_payload(),
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
            "error_metrics": self.error_metrics.to_dict(),
            "residual_diagnostics": self.residual_diagnostics.to_dict(),
            "global_warnings": list(self.global_warnings),
            "global_errors": list(self.global_errors),
            "settings": list(self.settings),
            "legacy_incomplete": self.legacy_incomplete,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DiagnosticsArtefact":
        """Load from a dict. Supports schema v1 (legacy_incomplete), v2
        (upgraded in place to the v3 shape - see the class docstring for why
        this is not also marked legacy_incomplete) and v3.

        `schema_version` is validated strictly via
        `_validate_diagnostics_schema_version` when the key is present -
        Python's `==`/`in` equality would otherwise let a `bool` (`True ==
        1`) or a `float` (`2.0 in (2, 3)`) silently masquerade as an actual
        integer schema version (Work Package 2 corrective fix). A genuinely
        absent `schema_version` key still takes the documented legacy
        default of 1 (an artefact predating schema versioning entirely).
        """
        sv = (
            _validate_diagnostics_schema_version(d["schema_version"])
            if "schema_version" in d
            else 1
        )
        if sv == 1:
            # Schema v1 → wrap summaries into sections, mark legacy_incomplete
            return cls._from_v1(d)
        if sv in (2, 3):
            if sv >= 3:
                error_metrics_sec = DiagnosticSection.from_dict(
                    d.get("error_metrics", {})
                )
                residual_diagnostics_sec = DiagnosticSection.from_dict(
                    d.get("residual_diagnostics", {})
                )
            else:
                # REQ-VAL-001: this evidence category did not exist when a
                # schema-v2 artefact was computed - not_computed, never a
                # fabricated payload.
                error_metrics_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error="Not available in schema v2 - error-metric "
                    "evidence (MAE/RMSE/sMAPE/WAPE/bias) was added in "
                    "schema v3.",
                )
                residual_diagnostics_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error="Not available in schema v2 - residual temporal "
                    "diagnostics (lag-1 autocorrelation/Durbin-Watson) "
                    "were added in schema v3.",
                )
            return cls(
                artefact_id=d.get("artefact_id", ""),
                diagnostics_version=d.get("diagnostics_version", "2.0.0"),
                schema_version=sv,
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
                error_metrics=error_metrics_sec,
                residual_diagnostics=residual_diagnostics_sec,
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

    PR 72B/PR 80A: Includes explicit data and spec fields for backtest so the
    service does not pass an empty DataFrame or FHModelMeta (which has no
    ``date_col``) as the ``ModelSpec`` that ``expanding_window_backtest``
    requires.
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
    raw_model_spec: Optional[ModelSpec] = None


@dataclass
class DiagnosticsResult:
    """Structured diagnostics output with governance-relevant metadata.

    PR 72B: The ``diagnostics_artefact`` is the authoritative evidence
    container. Legacy summary fields are retained for backward
    compatibility but derived from the artefact.

    Work Package 1: ``diagnostics_version`` defaults to the same
    ``CURRENT_DIAGNOSTICS_VERSION`` constant ``DiagnosticsArtefact`` uses,
    so ``DiagnosticsService.evaluate()``'s no-trace/error early-return
    (which constructs this dataclass without an explicit
    ``diagnostics_version``) reports the current version rather than a
    stale hardcoded one - it never carries a computed artefact, but the
    version identity it reports must still not silently regress.
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
    diagnostics_version: str = CURRENT_DIAGNOSTICS_VERSION
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
        """Run diagnostics and return a structured result with a current-schema artefact."""
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

        # --- 2b/2c. Error metrics (MAE/RMSE/sMAPE/WAPE/bias) and residual
        # temporal diagnostics (lag-1 autocorrelation/Durbin-Watson) - REQ-
        # VAL-001 UK-pilot evidence expansion. Independent single-authoritative
        # calculations, alongside (never inside) in-sample fit above, so a
        # failure in one never hides the other. Deliberately reports evidence
        # only - no blocking threshold is introduced here. ---
        error_metrics_sec: DiagnosticSection
        residual_diagnostics_sec: DiagnosticSection
        try:
            if diag_input.model_type == "market_specific":
                market_em_params = extract_market_specific_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                error_df = error_metrics_by_outcome_market_specific(
                    diag_input.frame, diag_input.meta, market_em_params
                )
                residual_df = residual_temporal_diagnostics_market_specific(
                    diag_input.frame, diag_input.meta, market_em_params
                )
            else:
                shared_em_params = extract_posterior_params(
                    diag_input.trace, diag_input.meta
                )
                error_df = error_metrics_by_outcome(
                    diag_input.frame, diag_input.meta, shared_em_params
                )
                residual_df = residual_temporal_diagnostics(
                    diag_input.frame, diag_input.meta, shared_em_params
                )
            error_metrics_sec = DiagnosticSection(
                status="computed", payload=error_df.to_dict(orient="records")
            )
            residual_diagnostics_sec = DiagnosticSection(
                status="computed", payload=residual_df.to_dict(orient="records")
            )
        except Exception as exc:
            errors.append(f"Error metrics / residual diagnostics failed: {exc}")
            error_metrics_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )
            residual_diagnostics_sec = DiagnosticSection(
                status="failed", payload=None, error=str(exc)
            )

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

        # --- 5. Identification: correlation matrix, condition number and
        # the combined flag report (single authoritative calculation - the
        # only place these three signals are computed; a leave-one-channel-
        # out refit sensitivity check is not included here, since it needs
        # a full model refit per channel and has no place in a single-pass
        # evaluate() call) ---
        ident_sec: DiagnosticSection
        try:
            corr_df = channel_spend_correlation_matrix(
                diag_input.frame, diag_input.meta
            )
            condition_number = design_matrix_condition_number(diag_input.frame)
            id_flags = identification_report(
                diag_input.frame, diag_input.meta, diag_input.trace
            )
            for flag in id_flags:
                warnings.append(
                    f"[{flag.get('level', 'info')}] "
                    f"{flag.get('channel', '?')}: {flag.get('message', '')}"
                )
            ident_sec = DiagnosticSection(
                status="computed",
                payload={
                    "flags": id_flags,
                    "correlation_matrix": json.loads(corr_df.to_json(orient="index")),
                    # Stored as a JSON-safe string when infinite (a
                    # deliberate, meaningful value for a degenerate design
                    # matrix - see design_matrix_condition_number's
                    # docstring - not an error to hide), matching how it is
                    # already displayed.
                    "condition_number": condition_number
                    if condition_number != float("inf")
                    else "inf",
                },
            )
        except Exception as exc:
            errors.append(f"Identification diagnostics failed: {exc}")
            ident_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

        # --- 6. Coefficient stability (single authoritative calculation) ---
        stab_sec: DiagnosticSection
        try:
            stability_df = posterior_coefficient_stability(
                diag_input.trace, diag_input.meta
            )
            stab_sec = DiagnosticSection(
                status="computed",
                payload=stability_df.to_dict(orient="records"),
            )
        except Exception as exc:
            errors.append(f"Coefficient stability computation failed: {exc}")
            stab_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))

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
            elif diag_input.raw_model_spec is None:
                bt_sec = DiagnosticSection(
                    status="failed",
                    payload=None,
                    error=(
                        "Backtest requested but no ModelSpec available "
                        "(raw_model_spec is required; FHModelMeta has no "
                        "date_col and cannot substitute for it)."
                    ),
                )
            else:
                try:
                    backtest_results = expanding_window_backtest(
                        bt_df,
                        diag_input.raw_model_spec,
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
            diagnostics_version=CURRENT_DIAGNOSTICS_VERSION,
            schema_version=CURRENT_DIAGNOSTICS_SCHEMA_VERSION,
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
            error_metrics=error_metrics_sec,
            residual_diagnostics=residual_diagnostics_sec,
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
            diagnostics_version=CURRENT_DIAGNOSTICS_VERSION,
            diagnostics_artefact=artefact,
        )

    def run_backtest(
        self,
        artefact: DiagnosticsArtefact,
        *,
        raw_model_dataframe: pd.DataFrame,
        raw_model_spec: ModelSpec,
        fit_fold_fn: Callable,
        n_folds: int,
        min_train_frac: float = 0.6,
    ) -> DiagnosticsArtefact:
        """Run an expanding-window backtest and return a new artefact with
        only the ``backtest`` section replaced.

        PR 82B: a pure, immutable update path for the canonical artefact -
        every other already-computed section (convergence, fit, PPC,
        plausibility, identification, coefficient stability) is carried
        over unchanged, never recomputed. Callers must re-evaluate
        readiness against the returned artefact, since its fingerprint
        changes whenever the backtest section changes.
        """
        try:
            backtest_results = expanding_window_backtest(
                raw_model_dataframe,
                raw_model_spec,
                fit_fold_fn,
                n_folds=n_folds,
                min_train_frac=min_train_frac,
            )
            bt_sec = DiagnosticSection(
                status="computed",
                payload=backtest_results.to_dict(orient="records"),
            )
        except Exception as exc:
            bt_sec = DiagnosticSection(status="failed", payload=None, error=str(exc))
        return dataclasses.replace(artefact, backtest=bt_sec)

    @staticmethod
    def _check_convergence(trace: az.InferenceData) -> tuple[float, float, int]:
        """Extract raw convergence metrics from the trace: max R-hat, min
        ESS, and the divergence count (0 if no divergences or no
        sample_stats) - the single authoritative convergence calculation
        reused for both the artefact and the displayed scorecard."""
        # A degenerate/zero-variance chain makes ArviZ's own rank-normalised
        # R-hat divide 0/0 internally (arviz/stats/diagnostics.py) - see
        # ancestry_mmm/core/models.py's compute_model_diagnostics for the
        # full rationale. Suppressed only around this exact call.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="invalid value encountered in scalar divide",
                category=RuntimeWarning,
            )
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
