from __future__ import annotations

from io import BytesIO

import pandas as pd

from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
)
from ancestry_mmm.data import (
    adopted_model_input_frame,
    adopted_model_input_sources,
    adopt_standard_source_bundle,
    build_standard_template,
)
from ancestry_mmm.data.loader import load_realistic_sample_sources
from ancestry_mmm.data.templates import (
    STANDARD_TEMPLATE_SCHEMA_VERSION_V2,
    canonicalize_standard_workbook,
    parse_standard_workbook,
)
from ancestry_mmm.core.official_preparation import prepare_canonical_native_frame
from ancestry_mmm.core.persistence import export_project, import_project


def _parse_template(domain: str, source_id: str):
    raw = build_standard_template(domain)
    return parse_standard_workbook(
        raw,
        source_id=source_id,
        filename=f"{source_id}.xlsx",
        logical_domain=domain,
    )


def test_downloaded_activity_and_context_templates_use_v2_semantics():
    for domain in (DOMAIN_ACTIVITY_AND_MEDIA, DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS):
        workbook = _parse_template(domain, f"template-{domain}")
        assert workbook.manifest.valid_standard_template
        assert (
            workbook.manifest.template_schema_version
            == STANDARD_TEMPLATE_SCHEMA_VERSION_V2
        )

    activity_bundle = canonicalize_standard_workbook(
        _parse_template(DOMAIN_ACTIVITY_AND_MEDIA, "template-activity")
    )
    assert activity_bundle.activity_semantic_mappings[0]["model_input_kind"] == (
        "monetary_spend"
    )
    assert activity_bundle.activity_semantic_mappings[0]["response_unit"] == (
        "impressions"
    )


def test_legacy_context_pack_remains_v1_and_is_not_upgraded_by_unit_column():
    frames, error = load_realistic_sample_sources()
    assert error is None
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name in ("context_data", "variable_dictionary", "events"):
            frames[name].to_excel(writer, sheet_name=name, index=False)
    workbook = parse_standard_workbook(
        output.getvalue(),
        source_id="legacy-context",
        filename="legacy-context.xlsx",
        logical_domain=DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    )
    assert workbook.manifest.valid_standard_template
    assert (
        workbook.manifest.template_schema_version != STANDARD_TEMPLATE_SCHEMA_VERSION_V2
    )
    bundle = canonicalize_standard_workbook(workbook)
    assert {item["native_frequency"] for item in bundle.context_variable_metadata} == {
        "weekly",
        "monthly",
    }


def test_adoption_merges_markets_and_preserves_explicit_activity_semantics():
    rows = []
    observations = []
    for market in ("UK", "AU"):
        for activity_id, ownership, measure, treatment, planning in (
            ("paid", "paid", "spend", "paid_media_cost", "optimisable"),
            ("owned", "owned", "delivery", "response_only", "fixed"),
            ("earned", "earned", "delivery", "response_only", "fixed"),
        ):
            model_column = f"{market.lower()}_{activity_id}"
            rows.append(
                {
                    "activity_id": activity_id,
                    "market": market,
                    "pooling_group_id": f"pool:{activity_id}",
                    "channel": activity_id,
                    "platform": "synthetic",
                    "campaign_type": "test",
                    "marketing_objective": "acquisition",
                    "funnel_stage": "mid_funnel",
                    "product_advertised": "Family History",
                    "message_type": "test",
                    "activity_ownership": ownership,
                    "intended_model_role": "intervention",
                    "model_input_column": model_column,
                    "model_input_measure": measure,
                    "model_input_unit": "GBP" if measure == "spend" else "impressions",
                    "model_input_kind": (
                        "monetary_spend" if measure == "spend" else "observed_delivery"
                    ),
                    "spend_column": "spend" if measure == "spend" else None,
                    "response_unit_column": "impressions"
                    if measure == "spend"
                    else "delivery",
                    "response_unit": "impressions",
                    "currency": "GBP" if measure == "spend" else None,
                    "effective_from": "2026-01-01",
                    "effective_to": "2026-12-31",
                    "economic_treatment": treatment,
                    "planning_eligibility": planning,
                    "source": "synthetic-test",
                }
            )
            observations.append(
                {
                    "period_start": pd.Timestamp("2026-01-05"),
                    "market": market,
                    "activity_id": activity_id,
                    "spend": 100.0 if measure == "spend" else pd.NA,
                    "delivery": 1000.0 if measure == "delivery" else pd.NA,
                    "impressions": 1000.0,
                }
            )
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame(observations).to_excel(
            writer, sheet_name="activity_data", index=False
        )
        pd.DataFrame(rows).to_excel(
            writer, sheet_name="activity_dictionary", index=False
        )
    workbook = parse_standard_workbook(
        output.getvalue(),
        source_id="activity-multi-market",
        filename="activity-multi-market.xlsx",
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
    )
    bundle = canonicalize_standard_workbook(workbook)
    adoption = adopt_standard_source_bundle(bundle)
    assert {item.market for item in adoption.activity_definitions} == {"UK", "AU"}
    assert {item.activity_ownership for item in adoption.activity_definitions} == {
        "paid",
        "owned",
        "earned",
    }
    assert set(adoption.activity_model_input.columns) >= {
        "uk_paid",
        "au_owned",
    }
    assert (
        adoption.semantic_statuses[0].status == "adopted_with_physical_mapping_review"
    )
    assert "ChannelMediaUnitConfig" not in adoption.semantic_statuses[0].adopted_objects


