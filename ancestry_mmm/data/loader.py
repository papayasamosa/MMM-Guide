"""Data loading and validation utilities."""

import warnings
from datetime import datetime, timezone

import pandas as pd
from pathlib import Path
from typing import Iterable, Optional, Tuple, List, Dict, Any

from ancestry_mmm.core.coverage import SourceVersion, compute_checksum
from ancestry_mmm.data.templates import StandardWorkbook, parse_standard_workbook
from ancestry_mmm.sample_data.realistic_source_pack import build_realistic_source_pack


def load_file(uploaded_file) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
    """
    Load a CSV, Excel (.xlsx/.xls/.xlsm), or Parquet file into a DataFrame.

    Returns:
        Tuple of (DataFrame, error_message). If successful, error_message is None.
    """
    try:
        filename = uploaded_file.name.lower()

        if filename.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif filename.endswith((".xlsx", ".xls", ".xlsm")):
            workbook = pd.ExcelFile(uploaded_file)
            if len(workbook.sheet_names) > 1:
                return (
                    None,
                    "Excel workbook contains multiple sheets. Use the standard "
                    "workbook loader or explicitly choose the generic first-sheet "
                    "path; sheets must not be combined silently.",
                )
            df = pd.read_excel(workbook, sheet_name=workbook.sheet_names[0])
        elif filename.endswith(".parquet"):
            df = pd.read_parquet(uploaded_file)
        else:
            return None, f"Unsupported file format: {filename}"

        if df.empty:
            return None, "The uploaded file is empty."

        return df, None

    except Exception as e:
        return None, f"Error loading file: {str(e)}"


def load_file_with_source_version(
    uploaded_file,
    source_id: str,
    existing_versions: Optional[Iterable[SourceVersion]] = None,
) -> Tuple[Optional[pd.DataFrame], Optional[SourceVersion], Optional[str]]:
    """REQ-COVERAGE-001 S3: capture an immutable `SourceVersion` alongside
    the parsed `DataFrame` from a real upload, from a sha256 checksum of the
    raw uploaded bytes - never the parsed representation treated as if it
    were the original file.

    `uploaded_file` must expose `.name` (used by `load_file` for format
    detection) and `.getvalue()` returning the complete raw bytes without
    consuming/moving whatever read position a subsequent parse uses -
    Streamlit's `UploadedFile` (an `io.BytesIO` subclass) and a plain
    `io.BytesIO` both satisfy this; `.getvalue()` is called before
    `load_file` parses the same object, so parsing always sees the file
    from its start regardless of call order.

    `existing_versions` is this `source_id`'s already-known version history
    (e.g. from session state) - `version` is `max(existing) + 1`, or `1` for
    a genuinely new source_id. This function does not persist anything
    itself; the caller is responsible for storing the returned
    `SourceVersion` (e.g. appending it to session state / a project
    bundle).

    Returns `(None, None, error)` if `load_file` itself fails - no
    `SourceVersion` is fabricated for a file that failed to parse.
    """
    raw_bytes = uploaded_file.getvalue()
    df, err = load_file(uploaded_file)
    if err:
        return None, None, err

    current_for_source = [
        v for v in (existing_versions or ()) if v.source_id == source_id
    ]
    next_version = max((v.version for v in current_for_source), default=0) + 1

    source_version = SourceVersion(
        source_id=source_id,
        version=next_version,
        original_filename=uploaded_file.name,
        checksum=compute_checksum(raw_bytes),
        size_bytes=len(raw_bytes),
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        parsed_representation_version=f"pandas-{pd.__version__}",
    )
    return df, source_version, None


def load_standard_workbook_with_source_version(
    uploaded_file,
    source_id: str,
    logical_domain: Optional[str] = None,
    existing_versions: Optional[Iterable[SourceVersion]] = None,
) -> Tuple[Optional[StandardWorkbook], Optional[SourceVersion], Optional[str]]:
    """Parse an Excel source pack and capture workbook-level provenance.

    The parser reads every sheet and returns a manifest even when standard
    validation fails. Validation diagnostics therefore remain inspectable by
    the caller, while an unreadable workbook produces no fabricated upload
    version. Generic Excel workbooks are returned with an explicit warning so
    the UI can offer the existing generic-source path without silently
    pretending that the workbook is a governed standard pack.
    """
    filename = str(uploaded_file.name)
    if not filename.lower().endswith((".xlsx", ".xls", ".xlsm")):
        return None, None, "Standard source-pack parsing requires an Excel workbook."

    raw_bytes = uploaded_file.getvalue()
    workbook = parse_standard_workbook(
        raw_bytes,
        source_id=source_id,
        filename=filename,
        logical_domain=logical_domain,
    )
    if not workbook.manifest.sheet_names and workbook.manifest.errors:
        return None, None, "; ".join(workbook.manifest.errors)

    current_for_source = [
        version
        for version in (existing_versions or ())
        if version.source_id == source_id
    ]
    next_version = (
        max((version.version for version in current_for_source), default=0) + 1
    )
    source_version = SourceVersion(
        source_id=source_id,
        version=next_version,
        original_filename=filename,
        checksum=compute_checksum(raw_bytes),
        size_bytes=len(raw_bytes),
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        parsed_representation_version=f"pandas-{pd.__version__}",
        template_schema_version=workbook.manifest.template_schema_version,
        standard_template=workbook.manifest.standard_template,
        parsed_table_ids=workbook.manifest.table_ids,
        workbook_sheet_names=workbook.manifest.sheet_names,
        template_warnings=workbook.manifest.warnings,
        template_errors=workbook.manifest.errors,
    )
    return workbook, source_version, None


