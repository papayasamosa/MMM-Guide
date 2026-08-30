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
from dataclasses import asdict, dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple, cast

from .coverage import COVERAGE_STATES, STATE_OBSERVED_ZERO

SEO_VISIBILITY_SCHEMA_VERSION = 1

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

    def __post_init__(self) -> None:
        if not self.market:
            raise ValueError("SeoPositionalVisibilityObservation requires a market.")
        if not self.week:
            raise ValueError("SeoPositionalVisibilityObservation requires a week.")
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
    )


def compute_weekly_positional_visibility_series(
    rows_by_market_week: Mapping[Tuple[str, str], Sequence[GscPositionRow]],
) -> List[SeoPositionalVisibilityObservation]:
    """Convenience wrapper applying `compute_weekly_positional_visibility`
    over every supplied `(market, week)` cell, in a stable, deterministic
    order. Cells with no entry in `rows_by_market_week` at all are simply
    absent from the result - this function never invents a cell that
    wasn't given to it."""
    return [
        compute_weekly_positional_visibility(rows, market=market, week=week)
        for (market, week) in sorted(rows_by_market_week)
        for rows in [rows_by_market_week[(market, week)]]
    ]
