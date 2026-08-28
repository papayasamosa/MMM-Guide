"""Outcome valuation reporting service - orchestrates historical Results
economic reporting (WP2D-ui: REQ-ECON-002 through REQ-ECON-004) without
Streamlit dependencies.

Composes, in this exact order: `core.outcome_valuation_periods` (resolve
which already-fitted weeks a requested reporting period covers),
`core.outcome_valuation_reporting` (per-draw posterior incremental
outcome and attributable spend for those weeks), `core.
outcome_valuation_rates.derive_weekly_value_rates` (fixed weekly
value-per-outcome rates from the governed valuation catalogue), and
`core.outcome_valuation_attribution.summarize_posterior_economic_
attribution` (the draw-level value join, aggregation, and posterior
summary). This is the exact sequence REQ-ECON-003 requires - the join
happens at draw level, at the weekly grain, strictly before any
temporal aggregation, never a shortcut that multiplies a pre-summed
total by an average rate.

This service is deliberately agnostic to the Total/Product/Segment/
Funnel/Channel reporting-dimension vocabulary the Results page presents
- it only ever takes an explicit `outcome_ids`/`segment`/`channel`
selection and reports on exactly that slice. Resolving which dimension
choices are genuinely eligible (and disclosing the ones that are not) is
the page's job; this service does not know or care which UI dimension a
given `(outcome_ids, segment, channel)` combination came from.

Fails closed - returns `errors`, never a fabricated result - whenever
the requested period resolves to no weeks, or any resolved week has no
governed valuation-rate coverage. Never silently drops a week, never
substitutes a nearby rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_valuation import WeeklyOutcomeValuationRecord
from ancestry_mmm.core.outcome_valuation_attribution import (
    PosteriorEconomicAttribution,
    summarize_posterior_economic_attribution,
)
from ancestry_mmm.core.outcome_valuation_periods import (
    PERIOD_GRAIN_CUSTOM,
    PERIOD_GRAIN_MONTH,
    PERIOD_GRAIN_QUARTER,
    PERIOD_GRAIN_WEEK,
    PERIOD_GRAIN_YEAR,
    resolve_weeks_for_calendar_period,
    resolve_weeks_for_custom_range,
)
from ancestry_mmm.core.outcome_valuation_rates import derive_weekly_value_rates
from ancestry_mmm.core.outcome_valuation_reporting import (
    DEFAULT_REPORTING_N_PERMUTATIONS,
    attributable_spend,
    available_weeks_for_market,
    extract_incremental_outcome_draws,
    observed_denominator_counts_frame,
)
from ancestry_mmm.core.uncertainty import DEFAULT_CRED_MASS, DEFAULT_N_DRAWS

_CALENDAR_GRAINS = {PERIOD_GRAIN_MONTH, PERIOD_GRAIN_QUARTER, PERIOD_GRAIN_YEAR}


@dataclass
class HistoricalOutcomeValuationRequest:
    """Typed input for one historical outcome-valuation report. Identity
    fields (`market`, `valuation_kind`, `segment`, `outcome_ids`) are
    explicit - never inferred from `meta`."""

    market: str
    grain: str
    trace: Any
    frame: Dict
    meta: FHModelMeta
    outcome_ids: Sequence[str]
    segment: str
    valuation_kind: str
    weekly_valuation_records: Sequence[WeeklyOutcomeValuationRecord]
    channel: Optional[str] = None
    period_label: Optional[str] = None
    custom_range_start: Optional[str] = None
    custom_range_end: Optional[str] = None
    n_draws: int = DEFAULT_N_DRAWS
    n_permutations: int = DEFAULT_REPORTING_N_PERMUTATIONS
    seed: int = 42
    credible_mass: float = DEFAULT_CRED_MASS


@dataclass
class HistoricalOutcomeValuationResult:
    """Structured historical outcome-valuation reporting output."""

    attribution: Optional[PosteriorEconomicAttribution] = None
    resolved_weeks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class OutcomeValuationReportingService:
    """Application service for historical Results economic reporting.

    Does not access Streamlit session state, mutate global state, or
    render any UI.
    """

    def evaluate_period(
        self, request: HistoricalOutcomeValuationRequest
    ) -> HistoricalOutcomeValuationResult:
        errors: List[str] = []

        if request.trace is None:
            errors.append("No fitted model trace provided.")
        if request.frame is None:
            errors.append("No model frame provided.")
        if request.meta is None:
            errors.append("No model metadata provided.")
        if not request.market:
            errors.append("No market provided.")
        if not request.valuation_kind:
            errors.append("No valuation_kind provided.")
        if not request.segment:
            errors.append("No segment provided.")
        if not request.outcome_ids:
            errors.append("No outcome_ids provided.")
        if errors:
            return HistoricalOutcomeValuationResult(errors=errors)

        try:
            available_weeks = available_weeks_for_market(
                request.frame, request.meta, request.market
            )
            resolved_weeks = self._resolve_weeks(request, available_weeks)
            if not resolved_weeks:
                return HistoricalOutcomeValuationResult(
                    errors=[
                        f"No weeks are available for the selected period in "
                        f"market '{request.market}' - this period is not "
                        "covered by the fitted model."
                    ]
                )

            resolved_week_set = set(resolved_weeks)
            filtered_records = [
                record
                for record in request.weekly_valuation_records
                if record.valuation_kind == request.valuation_kind
                and record.market == request.market
                and record.segment == request.segment
                and record.week in resolved_week_set
            ]
            observed_counts = observed_denominator_counts_frame(
                request.frame, request.meta, request.outcome_ids
            )
            rates, issues = derive_weekly_value_rates(filtered_records, observed_counts)
            rate_by_week = {rate.week: rate for rate in rates}
            missing_weeks = [w for w in resolved_weeks if w not in rate_by_week]
            if missing_weeks:
                return HistoricalOutcomeValuationResult(
                    resolved_weeks=resolved_weeks,
                    errors=[
                        "Missing governed valuation coverage for week(s) "
                        f"{', '.join(missing_weeks)} (market="
                        f"'{request.market}', segment='{request.segment}', "
                        f"valuation_kind='{request.valuation_kind}') - "
                        "cannot report this period without fabricating a "
                        "rate."
                    ]
                    + issues,
                )

            ordered_rates = [rate_by_week[week] for week in resolved_weeks]

            incremental_outcome_draws = extract_incremental_outcome_draws(
                request.trace,
                request.frame,
                request.meta,
                market=request.market,
                weeks=resolved_weeks,
                outcome_ids=request.outcome_ids,
                channel=request.channel,
                n_draws=request.n_draws,
                n_permutations=request.n_permutations,
                seed=request.seed,
            )
            spend = attributable_spend(
                request.frame,
                request.meta,
                market=request.market,
                weeks=resolved_weeks,
                channel=request.channel,
            )
            attribution = summarize_posterior_economic_attribution(
                incremental_outcome_draws,
                ordered_rates,
                spend=spend,
                credible_mass=request.credible_mass,
            )
        except Exception as exc:
            errors.append(f"Historical outcome valuation reporting failed: {exc}")
            return HistoricalOutcomeValuationResult(errors=errors)

        return HistoricalOutcomeValuationResult(
            attribution=attribution,
            resolved_weeks=resolved_weeks,
            errors=[],
            warnings=list(issues),
        )

    @staticmethod
    def _resolve_weeks(
        request: HistoricalOutcomeValuationRequest, available_weeks: List[str]
    ) -> List[str]:
        if request.grain == PERIOD_GRAIN_WEEK:
            if not request.period_label:
                raise ValueError("A week grain request requires period_label.")
            return (
                [request.period_label]
                if request.period_label in available_weeks
                else []
            )
        if request.grain == PERIOD_GRAIN_CUSTOM:
            if not request.custom_range_start or not request.custom_range_end:
                raise ValueError(
                    "A custom grain request requires custom_range_start and "
                    "custom_range_end."
                )
            return resolve_weeks_for_custom_range(
                available_weeks,
                request.custom_range_start,
                request.custom_range_end,
            )
        if request.grain in _CALENDAR_GRAINS:
            if not request.period_label:
                raise ValueError(
                    f"A '{request.grain}' grain request requires period_label."
                )
            return resolve_weeks_for_calendar_period(
                available_weeks, request.grain, request.period_label
            )
        raise ValueError(f"Unsupported reporting grain: '{request.grain}'.")
