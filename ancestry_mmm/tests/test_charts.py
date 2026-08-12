"""Tests for ancestry_mmm.components.charts - previously had no dedicated
test file (PR 97A); all 9 functions here are pure Plotly-figure builders
with no Streamlit/session-state/I/O dependency, so they're covered directly
with plain assertions on the returned go.Figure, no fixtures or mocking
needed.
"""

import numpy as np
import pandas as pd

from ancestry_mmm.components.charts import (
    create_time_series_chart,
    create_bar_chart_with_ci,
    create_stacked_area_chart,
    create_pie_chart,
    create_correlation_heatmap,
    create_response_curve,
    create_response_curve_with_band,
    create_annotated_response_curve,
    create_waterfall_chart,
)


def test_time_series_chart_has_one_trace_per_y_col_with_correct_names():
    df = pd.DataFrame(
        {
            "week": [1, 2, 3],
            "TV_Brand": [10.0, 20.0, 30.0],
            "Social": [5.0, 15.0, 25.0],
        }
    )
    fig = create_time_series_chart(df, "week", ["TV_Brand", "Social"], title="t")
    assert len(fig.data) == 2
    assert [trace.name for trace in fig.data] == ["TV_Brand", "Social"]
    assert fig.layout.xaxis.title.text == "week"
    assert fig.layout.title.text == "t"
    assert fig.layout.plot_bgcolor == "#FFFFFF"


def test_bar_chart_with_ci_computes_error_bars_from_bounds():
    fig = create_bar_chart_with_ci(
        categories=["A", "B"],
        values=[10.0, 20.0],
        lower_ci=[8.0, 15.0],
        upper_ci=[13.0, 22.0],
    )
    assert len(fig.data) == 2
    assert fig.data[0].error_y.array == (3.0,)
    assert fig.data[0].error_y.arrayminus == (2.0,)
    assert fig.data[1].error_y.array == (2.0,)
    assert fig.data[1].error_y.arrayminus == (5.0,)


def test_stacked_area_chart_stacks_every_trace():
    df = pd.DataFrame({"week": [1, 2], "direct": [1.0, 2.0], "halo": [0.5, 1.0]})
    fig = create_stacked_area_chart(df, "week", ["direct", "halo"])
    assert len(fig.data) == 2
    assert all(trace.stackgroup == "one" for trace in fig.data)


def test_pie_chart_has_one_trace_with_matching_colors_and_hole():
    fig = create_pie_chart(labels=["A", "B", "C"], values=[1.0, 2.0, 3.0], hole=0.5)
    assert len(fig.data) == 1
    assert fig.data[0].type == "pie"
    assert fig.data[0].hole == 0.5
    assert len(fig.data[0].marker.colors) == 3


def test_correlation_heatmap_sets_symmetric_color_range():
    corr = pd.DataFrame([[1.0, 0.5], [0.5, 1.0]], columns=["a", "b"], index=["a", "b"])
    fig = create_correlation_heatmap(corr)
    assert len(fig.data) == 1
    assert fig.layout.coloraxis.cmin == -1
    assert fig.layout.coloraxis.cmax == 1


def test_response_curve_without_current_spend_has_one_trace():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_response_curve(x, y, "TV_Brand")
    assert len(fig.data) == 1
    assert fig.data[0].mode == "lines"


def test_response_curve_with_current_spend_adds_marker_at_nearest_point():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_response_curve(x, y, "TV_Brand", current_spend=48.0)
    assert len(fig.data) == 2
    marker_trace = fig.data[1]
    assert marker_trace.mode == "markers"
    assert marker_trace.x[0] == 48.0
    assert marker_trace.y[0] == 10.0  # y_values at the nearest x (50.0)


def test_response_curve_with_band_has_two_traces_without_current_spend():
    x = np.array([0.0, 50.0, 100.0])
    mean = np.array([0.0, 10.0, 15.0])
    lower = np.array([0.0, 8.0, 12.0])
    upper = np.array([0.0, 12.0, 18.0])
    fig = create_response_curve_with_band(x, mean, lower, upper, "TV_Brand")
    assert len(fig.data) == 2
    band_trace, mean_trace = fig.data
    assert np.array_equal(band_trace.x, np.concatenate([x, x[::-1]]))
    assert np.array_equal(band_trace.y, np.concatenate([upper, lower[::-1]]))
    assert np.array_equal(mean_trace.y, mean)


