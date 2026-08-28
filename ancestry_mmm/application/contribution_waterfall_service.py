"""Contribution waterfall service - orchestrates the WP2F period-over-
period contribution waterfall (`docs/wp2f_contribution_waterfall_
design_note.md`) without Streamlit dependencies.

Composes, in this exact order: `core.outcome_valuation_periods.
resolve_weeks_for_grain` (resolve which already-fitted weeks each
period covers - the identical grain-dispatch `OutcomeValuationReporting
Service` uses, one lookup path), `core.outcome_valuation_reporting.
available_weeks_for_market` (the same week-universe lookup WP2D-ui/WP2E
use), and `core.contribution_waterfall.compute_contribution_waterfall_
bridge` (the generalised Shapley bridge itself). Fails closed - returns
`errors`, never a fabricated result - whenever either period resolves
to no weeks, an unknown market/outcome_id is requested, or the fitted
model's trace is missing a required Deterministic (`core.contribution_
waterfall.MissingGeneralisedEtaComponentError`) or is a Candidate A fit
(`core.attribution.CandidateAAttributionNotSupportedError`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from ancestry_mmm.core.attribution import CandidateAAttributionNotSupportedError
from ancestry_mmm.core.contribution_waterfall import (
    ContributionWaterfallBridge,
    MissingGeneralisedEtaComponentError,
    compute_contribution_waterfall_bridge,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.outcome_valuation_periods import resolve_weeks_for_grain
from ancestry_mmm.core.outcome_valuation_reporting import (
    DEFAULT_REPORTING_N_PERMUTATIONS,
    OutcomeValuationReportingCoverageError,
    available_weeks_for_market,
)
from ancestry_mmm.core.uncertainty import DEFAULT_CRED_MASS, DEFAULT_N_DRAWS


@dataclass
class ContributionWaterfallPeriodRequest:
    """One period's grain/label selection - the "when" half of a
    waterfall request. Reused, unchanged in shape, for both Period A
    and Period B."""

    grain: str
    period_label: Optional[str] = None
    custom_range_start: Optional[str] = None
    custom_range_end: Optional[str] = None


@dataclass
class ContributionWaterfallRequest:
    """Typed input for one contribution waterfall. Identity fields
    (`market`, `outcome_ids`) are explicit - never inferred from
    `meta`."""

    market: str
    trace: Any
    frame: Dict
    meta: FHModelMeta
    outcome_ids: Sequence[str]
    period_a: ContributionWaterfallPeriodRequest
    period_b: ContributionWaterfallPeriodRequest
    n_draws: int = DEFAULT_N_DRAWS
    n_permutations: int = DEFAULT_REPORTING_N_PERMUTATIONS
    seed: int = 42
    credible_mass: float = DEFAULT_CRED_MASS


@dataclass
class ContributionWaterfallResult:
    """Structured contribution-waterfall output."""

    bridge: Optional[ContributionWaterfallBridge] = None
    resolved_period_a_weeks: List[str] = field(default_factory=list)
    resolved_period_b_weeks: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class ContributionWaterfallService:
    """Application service for the WP2F contribution waterfall.

    Does not access Streamlit session state, mutate global state, or
    render any UI.
    """

    def compute(
        self, request: ContributionWaterfallRequest
    ) -> ContributionWaterfallResult:
        errors: List[str] = []
        if request.trace is None:
            errors.append("No fitted model trace provided.")
        if request.frame is None:
            errors.append("No model frame provided.")
        if request.meta is None:
            errors.append("No model metadata provided.")
        if not request.market:
            errors.append("No market provided.")
        if not request.outcome_ids:
            errors.append("No outcome_ids provided.")
        if errors:
            return ContributionWaterfallResult(errors=errors)

        try:
            available_weeks = available_weeks_for_market(
                request.frame, request.meta, request.market
            )
            resolved_a = resolve_weeks_for_grain(
                available_weeks,
                request.period_a.grain,
                period_label=request.period_a.period_label,
                custom_range_start=request.period_a.custom_range_start,
                custom_range_end=request.period_a.custom_range_end,
            )
            resolved_b = resolve_weeks_for_grain(
                available_weeks,
                request.period_b.grain,
                period_label=request.period_b.period_label,
                custom_range_start=request.period_b.custom_range_start,
                custom_range_end=request.period_b.custom_range_end,
            )
            if not resolved_a or not resolved_b:
                missing_sides = []
                if not resolved_a:
                    missing_sides.append("Period A")
                if not resolved_b:
                    missing_sides.append("Period B")
                return ContributionWaterfallResult(
                    resolved_period_a_weeks=resolved_a,
                    resolved_period_b_weeks=resolved_b,
                    errors=[
                        f"No weeks are available for {' and '.join(missing_sides)} "
                        f"in market '{request.market}' - not covered by the "
                        "fitted model."
                    ],
                )

            bridge = compute_contribution_waterfall_bridge(
                request.trace,
                request.frame,
                request.meta,
                market=request.market,
                outcome_ids=request.outcome_ids,
                period_a_weeks=resolved_a,
                period_b_weeks=resolved_b,
                n_draws=request.n_draws,
                n_permutations=request.n_permutations,
                seed=request.seed,
                credible_mass=request.credible_mass,
            )
        except (
            OutcomeValuationReportingCoverageError,
            MissingGeneralisedEtaComponentError,
            CandidateAAttributionNotSupportedError,
            ValueError,
        ) as exc:
            errors.append(f"Contribution waterfall failed: {exc}")
            return ContributionWaterfallResult(errors=errors)

        return ContributionWaterfallResult(
            bridge=bridge,
            resolved_period_a_weeks=resolved_a,
            resolved_period_b_weeks=resolved_b,
            errors=[],
        )
