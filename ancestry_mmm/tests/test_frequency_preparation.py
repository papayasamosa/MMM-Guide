"""WP6 official-preparation boundary tests.

The expected behaviour is governed by REQ-COVERAGE-001 S1/S4/S5 and the
decision-required record in docs/decision_required_frequency_methods.md.
"""

from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    STATE_UNKNOWN,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.frequency_alignment import (
    FREQUENCY_METHOD_DECISIONS_REQUIRED,
    assess_official_preparation,
)


def _matrix(*records: VariableCoverageRecord) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="matrix-1",
        matrix_version=1,
        generated_at="2026-08-13",
        records=records,
    )


def _record(
    *,
    variable_id: str = "tv",
    native_frequency: str = "weekly",
    target_frequency: str = "weekly",
    variable_class: str = "flow_count",
    coverage_segments: tuple[CoverageSegment, ...] = (),
) -> VariableCoverageRecord:
    return VariableCoverageRecord(
        variable_id=variable_id,
        source_id="source-1",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency=native_frequency,
            target_frequency=target_frequency,
            variable_class=variable_class,
        ),
        coverage_segments=coverage_segments,
    )


def _calendar():
    return {
        "governed_start": "2024-01-01",
        "governed_end": "2024-03-31",
        "governed_frequency": "weekly",
    }


def test_no_matrix_fails_closed_with_actionable_decision_required_state():
    result = assess_official_preparation(None)

    assert result.status == "decision_required"
    assert not result.ready
    assert result.native_data_preserved
    assert any("coverage matrix" in item for item in result.decisions_required)
    assert any("project calendar" in item for item in result.decisions_required)


def test_same_frequency_data_can_be_officially_prepared_without_conversion():
    result = assess_official_preparation(_matrix(_record()), **_calendar())

    assert result.status == "ready"
    assert result.ready
    assert result.alignment_results == ()
    assert "No frequency conversion is performed" in result.reason


def test_mixed_frequency_is_explicitly_unsupported_until_a_method_is_approved():
    result = assess_official_preparation(
        _matrix(
            _record(
                variable_id="cpi",
                native_frequency="monthly",
                target_frequency="weekly",
                variable_class="rate_index",
            )
        ),
        **_calendar(),
    )

    assert result.status == "unsupported_no_approved_method"
    assert not result.ready
    assert result.conversion_variable_classes == ("rate_index",)
    assert len(result.alignment_results) == 1
    assert result.alignment_results[0].status == "unsupported_no_approved_method"
    assert result.native_data_preserved
    assert any("rate/index" in item for item in result.decisions_required)


def test_unresolved_coverage_blocks_before_any_frequency_conversion():
    result = assess_official_preparation(
        _matrix(
            _record(
                variable_id="cpi",
                native_frequency="monthly",
                target_frequency="weekly",
                coverage_segments=(
                    CoverageSegment(
                        period_start="2024-01-01",
                        period_end="2024-01-31",
                        state=STATE_UNKNOWN,
                    ),
                ),
            )
        ),
        **_calendar(),
    )

    assert result.status == "decision_required"
    assert result.alignment_results == ()
    assert "unresolved coverage" in result.reason


def test_every_variable_class_has_explicit_method_decisions():
    assert set(FREQUENCY_METHOD_DECISIONS_REQUIRED) == {
        "flow_count",
        "stock_level",
        "rate_index",
        "survey_measurement",
        "event_flag",
    }
    assert all(FREQUENCY_METHOD_DECISIONS_REQUIRED.values())


def test_result_is_json_safe_and_reports_native_data_preservation():
    result = assess_official_preparation(
        _matrix(
            _record(
                variable_id="brand_health",
                native_frequency="monthly",
                target_frequency="weekly",
                variable_class="survey_measurement",
            )
        ),
        **_calendar(),
    )
    payload = result.to_dict()

    assert payload["status"] == "unsupported_no_approved_method"
    assert payload["native_data_preserved"] is True
    assert payload["alignment_results"][0]["status"] == (
        "unsupported_no_approved_method"
    )
