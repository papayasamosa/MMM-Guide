"""Data preprocessing utilities for MMM."""

import pandas as pd
import numpy as np
from typing import List, Optional, Tuple, Dict, Any

from ancestry_mmm.core.schema import ModelSpec


def prepare_data_for_modeling(
    df: pd.DataFrame,
    date_col: str,
    target_col: str,
    media_cols: List[str],
    control_cols: Optional[List[str]] = None,
    aggregation: str = "Weekly",
    segment_col: Optional[str] = None,
    segment_value: Optional[str] = None,
) -> Tuple[pd.DataFrame, dict]:
    """
    Prepare data for MMM modeling.

    Args:
        df: Raw DataFrame
        date_col: Name of date column
        target_col: Name of target/KPI column
        media_cols: List of media spend column names
        control_cols: Optional list of control variable columns
        aggregation: Aggregation level ('Daily', 'Weekly', 'Monthly')
        segment_col: Optional column for filtering by segment
        segment_value: Value to filter segment by

    Returns:
        Tuple of (prepared_df, metadata_dict)
    """
    control_cols = control_cols or []

    # Make a copy to avoid modifying original
    data = df.copy()

    # Filter by segment if specified
    if segment_col and segment_value:
        data = data[data[segment_col] == segment_value].copy()

    # Parse dates
    data[date_col] = pd.to_datetime(data[date_col])
    data = data.sort_values(date_col).reset_index(drop=True)

    # Select columns
    all_cols = [date_col, target_col] + media_cols + control_cols
    data = data[all_cols].copy()

    # Handle missing values
    data = data.dropna()

    # Aggregate if needed
    if aggregation == "Weekly":
        data['period'] = data[date_col].dt.to_period('W').dt.start_time
        numeric_cols = [target_col] + media_cols + control_cols
        data = data.groupby('period')[numeric_cols].sum().reset_index()
        data = data.rename(columns={'period': date_col})
    elif aggregation == "Monthly":
        data['period'] = data[date_col].dt.to_period('M').dt.start_time
        numeric_cols = [target_col] + media_cols + control_cols
        data = data.groupby('period')[numeric_cols].sum().reset_index()
        data = data.rename(columns={'period': date_col})

    # Add time index
    data['time_index'] = np.arange(len(data))

    # Calculate metadata
    metadata = {
        'n_observations': len(data),
        'n_media_channels': len(media_cols),
        'date_range': (data[date_col].min(), data[date_col].max()),
        'aggregation': aggregation,
        'media_columns': media_cols,
        'control_columns': control_cols,
        'target_column': target_col,
        'date_column': date_col,
    }

    # Calculate summary statistics for scaling
    metadata['target_mean'] = data[target_col].mean()
    metadata['target_std'] = data[target_col].std()
    metadata['media_means'] = {col: data[col].mean() for col in media_cols}
    metadata['media_stds'] = {col: data[col].std() for col in media_cols}

    return data, metadata


def create_fourier_features(
    n_periods: int,
    period: int = 52,
    n_harmonics: int = 3,
) -> np.ndarray:
    """
    Create Fourier features for seasonality modeling.

    Args:
        n_periods: Number of time periods
        period: Seasonality period (e.g., 52 for weekly data with annual seasonality)
        n_harmonics: Number of Fourier harmonics to include

    Returns:
        Array of shape (n_periods, 2 * n_harmonics) with sin/cos features
    """
    t = np.arange(n_periods)
    features = []

    for k in range(1, n_harmonics + 1):
        features.append(np.sin(2 * np.pi * k * t / period))
        features.append(np.cos(2 * np.pi * k * t / period))

    return np.column_stack(features)


def create_trend_feature(n_periods: int, normalize: bool = True) -> np.ndarray:
    """
    Create a trend feature.

    Args:
        n_periods: Number of time periods
        normalize: Whether to normalize to [0, 1] range

    Returns:
        Array of shape (n_periods,) with trend values
    """
    trend = np.arange(n_periods, dtype=float)
    if normalize:
        trend = trend / (n_periods - 1)
    return trend


def compute_correlation_matrix(
    df: pd.DataFrame,
    columns: List[str],
) -> pd.DataFrame:
    """
    Compute correlation matrix for specified columns.

    Args:
        df: DataFrame
        columns: Columns to include in correlation matrix

    Returns:
        Correlation matrix as DataFrame
    """
    return df[columns].corr()


def detect_outliers(
    df: pd.DataFrame,
    column: str,
    method: str = "iqr",
    threshold: float = 1.5,
) -> pd.Series:
    """
    Detect outliers in a column.

    Args:
        df: DataFrame
        column: Column to check for outliers
        method: Detection method ('iqr' or 'zscore')
        threshold: Threshold for outlier detection

    Returns:
        Boolean Series indicating outlier rows
    """
    values = df[column]

    if method == "iqr":
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
        return (values < lower) | (values > upper)

    elif method == "zscore":
        z_scores = np.abs((values - values.mean()) / values.std())
        return z_scores > threshold

    else:
        raise ValueError(f"Unknown method: {method}")


