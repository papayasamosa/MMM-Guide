"""Governed mappings between model media inputs and monetary spend.

MMM response functions may consume currency, impressions, clicks, GRPs, or
another delivery unit.  This module keeps that model input distinct from
money and makes monetary economics conditional on an approved, effective
market/channel/context mapping.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
from typing import Any, Dict, Iterable, Mapping, Optional, Protocol, Tuple

import numpy as np

APPROVED = "approved"
SUPPORTED_METHODS = {
    "identity_spend",
    "fixed_cost_per_unit",
    "piecewise_linear",
    "uploaded_plan",
}


@dataclass(frozen=True)
class MediaInputSpec:
    """Identity and scale of one model input at market/channel grain."""

    market: str
    channel: str
    column: str
    unit: str
    unit_scale: float = 1.0
    input_kind: str = "exposure"
    cost_mapping_required: bool = True
    source: str = ""
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    schema_version: int = 1
    scale_contract: str = "descriptive_only"

    def __post_init__(self) -> None:
        if not all((self.market, self.channel, self.column, self.unit)):
            raise ValueError("market, channel, column, and unit are required")
        if not np.isfinite(self.unit_scale) or self.unit_scale <= 0:
            raise ValueError("unit_scale must be finite and positive")
        if self.input_kind not in {"monetary_spend", "exposure"}:
            raise ValueError("input_kind must be monetary_spend or exposure")
        if self.scale_contract != "descriptive_only":
            raise ValueError(
                "unit_scale is descriptive metadata; model inputs must already "
                "be in their fitted numeric unit"
            )
        _validate_period(self.effective_period_start, self.effective_period_end)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "MediaInputSpec":
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})


class MediaCostMapping(Protocol):
    """Typed interface required by monetary response curves."""

    mapping_id: str
    method: str
    market: str
    channel: str
    cost_context_id: str
    currency: str
    effective_period_start: Optional[str]
    effective_period_end: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[str]
    owner: Optional[str]
    approval_note: Optional[str]

    def spend_to_media_input(self, spend: float | np.ndarray) -> np.ndarray: ...

    def media_input_to_spend(
        self, media_input: float | np.ndarray
    ) -> np.ndarray: ...

    def marginal_cost_per_media_input(
        self, media_input: float | np.ndarray
    ) -> np.ndarray: ...

    def marginal_media_input_per_currency(
        self, spend: float | np.ndarray
    ) -> np.ndarray: ...

    def is_valid_for(self, *, as_of: Optional[str] = None) -> bool: ...

    def to_dict(self) -> dict: ...


@dataclass(frozen=True)
class GovernedCostMapping:
    """Common governance fields for every cost mapping."""

    mapping_id: str
    market: str
    channel: str
    currency: str
    cost_context_id: str = "default"
    source: str = ""
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    assumptions: str = ""
    approval_status: str = "draft"
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    owner: Optional[str] = None
    approval_note: Optional[str] = None
    last_reviewed_at: Optional[str] = None
    supersedes_mapping_id: Optional[str] = None
    schema_version: int = 2

    def __post_init__(self) -> None:
        if not all(
            (
                self.mapping_id,
                self.market,
                self.channel,
                self.currency,
                self.cost_context_id,
            )
        ):
            raise ValueError(
                "mapping_id, market, channel, currency, and cost_context_id are required"
            )
        if (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or self.currency != self.currency.upper()
        ):
            raise ValueError("currency must be an uppercase three-letter ISO code")
        _validate_period(self.effective_period_start, self.effective_period_end)
        if self.approval_status == APPROVED and not all(
            (
                self.approved_by,
                self.approved_at,
                self.owner,
                self.approval_note,
                self.last_reviewed_at,
            )
        ):
            raise ValueError(
                "approved mappings require approved_by, approved_at, owner, "
                "approval_note, and last_reviewed_at"
            )

    def is_valid_for(self, *, as_of: Optional[str] = None) -> bool:
        if self.approval_status != APPROVED:
            return False
        if as_of is None:
            return True
        when = date.fromisoformat(as_of)
        if (
            self.effective_period_start
            and when < date.fromisoformat(self.effective_period_start)
        ):
            return False
        return not (
            self.effective_period_end
            and when > date.fromisoformat(self.effective_period_end)
        )

    def _base_dict(self) -> dict:
        values = asdict(self)
        values["currency"] = self.currency.upper()
        return values


@dataclass(frozen=True)
class IdentitySpendMapping(GovernedCostMapping):
    """One currency unit is one model media-input unit."""

    method: str = "identity_spend"

    def spend_to_media_input(self, spend: float | np.ndarray) -> np.ndarray:
        return _nonnegative_array(spend, "spend")

    def media_input_to_spend(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        return _nonnegative_array(media_input, "media_input")

    def marginal_cost_per_media_input(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        return np.ones_like(_nonnegative_array(media_input, "media_input"))

    def marginal_media_input_per_currency(
        self, spend: float | np.ndarray
    ) -> np.ndarray:
        return np.ones_like(_nonnegative_array(spend, "spend"))

    def to_dict(self) -> dict:
        return self._base_dict()


@dataclass(frozen=True)
class FixedCostPerUnitMapping(GovernedCostMapping):
    """Constant local-currency cost for one model media-input unit."""

    cost_per_media_input: float = 1.0
    method: str = "fixed_cost_per_unit"

    def __post_init__(self) -> None:
        super().__post_init__()
        if (
            not np.isfinite(self.cost_per_media_input)
            or self.cost_per_media_input <= 0
        ):
            raise ValueError("cost_per_media_input must be finite and positive")

    def spend_to_media_input(self, spend: float | np.ndarray) -> np.ndarray:
        return _nonnegative_array(spend, "spend") / self.cost_per_media_input

    def media_input_to_spend(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        return (
            _nonnegative_array(media_input, "media_input")
            * self.cost_per_media_input
        )

    def marginal_cost_per_media_input(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        values = _nonnegative_array(media_input, "media_input")
        return np.full_like(values, self.cost_per_media_input)

    def marginal_media_input_per_currency(
        self, spend: float | np.ndarray
    ) -> np.ndarray:
        values = _nonnegative_array(spend, "spend")
        return np.full_like(values, 1.0 / self.cost_per_media_input)

    def to_dict(self) -> dict:
        return self._base_dict()


@dataclass(frozen=True)
class PiecewiseLinearCostMapping(GovernedCostMapping):
    """Monotone spend/media-input knots with local linear marginal cost."""

    spend_knots: Tuple[float, ...] = ()
    media_input_knots: Tuple[float, ...] = ()
    allow_extrapolation: bool = False
    method: str = "piecewise_linear"

    def __post_init__(self) -> None:
        super().__post_init__()
        spend = np.asarray(self.spend_knots, dtype=float)
        media = np.asarray(self.media_input_knots, dtype=float)
        if (
            len(spend) < 2
            or len(spend) != len(media)
            or np.any(~np.isfinite(spend))
            or np.any(~np.isfinite(media))
            or np.any(spend < 0)
            or np.any(media < 0)
            or np.any(np.diff(spend) <= 0)
            or np.any(np.diff(media) <= 0)
        ):
            raise ValueError(
                "knots must be equal-length, finite, non-negative, and strictly increasing"
            )

    def spend_to_media_input(self, spend: float | np.ndarray) -> np.ndarray:
        values = _nonnegative_array(spend, "spend")
        return _piecewise(
            values,
            np.asarray(self.spend_knots),
            np.asarray(self.media_input_knots),
            self.allow_extrapolation,
        )

    def media_input_to_spend(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        values = _nonnegative_array(media_input, "media_input")
        return _piecewise(
            values,
            np.asarray(self.media_input_knots),
            np.asarray(self.spend_knots),
            self.allow_extrapolation,
        )

    def marginal_cost_per_media_input(
        self, media_input: float | np.ndarray
    ) -> np.ndarray:
        values = _nonnegative_array(media_input, "media_input")
        return _piecewise_slopes(
            values,
            np.asarray(self.media_input_knots),
            np.asarray(self.spend_knots),
            self.allow_extrapolation,
        )

    def marginal_media_input_per_currency(
        self, spend: float | np.ndarray
    ) -> np.ndarray:
        values = _nonnegative_array(spend, "spend")
        return _piecewise_slopes(
            values,
            np.asarray(self.spend_knots),
            np.asarray(self.media_input_knots),
            self.allow_extrapolation,
        )

    def to_dict(self) -> dict:
        values = self._base_dict()
        values["spend_knots"] = list(self.spend_knots)
        values["media_input_knots"] = list(self.media_input_knots)
        return values


@dataclass(frozen=True)
class UploadedPlanCostMapping(PiecewiseLinearCostMapping):
    """Piecewise mapping derived from an identified uploaded media plan."""

    plan_id: str = ""
    method: str = "uploaded_plan"

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.plan_id:
            raise ValueError("uploaded plan mappings require plan_id")


def cost_mapping_from_dict(values: Mapping[str, Any]) -> MediaCostMapping:
    """Deserialize a governed mapping without accepting unknown methods."""

    method = values.get("method")
    mapping_types = {
        "identity_spend": IdentitySpendMapping,
        "fixed_cost_per_unit": FixedCostPerUnitMapping,
        "piecewise_linear": PiecewiseLinearCostMapping,
        "uploaded_plan": UploadedPlanCostMapping,
    }
    try:
        cls = mapping_types[str(method)]
    except KeyError as exc:
        raise ValueError(f"Unsupported cost mapping method: {method!r}") from exc
    known = set(cls.__dataclass_fields__)
    payload = {key: value for key, value in values.items() if key in known}
    if (
        int(payload.get("schema_version", 1)) < 2
        and payload.get("approval_status") == APPROVED
        and not all(
            payload.get(name)
            for name in (
                "approved_at",
                "owner",
                "approval_note",
                "last_reviewed_at",
            )
        )
    ):
        payload["approval_status"] = "migration_required"
    for key in ("spend_knots", "media_input_knots"):
        if key in payload:
            payload[key] = tuple(payload[key])
    return cls(**payload)


class CostMappingRegistry:
    """Exact market/channel/context lookup with JSON-safe persistence."""

    def __init__(self, mappings: Iterable[MediaCostMapping] = ()) -> None:
        self._mappings: Dict[
            Tuple[str, str, str], list[MediaCostMapping]
        ] = {}
        self._mapping_ids: set[str] = set()
        for mapping in mappings:
            self.add(mapping)

    def add(self, mapping: MediaCostMapping) -> None:
        key = (mapping.market, mapping.channel, mapping.cost_context_id)
        if mapping.mapping_id in self._mapping_ids:
            raise ValueError(f"Duplicate cost mapping ID: {mapping.mapping_id}")
        existing = self._mappings.setdefault(key, [])
        if any(_periods_overlap(mapping, other) for other in existing):
            raise ValueError(f"Overlapping effective cost mappings for {key}")
        existing.append(mapping)
        self._mapping_ids.add(mapping.mapping_id)

    def resolve(
        self,
        market: str,
        channel: str,
        cost_context_id: str = "default",
        *,
        as_of: Optional[str] = None,
    ) -> Optional[MediaCostMapping]:
        candidates = [
            mapping
            for mapping in self._mappings.get(
                (market, channel, cost_context_id), []
            )
            if mapping.is_valid_for(as_of=as_of)
        ]
        if not candidates:
            return None
        if len(candidates) > 1:
            raise ValueError(
                "Cost mapping selection is ambiguous; supply an as_of date"
            )
        return candidates[0]

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "mappings": [
                mapping.to_dict()
                for key in sorted(self._mappings)
                for mapping in sorted(
                    self._mappings[key], key=lambda item: item.mapping_id
                )
            ],
        }

    def fingerprint(self) -> str:
        payload = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()

    @classmethod
    def from_dict(cls, values: Optional[Mapping[str, Any]]) -> "CostMappingRegistry":
        return cls(
            cost_mapping_from_dict(mapping)
            for mapping in (values or {}).get("mappings", [])
        )


@dataclass(frozen=True)
class MediaInputSupport:
    """Observed/planning support expressed only in fitted model-input units."""

    market: str
    channel: str
    unit: str
    current: float
    observed_min: float
    observed_max: float
    planning_min: float
    planning_max: float
    current_method: str
    source: str
    provenance: str
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    axis_type: str = "model_input"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.axis_type != "model_input":
            raise ValueError("MediaInputSupport axis_type must be model_input")
        values = np.asarray(
            [
                self.current,
                self.observed_min,
                self.observed_max,
                self.planning_min,
                self.planning_max,
            ]
        )
        if (
            np.any(~np.isfinite(values))
            or np.any(values < 0)
            or self.observed_min > self.observed_max
            or self.planning_min > self.planning_max
        ):
            raise ValueError("invalid media-input support range")
        _validate_period(self.effective_period_start, self.effective_period_end)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "MediaInputSupport":
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})


@dataclass(frozen=True)
class MonetarySpendSupport:
    """Auditable local/reporting spend support derived from media support."""

    market: str
    channel: str
    local_currency: str
    reporting_currency: str
    current_local: float
    observed_local_min: float
    observed_local_max: float
    planning_local_min: float
    planning_local_max: float
    fx_rate: float
    current_method: str
    source: str
    provenance: str
    cost_mapping_id: str
    cost_mapping_fingerprint: str
    current_media_input: float = 0.0
    observed_media_input_min: float = 0.0
    observed_media_input_max: float = 0.0
    planning_media_input_min: float = 0.0
    planning_media_input_max: float = 0.0
    approval_status: str = APPROVED
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    owner: Optional[str] = None
    approval_note: Optional[str] = None
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    axis_type: str = "monetary"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.axis_type != "monetary":
            raise ValueError("MonetarySpendSupport axis_type must be monetary")
        values = np.asarray(
            [
                self.current_local,
                self.observed_local_min,
                self.observed_local_max,
                self.planning_local_min,
                self.planning_local_max,
                self.fx_rate,
            ]
        )
        if np.any(~np.isfinite(values)) or np.any(values < 0) or self.fx_rate <= 0:
            raise ValueError("invalid monetary support range")
        if self.approval_status == APPROVED and not all(
            (self.approved_by, self.approved_at, self.owner, self.approval_note)
        ):
            raise ValueError(
                "approved monetary support requires approval governance"
            )

    @property
    def current_reporting(self) -> float:
        return self.current_local * self.fx_rate

    def to_dict(self) -> dict:
        values = asdict(self)
        reporting_fields = {
            "current": "current_local",
            "observed_min": "observed_local_min",
            "observed_max": "observed_local_max",
            "planning_min": "planning_local_min",
            "planning_max": "planning_local_max",
        }
        for name, local_name in reporting_fields.items():
            values[f"{name}_reporting"] = values[local_name] * self.fx_rate
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "MonetarySpendSupport":
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in values.items() if key in known})


def derive_monetary_support(
    media: MediaInputSupport,
    mapping: MediaCostMapping,
    *,
    reporting_currency: str,
    fx_rate: float,
    mapping_fingerprint: str,
) -> MonetarySpendSupport:
    """Convert typed model-input support through one governed mapping."""

    if (media.market, media.channel) != (mapping.market, mapping.channel):
        raise ValueError("support and cost mapping market/channel do not match")
    convert = mapping.media_input_to_spend
    return MonetarySpendSupport(
        market=media.market,
        channel=media.channel,
        local_currency=mapping.currency,
        reporting_currency=reporting_currency,
        current_local=float(convert(media.current)),
        observed_local_min=float(convert(media.observed_min)),
        observed_local_max=float(convert(media.observed_max)),
        planning_local_min=float(convert(media.planning_min)),
        planning_local_max=float(convert(media.planning_max)),
        fx_rate=fx_rate,
        current_method=media.current_method,
        source=mapping.source,
        provenance=f"derived_from:{media.provenance}",
        cost_mapping_id=mapping.mapping_id,
        cost_mapping_fingerprint=mapping_fingerprint,
        current_media_input=media.current,
        observed_media_input_min=media.observed_min,
        observed_media_input_max=media.observed_max,
        planning_media_input_min=media.planning_min,
        planning_media_input_max=media.planning_max,
        approval_status=APPROVED,
        approved_by=mapping.approved_by,
        approved_at=mapping.approved_at,
        owner=mapping.owner,
        approval_note=mapping.approval_note,
        effective_period_start=mapping.effective_period_start,
        effective_period_end=mapping.effective_period_end,
    )


def monetary_governance_fingerprint(
    *,
    cost_mappings: Mapping[str, Any] | dict,
    activity_definitions: object,
    fx_metadata: object,
    planning_support: object,
) -> str:
    """Fingerprint every non-model input that governs monetary artefacts."""

    payload = {
        "cost_mappings": cost_mappings,
        "activity_definitions": activity_definitions,
        "fx_metadata": fx_metadata,
        "planning_support": planning_support,
    }
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _validate_period(start: Optional[str], end: Optional[str]) -> None:
    start_date = date.fromisoformat(start) if start else None
    end_date = date.fromisoformat(end) if end else None
    if start_date and end_date and start_date > end_date:
        raise ValueError("effective_period_start must not be after effective_period_end")


def _periods_overlap(
    left: MediaCostMapping, right: MediaCostMapping
) -> bool:
    left_start = (
        date.fromisoformat(left.effective_period_start)
        if left.effective_period_start
        else date.min
    )
    left_end = (
        date.fromisoformat(left.effective_period_end)
        if left.effective_period_end
        else date.max
    )
    right_start = (
        date.fromisoformat(right.effective_period_start)
        if right.effective_period_start
        else date.min
    )
    right_end = (
        date.fromisoformat(right.effective_period_end)
        if right.effective_period_end
        else date.max
    )
    return max(left_start, right_start) <= min(left_end, right_end)


def _nonnegative_array(value: float | np.ndarray, name: str) -> np.ndarray:
    result = np.asarray(value, dtype=float)
    if np.any(~np.isfinite(result)) or np.any(result < 0):
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def _check_domain(values: np.ndarray, knots: np.ndarray, extrapolate: bool) -> None:
    if not extrapolate and (
        np.any(values < knots[0]) or np.any(values > knots[-1])
    ):
        raise ValueError("value is outside the governed mapping support")


def _piecewise(
    values: np.ndarray,
    x_knots: np.ndarray,
    y_knots: np.ndarray,
    extrapolate: bool,
) -> np.ndarray:
    _check_domain(values, x_knots, extrapolate)
    scalar = values.ndim == 0
    working = np.atleast_1d(values)
    result = np.interp(working, x_knots, y_knots)
    if extrapolate:
        low = working < x_knots[0]
        high = working > x_knots[-1]
        result = np.asarray(result)
        result[low] = y_knots[0] + (working[low] - x_knots[0]) * (
            (y_knots[1] - y_knots[0]) / (x_knots[1] - x_knots[0])
        )
        result[high] = y_knots[-1] + (working[high] - x_knots[-1]) * (
            (y_knots[-1] - y_knots[-2]) / (x_knots[-1] - x_knots[-2])
        )
    return result[0] if scalar else result


def _piecewise_slopes(
    values: np.ndarray,
    x_knots: np.ndarray,
    y_knots: np.ndarray,
    extrapolate: bool,
) -> np.ndarray:
    _check_domain(values, x_knots, extrapolate)
    indices = np.searchsorted(x_knots, values, side="right") - 1
    indices = np.clip(indices, 0, len(x_knots) - 2)
    slopes = np.diff(y_knots) / np.diff(x_knots)
    return slopes[indices]
