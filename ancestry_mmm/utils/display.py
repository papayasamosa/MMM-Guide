"""Display-only formatting helpers: dates, numbers, readable labels and
dataframe column configuration. These never change underlying values or
dtypes - they only control how a value or dataframe is *shown*, so callers
must keep using the raw dataframe/values for joins, filters, transforms,
modelling and exports.
"""

from typing import Any, Dict, Iterable, Mapping, Optional

import pandas as pd
import streamlit as st

# MomentJS-style format string understood natively by st.column_config.DateColumn:
# "D" = day of month, no leading zero; "MMM" = short month name; "YY" = 2-digit
# year. Confirmed empirically against a live Streamlit 1.59 DateColumn - the
# lowercase "yy" variant is NOT recognised and silently falls back to a
# 4-digit year, so the year token must be uppercase here even though the day
# token works either way.
DATE_COLUMN_FORMAT = "D MMM YY"

# Presentation-only labels for governed internal values. Stored keys remain
# unchanged for persistence, joins, and validation; this map only controls
# what an analyst reads in the dashboard.
DISPLAY_LABELS = {
    # Domain values shown in editors. These labels are presentation-only;
    # validators and persistence continue to use the keys on the left.
    "family_history": "Family History",
    "dna": "DNA",
    "primary": "Primary outcome",
    "secondary": "Secondary outcome",
    "funnel_intermediate": "Funnel intermediate",
    "diagnostic": "Diagnostic only",
    "primary_direct": "Primary direct effect",
    "active_cross_product": "Active cross-product effect",
    "exploratory_cross_product": "Exploratory cross-product effect",
    "excluded": "Excluded",
    "direct": "Direct effect",
    "cross_product": "Cross-product effect",
    "mediated": "Mediated diagnostic",
    "none": "No additional delay",
    "fixed_weeks": "Fixed delay",
    "adstock_only": "Media carryover only",
    "delayed_adstock": "Delayed media carryover",
    "business_assumption": "Business assumption",
    "experiment_supported": "Supported by experiment",
    "model_supported": "Supported by model evidence",
    "weak_evidence": "Weak evidence",
    "contradicted": "Contradicted by evidence",
    "unreviewed": "Not yet reviewed",
    "untested": "Not tested",
    "supported": "Supported",
    "inconclusive": "Inconclusive",
    "not_reviewed": "Not yet reviewed",
    "not_applicable": "Not applicable",
    "observed_zero": "Observed zero",
    "missing_expected": "Expected data missing",
    "unavailable_source": "Source unavailable",
    "suppressed": "Suppressed",
    "estimated": "Estimated",
    "modelled": "Modelled",
    "unknown": "Unknown",
    "proposed": "Proposed",
    "rejected": "Rejected",
    "approved": "Approved",
    "draft": "Draft",
    "reviewed": "Reviewed",
    "superseded": "Superseded",
    "paid": "Paid",
    "owned": "Owned",
    "earned": "Earned",
    "external_event": "External event",
    "intervention": "Planned intervention",
    "mediator": "Funnel mediator",
    "demand_capture": "Demand capture",
    "control": "Control variable",
    "event": "Event indicator",
    "paid_media_cost": "Paid media cost",
    "fully_loaded_cost": "Fully loaded cost",
    "campaign_cost": "Campaign cost",
    "response_only": "Response only",
    "optimisable": "Eligible for optimisation",
    "scenario_only": "Scenario use only",
    "fixed": "Fixed",
    "brand_upper": "Brand / upper funnel",
    "mid_funnel": "Mid-funnel",
    "performance_lower": "Performance / lower funnel",
    "cross_funnel": "Cross-funnel",
    "search_demand": "Branded-search demand",
    "paid_search_spend": "Paid Search spend",
    "paid_search_delivery": "Paid Search delivery",
    "paid_search_cap": "Paid Search cap",
    "organic_search_capture": "Organic search",
    "direct_navigation_capture": "Direct navigation",
    "monetary": "Money",
    "exposure_count": "Impressions / delivery count",
    "response_count": "Outcome / response count",
    "index": "Index",
    "observed": "Observed",
    "assumed": "Assumed",
    "daily": "Daily",
    "weekly": "Weekly",
    "monthly": "Monthly",
    "quarterly": "Quarterly",
    "irregular": "Irregular",
    "flow_count": "Flow or count",
    "stock_level": "Stock or level",
    "rate_index": "Rate or index",
    "survey_measurement": "Survey measurement",
    "event_flag": "Event flag",
    "market_specific": "Market-specific, partially pooled",
    "direct_channel": "Direct channel",
    "demand_capture_mediator": "Demand capture mediator",
    "experiment_calibrated_incremental": "Experiment-calibrated incrementality",
    "drop_rows": "Drop rows",
    "ffill": "Forward fill",
    "model_input": "Model-input curve",
    "specific_scenario": "Specific scenario",
    "historical_diagnostic_only": "Historical diagnostic only",
    "planned_decision": "Planned decision",
    "exogenous_forecastable_control": "Exogenous forecastable control",
    "cost_translation_assumption": "Cost / translation assumption",
    "endogenous_funnel_state": "Endogenous funnel state",
    "latent_baseline_state": "Latent baseline state",
    "fixed_business_assumption": "Fixed business assumption",
    "not_used_in_planning": "Not used in planning",
}


