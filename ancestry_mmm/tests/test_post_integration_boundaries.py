"""Focused regression tests for the final production-integration boundaries."""

import pandas as pd
import pytest

from ancestry_mmm.application.fx_service import (
    FXUploadValidationError,
    build_manual_fx_rate_set,
    resolve_approved_fx_rate,
    validate_persisted_fx_rate_set,
)
from ancestry_mmm.core.experiment_lift_test_mapping import (
    LiftTestCalibrationRow,
    ModelLiftTestCalibrationInput,
)
from ancestry_mmm.core.google_trends_anchor import (
    GoogleTrendsAnchorFitInputs,
    GoogleTrendsAnchorObservation,
    GoogleTrendsQuerySetDefinition,
)
from ancestry_mmm.core.persistence import export_project, import_project
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    SearchCandidateASpec,
)


def _anchor() -> GoogleTrendsAnchorFitInputs:
    query_set = GoogleTrendsQuerySetDefinition(
        query_set_id="uk-brand-v1",
        branded_terms=("Ancestry",),
        geography="GB",
        time_range_start="2026-01-05",
        time_range_end="2026-01-12",
    )
    observations = tuple(
        GoogleTrendsAnchorObservation(
            query_set_id=query_set.query_set_id,
            week=week,
            raw_index=raw,
            anchor_value=raw / 100.0,
        )
        for week, raw in (("2026-01-05", 40.0), ("2026-01-12", 60.0))
    )
    return GoogleTrendsAnchorFitInputs(
        query_set=query_set,
        observations=observations,
        model_weeks=("2026-01-05", "2026-01-12"),
    )


def test_google_trends_fit_boundary_round_trips_without_filling_weeks():
    anchor = _anchor()
    restored = GoogleTrendsAnchorFitInputs.from_dict(anchor.to_dict())
    assert restored == anchor
    assert restored.values_for_model_weeks().tolist() == [0.4, 0.6]
    with pytest.raises(ValueError, match="missing anchor observations"):
        GoogleTrendsAnchorFitInputs(
            query_set=anchor.query_set,
            observations=anchor.observations[:1],
            model_weeks=anchor.model_weeks,
        )


def test_manual_fx_upload_builds_and_revalidates_an_annual_rate_set():
    frame = pd.DataFrame(
        [
            {
                "rate_date": "2026-01-01",
                "source_currency": "AUD",
                "target_currency": "GBP",
                "rate": "0.51",
                "method": "observed_daily",
                "frequency": "daily",
            }
        ]
    )
    rate_set, records = build_manual_fx_rate_set(
        frame,
        rate_set_id="fx-2026",
        rate_set_version=1,
        name="Finance FY2026",
        provider="finance-approved-upload",
        base_or_reference_currency="GBP",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rate_policy="FIN-FX-2026",
    )
    restored_set, restored_records = validate_persisted_fx_rate_set(
        rate_set.to_dict(), [record.to_dict() for record in records]
    )
    assert restored_set == rate_set
    assert restored_records == records


def test_approved_fx_set_resolves_latest_rate_without_a_spot_fallback():
    frame = pd.DataFrame(
        [
            {
                "rate_date": "2026-01-01",
                "source_currency": "AUD",
                "target_currency": "GBP",
                "rate": "0.51",
                "method": "observed_daily",
                "frequency": "daily",
            },
            {
                "rate_date": "2026-07-01",
                "source_currency": "AUD",
                "target_currency": "GBP",
                "rate": "0.52",
                "method": "finance_constant_dollar_annual",
                "frequency": "annual",
                "financial_year": "FY2026",
            },
        ]
    )
    rate_set, records = build_manual_fx_rate_set(
        frame,
        rate_set_id="fx-2026",
        rate_set_version=1,
        name="Finance FY2026",
        provider="finance-approved-upload",
        base_or_reference_currency="GBP",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rate_policy="FIN-FX-2026",
        approval_status="approved",
        approved_by="finance-reviewer",
        approved_at="2026-08-31T12:00:00Z",
    )
    assert (
        str(
            resolve_approved_fx_rate(
                rate_set,
                records,
                source_currency="AUD",
                target_currency="GBP",
                as_of_date="2026-12-31",
            )
        )
        == "0.52"
    )
    assert (
        resolve_approved_fx_rate(
            rate_set,
            records,
            source_currency="USD",
            target_currency="GBP",
            as_of_date="2026-12-31",
        )
        is None
    )


