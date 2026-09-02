"""Regression coverage for the production-data onboarding boundaries."""

from __future__ import annotations

from io import BytesIO

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.application.candidate_a_input_service import (
    build_candidate_a_fit_inputs_from_frame,
)
from ancestry_mmm.application.outcome_valuation_input_service import (
    build_weekly_outcome_valuation_records,
)
from ancestry_mmm.core.optimization import scenario_to_dict
from ancestry_mmm.core.outcome_valuation import VALUATION_KIND_FH_LTR
from ancestry_mmm.core.persistence import export_project, import_project
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    SearchCandidateASpec,
    SearchCapacityValidationError,
    slice_candidate_a_fit_inputs,
)
from ancestry_mmm.core.search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    SearchObjectDefinition,
    UNIT_EXPOSURE_COUNT,
    UNIT_INDEX,
    UNIT_MONETARY,
    UNIT_RESPONSE_COUNT,
)
from ancestry_mmm.data.template_downloads import (
    OUTCOME_VALUATION_COLUMNS,
    build_outcome_valuation_template,
)


def _search_objects() -> list[SearchObjectDefinition]:
    common = dict(
        market="*",
        state="observed",
        approval_status="approved",
        approved_by="test",
        approved_at="2026-08-15",
    )
    return [
        SearchObjectDefinition(
            "demand", SEARCH_ROLE_DEMAND, "search_demand", UNIT_INDEX, **common
        ),
        SearchObjectDefinition(
            "spend",
            SEARCH_ROLE_PAID_SPEND,
            "paid_spend",
            UNIT_MONETARY,
            currency="GBP",
            channel="paid-search",
            planning_eligibility="optimisable",
            **common,
        ),
        SearchObjectDefinition(
            "delivery",
            SEARCH_ROLE_PAID_DELIVERY,
            "paid_delivery",
            UNIT_EXPOSURE_COUNT,
            channel="paid-search",
            **common,
        ),
        SearchObjectDefinition(
            "cap",
            SEARCH_ROLE_PAID_CAP,
            "paid_cap",
            UNIT_EXPOSURE_COUNT,
            channel="paid-search",
            **common,
        ),
        SearchObjectDefinition(
            "organic",
            SEARCH_ROLE_ORGANIC_CAPTURE,
            "organic_capture",
            UNIT_RESPONSE_COUNT,
            **common,
        ),
        SearchObjectDefinition(
            "direct",
            SEARCH_ROLE_DIRECT_NAV_CAPTURE,
            "direct_capture",
            UNIT_RESPONSE_COUNT,
            **common,
        ),
    ]


def _spec() -> SearchCandidateASpec:
    return SearchCandidateASpec(
        outcome_definition_id="fh_new",
        outcome_definition_version="1",
        outcome_definition_fingerprint="outcome-fp",
        market_scope="*",
        demand_object_id="demand",
        paid_spend_object_id="spend",
        paid_delivery_object_id="delivery",
        paid_cap_object_id="cap",
        organic_capture_object_id="organic",
        direct_navigation_object_id="direct",
        cap_to_delivery_scale=2.0,
        cap_provenance="observed_platform",
        cap_provenance_status="resolved",
    )


def _model_frame() -> dict:
    return {
        "df": pd.DataFrame(
            {
                "period_start": pd.to_datetime(
                    ["2026-01-04", "2026-01-04", "2026-01-11", "2026-01-11"]
                ),
                "market": ["UK", "US", "UK", "US"],
            }
        )
    }


def _candidate_rows() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period_start": ["2026-01-11", "2026-01-04", "2026-01-11", "2026-01-04"],
            "market": ["US", "UK", "UK", "US"],
            "paid_search_delivery": [8.0, 4.0, 6.0, 2.0],
            "paid_search_cap": [4.0, 2.0, 3.0, 1.0],
            "organic_search_capture": [1.0, 2.0, 3.0, 4.0],
            "direct_navigation_capture": [2.0, 3.0, 4.0, 5.0],
        }
    )


def test_candidate_a_upload_is_exactly_aligned_and_scaled():
    fit_inputs = build_candidate_a_fit_inputs_from_frame(
        _candidate_rows(),
        model_frame=_model_frame(),
        spec=_spec(),
        demand_channel_names=["TV"],
        search_objects=_search_objects(),
    )
    assert fit_inputs.periods == (
        "2026-01-04",
        "2026-01-04",
        "2026-01-11",
        "2026-01-11",
    )
    assert fit_inputs.markets == ("UK", "US", "UK", "US")
    assert fit_inputs.paid_search_delivery.tolist() == [4.0, 2.0, 6.0, 8.0]


