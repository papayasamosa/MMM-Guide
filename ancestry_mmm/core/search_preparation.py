"""Product-specific preparation contracts for the historical Search stage.

The historical UK workbooks use the same physical ``spend`` and ``clicks``
column names for separate Family History and DNA accounts.  This module keeps
those accounts distinct at the governed object boundary and provides the
fail-closed preparation used before a Search graph can be approved.

This is preparation and diagnostic plumbing, not a permission to fit real UK
Search mediation.  A missing spend value is resolved only when an explicit
structural-zero evidence set names the period.  A zero click observation is
never evidence of zero spend by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence, cast

import numpy as np
import pandas as pd

from .identification_diagnostics import equation_identification_diagnostics
from .causal_graph import (
    CausalGraph,
    EDGE_ROLE_DIRECT,
    EDGE_ROLE_MEDIATED,
    NODE_ROLE_INTERVENTION,
    NODE_ROLE_MEDIATOR,
    NODE_ROLE_OUTCOME,
)
from .search_objects import (
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT,
    UNIT_MONETARY,
    SearchObjectDefinition,
    validate_search_object_catalogue,
)
from .transformations import geometric_adstock

SEARCH_PRODUCT_FAMILY_HISTORY = "family_history"
SEARCH_PRODUCT_DNA = "dna"
SEARCH_PRODUCTS = (SEARCH_PRODUCT_FAMILY_HISTORY, SEARCH_PRODUCT_DNA)

# These are graph permissions, not claims that every family has a non-zero
# posterior effect.  The model must retain shrinkage and identification
# diagnostics for the permitted candidates.
SEARCH_UPSTREAM_DRIVER_FAMILIES = (
    "brand_tv",
    "avod",
    "bvod",
    "drtv",
    "mid_funnel_olv",
    "mid_funnel_social",
    "mid_funnel_display",
    "radio",
    "podcast_audio",
    "influencer",
    "content_marketing",
    "performance_social",
    "performance_display",
    "tv_sponsorship_linear",
    "tv_sponsorship_vod",
)
SEARCH_EXCLUDED_UPSTREAM_DRIVER_FAMILIES = (
    "affiliate",
    "non_brand_search",
    "email",
)


@dataclass(frozen=True)
class ProductSearchBinding:
    """The separate governed Search identities for one product account."""

    product: str
    product_label: str
    source_activity_id: str
    spend_object_id: str
    delivery_object_id: str
    spend_source_column: str = "spend"
    delivery_source_column: str = "clicks"
    spend_model_input_column: str = ""
    delivery_model_input_column: str = ""
    source: str = "media activity - needs transforming(1).xlsx"
    currency: str = "GBP"

    def __post_init__(self) -> None:
        if self.product not in SEARCH_PRODUCTS:
            raise ValueError(f"unsupported Search product {self.product!r}")
        required = {
            "product_label": self.product_label,
            "source_activity_id": self.source_activity_id,
            "spend_object_id": self.spend_object_id,
            "delivery_object_id": self.delivery_object_id,
            "spend_model_input_column": self.spend_model_input_column,
            "delivery_model_input_column": self.delivery_model_input_column,
        }
        missing = [name for name, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(
                "Search binding fields are required: " + ", ".join(missing)
            )
        if self.spend_object_id == self.delivery_object_id:
            raise ValueError(
                "Search spend and delivery must have distinct object identities"
            )
        if self.currency != "GBP":
            raise ValueError("paid UK Search spend must use GBP")

    @property
    def object_ids(self) -> tuple[str, str]:
        return self.spend_object_id, self.delivery_object_id


@dataclass(frozen=True)
class ProductSearchGraphContract:
    """Typed graph contract for one product's multi-outcome Search stage."""

    binding: ProductSearchBinding
    outcome_node_ids: tuple[str, ...]
    mediator_lag_strategy: str = (
        "product-specific geometric adstock estimated in Search path"
    )
    spend_to_delivery_role: str = "mediated"
    delivery_to_outcome_role: str = "mediated"
    direct_spend_to_outcome_allowed: bool = False
    clicks_as_ordinary_direct_media_allowed: bool = False

    def __post_init__(self) -> None:
        if not self.outcome_node_ids:
            raise ValueError("at least one product outcome is required")
        if len(set(self.outcome_node_ids)) != len(self.outcome_node_ids):
            raise ValueError("product outcome node IDs must be unique")


