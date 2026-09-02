"""Tests for `ancestry_mmm.core.google_trends_anchor` (Decision 9 Phase B
implementation: Google Trends brand-demand identifying anchor). See
`docs/google_trends_brand_demand_anchor_decision_record.md` for the
decisions (G1-G6) these tests verify."""

import pytest

from ancestry_mmm.core.coverage import STATE_OBSERVED_ZERO, STATE_SUPPRESSED
from ancestry_mmm.core.google_trends_anchor import (
    CANDIDATE_A_LATENT_DEMAND_STATE_ID,
    GOOGLE_TRENDS_ANCHOR_FIXED_LOADING,
    GoogleTrendsAnchorComparisonPoint,
    GoogleTrendsAnchorObservation,
    GoogleTrendsQuerySetDefinition,
    GoogleTrendsRawObservation,
    build_google_trends_identification_declaration,
    compare_anchor_to_fitted_latent_series,
    compute_anchor_series,
)
from ancestry_mmm.core.latent_state_identification import (
    STRATEGY_ANCHORED_TO_OBSERVED,
    assess_latent_state_identification,
)


def test_latent_state_id_matches_diagnostics_service_constant():
    # ancestry_mmm.core.google_trends_anchor deliberately duplicates this
    # string literal rather than importing from application.diagnostics_
    # service (core must not depend on application) - this test guards
    # the two definitions staying in sync.
    from ancestry_mmm.application.diagnostics_service import (
        CANDIDATE_A_LATENT_DEMAND_STATE_ID as diagnostics_service_constant,
    )

    assert CANDIDATE_A_LATENT_DEMAND_STATE_ID == diagnostics_service_constant


def _query_set(**overrides):
    defaults = dict(
        query_set_id="uk_ancestry_brand_v1",
        branded_terms=("ancestry", "ancestry.co.uk", "ancestry dna"),
        geography="GB",
        time_range_start="2023-01-01",
        time_range_end="2026-08-30",
        extraction_date="2026-08-30",
    )
    defaults.update(overrides)
    return GoogleTrendsQuerySetDefinition(**defaults)


class TestGoogleTrendsQuerySetDefinition:
    def test_valid_round_trip(self):
        qs = _query_set()
        restored = GoogleTrendsQuerySetDefinition.from_dict(qs.to_dict())
        assert restored == qs

    def test_requires_query_set_id(self):
        with pytest.raises(ValueError):
            _query_set(query_set_id="")

    def test_requires_at_least_one_branded_term(self):
        with pytest.raises(ValueError):
            _query_set(branded_terms=())

    def test_rejects_empty_term_in_list(self):
        with pytest.raises(ValueError):
            _query_set(branded_terms=("ancestry", ""))

    def test_requires_geography(self):
        with pytest.raises(ValueError):
            _query_set(geography="")

    def test_requires_time_range_bounds(self):
        with pytest.raises(ValueError):
            _query_set(time_range_start="")
        with pytest.raises(ValueError):
            _query_set(time_range_end="")

    def test_rejects_end_before_start(self):
        with pytest.raises(ValueError):
            _query_set(time_range_start="2026-01-01", time_range_end="2020-01-01")


class TestComputeAnchorSeries:
    def test_ordinary_series_rescales_linearly(self):
        rows = [
            GoogleTrendsRawObservation("qs1", "2026-W01", 50.0),
            GoogleTrendsRawObservation("qs1", "2026-W02", 100.0),
            GoogleTrendsRawObservation("qs1", "2026-W03", 25.0),
        ]
        series = compute_anchor_series("qs1", rows)
        by_week = {obs.week: obs for obs in series}
        assert by_week["2026-W01"].anchor_value == pytest.approx(0.5)
        assert by_week["2026-W02"].anchor_value == pytest.approx(1.0)
        assert by_week["2026-W03"].anchor_value == pytest.approx(0.25)
        assert all(obs.coverage_state is None for obs in series)

    def test_raw_zero_is_suppressed_not_observed_zero(self):
        rows = [GoogleTrendsRawObservation("qs1", "2026-W01", 0.0)]
        series = compute_anchor_series("qs1", rows)
        assert series[0].coverage_state == STATE_SUPPRESSED
        assert series[0].coverage_state != STATE_OBSERVED_ZERO
        assert series[0].anchor_value == 0.0
        assert series[0].raw_index == 0.0

    def test_result_is_sorted_by_week(self):
        rows = [
            GoogleTrendsRawObservation("qs1", "2026-W03", 10.0),
            GoogleTrendsRawObservation("qs1", "2026-W01", 20.0),
            GoogleTrendsRawObservation("qs1", "2026-W02", 30.0),
        ]
        series = compute_anchor_series("qs1", rows)
        assert [obs.week for obs in series] == ["2026-W01", "2026-W02", "2026-W03"]

    def test_mismatched_query_set_id_is_a_hard_error(self):
        rows = [
            GoogleTrendsRawObservation("qs1", "2026-W01", 50.0),
            GoogleTrendsRawObservation("qs2", "2026-W02", 60.0),
        ]
        with pytest.raises(ValueError, match="query_set_id"):
            compute_anchor_series("qs1", rows)

    def test_duplicate_week_is_a_hard_error(self):
        rows = [
            GoogleTrendsRawObservation("qs1", "2026-W01", 50.0),
            GoogleTrendsRawObservation("qs1", "2026-W01", 60.0),
        ]
        with pytest.raises(ValueError, match="duplicate week"):
            compute_anchor_series("qs1", rows)

    def test_empty_rows_produce_empty_series(self):
        assert compute_anchor_series("qs1", []) == []

    def test_requires_query_set_id_argument(self):
        with pytest.raises(ValueError):
            compute_anchor_series("", [])