def format_date(value: Any) -> str:
    """Format a date-like value for inline display, e.g. `2 Jan 23`.

    Returns "" for missing values. Never mutates the input - callers keep the
    original datetime/Timestamp for any downstream computation.
    """
    if value is None:
        return ""
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(ts):
        return ""
    return f"{ts.day} {ts.strftime('%b %y')}"


def format_number(value: Any) -> str:
    """Format a number for inline display: thousands separators, no
    unnecessary decimal places, meaningful decimals kept.

    - int-like -> "55,008"
    - whole-number float -> "15,020" (no trailing ".0")
    - other float -> "79.02" (2 decimal places)

    Returns "" for missing values; non-numeric values are passed through
    unchanged.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if pd.isna(value):
            return ""
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}"
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def readable_label(name: Any) -> str:
    """Technical column/key name -> human-readable label (spaces, not underscores).

    Purely cosmetic: the underlying column/key name is never renamed.
    """
    if not isinstance(name, str):
        return name
    if name in DISPLAY_LABELS:
        return DISPLAY_LABELS[name]
    return name.replace("_", " ")


def readable_labels(names: Iterable[str]) -> Dict[str, str]:
    """Map each technical name to its readable label."""
    return {name: readable_label(name) for name in names}


def outcome_display_label(outcome: Any, *, include_breakdown: bool = False) -> str:
    """Return a concise human label for a governed outcome.

    The stable ``outcome_id`` remains the value used by selectors, graph
    edges, persistence, and joins.  This helper only formats an
    ``OutcomeDefinition`` or its JSON-safe mapping for presentation, so
    imported draft candidates and fitted catalogue records use the same
    vocabulary without exposing raw IDs in routine UI.
    """

    def value(field: str) -> str:
        if isinstance(outcome, Mapping):
            raw = outcome.get(field, "")
        else:
            raw = getattr(outcome, field, "")
        return str(raw or "").strip()

    outcome_id = value("outcome_id")
    parts = [
        readable_label(value(field))
        for field in ("product", "segment", "metric")
        if value(field)
    ]
    label = " · ".join(parts) or readable_label(outcome_id)
    if include_breakdown:
        dimension = value("segment_dimension")
        if dimension and dimension != "unspecified":
            label += f" · Breakdown: {readable_label(dimension)}"
    definition_version = value("definition_version")
    if definition_version:
        label += f" (definition {definition_version})"
    return label


def display_enum_options(values: Iterable[Any]) -> list[Any]:
    """Return editor options with human labels while retaining no domain state.

    Streamlit's selectbox columns do not provide a value/label pair API. Pages
    therefore render these labels in a presentation dataframe and restore the
    original keys immediately after the editor returns.
    """
    return [readable_label(value) for value in values]


def display_enum_frame(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Copy ``df`` and humanise selected enum columns for a data editor."""
    displayed = df.copy()
    for column in columns:
        if column in displayed.columns:
            displayed[column] = displayed[column].map(readable_label)
    return displayed


def restore_enum_frame(
    df: pd.DataFrame, columns: Iterable[str], values_by_column: Dict[str, Iterable[Any]]
) -> pd.DataFrame:
    """Copy an edited display frame and restore its persisted enum keys."""
    restored = df.copy()
    for column in columns:
        if column not in restored.columns:
            continue
        reverse = {readable_label(value): value for value in values_by_column[column]}
        restored[column] = restored[column].map(lambda value: reverse.get(value, value))
    return restored


def dataframe_column_config(
    df: pd.DataFrame,
    *,
    label_overrides: Optional[Dict[str, str]] = None,
    numeric_format: str = "localized",
) -> Dict[str, Any]:
    """Build a `column_config` dict for `st.dataframe` / `st.data_editor`:
    readable labels, `d MMM yy` dates, comma-formatted numbers right-aligned,
    text left-aligned. Display-only - the dataframe passed to Streamlit keeps
    its original dtypes and values.
    """
    label_overrides = label_overrides or {}
    config: Dict[str, Any] = {}
    for col in df.columns:
        col_name = str(col)
        label = label_overrides.get(col, readable_label(col_name))
        dtype = df[col].dtype
        if pd.api.types.is_datetime64_any_dtype(dtype):
            config[col] = st.column_config.DateColumn(
                label=label, format=DATE_COLUMN_FORMAT
            )
        elif pd.api.types.is_bool_dtype(dtype):
            config[col] = st.column_config.CheckboxColumn(label=label)
        elif pd.api.types.is_numeric_dtype(dtype):
            config[col] = st.column_config.NumberColumn(
                label=label, format=numeric_format, alignment="right"
            )
        else:
            config[col] = st.column_config.TextColumn(label=label, alignment="left")
    return config