def validate_product_search_graph(
    graph: CausalGraph,
    contract: ProductSearchGraphContract,
) -> tuple[str, ...]:
    """Fail closed on collapsed IDs or prohibited Search direct paths."""

    nodes = {node.node_id: node for node in graph.nodes}
    issues: list[str] = []
    binding = contract.binding
    spend_nodes = [
        node for node in graph.nodes if node.search_object_id == binding.spend_object_id
    ]
    delivery_nodes = [
        node
        for node in graph.nodes
        if node.search_object_id == binding.delivery_object_id
    ]
    if len(spend_nodes) != 1 or spend_nodes[0].role != NODE_ROLE_INTERVENTION:
        issues.append("product-specific Search spend must be one intervention node")
    if len(delivery_nodes) != 1 or delivery_nodes[0].role != NODE_ROLE_MEDIATOR:
        issues.append("product-specific Search clicks must be one mediator node")
    generic_nodes = {
        "paid_brand_search_spend",
        "paid_brand_search_clicks",
        "paid_search_spend",
        "paid_search_delivery",
    }.intersection(nodes)
    if generic_nodes:
        issues.append(
            "generic shared Search graph nodes are prohibited: "
            + ", ".join(sorted(generic_nodes))
        )
    for outcome_id in contract.outcome_node_ids:
        outcome = nodes.get(outcome_id)
        if outcome is None or outcome.role != NODE_ROLE_OUTCOME:
            issues.append(
                f"product outcome node {outcome_id!r} is missing or not an outcome"
            )
        elif outcome.product and outcome.product != binding.product_label:
            issues.append(
                f"product outcome node {outcome_id!r} has the wrong product scope"
            )
    if len(spend_nodes) == 1 and len(delivery_nodes) == 1:
        spend_id = spend_nodes[0].node_id
        delivery_id = delivery_nodes[0].node_id
        spend_to_delivery = [
            edge
            for edge in graph.edges
            if edge.source_node_id == spend_id
            and edge.target_node_id == delivery_id
            and edge.role == EDGE_ROLE_MEDIATED
        ]
        if len(spend_to_delivery) != 1:
            issues.append(
                "Search spend must have exactly one mediated edge to Search clicks"
            )
        for outcome_id in contract.outcome_node_ids:
            mediated = [
                edge
                for edge in graph.edges
                if edge.source_node_id == delivery_id
                and edge.target_node_id == outcome_id
                and edge.role == EDGE_ROLE_MEDIATED
            ]
            if len(mediated) != 1:
                issues.append(
                    f"Search clicks must have exactly one mediated edge to {outcome_id!r}"
                )
            if any(
                edge.source_node_id == delivery_id
                and edge.target_node_id == outcome_id
                and edge.role == EDGE_ROLE_DIRECT
                for edge in graph.edges
            ):
                issues.append(
                    f"Search clicks cannot also be a direct media path to {outcome_id!r}"
                )
            if any(
                edge.source_node_id == spend_id
                and edge.target_node_id == outcome_id
                and edge.role == EDGE_ROLE_DIRECT
                for edge in graph.edges
            ):
                issues.append(
                    f"Search spend cannot have a direct outcome edge to {outcome_id!r}"
                )
    return tuple(dict.fromkeys(issues))


