"""Deterministic source-native demo pack for the ingestion contract.

The original checked-in demo is intentionally small and rectangular so that a
new user can reach the first modelling screens quickly.  This fixture serves a
different purpose: it exercises the source-pack boundary before any data is
joined into a model-ready matrix.

It keeps activities tidy, contexts at their native frequency, and irregular
events in separate tables.  Missing rows and values are deliberate synthetic
source conditions; callers must not turn them into zeros or frequency-filled
observations implicitly.

The Outcomes tables use the governed v2 dictionary contract: Family History GSA
and sign-up are split into New, DNA cross-sell, and Winback, while DNA kit sales
show customer relationship and purchase-recipient partitions as separate
dimensions.  These are synthetic examples, not customer-level classifications.
"""

from __future__ import annotations

from typing import Dict

import pandas as pd

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


MARKETS = ("UK", "AU")
ACTIVITY_IDS = (
    "meta_brand",
    "meta_mid_funnel",
    "meta_performance",
    "crm_brand",
    "crm_editorial",
    "crm_promotional",
    "paid_search_brand",
    "paid_search_nonbrand",
    "tv_brand",
)


def _activity_dictionary() -> pd.DataFrame:
    """Return governed identities for both markets, including unavailable ones."""

    definitions = (
        (
            "meta_brand",
            "Meta",
            "Meta",
            "Brand",
            "brand_upper",
            "paid",
            "spend",
            "paid_media_cost",
            "brand awareness",
        ),
        (
            "meta_mid_funnel",
            "Meta",
            "Meta",
            "Mid-funnel",
            "mid_funnel",
            "paid",
            "spend",
            "paid_media_cost",
            "consideration",
        ),
        (
            "meta_performance",
            "Meta",
            "Meta",
            "Performance",
            "performance_lower",
            "paid",
            "spend",
            "paid_media_cost",
            "conversion",
        ),
        (
            "crm_brand",
            "CRM",
            "Braze",
            "Brand",
            "cross_funnel",
            "owned",
            "sends",
            "not_applicable",
            "brand nurture",
        ),
        (
            "crm_editorial",
            "CRM",
            "Braze",
            "Editorial",
            "cross_funnel",
            "owned",
            "sends",
            "not_applicable",
            "editorial nurture",
        ),
        (
            "crm_promotional",
            "CRM",
            "Braze",
            "Promotional",
            "cross_funnel",
            "owned",
            "sends",
            "not_applicable",
            "promotion",
        ),
        (
            "paid_search_brand",
            "Paid Search",
            "Google Ads",
            "Brand",
            "performance_lower",
            "paid",
            "spend",
            "paid_media_cost",
            "demand capture",
        ),
        (
            "paid_search_nonbrand",
            "Paid Search",
            "Google Ads",
            "Non-brand",
            "performance_lower",
            "paid",
            "spend",
            "paid_media_cost",
            "demand capture",
        ),
        (
            "tv_brand",
            "TV",
            "Linear TV",
            "Brand",
            "brand_upper",
            "paid",
            "spend",
            "paid_media_cost",
            "brand awareness",
        ),
    )
    rows: list[dict[str, object]] = []
    for market in MARKETS:
        for (
            activity_id,
            channel,
            platform,
            campaign_type,
            funnel_stage,
            ownership,
            measure,
            economic_treatment,
            objective,
        ) in definitions:
            rows.append(
                {
                    "activity_id": activity_id,
                    "market": market,
                    "pooling_group_id": f"pool:{activity_id}",
                    "channel": channel,
                    "platform": platform,
                    "campaign_type": campaign_type,
                    "marketing_objective": objective,
                    "funnel_stage": funnel_stage,
                    "product_advertised": "Family History",
                    "message_type": campaign_type.lower(),
                    "activity_ownership": ownership,
                    "intended_model_role": "intervention",
                    "model_input_column": f"{market.lower()}_{activity_id}",
                    "model_input_measure": measure,
                    "economic_treatment": economic_treatment,
                    "planning_eligibility": (
                        "optimisable" if ownership == "paid" else "fixed"
                    ),
                    "source": "synthetic-realistic-source-pack",
                }
            )
    return pd.DataFrame(rows)


