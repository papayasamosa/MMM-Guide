"""Small, synthetic Excel templates for the governed source-pack domains.

The templates are deliberately generated from the same column contracts used
by :mod:`ancestry_mmm.data.templates`.  They are teaching aids for source
providers, not production data and not a second source of business meaning.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    DOMAIN_OUTCOMES,
)
from ancestry_mmm.core.outcomes import (
    DNA,
    FAMILY_HISTORY,
    METRIC_KEY_DNA_KIT_SALE,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_SIGNUP,
    SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
    SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
    SEGMENT_DIMENSION_FH_CUSTOMER,
)
from ancestry_mmm.data.templates import OUTCOMES_TEMPLATE_SCHEMA_VERSION

TEMPLATE_MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

_DOMAIN_FILENAMES = {
    DOMAIN_OUTCOMES: "ancestry-mmm-outcomes-v2-template.xlsx",
    DOMAIN_ACTIVITY_AND_MEDIA: "ancestry-mmm-activity-and-media-template.xlsx",
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS: "ancestry-mmm-context-and-external-factors-template.xlsx",
    DOMAIN_EXPERIMENT_EVIDENCE: "ancestry-mmm-experiment-evidence-template.xlsx",
}


def standard_template_filename(logical_domain: str) -> str:
    """Return the download filename for one logical source domain."""

    try:
        return _DOMAIN_FILENAMES[logical_domain]
    except KeyError as exc:
        raise ValueError(
            f"unsupported standard logical domain {logical_domain!r}"
        ) from exc


def _write_workbook(tables: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            table.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def _outcome_rows() -> list[dict[str, object]]:
    return [
        {
            "outcome_id": "fh_gsa_new",
            "source_column": "fh_gsa_new",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "New",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "fh_gsa_dna_cross_sell",
            "source_column": "fh_gsa_dna_cross_sell",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "DNA cross-sell",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "fh_gsa_winback",
            "source_column": "fh_gsa_winback",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_GSA,
            "metric": "GSA",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "Winback",
            "outcome_group_id": "fh_gsa_by_customer_segment",
            "outcome_group_label": "Family History GSA",
            "outcome_family_key": METRIC_KEY_FH_GSA,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "fh_signup_new",
            "source_column": "fh_signup_new",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_SIGNUP,
            "metric": "Sign-up",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "New",
            "outcome_group_id": "fh_signup_by_customer_segment",
            "outcome_group_label": "Family History sign-up",
            "outcome_family_key": METRIC_KEY_FH_SIGNUP,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "fh_signup_dna_cross_sell",
            "source_column": "fh_signup_dna_cross_sell",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_SIGNUP,
            "metric": "Sign-up",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "DNA cross-sell",
            "outcome_group_id": "fh_signup_by_customer_segment",
            "outcome_group_label": "Family History sign-up",
            "outcome_family_key": METRIC_KEY_FH_SIGNUP,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "fh_signup_winback",
            "source_column": "fh_signup_winback",
            "product": FAMILY_HISTORY,
            "metric_key": METRIC_KEY_FH_SIGNUP,
            "metric": "Sign-up",
            "segment_dimension": SEGMENT_DIMENSION_FH_CUSTOMER,
            "segment": "Winback",
            "outcome_group_id": "fh_signup_by_customer_segment",
            "outcome_group_label": "Family History sign-up",
            "outcome_family_key": METRIC_KEY_FH_SIGNUP,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "dna_kit_new_customer",
            "source_column": "dna_kit_new_customer",
            "product": DNA,
            "metric_key": METRIC_KEY_DNA_KIT_SALE,
            "metric": "Kit sale",
            "segment_dimension": SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            "segment": "New Customer",
            "outcome_group_id": "dna_kit_by_customer_relationship",
            "outcome_group_label": "DNA kit sale by customer relationship",
            "outcome_family_key": METRIC_KEY_DNA_KIT_SALE,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "dna_kit_existing_fh_customer",
            "source_column": "dna_kit_existing_fh_customer",
            "product": DNA,
            "metric_key": METRIC_KEY_DNA_KIT_SALE,
            "metric": "Kit sale",
            "segment_dimension": SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            "segment": "Existing Family History Customer",
            "outcome_group_id": "dna_kit_by_customer_relationship",
            "outcome_group_label": "DNA kit sale by customer relationship",
            "outcome_family_key": METRIC_KEY_DNA_KIT_SALE,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "dna_kit_self",
            "source_column": "dna_kit_self",
            "product": DNA,
            "metric_key": METRIC_KEY_DNA_KIT_SALE,
            "metric": "Kit sale",
            "segment_dimension": SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            "segment": "Self",
            "outcome_group_id": "dna_kit_by_purchase_recipient",
            "outcome_group_label": "DNA kit sale by purchase recipient",
            "outcome_family_key": METRIC_KEY_DNA_KIT_SALE,
            "group_aggregation": "sum",
        },
        {
            "outcome_id": "dna_kit_someone_else",
            "source_column": "dna_kit_someone_else",
            "product": DNA,
            "metric_key": METRIC_KEY_DNA_KIT_SALE,
            "metric": "Kit sale",
            "segment_dimension": SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            "segment": "Someone Else",
            "outcome_group_id": "dna_kit_by_purchase_recipient",
            "outcome_group_label": "DNA kit sale by purchase recipient",
            "outcome_family_key": METRIC_KEY_DNA_KIT_SALE,
            "group_aggregation": "sum",
        },
    ]


def _outcomes_template_tables() -> dict[str, pd.DataFrame]:
    rows = _outcome_rows()
    periods = pd.to_datetime(["2026-01-04", "2026-01-11"])
    values: dict[str, list[int]] = {}
    for index, row in enumerate(rows, start=1):
        values[str(row["source_column"])] = [index * 10, index * 10 + 2]
    outcomes = pd.DataFrame({"period_start": periods, "market": ["UK", "AU"], **values})
    dictionary = pd.DataFrame(rows)
    dictionary["definition_version"] = "1.0"
    dictionary["event_definition"] = (
        "Synthetic example only; replace with the approved event definition."
    )
    dictionary["date_basis"] = "event_date"
    dictionary["cohort_or_attribution_basis"] = "market-period example"
    dictionary["completeness_or_maturity_policy"] = (
        "Example is complete for demonstration only."
    )
    dictionary["exclusions"] = "Synthetic example only"
    dictionary["reconciliation_source"] = "Synthetic example only"
    dictionary["business_owner"] = "Example owner - replace before use"
    dictionary["unit"] = dictionary["metric"].map(
        {"GSA": "GSA", "Sign-up": "sign-up", "Kit sale": "kits"}
    )
    dictionary["aggregation_type"] = "count"
    return {"outcomes": outcomes, "outcome_dictionary": dictionary}


def _activity_template_tables() -> dict[str, pd.DataFrame]:
    return {
        "activity_data": pd.DataFrame(
            {
                "period_start": pd.to_datetime(["2026-01-04", "2026-01-11"]),
                "market": ["UK", "UK"],
                "activity_id": ["example_tv_brand", "example_tv_brand"],
                "spend": [1000.0, 1100.0],
                "impressions": [100000, 105000],
            }
        ),
        "activity_dictionary": pd.DataFrame(
            [
                {
                    "activity_id": "example_tv_brand",
                    "market": "UK",
                    "pooling_group_id": "example_tv_brand",
                    "channel": "TV",
                    "platform": "Example broadcaster",
                    "campaign_type": "Brand",
                    "marketing_objective": "brand awareness",
                    "funnel_stage": "brand_upper",
                    "product_advertised": FAMILY_HISTORY,
                    "message_type": "brand",
                    "activity_ownership": "paid",
                    "intended_model_role": "intervention",
                    "model_input_column": "uk_example_tv_brand",
                    "model_input_measure": "spend",
                    "model_input_unit": "GBP",
                    "model_input_kind": "monetary_spend",
                    "spend_column": "spend",
                    "response_unit_column": "impressions",
                    "response_unit": "impressions",
                    "currency": "GBP",
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-12-31",
                    "economic_treatment": "paid_media_cost",
                    "planning_eligibility": "optimisable",
                    "source": "synthetic template example",
                }
            ]
        ),
    }


def _context_template_tables() -> dict[str, pd.DataFrame]:
    return {
        "context_data": pd.DataFrame(
            {
                "period_start": pd.to_datetime(["2026-01-04", "2026-01-11"]),
                "market": ["UK", "UK"],
                "variable_id": ["example_cpi", "example_cpi"],
                "value": [100.0, 100.4],
                "native_frequency": ["weekly", "weekly"],
            }
        ),
        "variable_dictionary": pd.DataFrame(
            [
                {
                    "variable_id": "example_cpi",
                    "variable_class": "rate_index",
                    "native_frequency": "weekly",
                    "role": "exogenous_forecastable_control",
                    "source": "synthetic template example",
                    "scope": "UK",
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-12-31",
                    "unit": "index",
                }
            ]
        ),
        "events": pd.DataFrame(
            [
                {
                    "event_id": "example_event",
                    "event_name": "Synthetic example event",
                    "start_date": "2026-01-08",
                    "end_date": "2026-01-10",
                }
            ]
        ),
    }


def _experiment_template_tables() -> dict[str, pd.DataFrame]:
    return {
        "experiment_evidence": pd.DataFrame(
            [
                {
                    "experiment_id": "example_lift_test",
                    "activity_id": "example_tv_brand",
                    "market": "UK",
                    "start_date": "2026-01-05",
                    "end_date": "2026-01-18",
                }
            ]
        )
    }


def build_standard_template(logical_domain: str) -> bytes:
    """Build one valid, synthetic workbook for a logical source domain.

    Outcomes always use the governed v2 contract. Other domains use their
    existing standard sheet contracts and contain non-production example rows.
    """

    builders = {
        DOMAIN_OUTCOMES: _outcomes_template_tables,
        DOMAIN_ACTIVITY_AND_MEDIA: _activity_template_tables,
        DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS: _context_template_tables,
        DOMAIN_EXPERIMENT_EVIDENCE: _experiment_template_tables,
    }
    try:
        tables = builders[logical_domain]()
    except KeyError as exc:
        raise ValueError(
            f"unsupported standard logical domain {logical_domain!r}"
        ) from exc
    return _write_workbook(tables)


__all__ = [
    "OUTCOMES_TEMPLATE_SCHEMA_VERSION",
    "TEMPLATE_MIME_TYPE",
    "build_standard_template",
    "standard_template_filename",
]
