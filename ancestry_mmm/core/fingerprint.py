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
    hasher.update(
        ("COLUMNS:" + "|".join(str(c) for c in columns) + "\n").encode("utf-8")
    )
    hasher.update(("DTYPES:" + dtype_signature + "\n").encode("utf-8"))

    for _, row in df[columns].iterrows() if columns else []:
        row_str = "\x1f".join(_cell_repr(row[c]) for c in columns)
        hasher.update(row_str.encode("utf-8"))
        hasher.update(b"\x1e")
    hasher.update(f"ROWS:{len(df)}".encode("utf-8"))

    return hasher.hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def _model_relevant_market_config(
    market_spec_config: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
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
        "market_currencies": {
            market: (profile.get("currency") or {})
            for market, profile in profiles.items()
        },
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
    outcome_catalogue: Optional[List[Dict[str, Any]]] = None,
    outcome_groups: Optional[List[Dict[str, Any]]] = None,
    funnel_links: Optional[List[Dict[str, Any]]] = None,
    media_outcome_pathways: Optional[List[Dict[str, Any]]] = None,
    activity_fit_fingerprint: Optional[str] = None,
    causal_graph_structural_fingerprint: Optional[str] = None,
    search_object_fit_fingerprint: Optional[str] = None,
    variable_coverage_fingerprint: Optional[str] = None,
    outcome_group_treatments: Optional[List[Dict[str, Any]]] = None,
    official_preparation_evidence: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Fingerprint the full set of inputs that determine how the model is
    *built*: the structural ModelSpec (markets/segments/channels/DNA
    channels/promo & control columns/LTV), the prior overrides, the DNA
    halo lag, which model structure was fit, the transformation recipe that
    produced the modelling data (`pipeline_steps`), the calculation-
    relevant subset of market/channel configuration (`market_spec_config`,
    filtered by `_model_relevant_market_config` - see that function's
    docstring for the descriptive/model-relevant boundary), which
    outcome_ids get a direct DNA-media pathway (`direct_dna_outcome_ids` -
    the DNA-kit outcome_ids actually included in this fit, per
    `core.outcomes`/the Structure page's exclude-from-fit control; see
    `FHModelMeta.kit_only_outcome_ids`/`docs/dna_fh_causal_structure.md`),
    and the full canonical outcome catalogue (`outcome_catalogue` - PR E.1;
    pass `core.outcomes.outcome_catalogue_fingerprint_payload(outcomes)`,
    already sorted by outcome_id with only the calculation-relevant fields:
    outcome_id/product/segment/metric/unit/source_column/role/
    included_in_fit/value_weight/value_currency) - i.e. everything that
    determines the fitted model and what it's used to calculate, besides
    the data values themselves (those are covered separately by
    `fingerprint_dataframe`). A changed prior therefore changes this
    fingerprint, since priors are part of the fitted model's identity - and
    so does switching model structure (`model_type`): a shared-curve fit
    and a market-specific fit of the *same* data/spec/priors are not the
    same fitted model, and an approval granted for one must not be treated
    as valid for the other (docs/decision_log.md, market-specific
    redesign). Likewise, `outcome_catalogue` is what makes adding/removing
    a non-DNA FH outcome, changing sign-up to GSA, changing unit/source
    column/role/inclusion, or changing the value weight used in planning,
    into a fingerprint-breaking change - closing the gap the instruction
    document's audit confirmed: `direct_dna_outcome_ids` alone only covered
    DNA-kit outcome membership, not any of the rest of an outcome's
    identity, so e.g. relabelling a GSA outcome as a sign-up outcome (or
    vice versa) could previously leave an approval "matching" a
    structurally different fit.

    `outcome_groups` (REQ-DATAIN-002 WP1 - pass
    `core.outcomes.outcome_group_fingerprint_payload(groups)`) captures the
    calculation-relevant semantic grouping contract. It is sorted by
    `group_id` and excludes presentation-only group labels, so changing which
    outcomes belong to a group, its aggregation rule, or its supplied total
    invalidates the fit identity while a wording edit does not. The grouping
    contract is distinct from diagnostic reconciliation groups and from causal
    graph/pathway edges.

    `model_type` defaults to `"shared"` (core.hierarchical_model's model,
    "Model A") so existing call sites that don't pass it keep fingerprinting
    that model type explicitly, not omitting model identity from the hash.
    `pipeline_steps`, `market_spec_config`, `direct_dna_outcome_ids`,
    `outcome_catalogue`, `outcome_groups`, and `outcome_group_treatments` default to `None` (treated as
    empty) for the same
    reason - a caller with nothing to pass still gets a deterministic,
    explicit fingerprint rather than an error. `direct_dna_outcome_ids` is
    sorted before hashing - it names an unordered set of outcome_ids, so two
    calls listing the same outcome_ids in a different order must fingerprint
    identically; `outcome_catalogue` is likewise re-sorted by its own
    `outcome_id` key here (defensively - callers are expected to already
    pass it pre-sorted) for the same reason. `outcome_groups` and
    `outcome_group_treatments` are likewise re-sorted by their `group_id`
    keys here defensively. A treatment change such as `components_joint` to
    `total_only` therefore invalidates dependent evidence.

    `funnel_links` (PR E.2 - `core.funnel.FunnelLink`s, pass
    `core.funnel.funnel_links_fingerprint_payload(links)`) is diagnostic
    configuration - it never affects what gets fitted - but is still
    calculation-relevant to the *diagnostics displayed*, so it is
    fingerprinted the same way as the outcome catalogue: sorted by
    (upstream_outcome_id, downstream_outcome_id) here defensively, `[]` when
    omitted.

    `media_outcome_pathways` (PR F - `core.pathways.MediaOutcomePathway`s,
    pass `core.pathways.pathway_catalogue_fingerprint_payload(pathways)`) is,
    like `funnel_links`, configuration that does not (yet) change what gets
    fitted - no model equation reads it - but is calculation-*adjacent*
    metadata a future estimation PR will read, and is captured at fit time
    (`FHModelMeta.pathway_catalogue_at_fit`) for drift detection the same way
    the outcome catalogue is. Sorted by `(channel, target_outcome_id)` here
    defensively, `[]` when omitted.

    `activity_fit_fingerprint` (PR G2A.6c workstream F -
    `core.activities.activity_fit_fingerprint(activity_definitions)`) covers
    only the fit-relevant activity fields (market, activity_id, model_role,
    resolved model-input column, pathway_ids) - never economic_treatment,
    planning_eligibility or governance/approval metadata, which don't change
    what gets fitted. Changing an activity from `intervention` to `mediator`,
    repointing it at a different model-input column, or relinking its
    pathways therefore changes this fingerprint and correctly stales any
    approval bound to the old one, the same way changing `model_type` does.
    `""` when omitted (no activity governance data available).

    `causal_graph_structural_fingerprint` (REQ-GRAPH-001 work package D -
    `core.causal_graph.CausalGraph.structural_fingerprint()`) is the
    structural (never layout) fingerprint of the approved `CausalGraph`
    actually compiled for this fit, when one was used (see
    `core.graph_model_compiler.GraphModelCompiler`). `""` when omitted (no
    graph was used - either the project has no approved causal graph
    configured, or this fingerprint was computed via
    `core.causal_graph.current_structural_fingerprint_for_identity` for a
    fit that didn't use one). A layout-only edit to the graph never changes
    this value, so it never stales a bound approval; a structural edit
    always does, the same as every other field in this payload.

    `search_object_fit_fingerprint` (REQ-SEARCH-001 fit-identity closure -
    `core.search_objects.search_object_fit_fingerprint(search_objects,
    consumed_model_input_columns=model_spec["channels"])`) covers only the
    Search objects this fit actually consumes (a current-version, non-blank
    `model_input_column` matching one of this fit's own channels) and, for
    those, only their fit-relevant content fields (market, search_object_id,
    search_role, source_column, model_input_column, unit, grain, product) -
    never `channel`, `effective_period_start`/`effective_period_end`,
    `state`, `planning_eligibility`, `evidence_status`, approval metadata,
    `currency`, `schema_version`, or `search_object_version` (the
    governance/audit version counter - excluded so that a purely
    administrative sanctioned edit, which still bumps it, never stales a
    fit; see `search_object_fit_fingerprint`'s docstring), and never a
    Search object this fit does not consume, or a superseded version of one
    it does. `""` when omitted (no Search governance data available, or
    none of it is consumed by this fit).

    `variable_coverage_fingerprint` (REQ-COVERAGE-001 S5 - pass
    `core.coverage.VariableCoverageMatrix.fingerprint()`, which already
    hashes only `VariableCoverageRecord.fit_relevant_fields()`, never
    administrative/audit-only fields such as `owner`, `proposed_treatment`,
    approval attribution, observed/expected diagnostic windows, or free-text
    justifications - see that method's docstring for the full boundary) is a
    simple pass-through, like `causal_graph_structural_fingerprint`, not a
    consumption-filtered value like `search_object_fit_fingerprint`: unlike
    Search objects (which map onto specific model-input columns this fit
    either does or doesn't consume), the coverage matrix has no such
    per-fit consumption relationship yet - nothing in the current data
    pipeline reads a variable's coverage/treatment classification to decide
    what value to prepare (that binding is `FR-MOD-015`'s job, explicitly
    unresolved - REQ-COVERAGE-001 S6). Passing the live matrix's fingerprint
    here today therefore does exactly what REQ-COVERAGE-001 S5 requires, no
    more and no less: "a coverage or treatment change that alters
    prepared-data semantics must change prepared-data/model identity ... a
    purely presentational metadata change must not" - `fit_relevant_fields()`
    already strips the presentational fields, so every remaining change this
    fingerprint reacts to is calculation-relevant by construction, and once
    a future package makes coverage/treatment decisions actually change what
    gets fitted, this same wiring already staled every approval bound to the
    old, unaware fingerprint. `""` when omitted (no coverage matrix governed
    yet for this project).

    Note: adding `pipeline_steps`, `market_spec_config`,
    `direct_dna_outcome_ids`, `outcome_catalogue`, `outcome_groups`,
    `outcome_group_treatments`,
    `funnel_links`,
    `media_outcome_pathways`, `activity_fit_fingerprint`,
    `causal_graph_structural_fingerprint`, `search_object_fit_fingerprint`
    and `variable_coverage_fingerprint` to this payload is an intentional
    breaking change to every fingerprint this function produces, including
    for callers who pass none of them (the payload always carries
    `"pipeline_steps": []`, `"market_relevant_config": {}`,
    `"direct_dna_outcome_ids": []`, `"outcome_catalogue": []`,
    `"outcome_groups": []`, `"outcome_group_treatments": []`,
    `"funnel_links": []`, `"media_outcome_pathways": []`,
    `"activity_fit_fingerprint": ""`,
    `"causal_graph_structural_fingerprint": ""`,
    `"search_object_fit_fingerprint": ""` and
    `"variable_coverage_fingerprint": ""` keys now) - the same pattern used
    when `model_type` was added (docs/decision_log.md). Every pre-existing
    approval is invalidated by upgrading to this version, which is correct:
    an approval bound to a fingerprint that didn't cover the transformation
    recipe, media-unit/currency config, DNA-kit outcome membership, the full
    outcome catalogue, fit-relevant activity governance, the compiled causal
    graph, fit-relevant Search governance, or the governed coverage matrix
    was never actually binding on them, so forcing re-review is the honest
    behaviour, not a regression.

    Canonical JSON with sorted dict keys, so insertion order never matters;
    list order is preserved (json.dumps does not reorder lists), since list
    order is meaningful (e.g. `channels`, `pipeline_steps`) - except
    `direct_dna_outcome_ids`/`outcome_catalogue`/`outcome_groups`, sorted
    explicitly above for exactly that reason.
    """
    payload = {
        "model_spec": model_spec,
        "prior_config": prior_config,
        "dna_lag_weeks": dna_lag_weeks,
        "model_type": model_type,
        "pipeline_steps": pipeline_steps or [],
        "market_relevant_config": _model_relevant_market_config(market_spec_config),
        "direct_dna_outcome_ids": sorted(direct_dna_outcome_ids)
        if direct_dna_outcome_ids
        else [],
        "outcome_catalogue": (
            sorted(outcome_catalogue, key=lambda o: o.get("outcome_id", ""))
            if outcome_catalogue
            else []
        ),
        "outcome_groups": (
            sorted(outcome_groups, key=lambda group: group.get("group_id", ""))
            if outcome_groups
            else []
        ),
        "outcome_group_treatments": (
            sorted(
                outcome_group_treatments,
                key=lambda treatment: treatment.get("group_id", ""),
            )
            if outcome_group_treatments
            else []
        ),
        "funnel_links": (
            sorted(
                funnel_links,
                key=lambda link: (
                    link.get("upstream_outcome_id", ""),
                    link.get("downstream_outcome_id", ""),
                ),
            )
            if funnel_links
            else []
        ),
        "media_outcome_pathways": (
            sorted(
                media_outcome_pathways,
                key=lambda p: (p.get("channel", ""), p.get("target_outcome_id", "")),
            )
            if media_outcome_pathways
            else []
        ),
        "activity_fit_fingerprint": activity_fit_fingerprint or "",
        "causal_graph_structural_fingerprint": causal_graph_structural_fingerprint
        or "",
        "search_object_fit_fingerprint": search_object_fit_fingerprint or "",
        "variable_coverage_fingerprint": variable_coverage_fingerprint or "",
        "official_preparation_evidence": official_preparation_evidence or {},
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