def product_search_binding(product: str) -> ProductSearchBinding:
    """Return the documented FH or DNA source mapping without name inference."""

    if product == SEARCH_PRODUCT_FAMILY_HISTORY:
        return ProductSearchBinding(
            product=product,
            product_label="Family History",
            source_activity_id="fh_brand_search",
            spend_object_id="fh_paid_brand_search_spend",
            delivery_object_id="fh_paid_brand_search_clicks",
            spend_model_input_column="uk_fh_brand_search_spend",
            delivery_model_input_column="uk_fh_brand_search",
        )
    if product == SEARCH_PRODUCT_DNA:
        return ProductSearchBinding(
            product=product,
            product_label="DNA",
            source_activity_id="dna_brand_search",
            spend_object_id="dna_paid_brand_search_spend",
            delivery_object_id="dna_paid_brand_search_clicks",
            spend_model_input_column="uk_dna_brand_search_spend",
            delivery_model_input_column="uk_dna_brand_search",
        )
    raise ValueError(f"unsupported Search product {product!r}")


def product_search_bindings() -> tuple[ProductSearchBinding, ...]:
    return tuple(product_search_binding(product) for product in SEARCH_PRODUCTS)


def build_product_search_objects(
    product: str,
    *,
    market: str = "UK",
) -> tuple[SearchObjectDefinition, SearchObjectDefinition]:
    """Build separate draft spend and click objects for one product.

    The source workbook's shared physical column names are safe here because
    ``product`` is part of the governed source identity and catalogue
    validation.  Neither object is marked as planning or headline eligible.
    """

    binding = product_search_binding(product)
    common: dict[str, Any] = {
        "market": market,
        "channel": "Paid Search",
        "product": binding.product_label,
        "grain": "market_week",
        "state": "observed",
        "planning_eligibility": "excluded",
        "source": binding.source,
        "evidence_status": "source_mapped",
        "approval_status": "draft",
    }
    spend = SearchObjectDefinition(
        search_object_id=binding.spend_object_id,
        search_role=SEARCH_ROLE_PAID_SPEND,
        source_column=binding.spend_source_column,
        unit=UNIT_MONETARY,
        currency=binding.currency,
        model_input_column=binding.spend_model_input_column,
        **common,
    )
    delivery = SearchObjectDefinition(
        search_object_id=binding.delivery_object_id,
        search_role=SEARCH_ROLE_PAID_DELIVERY,
        source_column=binding.delivery_source_column,
        unit=UNIT_EXPOSURE_COUNT,
        model_input_column=binding.delivery_model_input_column,
        **common,
    )
    return spend, delivery


def validate_product_search_objects(
    definitions: Sequence[SearchObjectDefinition],
    *,
    market: str = "UK",
) -> tuple[str, ...]:
    """Validate that both product accounts retain separate spend/click IDs."""

    issues = [issue.detail for issue in validate_search_object_catalogue(definitions)]
    expected: dict[str, set[str]] = {
        binding.product_label: set(binding.object_ids)
        for binding in product_search_bindings()
    }
    for product, object_ids in expected.items():
        product_defs = {
            definition.search_object_id
            for definition in definitions
            if definition.market == market and definition.product == product
        }
        missing = sorted(object_ids - product_defs)
        if missing:
            issues.append(f"{product} Search objects missing: {missing}")
    all_ids = [definition.search_object_id for definition in definitions]
    generic_ids = {
        "paid_brand_search_spend",
        "paid_brand_search_clicks",
        "paid_search_spend",
        "paid_search_delivery",
    }
    reused = sorted(generic_ids.intersection(all_ids))
    if reused:
        issues.append(
            "generic shared Search identities are prohibited: " + ", ".join(reused)
        )
    return tuple(issues)


def _normalise_dates(values: Iterable[Any]) -> tuple[pd.Timestamp, ...]:
    dates = pd.to_datetime(list(values), errors="raise").normalize()
    unique = sorted(set(dates.tolist()))
    return tuple(pd.Timestamp(value) for value in unique)


