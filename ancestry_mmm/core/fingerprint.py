"""
Deterministic SHA-256 fingerprints of the three inputs that together define
"the fitted model": the modelling data, the model specification (structure +
priors), and the fitted posterior. Used to bind a ModelApproval to the exact
model run it was granted for (see core.approval.ModelApproval.matches_current_model)
rather than merely to "some model having been trained".

All three functions are pure and depend only on their arguments - never on
wall-clock time, object identity, or dict/set iteration order - so the same
inputs always produce the same fingerprint, and two logically-identical
inputs constructed differently (e.g. a dict built key-by-key in a different
order) still match.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

import numpy as np
import pandas as pd


def _cell_repr(value: Any) -> str:
    """A short, type-tagged, deterministic textual representation of a single cell value."""
    if pd.isna(value):
        return "\x00NULL\x00"
    if isinstance(value, (pd.Timestamp,)):
        return f"TS:{value.isoformat()}"
    if isinstance(value, (bool, np.bool_)):
        return f"B:{bool(value)}"
    if isinstance(value, (int, np.integer)):
        return f"I:{int(value)}"
    if isinstance(value, (float, np.floating)):
        return f"F:{float(value)!r}"
    return f"S:{value}"


def fingerprint_dataframe(df: pd.DataFrame) -> str:
    """
    Fingerprint a DataFrame's values, column names, column order, row order
    and dtypes. Two DataFrames produce the same fingerprint if and only if
    they are identical in all of these respects.

    Deliberately does not use `pandas.util.hash_pandas_object` (whose
    column-order sensitivity and dtype handling are internal/undocumented
    implementation details) - the row/column/dtype signature below is
    explicit and independently testable.
    """
    hasher = hashlib.sha256()
    columns = list(df.columns)
    dtype_signature = "|".join(f"{c}:{df[c].dtype}" for c in columns)
    hasher.update(("COLUMNS:" + "|".join(str(c) for c in columns) + "\n").encode("utf-8"))
    hasher.update(("DTYPES:" + dtype_signature + "\n").encode("utf-8"))

    for _, row in df[columns].iterrows() if columns else []:
        row_str = "\x1f".join(_cell_repr(row[c]) for c in columns)
        hasher.update(row_str.encode("utf-8"))
        hasher.update(b"\x1e")
    hasher.update(f"ROWS:{len(df)}".encode("utf-8"))

    return hasher.hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def fingerprint_model_spec(
    model_spec: Dict[str, Any],
    prior_config: Dict[str, Any],
    dna_lag_weeks: int,
    model_type: str = "shared",
) -> str:
    """
    Fingerprint the full set of inputs that determine how the model is
    *built*: the structural ModelSpec (markets/segments/channels/DNA
    channels/promo & control columns/LTV), the prior overrides, the DNA
    halo lag, and which model structure was fit - i.e. everything
    `build_fh_hierarchical_model` / `build_fh_market_specific_model` take
    besides the data itself. A changed prior therefore changes this
    fingerprint, since priors are part of the fitted model's identity - and
    so does switching model structure (`model_type`): a shared-curve fit and
    a market-specific fit of the *same* data/spec/priors are not the same
    fitted model, and an approval granted for one must not be treated as
    valid for the other (docs/decision_log.md, market-specific redesign).

    `model_type` defaults to `"shared"` (core.hierarchical_model's model,
    "Model A") so existing call sites that don't pass it keep fingerprinting
    that model type explicitly, not omitting model identity from the hash.

    Canonical JSON with sorted dict keys, so insertion order never matters;
    list order is preserved (json.dumps does not reorder lists), since list
    order is meaningful (e.g. `channels`).
    """
    payload = {
        "model_spec": model_spec,
        "prior_config": prior_config,
        "dna_lag_weeks": dna_lag_weeks,
        "model_type": model_type,
    }
    blob = _canonical_json(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _to_jsonable(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return _to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _to_jsonable(obj.tolist())
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj


def fingerprint_posterior(params: Any) -> str:
    """
    Fingerprint the posterior parameters actually used by the curve bank and
    scenario planner (an `FHPosteriorParams` instance, or any dataclass/dict
    with the same shape) - decay/K/S, per-segment betas, halo strength, promo
    coefficients, market offsets, intercepts, seasonality, etc.

    Converts nested dataclasses/dicts/numpy arrays into plain JSON-able
    structures (arrays -> lists, preserving element order, which is
    meaningful) before hashing with sorted dict keys - so dict key insertion
    order never affects the result, but the values themselves fully
    determine it.
    """
    payload = _to_jsonable(params)
    blob = _canonical_json(payload)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
