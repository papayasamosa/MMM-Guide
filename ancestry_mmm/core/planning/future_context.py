"""
Future-context builder (`REQ-SCEN-002`, Work Package 4 of `Media-Mix-Lab:
Coding LLM Next Steps Post PR262`).

Bridges a future canonical weekly calendar to the trend/Fourier/promotion/
control arrays `core.sequential_simulation.WeeklyPlan` needs for
non-decision context, deterministically reproducing the fitted model's own
trend/Fourier definitions rather than inventing a new one:

- **Trend**: `data.preprocessor.prepare_fh_modeling_frame` defines trend as
  a per-market row-position index normalized by that market's own
  historical row count (`arange(n) / max(n - 1, 1)`) - not date-derived,
  no shared origin across markets. `continue_trend` continues that SAME
  formula forward at future row positions `n, n+1, ...` (never reset to
  zero, never held flat at the last historical value - REQ-SCEN-002:
  "generated deterministically... using the same model definition the
  fitted model used"). This module cannot *import*
  `data.preprocessor` (that module already imports from `core` - `core`
  depending on `data` would be a circular/layering-inverted dependency,
  see root `AGENTS.md`'s "Architecture" section), so `continue_trend`
  mirrors the formula instead; kept numerically identical by
  `test_future_context.py::test_continue_trend_matches_fit_time_definition`.
- **Fourier/seasonality**: `data.preprocessor.create_fourier_features_from_calendar`
  is already a pure function of calendar date (day-of-year based,
  `period_days=365.25`) with no historical-length dependency, so it is
  inherently correct for any future date unchanged. `continue_fourier`
  mirrors that same formula for the same import-layering reason above;
  kept numerically identical by
  `test_future_context.py::test_continue_fourier_matches_fit_time_definition`.
- **Promotions/events**: REQ-SCEN-002 requires an explicit planned value
  or approved event schedule for every future period, in every mode - no
  `hold_last_observed` relaxation exists for promotions (that relaxation
  is scoped to "future exogenous controls" only).
- **Exogenous controls**: official mode requires an explicit future path
  for every required period, fail-closed if absent - no silent
  `hold_last_observed`. Exploratory mode may explicitly opt a specific,
  eligible control into `hold_last_observed`; that assumption is recorded
  per-control (`FutureControlAssumption`), and `FutureContextResult.
  is_decision_ready` is `False` whenever any control used it.

Deliberately out of scope (REQ-SCEN-002's own "Not yet covered" boundary,
root `AGENTS.md`'s future-variable-role invariants): Chronos-2 or any
other external forecaster; forecasting an endogenous mediator (e.g.
Candidate A branded-search demand) as though it were an exogenous
control - this module has no mediator-forecasting code path at all.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

FUTURE_CONTEXT_SCHEMA_VERSION = 1

OFFICIAL_MODE = "official"
EXPLORATORY_MODE = "exploratory"
_VALID_MODES = frozenset({OFFICIAL_MODE, EXPLORATORY_MODE})

HOLD_LAST_OBSERVED_ASSUMPTION = "hold_last_observed"
EXPLICIT_ASSUMPTION = "explicit"


class FutureContextError(ValueError):
    """Raised when the future context cannot be safely built - a missing
    required future control/promo value, an unsupported mode, or malformed
    input. Never silently filled (REQ-SCEN-002: "fail closed if absent")."""


def continue_trend(historical_n_weeks: int, n_future_weeks: int) -> np.ndarray:
    """See module docstring's "Trend" section. `historical_n_weeks` is
    this market's own historical row count (not shared across markets -
    matching `prepare_fh_modeling_frame`'s per-market convention
    exactly)."""
    if historical_n_weeks < 1:
        raise FutureContextError(
            f"historical_n_weeks must be at least 1, got {historical_n_weeks!r}."
        )
    if n_future_weeks < 1:
        raise FutureContextError(
            f"n_future_weeks must be at least 1, got {n_future_weeks!r}."
        )
    denom = max(historical_n_weeks - 1, 1)
    future_positions = np.arange(
        historical_n_weeks, historical_n_weeks + n_future_weeks
    )
    return future_positions / denom


def continue_fourier(period_labels: Sequence[str], n_harmonics: int) -> np.ndarray:
    """See module docstring's "Fourier/seasonality" section."""
    if n_harmonics < 1:
        raise FutureContextError(
            f"n_harmonics must be at least 1, got {n_harmonics!r}."
        )
    if not period_labels:
        raise FutureContextError("period_labels must not be empty.")
    doy = pd.to_datetime(list(period_labels)).dayofyear.to_numpy(dtype=float)
    features = []
    for k in range(1, n_harmonics + 1):
        features.append(np.sin(2 * np.pi * k * doy / 365.25))
        features.append(np.cos(2 * np.pi * k * doy / 365.25))
    return np.column_stack(features)


