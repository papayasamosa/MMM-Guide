"""Data preprocessing utilities for MMM."""

import pandas as pd
import numpy as np
from typing import List, Optional, Tuple, Dict, Any

from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.outcomes import OutcomeDefinition, included_outcomes, resolve_outcome_definitions
from ancestry_mmm.core.net_billthrough import (
    NBT_METRIC_KEY, NetBillthroughCompletenessMetadata,
    assert_supplied_net_billthrough_complete,
)


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
    df: pd.DataFrame,
    spec: ModelSpec,
    outcomes: Optional[List[OutcomeDefinition]] = None,
    media_outcome_pathways: Optional[List[Any]] = None,
    net_billthrough_metadata: Optional[NetBillthroughCompletenessMetadata | dict] = None,
) -> Dict[str, Any]:
    """
    Turn a joined, transformed DataFrame + ModelSpec into the arrays the
    joint hierarchical FH model needs: per-market index, media matrix,
    outcome matrix, promo matrix, controls and calendar-anchored
    seasonality/trend features.

    `outcomes` (the canonical `List[OutcomeDefinition]` - see core.outcomes)
    is this fit's structural input: the model's identity dimension is
    `outcome_id`, not segment, so two outcomes can share a `segment` (e.g. a
    Family History sign-up and a Family History GSA both on segment "New")
    and still get independent response curves. Only
    `included_outcomes(outcomes)` (`included_in_fit=True`) actually reach
    the frame - the rest stay in the catalogue but are excluded from this
    fit. If `outcomes` is omitted, it's derived from
    `spec.segment_outcomes`/`spec.segment_ltv` via `resolve_outcome_definitions`
    (FH-only, matching every fit's behaviour before this schema existed) -
    `ModelSpec.segment_outcomes` itself is untouched either way, it is now
    purely a migration source.

    Promo/control mapping resolution (PR E.2 - outcome_id is now the primary
    key, not segment): for each outcome_id, the promo column is
    `spec.outcome_promo_cols[outcome_id]` if set, else the legacy
    `spec.promo_cols[segment]` - so a sign-up and a GSA sharing a segment can
    have genuinely different promo mappings once configured explicitly, but
    a migrated/legacy project's segment-level mapping still applies to both
    until then. Controls are additive across four levels: global
    (`spec.control_cols`, every outcome), product-level
    (`spec.product_control_cols[product]`), legacy segment-level
    (`spec.segment_control_cols[segment]`), and outcome-level
    (`spec.outcome_control_cols[outcome_id]`) - deduplicated, order
    preserved.

    `media_outcome_pathways` (PR F, `List[core.pathways.MediaOutcomePathway]`)
    is pure pass-through metadata - it does not affect any array this
    function builds. It is threaded through purely so the model builders
    (`core.hierarchical_model.build_fh_hierarchical_model`,
    `core.market_specific_model.build_fh_market_specific_model`) can capture
    it onto `FHModelMeta.pathway_catalogue_at_fit` for drift detection
    (`core.pathways.pathway_drift_status`), the same way this function
    doesn't otherwise interpret `outcomes` beyond selecting/filtering it.
    """
    explicit_outcomes = outcomes is not None
    errors = spec.validate()
    if explicit_outcomes:
        # `spec.validate()`'s "at least one FH segment outcome column"
        # check is about `spec.segment_outcomes` specifically, which is now
        # only a migration source (core.outcomes) - an explicit outcome
        # catalogue with no FH entries in `segment_outcomes` (e.g. every
        # outcome captured as a custom sign-up/GSA pair, not through the
        # legacy segment_outcomes shape) is not itself invalid; the "at
        # least one outcome is actually being fit" requirement is enforced
        # below against the catalogue that was actually passed in instead.
        errors = [e for e in errors if "FH segment outcome column" not in e]
    if errors:
        raise ValueError("Invalid model spec: " + "; ".join(errors))

    if outcomes is None:
        outcomes = resolve_outcome_definitions(None, spec.segment_outcomes, spec.segment_ltv)
    fit_outcomes = included_outcomes(outcomes)
    if not fit_outcomes:
        raise ValueError("No outcomes are included in the fit - check included_in_fit on the outcome catalogue.")

    outcome_ids = [o.outcome_id for o in fit_outcomes]
    if len(set(outcome_ids)) != len(outcome_ids):
        raise ValueError(f"Duplicate outcome_id(s) among the outcomes included in the fit: {outcome_ids}")
    outcome_id_to_segment = {o.outcome_id: o.segment for o in fit_outcomes}
    outcome_id_to_product = {o.outcome_id: o.product for o in fit_outcomes}
    outcome_source_columns = {o.outcome_id: o.source_column for o in fit_outcomes}

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

    nbt_outcomes = [o for o in fit_outcomes if o.metric_key == NBT_METRIC_KEY]
    if nbt_outcomes:
        metadata = (
            NetBillthroughCompletenessMetadata.from_dict(net_billthrough_metadata)
            if isinstance(net_billthrough_metadata, dict)
            else net_billthrough_metadata
        )
        is_long_nbt = (
            "segment" in data.columns
            and NBT_METRIC_KEY in data.columns
            and data.duplicated([spec.market_col, spec.date_col], keep=False).any()
        )
        if is_long_nbt:
            assert_supplied_net_billthrough_complete(
                data,
                metadata,
                configured_markets=markets,
                configured_segments=[o.segment for o in nbt_outcomes],
                week_column=spec.date_col,
                market_column=spec.market_col,
            )
            keys = [spec.market_col, spec.date_col]
            base = data.drop(columns=["segment", NBT_METRIC_KEY]).groupby(
                keys, as_index=False
            ).first()
            for outcome in nbt_outcomes:
                column = f"__nbt_{outcome.outcome_id}"
                values = data[data["segment"].astype(str) == str(outcome.segment)][
                    keys + [NBT_METRIC_KEY]
                ].rename(columns={NBT_METRIC_KEY: column})
                base = base.merge(values, on=keys, how="left", validate="one_to_one")
                outcome_source_columns[outcome.outcome_id] = column
            data = base.sort_values(keys).reset_index(drop=True)
            markets = data[spec.market_col].unique().tolist()
            market_to_idx = {market: i for i, market in enumerate(markets)}
            market_idx = data[spec.market_col].map(market_to_idx).to_numpy()
            market_bounds = []
            offset = 0
            for market in markets:
                count = int((data[spec.market_col] == market).sum())
                market_bounds.append((offset, offset + count))
                offset += count
        else:
            configured = [
                {
                    "metric_key": o.metric_key,
                    "source_column": o.source_column,
                    "segment": o.segment,
                    "markets": markets,
                }
                for o in nbt_outcomes
            ]
            assert_supplied_net_billthrough_complete(
                data,
                metadata,
                configured_outcomes=configured,
                week_column=spec.date_col,
                market_column=spec.market_col,
            )
        net_billthrough_metadata = metadata

    missing_channels = [c for c in spec.channels if c not in data.columns]
    if missing_channels:
        raise ValueError(f"Channel columns missing from data: {missing_channels}")
    X_media = data[spec.channels].to_numpy(dtype=float)

    missing_outcomes = [
        outcome_source_columns[o.outcome_id]
        for o in fit_outcomes
        if outcome_source_columns[o.outcome_id] not in data.columns
    ]
    if missing_outcomes:
        raise ValueError(f"Outcome source columns missing from data: {missing_outcomes}")
    Y = data[
        [outcome_source_columns[o.outcome_id] for o in fit_outcomes]
    ].to_numpy(dtype=float)

    promo = np.zeros((len(data), len(outcome_ids)))
    for i, oid in enumerate(outcome_ids):
        # Outcome-id-keyed mapping (PR E.2, canonical) wins when set; the
        # legacy segment-keyed mapping is the fallback for a migrated
        # project that hasn't configured this outcome_id explicitly yet.
        col = (spec.outcome_promo_cols or {}).get(oid) or spec.promo_cols.get(outcome_id_to_segment[oid])
        if col and col in data.columns:
            promo[:, i] = data[col].to_numpy(dtype=float)

    control_cols = [c for c in spec.control_cols if c in data.columns]
    X_controls = data[control_cols].to_numpy(dtype=float) if control_cols else np.zeros((len(data), 0))

    outcome_controls: Dict[str, np.ndarray] = {}
    outcome_control_names: Dict[str, List[str]] = {}
    for oid in outcome_ids:
        # Additive across product-level, legacy segment-level, and
        # outcome-level controls (PR E.2) - deduplicated, order preserved.
        cols = list(dict.fromkeys(
            list((spec.product_control_cols or {}).get(outcome_id_to_product[oid], []))
            + list((spec.segment_control_cols or {}).get(outcome_id_to_segment[oid], []))
            + list((spec.outcome_control_cols or {}).get(oid, []))
        ))
        if not cols:
            continue
        present = [c for c in cols if c in data.columns]
        if present:
            outcome_controls[oid] = data[present].to_numpy(dtype=float)
            outcome_control_names[oid] = present

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
        "outcome_ids": outcome_ids,
        "outcomes": fit_outcomes,
        "X_media": X_media,
        "Y": Y,
        "promo": promo,
        "X_controls": X_controls,
        "control_names": control_cols,
        "outcome_controls": outcome_controls,
        "outcome_control_names": outcome_control_names,
        "fourier": fourier,
        "trend": trend,
        "unpooled_markets": spec.unpooled_markets,
        "media_outcome_pathways": media_outcome_pathways or [],
        "net_billthrough_metadata": net_billthrough_metadata,
    }
