"""Calibrated-versus-uncalibrated model comparison (REQ-CALIB-001, Work
Package 4, second record, of `Media-Mix-Lab: Coding LLM Next Steps
After PR #267 and Latest PRD Validation Updates`).

Depends on `REQ-EXPMODE-001` (`core.experiments`): an experiment must
already declare a `prior_calibration`/`likelihood_calibration` evidence
mode before this record's comparison becomes relevant. No calibration
mechanism exists in this repository yet - this module governs the
comparison contract that must exist before any future calibration
mechanism may become official; it does not implement, approve, or imply
any specific calibration mechanism itself.

This module resolves REQ-CALIB-001's own "whether calibrated-model
identity extends `core.model_identity` or introduces a parallel
calibration-identity object" open question: it reuses `core.
model_identity.ModelIdentity` directly rather than introducing a second,
parallel identity type. A calibrated model and the uncalibrated model it
was calibrated from are two distinct `ModelIdentity` instances - never
the same instance, never an in-place mutation (Requirement 1, mirroring
the same immutability pattern already established for `CausalGraph`
versions and validation policies).

This module provides:

- `CalibrationComparisonMetric`: one named metric's calibrated and
  uncalibrated values (and, where available, posterior draws), covering
  Requirement 2's comparison dimensions (posterior predictive
  performance, historical holdout, media/structural parameters, adstock/
  saturation, baseline, hierarchy, posterior uncertainty, response
  curves, marginal economics, planning/optimisation consequences) -
  generically, by name, since this module has no domain knowledge of how
  to compute any specific one of them. `difference` is a plain
  descriptive number, mirroring `core.structural_stability.
  ParameterFoldComparison.point_range`'s "report movement, never a
  verdict" pattern - there is no threshold, pass/fail, or "calibration
  preferred" field anywhere in this module (Requirement 3: "closer
  agreement with an experiment is not automatically preferred").
- `ExperimentAgreementComparison`: one experiment's calibrated versus
  uncalibrated agreement metric, reported individually - mirrors `core.
  experiments`'s own "never collapsed into an average" provenance
  pattern for Requirement 2's "agreement with each compatible
  experiment" comparison dimension.
- `CalibratedVsUncalibratedComparisonArtefact`/`assemble_calibration_
  comparison`: the full structured comparison (Requirement 2) - rejects
  construction if the calibrated and uncalibrated `ModelIdentity`
  instances match, since Requirement 1 requires them to be genuinely
  distinct model identities.
- `CalibrationEventRecord`: Requirement 5's per-calibration-event record
  (resolved a prior conflict? materially changed a decision? uncertainty
  increased/reduced/unchanged? which other validation dimensions
  improved or worsened? any new limitation introduced?) - every field is
  a caller-supplied, structured fact for a human reviewer to record, not
  a judgement this module computes itself, mirroring `core.
  structural_stability`'s "assigns that judgement to a human reviewer
  informed by this evidence, not to this module" pattern.

Deliberately out of scope for this module (see REQ-CALIB-001's own
"Explicitly excluded"/"Unresolved decisions"):

- The material-change criteria that trigger mandatory calibrated-versus-
  uncalibrated review before curves, planning, or recommendations may use
  a calibrated model (Part 7 §48 `VL-025`; Part 9 §RP-023) - a
  decision-required policy.
- Any specific comparison tolerance or pass/fail threshold - this module
  reports differences descriptively only.
- Computing any of the comparison metrics themselves (posterior
  predictive performance, holdout performance, curves, economics, etc.)
  - the caller supplies every metric value, mirroring `core.
  structural_stability`'s "the caller supplies the fold-local
  computation, this module only assembles and compares the result"
  pattern.
- Keeping the calibrated and uncalibrated versions "separately visible
  and directly comparable" in curves/planning/reports (Requirement 4) -
  a UI/reporting-page requirement, deferred alongside Work Package 1/2/3/
  4's own same open item.
- Any specific calibration statistical mechanism (`REQ-EXPMODE-001`'s own
  deferred decision-support-package question).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

from .model_identity import ModelIdentity

UNCERTAINTY_CHANGE_INCREASED = "increased"
UNCERTAINTY_CHANGE_REDUCED = "reduced"
UNCERTAINTY_CHANGE_UNCHANGED = "unchanged"

UNCERTAINTY_CHANGES = (
    UNCERTAINTY_CHANGE_INCREASED,
    UNCERTAINTY_CHANGE_REDUCED,
    UNCERTAINTY_CHANGE_UNCHANGED,
)


def _require_distinct_identities(
    calibrated: ModelIdentity, uncalibrated: ModelIdentity
) -> None:
    if calibrated.matches(uncalibrated):
        raise ValueError(
            "calibrated_model_identity and uncalibrated_model_identity must "
            "be distinct - calibration produces a new, separately versioned "
            "model identity, never an in-place mutation of the model it was "
            "calibrated from (Requirement 1)"
        )


@dataclass(frozen=True)
class CalibrationComparisonMetric:
    """One named metric's calibrated and uncalibrated values (Requirement
    2). `difference` is descriptive only - never a threshold-based
    verdict, since no comparison tolerance has been approved (see this
    record's own "Explicitly excluded")."""

    metric_name: str
    calibrated_value: float
    uncalibrated_value: float
    calibrated_draws: Tuple[float, ...] = ()
    uncalibrated_draws: Tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("metric_name is required")

    @property
    def difference(self) -> float:
        return self.calibrated_value - self.uncalibrated_value

    def to_dict(self) -> dict:
        return {
            "metric_name": self.metric_name,
            "calibrated_value": self.calibrated_value,
            "uncalibrated_value": self.uncalibrated_value,
            "calibrated_draws": list(self.calibrated_draws),
            "uncalibrated_draws": list(self.uncalibrated_draws),
            "difference": self.difference,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CalibrationComparisonMetric":
        return cls(
            metric_name=values["metric_name"],
            calibrated_value=float(values["calibrated_value"]),
            uncalibrated_value=float(values["uncalibrated_value"]),
            calibrated_draws=tuple(values.get("calibrated_draws") or ()),
            uncalibrated_draws=tuple(values.get("uncalibrated_draws") or ()),
        )


@dataclass(frozen=True)
class ExperimentAgreementComparison:
    """One experiment's calibrated versus uncalibrated agreement metric
    (Requirement 2's "agreement with each compatible experiment"
    dimension) - reported individually, per experiment, never averaged
    across experiments."""

    experiment_id: str
    calibrated_agreement: float
    uncalibrated_agreement: float

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("experiment_id is required")

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "calibrated_agreement": self.calibrated_agreement,
            "uncalibrated_agreement": self.uncalibrated_agreement,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ExperimentAgreementComparison":
        return cls(
            experiment_id=values["experiment_id"],
            calibrated_agreement=float(values["calibrated_agreement"]),
            uncalibrated_agreement=float(values["uncalibrated_agreement"]),
        )


@dataclass(frozen=True)
class CalibratedVsUncalibratedComparisonArtefact:
    """The full structured calibrated-versus-uncalibrated comparison
    (Requirement 2) - per-metric and per-experiment-agreement detail
    only; no aggregate score, threshold, or "calibration preferred"
    field anywhere on this class (Requirement 3)."""

    calibrated_model_identity: ModelIdentity
    uncalibrated_model_identity: ModelIdentity
    per_metric: Tuple[CalibrationComparisonMetric, ...] = ()
    per_experiment_agreement: Tuple[ExperimentAgreementComparison, ...] = ()
    limitations: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_distinct_identities(
            self.calibrated_model_identity, self.uncalibrated_model_identity
        )

    def to_dict(self) -> dict:
        return {
            "calibrated_model_identity": self.calibrated_model_identity.to_dict(),
            "uncalibrated_model_identity": self.uncalibrated_model_identity.to_dict(),
            "per_metric": [m.to_dict() for m in self.per_metric],
            "per_experiment_agreement": [
                a.to_dict() for a in self.per_experiment_agreement
            ],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "CalibratedVsUncalibratedComparisonArtefact":
        return cls(
            calibrated_model_identity=ModelIdentity.from_dict(
                values["calibrated_model_identity"]
            ),
            uncalibrated_model_identity=ModelIdentity.from_dict(
                values["uncalibrated_model_identity"]
            ),
            per_metric=tuple(
                CalibrationComparisonMetric.from_dict(m)
                for m in values.get("per_metric") or ()
            ),
            per_experiment_agreement=tuple(
                ExperimentAgreementComparison.from_dict(a)
                for a in values.get("per_experiment_agreement") or ()
            ),
            limitations=tuple(values.get("limitations") or ()),
        )


def assemble_calibration_comparison(
    calibrated_model_identity: ModelIdentity,
    uncalibrated_model_identity: ModelIdentity,
    *,
    metrics: Tuple[CalibrationComparisonMetric, ...] = (),
    experiment_agreements: Tuple[ExperimentAgreementComparison, ...] = (),
    limitations: Tuple[str, ...] = (),
) -> CalibratedVsUncalibratedComparisonArtefact:
    """Assemble a `CalibratedVsUncalibratedComparisonArtefact` from
    caller-supplied metric and experiment-agreement comparisons
    (REQ-CALIB-001). This function performs no computation of its own -
    every metric value is caller-supplied evidence."""
    return CalibratedVsUncalibratedComparisonArtefact(
        calibrated_model_identity=calibrated_model_identity,
        uncalibrated_model_identity=uncalibrated_model_identity,
        per_metric=tuple(metrics),
        per_experiment_agreement=tuple(experiment_agreements),
        limitations=tuple(limitations),
    )


@dataclass(frozen=True)
class CalibrationEventRecord:
    """Requirement 5's per-calibration-event record - every field is a
    caller-supplied, structured fact for a human reviewer to record
    (mirrors `core.structural_stability`'s "assigns that judgement to a
    human reviewer informed by this evidence, not to this module"
    pattern). `None` means "not yet assessed", distinct from an explicit
    `False`/empty-tuple recorded assessment."""

    calibrated_model_identity: ModelIdentity
    uncalibrated_model_identity: ModelIdentity
    resolved_prior_conflict: Optional[bool] = None
    materially_changed_decision: Optional[bool] = None
    uncertainty_change: Optional[str] = None
    validation_dimensions_improved: Tuple[str, ...] = ()
    validation_dimensions_worsened: Tuple[str, ...] = ()
    new_limitations_introduced: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_distinct_identities(
            self.calibrated_model_identity, self.uncalibrated_model_identity
        )
        if (
            self.uncertainty_change is not None
            and self.uncertainty_change not in UNCERTAINTY_CHANGES
        ):
            raise ValueError(
                f"invalid uncertainty_change {self.uncertainty_change!r}; must "
                f"be one of {UNCERTAINTY_CHANGES} or None"
            )

    def to_dict(self) -> dict:
        return {
            "calibrated_model_identity": self.calibrated_model_identity.to_dict(),
            "uncalibrated_model_identity": self.uncalibrated_model_identity.to_dict(),
            "resolved_prior_conflict": self.resolved_prior_conflict,
            "materially_changed_decision": self.materially_changed_decision,
            "uncertainty_change": self.uncertainty_change,
            "validation_dimensions_improved": list(self.validation_dimensions_improved),
            "validation_dimensions_worsened": list(self.validation_dimensions_worsened),
            "new_limitations_introduced": list(self.new_limitations_introduced),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "CalibrationEventRecord":
        return cls(
            calibrated_model_identity=ModelIdentity.from_dict(
                values["calibrated_model_identity"]
            ),
            uncalibrated_model_identity=ModelIdentity.from_dict(
                values["uncalibrated_model_identity"]
            ),
            resolved_prior_conflict=values.get("resolved_prior_conflict"),
            materially_changed_decision=values.get("materially_changed_decision"),
            uncertainty_change=values.get("uncertainty_change"),
            validation_dimensions_improved=tuple(
                values.get("validation_dimensions_improved") or ()
            ),
            validation_dimensions_worsened=tuple(
                values.get("validation_dimensions_worsened") or ()
            ),
            new_limitations_introduced=tuple(
                values.get("new_limitations_introduced") or ()
            ),
            metadata=dict(values.get("metadata") or {}),
        )
