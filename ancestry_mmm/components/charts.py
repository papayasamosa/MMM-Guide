"""Reusable chart components for the MMM Dashboard."""

import plotly.graph_objects as go
import plotly.express as px
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Sequence, Tuple

from ancestry_mmm.utils import CHART_COLORS, THEME_COLORS
from ancestry_mmm.core.coverage import COVERAGE_STATES
from ancestry_mmm.core.coverage_fabric import FABRIC_LABEL_COVERED, FabricCell


def _apply_chart_theme(fig: go.Figure) -> go.Figure:
    """Apply the shared light-workbench treatment to every chart."""

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=THEME_COLORS["card"],
        plot_bgcolor=THEME_COLORS["card"],
        font=dict(color=THEME_COLORS["foreground"]),
        hoverlabel=dict(
            bgcolor=THEME_COLORS["card"],
            bordercolor=THEME_COLORS["border"],
            font=dict(color=THEME_COLORS["foreground"]),
        ),
    )
    fig.update_xaxes(
        gridcolor=THEME_COLORS["grid"],
        linecolor=THEME_COLORS["border"],
        zeroline=False,
    )
    fig.update_yaxes(
        gridcolor=THEME_COLORS["grid"],
        linecolor=THEME_COLORS["border"],
        zeroline=False,
    )
    return fig


