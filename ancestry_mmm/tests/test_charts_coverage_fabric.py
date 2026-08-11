"""Tests for ancestry_mmm.components.charts.create_coverage_fabric_chart and
STATE_VISUALS (Phase 3 UI overhaul's coverage-fabric visualisation,
REQ-COVERAGE-001 - see docs/decision_log.md).
"""

import plotly.graph_objects as go

from ancestry_mmm.components.charts import STATE_VISUALS, create_coverage_fabric_chart
from ancestry_mmm.core.coverage import COVERAGE_STATES
from ancestry_mmm.core.coverage import (
    CoverageSegment,
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.coverage_fabric import FABRIC_LABEL_COVERED, build_fabric_cells


def _cells():
    freq = FrequencyMetadata(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    record = VariableCoverageRecord(
        variable_id="tv_spend",
        source_id="media",
        source_version=1,
        market="UK",
        frequency=freq,
        coverage_segments=(
            CoverageSegment(
                period_start="2024-01-08", period_end="2024-01-14", state="unknown"
            ),
        ),
        expected_start="2024-01-01",
        expected_end="2024-01-29",
    )
    matrix = VariableCoverageMatrix(
        matrix_id="coverage-test",
        matrix_version=1,
        generated_at="2026-01-01",
        records=(record,),
    )
    return build_fabric_cells(matrix)


class TestStateVisuals:
    def test_covers_every_governed_state_plus_the_covered_sentinel(self):
        assert set(STATE_VISUALS) == set(COVERAGE_STATES) | {FABRIC_LABEL_COVERED}

    def test_every_entry_has_a_non_empty_label_glyph_and_colour(self):
        for state, (label, glyph, color) in STATE_VISUALS.items():
            assert label, f"{state} has no label"
            assert glyph, f"{state} has no glyph - states must never be colour-only"
            assert color, f"{state} has no colour"

    def test_every_colour_is_distinct(self):
        colors = [c for (_, _, c) in STATE_VISUALS.values()]
        assert len(colors) == len(set(colors)), (
            "every state must have a distinct colour"
        )

    def test_no_purple_or_blue_hue_is_used(self):
        # Mirrors tokens.py's existing "no purple/blue AI-gradient accent"
        # convention for the app's status vocabulary.
        for _, (_, _, color) in STATE_VISUALS.items():
            r = int(color[1:3], 16)
            g = int(color[3:5], 16)
            b = int(color[5:7], 16)
            assert not (b > r and b > g and b > 100), f"{color} reads as blue/purple"


class TestCreateCoverageFabricChart:
    def test_returns_a_figure_with_one_trace_per_state_present(self):
        cells = _cells()
        fig = create_coverage_fabric_chart(cells)
        assert isinstance(fig, go.Figure)
        present_states = {c.state for c in cells}
        assert len(fig.data) == len(present_states)

    def test_each_bar_carries_a_glyph_text_label_not_colour_alone(self):
        cells = _cells()
        fig = create_coverage_fabric_chart(cells)
        for trace in fig.data:
            assert trace.text, "every bar trace must carry a glyph text label"

    def test_empty_cells_produces_a_figure_with_no_traces(self):
        fig = create_coverage_fabric_chart([])
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 0

    def test_hover_template_includes_state_and_treatment_fields(self):
        cells = _cells()
        fig = create_coverage_fabric_chart(cells)
        for trace in fig.data:
            template = trace.hovertemplate
            assert "State:" in template
            assert "Treatment status:" in template
            assert "Approved for official use:" in template