def test_fx_upload_rejects_unknown_method_without_a_fallback():
    with pytest.raises(FXUploadValidationError, match="Unrecognised FX conversion"):
        build_manual_fx_rate_set(
            pd.DataFrame(
                [
                    {
                        "rate_date": "2026-01-01",
                        "source_currency": "AUD",
                        "target_currency": "GBP",
                        "rate": "0.51",
                        "method": "spot_guess",
                        "frequency": "annual",
                        "financial_year": "FY2026",
                    }
                ]
            ),
            rate_set_id="fx-2026",
            rate_set_version=1,
            name="Finance FY2026",
            provider="finance-approved-upload",
            base_or_reference_currency="GBP",
            start_date="2026-01-01",
            end_date="2026-12-31",
            rate_policy="FIN-FX-2026",
        )


def test_fx_and_google_anchor_are_project_bundle_fields(tmp_path):
    fx_set, fx_records = build_manual_fx_rate_set(
        pd.DataFrame(
            [
                {
                    "rate_date": "2026-01-01",
                    "source_currency": "AUD",
                    "target_currency": "GBP",
                    "rate": "0.51",
                    "method": "finance_constant_dollar_annual",
                    "frequency": "annual",
                    "financial_year": "FY2026",
                }
            ]
        ),
        rate_set_id="fx-2026",
        rate_set_version=1,
        name="Finance FY2026",
        provider="finance-approved-upload",
        base_or_reference_currency="GBP",
        start_date="2026-01-01",
        end_date="2026-12-31",
        rate_policy="FIN-FX-2026",
    )
    path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={"joined": pd.DataFrame({"date": ["2026-01-05"]})},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        fx_rate_set=fx_set.to_dict(),
        fx_rate_records=[record.to_dict() for record in fx_records],
        google_trends_anchor=_anchor().to_dict(),
    )
    imported = import_project(path)
    assert imported["fx_rate_set"] == fx_set.to_dict()
    assert imported["fx_rate_records"] == [record.to_dict() for record in fx_records]
    assert imported["google_trends_anchor"] == _anchor().to_dict()


def test_candidate_a_fit_inputs_round_trip_preserves_observed_arrays(tmp_path):
    spec = SearchCandidateASpec(
        outcome_definition_id="fh_new",
        outcome_definition_version="1",
        outcome_definition_fingerprint="outcome-fp",
        market_scope="UK",
        demand_object_id="search-demand",
        paid_spend_object_id="paid-spend",
        paid_delivery_object_id="paid-delivery",
        paid_cap_object_id="paid-cap",
        organic_capture_object_id="organic",
        direct_navigation_object_id="direct",
    )
    fit_inputs = CandidateASearchFitInputs(
        spec=spec,
        demand_channel_names=["TV"],
        paid_search_delivery=pd.Series([1.0, 2.0]).to_numpy(),
        paid_search_cap=pd.Series([3.0, 4.0]).to_numpy(),
        organic_search_capture=pd.Series([5.0, 6.0]).to_numpy(),
        direct_navigation_capture=pd.Series([7.0, 8.0]).to_numpy(),
        google_trends_anchor=_anchor(),
    )
    restored = CandidateASearchFitInputs.from_dict(fit_inputs.to_dict())
    assert restored.spec == spec
    assert restored.demand_channel_names == ["TV"]
    assert restored.paid_search_delivery.tolist() == [1.0, 2.0]
    assert restored.google_trends_anchor == fit_inputs.google_trends_anchor

    bundle = export_project(
        tmp_path / "candidate-a-bundle.zip",
        raw_sources={"joined": pd.DataFrame({"date": ["2026-01-05"]})},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        candidate_a_fit_inputs=fit_inputs.to_dict(),
    )
    imported = import_project(bundle)
    assert imported["candidate_a_fit_inputs"] == fit_inputs.to_dict()


def test_model_calibration_requires_positive_observed_lift():
    row = LiftTestCalibrationRow(
        experiment_id="exp-1",
        experiment_version=1,
        channel="TV",
        x=10.0,
        delta_x=2.0,
        delta_y=4.0,
        sigma=1.0,
    )
    assert (
        ModelLiftTestCalibrationInput(row=row, outcome_id="fh_new").to_dict()[
            "outcome_id"
        ]
        == "fh_new"
    )
    zero_row = LiftTestCalibrationRow(
        experiment_id="exp-2",
        experiment_version=1,
        channel="TV",
        x=10.0,
        delta_x=2.0,
        delta_y=0.0,
        sigma=1.0,
    )
    with pytest.raises(ValueError, match="positive delta_y"):
        ModelLiftTestCalibrationInput(row=zero_row, outcome_id="fh_new")
