"""Tests for `ancestry_mmm.core.planning.planned_activity`
(`REQ-PLANACT-001`; Decision 14). See
`docs/planned_activity_and_promotion_inputs_decision_record.md`.

`TestMaterializePromoFutureIntegratesWithBuildFutureContext` proves the
real, end-to-end wiring claim: a structured `PromotionPeriod` list
materialises into a `promo_future` mapping that
`core.planning.future_context.build_future_context` (completely
unmodified) accepts and uses correctly - not merely a parallel,
never-consumed contract.
"""

import pytest

from ancestry_mmm.core.planning.future_context import (
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.planned_activity import (
    OVERLAP_POLICY_MAX,
    OVERLAP_POLICY_REJECT,
    PlannedActivity,
    PlannedActivityAndPromotionInputs,
    PromotionPeriod,
    materialize_promo_future,
)

WEEKS = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26"]


class TestPromotionPeriodValidation:
    def test_start_after_end_rejected(self):
        with pytest.raises(ValueError):
            PromotionPeriod(
                promotion_id="p1",
                outcome_id="New",
                start_week="2026-02-01",
                end_week="2026-01-01",
                intensity=1.0,
            )

    def test_non_finite_intensity_rejected(self):
        with pytest.raises(ValueError):
            PromotionPeriod(
                promotion_id="p1",
                outcome_id="New",
                start_week="2026-01-01",
                end_week="2026-01-08",
                intensity=float("nan"),
            )

    def test_weeks_filters_to_range(self):
        period = PromotionPeriod(
            promotion_id="p1",
            outcome_id="New",
            start_week="2026-01-12",
            end_week="2026-01-19",
            intensity=1.0,
        )
        assert period.weeks(WEEKS) == ("2026-01-12", "2026-01-19")

    def test_round_trip(self):
        period = PromotionPeriod(
            promotion_id="p1",
            outcome_id="New",
            start_week="2026-01-01",
            end_week="2026-01-08",
            intensity=1.5,
            label="Spring sale",
        )
        assert PromotionPeriod.from_dict(period.to_dict()) == period


class TestPlannedActivityValidation:
    def test_requires_channel(self):
        with pytest.raises(ValueError):
            PlannedActivity(
                activity_id="a1",
                channel="",
                start_week="2026-01-01",
                end_week="2026-01-08",
            )

    def test_round_trip(self):
        activity = PlannedActivity(
            activity_id="a1",
            channel="TV_Brand",
            start_week="2026-01-01",
            end_week="2026-01-08",
        )
        assert PlannedActivity.from_dict(activity.to_dict()) == activity


class TestPlannedActivityAndPromotionInputsBundle:
    def test_duplicate_promotion_id_rejected(self):
        p = PromotionPeriod(
            promotion_id="dup",
            outcome_id="New",
            start_week="2026-01-01",
            end_week="2026-01-08",
            intensity=1.0,
        )
        with pytest.raises(ValueError):
            PlannedActivityAndPromotionInputs(promotion_periods=(p, p))

    def test_fingerprint_stable_and_sensitive_to_content(self):
        bundle_a = PlannedActivityAndPromotionInputs(
            promotion_periods=(
                PromotionPeriod(
                    promotion_id="p1",
                    outcome_id="New",
                    start_week="2026-01-01",
                    end_week="2026-01-08",
                    intensity=1.0,
                ),
            )
        )
        bundle_b = PlannedActivityAndPromotionInputs.from_dict(bundle_a.to_dict())
        assert bundle_a.fingerprint() == bundle_b.fingerprint()
        bundle_c = PlannedActivityAndPromotionInputs(
            promotion_periods=(
                PromotionPeriod(
                    promotion_id="p1",
                    outcome_id="New",
                    start_week="2026-01-01",
                    end_week="2026-01-08",
                    intensity=2.0,  # different intensity
                ),
            )
        )
        assert bundle_a.fingerprint() != bundle_c.fingerprint()


class TestMaterializePromoFuture:
    def test_weeks_outside_range_default_to_zero(self):
        period = PromotionPeriod(
            promotion_id="p1",
            outcome_id="New",
            start_week="2026-01-12",
            end_week="2026-01-19",
            intensity=2.0,
        )
        promo_future = materialize_promo_future(
            [period], outcome_ids=["New"], weeks=WEEKS
        )
        assert promo_future["New"]["2026-01-05"] == 0.0
        assert promo_future["New"]["2026-01-12"] == 2.0
        assert promo_future["New"]["2026-01-19"] == 2.0
        assert promo_future["New"]["2026-01-26"] == 0.0

    def test_unknown_outcome_id_rejected(self):
        period = PromotionPeriod(
            promotion_id="p1",
            outcome_id="NotAnOutcome",
            start_week="2026-01-05",
            end_week="2026-01-05",
            intensity=1.0,
        )
        with pytest.raises(ValueError):
            materialize_promo_future([period], outcome_ids=["New"], weeks=WEEKS)

    def test_overlap_default_sums(self):
        periods = [
            PromotionPeriod(
                promotion_id="p1",
                outcome_id="New",
                start_week="2026-01-05",
                end_week="2026-01-12",
                intensity=1.0,
            ),
            PromotionPeriod(
                promotion_id="p2",
                outcome_id="New",
                start_week="2026-01-12",
                end_week="2026-01-19",
                intensity=3.0,
            ),
        ]
        promo_future = materialize_promo_future(
            periods, outcome_ids=["New"], weeks=WEEKS
        )
        assert promo_future["New"]["2026-01-12"] == 4.0

    def test_overlap_max_policy(self):
        periods = [
            PromotionPeriod(
                promotion_id="p1",
                outcome_id="New",
                start_week="2026-01-05",
                end_week="2026-01-12",
                intensity=1.0,
            ),
            PromotionPeriod(
                promotion_id="p2",
                outcome_id="New",
                start_week="2026-01-12",
                end_week="2026-01-19",
                intensity=3.0,
            ),
        ]
        promo_future = materialize_promo_future(
            periods, outcome_ids=["New"], weeks=WEEKS, overlap_policy=OVERLAP_POLICY_MAX
        )
        assert promo_future["New"]["2026-01-12"] == 3.0

    def test_overlap_reject_policy_raises(self):
        periods = [
            PromotionPeriod(
                promotion_id="p1",
                outcome_id="New",
                start_week="2026-01-05",
                end_week="2026-01-12",
                intensity=1.0,
            ),
            PromotionPeriod(
                promotion_id="p2",
                outcome_id="New",
                start_week="2026-01-12",
                end_week="2026-01-19",
                intensity=3.0,
            ),
        ]
        with pytest.raises(ValueError):
            materialize_promo_future(
                periods,
                outcome_ids=["New"],
                weeks=WEEKS,
                overlap_policy=OVERLAP_POLICY_REJECT,
            )

    def test_invalid_overlap_policy_rejected(self):
        with pytest.raises(ValueError):
            materialize_promo_future(
                [], outcome_ids=["New"], weeks=WEEKS, overlap_policy="banana"
            )


class TestMaterializePromoFutureIntegratesWithBuildFutureContext:
    def test_real_end_to_end_wiring_into_build_future_context(self):
        period = PromotionPeriod(
            promotion_id="spring-sale",
            outcome_id="New",
            start_week="2026-01-12",
            end_week="2026-01-19",
            intensity=2.0,
        )
        promo_future = materialize_promo_future(
            [period], outcome_ids=["New"], weeks=WEEKS
        )
        result = build_future_context(
            market="UK",
            period_labels=WEEKS,
            historical_n_weeks=104,
            n_fourier_harmonics=6,
            outcome_ids=["New"],
            mode=OFFICIAL_MODE,
            promo_future=promo_future,
        )
        assert result.promo[:, 0].tolist() == [0.0, 2.0, 2.0, 0.0]
        # Official mode with no held-last-observed controls is always
        # decision-ready.
        assert result.is_decision_ready is True
