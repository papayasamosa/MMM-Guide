"""
Ordered, auditable, replayable transformation pipeline.

Every transform applied to raw data is recorded as a step (dict) rather
than mutating the DataFrame silently. The same step list can be re-run on
refreshed weekly data (`apply_pipeline`), and is stored as plain JSON so a
non-author can read exactly what was done to the raw data.
"""

from __future__ import annotations

import ast
import operator as _op
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Safe calculated-column expressions
#
# Calculated columns are user-supplied text (e.g. "Search_Brand + Search_NonBrand").
# We do NOT eval()/exec() that text. Instead we parse it with `ast`, walk the
# tree, and only allow arithmetic on existing column names plus a small
# function whitelist - anything else (attribute access, imports, comprehensions,
# subscripts, calls to non-whitelisted names, ...) is rejected before evaluation.
# ---------------------------------------------------------------------------

_ALLOWED_BINOPS = {
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Div: _op.truediv, ast.Pow: _op.pow, ast.Mod: _op.mod,
}
_ALLOWED_UNARYOPS = {ast.USub: _op.neg, ast.UAdd: _op.pos}
_ALLOWED_FUNCS = {
    "log": np.log, "log1p": np.log1p, "exp": np.exp, "sqrt": np.sqrt,
    "abs": np.abs, "min": np.minimum, "max": np.maximum, "clip": np.clip,
}


class UnsafeExpressionError(ValueError):
    pass


