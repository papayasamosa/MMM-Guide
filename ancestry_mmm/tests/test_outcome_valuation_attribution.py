"""Tests for posterior economic attribution: the draw-level, weekly-grain
join and its posterior-uncertainty summary (REQ-ECON-003 Requirements
3-4).

The central regression this file guards against: computing period
economics by multiplying a *pre-summed* total incremental outcome by an
*average* rate, instead of joining at the weekly grain first and summing
only afterward - the business decision's own explicit prohibition
("Never calculate historical quarterly/yearly economic value by
multiplying total incremental outcomes by a simple average LTR/revenue
rate").
"""

import numpy as np
import pytest

from ancestry_mmm.core.outcome_valuation import VALUATION_KIND_FH_LTR
from ancestry_mmm.core.outcome_valuation_attribution import (
    aggregate_incremental_value_draws,
    join_incremental_outcome_draws_to_value,
    summarize_posterior_economic_attribution,
)
from ancestry_mmm.core.outcome_valuation_rates import WeeklyValueRate


def _rate(week: str, value_per_unit: float, **overrides) -> WeeklyValueRate:
    values = dict(
        valuation_kind=VALUATION_KIND_FH_LTR,
        market="UK",
        week=week,
        segment="New",
        value_per_unit=value_per_unit,
        currency="GBP",
        is_zero_denominator_carve_out=False,
        source_record_fingerprint=f"fp-{week}",
    )
    values.update(overrides)
    return WeeklyValueRate(**values)


class TestJoin:
    def test_elementwise_multiplication_by_week(self):
        draws = np.array([[10.0, 20.0], [12.0, 18.0]])  # 2 draws x 2 weeks
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        joined = join_incremental_outcome_draws_to_value(draws, rates)
        expected = np.array([[50.0, 200.0], [60.0, 180.0]])
        np.testing.assert_allclose(joined, expected)

    def test_shape_mismatch_is_rejected(self):
        draws = np.array([[10.0, 20.0, 30.0]])
        rates = [_rate("2025-01-06", 5.0)]
        with pytest.raises(ValueError, match="must correspond one-to-one"):
            join_incremental_outcome_draws_to_value(draws, rates)

    def test_non_2d_input_is_rejected(self):
        draws = np.array([10.0, 20.0])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        with pytest.raises(ValueError, match="must be 2-D"):
            join_incremental_outcome_draws_to_value(draws, rates)

    def test_mixed_segment_rates_rejected(self):
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0, segment="Winback")]
        with pytest.raises(ValueError, match="single cohesive weekly series"):
            join_incremental_outcome_draws_to_value(draws, rates)

    def test_mixed_currency_rates_rejected(self):
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0, currency="USD")]
        with pytest.raises(ValueError, match="must not mix currencies"):
            join_incremental_outcome_draws_to_value(draws, rates)

    def test_empty_rates_rejected(self):
        draws = np.zeros((1, 0))
        with pytest.raises(ValueError, match="must not be empty"):
            join_incremental_outcome_draws_to_value(draws, [])