# Readable labels + one-line explanations for transformation-pipeline operations
# (technical `op` keys are never renamed - these are display-only).
OPERATION_LABELS = {
    "rename_column": "Rename column",
    "cast_type": "Cast type",
    "calculated_column": "Calculated column",
    "lag_variable": "Lag variable",
    "fill_missing": "Fill missing",
    "drop_columns": "Drop columns",
    "drop_rows": "Drop rows",
    "event_flag": "Event flag",
}

OPERATION_DESCRIPTIONS = {
    "rename_column": "Change a column name without changing its values.",
    "cast_type": "Convert a column to text, number, date, or another supported type.",
    "calculated_column": "Create a new column from an expression.",
    "lag_variable": "Create a delayed version of a column.",
    "fill_missing": "Replace missing values using a selected rule.",
    "drop_columns": "Remove columns that are not needed.",
    "event_flag": "Create a binary flag for a date range or event.",
}

# Readable labels for scenario-planning spend constraint kinds (internal `kind`
# values are never renamed - display-only).
CONSTRAINT_KIND_LABELS = {
    "locked_cell": "Locked cell",
    "channel_total": "Channel total",
    "month_total": "Month total",
    "bounded_movement": "Bounded movement",
    "min_spend_floor": "Minimum spend floor",
}

# Short help text for technical fields, meant for the `help=` kwarg on widgets.
FIELD_HELP = {
    "adstock_decay": "Adstock controls how long the effect of media carries over after spend occurs.",
    "hill_saturation": "Saturation describes how each extra unit of spend produces a smaller incremental effect as spend increases.",
    "partial_pooling": "Partial pooling lets segments or markets share information, borrowing strength where data is thin and diverging where the data supports it.",
    "dna_halo_lag": "The DNA halo lag is the extra delay, beyond normal media carryover, before DNA-targeted media affects other segments.",
    "ltv": "Lifetime value (LTV) is the long-run value of one acquisition, used to weight outcomes when planning for value rather than raw volume.",
    "priors": "Priors are the model's starting assumptions about each parameter before seeing the data; fitting updates them using the data.",
    "curve_bank": "The curve bank stores versioned, traceable fitted parameter snapshots "
    "(Hill/decay/beta point estimates) for calibration tracking and evidence-tier "
    "display - never presented as official evaluated curves.",
    "approval": "Approval binds a named reviewer's sign-off to this exact fitted model - it becomes invalid the moment the data, specification or posterior changes.",
    "fixed_spend": "A fixed spend cell is excluded from optimisation and kept at its current value.",
    "locked_cells": "Locked cells are spend values the optimiser must not change, e.g. already-committed bookings.",
    "minimum_spend": "A minimum spend floor stops the optimiser from reducing spend below a required level.",
    "maximum_movement": "Maximum movement limits how far the optimiser can move spend away from the current plan, as a percentage.",
    "model_type_shared": "One response curve per channel, shared across every market. Simple and fast to fit, but can't show that a channel works differently in different markets.",
    "model_type_market_specific": "A separate response curve per channel in each market, allowing information to be shared (partial pooling) so smaller markets borrow strength from larger ones instead of being fitted alone.",
}

# Compact glossary of modelling/planning terms.
GLOSSARY = {
    "Adstock": "How the effect of media spend carries over and decays in the weeks after it occurs.",
    "Saturation": "How each extra unit of spend produces a smaller incremental effect as spend increases.",
    "Partial pooling": "Segments or markets share information with each other, borrowing strength where data is thin.",
    "Posterior": "The updated distribution of a parameter's plausible values after the model has seen the data.",
    "Prior": "The model's starting assumption about a parameter's plausible values before seeing the data.",
    "Response curve": "The relationship between spend on a channel and its modelled effect.",
    "Contribution": "The modelled portion of an outcome attributed to a specific channel or driver.",
    "Incremental outcome": "The extra outcome caused by spend, over and above what would have happened anyway.",
    "Scenario": "A specific spend plan and its predicted outcomes, saved for comparison.",
    "Constraint": "A rule the optimiser must respect when proposing a spend plan, e.g. a locked cell or spend floor.",
    "Approval": "A reviewer's sign-off on a specific fitted model, required before it can be used for planning.",
    "Curve Bank": "A versioned store of an approved model's fitted parameter snapshots (Hill/decay/beta point estimates) for calibration tracking and evidence-tier display; parameter snapshots, never presented as official response curves.",
    "Market-specific curve": "A response curve estimated separately for one market, rather than shared across all markets.",
    "Shrinkage": "How far a market's estimate is pulled toward the shared distribution - larger in weak-data markets, smaller in strong-data markets.",
    "Model comparison": "Fitting more than one candidate model structure and comparing their diagnostics before choosing which to trust.",
}
