"""Tests for ancestry_mmm.core.coverage_fabric (Phase 3 UI overhaul's
coverage-fabric visualisation, REQ-COVERAGE-001 - see docs/decision_log.md).

Pure-logic module, no Streamlit/Plotly import - these tests build a
VariableCoverageMatrix directly and assert on the derived FabricCell/summary
output, never on rendering.
"""

from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.coverage_fabric import (
    FABRIC_LABEL_COVERED,
    build_fabric_cells,
    cells_matching_points,
    fabric_summary_sentences,
    filter_cells_by_states,
)

_FREQ = FrequencyMetadata(
    native_frequency="weekly", target_frequency="weekly", variable_class="flow_count"
)


def _record(**overrides) -> VariableCoverageRecord:
    defaults = dict(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=_FREQ,
        coverage_segments=(),
        expected_start="2024-01-01",
        expected_end="2024-01-29",
        observed_start="2024-01-01",
        observed_end="2024-01-29",
    )
    defaults.update(overrides)
    return VariableCoverageRecord(**defaults)


def _matrix(records) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=tuple(records),
    )


class TestBuildFabricCells:
    def test_a_record_with_no_gap_segments_becomes_one_fully_covered_cell(self):
        matrix = _matrix([_record()])
        cells = build_fabric_cells(matrix)
        assert len(cells) == 1
        assert cells[0].state == FABRIC_LABEL_COVERED
        assert cells[0].period_start == "2024-01-01"
        assert cells[0].period_end == "2024-01-29"

    def test_a_record_with_one_gap_in_the_middle_produces_three_cells(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            )
        )
        matrix = _matrix([record])
        cells = build_fabric_cells(matrix)
        states = [(c.period_start, c.period_end, c.state) for c in cells]
        assert states == [
            ("2024-01-01", "2024-01-07", FABRIC_LABEL_COVERED),
            ("2024-01-08", "2024-01-14", "unknown"),
            ("2024-01-15", "2024-01-29", FABRIC_LABEL_COVERED),
        ]

    def test_a_gap_at_the_very_start_produces_no_leading_covered_cell(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-01", period_end="2024-01-07", state="unknown"
                ),
            )
        )
        cells = build_fabric_cells(_matrix([record]))
        assert cells[0].state == "unknown"
        assert len(cells) == 2

    def test_a_gap_spanning_the_entire_window_produces_no_covered_cell(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-01",
                    period_end="2024-01-29",
                    state="missing_expected",
                ),
            )
        )
        cells = build_fabric_cells(_matrix([record]))
        assert len(cells) == 1
        assert cells[0].state == "missing_expected"

    def test_a_record_with_no_expected_window_emits_only_recorded_segments(self):
        record = _record(
            expected_start=None,
            expected_end=None,
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            ),
        )
        cells = build_fabric_cells(_matrix([record]))
        assert len(cells) == 1
        assert cells[0].state == "unknown"

    def test_row_label_includes_product_and_segment_when_present(self):
        record = _record(product="DNA_Kits", segment="New Customer")
        cells = build_fabric_cells(_matrix([record]))
        assert cells[0].row.row_label == "tv_spend / UK / DNA_Kits / New Customer"

    def test_empty_matrix_produces_no_cells(self):
        assert build_fabric_cells(_matrix([])) == []


class TestFilterCellsByStates:
    def test_no_states_selected_returns_every_cell(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            )
        )
        cells = build_fabric_cells(_matrix([record]))
        assert filter_cells_by_states(cells, []) == cells

    def test_filtering_isolates_only_the_selected_states(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            )
        )
        cells = build_fabric_cells(_matrix([record]))
        filtered = filter_cells_by_states(cells, ["unknown"])
        assert len(filtered) == 1
        assert filtered[0].state == "unknown"


class TestCellsMatchingPoints:
    def test_matches_a_point_by_row_label_and_period_start(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            )
        )
        cells = build_fabric_cells(_matrix([record]))
        gap_cell = next(c for c in cells if c.state == "unknown")
        point = {
            "y": gap_cell.row.row_label,
            "customdata": [None, None, None, None, gap_cell.period_start],
        }
        matches = cells_matching_points(cells, [point])
        assert matches == [gap_cell]

    def test_a_point_with_no_matching_cell_is_skipped_not_raised(self):
        cells = build_fabric_cells(_matrix([_record()]))
        point = {"y": "nonexistent / row", "customdata": [None] * 5}
        assert cells_matching_points(cells, [point]) == []

    def test_empty_points_returns_empty_list(self):
        cells = build_fabric_cells(_matrix([_record()]))
        assert cells_matching_points(cells, []) == []


class TestFabricSummarySentences:
    def test_empty_matrix_returns_no_sentences(self):
        assert fabric_summary_sentences(_matrix([])) == []

    def test_fully_covered_record_is_reported_by_market(self):
        matrix = _matrix([_record(market="UK")])
        sentences = fabric_summary_sentences(matrix)
        assert any(
            "UK: all 1 governed variable record(s) cover the full expected window" in s
            for s in sentences
        )

    def test_a_late_starting_series_is_reported(self):
        record = _record(market="Australia", observed_start="2024-01-15")
        matrix = _matrix([record])
        sentences = fabric_summary_sentences(matrix)
        assert any(
            "Australia has 1 variable(s) whose observed history starts later" in s
            for s in sentences
        )

    def test_an_unresolved_record_is_reported_as_blocking(self):
        record = _record(
            market="UK",
            coverage_segments=(
                CoverageSegment(
                    period_start="2024-01-08", period_end="2024-01-14", state="unknown"
                ),
            ),
        )
        matrix = _matrix([record])
        sentences = fabric_summary_sentences(matrix)
        assert any(
            "UK has 1 of 1 variable record(s) with unresolved coverage" in s
            for s in sentences
        )

    def test_every_sentence_is_derived_only_from_matrix_data_no_two_records_no_speculation(
        self,
    ):
        """Sanity check that the function does not fabricate a market or
        count that isn't actually in the matrix."""
        matrix = _matrix([_record(market="UK")])
        sentences = fabric_summary_sentences(matrix)
        joined = " ".join(sentences)
        assert "Australia" not in joined
        assert "Canada" not in joined