def test_context_adoption_keeps_native_rows_for_mixed_frequency_review():
    frames, error = load_realistic_sample_sources()
    assert error is None
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for name in ("context_data", "variable_dictionary", "events"):
            frames[name].to_excel(writer, sheet_name=name, index=False)
    bundle = canonicalize_standard_workbook(
        parse_standard_workbook(
            output.getvalue(),
            source_id="mixed-context",
            filename="mixed-context.xlsx",
            logical_domain=DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
        )
    )
    adoption = adopt_standard_source_bundle(bundle)
    assert adoption.context_data is not None
    assert adoption.context_data["cpi"].notna().any()
    assert adoption.context_data["consumer_confidence"].notna().any()
    sources = adopted_model_input_sources(
        outcome_data=None,
        activity_model_input=None,
        context_model_input=adoption.context_data,
        context_variable_metadata=adoption.context_variable_metadata,
    )
    assert sources is not None
    assert "standard_context" in sources


def test_experiment_adoption_retains_evidence_status_without_calibration():
    bundle = canonicalize_standard_workbook(
        _parse_template(DOMAIN_EXPERIMENT_EVIDENCE, "experiment-pack")
    )
    adoption = adopt_standard_source_bundle(bundle)
    status = adoption.semantic_statuses[0]
    assert status.status == "source_evidence_only"
    assert status.details[0]["experiment_id"] == "example_lift_test"
    assert adoption.experiment_evidence is not None
    assert adoption.experiment_evidence.loc[0, "experiment_id"] == "example_lift_test"
    assert "CalibrationRecord" not in status.adopted_objects


def test_all_four_domain_packs_accumulate_into_the_official_source_boundary():
    adoption = None
    for index, domain in enumerate(
        (
            "outcomes",
            DOMAIN_ACTIVITY_AND_MEDIA,
            DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
            DOMAIN_EXPERIMENT_EVIDENCE,
        )
    ):
        source_id = f"pack-{index}"
        bundle = canonicalize_standard_workbook(_parse_template(domain, source_id))
        adoption = adopt_standard_source_bundle(
            bundle,
            activity_definitions=adoption.activity_definitions if adoption else (),
            activity_model_input=adoption.activity_model_input if adoption else None,
            outcome_data=adoption.outcome_data if adoption else None,
            context_data=adoption.context_data if adoption else None,
            context_variable_metadata=(
                adoption.context_variable_metadata if adoption else ()
            ),
            semantic_statuses=adoption.semantic_statuses if adoption else (),
        )

    assert adoption is not None
    assert {item.logical_domain for item in adoption.semantic_statuses} == {
        "outcomes",
        DOMAIN_ACTIVITY_AND_MEDIA,
        DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
        DOMAIN_EXPERIMENT_EVIDENCE,
    }
    sources = adopted_model_input_sources(
        outcome_data=adoption.outcome_data,
        activity_model_input=adoption.activity_model_input,
        context_model_input=adoption.context_data,
        context_variable_metadata=adoption.context_variable_metadata,
    )
    assert sources is not None
    prepared = prepare_canonical_native_frame(
        sources,
        date_col="period_start",
        market_col="market",
        governed_start="2026-01-05",
        governed_end="2026-01-12",
        governed_frequency="weekly",
        pipeline_steps=[],
    )
    assert set(prepared.frame["period_start"].dt.strftime("%Y-%m-%d")) == {
        "2026-01-05",
        "2026-01-12",
    }


def test_adopted_frames_outer_join_multiple_domains_without_filling_missingness():
    outcome = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2026-01-05"]),
            "market": ["UK"],
            "outcome": [10],
        }
    )
    activity = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2026-01-12"]),
            "market": ["UK"],
            "tv": [100.0],
        }
    )
    joined = adopted_model_input_frame(
        outcome_data=outcome,
        activity_model_input=activity,
        context_model_input=None,
    )
    assert joined is not None
    assert len(joined) == 2
    assert (
        joined.loc[joined["period_start"] == pd.Timestamp("2026-01-05"), "tv"]
        .isna()
        .all()
    )


def test_standard_adoption_frames_and_semantics_round_trip(tmp_path):
    activity = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2026-01-05"]),
            "market": ["UK"],
            "tv": [100.0],
        }
    )
    context = pd.DataFrame(
        {
            "period_start": pd.to_datetime(["2026-01-05"]),
            "market": ["UK"],
            "cpi": [100.0],
        }
    )
    statuses = [
        {
            "source_id": "context",
            "logical_domain": "context_and_external_factors",
            "schema_version": "standard-source-pack-v2",
            "status": "adopted",
            "table_ids": ["context_data"],
        }
    ]
    path = export_project(
        tmp_path / "standard-pack.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        standard_activity_model_input=activity,
        standard_context_data=context,
        context_variable_metadata=[
            {"variable_id": "cpi", "native_frequency": "weekly"}
        ],
        source_domain_semantics=statuses,
    )
    imported = import_project(path)
    pd.testing.assert_frame_equal(imported["standard_activity_model_input"], activity)
    pd.testing.assert_frame_equal(imported["standard_context_data"], context)
    assert imported["context_variable_metadata"] == [
        {"variable_id": "cpi", "native_frequency": "weekly"}
    ]
    assert imported["source_domain_semantics"] == statuses
    assert imported["manifest"]["contains"]["source_domain_semantics"]
