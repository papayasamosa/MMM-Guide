"""Characterisation tests for the application official-preparation boundary."""

from __future__ import annotations

from ancestry_mmm.application.official_preparation_service import (
    describe_official_preparation,
    review_official_preparation,
)
from ancestry_mmm.core.coverage import (
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.frequency_alignment import OfficialPreparationResult
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, OutcomeDefinition
from ancestry_mmm.core.schema import ModelSpec


def _spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend"],
        segment_outcomes={"New": "gsa"},
    )


def _outcome() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id="fh_new_gsa",
        product=FAMILY_HISTORY,
        segment="New",
        metric=METRIC_GSA,
        source_column="gsa",
    )


def _matrix(*variable_ids: str) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="coverage-service",
        matrix_version=1,
        generated_at="2026-08-15",
        records=tuple(
            VariableCoverageRecord(
                variable_id=variable_id,
                source_id=f"source-{variable_id}",
                source_version=1,
                market="UK",
                frequency=FrequencyMetadata(
                    native_frequency="weekly",
                    target_frequency="weekly",
                    variable_class="flow_count",
                ),
                coverage_segments=(),
            )
            for variable_id in variable_ids
        ),
    )


def test_review_service_preserves_consumed_scope_and_explicit_calendar():
    review = review_official_preparation(
        _spec(),
        [_outcome()],
        _matrix("gsa", "tv_spend", "unused"),
        canonical_calendar={
            "start": "2024-01-01",
            "end": "2024-01-15",
            "frequency": "weekly",
        },
    )

    assert review.consumed_variable_ids == ("gsa", "tv_spend")
    assert "unused" not in review.alignment_specs
    assert review.preparation.ready
    assert review.preparation.canonical_calendar is not None
    assert review.preparation.canonical_calendar.start == "2024-01-01"
    assert review.capability_report.to_dict()["coverage_matrix_fingerprint"]


def test_review_service_does_not_infer_missing_calendar():
    review = review_official_preparation(
        _spec(), [_outcome()], _matrix("gsa", "tv_spend")
    )

    assert review.preparation.status == "decision_required"
    assert not review.preparation.ready


def test_status_copy_is_stable_and_framework_independent():
    ready = describe_official_preparation(
        OfficialPreparationResult(status="ready", reason="ready for review")
    )
    blocked = describe_official_preparation(
        OfficialPreparationResult(
            status="unsupported_parameters", reason="invalid parameters"
        )
    )

    assert (ready.label, ready.badge, ready.reason) == (
        "Official preparation ready",
        "ready",
        "ready for review",
    )
    assert blocked.badge == "blocked"
    assert "missing or unsupported parameters" in blocked.reason