def test_response_curve_with_band_adds_marker_at_nearest_point():
    x = np.array([0.0, 50.0, 100.0])
    mean = np.array([0.0, 10.0, 15.0])
    lower = np.array([0.0, 8.0, 12.0])
    upper = np.array([0.0, 12.0, 18.0])
    fig = create_response_curve_with_band(
        x, mean, lower, upper, "TV_Brand", current_spend=99.0
    )
    assert len(fig.data) == 3
    marker_trace = fig.data[2]
    assert marker_trace.mode == "markers"
    assert marker_trace.x[0] == 99.0
    assert marker_trace.y[0] == 15.0  # mean_values at the nearest x (100.0)


def test_response_curve_with_band_defaults_to_spend_axis_label():
    x = np.array([0.0, 50.0, 100.0])
    mean = np.array([0.0, 10.0, 15.0])
    lower = np.array([0.0, 8.0, 12.0])
    upper = np.array([0.0, 12.0, 18.0])
    fig = create_response_curve_with_band(x, mean, lower, upper, "TV_Brand")
    assert fig.layout.xaxis.title.text == "Spend"


def test_response_curve_with_band_uses_the_supplied_axis_label():
    """Corrective PR E2.4: an official model-input curve's axis is a
    governed media-input unit, never hard-coded "Spend" - the chart
    contract accepts an explicit label rather than inferring one."""
    x = np.array([0.0, 50.0, 100.0])
    mean = np.array([0.0, 10.0, 15.0])
    lower = np.array([0.0, 8.0, 12.0])
    upper = np.array([0.0, 12.0, 18.0])
    fig = create_response_curve_with_band(
        x, mean, lower, upper, "TV_Brand", x_axis_label="Model input (TVRs)"
    )
    assert fig.layout.xaxis.title.text == "Model input (TVRs)"


# ---------------------------------------------------------------------------
# create_annotated_response_curve (Phase 6 UI overhaul) - the on-curve
# annotation layer application.curve_annotations feeds. Every value here is
# a plain scalar/sequence the caller must have already computed; this
# function only ever draws what it is given, never derives or fabricates a
# value itself.
# ---------------------------------------------------------------------------


def test_annotated_curve_with_no_annotation_args_has_one_line_trace():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(x, y, "TV_Brand")
    assert len(fig.data) == 1
    assert fig.data[0].mode == "lines"
    assert fig.data[0].name == "Response"
    assert fig.layout.annotations == ()


def test_annotated_curve_with_band_adds_credible_interval_trace():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    lower = np.array([0.0, 8.0, 12.0])
    upper = np.array([0.0, 12.0, 18.0])
    fig = create_annotated_response_curve(
        x, y, "TV_Brand", lower_values=lower, upper_values=upper
    )
    assert len(fig.data) == 2
    assert fig.data[0].name == "Credible interval"
    assert fig.data[1].name == "Mean response"


def test_annotated_curve_adds_current_marker_at_nearest_point():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(x, y, "TV_Brand", current_x=48.0)
    assert len(fig.data) == 2
    marker_trace = fig.data[1]
    assert marker_trace.mode == "markers"
    assert marker_trace.x[0] == 48.0
    assert marker_trace.y[0] == 10.0


def test_annotated_curve_draws_observed_support_shaded_region():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(
        x, y, "TV_Brand", observed_min=10.0, observed_max=80.0
    )
    shapes = fig.layout.shapes
    assert len(shapes) == 1
    assert shapes[0].x0 == 10.0
    assert shapes[0].x1 == 80.0


def test_annotated_curve_no_shaded_region_when_support_not_given():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(x, y, "TV_Brand")
    assert fig.layout.shapes == ()


def test_annotated_curve_renders_annotation_lines_as_a_text_box():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(
        x,
        y,
        "TV_Brand",
        annotation_lines=[
            "Locally estimated",
            "Average CPA at current spend: 12.50",
        ],
    )
    assert len(fig.layout.annotations) == 1
    text = fig.layout.annotations[0].text
    assert "Locally estimated" in text
    assert "Average CPA at current spend: 12.50" in text


def test_annotated_curve_no_annotation_box_when_no_lines_given():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(x, y, "TV_Brand", annotation_lines=[])
    assert fig.layout.annotations == ()


def test_annotated_curve_uses_supplied_axis_label():
    x = np.array([0.0, 50.0, 100.0])
    y = np.array([0.0, 10.0, 15.0])
    fig = create_annotated_response_curve(
        x, y, "TV_Brand", x_axis_label="Model input (TVRs)"
    )
    assert fig.layout.xaxis.title.text == "Model input (TVRs)"


def test_waterfall_chart_marks_every_category_relative_except_the_last():
    fig = create_waterfall_chart(
        categories=["Baseline", "TV_Brand", "Social", "Total"],
        values=[100.0, 20.0, -5.0, 115.0],
    )
    assert len(fig.data) == 1
    waterfall = fig.data[0]
    assert waterfall.measure == ("relative", "relative", "relative", "total")