def _activity_data(periods: pd.DatetimeIndex) -> pd.DataFrame:
    """Create tidy activity observations with ragged coverage and one gap."""

    rows: list[dict[str, object]] = []
    for market in MARKETS:
        market_periods = periods if market == "UK" else periods[4:]
        for index, period in enumerate(market_periods):
            values = {
                "meta_brand": 1900 + index * 17 + (200 if market == "UK" else 0),
                "meta_mid_funnel": 1400 + index * 13,
                "meta_performance": 2200 + index * 19,
                "paid_search_brand": 950 + index * 9,
                "paid_search_nonbrand": 1250 + index * 11,
                "tv_brand": 4800 + index * 25,
            }
            # TV is not present in the AU extract.  CRM has UK-only history,
            # and starts after the first two reporting periods.
            available = [
                "meta_brand",
                "meta_mid_funnel",
                "meta_performance",
                "paid_search_brand",
                "paid_search_nonbrand",
            ]
            if market == "UK":
                available.append("tv_brand")
                if index >= 2:
                    available.extend(["crm_brand", "crm_editorial", "crm_promotional"])
            for activity_id in available:
                measure = "sends" if activity_id.startswith("crm_") else "spend"
                value: object = values.get(
                    activity_id,
                    18000
                    + index * 140
                    + (500 if activity_id == "crm_editorial" else 0),
                )
                # A missing source observation is retained at its native grain;
                # canonicalisation must preserve it as missing, not zero-fill it.
                if market == "UK" and activity_id == "meta_mid_funnel" and index == 5:
                    value = pd.NA
                rows.append(
                    {
                        "period_start": period,
                        "market": market,
                        "activity_id": activity_id,
                        "spend": value if measure == "spend" else pd.NA,
                        "sends": value if measure == "sends" else pd.NA,
                    }
                )
    return pd.DataFrame(rows)


