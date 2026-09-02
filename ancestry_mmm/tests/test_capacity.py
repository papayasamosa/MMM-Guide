"""Tests for `ancestry_mmm.core.capacity` (Decisions 10/18 Phase C/E
implementation: pathway-agnostic capacity/cap semantics). See
`docs/capacity_cap_semantics_decision_record.md` for the decisions
(S, G, R4) these tests verify."""

import numpy as np
import pytest

from ancestry_mmm.core.capacity import (
    CAP_HIT_AMBIGUOUS,
    CAP_HIT_CAPPED,
    CAP_HIT_STATUSES,
    CAP_HIT_UNAVAILABLE,
    CAP_HIT_UNCAPPED,
    CAPACITY_LIMIT_KIND_SPEND,
    CapacityLimitDefinition,
    CapHitClassification,
    classify_cap_hit_status,
    classify_cap_hit_status_series,
    current_capacity_limit_versions,
    new_capacity_limit_version,
    verify_capacity_reconciliation,
)


class TestClassifyCapHitStatus:
    def test_no_cap_value_is_unavailable(self):
        result = classify_cap_hit_status(cap_value=None, point_binding=True)
        assert result.status == CAP_HIT_UNAVAILABLE
        assert result.cap_value is None

    def test_point_binding_true_is_capped(self):
        result = classify_cap_hit_status(cap_value=100.0, point_binding=True)
        assert result.status == CAP_HIT_CAPPED

    def test_point_binding_false_is_uncapped(self):
        result = classify_cap_hit_status(cap_value=100.0, point_binding=False)
        assert result.status == CAP_HIT_UNCAPPED

    def test_high_probability_is_capped(self):
        result = classify_cap_hit_status(cap_value=100.0, probability_binding=0.95)
        assert result.status == CAP_HIT_CAPPED

    def test_low_probability_is_uncapped(self):
        result = classify_cap_hit_status(cap_value=100.0, probability_binding=0.05)
        assert result.status == CAP_HIT_UNCAPPED

    def test_middle_probability_is_ambiguous(self):
        result = classify_cap_hit_status(cap_value=100.0, probability_binding=0.5)
        assert result.status == CAP_HIT_AMBIGUOUS

    def test_boundary_probabilities(self):
        # Ambiguity band is 0.20: >=0.80 capped, <=0.20 uncapped, else ambiguous.
        assert (
            classify_cap_hit_status(cap_value=1.0, probability_binding=0.80).status
            == CAP_HIT_CAPPED
        )
        assert (
            classify_cap_hit_status(cap_value=1.0, probability_binding=0.20).status
            == CAP_HIT_UNCAPPED
        )
        assert (
            classify_cap_hit_status(cap_value=1.0, probability_binding=0.21).status
            == CAP_HIT_AMBIGUOUS
        )
        assert (
            classify_cap_hit_status(cap_value=1.0, probability_binding=0.79).status
            == CAP_HIT_AMBIGUOUS
        )

    def test_a_finite_zero_cap_is_not_unavailable(self):
        result = classify_cap_hit_status(cap_value=0.0, point_binding=True)
        assert result.status == CAP_HIT_CAPPED
        assert result.cap_value == 0.0

    def test_requires_exactly_one_evidence_kind_when_cap_present(self):
        with pytest.raises(ValueError, match="exactly one"):
            classify_cap_hit_status(cap_value=1.0)
        with pytest.raises(ValueError, match="exactly one"):
            classify_cap_hit_status(
                cap_value=1.0, point_binding=True, probability_binding=0.5
            )

    def test_probability_out_of_range_rejected(self):
        with pytest.raises(ValueError):
            classify_cap_hit_status(cap_value=1.0, probability_binding=1.5)


class TestClassifyCapHitStatusSeries:
    def test_series_of_probabilities(self):
        results = classify_cap_hit_status_series(
            cap_values=[100.0, None, 50.0],
            probability_binding=[0.9, 0.5, 0.1],
        )
        assert [r.status for r in results] == [
            CAP_HIT_CAPPED,
            CAP_HIT_UNAVAILABLE,
            CAP_HIT_UNCAPPED,
        ]

    def test_series_of_point_binding(self):
        results = classify_cap_hit_status_series(
            cap_values=[100.0, 50.0], point_binding=[True, False]
        )
        assert [r.status for r in results] == [CAP_HIT_CAPPED, CAP_HIT_UNCAPPED]

    def test_requires_exactly_one_series_kind(self):
        with pytest.raises(ValueError, match="exactly one"):
            classify_cap_hit_status_series(cap_values=[1.0])
        with pytest.raises(ValueError, match="exactly one"):
            classify_cap_hit_status_series(
                cap_values=[1.0], point_binding=[True], probability_binding=[0.5]
            )

    def test_mismatched_length_rejected(self):
        with pytest.raises(ValueError, match="same length"):
            classify_cap_hit_status_series(cap_values=[1.0, 2.0], point_binding=[True])


