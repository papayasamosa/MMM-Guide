"""Tests for `ancestry_mmm.core.seo_partial_window_policy` (Decision 3
Phase B implementation: SEO partial-window handling policy). See
`docs/seo_partial_window_handling_decision_record.md` for the decisions
(W1-W4) these tests verify."""

import pytest

from ancestry_mmm.core.coverage import (
    STATE_MISSING_EXPECTED,
    STATE_OBSERVED_ZERO,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
)
from ancestry_mmm.core.seo_partial_window_policy import (
    ELIGIBILITY_STATUS_BELOW_APPROVED_THRESHOLD,
    ELIGIBILITY_STATUS_ELIGIBLE,
    ELIGIBILITY_STATUS_INSUFFICIENT_NO_THRESHOLD,
    ELIGIBILITY_STATUS_NO_WINDOW,
    SEO_GATED_REGRESSOR_ARCHITECTURE,
    SeoValidEstimationWindow,
    WEEK_CLASSIFICATION_AFTER_WINDOW,
    WEEK_CLASSIFICATION_BEFORE_WINDOW,
    WEEK_CLASSIFICATION_NO_WINDOW_DATA,
    WEEK_CLASSIFICATION_WITHIN_WINDOW,
    assess_seo_contribution_window_eligibility,
    build_window_diagnostic_series,
    classify_week_relative_to_window,
    determine_valid_estimation_window,
)


class TestDetermineValidEstimationWindow:
    def test_mixed_series_finds_first_and_last_queried_week(self):
        series = [
            ("2023-W01", STATE_MISSING_EXPECTED),
            ("2023-W02", STATE_MISSING_EXPECTED),
            ("2023-W03", None),  # ordinary observed fact
            ("2023-W04", STATE_OBSERVED_ZERO),
            ("2023-W05", None),
        ]
        window = determine_valid_estimation_window("UK", series)
        assert window.start_week == "2023-W03"
        assert window.end_week == "2023-W05"
        assert window.weeks_observed == 3
        assert window.has_window is True

    def test_all_never_queried_produces_no_window(self):
        series = [
            ("2023-W01", STATE_MISSING_EXPECTED),
            ("2023-W02", STATE_UNAVAILABLE_SOURCE),
            ("2023-W03", STATE_UNKNOWN),
        ]
        window = determine_valid_estimation_window("UK", series)
        assert window.start_week is None
        assert window.end_week is None
        assert window.weeks_observed == 0
        assert window.has_window is False

    def test_empty_series_produces_no_window(self):
        window = determine_valid_estimation_window("UK", [])
        assert window.has_window is False

    def test_observed_zero_counts_as_within_window(self):
        series = [("2023-W01", STATE_OBSERVED_ZERO)]
        window = determine_valid_estimation_window("UK", series)
        assert window.start_week == "2023-W01"
        assert window.weeks_observed == 1

    def test_temporary_gap_inside_window_does_not_split_the_window(self):
        # A source that goes temporarily unavailable and resumes still
        # produces one window bounded by first/last queried week - it is
        # not required to be contiguous.
        series = [
            ("2023-W01", None),
            ("2023-W02", STATE_UNAVAILABLE_SOURCE),
            ("2023-W03", None),
        ]
        window = determine_valid_estimation_window("UK", series)
        assert window.start_week == "2023-W01"
        assert window.end_week == "2023-W03"
        assert window.weeks_observed == 2  # W02 itself was not queried

    def test_requires_market(self):
        with pytest.raises(ValueError):
            determine_valid_estimation_window("", [("2023-W01", None)])

    def test_rejects_duplicate_week(self):
        with pytest.raises(ValueError, match="duplicate week"):
            determine_valid_estimation_window(
                "UK", [("2023-W01", None), ("2023-W01", STATE_OBSERVED_ZERO)]
            )

    def test_rejects_unknown_coverage_state(self):
        with pytest.raises(ValueError, match="unknown coverage_state"):
            determine_valid_estimation_window("UK", [("2023-W01", "not_a_real_state")])


class TestSeoValidEstimationWindow:
    def test_round_trip(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W01", end_week="2023-W05", weeks_observed=5
        )
        restored = SeoValidEstimationWindow.from_dict(window.to_dict())
        assert restored == window

    def test_start_and_end_must_be_present_or_absent_together(self):
        with pytest.raises(ValueError):
            SeoValidEstimationWindow(
                market="UK", start_week="2023-W01", end_week=None, weeks_observed=1
            )

    def test_end_before_start_is_rejected(self):
        with pytest.raises(ValueError):
            SeoValidEstimationWindow(
                market="UK",
                start_week="2023-W05",
                end_week="2023-W01",
                weeks_observed=1,
            )

    def test_weeks_observed_must_be_zero_when_no_window(self):
        with pytest.raises(ValueError):
            SeoValidEstimationWindow(
                market="UK", start_week=None, end_week=None, weeks_observed=1
            )


