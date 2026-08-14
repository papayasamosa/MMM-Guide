"""Contract tests for the source-native realistic synthetic demo (WP8)."""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_OUTCOMES,
)
from ancestry_mmm.data.loader import load_realistic_sample_sources
from ancestry_mmm.data.templates import (
    OUTCOMES_TEMPLATE_SCHEMA_VERSION,
    canonicalize_standard_workbook,
    parse_standard_workbook,
)


def _write_workbook(tables: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, table in tables.items():
            table.to_excel(writer, sheet_name=sheet_name, index=False)
    return output.getvalue()


def test_realistic_pack_is_deterministic_and_source_native():
    first, first_error = load_realistic_sample_sources()
    second, second_error = load_realistic_sample_sources()

    assert first_error is None
    assert second_error is None
    assert set(first) == {
        "activity_data",
        "activity_dictionary",
        "outcomes",
        "outcome_dictionary",
        "context_data",
        "variable_dictionary",
        "events",
        "segment_ltv",
    }
    for name in first:
        pd.testing.assert_frame_equal(first[name], second[name])


def test_activity_pack_exercises_identity_and_coverage_contracts():
    frames, error = load_realistic_sample_sources()
    assert error is None
    dictionary = frames["activity_dictionary"]
    activity_data = frames["activity_data"]

    meta = dictionary[dictionary["channel"] == "Meta"]
    assert set(meta["funnel_stage"]) == {
        "brand_upper",
        "mid_funnel",
        "performance_lower",
    }
    assert set(meta["market"]) == {"UK", "AU"}
    assert dictionary[dictionary["channel"] == "CRM"]["campaign_type"].nunique() == 3

    # The same governed activity identities can be pooled across markets, even
    # where one market has no extract for that activity.
    assert dictionary.groupby("activity_id")["pooling_group_id"].nunique().eq(1).all()
    assert activity_data[
        (activity_data["market"] == "AU")
        & activity_data["activity_id"].str.startswith("crm_")
    ].empty
    assert activity_data[
        (activity_data["market"] == "AU") & (activity_data["activity_id"] == "tv_brand")
    ].empty
    assert (
        activity_data["period_start"].nunique()
        > activity_data[activity_data["market"] == "AU"]["period_start"].nunique()
    )
    assert (
        activity_data.loc[activity_data["activity_id"] == "meta_mid_funnel", "spend"]
        .isna()
        .any()
    )


def test_realistic_pack_keeps_native_frequency_and_irregular_events():
    frames, error = load_realistic_sample_sources()
    assert error is None

    context = frames["context_data"]
    assert set(context["native_frequency"]) == {"weekly", "monthly"}
    assert set(frames["variable_dictionary"]["native_frequency"]) == {
        "weekly",
        "monthly",
    }
    events = frames["events"]
    durations = (
        pd.to_datetime(events["end_date"]) - pd.to_datetime(events["start_date"])
    ).dt.days
    assert len(events) == 2
    assert durations.nunique() == 2


def test_realistic_pack_demonstrates_canonical_outcome_breakdowns():
    frames, error = load_realistic_sample_sources()
    assert error is None

    outcomes = frames["outcomes"]
    dictionary = frames["outcome_dictionary"]
    assert {
        "fh_gsa_new",
        "fh_gsa_dna_cross_sell",
        "fh_gsa_winback",
        "fh_signup_new",
        "fh_signup_dna_cross_sell",
        "fh_signup_winback",
        "dna_kit_new_customer",
        "dna_kit_existing_fh_customer",
        "dna_kit_self",
        "dna_kit_someone_else",
    }.issubset(outcomes.columns)
    assert {
        "product",
        "metric",
        "segment_dimension",
        "segment",
        "outcome_group_id",
        "outcome_group_label",
        "outcome_family_key",
        "source_column",
    }.issubset(dictionary.columns)
    assert "cohort_basis" not in dictionary.columns
    assert "maturity_rule" not in dictionary.columns
    assert "owner" not in dictionary.columns
    assert "version" not in dictionary.columns
    assert set(dictionary.loc[dictionary["product"] == "DNA", "segment_dimension"]) == {
        "dna_customer_relationship",
        "dna_purchase_recipient",
    }
    assert set(dictionary.loc[dictionary["metric"] == "GSA", "segment"]) == {
        "New",
        "DNA cross-sell",
        "Winback",
    }

    workbook = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": outcomes,
                "outcome_dictionary": dictionary,
            }
        ),
        source_id="realistic-outcomes-v2",
        filename="realistic-outcomes-v2.xlsx",
        logical_domain=DOMAIN_OUTCOMES,
    )
    assert workbook.manifest.template_schema_version == OUTCOMES_TEMPLATE_SCHEMA_VERSION
    bundle = canonicalize_standard_workbook(workbook)
    assert {group.group_id for group in bundle.outcome_groups} == {
        "fh_gsa_by_customer_segment",
        "fh_signup_by_customer_segment",
        "dna_kit_by_customer_relationship",
        "dna_kit_by_purchase_recipient",
    }


def test_realistic_pack_canonicalises_each_domain_without_frequency_conversion():
    frames, error = load_realistic_sample_sources()
    assert error is None

    activity_workbook = parse_standard_workbook(
        _write_workbook(
            {
                "activity_data": frames["activity_data"],
                "activity_dictionary": frames["activity_dictionary"],
            }
        ),
        source_id="realistic-activity",
        filename="realistic-activity.xlsx",
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
    )
    activity_bundle = canonicalize_standard_workbook(activity_workbook)
    assert activity_workbook.manifest.valid_standard_template
    assert "uk_meta_brand" in activity_bundle.model_input_media.columns
    assert "au_meta_brand" in activity_bundle.model_input_media.columns
    assert activity_bundle.model_input_media["au_crm_brand"].isna().all()
    assert activity_bundle.model_input_media["uk_meta_mid_funnel"].isna().any()

    outcome_workbook = parse_standard_workbook(
        _write_workbook(
            {
                "outcomes": frames["outcomes"],
                "outcome_dictionary": frames["outcome_dictionary"],
            }
        ),
        source_id="realistic-outcomes",
        filename="realistic-outcomes.xlsx",
        logical_domain=DOMAIN_OUTCOMES,
    )
    outcome_bundle = canonicalize_standard_workbook(outcome_workbook)
    assert outcome_bundle.outcomes is not None
    assert len(outcome_bundle.outcomes) == len(frames["outcomes"])
    assert (
        outcome_workbook.manifest.template_schema_version
        == OUTCOMES_TEMPLATE_SCHEMA_VERSION
    )

    context_workbook = parse_standard_workbook(
        _write_workbook(
            {
                "context_data": frames["context_data"],
                "variable_dictionary": frames["variable_dictionary"],
                "events": frames["events"],
            }
        ),
        source_id="realistic-context",
        filename="realistic-context.xlsx",
        logical_domain=DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    )
    context_bundle = canonicalize_standard_workbook(context_workbook)
    assert context_bundle.native_context_data is not None
    assert set(context_bundle.native_context_data["native_frequency"]) == {
        "weekly",
        "monthly",
    }
    assert context_bundle.raw_tables["events"].shape[0] == 2