def _eval_node(node: ast.AST, columns: Dict[str, pd.Series]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, columns)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise UnsafeExpressionError(f"Constant not allowed: {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id in columns:
            return columns[node.id]
        raise UnsafeExpressionError(f"Unknown column referenced: '{node.id}'")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        return _ALLOWED_BINOPS[type(node.op)](
            _eval_node(node.left, columns), _eval_node(node.right, columns)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARYOPS:
        return _ALLOWED_UNARYOPS[type(node.op)](_eval_node(node.operand, columns))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _ALLOWED_FUNCS:
            raise UnsafeExpressionError("Only whitelisted functions may be called.")
        if node.keywords:
            raise UnsafeExpressionError("Keyword arguments are not allowed.")
        args = [_eval_node(a, columns) for a in node.args]
        return _ALLOWED_FUNCS[node.func.id](*args)
    raise UnsafeExpressionError(f"Expression element not permitted: {type(node).__name__}")


def safe_eval_expression(expr: str, df: pd.DataFrame) -> pd.Series:
    """Evaluate a restricted arithmetic expression against DataFrame columns."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise UnsafeExpressionError(f"Could not parse expression: {e}") from e
    columns = {c: df[c] for c in df.columns}
    result = _eval_node(tree, columns)
    if np.isscalar(result):
        result = pd.Series(result, index=df.index)
    return result


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

SUPPORTED_OPS = [
    "rename_column", "cast_type", "calculated_column", "lag_variable",
    "fill_missing", "drop_columns", "event_flag",
]

# "promotion_event" is intentionally excluded from SUPPORTED_OPS - it is
# only ever produced by `core.promotions.promotion_events_to_transform_steps`
# from a structured `PromotionEvent`, not something an analyst hand-builds
# through the generic Transform Pipeline page's op dropdown.


@dataclass
class TransformStep:
    op: str
    params: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {"op": self.op, "params": self.params, "description": self.description}

    @classmethod
    def from_dict(cls, d: dict) -> "TransformStep":
        return cls(op=d["op"], params=d.get("params", {}), description=d.get("description", ""))


def apply_step(df: pd.DataFrame, step: TransformStep) -> pd.DataFrame:
    df = df.copy()
    p = step.params

    if step.op == "rename_column":
        df = df.rename(columns={p["old"]: p["new"]})

    elif step.op == "cast_type":
        col, dtype = p["column"], p["dtype"]
        if dtype == "datetime":
            df[col] = pd.to_datetime(df[col])
        elif dtype == "float":
            df[col] = pd.to_numeric(df[col], errors="coerce")
        elif dtype == "int":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
        elif dtype == "category":
            df[col] = df[col].astype("category")
        else:
            raise ValueError(f"Unsupported dtype: {dtype}")

    elif step.op == "calculated_column":
        df[p["new_column"]] = safe_eval_expression(p["expression"], df)

    elif step.op == "lag_variable":
        group_col = p.get("group_col")
        col, new_col, periods = p["column"], p["new_column"], p["periods"]
        if group_col and group_col in df.columns:
            df[new_col] = df.groupby(group_col)[col].shift(periods)
        else:
            df[new_col] = df[col].shift(periods)

    elif step.op == "fill_missing":
        col, strategy = p["column"], p["strategy"]
        group_col = p.get("group_col")
        if strategy == "zero":
            df[col] = df[col].fillna(0)
        elif strategy == "mean":
            if group_col and group_col in df.columns:
                df[col] = df.groupby(group_col)[col].transform(lambda s: s.fillna(s.mean()))
            else:
                df[col] = df[col].fillna(df[col].mean())
        elif strategy == "median":
            if group_col and group_col in df.columns:
                df[col] = df.groupby(group_col)[col].transform(lambda s: s.fillna(s.median()))
            else:
                df[col] = df[col].fillna(df[col].median())
        elif strategy == "ffill":
            df[col] = df[col].ffill()
        elif strategy == "interpolate":
            df[col] = df[col].interpolate()
        elif strategy == "drop_rows":
            df = df.dropna(subset=[col])
        else:
            raise ValueError(f"Unsupported fill strategy: {strategy}")

    elif step.op == "drop_columns":
        df = df.drop(columns=[c for c in p["columns"] if c in df.columns])

    elif step.op == "event_flag":
        # Binary flag = 1 for rows whose date falls within [start, end] inclusive.
        date_col, new_col = p["date_col"], p["new_column"]
        start, end = pd.Timestamp(p["start"]), pd.Timestamp(p["end"])
        dates = pd.to_datetime(df[date_col])
        df[new_col] = ((dates >= start) & (dates <= end)).astype(int)

    elif step.op == "promotion_event":
        # Replay one structured PromotionEvent (core.promotions) as an
        # additive contribution to its segment's derived promo column.
        # Overlapping events for the same segment compound (summed), the
        # same behaviour as core.promotions.promotion_weekly_series - so
        # replaying N per-event steps for a segment reproduces exactly what
        # applying all N events to that segment at once would produce.
        event = p["event"]
        date_col = p["date_col"]
        new_col = f"{p.get('column_prefix', '_promo_event_')}{event['segment']}"
        start, end = pd.Timestamp(event["start_date"]), pd.Timestamp(event["end_date"])
        dates = pd.to_datetime(df[date_col])
        mask = (dates >= start) & (dates <= end)
        if new_col not in df.columns:
            df[new_col] = 0.0
        df.loc[mask, new_col] = df.loc[mask, new_col] + event.get("intensity", 1.0)

    else:
        raise ValueError(f"Unknown transform op: {step.op}")

    return df


def apply_pipeline(df: pd.DataFrame, steps: List[TransformStep]) -> pd.DataFrame:
    """Replay an ordered list of steps against a (possibly refreshed) raw DataFrame."""
    for step in steps:
        df = apply_step(df, step)
    return df


def pipeline_to_json(steps: List[TransformStep]) -> List[dict]:
    return [s.to_dict() for s in steps]


def pipeline_from_json(data: List[dict]) -> List[TransformStep]:
    return [TransformStep.from_dict(d) for d in data]


# ---------------------------------------------------------------------------
# Multi-source join
# ---------------------------------------------------------------------------

def join_sources(
    frames: Dict[str, pd.DataFrame],
    date_col: str,
    market_col: Optional[str] = None,
    how: str = "inner",
) -> pd.DataFrame:
    """
    Join media / outcomes / controls source files on date (+ market).

    Args:
        frames: mapping of source name -> DataFrame, e.g. {"media": df1, "outcomes": df2}
        date_col: shared date column name across all sources
        market_col: shared market/geography column name, if present
        how: pandas merge strategy
    """
    keys = [date_col] + ([market_col] if market_col else [])
    names = list(frames.keys())
    if not names:
        raise ValueError("No source frames provided.")

    merged = frames[names[0]].copy()
    merged[date_col] = pd.to_datetime(merged[date_col])

    for name in names[1:]:
        other = frames[name].copy()
        other[date_col] = pd.to_datetime(other[date_col])
        overlap = (set(merged.columns) & set(other.columns)) - set(keys)
        if overlap:
            raise ValueError(
                f"Column name collision between sources on {sorted(overlap)}; "
                "rename before joining."
            )
        merged = merged.merge(other, on=keys, how=how)

    return merged.sort_values(keys).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Validation checks - flagged before fitting, not discovered after
# ---------------------------------------------------------------------------

def validate_modeling_frame(
    df: pd.DataFrame,
    channels: List[str],
    segment_outcomes: Dict[str, str],
    market_col: Optional[str] = None,
    variance_cv_threshold: float = 0.05,
    collinearity_threshold: float = 0.85,
    min_obs_per_group: int = 26,
) -> List[Dict[str, str]]:
    """
    Flag likely modelling problems before fitting.

    Returns a list of {"level": "warning"|"error", "message": str} dicts.
    """
    issues: List[Dict[str, str]] = []

    # Low-variation channels (coefficient of variation) -> weakly identified curve
    for ch in channels:
        if ch not in df.columns:
            issues.append({"level": "error", "message": f"Channel column '{ch}' not found in data."})
            continue
        series = df[ch].astype(float)
        mean = series.mean()
        cv = series.std() / mean if mean > 0 else 0
        if cv < variance_cv_threshold:
            issues.append({
                "level": "warning",
                "message": f"'{ch}' has very low spend variation (CV={cv:.2f}) - "
                           "adstock/saturation for this channel will be weakly identified.",
            })

    # Collinearity between channel pairs
    present_channels = [c for c in channels if c in df.columns]
    if len(present_channels) >= 2:
        corr = df[present_channels].corr().abs()
        for i, c1 in enumerate(present_channels):
            for c2 in present_channels[i + 1:]:
                r = corr.loc[c1, c2]
                if r >= collinearity_threshold:
                    issues.append({
                        "level": "warning",
                        "message": f"'{c1}' and '{c2}' are highly correlated (r={r:.2f}) - "
                                   "their individual effects will be hard to separate.",
                    })

    # Sparse segments / geographies
    for seg, col in segment_outcomes.items():
        if col not in df.columns:
            issues.append({"level": "error", "message": f"Segment outcome column '{col}' not found."})
            continue
        n_nonzero = (df[col].fillna(0) > 0).sum()
        if n_nonzero < min_obs_per_group:
            issues.append({
                "level": "warning",
                "message": f"Segment '{seg}' has only {n_nonzero} non-zero observations - "
                           "consider leaning more on partial pooling for this segment.",
            })

    if market_col and market_col in df.columns:
        counts = df.groupby(market_col).size()
        for market, n in counts.items():
            if n < min_obs_per_group:
                issues.append({
                    "level": "warning",
                    "message": f"Market '{market}' has only {n} observations - "
                               "likely too thin to model unpooled; keep it partially pooled.",
                })

    return issues
