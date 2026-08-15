"""Application boundary for the official-preparation review.

The Model Setup page owns presentation and session state.  This module owns the
pure orchestration that combines the compiled proposal, governed coverage, and
the explicit project calendar into the two persisted readiness records.  It
keeps that boundary callable from tests and future non-Streamlit entry points
without changing the core preparation contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.coverage import VariableCoverageMatrix
from ancestry_mmm.core.frequency_alignment import (
    AlignmentSpecification,
    OfficialPreparationResult,
    alignment_specs_from_coverage_matrix,
    assess_official_preparation,
)
from ancestry_mmm.core.official_preparation import (
    OfficialCapabilityReport,
    build_official_capability_report,
)
from ancestry_mmm.core.outcomes import OutcomeDefinition
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_objects import SearchObjectDefinition


@dataclass(frozen=True)
class OfficialPreparationReview:
    """Pure review output consumed by a UI or another application adapter."""

    capability_report: OfficialCapabilityReport
    preparation: OfficialPreparationResult
    alignment_specs: Mapping[str, tuple[AlignmentSpecification, ...]]

    @property
    def consumed_variable_ids(self) -> tuple[str, ...]:
        return tuple(
            item.variable_id for item in self.capability_report.consumed_variables
        )


def review_official_preparation(
    spec: ModelSpec,
    outcomes: Sequence[OutcomeDefinition | Mapping[str, Any]],
    coverage_matrix: Optional[VariableCoverageMatrix],
    *,
    canonical_calendar: Optional[Mapping[str, Any]] = None,
    activity_definitions: Sequence[ActivityDefinition | Mapping[str, Any]] = (),
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
    pipeline_steps: Sequence[Mapping[str, Any]] = (),
) -> OfficialPreparationReview:
    """Build the capability, readiness, and explicit alignment review.

    ``canonical_calendar`` is a governed input.  This function deliberately
    does not infer dates or frequency from source data.
    """

    capability_report = build_official_capability_report(
        spec,
        outcomes,
        coverage_matrix,
        activity_definitions=activity_definitions,
        search_objects=search_objects,
        pipeline_steps=pipeline_steps,
    )
    calendar = canonical_calendar or {}
    preparation = assess_official_preparation(
        coverage_matrix,
        governed_start=calendar.get("start"),
        governed_end=calendar.get("end"),
        governed_frequency=calendar.get("frequency"),
        as_of=calendar.get("as_of"),
        consumed_variable_ids=tuple(
            item.variable_id for item in capability_report.consumed_variables
        ),
        capability_evidence=capability_report.to_dict(),
    )
    alignment_specs = (
        alignment_specs_from_coverage_matrix(
            coverage_matrix,
            target_frequency=calendar.get("frequency"),
            consumed_variable_ids=tuple(
                item.variable_id for item in capability_report.consumed_variables
            ),
        )
        if coverage_matrix is not None
        else {}
    )
    return OfficialPreparationReview(
        capability_report=capability_report,
        preparation=preparation,
        alignment_specs=alignment_specs,
    )


@dataclass(frozen=True)
class OfficialPreparationStatus:
    """Stable presentation copy for an official-preparation result."""

    label: str
    badge: str
    reason: str


def describe_official_preparation(
    result: OfficialPreparationResult,
) -> OfficialPreparationStatus:
    """Return the user-facing status copy without importing Streamlit."""

    if result.ready:
        return OfficialPreparationStatus(
            label="Official preparation ready",
            badge="ready",
            reason=result.reason,
        )
    reasons = {
        "unsupported_no_approved_method": (
            "Official preparation unavailable",
            "No approved method currently exists for converting one or more source "
            "frequencies for official modelling.",
        ),
        "method_available": (
            "Official preparation blocked",
            "An approved frequency method is available, but the governed conversion "
            "executor has not been validated for official modelling yet.",
        ),
        "unsupported_definition_break": (
            "Official preparation blocked",
            "The reviewed frequency definition changes across the available source "
            "support, so official preparation needs an explicit resolution.",
        ),
        "unsupported_leakage": (
            "Official preparation blocked",
            "The reviewed frequency treatment would use information outside the "
            "approved preparation boundary. Resolve the frequency decision before "
            "official modelling.",
        ),
        "unsupported_parameters": (
            "Official preparation blocked",
            "The selected frequency method has missing or unsupported parameters. "
            "Review the explicit method configuration on Data Coverage.",
        ),
    }
    label, reason = reasons.get(
        result.status,
        (
            "Official preparation blocked",
            "Required coverage, calendar, or frequency decisions are still needed "
            "before official modelling can be prepared.",
        ),
    )
    return OfficialPreparationStatus(label=label, badge="blocked", reason=reason)
