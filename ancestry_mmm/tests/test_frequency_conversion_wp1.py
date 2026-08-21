"""WP1 mixed-frequency executor tests (REQ-COVERAGE-001 S4/S5)."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from ancestry_mmm.core.coverage import (
    DefinitionBreak,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.frequency_alignment import (
    AlignmentSpecification,
    assess_official_preparation,
)
from ancestry_mmm.core.frequency_conversion import (
    FrequencyConversionError,
    available_method_ids,
    execute_frequency_conversion,
)


def _spec(**overrides) -> AlignmentSpecification:
    values = dict(
        variable_id="value",
        source_id="source",
        source_version=1,
        market="UK",
        native_frequency="monthly",
        target_frequency="weekly",
        variable_class="flow_count",
        method_id="calendar_overlap_allocation",
        method_version=1,
    )
    values.update(overrides)
    return AlignmentSpecification(**values)


def _target_periods(start="2023-12-31", end="2024-03-31"):
    return pd.date_range(start, end, freq="7D").strftime("%Y-%m-%d").tolist()


def test_catalogue_has_explicit_method_per_variable_class():
    assert "calendar_overlap_allocation" in available_method_ids("flow_count")
    assert "release_aware_locf" in available_method_ids("stock_level")
    assert "native_cadence_only" in available_method_ids("survey_measurement")
    assert "calendar_event_alignment" in available_method_ids("event_flag")


def test_flow_overlap_reconciles_leap_year_months_and_partial_weeks():
    source = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "value": [310.0, 290.0],
        }
    )
    result = execute_frequency_conversion(
        source,
        _spec(),
        date_col="period_start",
        value_col="value",
        target_periods=_target_periods(end="2024-03-03"),
    )

    assert result.frame["value"].sum() == pytest.approx(600.0)
    february_tail = result.frame.loc[
        result.frame["period_start"] == pd.Timestamp("2024-02-25"), "value"
    ]
    assert february_tail.iloc[0] == pytest.approx(50.0)
    assert len(result.evidence["reconciliation"]) == 10


def test_release_aware_locf_has_no_backward_fill_and_respects_release_date():
    source = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "released_on": pd.to_datetime(["2024-01-31", "2024-02-29"]),
            "value": [10.0, 20.0],
        }
    )
    spec = _spec(
        variable_class="rate_index",
        method_id="release_aware_locf",
        publication_timing={"release_date_column": "released_on"},
    )
    result = execute_frequency_conversion(
        source,
        spec,
        date_col="period_start",
        value_col="value",
        target_periods=_target_periods(end="2024-03-31"),
    )

    values = result.frame.set_index("period_start")["value"]
    assert pd.isna(values.loc[pd.Timestamp("2023-12-31")])
    assert pd.isna(values.loc[pd.Timestamp("2024-01-21")])
    assert values.loc[pd.Timestamp("2024-01-28")] == 10.0
    assert values.loc[pd.Timestamp("2024-02-25")] == 20.0


def test_release_aware_locf_fails_closed_on_definition_break():
    source = pd.DataFrame(
        {"period_start": pd.to_datetime(["2024-01-01"]), "value": [10.0]}
    )
    with pytest.raises(FrequencyConversionError, match="definition break"):
        execute_frequency_conversion(
            source,
            _spec(
                variable_class="stock_level",
                method_id="release_aware_locf",
                definition_breaks=(
                    DefinitionBreak(
                        break_date="2024-01-15", description="question wording changed"
                    ),
                ),
            ),
            date_col="period_start",
            value_col="value",
            target_periods=_target_periods(end="2024-01-29"),
        )


def test_event_point_and_duration_alignment_preserve_calendar_placement():
    point = pd.DataFrame(
        {
            "event_start": pd.to_datetime(["2024-01-17"]),
            "event_end": pd.to_datetime(["2024-01-17"]),
            "value": [1.0],
        }
    )
    point_spec = _spec(
        variable_class="event_flag",
        method_id="calendar_event_alignment",
        native_frequency="irregular",
        parameters={
            "event_type": "point",
            "start_column": "event_start",
            "end_column": "event_end",
        },
    )
    point_result = execute_frequency_conversion(
        point,
        point_spec,
        date_col="event_start",
        value_col="value",
        target_periods=_target_periods(end="2024-01-29"),
    )
    assert point_result.frame.iloc[0]["event_start"] == pd.Timestamp("2024-01-14")

    duration = pd.DataFrame(
        {
            "event_start": pd.to_datetime(["2024-02-26"]),
            "event_end": pd.to_datetime(["2024-03-04"]),
            "value": [1.0],
        }
    )
    duration_result = execute_frequency_conversion(
        duration,
        replace(
            point_spec,
            parameters={
                "event_type": "duration",
                "start_column": "event_start",
                "end_column": "event_end",
            },
        ),
        date_col="event_start",
        value_col="value",
        target_periods=_target_periods(start="2024-02-25", end="2024-03-03"),
    )
    assert duration_result.frame["value"].tolist() == pytest.approx([6 / 7, 2 / 7])


def test_sunday_calendar_handles_months_starting_and_ending_mid_week():
    source = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "value": [310.0, 290.0],
        }
    )
    result = execute_frequency_conversion(
        source,
        _spec(),
        date_col="period_start",
        value_col="value",
        target_periods=[
            "2023-12-31",
            "2024-01-07",
            "2024-01-14",
            "2024-01-21",
            "2024-01-28",
            "2024-02-04",
            "2024-02-11",
            "2024-02-18",
            "2024-02-25",
        ],
    )
    assert set(result.frame["period_start"]) == set(
        pd.to_datetime(
            [
                "2023-12-31",
                "2024-01-07",
                "2024-01-14",
                "2024-01-21",
                "2024-01-28",
                "2024-02-04",
                "2024-02-11",
                "2024-02-18",
                "2024-02-25",
            ]
        )
    )
    assert result.frame["value"].sum() == pytest.approx(600.0)


@pytest.mark.parametrize(
    ("source_date", "expected_week"),
    [("2024-01-01", "2024-01-07"), ("2024-01-07", "2024-01-07")],
)
def test_weekly_source_monday_or_sunday_is_aligned_to_sunday_start(
    source_date, expected_week
):
    source = pd.DataFrame(
        {"period_start": pd.to_datetime([source_date]), "value": [5.0]}
    )
    result = execute_frequency_conversion(
        source,
        _spec(
            native_frequency="weekly",
            variable_class="rate_index",
            method_id="weekly_anchor_alignment",
            parameters={
                "week_anchor": "monday" if source_date == "2024-01-01" else "sunday"
            },
        ),
        date_col="period_start",
        value_col="value",
        target_periods=["2023-12-31", "2024-01-07"],
    )
    assert result.frame["period_start"].tolist() == [pd.Timestamp(expected_week)]
    assert result.frame.loc[
        result.frame["period_start"] == pd.Timestamp(expected_week), "value"
    ].iloc[0] == pytest.approx(5.0)


def test_monthly_survey_step_is_as_of_release_and_does_not_leak_future_value():
    source = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2024-01-01", "2024-02-01"]),
            "released_on": pd.to_datetime(["2024-02-11", "2024-03-11"]),
            "value": [40.0, 50.0],
        }
    )
    result = execute_frequency_conversion(
        source,
        _spec(
            variable_class="survey_measurement",
            method_id="release_aware_locf",
            publication_timing={"release_date_column": "released_on"},
        ),
        date_col="period_start",
        value_col="value",
        target_periods=[
            "2024-01-28",
            "2024-02-04",
            "2024-02-11",
            "2024-03-03",
            "2024-03-10",
            "2024-03-17",
        ],
    )
    values = result.frame.set_index("period_start")["value"]
    assert pd.isna(values.loc[pd.Timestamp("2024-01-28")])
    assert pd.isna(values.loc[pd.Timestamp("2024-02-04")])
    assert values.loc[pd.Timestamp("2024-02-11")] == 40.0
    assert values.loc[pd.Timestamp("2024-03-03")] == 40.0
    assert values.loc[pd.Timestamp("2024-03-10")] == 50.0
    assert values.loc[pd.Timestamp("2024-03-17")] == 50.0


def test_unknown_method_and_missingness_fail_closed():
    source = pd.DataFrame(
        {"period_start": pd.to_datetime(["2024-01-01"]), "value": [1.0]}
    )
    with pytest.raises(FrequencyConversionError, match="explicit method_id"):
        execute_frequency_conversion(
            source,
            _spec(method_id=None),
            date_col="period_start",
            value_col="value",
            target_periods=_target_periods(end="2024-01-08"),
        )

    source = pd.DataFrame(
        {"period_start": pd.to_datetime(["2024-01-01"]), "value": ["not-a-number"]}
    )
    with pytest.raises(FrequencyConversionError, match="non-numeric"):
        execute_frequency_conversion(
            source,
            _spec(),
            date_col="period_start",
            value_col="value",
            target_periods=_target_periods(end="2024-01-08"),
        )


def test_method_version_and_parameters_round_trip_through_coverage_matrix():
    frequency = FrequencyMetadata(
        native_frequency="monthly",
        target_frequency="weekly",
        variable_class="rate_index",
        method="release_aware_locf",
        method_version=1,
        method_parameters={"release_basis": "explicit"},
        publication_timing={"release_date_column": "released_on"},
        reconciliation_rule="last released value",
    )
    record = VariableCoverageRecord(
        variable_id="cpi",
        source_id="context",
        source_version=2,
        market="UK",
        frequency=frequency,
        coverage_segments=(),
    )
    matrix = VariableCoverageMatrix(
        matrix_id="mixed",
        matrix_version=1,
        generated_at="2026-08-15",
        records=(record,),
    )
    restored = VariableCoverageMatrix.from_dict(matrix.to_dict())
    restored_frequency = restored.records[0].frequency
    assert restored_frequency.method_version == 1
    assert restored_frequency.method_parameters == {"release_basis": "explicit"}
    assert restored_frequency.publication_timing["release_date_column"] == "released_on"
    assert restored.fingerprint() == matrix.fingerprint()


def test_official_assessment_is_ready_only_for_explicit_executable_method():
    record = VariableCoverageRecord(
        variable_id="cpi",
        source_id="context",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="monthly",
            target_frequency="weekly",
            variable_class="rate_index",
            method="release_aware_locf",
            method_version=1,
        ),
        coverage_segments=(),
    )
    matrix = VariableCoverageMatrix(
        matrix_id="mixed",
        matrix_version=1,
        generated_at="2026-08-15",
        records=(record,),
    )
    result = assess_official_preparation(
        matrix,
        governed_start="2024-01-01",
        governed_end="2024-03-31",
        governed_frequency="weekly",
    )
    assert result.status == "ready"
    assert result.alignment_results[0].status == "ready"


def test_official_assessment_blocks_unknown_method_parameters():
    record = VariableCoverageRecord(
        variable_id="flow",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="monthly",
            target_frequency="weekly",
            variable_class="flow_count",
            method="calendar_overlap_allocation",
            method_version=1,
            method_parameters={"interpolation": "linear"},
        ),
        coverage_segments=(),
    )
    matrix = VariableCoverageMatrix(
        matrix_id="mixed",
        matrix_version=1,
        generated_at="2026-08-15",
        records=(record,),
    )
    result = assess_official_preparation(
        matrix,
        governed_start="2024-01-01",
        governed_end="2024-03-31",
        governed_frequency="weekly",
    )
    assert result.status == "unsupported_parameters"
    assert "invalid" in result.reason
