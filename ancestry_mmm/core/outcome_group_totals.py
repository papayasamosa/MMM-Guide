"""Draw-level aggregation for governed semantic outcome groups.

Outcome groups describe one business measure whose fitted components are
separate ``outcome_id`` values.  This module is deliberately independent of
PyMC and Streamlit: it operates on draw/summary tables and is shared by
curves, attribution, reporting, and scenario presentation.

The important ordering is:

``component rows -> one total per posterior draw -> posterior summary``

An exact supplied total is a reconciliation source for ``components_joint``;
it is not another official component.  ``total_only`` uses the supplied row
and excludes the member rows from the official group view.  Projects without
groups are returned unchanged for legacy compatibility.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .outcomes import (
    OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
    OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
    OutcomeGroupDefinition,
    OutcomeGroupTreatment,
)

GROUP_TOTAL_SOURCE_COMPONENTS = "derived_from_components"
GROUP_TOTAL_SOURCE_SUPPLIED = "supplied_total"
GROUP_TREATMENT_UNGROUPED = "ungrouped"

# These columns are outcome-scale additive quantities.  Ratios, flags,
# identities, and repeated whole-plan metrics are intentionally not included:
# they must be recomputed or carried from one representative row.
DEFAULT_ADDITIVE_COLUMNS = frozenset(
    {
        "response",
        "incremental_response",
        "volume_contribution",
        "media_eta_contribution",
        "incremental_media_eta_contribution",
        "marginal_response",
        "marginal_incremental_response_per_currency_unit",
        "marginal_incremental_response_per_media_input_unit",
        "marginal_value",
        "incremental_value",
        "predicted_outcome",
        "predicted_total_outcome",
        "predicted_counterfactual_outcome",
        "incremental_outcome",
        "incremental_outcome_all_activities",
        "incremental_outcome_paid_decisions",
        "incremental_outcome_response_only_activities",
        "value",
    }
)

DEFAULT_MAX_COLUMNS = frozenset(
    {
        "spend",
        "reporting_currency_spend",
        "local_spend",
        "incremental_spend",
        "total_spend",
        "paid_spend",
        "fully_loaded_owned_spend",
        "campaign_cost_spend",
    }
)


def _as_group(
    value: OutcomeGroupDefinition | Mapping[str, Any],
) -> OutcomeGroupDefinition:
    return (
        value
        if isinstance(value, OutcomeGroupDefinition)
        else OutcomeGroupDefinition.from_dict(value)
    )


def _as_treatment(
    value: OutcomeGroupTreatment | Mapping[str, Any],
) -> OutcomeGroupTreatment:
    return (
        value
        if isinstance(value, OutcomeGroupTreatment)
        else OutcomeGroupTreatment.from_dict(value)
    )


def _normalise_groups(
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None,
) -> list[OutcomeGroupDefinition]:
    return [_as_group(value) for value in (groups or ())]


def _normalise_treatments(
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None,
) -> dict[str, OutcomeGroupTreatment]:
    return {
        treatment.group_id: treatment
        for treatment in (_as_treatment(value) for value in (treatments or ()))
    }


def _treatment_for(
    group: OutcomeGroupDefinition,
    treatments: Mapping[str, OutcomeGroupTreatment],
) -> str:
    return treatments.get(
        group.group_id,
        OutcomeGroupTreatment(group_id=group.group_id),
    ).treatment


def _applicable_groups(
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None,
) -> list[tuple[OutcomeGroupDefinition, str]]:
    treatment_map = _normalise_treatments(treatments)
    return [
        (group, _treatment_for(group, treatment_map))
        for group in _normalise_groups(groups)
        if _treatment_for(group, treatment_map)
        in {
            OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT,
            OUTCOME_GROUP_TREATMENT_TOTAL_ONLY,
        }
    ]


def reporting_group_options(
    outcome_ids: Sequence[str],
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
) -> list[tuple[str, str]]:
    """Return safe group selectors as ``(stable_id, human_label)`` pairs.

    A selector is offered only when all fitted component outcomes are present
    for ``components_joint`` or the supplied total is present for
    ``total_only``.  Raw outcome IDs remain valid selectors alongside these
    group options.
    """

    fitted = set(outcome_ids)
    options: list[tuple[str, str]] = []
    for group, treatment in _applicable_groups(groups, treatments):
        if treatment == OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT:
            available = set(group.member_outcome_ids).issubset(fitted)
        else:
            available = bool(
                group.supplied_total_outcome_id
                and group.supplied_total_outcome_id in fitted
            )
        if available:
            options.append((group.group_id, group.group_label))
    return options


def selected_reporting_ids(
    outcome_ids: Sequence[str],
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
) -> set[str]:
    """Translate member outcome selections into non-double-counted views."""

    selected = set(outcome_ids)
    for group, treatment in _applicable_groups(groups, treatments):
        members = set(group.member_outcome_ids)
        if treatment == OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT:
            if not members.issubset(selected):
                continue
            selected -= members
            if group.supplied_total_outcome_id:
                selected.discard(group.supplied_total_outcome_id)
            selected.add(group.group_id)
        elif (
            group.supplied_total_outcome_id
            and group.supplied_total_outcome_id in selected
        ):
            selected -= members
            selected.discard(group.supplied_total_outcome_id)
            selected.add(group.group_id)
    return selected


def _infer_by_columns(
    data: pd.DataFrame,
    *,
    outcome_id_col: str,
    posterior_draw_col: str,
) -> list[str]:
    excluded = {
        outcome_id_col,
        "outcome_group_id",
        "outcome_group_label",
        "outcome_group_treatment",
        "outcome_group_source",
        "outcome_group_member_outcome_ids",
        "outcome_group_member_count",
        "segment",
        "metric",
        "metric_key",
        "product",
        "segment_dimension",
        "component_type",
        "pathway_role",
    }
    excluded.update(DEFAULT_ADDITIVE_COLUMNS)
    excluded.update(DEFAULT_MAX_COLUMNS)
    return [
        column
        for column in data.columns
        if column not in excluded and column != posterior_draw_col
    ]


def _aggregation_function(
    column: str,
    *,
    additive_columns: set[str],
) -> str | Any:
    if column in additive_columns:
        return lambda values: values.sum(min_count=1)
    if column in DEFAULT_MAX_COLUMNS:
        return "max"
    if column.startswith("include_in_") or column.endswith("_eligible"):
        return lambda values: bool(values.fillna(False).astype(bool).all())
    if column == "planning_support_eligible":
        return lambda values: bool(values.fillna(False).astype(bool).all())
    if column == "is_extrapolated":
        return lambda values: (
            None if values.isna().all() else bool(values.fillna(False).any())
        )
    if column in {"planning_blocked_reason", "observed_support_status"}:
        return lambda values: "; ".join(
            sorted(
                {str(value).strip() for value in values.dropna() if str(value).strip()}
            )
        )
    return "first"


def _aggregate_rows(
    rows: pd.DataFrame,
    *,
    group: OutcomeGroupDefinition,
    treatment: str,
    by: Sequence[str],
    outcome_id_col: str,
    value_columns: Sequence[str] | None,
    source: str,
) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    keys = list(dict.fromkeys([*by]))
    missing = [column for column in keys if column not in rows.columns]
    if missing:
        raise ValueError(f"outcome-group grain columns are missing: {missing}")
    additive_columns = set(value_columns or DEFAULT_ADDITIVE_COLUMNS)
    present = [
        column
        for column in rows.columns
        if column not in keys and column != outcome_id_col
    ]
    aggregations = {
        column: _aggregation_function(column, additive_columns=additive_columns)
        for column in present
    }
    result = (
        rows.groupby(keys, dropna=False, sort=False).agg(aggregations).reset_index()
    )
    result[outcome_id_col] = group.group_id
    # These presentation and provenance columns are deliberately assigned
    # after aggregation; component labels must never survive as if they were
    # a causal pathway type.
    if "product" in result.columns:
        result["product"] = group.product
    if "metric_key" in result.columns:
        result["metric_key"] = group.outcome_family_key
    if "segment" in result.columns:
        result["segment"] = group.group_label
    if "segment_dimension" in result.columns:
        result["segment_dimension"] = group.segment_dimension
    if "component_type" in result.columns:
        result["component_type"] = "total"
    if "pathway_role" in result.columns:
        result["pathway_role"] = "outcome_group_total"
    result["outcome_group_id"] = group.group_id
    result["outcome_group_label"] = group.group_label
    result["outcome_group_treatment"] = treatment
    result["outcome_group_source"] = source
    result["outcome_group_member_outcome_ids"] = json.dumps(
        list(group.member_outcome_ids), separators=(",", ":")
    )
    result["outcome_group_member_count"] = len(group.member_outcome_ids)
    return result


def aggregate_outcome_groups(
    rows: pd.DataFrame,
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
    *,
    by: Sequence[str] | None = None,
    value_columns: Sequence[str] | None = None,
    outcome_id_col: str = "outcome_id",
    posterior_draw_col: str = "posterior_draw",
    include_member_rows: bool = False,
    strict: bool = False,
) -> pd.DataFrame:
    """Build a non-double-counted official view of outcome rows.

    ``by`` is the row grain excluding ``outcome_id``.  When omitted, common
    identity columns are inferred, which is convenient for small generic
    tables; production callers pass it explicitly.  If a posterior draw
    column exists it must be included in ``by`` or it is appended
    automatically, ensuring totals are formed separately for every draw.

    ``strict`` raises when a selected group cannot be formed from the rows.
    The default skips incomplete groups, which is needed for an artifact that
    is intentionally scoped to one approved outcome and therefore cannot
    contain the other members of its semantic group.
    """
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    if outcome_id_col not in rows.columns:
        raise ValueError(f"rows must carry {outcome_id_col!r}")
    normalised_groups = _normalise_groups(groups)
    if not normalised_groups:
        return rows.copy()
    if rows.empty:
        return rows.copy()
    selected = _applicable_groups(normalised_groups, treatments)
    if not selected:
        return rows.copy()

    grain = (
        list(by)
        if by is not None
        else _infer_by_columns(
            rows,
            outcome_id_col=outcome_id_col,
            posterior_draw_col=posterior_draw_col,
        )
    )
    if posterior_draw_col in rows.columns and posterior_draw_col not in grain:
        grain.append(posterior_draw_col)
    if outcome_id_col in grain:
        raise ValueError("outcome-group grain must not include outcome_id")

    output_parts: list[pd.DataFrame] = []
    remove_ids: set[str] = set()
    created_group_ids: set[str] = set()
    fitted_ids = set(rows[outcome_id_col].dropna().astype(str))
    for group, treatment in selected:
        members = set(group.member_outcome_ids)
        if treatment == OUTCOME_GROUP_TREATMENT_COMPONENTS_JOINT:
            source_ids = members
            source = GROUP_TOTAL_SOURCE_COMPONENTS
            missing = sorted(source_ids - fitted_ids)
        else:
            source_ids = (
                {group.supplied_total_outcome_id}
                if group.supplied_total_outcome_id
                else set()
            )
            source = GROUP_TOTAL_SOURCE_SUPPLIED
            missing = sorted(source_ids - fitted_ids)
        if missing or not source_ids:
            message = (
                f"Outcome group '{group.group_id}' cannot be materialised; "
                f"missing rows: {missing or ['supplied_total_outcome_id']}"
            )
            if strict:
                raise ValueError(message)
            continue
        selected_rows = rows[rows[outcome_id_col].isin(source_ids)]
        output_parts.append(
            _aggregate_rows(
                selected_rows,
                group=group,
                treatment=treatment,
                by=grain,
                outcome_id_col=outcome_id_col,
                value_columns=value_columns,
                source=source,
            )
        )
        created_group_ids.add(group.group_id)
        if not include_member_rows:
            remove_ids.update(members)
            if group.supplied_total_outcome_id:
                remove_ids.add(group.supplied_total_outcome_id)

    if include_member_rows:
        retained = rows.copy()
    else:
        retained = rows[~rows[outcome_id_col].isin(remove_ids)].copy()
    if output_parts:
        retained = pd.concat([retained, *output_parts], ignore_index=True, sort=False)
    if not created_group_ids:
        return rows.copy()
    return retained.reset_index(drop=True)


def aggregate_outcome_group_draws(
    draws: pd.DataFrame,
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> pd.DataFrame:
    """Explicit draw-table alias for :func:`aggregate_outcome_groups`."""
    if "posterior_draw" not in draws.columns:
        raise ValueError("draws must carry posterior_draw")
    return aggregate_outcome_groups(draws, groups, treatments, **kwargs)


def summarize_outcome_group_draws(
    draws: pd.DataFrame,
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
    *,
    by: Sequence[str] | None = None,
    measures: Sequence[str] | None = None,
    cred_mass: float = 0.9,
    **kwargs: Any,
) -> pd.DataFrame:
    """Aggregate group members per draw, then compute posterior summaries."""
    if not 0 < cred_mass < 1:
        raise ValueError("cred_mass must be between zero and one")
    aggregated = aggregate_outcome_group_draws(
        draws,
        groups,
        treatments,
        by=by,
        **kwargs,
    )
    dimensions = list(by or [])
    if "posterior_draw" in dimensions:
        dimensions.remove("posterior_draw")
    dimensions.append("outcome_id")
    missing = [column for column in dimensions if column not in aggregated.columns]
    if missing:
        raise ValueError(f"summary dimensions are missing from draws: {missing}")
    tail = (1.0 - cred_mass) / 2.0
    grouped = aggregated.groupby(dimensions, dropna=False, sort=False)
    selected_measures = list(measures or DEFAULT_ADDITIVE_COLUMNS)
    selected_measures = [
        column for column in selected_measures if column in aggregated.columns
    ]
    result = grouped.first().reset_index()
    result = result[
        dimensions
        + [
            column
            for column in result.columns
            if column not in dimensions
            and column not in selected_measures
            and column != "posterior_draw"
        ]
    ]
    for measure in selected_measures:
        stats = (
            grouped[measure]
            .agg(
                posterior_mean="mean",
                posterior_median="median",
                lower_interval=lambda values: values.quantile(tail),
                upper_interval=lambda values: values.quantile(1.0 - tail),
            )
            .reset_index()
            .rename(
                columns={
                    "posterior_mean": f"{measure}_posterior_mean",
                    "posterior_median": f"{measure}_posterior_median",
                    "lower_interval": f"{measure}_lower_interval",
                    "upper_interval": f"{measure}_upper_interval",
                }
            )
        )
        result = result.merge(stats, on=dimensions, how="left")
    if "incremental_response_posterior_mean" in result.columns:
        result["posterior_mean"] = result["incremental_response_posterior_mean"]
        result["posterior_median"] = result["incremental_response_posterior_median"]
        result["lower_interval"] = result["incremental_response_lower_interval"]
        result["upper_interval"] = result["incremental_response_upper_interval"]
    return result


def aggregate_attribution_group_rows(
    rows: pd.DataFrame,
    groups: Sequence[OutcomeGroupDefinition | Mapping[str, Any]] | None = None,
    treatments: Sequence[OutcomeGroupTreatment | Mapping[str, Any]] | None = None,
    *,
    by: Sequence[str],
) -> pd.DataFrame:
    """Group point-estimate attribution rows and recompute ratio measures."""
    grouped = aggregate_outcome_groups(
        rows,
        groups,
        treatments,
        by=by,
        value_columns=("volume_contribution", "value_contribution"),
    )
    if grouped.empty:
        return grouped
    spend = grouped["spend"].replace(0, np.nan) if "spend" in grouped else np.nan
    if "volume_contribution" in grouped:
        grouped["roas"] = grouped["volume_contribution"] / spend
        grouped["cpa"] = spend / grouped["volume_contribution"].where(
            grouped["volume_contribution"] > 0, np.nan
        )
    if "value_contribution" in grouped:
        grouped["value_roas"] = grouped["value_contribution"] / spend
    if "ltv" in grouped:
        grouped["ltv"] = np.nan
    return grouped


def outcome_group_member_shares(
    draws: pd.DataFrame,
    group: OutcomeGroupDefinition | Mapping[str, Any],
    *,
    value_column: str = "incremental_response",
    by: Sequence[str] | None = None,
    posterior_draw_col: str = "posterior_draw",
) -> pd.DataFrame:
    """Return draw-level component shares and their reconciliation total."""
    definition = _as_group(group)
    if value_column not in draws.columns:
        raise ValueError(f"draws must carry {value_column!r}")
    if posterior_draw_col not in draws.columns:
        raise ValueError("draws must carry posterior_draw")
    grain = list(
        by
        or _infer_by_columns(
            draws,
            outcome_id_col="outcome_id",
            posterior_draw_col=posterior_draw_col,
        )
    )
    grain.append(posterior_draw_col)
    member_rows = draws[draws["outcome_id"].isin(definition.member_outcome_ids)].copy()
    if member_rows.empty:
        return pd.DataFrame()
    total = member_rows.groupby(grain, dropna=False, sort=False)[value_column].sum()
    total = total.rename("outcome_group_total").reset_index()
    result = member_rows.merge(total, on=grain, how="left")
    result["outcome_group_id"] = definition.group_id
    result["outcome_group_label"] = definition.group_label
    result["member_share"] = result[value_column] / result[
        "outcome_group_total"
    ].replace(0, np.nan)
    return result