class TestGoogleTrendsRawObservation:
    def test_rejects_out_of_range_index(self):
        with pytest.raises(ValueError):
            GoogleTrendsRawObservation("qs1", "2026-W01", 101.0)
        with pytest.raises(ValueError):
            GoogleTrendsRawObservation("qs1", "2026-W01", -1.0)

    def test_requires_query_set_id_and_week(self):
        with pytest.raises(ValueError):
            GoogleTrendsRawObservation("", "2026-W01", 50.0)
        with pytest.raises(ValueError):
            GoogleTrendsRawObservation("qs1", "", 50.0)


class TestGoogleTrendsAnchorObservation:
    def test_round_trip(self):
        obs = GoogleTrendsAnchorObservation(
            query_set_id="qs1",
            week="2026-W01",
            raw_index=40.0,
            anchor_value=0.4,
            coverage_state=None,
        )
        restored = GoogleTrendsAnchorObservation.from_dict(obs.to_dict())
        assert restored == obs

    def test_anchor_value_must_equal_raw_index_over_100(self):
        with pytest.raises(ValueError, match="anchor_value"):
            GoogleTrendsAnchorObservation(
                query_set_id="qs1",
                week="2026-W01",
                raw_index=40.0,
                anchor_value=0.9,
            )

    def test_raw_zero_requires_suppressed_coverage_state(self):
        with pytest.raises(ValueError, match="suppressed"):
            GoogleTrendsAnchorObservation(
                query_set_id="qs1",
                week="2026-W01",
                raw_index=0.0,
                anchor_value=0.0,
                coverage_state=None,
            )

    def test_nonzero_raw_index_rejects_suppressed_coverage_state(self):
        with pytest.raises(ValueError, match="suppressed"):
            GoogleTrendsAnchorObservation(
                query_set_id="qs1",
                week="2026-W01",
                raw_index=10.0,
                anchor_value=0.1,
                coverage_state=STATE_SUPPRESSED,
            )

    def test_rejects_unknown_coverage_state(self):
        with pytest.raises(ValueError, match="coverage_state"):
            GoogleTrendsAnchorObservation(
                query_set_id="qs1",
                week="2026-W01",
                raw_index=10.0,
                anchor_value=0.1,
                coverage_state="not_a_real_state",
            )


class TestIdentificationDeclaration:
    def test_fixed_loading_is_one(self):
        assert GOOGLE_TRENDS_ANCHOR_FIXED_LOADING == 1.0

    def test_declaration_uses_anchored_to_observed_strategy(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        assert declaration.strategy_kind == STRATEGY_ANCHORED_TO_OBSERVED
        assert declaration.latent_state_id == CANDIDATE_A_LATENT_DEMAND_STATE_ID

    def test_declaration_names_the_query_set_and_fixed_loading(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        assert qs.query_set_id in declaration.description
        assert "FIXED" in declaration.description
        assert "1.0" in declaration.description
        assert qs.query_set_id in (declaration.anchor_reference or "")

    def test_declaration_states_business_interpretation_of_one_unit(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        text = declaration.description
        assert "one unit" in text.lower() or "one point" in text.lower()
        assert "NOT one search" in text

    def test_declaration_never_estimated_language_present(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        assert "never" in declaration.description.lower()

    def test_declaration_metadata_carries_query_set_id(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        assert declaration.metadata["query_set_id"] == qs.query_set_id
        assert (
            declaration.metadata["fixed_loading"] == GOOGLE_TRENDS_ANCHOR_FIXED_LOADING
        )

    def test_declaration_is_accepted_by_latent_state_identification_module(self):
        # Regression: the declaration this module builds must be a valid,
        # consumable input to core.latent_state_identification without any
        # modification to that module (REQ-LATENT-001's own scope boundary).
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(qs)
        result = assess_latent_state_identification(
            CANDIDATE_A_LATENT_DEMAND_STATE_ID, declaration
        )
        assert result.status == "review_required"  # no chain draws supplied yet

    def test_custom_latent_state_id_is_honoured(self):
        qs = _query_set()
        declaration = build_google_trends_identification_declaration(
            qs, latent_state_id="some_other_latent_state"
        )
        assert declaration.latent_state_id == "some_other_latent_state"


class TestDiagnosticComparison:
    def test_pairs_anchor_with_fitted_values(self):
        rows = [
            GoogleTrendsRawObservation("qs1", "2026-W01", 50.0),
            GoogleTrendsRawObservation("qs1", "2026-W02", 80.0),
        ]
        series = compute_anchor_series("qs1", rows)
        fitted = {"2026-W01": 0.52, "2026-W02": 0.77}
        comparison = compare_anchor_to_fitted_latent_series(series, fitted)
        assert len(comparison) == 2
        assert comparison[0] == GoogleTrendsAnchorComparisonPoint(
            week="2026-W01",
            anchor_value=0.5,
            coverage_state=None,
            fitted_latent_value=0.52,
        )

    def test_missing_fitted_value_is_none_not_fabricated(self):
        rows = [GoogleTrendsRawObservation("qs1", "2026-W01", 50.0)]
        series = compute_anchor_series("qs1", rows)
        comparison = compare_anchor_to_fitted_latent_series(series, {})
        assert comparison[0].fitted_latent_value is None

    def test_comparison_carries_coverage_state_through(self):
        rows = [GoogleTrendsRawObservation("qs1", "2026-W01", 0.0)]
        series = compute_anchor_series("qs1", rows)
        comparison = compare_anchor_to_fitted_latent_series(series, {})
        assert comparison[0].coverage_state == STATE_SUPPRESSED
