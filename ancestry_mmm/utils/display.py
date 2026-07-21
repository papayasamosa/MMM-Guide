"""Display-only formatting helpers: dates, numbers, readable labels and
dataframe column configuration. These never change underlying values or
dtypes - they only control how a value or dataframe is *shown*, so callers
must keep using the raw dataframe/values for joins, filters, transforms,
modelling and exports.
"""

from typing import Any, Dict, Iterable, Optional

import pandas as pd
import streamlit as st

# MomentJS-style format string understood natively by st.column_config.DateColumn:
# "D" = day of month, no leading zero; "MMM" = short month name; "YY" = 2-digit
# year. Confirmed empirically against a live Streamlit 1.59 DateColumn - the
# lowercase "yy" variant is NOT recognised and silently falls back to a
# 4-digit year, so the year token must be uppercase here even though the day
# token works either way.
DATE_COLUMN_FORMAT = "D MMM YY"


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
    return name.replace("_", " ")


def readable_labels(names: Iterable[str]) -> Dict[str, str]:
    """Map each technical name to its readable label."""
    return {name: readable_label(name) for name in names}


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
            config[col] = st.column_config.DateColumn(label=label, format=DATE_COLUMN_FORMAT)
        elif pd.api.types.is_bool_dtype(dtype):
            config[col] = st.column_config.CheckboxColumn(label=label)
        elif pd.api.types.is_numeric_dtype(dtype):
            config[col] = st.column_config.NumberColumn(label=label, format=numeric_format, alignment="right")
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
    "curve_bank": "The curve bank stores a versioned, traceable snapshot of an approved model's response curves and segment parameters.",
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
    "Curve Bank": "A versioned store of an approved model's response curves and segment parameters.",
    "Market-specific curve": "A response curve estimated separately for one market, rather than shared across all markets.",
    "Shrinkage": "How far a market's estimate is pulled toward the shared distribution - larger in weak-data markets, smaller in strong-data markets.",
    "Model comparison": "Fitting more than one candidate model structure and comparing their diagnostics before choosing which to trust.",
}