class TestCapHitClassification:
    def test_ambiguous_requires_probability(self):
        with pytest.raises(ValueError, match="ambiguous"):
            CapHitClassification(status=CAP_HIT_AMBIGUOUS, cap_value=1.0)

    def test_unavailable_requires_no_cap_value(self):
        with pytest.raises(ValueError, match="unavailable"):
            CapHitClassification(status=CAP_HIT_UNAVAILABLE, cap_value=1.0)

    def test_non_unavailable_requires_cap_value(self):
        with pytest.raises(ValueError):
            CapHitClassification(status=CAP_HIT_CAPPED, cap_value=None)

    def test_round_trip(self):
        original = CapHitClassification(
            status=CAP_HIT_CAPPED, cap_value=100.0, probability_binding=0.9
        )
        restored = CapHitClassification.from_dict(original.to_dict())
        assert restored == original

    def test_every_status_is_a_valid_member(self):
        assert set(CAP_HIT_STATUSES) == {
            CAP_HIT_CAPPED,
            CAP_HIT_UNCAPPED,
            CAP_HIT_AMBIGUOUS,
            CAP_HIT_UNAVAILABLE,
        }


class TestVerifyCapacityReconciliation:
    def test_valid_reconciliation_passes(self):
        realised = np.array([10.0, 20.0])
        unmet = np.array([5.0, 0.0])
        potential = np.array([15.0, 20.0])
        verify_capacity_reconciliation(realised, unmet, potential)  # no raise

    def test_violation_raises(self):
        realised = np.array([10.0])
        unmet = np.array([5.0])
        potential = np.array([100.0])
        with pytest.raises(ValueError, match="reconciliation failed"):
            verify_capacity_reconciliation(realised, unmet, potential)

    def test_negative_unmet_raises(self):
        realised = np.array([10.0])
        unmet = np.array([-1.0])
        potential = np.array([9.0])
        with pytest.raises(ValueError, match="negative"):
            verify_capacity_reconciliation(realised, unmet, potential)

    def test_shape_mismatch_raises(self):
        with pytest.raises(ValueError, match="same shape"):
            verify_capacity_reconciliation(
                np.array([1.0, 2.0]), np.array([1.0]), np.array([2.0, 2.0])
            )


class TestCapacityLimitDefinition:
    def _definition(self, **overrides):
        defaults = dict(
            limit_id="uk_paid_search_cap",
            limit_version=1,
            kind=CAPACITY_LIMIT_KIND_SPEND,
            unit="GBP",
            applies_to="paid_search_uk",
            value_by_period={"2026-W01": 10000.0, "2026-W02": None},
        )
        defaults.update(overrides)
        return CapacityLimitDefinition(**defaults)

    def test_round_trip(self):
        original = self._definition()
        restored = CapacityLimitDefinition.from_dict(original.to_dict())
        assert restored == original

    def test_rejects_unknown_kind(self):
        with pytest.raises(ValueError, match="kind"):
            self._definition(kind="not_a_real_kind")

    def test_rejects_negative_period_value(self):
        with pytest.raises(ValueError, match="negative"):
            self._definition(value_by_period={"2026-W01": -1.0})

    def test_requires_applies_to(self):
        with pytest.raises(ValueError, match="applies_to"):
            self._definition(applies_to="")

    def test_new_version_increments(self):
        original = self._definition()
        updated = new_capacity_limit_version(original, notes="revised")
        assert updated.limit_version == 2
        assert updated.notes == "revised"
        assert updated.limit_id == original.limit_id

    def test_new_version_rejects_identity_change(self):
        original = self._definition()
        with pytest.raises(ValueError):
            new_capacity_limit_version(original, limit_id="other")

    def test_current_versions_resolves_latest(self):
        v1 = self._definition(limit_version=1)
        v2 = new_capacity_limit_version(v1, notes="v2")
        v3 = new_capacity_limit_version(v2, notes="v3")
        current = current_capacity_limit_versions([v1, v2, v3])
        assert len(current) == 1
        assert current[0].limit_version == 3
        assert current[0].notes == "v3"
