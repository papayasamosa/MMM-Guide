"""Governed SEO positional-visibility metric definition, observation
record, and deterministic computation (REQ-SEO-001; Decision 5 of the
"Post-UI/UX Implementation Instructions: Approved Business Decisions"
brief).

This module implements the formula Decision 5's own addendum to
`REQ-SEO-001` explicitly deferred as Phase B research-first work: the
exact aggregation and transformation of raw Google Search Console (GSC)
fields into a single, governed positional-visibility metric. See
`docs/seo_positional_visibility_metric_decision_record.md` for the full
options-considered decision record (sources consulted, alternatives
rejected, and why).

Formula summary (see the decision record for the full reasoning):

1. Raw GSC fields consumed: `position` (row-level average rank, 1-indexed,
   lower is better - confirmed by Google's own Search Analytics API and
   Search Console Help Center documentation) and `impressions` (row-level
   impression count). `clicks` is retained as a diagnostic only.
2. Aggregation: impression-weighted average position across whatever rows
   are supplied (queries, pages, days - this module is agnostic to which),
   mirroring Google's own official BigQuery-export formula for combining
   multiple rows' `position` values
   (``(sum(sum_top_position) / sum(impressions)) + 1.0``) rather than a
   naive unweighted mean, which query/page mix shifts would distort.
3. Transformation: `visibility_index = 1.0 / weighted_avg_position` - a
   bounded (0, 1], deterministic, monotonic, higher-is-better index. This
   is a MEASUREMENT-level transformation only (turning a raw, non-linear
   GSC metric into a well-defined, documented number) - it does not select
   the functional form this index takes if and when it later enters an
   actual MMM regression as a treatment (REQ-SEO-001's still-open,
   separate "transformation... for use as a linear treatment" item,
   Decision 6/Phase C's causal-wiring scope).
4. Missing data: a week/market with zero total impressions across all
   supplied rows produces `weighted_avg_position = None` and
   `visibility_index = None` (undefined, never a fabricated value) -
   matching Google's own documented behaviour ("a position is only
   recorded if the result receives an impression"). `total_impressions`/
   `total_clicks` remain real, confirmed numbers (including a genuine
   0.0) in that case, since a confirmed zero-impression week is a
   different, non-missing fact from "we never queried this week at all"
   (the latter is the caller's responsibility to represent via
   `core.coverage`'s vocabulary directly - this function only computes
   from data it is actually given, it never guesses whether an empty
   input means "confirmed zero" or "not queried").
"""

from __future__ import annotations

import math
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple, cast

import numpy as np

from .coverage import COVERAGE_STATES, STATE_OBSERVED_ZERO
from .seo_partial_window_policy import (
    SeoValidEstimationWindow,
    determine_valid_estimation_window,
)

SEO_VISIBILITY_SCHEMA_VERSION = 1

# SEO groups are observed organic-search diagnostics/treatments, never spend
# channels.  Keeping the IDs explicit makes a Brand/Non-Brand split (and any
# approved deeper group) survive model, report, and persistence boundaries.
SEO_GROUP_BRAND = "brand"
SEO_GROUP_NON_BRAND = "non_brand"
SEO_GROUPS = (SEO_GROUP_BRAND, SEO_GROUP_NON_BRAND)

# ---------------------------------------------------------------------------
# REQ-SEO-001 §5 causal-role / directionality vocabulary. `CAUSAL_ROLES`
# reproduces Part 6 §15.8's exact four candidate values; Decision 6 (2026-
# 08-30 addendum) already approved `CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_
# EFFICIENCY_STATE` as the value for the primary metric below - this module
# does not re-decide that, it only carries it through as governed metadata.
# ---------------------------------------------------------------------------

