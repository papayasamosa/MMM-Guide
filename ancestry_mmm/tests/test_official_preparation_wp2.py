"""WP2 tests for canonical official preparation and consumed coverage."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ancestry_mmm.core.coverage import (
    FrequencyMetadata,
    VariableCoverageMatrix,
    VariableCoverageRecord,
)
from ancestry_mmm.core.fingerprint import fingerprint_model_spec
from ancestry_mmm.core.official_preparation import (
    OfficialPreparationDataError,
    build_official_capability_report,
    prepare_canonical_native_frame,
)
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, OutcomeDefinition
from ancestry_mmm.core.persistence import export_project, import_project
from ancestry_mmm.core.schema import ModelSpec


def _spec() -> ModelSpec:
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        channels=["tv_spend"],
        segment_outcomes={"New": "gsa"},
        control_cols=["cpi"],
        outcome_promo_cols={"fh_new_gsa": "promo"},
    )


def _outcome() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id="fh_new_gsa",
        product=FAMILY_HISTORY,
        segment="New",
        metric=METRIC_GSA,
        source_column="gsa",
    )


def _matrix(*variable_ids: str) -> VariableCoverageMatrix:
    return VariableCoverageMatrix(
        matrix_id="coverage-1",
        matrix_version=1,
        generated_at="2026-08-14",
        records=tuple(
            VariableCoverageRecord(
                variable_id=variable_id,
                source_id=f"source-{variable_id}",
                source_version=1,
                market="UK",
                frequency=FrequencyMetadata(
                    native_frequency="weekly",
                    target_frequency="weekly",
                    variable_class="flow_count",
                ),
                coverage_segments=(),
            )
            for variable_id in variable_ids
        ),
    )


def test_official_native_join_preserves_union_and_missing_values():
    sources = {
        "media": pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01", "2024-01-08"]),
                "market": ["UK", "UK"],
                "tv_spend": [10.0, 20.0],
            }
        ),
        "outcomes": pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-08", "2024-01-15"]),
                "market": ["UK", "UK"],
                "gsa": [2.0, 3.0],
            }
        ),
    }

    result = prepare_canonical_native_frame(
        sources,
        date_col="date",
        market_col="market",
        governed_start="2024-01-01",
        governed_end="2024-01-22",
        governed_frequency="weekly",
    )

    assert result.union_periods == (
        "2024-01-01",
        "2024-01-08",
        "2024-01-15",
        "2024-01-22",
    )
    assert len(result.frame) == 4
    assert np.isnan(
        result.frame.loc[result.frame["date"] == pd.Timestamp("2024-01-01"), "gsa"]
    ).all()
    assert np.isnan(
        result.frame.loc[result.frame["date"] == pd.Timestamp("2024-01-15"), "tv_spend"]
    ).all()
    assert np.isnan(
        result.frame.loc[result.frame["date"] == pd.Timestamp("2024-01-22"), "tv_spend"]
    ).all()
    assert np.isnan(
        result.frame.loc[result.frame["date"] == pd.Timestamp("2024-01-22"), "gsa"]
    ).all()
    assert result.join_diagnostics["join_mode"] == "outer"


def test_official_native_path_rejects_exploratory_missingness_operations():
    sources = {
        "source": pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-01"]),
                "market": ["UK"],
                "tv_spend": [10.0],
            }
        )
    }
    for operation in ("fill_missing", "drop_columns"):
        try:
            prepare_canonical_native_frame(
                sources,
                date_col="date",
                market_col="market",
                governed_start="2024-01-01",
                governed_end="2024-01-01",
                governed_frequency="weekly",
                pipeline_steps=[{"op": operation, "params": {}}],
            )
        except OfficialPreparationDataError as exc:
            assert "exploratory-only" in str(exc) or "not approved" in str(exc)
        else:
            raise AssertionError(
                f"{operation} unexpectedly passed official preparation"
            )


def test_consumed_capability_covers_outcome_media_control_and_promotion():
    matrix = _matrix("gsa", "tv_spend", "cpi", "promo", "unused")
    report = build_official_capability_report(_spec(), [_outcome()], matrix)

    assert report.supported
    by_variable = {item.variable_id: item for item in report.consumed_variables}
    assert set(by_variable) == {"cpi", "gsa", "promo", "tv_spend"}
    assert "unused" not in by_variable
    assert "outcome" in by_variable["gsa"].roles
    assert "media" in by_variable["tv_spend"].roles
    assert "control" in by_variable["cpi"].roles
    assert "promotion" in by_variable["promo"].roles


def test_unconsumed_gap_does_not_block_but_consumed_gap_does():
    unresolved = VariableCoverageRecord(
        variable_id="unused",
        source_id="source-unused",
        source_version=1,
        market="UK",
        frequency=FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        ),
        coverage_segments=(),
    )
    # The record is fully observed in this matrix, so use a missing consumed
    # record to prove the report is scoped rather than trusting frame values.
    report = build_official_capability_report(
        _spec(),
        [_outcome()],
        VariableCoverageMatrix(
            matrix_id="coverage-2",
            matrix_version=1,
            generated_at="2026-08-14",
            records=(unresolved,),
        ),
    )
    assert not report.supported
    assert any("no coverage record" in issue for issue in report.blocking_issues)


def test_official_preparation_evidence_changes_model_identity():
    spec = _spec().to_dict()
    base = fingerprint_model_spec(spec, {}, 4)
    weekly = fingerprint_model_spec(
        spec,
        {},
        4,
        official_preparation_evidence={
            "status": "ready",
            "canonical_calendar": {"start": "2024-01-01", "end": "2024-01-15"},
        },
    )
    changed = fingerprint_model_spec(
        spec,
        {},
        4,
        official_preparation_evidence={
            "status": "ready",
            "canonical_calendar": {"start": "2024-01-08", "end": "2024-01-15"},
        },
    )
    assert weekly != base
    assert weekly != changed


def test_official_preparation_evidence_round_trips(tmp_path):
    official_data = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01"]),
            "market": ["UK"],
            "tv_spend": [10.0],
        }
    )
    result = {
        "status": "ready",
        "canonical_calendar": {
            "start": "2024-01-01",
            "end": "2024-01-01",
            "frequency": "weekly",
        },
        "ready": True,
    }
    capability = {"supported": True, "consumed_variables": []}
    bundle = export_project(
        tmp_path / "official.zip",
        raw_sources={"source": official_data},
        transformed_data=official_data,
        pipeline_steps=[],
        model_spec=None,
        prior_config={},
        dna_lag_weeks=4,
        trace=None,
        scenarios=[],
        canonical_calendar=result["canonical_calendar"],
        official_preparation_result=result,
        official_capability_report=capability,
        official_prepared_data=official_data,
        official_join_diagnostics={"join_mode": "outer"},
    )
    imported = import_project(bundle)
    assert imported["canonical_calendar"] == result["canonical_calendar"]
    assert imported["official_preparation_result"] == result
    assert imported["official_capability_report"] == capability
    assert imported["official_join_diagnostics"] == {"join_mode": "outer"}
    pd.testing.assert_frame_equal(imported["official_prepared_data"], official_data)
