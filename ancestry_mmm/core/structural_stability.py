"""Structural stability evidence across time-respecting historical folds
(REQ-STAB-001, Work Package 2 part 2 of `Media-Mix-Lab: Coding LLM Next
Steps After PR #267 and Latest PRD Validation Updates`).

Current `core.diagnostics`/`core.identification_diagnostics` compute
posterior coefficient variation, condition number, and sensitivity on a
*single* fit. Neither re-estimates a model across time-respecting
historical folds and compares decision-driving structural quantities
across them. A model can predict adequately while its decision-driving
structural quantities (adstock decay, saturation shape, media response
coefficients, baseline behaviour, hierarchy parameters, selected marginal
economics) move materially across supported folds - predictive quality
and structural stability are separate evidence dimensions, and this
repository has no module that assesses the second one.

This module does not itself re-fit a model per fold - re-estimation is
expensive and belongs to the caller (a real per-fold PyMC re-fit, an
injected/fake parameter-extraction function for fast contract tests, or
another approved method), mirroring `core.validation_folds`'s own
"the caller supplies the fold-local computation, this module only
assembles and compares the result" pattern from Work Package 1.
`FoldParameterSnapshot.fold_id` is intended to match a `core.
validation_folds.ValidationFold.fold_id` - the same fold-manifest
identity REQ-LEAK-001 established - so the two records share one notion
of what a historical fold is, never two divergent ones.

This module provides:

- `FoldParameterSnapshot`: one fold's decision-driving parameter values
  (point values and, where available, posterior draws), however obtained.
- `ParameterFoldComparison`: the per-parameter comparison across every
  fold that reported it - point values, posterior draws where available,
  and the plain numeric point-value range. No threshold, no pass/fail
  verdict, no materiality judgement.
- `StructuralStabilityArtefact`: the full structured, per-parameter
  comparison across folds. Never one opaque aggregate score.
- `assess_structural_stability`: assembles the artefact from caller-
  supplied snapshots.

Deliberately out of scope for this module (see REQ-STAB-001's own
"Explicitly excluded"/"Unresolved decisions"):

- Any specific numeric instability threshold, minimum fold-support rule,
  or materiality policy (Part 7 §48 `VL-022`) - this module reports
  movement, never a verdict on whether that movement is acceptable.
- Automatic interpretation (genuine evolution vs. weak identification vs.
  data-definition change vs. leakage artefact vs. misspecification) -
  Requirement 4 assigns that judgement to a human reviewer informed by
  this evidence, not to this module.
- Re-fitting a model per fold. All real-model integration remains
  schedule/manual evidence until a normal-CI-runtime case is measured
  (the same open question REQ-LEAK-001 already recorded).
- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics page -
  deferred to land jointly with `REQ-PPD-001`'s posterior-predictive-
  metric-distribution evidence (Work Package 2 part 1), so the Diagnostics
  UI's required separation of predictive quality, predictive stability,
  structural stability, identification and approval readiness is designed
  as one coherent update, not several uncoordinated ones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Tuple


@dataclass(frozen=True)
class FoldParameterSnapshot:
    """One fold's decision-driving parameter values, however obtained -
    a real per-fold re-fit, an injected/fake extraction for fast contract
    tests, or another approved method (REQ-STAB-001; this module does not
    itself re-fit a model).

    `point_values` maps a parameter name (caller's own naming convention -
    e.g. ``"adstock_decay__TV"``, ``"hill_K__TV"``, ``"beta__TV__fh_new_
    gsa"``) to its point estimate for this fold. `draws`, where supplied,
    maps the same parameter names to that fold's posterior draws for it -
    Requirement 3 requires preserving posterior uncertainty per fold, not
    reducing every fold to a bare point estimate.
    """

    fold_id: str
    point_values: Mapping[str, float] = field(default_factory=dict)
    draws: Mapping[str, Tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.fold_id:
            raise ValueError("fold_id is required")

    def to_dict(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "point_values": dict(self.point_values),
            "draws": {k: list(v) for k, v in self.draws.items()},
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FoldParameterSnapshot":
        return cls(
            fold_id=values["fold_id"],
            point_values=dict(values.get("point_values") or {}),
            draws={k: tuple(v) for k, v in (values.get("draws") or {}).items()},
        )


@dataclass(frozen=True)
class ParameterFoldComparison:
    """One parameter's point values (and, where available, posterior
    draws) across every fold that reported it (REQ-STAB-001 requirements
    2-3). Deliberately carries no threshold, pass/fail verdict, or
    materiality judgement - `point_range` is a plain descriptive number,
    not a stability score."""

    parameter_name: str
    fold_point_values: Tuple[Tuple[str, float], ...]
    fold_draws: Mapping[str, Tuple[float, ...]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.parameter_name:
            raise ValueError("parameter_name is required")

    @property
    def point_range(self) -> float:
        """max - min of this parameter's point values across folds. A
        plain descriptive number, not a threshold or verdict - REQ-STAB-001
        explicitly reserves materiality/threshold policy as a separate,
        decision-required layer (Part 7 VL-022)."""
        if not self.fold_point_values:
            return float("nan")
        values = [v for _, v in self.fold_point_values]
        return float(max(values) - min(values))

    def to_dict(self) -> dict:
        return {
            "parameter_name": self.parameter_name,
            "fold_point_values": [list(pair) for pair in self.fold_point_values],
            "fold_draws": {k: list(v) for k, v in self.fold_draws.items()},
            "point_range": self.point_range,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "ParameterFoldComparison":
        return cls(
            parameter_name=values["parameter_name"],
            fold_point_values=tuple(
                (fold_id, value)
                for fold_id, value in values.get("fold_point_values") or ()
            ),
            fold_draws={
                k: tuple(v) for k, v in (values.get("fold_draws") or {}).items()
            },
        )


@dataclass(frozen=True)
class StructuralStabilityArtefact:
    """The full structured, per-parameter comparison across every
    assessed fold (REQ-STAB-001 requirement 3) - never one opaque
    aggregate health score. `limitations` records every parameter/fold
    combination this artefact could not assemble a complete comparison
    for (e.g. a parameter absent from one fold's snapshot), so an
    incomplete comparison is never silently presented as a complete one.
    """

    fold_ids: Tuple[str, ...]
    per_parameter: Tuple[ParameterFoldComparison, ...]
    limitations: Tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "fold_ids": list(self.fold_ids),
            "per_parameter": [p.to_dict() for p in self.per_parameter],
            "limitations": list(self.limitations),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "StructuralStabilityArtefact":
        return cls(
            fold_ids=tuple(values.get("fold_ids") or ()),
            per_parameter=tuple(
                ParameterFoldComparison.from_dict(p)
                for p in values.get("per_parameter") or ()
            ),
            limitations=tuple(values.get("limitations") or ()),
        )


def assess_structural_stability(
    snapshots: Tuple[FoldParameterSnapshot, ...],
) -> StructuralStabilityArtefact:
    """Assemble a `StructuralStabilityArtefact` from caller-supplied
    per-fold parameter snapshots (REQ-STAB-001).

    Compares every parameter that appears in at least one snapshot across
    every fold that reported it. A parameter missing from a fold's
    snapshot is recorded as a limitation for that fold, never silently
    skipped without a trace or backfilled with a fabricated value.
    """
    if not snapshots:
        raise ValueError("snapshots must not be empty")
    fold_ids = tuple(s.fold_id for s in snapshots)
    if len(set(fold_ids)) != len(fold_ids):
        raise ValueError(f"duplicate fold_id(s) in snapshots: {fold_ids}")

    all_parameter_names: set = set()
    for snapshot in snapshots:
        all_parameter_names.update(snapshot.point_values.keys())

    limitations = []
    per_parameter = []
    for name in sorted(all_parameter_names):
        fold_point_values = []
        fold_draws: Dict[str, Tuple[float, ...]] = {}
        for snapshot in snapshots:
            if name not in snapshot.point_values:
                limitations.append(
                    f"Parameter {name!r} is missing from fold "
                    f"{snapshot.fold_id!r}'s snapshot - the cross-fold "
                    "comparison for this parameter is incomplete."
                )
                continue
            fold_point_values.append((snapshot.fold_id, snapshot.point_values[name]))
            if name in snapshot.draws:
                fold_draws[snapshot.fold_id] = tuple(snapshot.draws[name])
        per_parameter.append(
            ParameterFoldComparison(
                parameter_name=name,
                fold_point_values=tuple(fold_point_values),
                fold_draws=fold_draws,
            )
        )

    return StructuralStabilityArtefact(
        fold_ids=fold_ids,
        per_parameter=tuple(per_parameter),
        limitations=tuple(limitations),
    )