CAUSAL_ROLE_DIAGNOSTIC_ONLY = "diagnostic_only"
CAUSAL_ROLE_OBSERVED_CONTEXT_VARIABLE = "observed_context_variable"
CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE = (
    "mediator_or_capture_efficiency_state"
)
CAUSAL_ROLE_STRUCTURAL_EXPOSURE_INTERVENTION = "structural_exposure_intervention"
CAUSAL_ROLE_NOT_YET_APPROVED = "not_yet_approved"
CAUSAL_ROLES = (
    CAUSAL_ROLE_DIAGNOSTIC_ONLY,
    CAUSAL_ROLE_OBSERVED_CONTEXT_VARIABLE,
    CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE,
    CAUSAL_ROLE_STRUCTURAL_EXPOSURE_INTERVENTION,
    CAUSAL_ROLE_NOT_YET_APPROVED,
)

DIRECTIONALITY_HIGHER_IS_BETTER = "higher_is_better"
DIRECTIONALITY_LOWER_IS_BETTER = "lower_is_better"
DIRECTIONALITIES = (DIRECTIONALITY_HIGHER_IS_BETTER, DIRECTIONALITY_LOWER_IS_BETTER)


@dataclass(frozen=True)
class SeoVisibilityMetricDefinition:
    """One governed `dim_seo_visibility_metric_definition` record
    (`REQ-SEO-001` §1). `direction_relative_to_estimand` stays
    `"not_yet_approved"` even for an approved metric with an approved
    `causal_role` - Decision 6's addendum is explicit that this is
    estimand-specific per use, never a single global setting."""

    metric_name: str
    source_methodology: str
    methodology_version: str
    unit: str
    directionality: str
    aggregation_rule: str
    causal_role: str
    direction_relative_to_estimand: str = CAUSAL_ROLE_NOT_YET_APPROVED
    permitted_roles: Tuple[str, ...] = ()
    interpretation: str = ""
    limitations: str = ""
    approval_status: str = "draft"
    effective_period_start: Optional[str] = None
    effective_period_end: Optional[str] = None
    schema_version: int = SEO_VISIBILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("SeoVisibilityMetricDefinition requires a metric_name.")
        if self.directionality not in DIRECTIONALITIES:
            raise ValueError(
                f"SeoVisibilityMetricDefinition: unknown directionality "
                f"'{self.directionality}' (expected one of {DIRECTIONALITIES})."
            )
        if self.causal_role not in CAUSAL_ROLES:
            raise ValueError(
                f"SeoVisibilityMetricDefinition: unknown causal_role "
                f"'{self.causal_role}' (expected one of {CAUSAL_ROLES})."
            )

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["permitted_roles"] = list(self.permitted_roles)
        return payload

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SeoVisibilityMetricDefinition":
        payload = dict(values)
        if "permitted_roles" in payload:
            payload["permitted_roles"] = tuple(payload["permitted_roles"] or ())
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in payload.items() if k in known}))


# The approved governed metric definition (this module's own decision
# record + REQ-SEO-001's addenda). `direction_relative_to_estimand` is
# deliberately left `not_yet_approved` per Decision 6.
SEO_POSITIONAL_VISIBILITY_METRIC = SeoVisibilityMetricDefinition(
    metric_name="seo_positional_visibility_index",
    source_methodology=(
        "Google Search Console Search Analytics: impression-weighted "
        "average organic search position, transformed to 1/position."
    ),
    methodology_version="1.0.0",
    unit="index_0_to_1",
    directionality=DIRECTIONALITY_HIGHER_IS_BETTER,
    aggregation_rule="impression_weighted_average_position_then_inverse",
    causal_role=CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE,
    permitted_roles=(CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE,),
    interpretation=(
        "Higher values mean better average organic ranking (visibility "
        "close to 1.0 means an average position near the very top of "
        "search results; values near 0 mean a low average position). "
        "Computed only from weeks/markets with at least one impression; "
        "never a proxy for organic Search capture or click volume."
    ),
    limitations=(
        "A single scalar cannot represent the full distribution of "
        "positions across queries/pages; a market with many queries "
        "clustered at position 1 and a long tail at position 50 will "
        "average differently than one with all queries near position 10, "
        "even at the same raw average. The 1/position transform is a "
        "measurement-level choice only - it does not itself decide the "
        "functional form this index takes inside a future MMM regression."
    ),
    approval_status="approved",
)


