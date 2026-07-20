"""Data loading and validation utilities."""

import pandas as pd
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any


def load_file(uploaded_file) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Load a CSV or Excel file into a DataFrame.

    Returns:
        Tuple of (DataFrame, error_message). If successful, error_message is None.
    """
    try:
        filename = uploaded_file.name.lower()

        if filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        elif filename.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        else:
            return None, f"Unsupported file format: {filename}"

        if df.empty:
            return None, "The uploaded file is empty."

        return df, None

    except Exception as e:
        return None, f"Error loading file: {str(e)}"


SAMPLE_DATA_DIR = Path(__file__).parent.parent / "sample_data"

SAMPLE_SOURCES = {
    "media": SAMPLE_DATA_DIR / "ancestry_media_sample.csv",
    "outcomes": SAMPLE_DATA_DIR / "ancestry_outcomes_sample.csv",
    "controls": SAMPLE_DATA_DIR / "ancestry_controls_sample.csv",
    "ltv": SAMPLE_DATA_DIR / "ancestry_segment_ltv_sample.csv",
}


def load_sample_data(sample_name: str = "media") -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Load a synthetic Ancestry FH sample source ("media", "outcomes", "controls" or "ltv").

    These are synthetic demo files (see ancestry_mmm/sample_data/generate_sample_data.py),
    not real Ancestry data - they exist so the tool is runnable end-to-end before real
    data is connected.

    Returns:
        Tuple of (DataFrame, error_message).
    """
    try:
        if sample_name not in SAMPLE_SOURCES:
            return None, f"Unknown sample dataset: {sample_name}"

        file_path = SAMPLE_SOURCES[sample_name]
        if not file_path.exists():
            return None, f"Sample data file not found: {file_path}"

        df = pd.read_csv(file_path)
        return df, None

    except Exception as e:
        return None, f"Error loading sample data: {str(e)}"


def load_all_sample_sources() -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Load all synthetic sample sources (media, outcomes, controls, ltv) at once."""
    frames = {}
    for name in SAMPLE_SOURCES:
        df, err = load_sample_data(name)
        if err:
            return {}, err
        frames[name] = df
    return frames, None


def detect_column_types(df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Auto-detect column types based on content and naming patterns.

    Returns:
        Dictionary with keys: 'date', 'numeric', 'categorical', 'potential_target', 'potential_media'
    """
    date_hints = ['date', 'week', 'month', 'day', 'time', 'period']
    target_hints = ['gsa', 'sign', 'signup', 'subscri', 'sales', 'revenue', 'conversions', 'kpi', 'target', 'y', 'outcome']
    spend_hints = ['spend', 'cost', 'budget', 'investment', 'media', 'channel', 'ad']
    market_hints = ['market', 'geo', 'region', 'country']
    dna_hints = ['dna']
    promo_hints = ['promo', 'discount', 'offer']

    result = {
        'date': [],
        'numeric': [],
        'categorical': [],
        'potential_target': [],
        'potential_media': [],
        'potential_market': [],
        'potential_dna': [],
        'potential_promo': [],
    }

    for col in df.columns:
        col_lower = col.lower()

        # Check for date columns
        if df[col].dtype == 'object':
            try:
                pd.to_datetime(df[col])
                result['date'].append(col)
                continue
            except (ValueError, TypeError):
                pass

        if pd.api.types.is_datetime64_any_dtype(df[col]):
            result['date'].append(col)
            continue

        if any(hint in col_lower for hint in date_hints):
            result['date'].append(col)
            continue

        # Check for numeric columns
        if pd.api.types.is_numeric_dtype(df[col]):
            result['numeric'].append(col)

            # Check if it might be a target variable
            if any(hint in col_lower for hint in target_hints):
                result['potential_target'].append(col)

            # Check if it might be a media spend variable
            elif any(hint in col_lower for hint in spend_hints):
                result['potential_media'].append(col)

            if any(hint in col_lower for hint in dna_hints):
                result['potential_dna'].append(col)
            if any(hint in col_lower for hint in promo_hints):
                result['potential_promo'].append(col)

        # Categorical columns
        elif df[col].dtype == 'object' or pd.api.types.is_categorical_dtype(df[col]):
            result['categorical'].append(col)
            if any(hint in col_lower for hint in market_hints):
                result['potential_market'].append(col)

    return result


def validate_data(df: pd.DataFrame, date_col: str, target_col: str,
                  media_cols: List[str]) -> List[str]:
    """
    Validate data for MMM modeling.

    Returns:
        List of validation warnings/errors.
    """
    warnings = []

    # Check for missing values
    for col in [date_col, target_col] + media_cols:
        if col in df.columns:
            missing_pct = df[col].isna().sum() / len(df) * 100
            if missing_pct > 0:
                warnings.append(f"Column '{col}' has {missing_pct:.1f}% missing values")

    # Check for negative values in target and media columns
    if target_col in df.columns and (df[target_col] < 0).any():
        warnings.append(f"Target column '{target_col}' contains negative values")

    for col in media_cols:
        if col in df.columns and (df[col] < 0).any():
            warnings.append(f"Media column '{col}' contains negative values")

    # Check for sufficient data points
    if len(df) < 52:
        warnings.append(f"Only {len(df)} data points. Recommend at least 52 for weekly data.")

    # Check for date continuity
    if date_col in df.columns:
        try:
            dates = pd.to_datetime(df[date_col])
            date_diff = dates.diff().dropna()
            if date_diff.nunique() > 1:
                warnings.append("Irregular time intervals detected in date column")
        except (ValueError, TypeError):
            warnings.append(f"Could not parse dates in column '{date_col}'")

    return warnings


def get_data_summary(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Generate a summary of the dataset.

    Returns:
        Dictionary with summary statistics.
    """
    summary = {
        'rows': len(df),
        'columns': len(df.columns),
        'memory_mb': df.memory_usage(deep=True).sum() / 1024 / 1024,
        'column_types': df.dtypes.value_counts().to_dict(),
        'missing_values': df.isna().sum().sum(),
        'missing_pct': df.isna().sum().sum() / (len(df) * len(df.columns)) * 100,
    }

    # Try to detect date range
    for col in df.columns:
        try:
            dates = pd.to_datetime(df[col])
            summary['date_range'] = {
                'start': dates.min().strftime('%Y-%m-%d'),
                'end': dates.max().strftime('%Y-%m-%d'),
                'column': col,
            }
            break
        except (ValueError, TypeError):
            continue

    return summary
