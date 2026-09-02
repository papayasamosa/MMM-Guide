"""Tests for `ancestry_mmm.core.named_event_response` (Decision 12
implementation). See
`docs/named_event_response_method_decision_record.md` for the decisions
these tests verify."""

import numpy as np
import pytest

from ancestry_mmm.core.named_event_response import (
    EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE,
    EVENT_RESPONSE_SHRINKAGE_PRIOR_REQUIRES_RECALIBRATION,
    GIFTING_WINDOW_POLICY,
    NAMED_EVENT_RESPONSE_STRUCTURE,
    POOLING_ELIGIBILITY_BELOW_APPROVED_THRESHOLD,
    POOLING_ELIGIBILITY_ELIGIBLE,
    POOLING_ELIGIBILITY_INSUFFICIENT_NO_THRESHOLD,
    PROMOTIONAL_WINDOW_POLICY,
    REMEMBRANCE_WINDOW_POLICY,
    TEMPORAL_TREATMENT_ANTICIPATORY,
    TEMPORAL_TREATMENT_CONTEMPORANEOUS,
    TEMPORAL_TREATMENT_POST_EVENT,
    NamedEventFamilyWindowPolicy,
    assess_family_pooling_eligibility,
    build_event_relative_design_matrix,
    build_spline_basis,
)


class TestFamilyWindowPolicies:
    def test_gifting_is_anticipatory_only(self):
        assert (
            GIFTING_WINDOW_POLICY.temporal_treatment == TEMPORAL_TREATMENT_ANTICIPATORY
        )
        assert GIFTING_WINDOW_POLICY.max_lead_weeks == 6
        assert GIFTING_WINDOW_POLICY.max_lag_weeks == 0

    def test_remembrance_is_contemporaneous_with_short_lag(self):
        assert (
            REMEMBRANCE_WINDOW_POLICY.temporal_treatment
            == TEMPORAL_TREATMENT_CONTEMPORANEOUS
        )
        assert REMEMBRANCE_WINDOW_POLICY.max_lead_weeks == 0
        assert REMEMBRANCE_WINDOW_POLICY.max_lag_weeks == 2

    def test_promotional_is_post_event_with_no_fixed_lag(self):
        assert (
            PROMOTIONAL_WINDOW_POLICY.temporal_treatment
            == TEMPORAL_TREATMENT_POST_EVENT
        )
        assert PROMOTIONAL_WINDOW_POLICY.max_lag_weeks is None

    def test_every_policy_discloses_a_basis(self):
        for policy in (
            GIFTING_WINDOW_POLICY,
            REMEMBRANCE_WINDOW_POLICY,
            PROMOTIONAL_WINDOW_POLICY,
        ):
            assert policy.basis

    def test_round_trip(self):
        restored = NamedEventFamilyWindowPolicy.from_dict(
            GIFTING_WINDOW_POLICY.to_dict()
        )
        assert restored == GIFTING_WINDOW_POLICY

    def test_rejects_unknown_temporal_treatment(self):
        with pytest.raises(ValueError, match="temporal_treatment"):
            NamedEventFamilyWindowPolicy(
                family="x",
                temporal_treatment="not_a_real_treatment",
                max_lead_weeks=1,
                max_lag_weeks=1,
                basis="test",
            )

    def test_requires_basis(self):
        with pytest.raises(ValueError, match="basis"):
            NamedEventFamilyWindowPolicy(
                family="x",
                temporal_treatment=TEMPORAL_TREATMENT_ANTICIPATORY,
                max_lead_weeks=1,
                max_lag_weeks=0,
                basis="",
            )