@dataclass(frozen=True)
class GscPositionRow:
    """One raw Google Search Console Search Analytics row - the shape the
    GSC Search Analytics API's ``rows[]`` returns per query/page/date (or
    whatever dimension combination the caller queried at): ``position``
    (row-level average position, 1-indexed) and ``impressions`` (row-level
    impression count) are the two fields this metric is computed from;
    ``clicks`` is carried through only as a retained diagnostic."""

    dimension_label: str
    position: float
    impressions: float
    clicks: float = 0.0

    def __post_init__(self) -> None:
        if self.impressions < 0:
            raise ValueError("GscPositionRow.impressions must be non-negative.")
        if self.clicks < 0:
            raise ValueError("GscPositionRow.clicks must be non-negative.")
        if self.impressions > 0 and self.position < 1:
            raise ValueError(
                "GscPositionRow.position must be >= 1 when impressions > 0 "
                "- Google Search Console's position field is 1-indexed."
            )


@dataclass(frozen=True)
class SeoPositionalVisibilityObservation:
    """One governed `fact_seo_visibility_observation` record
    (`REQ-SEO-001` §2) for one `market x week` cell.

    `weighted_avg_position`/`visibility_index` are `None` together
    whenever the underlying total impressions are zero (undefined, never
    a fabricated 0 or 1). `total_impressions`/`total_clicks` remain real
    numbers (including a genuine 0.0) whenever the caller actually
    supplied source rows for the period - this repository's `core.
    coverage` vocabulary is reused only for the recognised exception
    (`STATE_OBSERVED_ZERO`, a confirmed zero-impression week); an
    ordinary, fully-observed, non-zero week carries `coverage_state=None`
    rather than being forced into `estimated`/`modelled` (which would
    misrepresent a raw GSC source fact as a latent/derived one - exactly
    what `REQ-COVERAGE-001` §2 warns against in the other direction)."""

    market: str
    week: str
    weighted_avg_position: Optional[float]
    visibility_index: Optional[float]
    total_impressions: Optional[float]
    total_clicks: Optional[float]
    ctr: Optional[float]
    coverage_state: Optional[str] = None
    methodology_version: str = "1.0.0"
    schema_version: int = SEO_VISIBILITY_SCHEMA_VERSION
    seo_group_id: str = "seo_visibility"
    seo_group_name: str = ""

    def __post_init__(self) -> None:
        if not self.market:
            raise ValueError("SeoPositionalVisibilityObservation requires a market.")
        if not self.week:
            raise ValueError("SeoPositionalVisibilityObservation requires a week.")
        if not self.seo_group_id:
            raise ValueError(
                "SeoPositionalVisibilityObservation requires seo_group_id."
            )
        if (
            self.coverage_state is not None
            and self.coverage_state not in COVERAGE_STATES
        ):
            raise ValueError(
                f"SeoPositionalVisibilityObservation: unknown coverage_state "
                f"'{self.coverage_state}' (expected one of {COVERAGE_STATES} or None)."
            )
        position_present = self.weighted_avg_position is not None
        visibility_present = self.visibility_index is not None
        if position_present != visibility_present:
            raise ValueError(
                "SeoPositionalVisibilityObservation: weighted_avg_position "
                "and visibility_index must be present or absent together."
            )
        if position_present:
            if self.weighted_avg_position < 1:  # type: ignore[operator]
                raise ValueError(
                    "SeoPositionalVisibilityObservation.weighted_avg_position "
                    "must be >= 1 (GSC position is 1-indexed)."
                )
            expected_visibility = 1.0 / cast(float, self.weighted_avg_position)
            if not math.isclose(
                cast(float, self.visibility_index), expected_visibility, rel_tol=1e-9
            ):
                raise ValueError(
                    "SeoPositionalVisibilityObservation: visibility_index "
                    "does not equal 1 / weighted_avg_position."
                )
        for field_name in ("total_impressions", "total_clicks"):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(
                    f"SeoPositionalVisibilityObservation.{field_name} must "
                    "be non-negative."
                )
        if self.ctr is not None:
            if not (0.0 <= self.ctr <= 1.0):
                raise ValueError(
                    "SeoPositionalVisibilityObservation.ctr must be in [0, 1]."
                )
            if self.total_clicks is not None and self.total_impressions:
                expected_ctr = self.total_clicks / self.total_impressions
                if not math.isclose(
                    self.ctr, expected_ctr, rel_tol=1e-9, abs_tol=1e-12
                ):
                    raise ValueError(
                        "SeoPositionalVisibilityObservation: ctr does not "
                        "equal total_clicks / total_impressions."
                    )
        if self.coverage_state == STATE_OBSERVED_ZERO:
            if self.total_impressions != 0:
                raise ValueError(
                    "SeoPositionalVisibilityObservation: coverage_state "
                    "'observed_zero' requires total_impressions == 0."
                )
            if position_present:
                raise ValueError(
                    "SeoPositionalVisibilityObservation: coverage_state "
                    "'observed_zero' requires weighted_avg_position/"
                    "visibility_index to be None (undefined at zero "
                    "impressions)."
                )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "SeoPositionalVisibilityObservation":
        known = set(cls.__dataclass_fields__)
        return cls(**cast(Any, {k: v for k, v in values.items() if k in known}))