@dataclass(frozen=True)
class SearchSpendCoverageResolution:
    """Auditable result of one product's spend-coverage resolution."""

    product: str
    source_activity_id: str
    target_week_count: int
    observed_spend_dates: tuple[str, ...]
    observed_zero_spend_dates: tuple[str, ...]
    structural_zero_dates: tuple[str, ...]
    unresolved_dates: tuple[str, ...]
    missing_source_row_dates: tuple[str, ...]
    missing_spend_dates: tuple[str, ...]
    zero_click_with_unresolved_spend_dates: tuple[str, ...]
    source_date_min: str | None
    source_date_max: str | None

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_dates

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "source_activity_id": self.source_activity_id,
            "target_week_count": self.target_week_count,
            "observed_spend_dates": list(self.observed_spend_dates),
            "observed_zero_spend_dates": list(self.observed_zero_spend_dates),
            "structural_zero_dates": list(self.structural_zero_dates),
            "unresolved_dates": list(self.unresolved_dates),
            "missing_source_row_dates": list(self.missing_source_row_dates),
            "missing_spend_dates": list(self.missing_spend_dates),
            "zero_click_with_unresolved_spend_dates": list(
                self.zero_click_with_unresolved_spend_dates
            ),
            "source_date_min": self.source_date_min,
            "source_date_max": self.source_date_max,
            "status": "resolved" if self.is_resolved else "unresolved",
            "zero_fill_rule": (
                "only explicit structural-zero evidence may resolve missing spend; "
                "zero clicks never infer zero spend"
            ),
        }


def resolve_product_search_spend_coverage(
    frame: pd.DataFrame,
    target_dates: Iterable[Any],
    binding: ProductSearchBinding,
    *,
    structural_zero_dates: Iterable[Any] = (),
) -> tuple[pd.DataFrame, SearchSpendCoverageResolution]:
    """Resolve observed Search spend without inventing unavailable values.

    ``structural_zero_dates`` is an explicit source-evidence input.  It is not
    inferred from clicks, spend absence, campaign boundaries, or a date range.
    The returned frame contains ``NaN`` for unresolved spend and is therefore
    safe to pass to an official-preparation gate that blocks incomplete fits.
    """

    required_columns = {"period_start", "activity_id", "spend", "clicks"}
    missing_columns = sorted(required_columns.difference(frame.columns))
    if missing_columns:
        raise ValueError(
            "Search coverage frame is missing columns: " + ", ".join(missing_columns)
        )
    dates = _normalise_dates(target_dates)
    zero_dates = set(_normalise_dates(structural_zero_dates))
    if not zero_dates.issubset(set(dates)):
        raise ValueError(
            "structural-zero evidence contains dates outside the target window"
        )
    source = frame.loc[frame["activity_id"].eq(binding.source_activity_id)].copy()
    source["period_start"] = pd.to_datetime(
        source["period_start"], errors="raise"
    ).dt.normalize()
    if source["period_start"].duplicated().any():
        raise ValueError(
            f"duplicate Search source rows for {binding.source_activity_id!r}"
        )
    by_date = source.set_index("period_start")
    rows: list[dict[str, Any]] = []
    observed_spend: list[str] = []
    observed_zero: list[str] = []
    structural_zero: list[str] = []
    unresolved: list[str] = []
    missing_source_row: list[str] = []
    missing_spend: list[str] = []
    zero_click_unresolved: list[str] = []
    for period in dates:
        key = period.strftime("%Y-%m-%d")
        present = period in by_date.index
        source_row = by_date.loc[period] if present else None
        spend = None if source_row is None else source_row["spend"]
        clicks = None if source_row is None else source_row["clicks"]
        spend_missing = spend is None or bool(pd.isna(spend))
        if period in zero_dates:
            if not spend_missing and float(cast(float, spend)) != 0.0:
                raise ValueError(
                    f"structural-zero evidence conflicts with observed spend on {key}"
                )
            resolved_spend: float | None = 0.0
            structural_zero.append(key)
            spend_status = "structural_zero_evidence"
        elif not present:
            resolved_spend = None
            unresolved.append(key)
            missing_source_row.append(key)
            spend_status = "missing_source_row"
        elif spend_missing:
            resolved_spend = None
            unresolved.append(key)
            missing_spend.append(key)
            if pd.notna(clicks) and float(cast(float, clicks)) == 0.0:
                zero_click_unresolved.append(key)
            spend_status = "missing_spend"
        else:
            resolved_spend = float(cast(float, spend))
            if resolved_spend == 0.0:
                observed_zero.append(key)
                spend_status = "observed_zero"
            else:
                observed_spend.append(key)
                spend_status = "observed"
        rows.append(
            {
                "period_start": period,
                "product": binding.product,
                "source_activity_id": binding.source_activity_id,
                "spend": resolved_spend,
                "spend_status": spend_status,
                "clicks": (
                    None
                    if clicks is None or pd.isna(clicks)
                    else float(cast(float, clicks))
                ),
                "source_row_present": present,
            }
        )
    resolution = SearchSpendCoverageResolution(
        product=binding.product,
        source_activity_id=binding.source_activity_id,
        target_week_count=len(dates),
        observed_spend_dates=tuple(observed_spend),
        observed_zero_spend_dates=tuple(observed_zero),
        structural_zero_dates=tuple(structural_zero),
        unresolved_dates=tuple(unresolved),
        missing_source_row_dates=tuple(missing_source_row),
        missing_spend_dates=tuple(missing_spend),
        zero_click_with_unresolved_spend_dates=tuple(zero_click_unresolved),
        source_date_min=(
            source["period_start"].min().strftime("%Y-%m-%d")
            if not source.empty
            else None
        ),
        source_date_max=(
            source["period_start"].max().strftime("%Y-%m-%d")
            if not source.empty
            else None
        ),
    )
    return pd.DataFrame(rows), resolution


