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
   model-fitting code - the raw-PyMC builder adapter below composes the
   same observation-model idea against the existing Hill response and
   log-link. It is deliberately limited to direct channel/outcome rows;
   temporal/adstock translation remains an explicit future extension.
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

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, cast

import numpy as np

from .experiments import (
    EVIDENCE_MODE_LIKELIHOOD_CALIBRATION,
    CompatibilityAssessment,
    ExperimentRecord,
    ExperimentToModelUse,
)
from .transformations import pt_hill_function

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
        if self.delta_x < 0:
            raise ValueError("LiftTestCalibrationRow.delta_x cannot be negative.")
        if not np.isfinite(self.x) or not np.isfinite(self.delta_x):
            raise ValueError("LiftTestCalibrationRow x and delta_x must be finite.")
        if not np.isfinite(self.delta_y):
            raise ValueError("LiftTestCalibrationRow.delta_y must be finite.")
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


@dataclass(frozen=True)
class ModelLiftTestCalibrationInput:
    """One row plus the explicit outcome identity required by Ancestry's
    joint model.

    ``x`` and ``delta_x`` are the prepared model-input units for the named
    channel. This is intentional: the adapter does not guess a spend-to-input
    translation or silently apply a second adstock transformation.
    """

    row: LiftTestCalibrationRow
    outcome_id: str

    def __post_init__(self) -> None:
        if not self.outcome_id:
            raise ValueError(
                "ModelLiftTestCalibrationInput requires an explicit outcome_id."
            )
        if self.row.delta_y <= 0:
            raise ValueError(
                "The supported Gamma lift-test likelihood requires a strictly "
                "positive delta_y; signed effects need a separately approved "
                "calibration mechanism."
            )

    def to_dict(self) -> dict:
        return {"row": self.row.to_dict(), "outcome_id": self.outcome_id}

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ModelLiftTestCalibrationInput":
        return cls(
            row=LiftTestCalibrationRow.from_dict(values["row"]),
            outcome_id=str(values["outcome_id"]),
        )


def calibration_inputs_fingerprint(
    inputs: Optional[Sequence[ModelLiftTestCalibrationInput]],
) -> Optional[str]:
    """Fingerprint the calibration terms consumed by one fitted model.

    Experiment rows are an unordered set of separately named observation
    terms. Sorting the canonical rows makes the identity independent of UI
    declaration order while retaining every fit-relevant value.
    """
    if not inputs:
        return None
    payload = sorted(
        (item.to_dict() for item in inputs),
        key=lambda item: (item["row"]["experiment_id"], item["outcome_id"]),
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()


def attach_lift_test_calibration_terms(
    *,
    model: Any,
    sat_media: Any,
    hill_K: Any,
    hill_S: Any,
    beta: Any,
    eta: Any,
    channels: Sequence[str],
    outcome_ids: Sequence[str],
    primary_mask: np.ndarray,
    market_idx: Optional[np.ndarray],
    inputs: Sequence[ModelLiftTestCalibrationInput],
) -> None:
    """Attach compatible positive lift-test observations to a raw PyMC model.

    PyMC-Marketing's documented ``MMM.add_lift_test_measurements`` API is
    the upstream reference. The production builders here are raw PyMC, so
    this adapter composes the equivalent Gamma observation term against the
    existing Hill curve and model log-link rather than creating a second MMM.
    Predicted effects are calculated on the outcome scale. Only a direct
    primary channel/outcome cell is accepted; unsupported structural cases
    fail closed.
    """

    import pymc as pm
    import pytensor.tensor as pt

    if not inputs:
        return
    if primary_mask.shape != (len(outcome_ids), len(channels)):
        raise ValueError("primary_mask does not match model dimensions")
    for item in inputs:
        row = item.row
        if row.channel not in channels:
            raise ValueError(
                f"Lift-test channel {row.channel!r} is not in this model's channels."
            )
        oi = outcome_ids.index(item.outcome_id)
        ci = channels.index(row.channel)
        if float(primary_mask[oi, ci]) != 1.0:
            raise ValueError(
                f"Lift-test row {row.experiment_id!r} targets a non-direct "
                f"pathway ({row.channel!r}, {item.outcome_id!r})."
            )
        if getattr(beta, "ndim", None) == 3:
            if market_idx is None:
                raise ValueError(
                    "market_idx is required for market-specific calibration"
                )
            beta_obs = beta[market_idx, oi, ci]
        else:
            beta_obs = beta[oi, ci]
        base_eta = eta[:, oi] - beta_obs * sat_media[:, ci]
        base_mu = pt.exp(base_eta)
        response_at_x = pt_hill_function(
            pt.as_tensor_variable(float(row.x)), hill_K[ci], hill_S[ci]
        )
        response_at_x_plus_delta = pt_hill_function(
            pt.as_tensor_variable(float(row.x + row.delta_x)), hill_K[ci], hill_S[ci]
        )
        predicted_lift = pt.mean(
            base_mu * pt.expm1(beta_obs * (response_at_x_plus_delta - response_at_x))
        )
        safe_id = "".join(
            character if character.isalnum() else "_" for character in row.experiment_id
        )
        pm.Deterministic(f"lift_test_{safe_id}_predicted_lift", predicted_lift)
        pm.Gamma(
            f"lift_test_{safe_id}_obs",
            mu=pt.clip(predicted_lift, 1e-9, 1e12),
            sigma=float(row.sigma),
            observed=float(row.delta_y),
        )


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