class TestWeeklyGrainOrderingInvariant:
    def test_join_then_aggregate_differs_from_aggregate_then_average_rate(self):
        """The central regression guard: week-varying rates make
        join-then-sum genuinely different from sum-then-multiply-by-
        average-rate. If these ever coincidentally matched, the test
        data (deliberately anti-correlated outcome/rate) would need
        adjusting - they must not match here."""
        draws = np.array([[100.0, 10.0]])  # 1 draw, 2 weeks: high outcome, low outcome
        rates = [
            _rate("2025-01-06", 1.0),
            _rate("2025-01-13", 10.0),
        ]  # low rate, high rate

        correct = aggregate_incremental_value_draws(
            join_incremental_outcome_draws_to_value(draws, rates)
        )[0]
        # correct = 100*1 + 10*10 = 200

        wrong_total_outcome = draws.sum(axis=1)[0]  # 110
        wrong_average_rate = np.mean([r.value_per_unit for r in rates])  # 5.5
        wrong = wrong_total_outcome * wrong_average_rate  # 605

        assert correct == pytest.approx(200.0)
        assert wrong == pytest.approx(605.0)
        assert correct != pytest.approx(wrong)

    def test_constant_rate_makes_the_two_methods_agree(self):
        """Sanity check on the invariant test above: when the rate is
        genuinely constant across weeks, order doesn't matter - proving
        the discrepancy above comes from week-varying rates, not a bug
        in either computation path."""
        draws = np.array([[100.0, 10.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 5.0)]

        correct = aggregate_incremental_value_draws(
            join_incremental_outcome_draws_to_value(draws, rates)
        )[0]
        wrong_total_outcome = draws.sum(axis=1)[0]
        wrong = wrong_total_outcome * 5.0

        assert correct == pytest.approx(wrong)


class TestSummarizePosteriorEconomicAttribution:
    def test_produces_a_value_summary(self):
        draws = np.array([[10.0, 20.0], [12.0, 18.0], [8.0, 22.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates)
        assert artefact.valuation_kind == VALUATION_KIND_FH_LTR
        assert artefact.market == "UK"
        assert artefact.segment == "New"
        assert artefact.currency == "GBP"
        assert artefact.weeks == ("2025-01-06", "2025-01-13")
        assert artefact.incremental_value_n_draws == 3
        # draw totals: 10*5+20*10=250, 12*5+18*10=240, 8*5+22*10=260
        assert artefact.incremental_value_mean == pytest.approx(250.0)
        assert artefact.incremental_value_median == pytest.approx(250.0)

    def test_no_spend_means_no_roi(self):
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates, spend=None)
        assert artefact.roi_mean is None
        assert artefact.spend is None

    def test_zero_spend_means_no_roi(self):
        """REQ-ECON-001: ROI is never fabricated from a zero/absent
        spend denominator."""
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates, spend=0.0)
        assert artefact.roi_mean is None

    def test_positive_spend_produces_roi(self):
        draws = np.array([[10.0, 20.0], [12.0, 18.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates, spend=100.0)
        # draw totals: 250, 240 -> roi: 2.5, 2.4
        assert artefact.roi_mean == pytest.approx(2.45)

    def test_source_rate_fingerprints_are_traceable(self):
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates)
        assert artefact.source_rate_fingerprints == ("fp-2025-01-06", "fp-2025-01-13")

    def test_credible_interval_uses_the_existing_governed_convention(self):
        """Guards against reinventing a standard-deviation-based interval
        - must go through core.uncertainty.summarize_distribution."""
        rng = np.random.default_rng(0)
        draws = rng.normal(loc=100.0, scale=10.0, size=(500, 1))
        rates = [_rate("2025-01-06", 1.0)]
        artefact = summarize_posterior_economic_attribution(
            draws, rates, credible_mass=0.9
        )
        assert artefact.credible_mass == 0.9
        assert artefact.incremental_value_lower < artefact.incremental_value_mean
        assert artefact.incremental_value_mean < artefact.incremental_value_upper
        assert artefact.incremental_value_n_draws == 500

    def test_incremental_outcome_summary_is_the_raw_pre_join_draws(self):
        """WP2E: incremental_outcome_* summarises the same draws this
        artefact is built from, summed per draw, *before* the value
        join - independent of the rates' value_per_unit."""
        draws = np.array([[10.0, 20.0], [12.0, 18.0], [8.0, 22.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates)
        # draw totals (raw outcome units, not value): 30, 30, 30
        assert artefact.incremental_outcome_mean == pytest.approx(30.0)
        assert artefact.incremental_outcome_median == pytest.approx(30.0)

    def test_incremental_outcome_summary_available_without_spend(self):
        """The raw-outcome summary never depends on spend/ROI being
        available - REQ-ECON-001's CPA-vs-ROI split."""
        draws = np.array([[10.0, 20.0]])
        rates = [_rate("2025-01-06", 5.0), _rate("2025-01-13", 10.0)]
        artefact = summarize_posterior_economic_attribution(draws, rates, spend=None)
        assert artefact.incremental_outcome_mean == pytest.approx(30.0)
        assert artefact.roi_mean is None