def compute_weekly_positional_visibility(
    rows: Sequence[GscPositionRow],
    *,
    market: str,
    week: str,
    seo_group_id: str = "seo_visibility",
    seo_group_name: str = "",
) -> SeoPositionalVisibilityObservation:
    """Deterministically compute one `market x week` positional-visibility
    observation from raw GSC-shaped rows, per this module's approved
    formula (impression-weighted average position, then 1/position).

    `rows` must be the actual rows returned for this market/week - an
    empty sequence means "the source was queried and returned zero rows"
    (a genuine, confirmed zero-impression week), NOT "no data available
    for this week." A caller that has not queried the source for a given
    week at all must not call this function for that week; representing
    that absence is the caller's own responsibility via `core.coverage`'s
    `STATE_UNAVAILABLE_SOURCE`/`STATE_MISSING_EXPECTED` vocabulary
    directly - this function has no way to distinguish "not queried" from
    "queried, zero rows" from an empty list alone, and must not guess.
    """
    total_impressions = float(sum(row.impressions for row in rows))
    total_clicks = float(sum(row.clicks for row in rows))

    if total_impressions <= 0:
        return SeoPositionalVisibilityObservation(
            market=market,
            week=week,
            weighted_avg_position=None,
            visibility_index=None,
            total_impressions=total_impressions,
            total_clicks=total_clicks,
            ctr=None,
            coverage_state=STATE_OBSERVED_ZERO,
            seo_group_id=seo_group_id,
            seo_group_name=seo_group_name,
        )

    weighted_avg_position = (
        sum(row.position * row.impressions for row in rows) / total_impressions
    )
    visibility_index = 1.0 / weighted_avg_position
    ctr = total_clicks / total_impressions

    return SeoPositionalVisibilityObservation(
        market=market,
        week=week,
        weighted_avg_position=weighted_avg_position,
        visibility_index=visibility_index,
        total_impressions=total_impressions,
        total_clicks=total_clicks,
        ctr=ctr,
        coverage_state=None,
        seo_group_id=seo_group_id,
        seo_group_name=seo_group_name,
    )


def compute_weekly_positional_visibility_series(
    rows_by_market_week: Mapping[Tuple[str, str], Sequence[GscPositionRow]],
    *,
    seo_group_id: str = "seo_visibility",
    seo_group_name: str = "",
) -> List[SeoPositionalVisibilityObservation]:
    """Convenience wrapper applying `compute_weekly_positional_visibility`
    over every supplied `(market, week)` cell, in a stable, deterministic
    order. Cells with no entry in `rows_by_market_week` at all are simply
    absent from the result - this function never invents a cell that
    wasn't given to it."""
    return [
        compute_weekly_positional_visibility(
            rows,
            market=market,
            week=week,
            seo_group_id=seo_group_id,
            seo_group_name=seo_group_name,
        )
        for (market, week) in sorted(rows_by_market_week)
        for rows in [rows_by_market_week[(market, week)]]
    ]