class TestBuildEventRelativeDesignMatrix:
    def test_factual_dates_are_never_shifted(self):
        # The occurrence week itself (offset 0) must always be marked,
        # regardless of window - this is REQ-EVENT-001's own invariant.
        design = build_event_relative_design_matrix(
            [10], 20, max_lead_weeks=2, max_lag_weeks=2
        )
        offsets = list(range(-2, 3))
        zero_col = offsets.index(0)
        assert design[10, zero_col] == 1.0

    def test_shape_matches_window(self):
        design = build_event_relative_design_matrix(
            [10, 20], 30, max_lead_weeks=6, max_lag_weeks=0
        )
        assert design.shape == (30, 7)

    def test_out_of_range_offsets_are_dropped_not_wrapped(self):
        design = build_event_relative_design_matrix(
            [1], 10, max_lead_weeks=6, max_lag_weeks=0
        )
        # week 1 - 6 = -5, out of range: must not wrap to the end.
        assert design[:, 0].sum() == 0.0

    def test_multiple_events_accumulate(self):
        design = build_event_relative_design_matrix(
            [5, 15], 20, max_lead_weeks=1, max_lag_weeks=1
        )
        assert design.sum() == 6.0  # 2 events x 3 offsets each, no overlap


class TestBuildSplineBasis:
    def test_symmetric_window_matches_wp2_evidence_shape(self):
        basis = build_spline_basis(max_lead_weeks=4, max_lag_weeks=4)
        assert basis.shape == (9, 6)

    def test_partition_of_unity_symmetric(self):
        basis = build_spline_basis(max_lead_weeks=4, max_lag_weeks=4)
        assert np.allclose(basis.sum(axis=1), 1.0)

    def test_partition_of_unity_lead_only(self):
        # Regression: this exact case (max_lag_weeks=0) previously
        # degenerated (a knot coincided with a boundary), producing an
        # all-zero row at the right edge - fixed by placing interior
        # knots at 1/4 and 3/4 of the TOTAL span, not each side's own
        # midpoint.
        basis = build_spline_basis(max_lead_weeks=6, max_lag_weeks=0)
        assert np.allclose(basis.sum(axis=1), 1.0)
        assert not np.any(np.all(basis == 0.0, axis=1))

    def test_partition_of_unity_lag_only(self):
        basis = build_spline_basis(max_lead_weeks=0, max_lag_weeks=2)
        assert np.allclose(basis.sum(axis=1), 1.0)
        assert not np.any(np.all(basis == 0.0, axis=1))

    def test_rejects_fully_degenerate_window(self):
        with pytest.raises(ValueError, match="non-degenerate"):
            build_spline_basis(max_lead_weeks=0, max_lag_weeks=0)

    def test_rejects_negative_window(self):
        with pytest.raises(ValueError):
            build_spline_basis(max_lead_weeks=-1, max_lag_weeks=1)

    def test_basis_is_non_negative(self):
        # B-spline basis functions are non-negative by construction.
        basis = build_spline_basis(max_lead_weeks=6, max_lag_weeks=2)
        assert np.all(basis >= -1e-9)


class TestGovernedConstants:
    def test_response_structure_is_s3(self):
        assert NAMED_EVENT_RESPONSE_STRUCTURE == "S3_regularised_spline_basis"

    def test_shrinkage_prior_flagged_for_recalibration(self):
        assert EVENT_RESPONSE_SHRINKAGE_PRIOR_REQUIRES_RECALIBRATION is True
        assert EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE == 1.0


class TestAssessFamilyPoolingEligibility:
    def test_no_threshold_is_never_eligible(self):
        result = assess_family_pooling_eligibility("gifting", 50)
        assert result.status == POOLING_ELIGIBILITY_INSUFFICIENT_NO_THRESHOLD
        assert result.is_eligible is False

    def test_below_threshold(self):
        result = assess_family_pooling_eligibility(
            "gifting", 3, approved_minimum_occurrences_threshold=8
        )
        assert result.status == POOLING_ELIGIBILITY_BELOW_APPROVED_THRESHOLD

    def test_meeting_threshold_is_eligible(self):
        result = assess_family_pooling_eligibility(
            "gifting", 10, approved_minimum_occurrences_threshold=8
        )
        assert result.status == POOLING_ELIGIBILITY_ELIGIBLE
        assert result.is_eligible is True

    def test_rejects_negative_occurrence_count(self):
        with pytest.raises(ValueError):
            assess_family_pooling_eligibility("gifting", -1)

    def test_rejects_threshold_below_one(self):
        with pytest.raises(ValueError):
            assess_family_pooling_eligibility(
                "gifting", 5, approved_minimum_occurrences_threshold=0
            )