class TestClassifyWeekRelativeToWindow:
    def test_no_window_data(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week=None, end_week=None, weeks_observed=0
        )
        assert (
            classify_week_relative_to_window("2023-W01", window)
            == WEEK_CLASSIFICATION_NO_WINDOW_DATA
        )

    def test_before_within_after(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W03", end_week="2023-W05", weeks_observed=3
        )
        assert (
            classify_week_relative_to_window("2023-W01", window)
            == WEEK_CLASSIFICATION_BEFORE_WINDOW
        )
        assert (
            classify_week_relative_to_window("2023-W04", window)
            == WEEK_CLASSIFICATION_WITHIN_WINDOW
        )
        assert (
            classify_week_relative_to_window("2023-W09", window)
            == WEEK_CLASSIFICATION_AFTER_WINDOW
        )

    def test_boundary_weeks_are_within_window(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W03", end_week="2023-W05", weeks_observed=3
        )
        assert (
            classify_week_relative_to_window("2023-W03", window)
            == WEEK_CLASSIFICATION_WITHIN_WINDOW
        )
        assert (
            classify_week_relative_to_window("2023-W05", window)
            == WEEK_CLASSIFICATION_WITHIN_WINDOW
        )


class TestBuildWindowDiagnosticSeries:
    def test_classifies_full_mmm_grid_not_just_seo_weeks(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W02", end_week="2023-W03", weeks_observed=2
        )
        full_grid = ["2023-W01", "2023-W02", "2023-W03", "2023-W04"]
        diagnostics = build_window_diagnostic_series(full_grid, window)
        assert [d.classification for d in diagnostics] == [
            WEEK_CLASSIFICATION_BEFORE_WINDOW,
            WEEK_CLASSIFICATION_WITHIN_WINDOW,
            WEEK_CLASSIFICATION_WITHIN_WINDOW,
            WEEK_CLASSIFICATION_AFTER_WINDOW,
        ]


class TestAssessSeoContributionWindowEligibility:
    def test_no_window_is_never_eligible(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week=None, end_week=None, weeks_observed=0
        )
        result = assess_seo_contribution_window_eligibility(
            "UK", window, approved_minimum_weeks_threshold=10
        )
        assert result.status == ELIGIBILITY_STATUS_NO_WINDOW
        assert result.is_eligible is False

    def test_no_approved_threshold_can_never_be_eligible(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W01", end_week="2024-W01", weeks_observed=52
        )
        result = assess_seo_contribution_window_eligibility("UK", window)
        assert result.status == ELIGIBILITY_STATUS_INSUFFICIENT_NO_THRESHOLD
        assert result.is_eligible is False

    def test_below_threshold_is_not_eligible(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W01", end_week="2023-W05", weeks_observed=5
        )
        result = assess_seo_contribution_window_eligibility(
            "UK", window, approved_minimum_weeks_threshold=52
        )
        assert result.status == ELIGIBILITY_STATUS_BELOW_APPROVED_THRESHOLD
        assert result.is_eligible is False

    def test_meeting_threshold_is_eligible(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W01", end_week="2024-W01", weeks_observed=52
        )
        result = assess_seo_contribution_window_eligibility(
            "UK", window, approved_minimum_weeks_threshold=52
        )
        assert result.status == ELIGIBILITY_STATUS_ELIGIBLE
        assert result.is_eligible is True

    def test_mismatched_market_is_a_hard_error(self):
        window = SeoValidEstimationWindow(
            market="US", start_week="2023-W01", end_week="2023-W05", weeks_observed=5
        )
        with pytest.raises(ValueError, match="window.market"):
            assess_seo_contribution_window_eligibility("UK", window)

    def test_result_never_a_bare_boolean_always_disclaimed(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week=None, end_week=None, weeks_observed=0
        )
        result = assess_seo_contribution_window_eligibility("UK", window)
        assert result.disclaimer
        assert isinstance(result.to_dict(), dict)

    def test_rejects_threshold_below_one(self):
        window = SeoValidEstimationWindow(
            market="UK", start_week="2023-W01", end_week="2023-W05", weeks_observed=5
        )
        with pytest.raises(ValueError):
            assess_seo_contribution_window_eligibility(
                "UK", window, approved_minimum_weeks_threshold=0
            )


class TestGatedRegressorArchitectureMetadata:
    def test_architecture_metadata_matches_executable_w2b_integration(self):
        assert SEO_GATED_REGRESSOR_ARCHITECTURE["candidate"] == "W2-B"
        assert SEO_GATED_REGRESSOR_ARCHITECTURE["not_yet_implemented"] is False
        assert "rejected_alternative" in SEO_GATED_REGRESSOR_ARCHITECTURE
        assert (
            SEO_GATED_REGRESSOR_ARCHITECTURE["rejected_alternative"]["candidate"]
            == "W2-A"
        )
