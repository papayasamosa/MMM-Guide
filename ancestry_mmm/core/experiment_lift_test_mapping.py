"""Governed experiment-to-lift-test calibration mapping (`REQ-EXPMODE-001`;
Decision 11 of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief).

See `docs/experiment_calibration_mechanism_decision_record.md` for the
full options-considered decision record (PyMC-Marketing documentation
consulted via Context7, and why this mechanism was chosen).

Summary (see the decision record for full reasoning):

1. PyMC-Marketing's own official, documented `MMM.add_lift_test_
   measurements(df_lift_test)` API is the approved mechanism for
   `likelihood_calibration`-mode experiment evidence - it contributes a
   calibration observation-model term against the model's saturation
   curve, matching `REQ-EXPMODE-001`'s own `likelihood_calibration`
   evidence-mode definition exactly. No equally well-established
   PyMC-Marketing mechanism was found for `prior_calibration`; that
   evidence mode's mechanism remains unresolved.
2. This module maps a fully compatible, likelihood-calibration-mode
   `ExperimentRecord` into `LiftTestCalibrationRow`, matching
   PyMC-Marketing's own documented `df_lift_test` row shape exactly
   (`channel`/`x`/`delta_x`/`delta_y`/`sigma`/`date`). It does NOT call
   `add_lift_test_measurements` itself, and does NOT touch any real
   model-fitting code - actually wiring this into a live model build is
   a separate, materially statistical follow-up requiring its own
   validation, mirroring every other Phase B/C step's scope boundary in
   this repository.
3. The mapping fails closed: it raises rather than silently substituting
   a default whenever the evidence mode is not `likelihood_calibration`,
   the supplied compatibility assessment is not fully compatible (this
   module never assumes compatibility merely because an
   `ExperimentToModelUse` object exists - `ExperimentToModelUse` can be
   constructed directly without going through `build_calibrating_use`'s
   own gate), the record is missing `baseline_exposure_level` or
   `treatment_quantity`, or `effect_uncertainty` is not strictly
   positive (a zero-uncertainty pseudo-observation would give the
   calibration term infinite/degenerate weight).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, cast

from .experiments import (
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
)

EXPERIMENT_LIFT_TEST_MAPPING_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LiftTestCalibrationRow:
    """One row matching PyMC-Marketing's official `df_lift_test` schema
    for `MMM.add_lift_test_measurements` exactly: `channel` (the model's
    channel column name being calibrated), `x` (the baseline spend/
    exposure level immediately before the tested delta), `delta_x` (the
    size of the tested change), `delta_y` (the observed incremental
    effect), `sigma` (the lift estimate's uncertainty, strictly positive),
    and `date` (optional)."""

    experiment_id: str
    experiment_version: int
    channel: str
    x: float
    delta_x: float
    delta_y: float
    sigma: float
    date: Optional[str] = None
    schema_version: int = EXPERIMENT_LIFT_TEST_MAPPING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.experiment_id:
            raise ValueError("LiftTestCalibrationRow requires an experiment_id.")
        if not self.channel:
            raise ValueError("LiftTestCalibrationRow requires a channel.")
        if self.x < 0:
            raise ValueError("LiftTestCalibrationRow.x cannot be negative.")
        if self.sigma <= 0:
            raise ValueError(
                "LiftTestCalibrationRow.sigma must be strictly positive - a "
                "zero-uncertainty pseudo-observation would give the "
                "calibration term infinite/degenerate weight."
            )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "LiftTestCalibrationRow":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def build_lift_test_calibration_row(
    record: ExperimentRecord,
    use: ExperimentToModelUse,
    compatibility: CompatibilityAssessment,
    *,
    channel: str,
) -> LiftTestCalibrationRow:
    """Fail-closed mapping of one `ExperimentRecord` into a
    `LiftTestCalibrationRow` for PyMC-Marketing's `add_lift_test_
    measurements`. `channel` must be supplied explicitly by the caller -
    the model's channel-column identity is a property of the specific
    MMM being calibrated, not of the experiment itself, so this module
    never guesses it.

    Raises `ValueError` (never silently substitutes a default or drops
    the row) if:

    - `use.evidence_mode` is not `likelihood_calibration`;
    - `use.experiment_id`/`compatibility.experiment_id` does not match
      `record.experiment_id`, or `use.experiment_version` does not match
      `record.experiment_version`;
    - `compatibility.is_fully_compatible` is `False` - re-verified
      independently here, never assumed merely because `use` exists;
    - `record.baseline_exposure_level` or `record.treatment_quantity` is
      `None`;
    - `record.effect_uncertainty` is not strictly positive.
    """
    if use.evidence_mode != EVIDENCE_MODE_LIKELIHOOD_CALIBRATION:
        raise ValueError(
            f"build_lift_test_calibration_row requires evidence_mode "
            f"{EVIDENCE_MODE_LIKELIHOOD_CALIBRATION!r}; got "
            f"{use.evidence_mode!r}. PyMC-Marketing's add_lift_test_"
            "measurements calibrates a likelihood/observation-model term, "
            "not a prior - use a different mechanism for prior_calibration "
            "(unresolved, see the decision record)."
        )
    if use.experiment_id != record.experiment_id:
        raise ValueError(
            f"use.experiment_id {use.experiment_id!r} does not match "
            f"record.experiment_id {record.experiment_id!r}."
        )
    if use.experiment_version != record.experiment_version:
        raise ValueError(
            f"use.experiment_version {use.experiment_version} does not "
            f"match record.experiment_version {record.experiment_version}."
        )
    if compatibility.experiment_id != record.experiment_id:
        raise ValueError(
            f"compatibility.experiment_id {compatibility.experiment_id!r} "
            f"does not match record.experiment_id {record.experiment_id!r}."
        )
    if not compatibility.is_fully_compatible:
        raise ValueError(
            f"experiment {record.experiment_id!r} is not fully compatible "
            f"(incompatible dimensions: {compatibility.incompatible_dimensions}) "
            "- an incompatible experiment must not calibrate automatically."
        )
    if record.baseline_exposure_level is None:
        raise ValueError(
            f"experiment {record.experiment_id!r} is missing "
            "baseline_exposure_level - required as the 'x' input to a "
            "lift-test calibration row (a saturation curve's marginal "
            "effect is non-linear in its starting point)."
        )
    if record.treatment_quantity is None:
        raise ValueError(
            f"experiment {record.experiment_id!r} is missing "
            "treatment_quantity - required as the 'delta_x' input to a "
            "lift-test calibration row."
        )
    if record.effect_uncertainty <= 0:
        raise ValueError(
            f"experiment {record.experiment_id!r} has effect_uncertainty "
            f"{record.effect_uncertainty} - a lift-test calibration row "
            "requires a strictly positive sigma."
        )
    if not channel:
        raise ValueError(
            "build_lift_test_calibration_row requires a non-empty channel."
        )

    return LiftTestCalibrationRow(
        experiment_id=record.experiment_id,
        experiment_version=record.experiment_version,
        channel=channel,
        x=record.baseline_exposure_level,
        delta_x=record.treatment_quantity,
        delta_y=record.observed_effect_estimate,
        sigma=record.effect_uncertainty,
        date=record.start_date,
    )


def build_lift_test_calibration_rows(
    entries: Sequence[
        tuple[ExperimentRecord, ExperimentToModelUse, CompatibilityAssessment, str]
    ],
) -> List[LiftTestCalibrationRow]:
    """Apply `build_lift_test_calibration_row` over a supplied sequence of
    `(record, use, compatibility, channel)` tuples, in order. Raises on
    the first invalid entry rather than silently skipping it - a caller
    that wants to tolerate some invalid entries must filter its own input
    first; this function never drops an entry silently."""
    return [
        build_lift_test_calibration_row(record, use, compatibility, channel=channel)
        for record, use, compatibility, channel in entries
    ]