def mediator_adstock_parameter_name(product: str, predictor: str) -> str:
    """Use a separate namespace from outcome-path adstock parameters."""

    if product not in SEARCH_PRODUCTS:
        raise ValueError(f"unsupported Search product {product!r}")
    if not str(predictor).strip():
        raise ValueError("Search mediator predictor is required")
    return f"search_mediator_adstock_decay__{product}__{predictor}"


def apply_search_mediator_adstock(
    values: Sequence[float] | np.ndarray,
    *,
    decay_rate: float,
    initial_state: float = 0.0,
    normalize: bool = True,
) -> np.ndarray:
    """Apply the governed Search-path adstock, distinct from outcome state."""

    return cast(
        np.ndarray,
        geometric_adstock(
            np.asarray(values, dtype=float),
            decay_rate=decay_rate,
            initial_state=initial_state,
            normalize=normalize,
        ),
    )


def search_mediator_equation_diagnostics(
    predictors: Any,
    labels: Sequence[str] | None = None,
    *,
    transformed_predictors: Any = None,
) -> dict[str, Any]:
    """Expose the full existing diagnostic bundle under the Search contract."""

    result = cast(
        dict[str, Any],
        equation_identification_diagnostics(
            predictors,
            labels=list(labels) if labels is not None else None,
            transformed_predictors=transformed_predictors,
        ),
    )
    # ``temporal_overlap`` is the governed flight-overlap measure in the
    # existing diagnostic service; the explicit alias makes the Search report
    # unambiguous without creating a second calculation.
    result["flight_overlap"] = result["temporal_overlap"]
    result["automatic_variable_deletion"] = False
    return result


__all__ = [
    "ProductSearchGraphContract",
    "ProductSearchBinding",
    "SEARCH_PRODUCT_DNA",
    "SEARCH_PRODUCT_FAMILY_HISTORY",
    "SEARCH_PRODUCTS",
    "SEARCH_EXCLUDED_UPSTREAM_DRIVER_FAMILIES",
    "SEARCH_UPSTREAM_DRIVER_FAMILIES",
    "SearchSpendCoverageResolution",
    "apply_search_mediator_adstock",
    "build_product_search_objects",
    "mediator_adstock_parameter_name",
    "product_search_binding",
    "product_search_bindings",
    "resolve_product_search_spend_coverage",
    "search_mediator_equation_diagnostics",
    "validate_product_search_objects",
    "validate_product_search_graph",
]