@dataclass(frozen=True)
class SeoModelFitInputs:
    """Row-aligned SEO visibility treatment for a fitted MMM.

    The full MMM history remains present in ``model_weeks``.  ``active_mask``
    identifies the observed SEO window, while inactive rows contain only a
    computational zero in ``standardized_visibility`` and are never treated
    as an observed zero.  This is the W2-B gated-regressor implementation of
    Decision 3: the outcome likelihood still uses every model week, but SEO's
    contribution is structurally inactive outside its valid source window.
    """

    metric_definition: SeoVisibilityMetricDefinition
    model_markets: Tuple[str, ...]
    model_weeks: Tuple[str, ...]
    standardized_visibility: Tuple[float, ...]
    active_mask: Tuple[float, ...]
    raw_visibility: Tuple[Optional[float], ...]
    window_by_market: Mapping[str, SeoValidEstimationWindow]
    standardization_center: float
    standardization_scale: float
    pathway_id: str = "seo_visibility_to_organic_outcome_v1"
    schema_version: int = SEO_VISIBILITY_SCHEMA_VERSION
    seo_group_id: str = "seo_visibility"
    seo_group_name: str = ""

    def __post_init__(self) -> None:
        n = len(self.model_weeks)
        if len(self.standardized_visibility) != n or len(self.active_mask) != n:
            raise ValueError(
                "SeoModelFitInputs arrays must have one value per model week."
            )
        if len(self.raw_visibility) != n:
            raise ValueError(
                "SeoModelFitInputs.raw_visibility must be row-aligned to model weeks."
            )
        if not self.seo_group_id:
            raise ValueError("SeoModelFitInputs requires seo_group_id.")
        if (
            not np.isfinite(self.standardization_center)
            or not np.isfinite(self.standardization_scale)
            or self.standardization_scale <= 0
        ):
            raise ValueError(
                "SEO standardization metadata must be finite and positive."
            )
        if self.metric_definition.approval_status != "approved":
            raise ValueError("SEO model inputs require an approved metric definition.")
        if (
            self.metric_definition.causal_role
            != CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE
        ):
            raise ValueError(
                "SEO model inputs require the approved mediator/capture-efficiency role."
            )
        if any(value not in (0.0, 1.0) for value in self.active_mask):
            raise ValueError("SEO active_mask must contain only 0.0 or 1.0 values.")

    @classmethod
    def from_observations(
        cls,
        observations: Sequence[SeoPositionalVisibilityObservation],
        *,
        model_markets: Sequence[str],
        model_weeks: Sequence[str],
        metric_definition: SeoVisibilityMetricDefinition = SEO_POSITIONAL_VISIBILITY_METRIC,
        seo_group_id: Optional[str] = None,
        seo_group_name: str = "",
    ) -> "SeoModelFitInputs":
        if not model_markets or not model_weeks:
            raise ValueError("SEO model inputs require non-empty markets and weeks.")
        if len(model_markets) != len(model_weeks):
            raise ValueError("SEO model markets and weeks must be row-aligned.")
        keys = list(
            zip(
                (str(market) for market in model_markets),
                (str(week) for week in model_weeks),
            )
        )
        by_key: dict[tuple[str, str], SeoPositionalVisibilityObservation] = {}
        observed_group_ids = set()
        observed_group_names = set()
        for source_observation in observations:
            key = (source_observation.market, source_observation.week)
            if key in by_key:
                raise ValueError(f"Duplicate SEO observation for {key}.")
            by_key[key] = source_observation
            observed_group_ids.add(source_observation.seo_group_id)
            if source_observation.seo_group_name:
                observed_group_names.add(source_observation.seo_group_name)
        if len(observed_group_ids) > 1:
            raise ValueError("SeoModelFitInputs cannot mix SEO groups.")
        resolved_group_id = seo_group_id or next(
            iter(observed_group_ids), "seo_visibility"
        )
        if observed_group_ids and resolved_group_id not in observed_group_ids:
            raise ValueError(
                "SEO observations do not match the requested seo_group_id."
            )
        resolved_group_name = seo_group_name or next(iter(observed_group_names), "")

        values: list[Optional[float]] = []
        active: list[float] = []
        for key in keys:
            observation = by_key.get(key)
            value = (
                float(observation.visibility_index)
                if observation is not None
                and observation.visibility_index is not None
                and observation.coverage_state != STATE_OBSERVED_ZERO
                else None
            )
            values.append(value)
            active.append(1.0 if value is not None else 0.0)
        observed_values = np.asarray(
            [value for value in values if value is not None], dtype=float
        )
        if observed_values.size == 0:
            raise ValueError(
                "SEO fitting requires at least one observed positive-impression "
                "visibility value; missing weeks cannot be imputed."
            )
        center = float(np.mean(observed_values))
        scale = float(np.std(observed_values))
        if not np.isfinite(scale) or scale <= 0:
            scale = 1.0
        standardized = tuple(
            float((value - center) / scale) if value is not None else 0.0
            for value in values
        )
        windows = {}
        for market in sorted(set(str(value) for value in model_markets)):
            coverage = [
                (week, by_key[(str(market), str(week))].coverage_state)
                for week in model_weeks
                if (str(market), str(week)) in by_key
            ]
            windows[str(market)] = determine_valid_estimation_window(
                str(market), coverage
            )
        return cls(
            metric_definition=metric_definition,
            model_markets=tuple(str(market) for market in model_markets),
            model_weeks=tuple(str(week) for week in model_weeks),
            standardized_visibility=standardized,
            active_mask=tuple(active),
            raw_visibility=tuple(values),
            window_by_market=windows,
            standardization_center=center,
            standardization_scale=scale,
            seo_group_id=resolved_group_id,
            seo_group_name=resolved_group_name,
        )

    def validate_frame(self, *, markets: Sequence[str], weeks: Sequence[str]) -> None:
        if tuple(str(market) for market in markets) != self.model_markets:
            raise ValueError("SEO inputs do not match the fitted model markets.")
        if tuple(str(week) for week in weeks) != self.model_weeks:
            raise ValueError(
                "SEO inputs do not cover the fitted model weeks in exact row order."
            )

    def to_dict(self) -> dict:
        return {
            "metric_definition": self.metric_definition.to_dict(),
            "model_markets": list(self.model_markets),
            "model_weeks": list(self.model_weeks),
            "standardized_visibility": list(self.standardized_visibility),
            "active_mask": list(self.active_mask),
            "raw_visibility": list(self.raw_visibility),
            "window_by_market": {
                market: window.to_dict()
                for market, window in sorted(self.window_by_market.items())
            },
            "standardization_center": self.standardization_center,
            "standardization_scale": self.standardization_scale,
            "pathway_id": self.pathway_id,
            "schema_version": self.schema_version,
            "seo_group_id": self.seo_group_id,
            "seo_group_name": self.seo_group_name,
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SeoModelFitInputs":
        payload = dict(values)
        payload["metric_definition"] = SeoVisibilityMetricDefinition.from_dict(
            payload["metric_definition"]
        )
        payload["model_markets"] = tuple(payload.get("model_markets") or ())
        payload["model_weeks"] = tuple(payload.get("model_weeks") or ())
        payload["standardized_visibility"] = tuple(
            float(value) for value in payload.get("standardized_visibility") or ()
        )
        payload["active_mask"] = tuple(
            float(value) for value in payload.get("active_mask") or ()
        )
        payload["raw_visibility"] = tuple(payload.get("raw_visibility") or ())
        payload["window_by_market"] = {
            market: SeoValidEstimationWindow.from_dict(window)
            for market, window in (payload.get("window_by_market") or {}).items()
        }
        known = set(cls.__dataclass_fields__)
        return cls(
            **cast(Any, {key: value for key, value in payload.items() if key in known})
        )


@dataclass(frozen=True)
class SeoModelFitInputsCollection:
    """Explicitly selected set of independently modelled SEO groups."""

    groups: Tuple[SeoModelFitInputs, ...]
    schema_version: int = SEO_VISIBILITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.groups:
            raise ValueError("SeoModelFitInputsCollection requires at least one group.")
        ids = [group.seo_group_id for group in self.groups]
        if len(set(ids)) != len(ids):
            raise ValueError("SEO model groups must have unique seo_group_id values.")
        object.__setattr__(
            self,
            "groups",
            tuple(sorted(self.groups, key=lambda item: item.seo_group_id)),
        )

    @classmethod
    def from_groups(
        cls, groups: Sequence[SeoModelFitInputs]
    ) -> "SeoModelFitInputsCollection":
        return cls(tuple(groups))

    def validate_frame(self, *, markets: Sequence[str], weeks: Sequence[str]) -> None:
        for group in self.groups:
            group.validate_frame(markets=markets, weeks=weeks)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "groups": [group.to_dict() for group in self.groups],
        }

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SeoModelFitInputsCollection":
        if "groups" not in values:
            # Accept both the legacy singular payload and an explicit
            # group-id -> payload mapping used by early onboarding exports.
            if "metric_definition" in values:
                return cls((SeoModelFitInputs.from_dict(values),))
            return cls(
                tuple(
                    SeoModelFitInputs.from_dict(
                        dict(
                            payload, seo_group_id=payload.get("seo_group_id", group_id)
                        )
                    )
                    for group_id, payload in values.items()
                    if isinstance(payload, Mapping)
                )
            )
        return cls(
            tuple(
                SeoModelFitInputs.from_dict(item) for item in values.get("groups") or ()
            )
        )