@dataclass(frozen=True)
class FutureControlAssumption:
    """Provenance for one exogenous control's future path (REQ-SCEN-002:
    an exploratory-mode `hold_last_observed` assumption must be visible,
    stored, fingerprinted, and excluded from decision-ready status)."""

    name: str
    assumption: str  # EXPLICIT_ASSUMPTION | HOLD_LAST_OBSERVED_ASSUMPTION
    is_decision_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "assumption": self.assumption,
            "is_decision_ready": self.is_decision_ready,
        }


def _resolve_future_series(
    *,
    name: str,
    period_labels: Sequence[str],
    explicit_future: Optional[Mapping[str, float]],
    mode: str,
    eligible_for_hold_last_observed: bool,
    last_observed_value: Optional[float],
    requested_hold_last_observed: bool,
) -> Tuple[np.ndarray, FutureControlAssumption]:
    """One exogenous control's future series, per REQ-SCEN-002's official/
    exploratory contract (see module docstring). Never silently falls
    back - every branch that does not return an explicit future path
    raises with a specific reason."""
    if explicit_future is not None:
        missing = [w for w in period_labels if w not in explicit_future]
        if missing:
            raise FutureContextError(
                f"{name!r} has an explicit future path but is missing "
                f"value(s) for week(s): {missing}."
            )
        values = np.array([float(explicit_future[w]) for w in period_labels])
        if not np.all(np.isfinite(values)):
            raise FutureContextError(
                f"{name!r}'s explicit future path has non-finite value(s)."
            )
        return values, FutureControlAssumption(name, EXPLICIT_ASSUMPTION, True)

    if mode == OFFICIAL_MODE:
        raise FutureContextError(
            f"{name!r} has no explicit future path - official mode "
            "requires an explicit future value for every required "
            "period; missing values block rather than silently using "
            "hold_last_observed."
        )

    if not requested_hold_last_observed:
        raise FutureContextError(
            f"{name!r} has no explicit future path and was not "
            "explicitly opted into hold_last_observed - exploratory mode "
            "still requires an explicit, visible choice, never a silent "
            "default."
        )
    if not eligible_for_hold_last_observed:
        raise FutureContextError(f"{name!r} is not eligible for hold_last_observed.")
    if last_observed_value is None or not np.isfinite(last_observed_value):
        raise FutureContextError(
            f"{name!r} has no finite last-observed value to hold - cannot "
            "apply hold_last_observed."
        )
    values = np.full(len(period_labels), float(last_observed_value))
    return values, FutureControlAssumption(name, HOLD_LAST_OBSERVED_ASSUMPTION, False)


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_hex(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


@dataclass(frozen=True)
class FutureContextResult:
    """The complete non-decision future context for one market/plan
    window - trend, Fourier, promotions, and exogenous controls, plus
    provenance. Never itself a decision (media/spend) - see
    `core.sequential_simulation.WeeklyPlan` for that."""

    market: str
    period_labels: Tuple[str, ...]
    mode: str
    trend: np.ndarray
    fourier: np.ndarray
    promo: np.ndarray  # (n_weeks, n_outcomes)
    outcome_ids: Tuple[str, ...]
    control_names: Tuple[str, ...]
    X_controls: np.ndarray  # (n_weeks, len(control_names))
    outcome_controls: Dict[str, np.ndarray]
    outcome_control_names: Dict[str, Tuple[str, ...]]
    control_assumptions: Tuple[FutureControlAssumption, ...]
    schema_version: int = FUTURE_CONTEXT_SCHEMA_VERSION

    @property
    def is_decision_ready(self) -> bool:
        """`False` whenever any control used an exploratory
        `hold_last_observed` assumption (REQ-SCEN-002: "exclude it from
        decision-ready status")."""
        return all(a.is_decision_ready for a in self.control_assumptions)

    def fingerprint(self) -> str:
        payload = {
            "market": self.market,
            "period_labels": list(self.period_labels),
            "mode": self.mode,
            "trend": self.trend.tolist(),
            "fourier": self.fourier.tolist(),
            "promo": self.promo.tolist(),
            "outcome_ids": list(self.outcome_ids),
            "control_names": list(self.control_names),
            "X_controls": self.X_controls.tolist(),
            "outcome_controls": {
                k: v.tolist() for k, v in sorted(self.outcome_controls.items())
            },
            "control_assumptions": [a.to_dict() for a in self.control_assumptions],
            "schema_version": self.schema_version,
        }
        return _sha256_hex(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market": self.market,
            "period_labels": list(self.period_labels),
            "mode": self.mode,
            "trend": self.trend.tolist(),
            "fourier": self.fourier.tolist(),
            "promo": self.promo.tolist(),
            "outcome_ids": list(self.outcome_ids),
            "control_names": list(self.control_names),
            "X_controls": self.X_controls.tolist(),
            "outcome_controls": {
                key: value.tolist() for key, value in self.outcome_controls.items()
            },
            "outcome_control_names": {
                key: list(value) for key, value in self.outcome_control_names.items()
            },
            "control_assumptions": [
                assumption.to_dict() for assumption in self.control_assumptions
            ],
            "schema_version": self.schema_version,
            "fingerprint": self.fingerprint(),
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "FutureContextResult":
        payload = dict(values)
        payload["period_labels"] = tuple(payload.get("period_labels") or ())
        payload["trend"] = np.asarray(payload.get("trend") or (), dtype=float)
        payload["fourier"] = np.asarray(payload.get("fourier") or (), dtype=float)
        payload["promo"] = np.asarray(payload.get("promo") or (), dtype=float)
        payload["outcome_ids"] = tuple(payload.get("outcome_ids") or ())
        payload["control_names"] = tuple(payload.get("control_names") or ())
        payload["X_controls"] = np.asarray(payload.get("X_controls") or (), dtype=float)
        payload["outcome_controls"] = {
            key: np.asarray(value, dtype=float)
            for key, value in (payload.get("outcome_controls") or {}).items()
        }
        payload["outcome_control_names"] = {
            key: tuple(value)
            for key, value in (payload.get("outcome_control_names") or {}).items()
        }
        payload["control_assumptions"] = tuple(
            FutureControlAssumption(
                name=str(item["name"]),
                assumption=str(item["assumption"]),
                is_decision_ready=bool(item["is_decision_ready"]),
            )
            for item in (payload.get("control_assumptions") or ())
        )
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def build_future_context(
    *,
    market: str,
    period_labels: Sequence[str],
    historical_n_weeks: int,
    n_fourier_harmonics: int,
    outcome_ids: Sequence[str],
    control_names: Sequence[str] = (),
    outcome_control_names: Optional[Mapping[str, Sequence[str]]] = None,
    mode: str,
    promo_future: Mapping[str, Mapping[str, float]],
    control_future: Optional[Mapping[str, Mapping[str, float]]] = None,
    outcome_control_future: Optional[
        Mapping[str, Mapping[str, Mapping[str, float]]]
    ] = None,
    eligible_for_hold_last_observed: FrozenSet[str] = frozenset(),
    hold_last_observed: FrozenSet[str] = frozenset(),
    last_observed_controls: Optional[Mapping[str, float]] = None,
    last_observed_outcome_controls: Optional[Mapping[str, float]] = None,
) -> FutureContextResult:
    """Build the complete future non-decision context for one market.

    `promo_future` is `{outcome_id: {week_label: value}}` and is always
    required explicitly, regardless of `mode` (REQ-SCEN-002: no
    `hold_last_observed` relaxation for promotions/events).

    `control_future`/`outcome_control_future` supply explicit future
    values the same way; a control name in `hold_last_observed`
    (exploratory mode only, and only if also present in
    `eligible_for_hold_last_observed`) may instead be held at its
    `last_observed_controls`/`last_observed_outcome_controls` value.
    `outcome_control_future`/`last_observed_outcome_controls` key outcome
    controls as `f"{outcome_id}.{control_name}"`.
    """
    if mode not in _VALID_MODES:
        raise FutureContextError(
            f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}."
        )
    if not period_labels:
        raise FutureContextError("period_labels must not be empty.")
    period_labels = tuple(period_labels)
    n_weeks = len(period_labels)
    outcome_ids = tuple(outcome_ids)
    control_names = tuple(control_names)
    normalized_outcome_control_names: Dict[str, Tuple[str, ...]] = {
        k: tuple(v) for k, v in (outcome_control_names or {}).items()
    }
    control_future = control_future or {}
    outcome_control_future = outcome_control_future or {}
    last_observed_controls = last_observed_controls or {}
    last_observed_outcome_controls = last_observed_outcome_controls or {}

    trend = continue_trend(historical_n_weeks, n_weeks)
    fourier = continue_fourier(period_labels, n_fourier_harmonics)

    missing_promo_outcomes = [o for o in outcome_ids if o not in promo_future]
    if missing_promo_outcomes:
        raise FutureContextError(
            "promo_future is missing (an) outcome_id(s) entirely: "
            f"{missing_promo_outcomes} - promotions/events require an "
            "explicit planned value for every required period in every "
            "mode."
        )
    promo_columns = []
    for outcome_id in outcome_ids:
        series, _assumption = _resolve_future_series(
            name=f"promo[{outcome_id}]",
            period_labels=period_labels,
            explicit_future=promo_future[outcome_id],
            mode=OFFICIAL_MODE,  # promo never gets the hold-last-observed relaxation
            eligible_for_hold_last_observed=False,
            last_observed_value=None,
            requested_hold_last_observed=False,
        )
        promo_columns.append(series)
    promo = np.column_stack(promo_columns) if promo_columns else np.zeros((n_weeks, 0))

    control_assumptions: List[FutureControlAssumption] = []
    control_columns = []
    for name in control_names:
        series, assumption = _resolve_future_series(
            name=name,
            period_labels=period_labels,
            explicit_future=control_future.get(name),
            mode=mode,
            eligible_for_hold_last_observed=name in eligible_for_hold_last_observed,
            last_observed_value=last_observed_controls.get(name),
            requested_hold_last_observed=name in hold_last_observed,
        )
        control_columns.append(series)
        control_assumptions.append(assumption)
    X_controls = (
        np.column_stack(control_columns) if control_columns else np.zeros((n_weeks, 0))
    )

    outcome_controls: Dict[str, np.ndarray] = {}
    for outcome_id, names in normalized_outcome_control_names.items():
        columns = []
        for name in names:
            qualified = f"{outcome_id}.{name}"
            series, assumption = _resolve_future_series(
                name=qualified,
                period_labels=period_labels,
                explicit_future=(outcome_control_future.get(outcome_id) or {}).get(
                    name
                ),
                mode=mode,
                eligible_for_hold_last_observed=qualified
                in eligible_for_hold_last_observed,
                last_observed_value=last_observed_outcome_controls.get(qualified),
                requested_hold_last_observed=qualified in hold_last_observed,
            )
            columns.append(series)
            control_assumptions.append(assumption)
        outcome_controls[outcome_id] = (
            np.column_stack(columns) if columns else np.zeros((n_weeks, 0))
        )

    return FutureContextResult(
        market=market,
        period_labels=period_labels,
        mode=mode,
        trend=trend,
        fourier=fourier,
        promo=promo,
        outcome_ids=outcome_ids,
        control_names=control_names,
        X_controls=X_controls,
        outcome_controls=outcome_controls,
        outcome_control_names=normalized_outcome_control_names,
        control_assumptions=tuple(control_assumptions),
    )


__all__ = [
    "EXPLICIT_ASSUMPTION",
    "EXPLORATORY_MODE",
    "HOLD_LAST_OBSERVED_ASSUMPTION",
    "OFFICIAL_MODE",
    "FutureContextError",
    "FutureContextResult",
    "FutureControlAssumption",
    "build_future_context",
    "continue_fourier",
    "continue_trend",
]