SAMPLE_DATA_DIR = Path(__file__).parent.parent / "sample_data"

SAMPLE_SOURCES = {
    "media": SAMPLE_DATA_DIR / "ancestry_media_sample.csv",
    "outcomes": SAMPLE_DATA_DIR / "ancestry_outcomes_sample.csv",
    "controls": SAMPLE_DATA_DIR / "ancestry_controls_sample.csv",
    "ltv": SAMPLE_DATA_DIR / "ancestry_segment_ltv_sample.csv",
}


def load_sample_data(
    sample_name: str = "media",
) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
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


def load_realistic_sample_sources() -> Tuple[Dict[str, pd.DataFrame], Optional[str]]:
    """Load the deterministic source-native demo pack.

    Unlike :func:`load_all_sample_sources`, this deliberately returns separate
    tidy activity, dictionary, outcome, context, and event tables.  It is an
    ingestion/source-contract fixture, not a pre-joined model matrix.
    """

    try:
        return build_realistic_source_pack(), None
    except Exception as exc:
        return {}, f"Error building realistic sample data: {exc}"


def detect_column_types(df: pd.DataFrame) -> Dict[str, List[str]]:
    """
    Auto-detect column types based on content and naming patterns.

    Returns:
        Dictionary with keys: 'date', 'numeric', 'categorical', 'potential_target', 'potential_media'
    """
    date_hints = ["date", "week", "month", "day", "time", "period"]
    target_hints = [
        "gsa",
        "sign",
        "signup",
        "subscri",
        "sales",
        "revenue",
        "conversions",
        "kpi",
        "target",
        "y",
        "outcome",
    ]
    spend_hints = ["spend", "cost", "budget", "investment", "media", "channel", "ad"]
    market_hints = ["market", "geo", "region", "country"]
    dna_hints = ["dna"]
    promo_hints = ["promo", "discount", "offer"]

    result: Dict[str, List[str]] = {
        "date": [],
        "numeric": [],
        "categorical": [],
        "potential_target": [],
        "potential_media": [],
        "potential_market": [],
        "potential_dna": [],
        "potential_promo": [],
    }

    for col in df.columns:
        col_lower = col.lower()

        # Check for date columns. is_string_dtype covers both the legacy
        # numpy "object" dtype and pandas' newer default StringDtype (e.g.
        # pandas>=3's read_csv no longer returns "object" for text columns -
        # a plain dtype=="object" check silently misses them). The explicit
        # dtype == "object" check is kept alongside it: is_string_dtype
        # inspects content and returns False for object-dtype columns that
        # hold real date/Timestamp objects rather than strings, which would
        # otherwise skip the pd.to_datetime attempt entirely.
        if pd.api.types.is_string_dtype(df[col]) or df[col].dtype == "object":
            try:
                # This probe deliberately has no fixed format - arbitrary
                # uploaded columns can use any date format, and forcing one
                # would break detection of legitimate columns using a
                # different one. pandas' "falling back to dateutil" notice
                # is therefore expected here specifically, not a sign of a
                # genuinely ambiguous/inconsistent format worth surfacing -
                # suppressed only around this exact call, not repo-wide, so
                # the same warning from any other, non-probing conversion
                # path still surfaces normally.
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message="Could not infer format",
                        category=UserWarning,
                    )
                    pd.to_datetime(df[col])
                result["date"].append(col)
                continue
            except (ValueError, TypeError):
                pass

        if pd.api.types.is_datetime64_any_dtype(df[col]):
            result["date"].append(col)
            continue

        if any(hint in col_lower for hint in date_hints):
            result["date"].append(col)
            continue

        # Check for numeric columns
        if pd.api.types.is_numeric_dtype(df[col]):
            result["numeric"].append(col)

            # Check if it might be a target variable
            if any(hint in col_lower for hint in target_hints):
                result["potential_target"].append(col)

            # Check if it might be a media spend variable
            elif any(hint in col_lower for hint in spend_hints):
                result["potential_media"].append(col)

            if any(hint in col_lower for hint in dna_hints):
                result["potential_dna"].append(col)
            if any(hint in col_lower for hint in promo_hints):
                result["potential_promo"].append(col)

        # Categorical columns
        elif pd.api.types.is_string_dtype(df[col]) or isinstance(
            df[col].dtype, pd.CategoricalDtype
        ):
            result["categorical"].append(col)
            if any(hint in col_lower for hint in market_hints):
                result["potential_market"].append(col)

    return result


def validate_data(
    df: pd.DataFrame, date_col: str, target_col: str, media_cols: List[str]
) -> List[str]:
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
        warnings.append(
            f"Only {len(df)} data points. Recommend at least 52 for weekly data."
        )

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
        "rows": len(df),
        "columns": len(df.columns),
        "memory_mb": df.memory_usage(deep=True).sum() / 1024 / 1024,
        "column_types": df.dtypes.value_counts().to_dict(),
        "missing_values": df.isna().sum().sum(),
        "missing_pct": df.isna().sum().sum() / (len(df) * len(df.columns)) * 100,
    }

    # Try to detect date range
    for col in df.columns:
        try:
            dates = pd.to_datetime(df[col])
            summary["date_range"] = {
                "start": dates.min().strftime("%Y-%m-%d"),
                "end": dates.max().strftime("%Y-%m-%d"),
                "column": col,
            }
            break
        except (ValueError, TypeError):
            continue

    return summary