def create_fourier_features_from_calendar(
    dates: pd.Series,
    period_days: float = 365.25,
    n_harmonics: int = 3,
) -> np.ndarray:
    """
    Calendar-anchored Fourier seasonality features (day-of-year based).

    Unlike a row-position Fourier basis, this stays aligned to actual
    calendar weeks (Christmas, DNA Day, Mother's/Father's Day, ...) even
    when markets have different start dates or series lengths - which
    matters once UK/Australia/Canada are modelled jointly.
    """
    doy = pd.to_datetime(dates).dt.dayofyear.to_numpy(dtype=float)
    features = []
    for k in range(1, n_harmonics + 1):
        features.append(np.sin(2 * np.pi * k * doy / period_days))
        features.append(np.cos(2 * np.pi * k * doy / period_days))
    return np.column_stack(features)


def prepare_fh_modeling_frame(
    df: pd.DataFrame, spec: ModelSpec, dna_kit_outcomes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Turn a joined, transformed DataFrame + ModelSpec into the arrays the
    joint hierarchical FH model needs: per-market index, media matrix,
    segment outcome matrix, promo matrix, controls and calendar-anchored
    seasonality/trend features.

    `dna_kit_outcomes` (segment key -> outcome column, same shape as
    `spec.segment_outcomes`) optionally adds DNA-product kit-sale segments
    (core.outcomes) to the fit alongside the Family History segments -
    `ModelSpec.segment_outcomes` itself is untouched, so a project with no
    DNA outcomes mapped behaves identically to before. Promo/segment-control
    mapping for a DNA kit segment reuses `spec.promo_cols`/
    `spec.segment_control_cols` exactly as for an FH segment - both are
    already keyed by segment name generically, not FH-specific.
    """
    errors = spec.validate()
    if errors:
        raise ValueError("Invalid model spec: " + "; ".join(errors))

    data = df.copy()
    data[spec.date_col] = pd.to_datetime(data[spec.date_col])

    markets_filter = spec.markets or sorted(data[spec.market_col].dropna().unique().tolist())
    data = data[data[spec.market_col].isin(markets_filter)].copy()
    data = data.sort_values([spec.market_col, spec.date_col]).reset_index(drop=True)

    # Re-derive market order from the sorted rows themselves (not spec.markets'
    # input order) so `market_bounds` below is guaranteed to describe contiguous
    # blocks in the same order the DataFrame is actually laid out in - the
    # per-market adstock scan in the model builder slices on these bounds.
    markets = data[spec.market_col].unique().tolist()
    market_to_idx = {m: i for i, m in enumerate(markets)}
    market_idx = data[spec.market_col].map(market_to_idx).to_numpy()

    market_bounds = []
    offset = 0
    for m in markets:
        n = int((data[spec.market_col] == m).sum())
        market_bounds.append((offset, offset + n))
        offset += n

    missing_channels = [c for c in spec.channels if c not in data.columns]
    if missing_channels:
        raise ValueError(f"Channel columns missing from data: {missing_channels}")
    X_media = data[spec.channels].to_numpy(dtype=float)

    dna_kit_outcomes = dna_kit_outcomes or {}
    colliding = set(spec.segment_outcomes) & set(dna_kit_outcomes)
    if colliding:
        raise ValueError(f"dna_kit_outcomes segment key(s) collide with existing FH segments: {sorted(colliding)}")
    outcome_cols = {**spec.segment_outcomes, **dna_kit_outcomes}
    segments = list(spec.segment_outcomes.keys()) + list(dna_kit_outcomes.keys())
    missing_outcomes = [c for c in outcome_cols.values() if c not in data.columns]
    if missing_outcomes:
        raise ValueError(f"Segment outcome columns missing from data: {missing_outcomes}")
    Y = data[[outcome_cols[s] for s in segments]].to_numpy(dtype=float)

    promo = np.zeros((len(data), len(segments)))
    for i, seg in enumerate(segments):
        col = spec.promo_cols.get(seg)
        if col and col in data.columns:
            promo[:, i] = data[col].to_numpy(dtype=float)

    control_cols = [c for c in spec.control_cols if c in data.columns]
    X_controls = data[control_cols].to_numpy(dtype=float) if control_cols else np.zeros((len(data), 0))

    segment_controls: Dict[str, np.ndarray] = {}
    segment_control_names: Dict[str, List[str]] = {}
    for seg, cols in (spec.segment_control_cols or {}).items():
        present = [c for c in cols if c in data.columns]
        if present:
            segment_controls[seg] = data[present].to_numpy(dtype=float)
            segment_control_names[seg] = present

    fourier = create_fourier_features_from_calendar(
        data[spec.date_col], n_harmonics=spec.fourier_harmonics
    )

    trend = np.zeros(len(data))
    for m in markets:
        mask = (data[spec.market_col] == m).to_numpy()
        n = int(mask.sum())
        if n > 0:
            trend[mask] = np.arange(n) / max(n - 1, 1)

    dna_channel_idx = [spec.channels.index(c) for c in spec.dna_channels if c in spec.channels]

    return {
        "df": data,
        "dates": data[spec.date_col].to_numpy(),
        "markets": markets,
        "market_idx": market_idx,
        "market_bounds": market_bounds,
        "channels": spec.channels,
        "dna_channel_idx": dna_channel_idx,
        "segments": segments,
        "X_media": X_media,
        "Y": Y,
        "promo": promo,
        "X_controls": X_controls,
        "control_names": control_cols,
        "segment_controls": segment_controls,
        "segment_control_names": segment_control_names,
        "fourier": fourier,
        "trend": trend,
        "unpooled_markets": spec.unpooled_markets,
    }