def normalise_seo_fit_inputs(
    value: Optional[
        SeoModelFitInputs | SeoModelFitInputsCollection | Mapping[str, Any]
    ],
) -> Tuple[SeoModelFitInputs, ...]:
    """Return the selected SEO groups, retaining legacy singular payloads."""
    if value is None:
        return ()
    if isinstance(value, SeoModelFitInputsCollection):
        return value.groups
    if isinstance(value, SeoModelFitInputs):
        return (value,)
    if isinstance(value, Mapping):
        return SeoModelFitInputsCollection.from_dict(value).groups
    raise TypeError("Unsupported SEO fit-input payload.")


def seo_fit_inputs_to_dict(
    value: Optional[SeoModelFitInputs | SeoModelFitInputsCollection],
) -> dict:
    groups = normalise_seo_fit_inputs(value)
    if not groups:
        return {}
    if len(groups) == 1:
        return groups[0].to_dict()
    return SeoModelFitInputsCollection.from_groups(groups).to_dict()


def seo_fit_inputs_fingerprint(
    value: Optional[SeoModelFitInputs | SeoModelFitInputsCollection],
) -> str:
    payload = seo_fit_inputs_to_dict(value)
    if not payload:
        return ""
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


__all__ = [
    "CAUSAL_ROLE_MEDIATOR_OR_CAPTURE_EFFICIENCY_STATE",
    "SEO_GROUP_BRAND",
    "SEO_GROUP_NON_BRAND",
    "SEO_GROUPS",
    "GscPositionRow",
    "SEO_POSITIONAL_VISIBILITY_METRIC",
    "SeoModelFitInputs",
    "SeoModelFitInputsCollection",
    "SeoPositionalVisibilityObservation",
    "SeoVisibilityMetricDefinition",
    "compute_weekly_positional_visibility",
    "compute_weekly_positional_visibility_series",
    "normalise_seo_fit_inputs",
    "seo_fit_inputs_fingerprint",
    "seo_fit_inputs_to_dict",
]