def test_candidate_a_upload_rejects_missing_rows_and_never_fills():
    rows = _candidate_rows().iloc[:-1]
    with pytest.raises(SearchCapacityValidationError, match="align exactly"):
        build_candidate_a_fit_inputs_from_frame(
            rows,
            model_frame=_model_frame(),
            spec=_spec(),
            demand_channel_names=["TV"],
            search_objects=_search_objects(),
        )


def test_candidate_a_fold_slice_preserves_only_pinned_rows():
    full = build_candidate_a_fit_inputs_from_frame(
        _candidate_rows(),
        model_frame=_model_frame(),
        spec=_spec(),
        demand_channel_names=["TV"],
        search_objects=_search_objects(),
    )
    sliced = slice_candidate_a_fit_inputs(
        full,
        periods=["2026-01-11", "2026-01-11"],
        markets=["UK", "US"],
    )
    assert sliced.paid_search_cap.tolist() == [3.0, 4.0]
    assert sliced.periods == ("2026-01-11", "2026-01-11")
    with pytest.raises(SearchCapacityValidationError, match="row identity"):
        slice_candidate_a_fit_inputs(
            CandidateASearchFitInputs(
                spec=_spec(),
                demand_channel_names=["TV"],
                paid_search_delivery=np.array([1.0]),
                paid_search_cap=np.array([1.0]),
                organic_search_capture=np.array([1.0]),
                direct_navigation_capture=np.array([1.0]),
            ),
            periods=["2026-01-04"],
            markets=["UK"],
        )


def test_weekly_valuation_upload_requires_governed_denominator_and_round_trips(
    tmp_path,
):
    frame = pd.DataFrame(
        [
            {
                "valuation_kind": VALUATION_KIND_FH_LTR,
                "market": "UK",
                "week": "2026-01-04",
                "segment": "New",
                "denominator_outcome_id": "fh_new",
                "quality_status": "observed_zero",
                "segment_dimension": "fh_customer_segment",
                "aggregate_value": 0.0,
                "currency": "GBP",
                "source": "Finance",
                "source_version": "v1",
                "schema_version": 1,
                "horizon_months": 48,
            }
        ]
    )
    records = build_weekly_outcome_valuation_records(
        frame,
        outcome_definitions=[{"outcome_id": "fh_new", "aggregation_type": "count"}],
    )
    assert records[0].to_dict()["horizon_months"] == 48
    with pytest.raises(ValueError, match="denominator"):
        build_weekly_outcome_valuation_records(
            frame.assign(denominator_outcome_id="not-governed"),
            outcome_definitions=[{"outcome_id": "fh_new", "aggregation_type": "count"}],
        )
    bundle = export_project(
        tmp_path / "valuations.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        outcome_valuation_records=[record.to_dict() for record in records],
    )
    imported = import_project(bundle)
    assert imported["outcome_valuation_records"] == [
        record.to_dict() for record in records
    ]


def test_saved_scenario_contains_exact_value_assumption_provenance():
    assumptions = {
        "assumptions_id": "finance-approved-2026",
        "source": "Finance",
        "currency": "GBP",
        "fh_value_by_outcome_id": {"fh_new": 123.0},
        "dna_value_by_outcome_id": {},
        "dna_mode": "overall",
    }
    scenario = scenario_to_dict(
        "test",
        "UK",
        {"TV": {"2026-01": 1.0}},
        "expected_value",
        [],
        scenario_value_assumptions=assumptions,
    )
    assert scenario["scenario_value_assumptions"] == assumptions


def test_valuation_template_has_no_numeric_example_values():
    payload = build_outcome_valuation_template()
    workbook = pd.ExcelFile(BytesIO(payload))
    assert workbook.sheet_names == ["valuation_data", "README"]
    readme = pd.read_excel(BytesIO(payload), sheet_name="README")
    assert "Finance/Analytics" in readme.iloc[0, 0]
    assert pd.read_excel(BytesIO(payload), sheet_name="valuation_data").empty
    assert OUTCOME_VALUATION_COLUMNS[0] == "valuation_kind"
