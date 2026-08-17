"""Tests for core.planning.weekly_plan_builder (Work Package 4 of
`Media-Mix-Lab: Coding LLM Next Steps Post PR262`)."""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.planning.future_context import (
    OFFICIAL_MODE,
    build_future_context,
)
from ancestry_mmm.core.planning.phasing import (
    MethodProvenance,
    WeeklyAllocationResult,
)
from ancestry_mmm.core.planning.weekly_plan_builder import (
    WeeklyPlanConstructionError,
    build_governed_weekly_plan,
)

CHANNELS = ["TV", "DNA_Media"]
OUTCOME_IDS = ["New", "DNA_CrossSell"]
WEEKS = ("2026-06-01", "2026-06-08", "2026-06-15")


def _meta(**overrides) -> FHModelMeta:
    values = dict(
        markets=["UK"],
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=2,
        unpooled_markets=[],
        control_names=[],
    )
    values.update(overrides)
    return FHModelMeta(**values)


def _allocation(
    channel: str, values, market="UK", weeks=WEEKS
) -> WeeklyAllocationResult:
    return WeeklyAllocationResult(
        market=market,
        series_id=channel,
        period_labels=tuple(weeks),
        values=tuple(values),
        provenance=MethodProvenance(
            method_id="calendar_day_overlap_v1",
            method_version=1,
            canonical_calendar_start=weeks[0],
            canonical_calendar_end=weeks[-1],
        ),
        reconciliation=(),
    )


def _future_context(**overrides):
    kwargs = dict(
        market="UK",
        period_labels=WEEKS,
        historical_n_weeks=20,
        n_fourier_harmonics=3,
        outcome_ids=tuple(OUTCOME_IDS),
        mode=OFFICIAL_MODE,
        promo_future={oid: {w: 0.0 for w in WEEKS} for oid in OUTCOME_IDS},
    )
    kwargs.update(overrides)
    return build_future_context(**kwargs)


def _allocations(**overrides):
    values = {
        "TV": _allocation("TV", [100.0, 200.0, 150.0]),
        "DNA_Media": _allocation("DNA_Media", [50.0, 60.0, 70.0]),
    }
    values.update(overrides)
    return values


class TestBuildGovernedWeeklyPlan:
    def test_builds_a_valid_plan(self):
        meta = _meta()
        plan, provenance = build_governed_weekly_plan(
            market="UK",
            meta=meta,
            channel_allocations=_allocations(),
            future_context=_future_context(),
            expected_n_fourier_columns=6,
        )
        assert plan.market == "UK"
        assert plan.period_labels == WEEKS
        np.testing.assert_allclose(plan.media_by_channel["TV"], [100.0, 200.0, 150.0])
        assert provenance.market == "UK"
        assert provenance.channel_names == ("TV", "DNA_Media")
        assert provenance.fingerprint()

    def test_unknown_extra_channel_raises(self):
        meta = _meta()
        allocations = _allocations()
        allocations["Radio"] = _allocation("Radio", [10.0, 10.0, 10.0])
        with pytest.raises(WeeklyPlanConstructionError, match="Radio"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=allocations,
                future_context=_future_context(),
                expected_n_fourier_columns=6,
            )

    def test_missing_channel_raises(self):
        meta = _meta()
        allocations = _allocations()
        del allocations["DNA_Media"]
        with pytest.raises(WeeklyPlanConstructionError, match="DNA_Media"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=allocations,
                future_context=_future_context(),
                expected_n_fourier_columns=6,
            )

    def test_mismatched_week_order_raises(self):
        meta = _meta()
        allocations = _allocations()
        allocations["TV"] = _allocation(
            "TV",
            [100.0, 200.0, 150.0],
            weeks=("2026-06-08", "2026-06-01", "2026-06-15"),
        )
        with pytest.raises(WeeklyPlanConstructionError, match="canonical week order"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=allocations,
                future_context=_future_context(),
                expected_n_fourier_columns=6,
            )

    def test_wrong_market_allocation_raises(self):
        meta = _meta(markets=["UK", "IE"])
        allocations = _allocations()
        allocations["TV"] = _allocation("TV", [100.0, 200.0, 150.0], market="IE")
        with pytest.raises(WeeklyPlanConstructionError, match="market"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=allocations,
                future_context=_future_context(),
                expected_n_fourier_columns=6,
            )

    def test_future_context_market_mismatch_raises(self):
        meta = _meta(markets=["UK", "IE"])
        with pytest.raises(WeeklyPlanConstructionError, match="future_context.market"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=_allocations(),
                future_context=_future_context(market="IE"),
                expected_n_fourier_columns=6,
            )

    def test_fourier_shape_mismatch_raises(self):
        meta = _meta()
        with pytest.raises(WeeklyPlanConstructionError, match="fourier"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=_allocations(),
                future_context=_future_context(),
                expected_n_fourier_columns=99,  # actual is 6 (3 harmonics)
            )

    def test_promo_outcome_shape_mismatch_raises(self):
        meta = _meta(outcome_ids=["New", "DNA_CrossSell", "Winback"])
        with pytest.raises(WeeklyPlanConstructionError, match="outcome_ids"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=_allocations(),
                future_context=_future_context(),  # only has 2 outcomes
                expected_n_fourier_columns=6,
            )

    def test_control_names_mismatch_raises(self):
        meta = _meta(control_names=["CPI"])
        with pytest.raises(WeeklyPlanConstructionError, match="control_names"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=_allocations(),
                future_context=_future_context(),  # no controls
                expected_n_fourier_columns=6,
            )

    def test_negative_allocation_value_raises_even_if_constructed_directly(self):
        meta = _meta()

        # WeeklyAllocationResult itself already rejects negative values
        # (Work Package 2 hardening) - confirm the builder does not
        # silently trust a differently-shaped allocation-like object.
        class _BadAllocation:
            market = "UK"
            period_labels = WEEKS

            def as_array(self):
                return np.array([-1.0, 2.0, 3.0])

        allocations = _allocations()
        allocations["TV"] = _BadAllocation()
        with pytest.raises(WeeklyPlanConstructionError, match="negative"):
            build_governed_weekly_plan(
                market="UK",
                meta=meta,
                channel_allocations=allocations,
                future_context=_future_context(),
                expected_n_fourier_columns=6,
            )
