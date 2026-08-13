"""Tests for the REQ-DATAIN-001 standard source-pack boundary (WP5)."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_OUTCOMES,
    SourceVersion,
    compute_checksum,
)
from ancestry_mmm.data.loader import load_standard_workbook_with_source_version
from ancestry_mmm.data.templates import (
    STANDARD_TEMPLATE_SCHEMA_VERSION,
    activity_definitions_from_dictionary,
    canonicalize_standard_workbook,
    parse_standard_workbook,
)


def _write_workbook(tables: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            table.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def _activity_dictionary() -> pd.DataFrame:
    rows = []
    activities = [
        (
            "meta_brand",
            "paid_social",
            "Meta",
            "Brand",
            "brand_upper",
            "paid",
            "spend",
            "paid_media_cost",
        ),
        (
            "meta_mid",
            "paid_social",
            "Meta",
            "Mid",
            "mid_funnel",
            "paid",
            "spend",
            "paid_media_cost",
        ),
        (
            "meta_performance",
            "paid_social",
            "Meta",
            "Performance",
            "performance_lower",
            "paid",
            "spend",
            "paid_media_cost",
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
        ),
        (
            "crm_promotional",
            "CRM",
            "Braze",
            "Promotional",
            "cross_funnel",
            "earned",
            "earned_mentions",
            "not_applicable",
        ),
    ]
    for market in ("UK", "AU"):
        for (
            activity_id,
            channel,
            platform,
            campaign_type,
            funnel_stage,
            ownership,
            measure,
            economic,
        ) in activities:
            # The AU history deliberately omits CRM activities in the data
            # fixture below, but their governed identities remain explicit.
            rows.append(
                {
                    "activity_id": activity_id,
                    "market": market,
                    "pooling_group_id": f"pool:{activity_id}",
                    "channel": channel,
                    "platform": platform,
                    "campaign_type": campaign_type,
                    "marketing_objective": "brand awareness",
                    "funnel_stage": funnel_stage,
                    "product_advertised": "Family History",
                    "message_type": campaign_type.lower(),
                    "activity_ownership": ownership,
                    "intended_model_role": "intervention",
                    "model_input_column": f"{market.lower()}_{activity_id}",
                    "model_input_measure": measure,
                    "economic_treatment": economic,
                    "planning_eligibility": "optimisable"
                    if ownership == "paid"
                    else "fixed",
                    "source": "synthetic-uk-au-fixture",
                }
            )
    return pd.DataFrame(rows)


def _activity_data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    periods = pd.to_datetime(["2025-01-06", "2025-01-13", "2025-01-20"])
    for period in periods:
        for market in ("UK", "AU"):
            for activity_id in ("meta_brand", "meta_mid", "meta_performance"):
                rows.append(
                    {
                        "period_start": period,
                        "market": market,
                        "activity_id": activity_id,
                        "spend": 100.0,
                        "sends": pd.NA,
                        "earned_mentions": pd.NA,
                    }
                )
            # UK has the CRM history; AU has no CRM extract in this fixture.
            if market == "UK":
                rows.extend(
                    [
                        {
                            "period_start": period,
                            "market": market,
                            "activity_id": "crm_brand",
                            "spend": pd.NA,
                            "sends": 50,
                            "earned_mentions": pd.NA,
                        },
                        {
                            "period_start": period,
                            "market": market,
                            "activity_id": "crm_editorial",
                            "spend": pd.NA,
                            "sends": 75,
                            "earned_mentions": pd.NA,
                        },
                        {
                            "period_start": period,
                            "market": market,
                            "activity_id": "crm_promotional",
                            "spend": pd.NA,
                            "sends": pd.NA,
                            "earned_mentions": 3,
                        },
                    ]
                )
    return pd.DataFrame(rows)


def _activity_workbook_bytes() -> bytes:
    return _write_workbook(
        {
            "activity_data": _activity_data(),
            "activity_dictionary": _activity_dictionary(),
            "notes": pd.DataFrame({"note": ["unknown sheets are retained"]}),
        }
    )


def test_parser_reads_every_sheet_and_preserves_unknown_sheet_warning():
    workbook = parse_standard_workbook(
        _activity_workbook_bytes(),
        source_id="activity-pack",
        filename="activity-pack.xlsx",
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
    )

    assert workbook.manifest.valid_standard_template
    assert workbook.manifest.template_schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION
    assert set(workbook.tables) == {"activity_data", "activity_dictionary", "notes"}
    assert set(workbook.manifest.sheet_names) == set(workbook.tables)
    assert workbook.manifest.table_ids == (
        "activity_and_media:activity_data",
        "activity_and_media:activity_dictionary",
    )
    assert any("notes" in warning for warning in workbook.manifest.warnings)


def test_parser_requires_an_explicit_domain_when_sheets_match_multiple_domains():
    workbook = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": pd.DataFrame(
                    {"period_start": ["2025-01-01"], "market": ["UK"]}
                ),
                "activity_data": pd.DataFrame(
                    {
                        "period_start": ["2025-01-01"],
                        "market": ["UK"],
                        "activity_id": ["meta_brand"],
                    }
                ),
            }
        ),
        source_id="ambiguous-pack",
        filename="ambiguous-pack.xlsx",
    )

    assert not workbook.manifest.valid_standard_template
    assert any(
        "multiple standard domains" in error for error in workbook.manifest.errors
    )


def test_invalid_standard_workbook_reports_missing_sheet_and_column():
    workbook = parse_standard_workbook(
        _write_workbook(
            {
                "activity_data": pd.DataFrame(
                    {"period_start": ["2025-01-01"], "market": ["UK"]}
                )
            }
        ),
        source_id="invalid-pack",
        filename="invalid-pack.xlsx",
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
    )

    assert not workbook.manifest.valid_standard_template
    assert any("activity_dictionary" in error for error in workbook.manifest.errors)
    assert any(
        "activity_data" in error and "activity_id" in error
        for error in workbook.manifest.errors
    )
    with pytest.raises(ValueError, match="invalid standard workbook"):
        canonicalize_standard_workbook(workbook)


def test_activity_canonicalisation_preserves_identity_pooling_and_missingness():
    workbook = parse_standard_workbook(
        _activity_workbook_bytes(),
        source_id="activity-pack",
        filename="activity-pack.xlsx",
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
    )
    bundle = canonicalize_standard_workbook(workbook)

    assert {item.activity_id for item in bundle.activity_definitions} == {
        "meta_brand",
        "meta_mid",
        "meta_performance",
        "crm_brand",
        "crm_editorial",
        "crm_promotional",
    }
    assert all(item.pooling_group_id for item in bundle.activity_definitions)
    assert bundle.activity_column_map[("UK", "meta_brand")] == "uk_meta_brand"
    assert bundle.activity_column_map[("AU", "meta_brand")] == "au_meta_brand"
    assert "uk_crm_editorial" in bundle.model_input_media.columns
    au_rows = bundle.model_input_media.loc[bundle.model_input_media["market"] == "AU"]
    assert au_rows["uk_crm_editorial"].isna().all()
    assert bundle.raw_tables["activity_data"].shape[0] == 27


def test_context_and_outcomes_remain_native_tables_without_frequency_conversion():
    outcomes = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": pd.DataFrame(
                    {
                        "period_start": ["2025-01-01", "2025-02-01"],
                        "market": ["UK", "AU"],
                        "fh_new_signups": [10, 8],
                        "dna_cross_sell": [2, 1],
                    }
                ),
                "outcome_dictionary": pd.DataFrame(
                    {
                        "outcome_id": ["fh_new_signups"],
                        "source_column": ["fh_new_signups"],
                    }
                ),
            }
        ),
        source_id="outcome-pack",
        filename="outcome-pack.xlsx",
        logical_domain=DOMAIN_OUTCOMES,
    )
    context = parse_standard_workbook(
        _write_workbook(
            {
                "context_data": pd.DataFrame(
                    {
                        "period_start": ["2025-01-01", "2025-02-01"],
                        "market": ["UK", "UK"],
                        "variable_id": ["cpi", "brand_health"],
                        "value": [2.1, 56.0],
                        "native_frequency": ["monthly", "monthly"],
                    }
                ),
                "variable_dictionary": pd.DataFrame(
                    {
                        "variable_id": ["cpi", "brand_health"],
                        "variable_class": ["rate_index", "survey_measurement"],
                        "native_frequency": ["monthly", "monthly"],
                        "role": [
                            "exogenous_forecastable_control",
                            "historical_diagnostic_only",
                        ],
                    }
                ),
                "events": pd.DataFrame(
                    {
                        "event_id": ["launch"],
                        "event_name": ["UK launch"],
                        "start_date": ["2025-01-15"],
                        "end_date": ["2025-01-20"],
                    }
                ),
            }
        ),
        source_id="context-pack",
        filename="context-pack.xlsx",
        logical_domain=DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    )

    outcome_bundle = canonicalize_standard_workbook(outcomes)
    context_bundle = canonicalize_standard_workbook(context)
    assert list(outcome_bundle.outcomes.columns) == [
        "period_start",
        "market",
        "fh_new_signups",
        "dna_cross_sell",
    ]
    assert set(context_bundle.native_context_data["native_frequency"]) == {"monthly"}
    assert context_bundle.raw_tables["events"].iloc[0]["event_name"] == "UK launch"


def test_activity_dictionary_rejects_blank_governance_fields():
    dictionary = _activity_dictionary()
    dictionary.loc[0, "pooling_group_id"] = ""
    dictionary.loc[0, "channel"] = pd.NA

    with pytest.raises(ValueError, match="channel"):
        activity_definitions_from_dictionary(dictionary)


def test_workbook_loader_records_workbook_identity_in_source_version():
    raw_bytes = _activity_workbook_bytes()

    class Upload(BytesIO):
        name = "activity-pack.xlsx"

    upload = Upload(raw_bytes)
    workbook, version, error = load_standard_workbook_with_source_version(
        upload,
        "activity-pack",
        DOMAIN_ACTIVITY_AND_MEDIA,
    )

    assert error is None
    assert workbook is not None and version is not None
    assert version.checksum == compute_checksum(raw_bytes)
    assert version.standard_template is True
    assert version.template_schema_version == STANDARD_TEMPLATE_SCHEMA_VERSION
    assert version.parsed_table_ids == workbook.manifest.table_ids
    assert version.workbook_sheet_names == (
        "activity_data",
        "activity_dictionary",
        "notes",
    )
    assert version.template_warnings

    restored = SourceVersion.from_dict(version.to_dict())
    assert restored == version
