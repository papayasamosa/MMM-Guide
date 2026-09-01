"""
Diagnostics artefact schema - the persisted, versioned evidence container
`application.diagnostics_service.DiagnosticsService` computes into and
reads from, plus its typed input/result dataclasses.

Split out of `application.diagnostics_service` (Work Package 3,
`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`, Phase 1 of
`docs/wp3_diagnostics_coupling_refactor_plan.md`): this is pure-data
(dataclasses, dict serialisation, fingerprinting) with no PyMC/Streamlit
dependency and no orchestration logic - `core` is the correct home per
root `AGENTS.md`'s "core for analytical logic; application services for
orchestration" rule, not `application`, where it previously sat only
because the schema and the service that populates it were originally
written together.

`application.diagnostics_service` re-exports every name here
(`from ancestry_mmm.core.diagnostics_artefact import DiagnosticsArtefact,
...`), so every existing caller's `from ancestry_mmm.application.
diagnostics_service import DiagnosticsArtefact`-style import continues to
resolve to the exact same class object, unchanged. This module changed no
field, no serialisation order, no fingerprint computation, and no schema-
version migration behaviour - a pure move, verified by the full existing
`ancestry_mmm/tests/test_diagnostics_artefact.py` suite (130 tests)
passing unmodified.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

import arviz as az
import numpy as np
import pandas as pd

from ancestry_mmm.core.calibration_comparison import (
    CalibratedVsUncalibratedComparisonArtefact,
)
from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.experiments import ExperimentProvenanceReport
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.named_event_fit_inputs import NamedEventFitInputs
from ancestry_mmm.core.latent_state_identification import (
    LatentStateIdentificationDeclaration,
)
from ancestry_mmm.core.market_specific_predict import (
    FHMarketSpecificPosteriorParams,
)
from ancestry_mmm.core.model_identity import ModelIdentity
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_capacity import SearchCandidateASpec
from ancestry_mmm.core.search_objects import SearchObjectDefinition
from ancestry_mmm.core.validation_folds import (
    RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
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
#
# Work Package 2 (REQ-VAL-001 prior predictive evidence): schema v3 -> v4
# adds the ``prior_predictive`` section (``core.diagnostics.
# prior_predictive_summary`` - outcome-scale ``pm.sample_prior_predictive``
# evidence per market x outcome_id, computed via
# ``DiagnosticsService.run_prior_predictive_check``, never inside
# ``evaluate()`` itself - mirrors how ``backtest`` is a separate, explicitly
# triggered action via ``run_backtest``, not part of the main evaluation
# pass). This is a genuine schema *shape* change (a new serialised section),
# not only a calculation-method change, so both the schema version and the
# diagnostics version are bumped together, the same precedent schema v2 ->
# v3 set.
#
# Work Package 3 (REQ-VAL-001 predictive-density evidence): schema v4 -> v5
# adds the ``predictive_density`` section (``core.diagnostics.
# predictive_density_summary`` - PSIS-LOO/WAIC computed post-hoc against an
# already-fitted trace via ``pm.compute_log_likelihood`` + ``az.loo``/
# ``az.waic``, no refit, per market x outcome_id, computed via
# ``DiagnosticsService.run_predictive_density_check`` - the same separate,
# explicitly-triggered pure/immutable update pattern as
# ``run_prior_predictive_check``/``run_backtest``). Another schema *shape*
# change, same precedent as v3 -> v4.
#
# Work Package B (REQ-COVERAGE-001 S6, official-use coverage gate): schema
# v5 -> v6 adds the ``market_channel_capability`` section
# (``core.market_data_capability.check_market_channel_capability`` -
# whether every requested (market, channel) cell has governed,
# officially-resolved variable coverage under the current rectangular
# engine, computed by ``DiagnosticsService.evaluate()`` from
# ``raw_model_spec``/``coverage_matrix`` when both are supplied). Another
# schema *shape* change, same precedent as v4 -> v5.
#
# Work Package 3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`,
# REQ-SEARCH-002): schema v6 -> v7 adds the ``search_capacity`` section -
# Candidate A Search mediation/capacity evidence (governed Search object
# mapping validity, cap identification, demand/capture reconciliation,
# cap-binding probability, capture-outcome beta posteriors, convergence,
# and the current `core.search_capacity.candidate_a_use_gate` status),
# computed only for a fit whose ``model_identity``/`meta` records
# ``causal_graph_engine == core.search_capacity.SEARCH_CANDIDATE_A_ENGINE``;
# ``not_applicable`` for every ordinary fit. Another schema *shape* change,
# same precedent as v5 -> v6.
#
# Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps After PR #286`,
# canonical Diagnostics evidence integration): schema v7 -> v8 adds six
# sections, wiring evidence types that already existed as standalone core/
# application objects (REQ-PPD-001, REQ-LEAK-001/REQ-STAB-001,
# REQ-IDENT-001, REQ-LATENT-001, REQ-EXPMODE-001/REQ-CALIB-001) into one
# persisted artefact for the first time, per each record's own deferred
# "DiagnosticsArtefact/Diagnostics-page integration" open item:
#
# - ``posterior_predictive_metric_distributions`` (REQ-PPD-001): computed
#   inline in ``evaluate()`` from the same trace/frame/meta/params already
#   used for ``error_metrics`` - cheap, no extra fit required.
# - ``historical_validation`` / ``structural_stability`` (REQ-LEAK-001 /
#   REQ-STAB-001): NOT computed inline - real per-fold PyMC re-fitting is
#   expensive (`application.fold_refit_service.run_leakage_safe_fold_
#   refit`/`run_leakage_safe_fold_refit_from_sources`). A caller runs that
#   separately and passes the resulting folds/assessments/snapshots to
#   ``run_historical_and_structural_validation_check`` - the same pure,
#   immutable "replace one section, carry the rest" pattern as
#   ``run_backtest``/``run_prior_predictive_check``. Both sections are
#   populated from exactly one fold-refit run (never two divergent fits
#   for the same fold), consistent with REQ-LEAK-001 requirement 6's "the
#   two must not each derive their own, potentially divergent, notion of
#   what a historical fold reconstructed."
# - ``graphical_identification`` (REQ-IDENT-001): computed inline when the
#   caller supplies a ``causal_graph`` and one or more
#   ``identification_requests`` - cheap (no PyMC), analogous to
#   ``market_channel_capability``'s "computed only when the optional input
#   is supplied" pattern. Every result carries `core.
#   estimand_identification.GRAPHICAL_IDENTIFICATION_DISCLAIMER`
#   unchanged (REQ-IDENT-001 requirement 1) - this module never strips or
#   paraphrases it.
# - ``latent_state_identification`` (REQ-LATENT-001): computed inline,
#   dispatched the same way ``search_capacity`` already is - `meta.
#   causal_graph_engine == SEARCH_CANDIDATE_A_ENGINE` determines whether
#   Candidate A's latent demand state is in scope; declarations/chain
#   draws are optional caller-supplied evidence. No declaration means
#   `not_identified`, never a fabricated pass (REQ-LATENT-001's own
#   fail-closed contract, unchanged here).
# - ``experiment_calibration`` (REQ-EXPMODE-001 / REQ-CALIB-001): computed
#   inline from an optional caller-supplied `ExperimentProvenanceReport`/
#   `CalibratedVsUncalibratedComparisonArtefact` pair - `not_applicable`
#   when neither is supplied, since no experiment-registry/calibration
#   persistence wiring exists in this repository yet (deferred to the
#   Experiment Evidence workflow work package; this record only adds the
#   artefact slot the evidence will occupy once that workflow exists).
#
# None of these six sections introduces a new blocking threshold - every
# one is descriptive evidence only, exactly like every other
# DiagnosticsArtefact section (REQ-VAL-001's "evidence computation and
# approval policy are separate"; `core.validation_policy.ThresholdPolicy`/
# `ApprovalReadiness` are unchanged by this schema addition - the existing
# `diagnostic_artefact_fingerprint` staleness mechanism already reacts to
# this artefact's now-larger fingerprint automatically).
CURRENT_DIAGNOSTICS_SCHEMA_VERSION = 9
CURRENT_DIAGNOSTICS_VERSION = "9.0.0"

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

    WP2.11 item 6: Schema v9 adds ``residual_series`` - the canonical
    per-``market x date x outcome_id`` residual evidence
    (``core.diagnostics.residual_series``/``core.market_specific_
    diagnostics.residual_series_market_specific``, plus ``core.
    diagnostics.shared_residual_evidence``'s cross-outcome comparison as
    a sub-key of the same section's payload) the Residual Explorer
    (``pages/06_Diagnostics.py``) reads - additive, alongside (never
    replacing) ``residual_diagnostics``'s existing aggregate lag-1/
    Durbin-Watson evidence, which continues unchanged.

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
    residual_series: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    prior_predictive: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    predictive_density: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    market_channel_capability: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    search_capacity: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    posterior_predictive_metric_distributions: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    historical_validation: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    structural_stability: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    graphical_identification: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    latent_state_identification: DiagnosticSection = field(
        default_factory=lambda: DiagnosticSection(status="not_computed", payload=None)
    )
    experiment_calibration: DiagnosticSection = field(
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
            "residual_series": self.residual_series.fingerprint_payload(),
            "prior_predictive": self.prior_predictive.fingerprint_payload(),
            "predictive_density": self.predictive_density.fingerprint_payload(),
            "market_channel_capability": self.market_channel_capability.fingerprint_payload(),
            "search_capacity": self.search_capacity.fingerprint_payload(),
            "posterior_predictive_metric_distributions": (
                self.posterior_predictive_metric_distributions.fingerprint_payload()
            ),
            "historical_validation": self.historical_validation.fingerprint_payload(),
            "structural_stability": self.structural_stability.fingerprint_payload(),
            "graphical_identification": self.graphical_identification.fingerprint_payload(),
            "latent_state_identification": (
                self.latent_state_identification.fingerprint_payload()
            ),
            "experiment_calibration": self.experiment_calibration.fingerprint_payload(),
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
            "residual_series": self.residual_series.to_dict(),
            "prior_predictive": self.prior_predictive.to_dict(),
            "predictive_density": self.predictive_density.to_dict(),
            "market_channel_capability": self.market_channel_capability.to_dict(),
            "search_capacity": self.search_capacity.to_dict(),
            "posterior_predictive_metric_distributions": (
                self.posterior_predictive_metric_distributions.to_dict()
            ),
            "historical_validation": self.historical_validation.to_dict(),
            "structural_stability": self.structural_stability.to_dict(),
            "graphical_identification": self.graphical_identification.to_dict(),
            "latent_state_identification": self.latent_state_identification.to_dict(),
            "experiment_calibration": self.experiment_calibration.to_dict(),
            "global_warnings": list(self.global_warnings),
            "global_errors": list(self.global_errors),
            "settings": list(self.settings),
            "legacy_incomplete": self.legacy_incomplete,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DiagnosticsArtefact":
        """Load from a dict. Supports schema v1 (legacy_incomplete) through
        the current schema v9 (each upgraded in place to the current shape
        - see the class docstring for why this is not also marked
        legacy_incomplete).

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
        if sv in (2, 3, 4, 5, 6, 7, 8, 9):
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
            if sv >= 4:
                prior_predictive_sec = DiagnosticSection.from_dict(
                    d.get("prior_predictive", {})
                )
            else:
                # Work Package 2: prior predictive evidence did not exist
                # when a schema-v2/v3 artefact was computed - not_computed,
                # never a fabricated payload (mirrors the v2 -> v3 pattern
                # directly above).
                prior_predictive_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - prior "
                    "predictive evidence (pm.sample_prior_predictive, "
                    "outcome-scale, per market x outcome_id) was added in "
                    "schema v4.",
                )
            if sv >= 5:
                predictive_density_sec = DiagnosticSection.from_dict(
                    d.get("predictive_density", {})
                )
            else:
                # Work Package 3: predictive-density evidence did not exist
                # when a schema-v2/v3/v4 artefact was computed -
                # not_computed, never a fabricated payload (mirrors the
                # v3 -> v4 pattern directly above).
                predictive_density_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - predictive "
                    "density evidence (PSIS-LOO/WAIC, per market x "
                    "outcome_id) was added in schema v5.",
                )
            if sv >= 6:
                market_channel_capability_sec = DiagnosticSection.from_dict(
                    d.get("market_channel_capability", {})
                )
            else:
                # Work Package B: market x channel engine-capability
                # evidence did not exist when a schema-v2..v5 artefact was
                # computed - not_computed, never a fabricated payload
                # (mirrors the v4 -> v5 pattern directly above).
                market_channel_capability_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - market x "
                    "channel engine-capability evidence "
                    "(REQ-COVERAGE-001 S6) was added in schema v6.",
                )
            if sv >= 7:
                search_capacity_sec = DiagnosticSection.from_dict(
                    d.get("search_capacity", {})
                )
            else:
                # Work Package 3: Candidate A Search capacity evidence did
                # not exist when a schema-v2..v6 artefact was computed -
                # not_computed, never a fabricated payload (mirrors the
                # v5 -> v6 pattern directly above).
                search_capacity_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - Candidate A "
                    "Search capacity evidence (REQ-SEARCH-002) was added "
                    "in schema v7.",
                )
            if sv >= 8:
                ppd_sec = DiagnosticSection.from_dict(
                    d.get("posterior_predictive_metric_distributions", {})
                )
                historical_validation_sec = DiagnosticSection.from_dict(
                    d.get("historical_validation", {})
                )
                # Work Package 1 (`...Next Steps After PR #291`): evidence-
                # source tier provenance. An artefact computed before the
                # tier contract existed carries no `reconstruction_tier`
                # key; its evidence was produced by the weaker coverage-
                # metadata-only path (the only path the page offered
                # then). Reload must restore that weaker tier - never
                # upgrade weaker historical evidence into stronger.
                if (
                    historical_validation_sec.status == "computed"
                    and isinstance(historical_validation_sec.payload, dict)
                    and "reconstruction_tier" not in historical_validation_sec.payload
                ):
                    tiered_payload = dict(historical_validation_sec.payload)
                    tiered_payload["reconstruction_tier"] = (
                        RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY
                    )
                    historical_validation_sec = DiagnosticSection(
                        status=historical_validation_sec.status,
                        payload=tiered_payload,
                        error=historical_validation_sec.error,
                        warnings=historical_validation_sec.warnings,
                    )
                structural_stability_sec = DiagnosticSection.from_dict(
                    d.get("structural_stability", {})
                )
                graphical_identification_sec = DiagnosticSection.from_dict(
                    d.get("graphical_identification", {})
                )
                latent_state_identification_sec = DiagnosticSection.from_dict(
                    d.get("latent_state_identification", {})
                )
                experiment_calibration_sec = DiagnosticSection.from_dict(
                    d.get("experiment_calibration", {})
                )
            else:
                # Work Package 2 (canonical Diagnostics evidence
                # integration): none of these six sections existed when a
                # schema-v2..v7 artefact was computed - not_computed,
                # never a fabricated payload (mirrors every earlier
                # schema-bump precedent above).
                ppd_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - posterior "
                    "predictive metric distribution evidence (REQ-PPD-001) "
                    "was added in schema v8.",
                )
                historical_validation_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - point-in-time "
                    "historical validation evidence (REQ-LEAK-001) was "
                    "added in schema v8.",
                )
                structural_stability_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - structural "
                    "stability evidence (REQ-STAB-001) was added in "
                    "schema v8.",
                )
                graphical_identification_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - estimand-"
                    "specific graphical identification evidence "
                    "(REQ-IDENT-001) was added in schema v8.",
                )
                latent_state_identification_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - latent-state "
                    "scale/location identification evidence "
                    "(REQ-LATENT-001) was added in schema v8.",
                )
                experiment_calibration_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - experiment "
                    "provenance / calibrated-vs-uncalibrated comparison "
                    "evidence (REQ-EXPMODE-001 / REQ-CALIB-001) was added "
                    "in schema v8.",
                )
            if sv >= 9:
                residual_series_sec = DiagnosticSection.from_dict(
                    d.get("residual_series", {})
                )
            else:
                # WP2.11 item 6: canonical per-market x date x outcome_id
                # residual evidence did not exist when a schema-v2..v8
                # artefact was computed - not_computed, never a fabricated
                # payload (mirrors every earlier schema-bump precedent
                # above). The aggregate residual_diagnostics section
                # (lag-1/Durbin-Watson) is unaffected and still loads
                # normally regardless of this gate.
                residual_series_sec = DiagnosticSection(
                    status="not_computed",
                    payload=None,
                    error=f"Not available in schema v{sv} - canonical "
                    "per-market x date x outcome_id residual evidence "
                    "(the Residual Explorer) was added in schema v9.",
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
                residual_series=residual_series_sec,
                prior_predictive=prior_predictive_sec,
                predictive_density=predictive_density_sec,
                market_channel_capability=market_channel_capability_sec,
                search_capacity=search_capacity_sec,
                posterior_predictive_metric_distributions=ppd_sec,
                historical_validation=historical_validation_sec,
                structural_stability=structural_stability_sec,
                graphical_identification=graphical_identification_sec,
                latent_state_identification=latent_state_identification_sec,
                experiment_calibration=experiment_calibration_sec,
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
    # Work Package B (REQ-COVERAGE-001 S6): the governed variable coverage
    # matrix, when one has been built on the Data Coverage page. Enables the
    # market_channel_capability section below; absent this, that section
    # stays not_computed rather than assuming support.
    coverage_matrix: Optional[VariableCoverageMatrix] = None
    # Freshness pair (review finding on this PR's initial version): the
    # session-recorded `fingerprint_dataframe(joined_df)` the matrix was
    # actually built against (`variable_coverage_matrix_built_against_
    # fingerprint`), and the *current* joined dataframe's fingerprint. A
    # coverage matrix built against an earlier Transform Pipeline join (or
    # restored from an imported project bundle) can drift out of sync with
    # the data actually being fit now, even though the matrix's own content
    # is unchanged - `check_market_channel_capability`'s per-cell result
    # alone cannot see this, since it never reads the joined data. Mirrors
    # the live fingerprint comparison already surfaced (informationally) on
    # `pages/04_Model_Config.py`/`pages/15_Data_Coverage.py`, but here it is
    # authoritative: the market_channel_capability section reports
    # unsupported when these are absent or mismatched, never merely warns.
    coverage_matrix_built_against_fingerprint: Optional[str] = None
    joined_dataframe_fingerprint: Optional[str] = None
    # Work Package 3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`,
    # REQ-SEARCH-002): optional governed Candidate A identity/observations,
    # enabling the search_capacity section's spec-validation/identification/
    # use-gate evidence. All optional and additive - no existing caller is
    # affected; absent, the section still reports posterior-summary evidence
    # for a Candidate A fit (see evaluate()'s §9).
    candidate_a_spec: Optional[SearchCandidateASpec] = None
    candidate_a_search_objects: Sequence[
        SearchObjectDefinition | Mapping[str, Any]
    ] = ()
    candidate_a_paid_search_cap: Optional[np.ndarray] = None
    candidate_a_paid_search_delivery: Optional[np.ndarray] = None
    # Work Package 2 (canonical Diagnostics evidence integration,
    # `Media-Mix-Lab: Coding LLM Next Steps After PR #286`): optional
    # governed evidence for the six new schema-v8 sections. Every field
    # here is caller-supplied, already-computed evidence (mirroring
    # `candidate_a_spec`'s own "optional, additive" pattern above) - this
    # service performs no fitting, graph editing, or identification-anchor
    # invention of its own.
    #
    # REQ-IDENT-001 (graphical identification): a requested estimand,
    # e.g. {"treatment": "tv_spend", "outcome": "fh_new_gsa",
    # "effect_type": "total", "proposed_adjustment_set": ("seasonality",)}.
    # `effect_type` defaults to "total" (the only effect type this
    # module's checker supports natively - see
    # `core.estimand_identification`'s own module docstring; requesting
    # "direct" is still accepted here and correctly resolves to
    # `unsupported_by_current_checker`, never silently treated as total).
    causal_graph: Optional[CausalGraph] = None
    identification_requests: Sequence[Mapping[str, Any]] = ()
    # REQ-LATENT-001 (latent-state identification): optional declarations
    # and, optionally, per-chain posterior draws for each declared state's
    # representative scalar, keyed by latent_state_id.
    latent_state_declarations: Sequence[LatentStateIdentificationDeclaration] = ()
    latent_state_chain_draws: Mapping[str, Tuple[Tuple[float, ...], ...]] = field(
        default_factory=dict
    )
    # REQ-EXPMODE-001 / REQ-CALIB-001 (experiment provenance / calibrated-
    # vs-uncalibrated comparison): both optional - neither the experiment
    # registry nor a calibration mechanism has persistence/UI wiring in
    # this repository yet (see each record's own "Capability status"), so
    # this section stays `not_applicable` until a caller (a future
    # Experiment Evidence workflow) supplies one or both.
    experiment_provenance_report: Optional[ExperimentProvenanceReport] = None
    calibration_comparison_artefact: Optional[
        CalibratedVsUncalibratedComparisonArtefact
    ] = None
    # Decision 12: replay inputs are caller-built from the governed named-
    # event registry and the exact fit-time response-definition versions.
    # They are required whenever the fit consumed named events; ``None``
    # intentionally preserves predict_mu's fail-closed guard.
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None


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
