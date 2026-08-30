"""Experiment evidence modes and provenance (REQ-EXPMODE-001, Work
Package 4 of `Media-Mix-Lab: Coding LLM Next Steps After PR #267 and
Latest PRD Validation Updates`).

Experiment Evidence exists in this repository as an input data domain,
but no module previously declared a governed evidence mode for an
experiment-to-model relationship, and no calibration mechanism exists.
This module adds the registry and evidence-mode contract only - it does
not implement, approve, or imply any specific likelihood-calibration or
prior-calibration statistical mechanism (that is explicitly reserved by
REQ-EXPMODE-001's own "Explicitly excluded" section as a Work Package 4
decision-support-package question, and by the PRD-authority instruction
governing this program: do not guess an unresolved statistical
decision). This module also does not couple to any model-fitting code -
`core.search_capacity`, `core.pathways`, and every other model-building
module are untouched, so registering an `ExperimentRecord` or an
`ExperimentToModelUse` cannot silently alter fitting (Requirement 2's
"uploading or registering an experiment must never silently calibrate a
model" is satisfied by construction: nothing in this repository yet
reads this registry to build a model).

This module provides:

- `ExperimentRecord`: an immutable, versioned experiment record
  (Requirement 1) - `experiment_id`/`experiment_version` is the
  lineage/version identity, following exactly the same "lineage
  identity is locked, every edit produces a new version, never an
  in-place mutation" pattern already established by `core.causal_graph`
  (`graph_id`/`graph_version`) and `core.search_objects`
  (`search_object_id`/`search_object_version`) - `new_experiment_
  version` and `current_experiment_versions` mirror `core.
  search_objects.new_search_object_version`/`current_search_object_
  versions` exactly.
- `ExperimentToModelUse`: exactly one governed evidence mode per
  experiment-to-model relationship (Requirement 2) - `validation_only`,
  `prior_calibration` (must record the affected prior's name and
  version), `likelihood_calibration` (must record the affected
  likelihood term's name and version), or `diagnostic_comparison`.
- `CompatibilityAssessment`/`assess_experiment_compatibility`: the
  compatibility-across-dimensions record required before any
  `prior_calibration`/`likelihood_calibration` use (Requirement 3) -
  mirrors `core.structural_stability`'s "the caller supplies the
  computation, this module only assembles and validates the result"
  pattern: this module has no domain knowledge of what makes two
  markets or channel definitions compatible, so every dimension's
  compatibility is caller-supplied evidence, never inferred.
- `build_calibrating_use` / `validate_no_double_counted_dependence`:
  Requirement 3's fail-closed rule ("An incompatible experiment must not
  calibrate automatically") and Requirement 2's double-counting rule
  (the same experiment must never be counted twice through incompatible
  calibration routes unless an approved method explicitly accounts for
  the dependence).
- `ExperimentProvenanceReport`/`build_provenance_report`: Requirement
  6's reporting contract - every contributing experiment's evidence
  mode, compatible estimand, version, and uncertainty individually,
  never collapsed into an unexplained average. A portfolio summary may
  be added in addition to, never instead of, this per-experiment detail
  - this module simply does not offer a function that collapses the
  list, so no caller can accidentally display only an average.

Deliberately out of scope for this module (see REQ-EXPMODE-001's own
"Explicitly excluded"/"Unresolved decisions"):

- Any specific likelihood-calibration or prior-calibration statistical
  formula or mechanism - reserved for a future Work Package 4
  decision-support package using Context7/official PyMC/PyMC-Marketing
  sources, per this record's own text, before any production default is
  chosen.
- The full evidence-mode taxonomy's edge cases, multi-experiment
  likelihood-calibration conditions, and dependence-treatment method
  beyond Requirement 2's explicit double-counting rule (Part 7 §48
  `VL-024`).
- `core.persistence` export/import wiring for the experiment registry -
  delivered by Work Package 2 of `Media-Mix-Lab: Coding LLM Next Steps
  After PR #291` (`config/experiments.json` under
  `EXPERIMENT_REGISTRY_SCHEMA_VERSION`, with the adoption boundary in
  `application.experiment_service` and quarantine-on-import via
  `core.persistence.resolve_imported_experiments`). This module itself
  remains persistence-agnostic.
- `REQ-CALIB-001`'s calibrated-versus-uncalibrated comparison contract -
  a separate, dependent record (its own module). No calibration
  mechanism exists or is implied by any of the above.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

import pandas as pd

EXPERIMENT_DESIGN_GEO_TEST = "geo_test"
EXPERIMENT_DESIGN_HOLDOUT = "holdout"
EXPERIMENT_DESIGN_PAUSE_TEST = "pause_test"
EXPERIMENT_DESIGN_LIFT_STUDY = "lift_study"
EXPERIMENT_DESIGN_OTHER_APPROVED = "other_approved"

EXPERIMENT_DESIGNS = (
    EXPERIMENT_DESIGN_GEO_TEST,
    EXPERIMENT_DESIGN_HOLDOUT,
    EXPERIMENT_DESIGN_PAUSE_TEST,
    EXPERIMENT_DESIGN_LIFT_STUDY,
    EXPERIMENT_DESIGN_OTHER_APPROVED,
)

EVIDENCE_MODE_VALIDATION_ONLY = "validation_only"
EVIDENCE_MODE_PRIOR_CALIBRATION = "prior_calibration"
EVIDENCE_MODE_LIKELIHOOD_CALIBRATION = "likelihood_calibration"
EVIDENCE_MODE_DIAGNOSTIC_COMPARISON = "diagnostic_comparison"

EVIDENCE_MODES = (
    EVIDENCE_MODE_VALIDATION_ONLY,
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    EVIDENCE_MODE_DIAGNOSTIC_COMPARISON,
)

_CALIBRATING_MODES = (
    EVIDENCE_MODE_PRIOR_CALIBRATION,
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
)

# Record-level schema version of the persisted experiment registry file
# (`config/experiments.json` in the project bundle). Importers reject an
# unrecognised future version rather than guessing - mirrors every other
# governed record's schema-version contract in this repository.
#
# v2 (2026-08-30, Decision 11): added ExperimentRecord.baseline_exposure_
# level/strategy_or_tactic_tested/post_adoption_outcome_tracked/
# applicability_period_start/applicability_period_end (all optional). No
# `config/experiments.json` file exists anywhere in this repository yet,
# so no live persisted registry required migration.
EXPERIMENT_REGISTRY_SCHEMA_VERSION = 2

COMPATIBILITY_DIMENSIONS = (
    "outcome",
    "estimand",
    "market_segment_product",
    "channel_or_activity_definition",
    "treatment",
    "counterfactual",
    "spend_delivery_range",
    "time_horizon",
    "effect_scale",
)


@dataclass(frozen=True)
class ExperimentRecord:
    """One immutable, versioned experiment record (Requirement 1).

    `experiment_id`/`experiment_version` is the lineage/version identity
    - mirrors `core.causal_graph`'s `graph_id`/`graph_version` and
    `core.search_objects`'s `search_object_id`/`search_object_version`
    immutability pattern exactly. Use `new_experiment_version` to record
    an edit as a new version; never mutate an existing record in place.

    Decision 11 (`docs/experiment_calibration_mechanism_decision_
    record.md`) added five optional, backward-compatible fields
    (`EXPERIMENT_REGISTRY_SCHEMA_VERSION` 1 -> 2): `baseline_exposure_
    level` (the "x" PyMC-Marketing's official `add_lift_test_
    measurements` row shape requires - the channel's spend/exposure
    level immediately before the tested delta was applied, needed
    because a saturation curve's marginal effect is non-linear in its
    starting point); `strategy_or_tactic_tested` (what was actually
    tested - a creative, targeting, or budget-level change - since "the
    experiment" alone does not disambiguate this); `post_adoption_
    outcome_tracked` (whether the tested change, once adopted into
    always-on activity, has had its real-world outcome tracked
    afterward); and `applicability_period_start`/`applicability_period_
    end` (the period during which this experiment's finding is
    considered still valid for calibration - distinct from `start_date`/
    `end_date`, which record when the experiment itself ran).
    """

    experiment_id: str
    experiment_version: int
    design: str
    start_date: str
    end_date: str
    market_scope: Tuple[str, ...]
    estimand: str
    observed_effect_estimate: float
    effect_uncertainty: float
    method: str
    source: str
    evidence_status: str
    product_scope: Tuple[str, ...] = ()
    segment_scope: Tuple[str, ...] = ()
    treatment_quantity: Optional[float] = None
    limitations: Tuple[str, ...] = ()
    overlapping_experiment_ids: Tuple[str, ...] = ()
    baseline_exposure_level: Optional[float] = None
    strategy_or_tactic_tested: Optional[str] = None
    post_adoption_outcome_tracked: Optional[bool] = None
    applicability_period_start: Optional[str] = None
    applicability_period_end: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if self.experiment_version < 1:
            raise ValueError("experiment_version must be >= 1")
        if self.design not in EXPERIMENT_DESIGNS:
            raise ValueError(
                f"invalid design {self.design!r}; must be one of {EXPERIMENT_DESIGNS}"
            )
        if not self.estimand:
            raise ValueError("estimand is required")
        if pd.Timestamp(self.end_date) < pd.Timestamp(self.start_date):
            raise ValueError(
                f"end_date ({self.end_date!r}) is before start_date "
                f"({self.start_date!r})"
            )
        if not self.market_scope:
            raise ValueError("market_scope is required")
        if self.effect_uncertainty < 0:
            raise ValueError("effect_uncertainty cannot be negative")
        if (
            self.baseline_exposure_level is not None
            and self.baseline_exposure_level < 0
        ):
            raise ValueError("baseline_exposure_level cannot be negative")
        if (self.applicability_period_start is None) != (
            self.applicability_period_end is None
        ):
            raise ValueError(
                "applicability_period_start and applicability_period_end "
                "must be present or absent together"
            )
        if (
            self.applicability_period_start is not None
            and self.applicability_period_end is not None
            and pd.Timestamp(self.applicability_period_end)
            < pd.Timestamp(self.applicability_period_start)
        ):
            raise ValueError(
                "applicability_period_end must not precede applicability_period_start"
            )

    @property
    def experiment_key(self) -> str:
        return self.experiment_id

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "design": self.design,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "market_scope": list(self.market_scope),
            "product_scope": list(self.product_scope),
            "segment_scope": list(self.segment_scope),
            "estimand": self.estimand,
            "treatment_quantity": self.treatment_quantity,
            "observed_effect_estimate": self.observed_effect_estimate,
            "effect_uncertainty": self.effect_uncertainty,
            "method": self.method,
            "source": self.source,
            "evidence_status": self.evidence_status,
            "limitations": list(self.limitations),
            "overlapping_experiment_ids": list(self.overlapping_experiment_ids),
            "baseline_exposure_level": self.baseline_exposure_level,
            "strategy_or_tactic_tested": self.strategy_or_tactic_tested,
            "post_adoption_outcome_tracked": self.post_adoption_outcome_tracked,
            "applicability_period_start": self.applicability_period_start,
            "applicability_period_end": self.applicability_period_end,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ExperimentRecord":
        post_adoption_outcome_tracked = values.get("post_adoption_outcome_tracked")
        return cls(
            experiment_id=values["experiment_id"],
            experiment_version=int(values["experiment_version"]),
            design=values["design"],
            start_date=values["start_date"],
            end_date=values["end_date"],
            market_scope=tuple(values.get("market_scope") or ()),
            product_scope=tuple(values.get("product_scope") or ()),
            segment_scope=tuple(values.get("segment_scope") or ()),
            estimand=values["estimand"],
            treatment_quantity=values.get("treatment_quantity"),
            baseline_exposure_level=values.get("baseline_exposure_level"),
            strategy_or_tactic_tested=values.get("strategy_or_tactic_tested"),
            post_adoption_outcome_tracked=(
                bool(post_adoption_outcome_tracked)
                if post_adoption_outcome_tracked is not None
                else None
            ),
            applicability_period_start=values.get("applicability_period_start"),
            applicability_period_end=values.get("applicability_period_end"),
            observed_effect_estimate=float(values["observed_effect_estimate"]),
            effect_uncertainty=float(values["effect_uncertainty"]),
            method=values["method"],
            source=values["source"],
            evidence_status=values["evidence_status"],
            limitations=tuple(values.get("limitations") or ()),
            overlapping_experiment_ids=tuple(
                values.get("overlapping_experiment_ids") or ()
            ),
            metadata=dict(values.get("metadata") or {}),
        )


def new_experiment_version(
    record: ExperimentRecord, **changes: Any
) -> ExperimentRecord:
    """Apply an edit to a registered experiment as a new version - never
    an in-place mutation of history (Requirement 1). Returns a new
    `ExperimentRecord` with `experiment_version` incremented by one.
    `experiment_id` and `experiment_version` are this record's lineage/
    version identity and may not be passed in `changes` - mirrors
    `core.search_objects.new_search_object_version` exactly."""
    for locked_field in ("experiment_id", "experiment_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot be "
                "set via new_experiment_version - construct a new "
                "ExperimentRecord directly to register a different "
                "experiment."
            )
    return replace(
        record,
        experiment_version=record.experiment_version + 1,
        **changes,
    )


def current_experiment_versions(
    records: Iterable[ExperimentRecord],
) -> Tuple[ExperimentRecord, ...]:
    """Resolve, per `experiment_id` lineage, the current (highest
    `experiment_version`) record - mirrors `core.search_objects.
    current_search_object_versions`."""
    latest: Dict[str, ExperimentRecord] = {}
    for record in records:
        current = latest.get(record.experiment_id)
        if current is None or record.experiment_version > current.experiment_version:
            latest[record.experiment_id] = record
    return tuple(latest.values())


@dataclass(frozen=True)
class CompatibilityAssessment:
    """The compatibility-across-dimensions record required before any
    `prior_calibration`/`likelihood_calibration` use (Requirement 3).
    Every dimension in `COMPATIBILITY_DIMENSIONS` must be assessed;
    `dimension_notes` records the caller-supplied evidence/reasoning per
    dimension - this module has no domain knowledge of what makes two
    markets or channel definitions compatible, so it never infers a
    dimension's compatibility itself. Compatibility may be local (one
    market or spend range) rather than global - `is_local` records
    that scope explicitly rather than leaving it implicit."""

    experiment_id: str
    dimension_results: Mapping[str, bool]
    dimension_notes: Mapping[str, str] = field(default_factory=dict)
    is_local: bool = False
    scope_note: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        missing = set(COMPATIBILITY_DIMENSIONS) - set(self.dimension_results)
        if missing:
            raise ValueError(
                f"dimension_results is missing required dimension(s): {sorted(missing)}"
            )
        unknown = set(self.dimension_results) - set(COMPATIBILITY_DIMENSIONS)
        if unknown:
            raise ValueError(
                f"dimension_results contains unknown dimension(s): {sorted(unknown)}"
            )

    @property
    def is_fully_compatible(self) -> bool:
        return all(self.dimension_results.values())

    @property
    def incompatible_dimensions(self) -> Tuple[str, ...]:
        return tuple(
            sorted(dim for dim, ok in self.dimension_results.items() if not ok)
        )

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "dimension_results": dict(self.dimension_results),
            "dimension_notes": dict(self.dimension_notes),
            "is_local": self.is_local,
            "scope_note": self.scope_note,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CompatibilityAssessment":
        return cls(
            experiment_id=values["experiment_id"],
            dimension_results=dict(values["dimension_results"]),
            dimension_notes=dict(values.get("dimension_notes") or {}),
            is_local=bool(values.get("is_local", False)),
            scope_note=values.get("scope_note"),
        )


def assess_experiment_compatibility(
    experiment_id: str,
    dimension_results: Mapping[str, bool],
    *,
    dimension_notes: Optional[Mapping[str, str]] = None,
    is_local: bool = False,
    scope_note: Optional[str] = None,
) -> CompatibilityAssessment:
    """Assemble a `CompatibilityAssessment` from caller-supplied,
    per-dimension compatibility evidence (Requirement 3). This function
    performs no inference of its own - it only validates that every
    required dimension was assessed and assembles the result."""
    return CompatibilityAssessment(
        experiment_id=experiment_id,
        dimension_results=dict(dimension_results),
        dimension_notes=dict(dimension_notes or {}),
        is_local=is_local,
        scope_note=scope_note,
    )


@dataclass(frozen=True)
class ExperimentToModelUse:
    """Exactly one governed evidence mode for one experiment-to-model
    relationship (Requirement 2). `prior_calibration` must record
    `affected_prior_name`/`affected_prior_version`; `likelihood_
    calibration` must record `affected_likelihood_term_name`/
    `affected_likelihood_term_version` - the affected target and its
    version, per Requirement 2's explicit text. Construct a calibrating
    use (`prior_calibration`/`likelihood_calibration`) via
    `build_calibrating_use`, never directly, so the Requirement 3
    fail-closed compatibility gate cannot be bypassed."""

    experiment_id: str
    experiment_version: int
    evidence_mode: str
    model_id: str
    model_version: str
    affected_prior_name: Optional[str] = None
    affected_prior_version: Optional[str] = None
    affected_likelihood_term_name: Optional[str] = None
    affected_likelihood_term_version: Optional[str] = None
    dependence_handling_method: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id is required")
        if not self.model_id:
            raise ValueError("model_id is required")
        if self.evidence_mode not in EVIDENCE_MODES:
            raise ValueError(
                f"invalid evidence_mode {self.evidence_mode!r}; must be one "
                f"of {EVIDENCE_MODES}"
            )
        if self.evidence_mode == EVIDENCE_MODE_PRIOR_CALIBRATION:
            if not self.affected_prior_name or not self.affected_prior_version:
                raise ValueError(
                    "prior_calibration requires affected_prior_name and "
                    "affected_prior_version to be recorded (Requirement 2)"
                )
        if self.evidence_mode == EVIDENCE_MODE_LIKELIHOOD_CALIBRATION:
            if (
                not self.affected_likelihood_term_name
                or not self.affected_likelihood_term_version
            ):
                raise ValueError(
                    "likelihood_calibration requires affected_likelihood_"
                    "term_name and affected_likelihood_term_version to be "
                    "recorded (Requirement 2)"
                )

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "evidence_mode": self.evidence_mode,
            "model_id": self.model_id,
            "model_version": self.model_version,
            "affected_prior_name": self.affected_prior_name,
            "affected_prior_version": self.affected_prior_version,
            "affected_likelihood_term_name": self.affected_likelihood_term_name,
            "affected_likelihood_term_version": self.affected_likelihood_term_version,
            "dependence_handling_method": self.dependence_handling_method,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ExperimentToModelUse":
        return cls(
            experiment_id=values["experiment_id"],
            experiment_version=int(values["experiment_version"]),
            evidence_mode=values["evidence_mode"],
            model_id=values["model_id"],
            model_version=values["model_version"],
            affected_prior_name=values.get("affected_prior_name"),
            affected_prior_version=values.get("affected_prior_version"),
            affected_likelihood_term_name=values.get("affected_likelihood_term_name"),
            affected_likelihood_term_version=values.get(
                "affected_likelihood_term_version"
            ),
            dependence_handling_method=values.get("dependence_handling_method"),
        )


def build_calibrating_use(
    compatibility: CompatibilityAssessment,
    *,
    experiment_version: int,
    evidence_mode: str,
    model_id: str,
    model_version: str,
    affected_prior_name: Optional[str] = None,
    affected_prior_version: Optional[str] = None,
    affected_likelihood_term_name: Optional[str] = None,
    affected_likelihood_term_version: Optional[str] = None,
    dependence_handling_method: Optional[str] = None,
) -> ExperimentToModelUse:
    """Construct a `prior_calibration`/`likelihood_calibration` use,
    fail-closed on an incompatible experiment (Requirement 3: "An
    incompatible experiment must not calibrate automatically"). Raises
    `ValueError` if `compatibility.is_fully_compatible` is `False`, or if
    `evidence_mode` is not a calibrating mode - use `ExperimentToModelUse`
    directly for `validation_only`/`diagnostic_comparison`, which never
    require a compatibility assessment."""
    if evidence_mode not in _CALIBRATING_MODES:
        raise ValueError(
            f"build_calibrating_use is only for {_CALIBRATING_MODES}; use "
            "ExperimentToModelUse directly for a non-calibrating evidence mode"
        )
    if not compatibility.is_fully_compatible:
        raise ValueError(
            f"experiment {compatibility.experiment_id!r} is not fully "
            f"compatible (incompatible dimensions: "
            f"{compatibility.incompatible_dimensions}) - an incompatible "
            "experiment must not calibrate automatically (Requirement 3)"
        )
    return ExperimentToModelUse(
        experiment_id=compatibility.experiment_id,
        experiment_version=experiment_version,
        evidence_mode=evidence_mode,
        model_id=model_id,
        model_version=model_version,
        affected_prior_name=affected_prior_name,
        affected_prior_version=affected_prior_version,
        affected_likelihood_term_name=affected_likelihood_term_name,
        affected_likelihood_term_version=affected_likelihood_term_version,
        dependence_handling_method=dependence_handling_method,
    )


def validate_no_double_counted_dependence(
    uses: Iterable[ExperimentToModelUse],
) -> Tuple[str, ...]:
    """Requirement 2's double-counting rule: the same experiment must
    never be counted twice through incompatible calibration routes
    (e.g. simultaneously as an informative prior and an independent
    likelihood term for the same model) unless an approved statistical
    method explicitly accounts for that dependence
    (`dependence_handling_method` recorded on every such use). Returns
    the tuple of `experiment_id`s that violate this rule for the
    supplied uses - callers decide what to do with a non-empty result
    (this function raises nothing; it is a query, not a gate)."""
    by_experiment_and_model: Dict[Tuple[str, str], list] = {}
    for use in uses:
        if use.evidence_mode not in _CALIBRATING_MODES:
            continue
        key = (use.experiment_id, use.model_id)
        by_experiment_and_model.setdefault(key, []).append(use)

    violating: list = []
    for (experiment_id, _model_id), group in by_experiment_and_model.items():
        modes = {u.evidence_mode for u in group}
        if len(modes) < 2:
            continue
        if all(u.dependence_handling_method for u in group):
            continue
        violating.append(experiment_id)
    return tuple(sorted(set(violating)))


@dataclass(frozen=True)
class ExperimentProvenanceEntry:
    """One experiment's individual provenance for one model use
    (Requirement 6) - never collapsed into an average."""

    experiment_id: str
    experiment_version: int
    evidence_mode: str
    estimand: str
    observed_effect_estimate: float
    effect_uncertainty: float

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "experiment_version": self.experiment_version,
            "evidence_mode": self.evidence_mode,
            "estimand": self.estimand,
            "observed_effect_estimate": self.observed_effect_estimate,
            "effect_uncertainty": self.effect_uncertainty,
        }


@dataclass(frozen=True)
class ExperimentProvenanceReport:
    """Requirement 6's reporting contract: every contributing
    experiment's provenance individually (`entries`), plus an optional
    descriptive portfolio summary that is additive, never a
    replacement - there is no method on this class that discards
    `entries`, so a caller cannot accidentally display only the
    summary."""

    model_id: str
    model_version: str
    entries: Tuple[ExperimentProvenanceEntry, ...]
    portfolio_summary: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_version": self.model_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "portfolio_summary": self.portfolio_summary,
        }


def build_provenance_report(
    model_id: str,
    model_version: str,
    uses: Iterable[ExperimentToModelUse],
    records_by_experiment_id: Mapping[str, ExperimentRecord],
    *,
    portfolio_summary: Optional[str] = None,
) -> ExperimentProvenanceReport:
    """Assemble Requirement 6's provenance report for one model from its
    experiment-to-model uses and their corresponding `ExperimentRecord`s.
    Raises `KeyError` if a use references an experiment_id absent from
    `records_by_experiment_id` - a provenance report must never silently
    omit a use it cannot fully describe."""
    entries = []
    for use in uses:
        if use.model_id != model_id or use.model_version != model_version:
            continue
        record = records_by_experiment_id[use.experiment_id]
        entries.append(
            ExperimentProvenanceEntry(
                experiment_id=use.experiment_id,
                experiment_version=use.experiment_version,
                evidence_mode=use.evidence_mode,
                estimand=record.estimand,
                observed_effect_estimate=record.observed_effect_estimate,
                effect_uncertainty=record.effect_uncertainty,
            )
        )
    return ExperimentProvenanceReport(
        model_id=model_id,
        model_version=model_version,
        entries=tuple(entries),
        portfolio_summary=portfolio_summary,
    )