def _outcomes(periods: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for market in MARKETS:
        market_periods = periods if market == "UK" else periods[4:]
        for index, period in enumerate(market_periods):
            scale = 1.0 if market == "UK" else 0.62
            rows.append(
                {
                    "period_start": period,
                    "market": market,
                    "fh_gsa_new": int(scale * (420 + index * 7)),
                    "fh_gsa_dna_cross_sell": int(scale * (135 + index * 3)),
                    "fh_gsa_winback": int(scale * (95 + index * 2)),
                    "fh_signup_new": int(scale * (510 + index * 8)),
                    "fh_signup_dna_cross_sell": int(scale * (152 + index * 4)),
                    "fh_signup_winback": int(scale * (108 + index * 2)),
                    "dna_kit_new_customer": int(scale * (72 + index)),
                    "dna_kit_existing_fh_customer": int(scale * (31 + index)),
                    "dna_kit_self": int(scale * (55 + index)),
                    "dna_kit_someone_else": int(scale * (48 + index)),
                }
            )
    specifications = (
        (
            "fh_gsa_new",
            FAMILY_HISTORY,
            METRIC_KEY_FH_GSA,
            "GSA",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "New",
            "fh_gsa_by_customer_segment",
            "Family History GSA",
            "Family History GSA by customer segment",
            "GSA",
        ),
        (
            "fh_gsa_dna_cross_sell",
            FAMILY_HISTORY,
            METRIC_KEY_FH_GSA,
            "GSA",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "DNA cross-sell",
            "fh_gsa_by_customer_segment",
            "Family History GSA",
            "Family History GSA by customer segment",
            "GSA",
        ),
        (
            "fh_gsa_winback",
            FAMILY_HISTORY,
            METRIC_KEY_FH_GSA,
            "GSA",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "Winback",
            "fh_gsa_by_customer_segment",
            "Family History GSA",
            "Family History GSA by customer segment",
            "GSA",
        ),
        (
            "fh_signup_new",
            FAMILY_HISTORY,
            METRIC_KEY_FH_SIGNUP,
            "Sign-up",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "New",
            "fh_signup_by_customer_segment",
            "Family History sign-up",
            "Family History sign-up by customer segment",
            "sign-up",
        ),
        (
            "fh_signup_dna_cross_sell",
            FAMILY_HISTORY,
            METRIC_KEY_FH_SIGNUP,
            "Sign-up",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "DNA cross-sell",
            "fh_signup_by_customer_segment",
            "Family History sign-up",
            "Family History sign-up by customer segment",
            "sign-up",
        ),
        (
            "fh_signup_winback",
            FAMILY_HISTORY,
            METRIC_KEY_FH_SIGNUP,
            "Sign-up",
            SEGMENT_DIMENSION_FH_CUSTOMER,
            "Winback",
            "fh_signup_by_customer_segment",
            "Family History sign-up",
            "Family History sign-up by customer segment",
            "sign-up",
        ),
        (
            "dna_kit_new_customer",
            DNA,
            METRIC_KEY_DNA_KIT_SALE,
            "Kit sale",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            "New Customer",
            "dna_kit_by_customer_relationship",
            "DNA kit sale by customer relationship",
            "DNA kit sale by customer relationship",
            "kits",
        ),
        (
            "dna_kit_existing_fh_customer",
            DNA,
            METRIC_KEY_DNA_KIT_SALE,
            "Kit sale",
            SEGMENT_DIMENSION_DNA_CUSTOMER_RELATIONSHIP,
            "Existing Family History Customer",
            "dna_kit_by_customer_relationship",
            "DNA kit sale by customer relationship",
            "DNA kit sale by customer relationship",
            "kits",
        ),
        (
            "dna_kit_self",
            DNA,
            METRIC_KEY_DNA_KIT_SALE,
            "Kit sale",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            "Self",
            "dna_kit_by_purchase_recipient",
            "DNA kit sale by purchase recipient",
            "DNA kit sale by purchase recipient",
            "kits",
        ),
        (
            "dna_kit_someone_else",
            DNA,
            METRIC_KEY_DNA_KIT_SALE,
            "Kit sale",
            SEGMENT_DIMENSION_DNA_PURCHASE_RECIPIENT,
            "Someone Else",
            "dna_kit_by_purchase_recipient",
            "DNA kit sale by purchase recipient",
            "DNA kit sale by purchase recipient",
            "kits",
        ),
    )
    dictionary = pd.DataFrame(
        {
            "outcome_id": outcome_id,
            "source_column": outcome_id,
            "product": product,
            "metric_key": metric_key,
            "metric": metric,
            "segment_dimension": segment_dimension,
            "segment": segment,
            "outcome_group_id": group_id,
            "outcome_group_label": group_label,
            "outcome_family_key": metric_key,
            "group_aggregation": "sum",
            "unit": unit,
            "aggregation_type": "count",
            "event_definition": definition,
            "date_basis": "event_date",
            "cohort_or_attribution_basis": "market-period",
            "completeness_or_maturity_policy": "Synthetic fixture: observed and complete.",
            "exclusions": "Synthetic fixture only; no production exclusions.",
            "reconciliation_source": "synthetic-realistic-source-pack",
            "business_owner": "Demo only - replace before official use",
            "definition_version": "1.0",
        }
        for (
            outcome_id,
            product,
            metric_key,
            metric,
            segment_dimension,
            segment,
            group_id,
            group_label,
            definition,
            unit,
        ) in specifications
    )
    return pd.DataFrame(rows), dictionary


def _context(periods: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    for market in MARKETS:
        for month_index, period in enumerate(
            pd.date_range(periods.min().replace(day=1), periods.max(), freq="MS")
        ):
            rows.append(
                {
                    "period_start": period,
                    "market": market,
                    "variable_id": "cpi",
                    "value": 100.0 + month_index * 0.4 + (0.2 if market == "AU" else 0),
                    "native_frequency": "monthly",
                }
            )
        for index, period in enumerate(periods if market == "UK" else periods[4:]):
            rows.append(
                {
                    "period_start": period,
                    "market": market,
                    "variable_id": "consumer_confidence",
                    "value": 98.0 + index * 0.2,
                    "native_frequency": "weekly",
                }
            )
    dictionary = pd.DataFrame(
        [
            {
                "variable_id": "cpi",
                "variable_class": "rate_index",
                "native_frequency": "monthly",
                "role": "exogenous_forecastable_control",
                "unit": "index",
            },
            {
                "variable_id": "consumer_confidence",
                "variable_class": "consumer_signal",
                "native_frequency": "weekly",
                "role": "exogenous_forecastable_control",
                "unit": "index",
            },
        ]
    )
    return pd.DataFrame(rows), dictionary


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "uk_tv_launch",
                "event_name": "UK brand TV launch",
                "start_date": "2025-01-09",
                "end_date": "2025-01-19",
                "market": "UK",
            },
            {
                "event_id": "au_partner_burst",
                "event_name": "AU partner burst",
                "start_date": "2025-02-03",
                "end_date": "2025-02-05",
                "market": "AU",
            },
        ]
    )


def build_realistic_source_pack(seed: int = 17) -> Dict[str, pd.DataFrame]:
    """Return a deterministic, source-native demo pack.

    ``seed`` is part of the public helper so tests can verify reproducibility;
    the current fixture uses deterministic arithmetic, while the local RNG
    deliberately makes future synthetic extensions explicit.
    """

    if seed < 0:
        raise ValueError("seed must be non-negative")
    periods = pd.date_range("2025-01-06", periods=16, freq="W-MON")
    outcomes, outcome_dictionary = _outcomes(periods)
    context_data, variable_dictionary = _context(periods)
    return {
        "activity_data": _activity_data(periods),
        "activity_dictionary": _activity_dictionary(),
        "outcomes": outcomes,
        "outcome_dictionary": outcome_dictionary,
        "context_data": context_data,
        "variable_dictionary": variable_dictionary,
        "events": _events(),
        "segment_ltv": pd.DataFrame(
            {
                "segment": ["New", "DNA_CrossSell", "Winback"],
                "ltv": [180.0, 260.0, 110.0],
            }
        ),
    }