def create_time_series_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: List[str],
    title: Optional[str] = None,
    height: int = 400,
) -> go.Figure:
    """Create a multi-line time series chart."""
    fig = go.Figure()

    colors = list(CHART_COLORS.values())

    for i, col in enumerate(y_cols):
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[col],
                name=col,
                line=dict(color=colors[i % len(colors)]),
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        xaxis_title=x_col,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_bar_chart_with_ci(
    categories: List[str],
    values: List[float],
    lower_ci: List[float],
    upper_ci: List[float],
    title: Optional[str] = None,
    height: int = 320,
) -> go.Figure:
    """Create a bar chart with confidence intervals."""
    fig = go.Figure()

    colors = list(CHART_COLORS.values())

    for i, (cat, val, lower, upper) in enumerate(
        zip(categories, values, lower_ci, upper_ci)
    ):
        fig.add_trace(
            go.Bar(
                name=cat,
                x=[cat],
                y=[val],
                marker_color=colors[i % len(colors)],
                error_y=dict(
                    type="data",
                    symmetric=False,
                    array=[upper - val],
                    arrayminus=[val - lower],
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        showlegend=False,
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_stacked_area_chart(
    df: pd.DataFrame,
    x_col: str,
    y_cols: List[str],
    title: Optional[str] = None,
    height: int = 300,
) -> go.Figure:
    """Create a stacked area chart for decomposition."""
    fig = go.Figure()

    colors = [THEME_COLORS["foreground_muted"]] + list(
        CHART_COLORS.values()
    )  # Baseline + channels

    for i, col in enumerate(y_cols):
        fig.add_trace(
            go.Scatter(
                x=df[x_col],
                y=df[col],
                name=col,
                mode="lines",
                stackgroup="one",
                fillcolor=colors[i % len(colors)],
                line=dict(width=0),
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_pie_chart(
    labels: List[str],
    values: List[float],
    title: Optional[str] = None,
    height: int = 300,
    hole: float = 0.4,
) -> go.Figure:
    """Create a donut/pie chart."""
    colors = list(CHART_COLORS.values())

    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=hole,
                marker_colors=colors[: len(labels)],
            )
        ]
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        title=title,
        height=height,
        margin=dict(t=30, b=0, l=0, r=0),
    )

    _apply_chart_theme(fig)
    return fig


def create_correlation_heatmap(
    corr_matrix: pd.DataFrame,
    title: Optional[str] = None,
    height: int = 500,
) -> go.Figure:
    """Create a correlation matrix heatmap."""
    fig = px.imshow(
        corr_matrix,
        text_auto=".2f",
        color_continuous_scale="RdBu_r",
        zmin=-1,
        zmax=1,
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_response_curve(
    x_values: np.ndarray,
    y_values: np.ndarray,
    channel_name: str,
    current_spend: Optional[float] = None,
    height: int = 320,
) -> go.Figure:
    """Create a response curve visualization."""
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=y_values,
            mode="lines",
            line=dict(color=CHART_COLORS["primary"], width=2),
            name="Response",
        )
    )

    if current_spend is not None:
        # Find y value at current spend
        idx = np.argmin(np.abs(x_values - current_spend))
        current_y = y_values[idx]

        fig.add_trace(
            go.Scatter(
                x=[current_spend],
                y=[current_y],
                mode="markers",
                marker=dict(color=CHART_COLORS["warning"], size=10),
                name="Current",
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=f"{channel_name} Response Curve",
        xaxis_title="Spend",
        yaxis_title="Response",
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_response_curve_with_band(
    x_values: np.ndarray,
    mean_values: np.ndarray,
    lower_values: np.ndarray,
    upper_values: np.ndarray,
    channel_name: str,
    current_spend: Optional[float] = None,
    height: int = 320,
    x_axis_label: str = "Spend",
) -> go.Figure:
    """Response curve with a shaded credible-interval band around the mean -
    the per-draw uncertainty equivalent of create_response_curve
    (core.uncertainty's generate_channel_curve_with_uncertainty /
    generate_market_channel_curve_with_uncertainty).

    ``x_axis_label`` (Corrective PR E2.4) defaults to "Spend" for the
    exploratory/legacy point-estimate viewers that always pass a genuine
    spend axis, but an official curve caller must resolve and pass the
    actual axis label explicitly (e.g. via
    ``core.canonical_curves.resolve_curve_axis_label``) - an official
    model-input curve's x-axis is a governed media-input unit (TVRs,
    impressions, clicks, ...), never spend, and this function must never
    infer a monetary meaning from its own name or from column presence.
    """
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=np.concatenate([x_values, x_values[::-1]]),
            y=np.concatenate([upper_values, lower_values[::-1]]),
            fill="toself",
            fillcolor="rgba(99, 179, 138, 0.2)",
            line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip",
            name="Credible interval",
            showlegend=True,
        )
    )

    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=mean_values,
            mode="lines",
            line=dict(color=CHART_COLORS["primary"], width=2),
            name="Mean response",
        )
    )

    if current_spend is not None:
        idx = np.argmin(np.abs(x_values - current_spend))
        fig.add_trace(
            go.Scatter(
                x=[current_spend],
                y=[mean_values[idx]],
                mode="markers",
                marker=dict(color=CHART_COLORS["warning"], size=10),
                name="Current",
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=f"{channel_name} Response Curve (with uncertainty)",
        xaxis_title=x_axis_label,
        yaxis_title="Response",
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_annotated_response_curve(
    x_values: np.ndarray,
    y_values: np.ndarray,
    channel_name: str,
    *,
    lower_values: Optional[np.ndarray] = None,
    upper_values: Optional[np.ndarray] = None,
    current_x: Optional[float] = None,
    observed_min: Optional[float] = None,
    observed_max: Optional[float] = None,
    annotation_lines: Optional[Sequence[str]] = None,
    x_axis_label: str = "Spend",
    height: int = 340,
) -> go.Figure:
    """Response curve with the Phase 6 UI overhaul's on-curve annotation
    layer (see docs/decision_log.md; ``application.curve_annotations``
    computes every value this function is passed - it never invents one).

    Adds, only where the corresponding value is given: a shaded band for the
    observed historical support range (never drawn from a saturation
    parameter - the caller must have derived it from real historical data),
    a marker at the current spend/model-input point, and a small fixed text
    box listing evidence/status, extrapolation, and any economics lines a
    caller resolved. ``lower_values``/``upper_values`` optionally add the
    same credible-interval band ``create_response_curve_with_band`` draws -
    this function replaces neither existing chart function; both remain in
    use where no annotation layer is needed.
    """
    fig = go.Figure()

    if (
        observed_min is not None
        and observed_max is not None
        and observed_max > observed_min
    ):
        fig.add_vrect(
            x0=observed_min,
            x1=observed_max,
            fillcolor="rgba(107, 139, 122, 0.14)",
            line_width=0,
            layer="below",
            annotation_text="Observed support",
            annotation_position="top left",
            annotation_font_size=10,
        )

    has_band = lower_values is not None and upper_values is not None
    if has_band:
        fig.add_trace(
            go.Scatter(
                x=np.concatenate([x_values, x_values[::-1]]),
                y=np.concatenate([upper_values, lower_values[::-1]]),
                fill="toself",
                fillcolor="rgba(99, 179, 138, 0.2)",
                line=dict(color="rgba(0,0,0,0)"),
                hoverinfo="skip",
                name="Credible interval",
                showlegend=True,
            )
        )

    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=y_values,
            mode="lines",
            line=dict(color=CHART_COLORS["primary"], width=2),
            name="Mean response" if has_band else "Response",
        )
    )

    if current_x is not None and len(x_values):
        idx = int(np.argmin(np.abs(x_values - current_x)))
        fig.add_trace(
            go.Scatter(
                x=[current_x],
                y=[y_values[idx]],
                mode="markers",
                marker=dict(color=CHART_COLORS["warning"], size=12, symbol="diamond"),
                name="Current",
                hovertemplate=f"Current: {current_x:,.2f}<extra></extra>",
            )
        )

    if annotation_lines:
        fig.add_annotation(
            xref="paper",
            yref="paper",
            x=0.02,
            y=0.98,
            xanchor="left",
            yanchor="top",
            showarrow=False,
            align="left",
            text="<br>".join(annotation_lines),
            bgcolor="rgba(20, 28, 24, 0.72)",
            bordercolor=THEME_COLORS["border"],
            borderwidth=1,
            borderpad=6,
            font=dict(size=11, color=THEME_COLORS["foreground"]),
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=f"{channel_name} response curve",
        xaxis_title=x_axis_label,
        yaxis_title="Response",
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


def create_waterfall_chart(
    categories: List[str],
    values: List[float],
    title: Optional[str] = None,
    height: int = 300,
) -> go.Figure:
    """Create a waterfall chart for contribution analysis."""
    # Determine measure type (relative vs total)
    measure = ["relative"] * (len(categories) - 1) + ["total"]

    fig = go.Figure(
        go.Waterfall(
            name="Contribution",
            orientation="v",
            measure=measure,
            x=categories,
            y=values,
            connector={"line": {"color": THEME_COLORS["border"]}},
            increasing={"marker": {"color": CHART_COLORS["success"]}},
            decreasing={"marker": {"color": CHART_COLORS["error"]}},
            totals={"marker": {"color": CHART_COLORS["primary"]}},
        )
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        title=title,
        height=height,
    )

    _apply_chart_theme(fig)
    return fig


# ---------------------------------------------------------------------------
# Coverage fabric (Phase 3 UI overhaul, REQ-COVERAGE-001 - see
# docs/decision_log.md and ancestry_mmm.core.coverage_fabric). A "categorical
# heatmap made unusually good" rather than a Components v2 build: Plotly's
# own grouped-bar/legend/hover machinery already gives every state its own
# toggleable legend entry, and each bar additionally carries a short glyph
# label - so no missingness state is ever colour-only (root AGENTS.md /
# pages/AGENTS.md accessibility rule: "distinguish states by more than
# colour alone"). Never a purple/blue hue (tokens.py's existing "no
# purple/blue AI-gradient accent" convention, extended here): "unknown" -
# the one state that has not even been triaged yet - instead gets the one
# stand-out *light* cell against this app's otherwise dark palette, which
# reads as "flag for review" without borrowing a severity colour that would
# misrepresent it as a confirmed problem the way "missing_expected" (red) is.
# ---------------------------------------------------------------------------

# state -> (display label, short in-cell glyph, hex colour). Every entry in
# core.coverage.COVERAGE_STATES plus the FABRIC_LABEL_COVERED sentinel must
# appear here (enforced by test_charts_coverage_fabric.py) - a chart must
# never silently drop a governed state for lack of a colour/glyph.
STATE_VISUALS: Dict[str, Tuple[str, str, str]] = {
    FABRIC_LABEL_COVERED: ("Covered (no recorded gap)", "·", "#22301F"),
    "observed_zero": ("Observed zero", "0", CHART_COLORS["chart_1"]),
    "estimated": ("Estimated", "~", CHART_COLORS["chart_2"]),
    "modelled": ("Modelled", "M", CHART_COLORS["chart_5"]),
    "not_applicable": ("Not applicable", "–", CHART_COLORS["chart_6"]),
    "suppressed": ("Suppressed", "S", "#7A6A57"),
    "unavailable_source": ("Unavailable source", "U", CHART_COLORS["chart_3"]),
    "missing_expected": ("Missing (expected)", "!", CHART_COLORS["error"]),
    "unknown": ("Unknown - not yet triaged", "?", THEME_COLORS["foreground"]),
}
# Text colour per state's glyph - the light "unknown"/"covered" cells need
# dark glyph text to stay legible; every other (dark) cell keeps light text.
_DARK_GLYPH_STATES = {FABRIC_LABEL_COVERED, "unknown"}

assert set(STATE_VISUALS) == set(COVERAGE_STATES) | {FABRIC_LABEL_COVERED}, (
    "STATE_VISUALS must cover exactly every core.coverage.COVERAGE_STATES "
    "entry plus FABRIC_LABEL_COVERED - see test_charts_coverage_fabric.py"
)


def create_coverage_fabric_chart(
    cells: Sequence[FabricCell],
    *,
    row_order: Optional[Sequence[str]] = None,
    height: int = 480,
) -> go.Figure:
    """A time x variable-market fabric: one horizontal row per governed
    variable/market (``FabricCell.row.row_label``), with one coloured,
    glyph-labelled segment per recorded state run along a real date axis.
    One Plotly trace per state (never one trace per cell) so Plotly's own
    legend does the "never colour alone" accessibility work for free - every
    state is independently togglable and always paired with its text label.

    ``row_order`` fixes the row (y-axis) order top-to-bottom; omitted rows
    default to first-seen order in ``cells``, which already reflects the
    coverage matrix's own market/variable ordering.
    """
    if row_order is None:
        seen: List[str] = []
        for cell in cells:
            if cell.row.row_label not in seen:
                seen.append(cell.row.row_label)
        row_order = seen

    fig = go.Figure()
    for state in STATE_VISUALS:
        state_cells = [c for c in cells if c.state == state]
        if not state_cells:
            continue
        label, glyph, color = STATE_VISUALS[state]
        starts = [pd.Timestamp(c.period_start) for c in state_cells]
        ends = [pd.Timestamp(c.period_end) + pd.Timedelta(days=1) for c in state_cells]
        durations_ms = [(e - s).total_seconds() * 1000 for s, e in zip(starts, ends)]
        customdata = [
            (
                label,
                c.record.frequency.native_frequency,
                c.record.source_id,
                c.record.source_version,
                c.period_start,
                c.period_end,
                c.record.observed_start or "n/a",
                c.record.observed_end or "n/a",
                c.record.treatment_status,
                "Yes" if c.record.approved_for_official_use else "No",
            )
            for c in state_cells
        ]
        fig.add_trace(
            go.Bar(
                name=label,
                x=durations_ms,
                base=starts,
                y=[c.row.row_label for c in state_cells],
                orientation="h",
                marker=dict(
                    color=color, line=dict(color=THEME_COLORS["border"], width=1)
                ),
                text=[glyph] * len(state_cells),
                textposition="inside",
                insidetextanchor="middle",
                textfont=dict(
                    color=(
                        THEME_COLORS["background"]
                        if state in _DARK_GLYPH_STATES
                        else THEME_COLORS["foreground"]
                    )
                ),
                customdata=customdata,
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "State: %{customdata[0]}<br>"
                    "Native frequency: %{customdata[1]}<br>"
                    "Source: %{customdata[2]} v%{customdata[3]}<br>"
                    "Period: %{customdata[4]} to %{customdata[5]}<br>"
                    "Observed window: %{customdata[6]} to %{customdata[7]}<br>"
                    "Treatment status: %{customdata[8]}<br>"
                    "Approved for official use: %{customdata[9]}"
                    "<extra></extra>"
                ),
            )
        )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        barmode="overlay",
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis=dict(type="date", title="Period"),
        yaxis=dict(
            title=None,
            categoryorder="array",
            categoryarray=list(row_order),
            autorange="reversed",
        ),
        margin=dict(l=10, r=10, t=40, b=10),
    )
    _apply_chart_theme(fig)
    return fig
