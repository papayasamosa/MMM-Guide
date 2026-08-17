"""
Governed `WeeklyPlan` construction boundary (Work Package 4 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`).

Builds a validated `core.sequential_simulation.WeeklyPlan` from phased
weekly media/model-input allocations (`core.planning.phasing.
WeeklyAllocationResult`/`WeeklyModelInputDerivation`) plus a
`core.planning.future_context.FutureContextResult`, validating everything
`WeeklyPlan.__post_init__` does not already check: exact canonical week
order (every input's `period_labels` must equal the same canonical
sequence, not merely the same length), an exact expected channel set (no
unknown channel silently ignored - `WeeklyPlan.to_media_matrix` only
raises for a *missing* channel, never for an unexpected extra one), finite
non-negative values even on a directly-constructed allocation, and
Fourier/outcome/control shape and identity against the fitted model. This
is deliberately a thin governance layer above `WeeklyPlan`, not a
competing plan representation, and it never duplicates
`application.scenario_service`'s existing `ScenarioPlan` (the steady-state
monthly plan value object) - that remains the steady-state method's own
input type, wired above `core.optimization`/`core.predict.
steady_state_outcome_response`, not this sequential engine.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Tuple

import numpy as np

from ..hierarchical_model import FHModelMeta
from ..sequential_simulation import WeeklyPlan
from .future_context import FutureContextResult

WEEKLY_PLAN_CONSTRUCTION_SCHEMA_VERSION = 1


class WeeklyPlanConstructionError(ValueError):
    """Raised when a phased allocation + future context cannot be safely
    assembled into a governed `WeeklyPlan` - never silently coerced or
    truncated to fit."""


class _WeeklyAllocationLike(Protocol):
    """Structural contract both `core.planning.phasing.
    WeeklyAllocationResult` (model-input path) and `WeeklyModelInputDerivation`
    (monetary path's cost-mapping-derived quantity) satisfy - this module
    accepts either without caring which phasing path produced it."""

    market: str
    period_labels: Tuple[str, ...]

    def as_array(self) -> np.ndarray: ...


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_hex(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


@dataclass(frozen=True)
class WeeklyPlanConstructionProvenance:
    """Auditable evidence of what a governed `WeeklyPlan` was built from -
    every phased channel allocation's own fingerprint plus the future
    context's fingerprint, so a change to either is detectable without
    re-deriving the whole plan."""

    market: str
    period_labels: Tuple[str, ...]
    channel_names: Tuple[str, ...]
    future_context_fingerprint: str
    schema_version: int = WEEKLY_PLAN_CONSTRUCTION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "period_labels": list(self.period_labels),
            "channel_names": list(self.channel_names),
            "future_context_fingerprint": self.future_context_fingerprint,
            "schema_version": self.schema_version,
        }

    def fingerprint(self) -> str:
        return _sha256_hex(self.to_dict())


def build_governed_weekly_plan(
    *,
    market: str,
    meta: FHModelMeta,
    channel_allocations: Mapping[str, _WeeklyAllocationLike],
    future_context: FutureContextResult,
    expected_n_fourier_columns: int,
    candidate_a_paid_search_cap: Optional[np.ndarray] = None,
) -> Tuple[WeeklyPlan, WeeklyPlanConstructionProvenance]:
    """Assemble and validate a governed `WeeklyPlan` for `market`.

    `channel_allocations` must have exactly one entry per
    `meta.channels` (`{channel_name: WeeklyAllocationResult |
    WeeklyModelInputDerivation}`) - an unknown extra channel or a missing
    one both raise, rather than the unknown one being silently dropped or
    the missing one only surfacing later inside `WeeklyPlan.
    to_media_matrix`.
    """
    if future_context.market != market:
        raise WeeklyPlanConstructionError(
            f"future_context.market ({future_context.market!r}) does not "
            f"match the requested market ({market!r})."
        )
    if market not in meta.markets:
        raise WeeklyPlanConstructionError(
            f"{market!r} is not one of this model's markets: {meta.markets}."
        )

    expected_channels = set(meta.channels)
    got_channels = set(channel_allocations)
    unknown = sorted(got_channels - expected_channels)
    missing = sorted(expected_channels - got_channels)
    if unknown:
        raise WeeklyPlanConstructionError(
            f"channel_allocations contains channel(s) not in this fit's "
            f"channel set and cannot be silently ignored: {unknown} - "
            f"expected exactly {sorted(expected_channels)}."
        )
    if missing:
        raise WeeklyPlanConstructionError(
            f"channel_allocations is missing required channel(s): {missing} "
            f"- expected exactly {sorted(expected_channels)}."
        )

    canonical_weeks = future_context.period_labels
    media_by_channel: Dict[str, np.ndarray] = {}
    for channel in meta.channels:
        allocation = channel_allocations[channel]
        if allocation.market != market:
            raise WeeklyPlanConstructionError(
                f"channel_allocations[{channel!r}].market "
                f"({allocation.market!r}) does not match the requested "
                f"market ({market!r})."
            )
        if tuple(allocation.period_labels) != tuple(canonical_weeks):
            raise WeeklyPlanConstructionError(
                f"channel_allocations[{channel!r}].period_labels does not "
                "exactly match the future context's canonical week order - "
                f"expected {canonical_weeks!r}, got "
                f"{tuple(allocation.period_labels)!r}."
            )
        values = allocation.as_array()
        if not np.all(np.isfinite(values)):
            raise WeeklyPlanConstructionError(
                f"channel_allocations[{channel!r}] contains non-finite value(s)."
            )
        if np.any(values < 0):
            raise WeeklyPlanConstructionError(
                f"channel_allocations[{channel!r}] contains negative "
                "value(s) - a weekly media/model-input plan must be "
                "non-negative."
            )
        media_by_channel[channel] = values

    if future_context.outcome_ids != tuple(meta.outcome_ids):
        raise WeeklyPlanConstructionError(
            "future_context.outcome_ids does not match this fit's "
            f"outcome_ids - expected {tuple(meta.outcome_ids)!r}, got "
            f"{future_context.outcome_ids!r}."
        )
    if future_context.promo.shape != (len(canonical_weeks), len(meta.outcome_ids)):
        raise WeeklyPlanConstructionError(
            "future_context.promo has shape "
            f"{future_context.promo.shape}, expected "
            f"{(len(canonical_weeks), len(meta.outcome_ids))} (one row per "
            "canonical week, one column per fitted outcome)."
        )
    if future_context.fourier.shape != (
        len(canonical_weeks),
        expected_n_fourier_columns,
    ):
        raise WeeklyPlanConstructionError(
            f"future_context.fourier has shape {future_context.fourier.shape}, "
            f"expected {(len(canonical_weeks), expected_n_fourier_columns)} "
            "(one row per canonical week, one column per fitted Fourier term)."
        )

    fitted_control_names = tuple(getattr(meta, "control_names", ()) or ())
    if future_context.control_names != fitted_control_names:
        raise WeeklyPlanConstructionError(
            "future_context.control_names does not match this fit's "
            f"control_names - expected {fitted_control_names!r}, got "
            f"{future_context.control_names!r}."
        )

    fitted_outcome_control_names = {
        oid: tuple(names)
        for oid, names in (getattr(meta, "outcome_control_names", None) or {}).items()
    }
    if future_context.outcome_control_names != fitted_outcome_control_names:
        raise WeeklyPlanConstructionError(
            "future_context.outcome_control_names does not match this "
            f"fit's outcome_control_names - expected "
            f"{fitted_outcome_control_names!r}, got "
            f"{future_context.outcome_control_names!r}."
        )

    plan = WeeklyPlan(
        market=market,
        period_labels=canonical_weeks,
        media_by_channel=media_by_channel,
        promo=future_context.promo,
        trend=future_context.trend,
        fourier=future_context.fourier,
        control_names=future_context.control_names,
        X_controls=(
            future_context.X_controls if future_context.control_names else None
        ),
        outcome_controls=future_context.outcome_controls,
        outcome_control_names={
            oid: list(names)
            for oid, names in future_context.outcome_control_names.items()
        },
        candidate_a_paid_search_cap=candidate_a_paid_search_cap,
    )

    provenance = WeeklyPlanConstructionProvenance(
        market=market,
        period_labels=canonical_weeks,
        channel_names=tuple(meta.channels),
        future_context_fingerprint=future_context.fingerprint(),
    )
    return plan, provenance


__all__ = [
    "WeeklyPlanConstructionError",
    "WeeklyPlanConstructionProvenance",
    "build_governed_weekly_plan",
]
