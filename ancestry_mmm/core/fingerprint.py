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
from typing import Any, Dict, List, Optional

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


def _model_relevant_market_config(market_spec_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    The subset of a `MarketSpecConfig.to_dict()` payload that actually feeds
    a calculation, for the fingerprint - not the whole thing.

    The descriptive/model-relevant boundary (docs/decision_log.md has the
    full rationale):

    - **Included** - `channel_media_units` (spend/response-unit column
      mapping, unit type, currency, cost basis, date frequency: these drive
      `core.media_units`'s CPA and response-unit-curve calculations and
      `core.curve_bank.make_media_unit_entries`) and each market's
      `currency` (local/reporting currency, exchange rate: reporting
      context a planner reads directly off exported curves/CPA tables).
    - **Excluded** - each market's `descriptors` (population, awareness,
      market maturity, etc.). Nothing in the fitting, prediction, curve, CPA
      or scenario code reads `MarketDescriptors` - `core/market_config.py`
      says so explicitly ("Phase 1 only stores and displays these: nothing
      downstream requires them"). Editing a market's population must not
      invalidate an approval that has nothing to do with it.

    If a future phase makes `MarketDescriptors` calculation-relevant (e.g.
    feeding a covariate), it must move to the included side here - and that
    move is itself a fingerprint-breaking change, same as any other new
    model-relevant field.
    """
    if not market_spec_config:
        return {}
    profiles = market_spec_config.get("market_profiles") or {}
    return {
        "market_currencies": {market: (profile.get("currency") or {}) for market, profile in profiles.items()},
        "channel_media_units": market_spec_config.get("channel_media_units") or {},
    }


def fingerprint_model_spec(
    model_spec: Dict[str, Any],
    prior_config: Dict[str, Any],
    dna_lag_weeks: int,
    model_type: str = "shared",
    pipeline_steps: Optional[List[Dict[str, Any]]] = None,
    market_spec_config: Optional[Dict[str, Any]] = None,
    direct_dna_outcome_ids: Optional[List[str]] = None,
) -> str:
    """
    Fingerprint the full set of inputs that determine how the model is
    *built*: the structural ModelSpec (markets/segments/channels/DNA
    channels/promo & control columns/LTV), the prior overrides, the DNA
    halo lag, which model structure was fit, the transformation recipe that
    produced the modelling data (`pipeline_steps`), the calculation-
    relevant subset of market/channel configuration (`market_spec_config`,
    filtered by `_model_relevant_market_config` - see that function's
    docstring for the descriptive/model-relevant boundary), and which
    outcome_ids get a direct DNA-media pathway (`direct_dna_outcome_ids` -
    the DNA-kit outcome_ids actually included in this fit, per
    `core.outcomes`/the Structure page's exclude-from-fit control; see
    `FHModelMeta.kit_only_outcome_ids`/`docs/dna_fh_causal_structure.md`) -
    i.e. everything that determines the fitted model and what it's used to
    calculate, besides the data values themselves (those are covered
    separately by `fingerprint_dataframe`). A changed prior therefore
    changes this fingerprint, since priors are part of the fitted model's
    identity - and so does switching model structure (`model_type`): a
    shared-curve fit and a market-specific fit of the *same* data/spec/
    priors are not the same fitted model, and an approval granted for one
    must not be treated as valid for the other (docs/decision_log.md,
    market-specific redesign). Likewise, toggling which DNA-kit outcomes
    are excluded from a fit (Structure page) changes `meta.outcome_ids` and
    `meta.kit_only_outcome_ids` without touching `model_spec`/`prior_config`/
    the raw data at all - `direct_dna_outcome_ids` is what makes that a
    fingerprint-breaking change too, closing a gap the instruction
    document's audit confirmed (an approval could otherwise stay
    "matching" across two structurally different fits).

    `model_type` defaults to `"shared"` (core.hierarchical_model's model,
    "Model A") so existing call sites that don't pass it keep fingerprinting
    that model type explicitly, not omitting model identity from the hash.
    `pipeline_steps`, `market_spec_config` and `direct_dna_outcome_ids`
    default to `None` (treated as empty) for the same reason - a caller with
    nothing to pass still gets a deterministic, explicit fingerprint rather
    than an error. `direct_dna_outcome_ids` is sorted before hashing - it
    names an unordered set of outcome_ids, so two calls listing the same
    outcome_ids in a different order must fingerprint identically.

    Note: adding `pipeline_steps`, `market_spec_config` and
    `direct_dna_outcome_ids` to this payload is an intentional breaking
    change to every fingerprint this function produces, including for
    callers who pass none of them (the payload always carries
    `"pipeline_steps": []`, `"market_relevant_config": {}` and
    `"direct_dna_outcome_ids": []` keys now) - the same pattern used when
    `model_type` was added (docs/decision_log.md). Every pre-existing
    approval is invalidated by upgrading to this version, which is correct:
    an approval bound to a fingerprint that didn't cover the transformation
    recipe, media-unit/currency config, or DNA-kit outcome membership was
    never actually binding on them, so forcing re-review is the honest
    behaviour, not a regression.

    Canonical JSON with sorted dict keys, so insertion order never matters;
    list order is preserved (json.dumps does not reorder lists), since list
    order is meaningful (e.g. `channels`, `pipeline_steps`) - except
    `direct_dna_outcome_ids`, sorted explicitly above for exactly that reason.
    """
    payload = {
        "model_spec": model_spec,
        "prior_config": prior_config,
        "dna_lag_weeks": dna_lag_weeks,
        "model_type": model_type,
        "pipeline_steps": pipeline_steps or [],
        "market_relevant_config": _model_relevant_market_config(market_spec_config),
        "direct_dna_outcome_ids": sorted(direct_dna_outcome_ids) if direct_dna_outcome_ids else [],
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
