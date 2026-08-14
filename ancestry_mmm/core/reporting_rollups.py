"""Governed reporting enrichment and posterior-safe roll-ups.

Reporting taxonomy is a display and analysis dimension. It does not change
the causal graph, fitted response, or pathway meaning. This module keeps
that boundary explicit while making activity-level contribution and curve
rows usable at channel, platform, objective, and funnel levels.

Rows carrying ``posterior_draw`` are always aggregated at draw level before
any posterior summary. Direct, mediated, halo, and total effects remain
separate through the explicit ``effect_type`` dimension; funnel stage is
never used to infer an effect type.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import pandas as pd

from .activities import (
    ActivityDefinition,
    FUNNEL_STAGES,
    activity_reporting_fingerprint,
)
from .outcome_group_totals import aggregate_outcome_group_draws

FUNNEL_STAGE_LABELS = {
    "brand_upper": "Brand / upper funnel",
    "mid_funnel": "Mid-funnel",
    "performance_lower": "Performance / lower funnel",
    "cross_funnel": "Cross-funnel",
    "not_applicable": "Not applicable",
    "unclassified": "Unclassified",
}

REPORTING_DIMENSIONS = (
    "activity_id",
    "reporting_channel",
    "platform",
    "campaign_type",
    "marketing_objective",
    "message_type",
    "funnel_stage",
    "product_advertised",
    "market",
    "outcome_id",
    "segment",
    "pathway_role",
    "effect_type",
)

# Additive response/economic measures. Ratios, posterior summaries,
# coefficients, and governance flags are deliberately excluded: they must be
# recomputed from draw-level totals or retained as metadata, never summed.
ADDITIVE_MEASURES = (
    "incremental_response",
    "response",
    "volume_contribution",
    "media_eta_contribution",
    "incremental_value",
    "marginal_value",
    "marginal_response",
    "marginal_incremental_response_per_currency_unit",
    "marginal_incremental_response_per_media_input_unit",
)

COST_MEASURES = (
    "spend",
    "reporting_currency_spend",
    "local_spend",
    "incremental_spend",
    "allocated_incremental_spend",
)

SUMMARY_MEASURES = ADDITIVE_MEASURES + COST_MEASURES


class ReportingEnrichmentError(ValueError):
    """Raised when strict reporting enrichment cannot resolve identity."""


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _definition_rows(
    definitions: Iterable[ActivityDefinition | Mapping[str, object]],
) -> list[ActivityDefinition]:
    return [
        item
        if isinstance(item, ActivityDefinition)
        else ActivityDefinition.from_dict(item)
        for item in definitions
    ]


def _market_candidates(
    candidates: Sequence[ActivityDefinition], market: str
) -> list[ActivityDefinition]:
    if market == "*":
        return list(candidates)
    exact = [item for item in candidates if item.market == market]
    return exact or [item for item in candidates if item.market == "*"]


def _unique_definition(
    candidates: Sequence[ActivityDefinition],
    *,
    market: str,
    lookup: str,
) -> ActivityDefinition | None:
    selected = _market_candidates(candidates, market)
    if not selected:
        return None
    identities = {
        (
            item.activity_id,
            item.channel,
            item.platform,
            item.campaign_type,
            item.marketing_objective,
            item.message_type,
            item.funnel_stage,
            item.product_advertised,
        )
        for item in selected
    }
    if len(identities) != 1:
        raise ReportingEnrichmentError(
            f"ambiguous governed activity for {lookup!r} in market {market!r}; "
            "review the activity mapping"
        )
    return selected[0]


def _resolve_definition(
    row: Mapping[str, object], definitions: Sequence[ActivityDefinition]
) -> tuple[ActivityDefinition | None, str]:
    market = _text(row.get("market")) or "*"
    activity_id = _text(row.get("activity_id"))
    if activity_id:
        definition = _unique_definition(
            [item for item in definitions if item.activity_id == activity_id],
            market=market,
            lookup=f"activity_id={activity_id}",
        )
        if definition is not None:
            return definition, "governed_activity_id"
        return None, f"no governed activity matches activity_id={activity_id!r}"

    source = _text(row.get("model_input_column")) or _text(row.get("channel"))
    if not source:
        return None, "row has no activity_id or model-input/channel identity"

    physical = [
        item for item in definitions if item.resolved_model_input_column == source
    ]
    definition = _unique_definition(
        physical,
        market=market,
        lookup=f"model_input_column={source}",
    )
    if definition is not None:
        return definition, "governed_model_input"

    # Compatibility for old attribution rows: channel fallback is allowed
    # only when it identifies exactly one governed activity.
    channel_candidates = [item for item in definitions if item.channel == source]
    definition = _unique_definition(
        channel_candidates,
        market=market,
        lookup=f"reporting_channel={source}",
    )
    if definition is not None:
        return definition, "legacy_unique_reporting_channel"
    return None, f"no unique governed activity matches source={source!r}"


def _unclassified_values(row: Mapping[str, object]) -> dict[str, object]:
    stage = _text(row.get("funnel_stage"))
    if stage not in FUNNEL_STAGES:
        stage = "unclassified"
    return {
        "activity_id": row.get("activity_id"),
        "activity_market": row.get("activity_market") or row.get("market") or "*",
        "reporting_channel": row.get("reporting_channel"),
        "platform": row.get("platform"),
        "campaign_type": row.get("campaign_type"),
        "marketing_objective": row.get("marketing_objective"),
        "message_type": row.get("message_type"),
        "funnel_stage": stage,
        "funnel_stage_label": FUNNEL_STAGE_LABELS[stage],
        "product_advertised": row.get("product_advertised"),
        "reporting_enrichment_status": "unclassified",
    }


def _resolve_effect_type(row: Mapping[str, object]) -> str:
    """Use explicit effect/pathway metadata without inferring from funnel."""
    for column in ("effect_type", "pathway_role", "component_type"):
        value = _text(row.get(column))
        if value:
            return value
    # A row without a component/pathway dimension is already a total
    # attribution or channel-safe summary, not an inferred mediated effect.
    return "total"


def enrich_reporting_rows(
    rows: pd.DataFrame,
    activity_definitions: Iterable[ActivityDefinition | Mapping[str, object]],
    *,
    strict: bool = False,
) -> pd.DataFrame:
    """Join contribution/curve/economic rows to governed activity metadata.

    ``activity_id`` is authoritative when present. Older rows may resolve
    through an exact physical model-input column, with a reporting-channel
    fallback only when it identifies exactly one candidate. Unresolved or
    ambiguous rows remain in the explicit Unclassified bucket unless
    ``strict=True`` is requested.
    """
    if not isinstance(rows, pd.DataFrame):
        raise TypeError("rows must be a pandas DataFrame")
    data = rows.copy()
    definitions = _definition_rows(activity_definitions)
    taxonomy_fingerprint = (
        activity_reporting_fingerprint(definitions) if definitions else None
    )
    if data.empty:
        for column in (
            "activity_id",
            "activity_market",
            "reporting_channel",
            "platform",
            "campaign_type",
            "marketing_objective",
            "message_type",
            "funnel_stage",
            "funnel_stage_label",
            "product_advertised",
            "reporting_enrichment_status",
            "reporting_enrichment_issue",
            "reporting_taxonomy_fingerprint",
            "effect_type",
        ):
            data[column] = pd.Series(index=data.index, dtype="object")
        return data
    enrichment: list[dict[str, object]] = []
    errors: list[str] = []

    for index, row in data.iterrows():
        try:
            definition, resolution = _resolve_definition(row.to_dict(), definitions)
        except ReportingEnrichmentError as exc:
            definition = None
            resolution = str(exc)
        if definition is None:
            issue = resolution or "unresolved governed activity"
            errors.append(f"row {index}: {issue}")
            values = _unclassified_values(row)
            values["reporting_enrichment_issue"] = issue
        else:
            row_market = _text(row.get("market"))
            effective_market = row_market or (
                definition.market if definition.market == "*" else "*"
            )
            values = {
                "activity_id": definition.activity_id,
                "activity_market": effective_market,
                "reporting_channel": definition.channel,
                "platform": definition.platform,
                "campaign_type": definition.campaign_type,
                "marketing_objective": definition.marketing_objective,
                "message_type": definition.message_type,
                "funnel_stage": definition.funnel_stage,
                "funnel_stage_label": FUNNEL_STAGE_LABELS[definition.funnel_stage],
                "product_advertised": definition.product_advertised,
                "reporting_enrichment_status": resolution,
                "reporting_enrichment_issue": None,
            }
        values["reporting_taxonomy_fingerprint"] = taxonomy_fingerprint
        values["effect_type"] = _resolve_effect_type(row)
        enrichment.append(values)

    if strict and errors:
        raise ReportingEnrichmentError("; ".join(errors[:12]))
    enrichment_frame = pd.DataFrame(enrichment, index=data.index)
    for column in enrichment_frame.columns:
        data[column] = enrichment_frame[column]
    return data


def _group_columns(data: pd.DataFrame, by: Sequence[str]) -> list[str]:
    dimensions = list(dict.fromkeys([*by, "effect_type"]))
    missing = [column for column in dimensions if column not in data.columns]
    if missing:
        raise ValueError(f"reporting dimensions are missing from rows: {missing}")
    return dimensions + (["posterior_draw"] if "posterior_draw" in data.columns else [])


def _cost_identity_columns(data: pd.DataFrame) -> list[str]:
    return [
        column
        for column in (
            "activity_id",
            "activity_market",
            "market",
            "outcome_id",
            "metric_key",
            "spend_point",
            "reference_context_id",
            "curve_type",
            "posterior_draw",
        )
        if column in data.columns
    ]


def roll_up_reporting_draws(
    rows: pd.DataFrame,
    *,
    by: Sequence[str],
    activity_definitions: Iterable[ActivityDefinition | Mapping[str, object]],
    strict: bool = False,
    sum_columns: Sequence[str] = (),
) -> pd.DataFrame:
    """Aggregate enriched rows at draw level for a reporting view.

    ``effect_type`` is always retained as a grouping dimension. Thus a funnel
    roll-up cannot present a mediated or halo component as a funnel total, and
    a caller must explicitly work with total rows for channel economics.
    Cost-bearing fields are populated only for total effect rows and are
    deduplicated at activity/effect context so component rows cannot count the
    same spend more than once.
    """
    data = enrich_reporting_rows(rows, activity_definitions, strict=strict)
    if data.empty:
        return data
    group_columns = _group_columns(data, by)
    present_sums = [
        column
        for column in dict.fromkeys([*ADDITIVE_MEASURES, *sum_columns])
        if column in data.columns
    ]
    grouped = data.groupby(group_columns, dropna=False, sort=False)
    if present_sums:
        result = grouped[present_sums].sum(min_count=1).reset_index()
    else:
        result = grouped.size().reset_index(name="row_count")

    cost_columns = [column for column in COST_MEASURES if column in data.columns]
    for column in cost_columns:
        result[column] = pd.NA
    total_rows = data[data["effect_type"] == "total"].copy()
    if cost_columns and not total_rows.empty:
        identity = _cost_identity_columns(total_rows)
        if identity:
            total_rows = (
                total_rows.groupby(identity, dropna=False, sort=False)[cost_columns]
                .max(min_count=1)
                .reset_index()
            )
        cost_group_columns = [
            column for column in group_columns if column in total_rows
        ]
        if cost_group_columns:
            costs = (
                total_rows.groupby(cost_group_columns, dropna=False, sort=False)[
                    cost_columns
                ]
                .sum(min_count=1)
                .reset_index()
            )
            result = result.merge(
                costs,
                on=cost_group_columns,
                how="left",
                suffixes=("", "_cost"),
            )
            for column in cost_columns:
                cost_column = f"{column}_cost"
                if cost_column in result:
                    result[column] = result[cost_column]
                    result = result.drop(columns=cost_column)

    result["spend_scope"] = result["effect_type"].map(
        lambda value: (
            "activity_or_channel_total"
            if value == "total" and cost_columns
            else "component_cost_unallocated"
        )
    )
    result["funnel_rollup_status"] = (
        "contains_unclassified"
        if data["funnel_stage"].eq("unclassified").any()
        else "complete"
    )
    if "funnel_stage" in result.columns:
        result["funnel_stage_label"] = (
            result["funnel_stage"]
            .map(FUNNEL_STAGE_LABELS)
            .fillna(FUNNEL_STAGE_LABELS["unclassified"])
        )
    result["posterior_aggregation_status"] = (
        "draw_level" if "posterior_draw" in data.columns else "no_posterior_draw"
    )
    return result


def summarize_reporting_draws(
    draws: pd.DataFrame,
    *,
    by: Sequence[str] | None = None,
    cred_mass: float = 0.9,
) -> pd.DataFrame:
    """Summarize already rolled-up posterior draws."""
    if not 0 < cred_mass < 1:
        raise ValueError("cred_mass must be between zero and one")
    if "posterior_draw" not in draws.columns:
        raise ValueError("draws must carry posterior_draw before summarization")
    dimensions = list(by or [])
    if not dimensions:
        dimensions = [
            column for column in REPORTING_DIMENSIONS if column in draws.columns
        ]
        dimensions += [
            column
            for column in ("spend_point", "curve_type", "metric_key")
            if column in draws.columns and column not in dimensions
        ]
    missing = [column for column in dimensions if column not in draws.columns]
    if missing:
        raise ValueError(f"summary dimensions are missing from draws: {missing}")
    measures = [column for column in SUMMARY_MEASURES if column in draws.columns]
    grouped = draws.groupby(dimensions, dropna=False, sort=False)
    result = grouped.first().reset_index()
    result = result[
        dimensions
        + [
            column
            for column in result.columns
            if column not in dimensions
            and column not in measures
            and column != "posterior_draw"
        ]
    ].copy()
    tail = (1.0 - cred_mass) / 2.0
    for measure in measures:
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


def build_reporting_views(
    rows: pd.DataFrame,
    activity_definitions: Iterable[ActivityDefinition | Mapping[str, object]],
    *,
    strict: bool = False,
    outcome_groups: Iterable[object] | None = None,
    outcome_group_treatments: Iterable[object] | None = None,
) -> dict[str, pd.DataFrame]:
    """Build standard funnel, channel/platform, and activity views.

    When fit-time semantic groups are supplied, their member rows are first
    combined at ``posterior_draw`` grain.  This keeps the reporting taxonomy
    a presentation layer while ensuring a grouped outcome is not counted once
    per component or once per causal pathway.
    """
    definitions = _definition_rows(activity_definitions)
    grouped_rows = rows
    if outcome_groups:
        grouping_columns = [
            column
            for column in (
                "model_run_id",
                "reference_context_id",
                "market",
                "channel",
                "model_input_column",
                "media_input_column",
                "activity_id",
                "spend_point",
                "curve_type",
                "counterfactual_axis_type",
                "posterior_draw",
            )
            if column in rows.columns
        ]
        grouped_rows = aggregate_outcome_group_draws(
            rows,
            list(outcome_groups),
            list(outcome_group_treatments or ()),
            by=grouping_columns,
        )
    enriched = enrich_reporting_rows(grouped_rows, definitions, strict=strict)
    common = [
        column
        for column in ("market", "outcome_id", "segment", "spend_point")
        if column in enriched.columns
    ]
    return {
        "funnel": roll_up_reporting_draws(
            enriched,
            by=["funnel_stage", *common],
            activity_definitions=definitions,
            strict=strict,
        ),
        "channel_platform": roll_up_reporting_draws(
            enriched,
            by=["funnel_stage", "reporting_channel", "platform", *common],
            activity_definitions=definitions,
            strict=strict,
        ),
        "activity": roll_up_reporting_draws(
            enriched,
            by=[
                "funnel_stage",
                "reporting_channel",
                "platform",
                "activity_id",
                *common,
            ],
            activity_definitions=definitions,
            strict=strict,
        ),
    }
