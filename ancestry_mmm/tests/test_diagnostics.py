"""Tests for the error-metric and residual-temporal-structure evidence added
to core.diagnostics (REQ-VAL-001: canonical UK-pilot model evidence
expansion) - MAE/RMSE/sMAPE/WAPE/bias and lag-1 autocorrelation/
Durbin-Watson, each a pure known-answer computation over (actual,
predicted)/residual arrays. `in_sample_fit`/`error_metrics_by_outcome`/
`residual_temporal_diagnostics` themselves are thin `predict_mu` wrappers
with no dedicated fixture-based test of their own, per this project's
established convention (see test_predict.py's module docstring) - their
correctness follows from these arithmetic tests plus `predict_mu`'s own
tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.core.diagnostics import (
    _bias,
    _mae,
    _residual_autocorrelation_stats,
    _rmse,
    _smape,
    _wape,
    error_metrics_by_outcome,
    residual_temporal_diagnostics,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams, predict_mu
from ancestry_mmm.tests.conftest import pathway_strength_from_flat


OUTCOME_IDS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=OUTCOME_IDS,
        channels=CHANNELS,
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={"TV_Brand": 1000.0, "DNA_Media": 500.0},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={
            "New": {"TV_Brand": 0.10, "DNA_Media": 0.05},
            "DNA_CrossSell": {"TV_Brand": 0.02, "DNA_Media": 0.20},
        },
        pathway_strength=pathway_strength_from_flat(
            {"New": 0.15, "DNA_CrossSell": 1.0}, "DNA_Media"
        ),
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={},
        outcome_control_coef={},
    )


def _frame_with_actuals(meta: FHModelMeta, params: FHPosteriorParams, n: int = 12):
    """A minimal frame (no media spend, so mu is deterministic from
    intercept/trend alone) with an actuals array Y set to that exact
    predicted mu - i.e. a perfect-fit frame, so error_metrics_by_outcome/
    residual_temporal_diagnostics have a known, hand-verifiable answer
    (all error metrics zero, residuals all zero) without needing to
    hand-derive predict_mu's own math."""
    frame = {
        "markets": ["UK"],
        "market_idx": np.zeros(n, dtype=int),
        "market_bounds": [(0, n)],
        "X_media": np.zeros((n, len(CHANNELS))),
        "promo": np.zeros((n, len(OUTCOME_IDS))),
        "trend": np.arange(n, dtype=float),
        "fourier": np.zeros((n, 6)),
        "control_names": [],
        "X_controls": np.zeros((n, 0)),
        "outcome_controls": {},
        "outcome_control_names": {},
    }
    frame["Y"] = predict_mu(frame, meta, params)
    return frame


class TestErrorMetricsByOutcomeEndToEnd:
    def test_perfect_fit_gives_zero_error_metrics(self, meta, params):
        frame = _frame_with_actuals(meta, params)
        result = error_metrics_by_outcome(frame, meta, params)
        assert set(result["outcome_id"]) == set(OUTCOME_IDS)
        for column in ("mae", "rmse", "smape_pct", "wape_pct", "bias"):
            assert (result[column].abs() < 1e-9).all()

    def test_offset_actuals_produce_matching_bias(self, meta, params):
        frame = _frame_with_actuals(meta, params)
        offset = 5.0
        frame["Y"] = frame["Y"] + offset
        result = error_metrics_by_outcome(frame, meta, params)
        # Y is now uniformly `offset` above the prediction - bias (pred -
        # actual) should be exactly -offset for every outcome.
        assert np.allclose(result["bias"].to_numpy(), -offset)


class TestResidualTemporalDiagnosticsEndToEnd:
    def test_perfect_fit_gives_nan_autocorrelation_from_zero_variance_residuals(
        self, meta, params
    ):
        frame = _frame_with_actuals(meta, params)
        result = residual_temporal_diagnostics(frame, meta, params)
        assert set(result["outcome_id"]) == set(OUTCOME_IDS)
        assert (result["n_observations"] == len(frame["Y"])).all()
        # All-zero residuals: lag1_autocorrelation and durbin_watson are
        # both undefined (nan), not fabricated zeros.
        assert result["lag1_autocorrelation"].isna().all()
        assert result["durbin_watson"].isna().all()


class TestMae:
    def test_perfect_prediction_is_zero(self):
        actual = np.array([1.0, 2.0, 3.0])
        assert _mae(actual, actual.copy()) == pytest.approx(0.0)

    def test_known_answer(self):
        actual = np.array([0.0, 0.0, 0.0])
        pred = np.array([1.0, 2.0, 3.0])
        assert _mae(actual, pred) == pytest.approx(2.0)


class TestRmse:
    def test_perfect_prediction_is_zero(self):
        actual = np.array([1.0, 2.0, 3.0])
        assert _rmse(actual, actual.copy()) == pytest.approx(0.0)

    def test_known_answer(self):
        actual = np.array([0.0, 0.0])
        pred = np.array([3.0, 4.0])
        # sqrt((9 + 16) / 2) = sqrt(12.5)
        assert _rmse(actual, pred) == pytest.approx(np.sqrt(12.5))

    def test_penalizes_large_errors_more_than_mae(self):
        # A single large error inflates RMSE more than MAE - the reason
        # both are reported rather than either alone.
        actual = np.array([0.0, 0.0, 0.0, 0.0])
        pred_uniform = np.array([1.0, 1.0, 1.0, 1.0])
        pred_one_large = np.array([0.0, 0.0, 0.0, 4.0])
        assert _mae(actual, pred_uniform) == pytest.approx(_mae(actual, pred_one_large))
        assert _rmse(actual, pred_one_large) > _rmse(actual, pred_uniform)


class TestSmape:
    def test_perfect_prediction_is_zero(self):
        actual = np.array([10.0, 20.0])
        assert _smape(actual, actual.copy()) == pytest.approx(0.0)

    def test_known_answer(self):
        actual = np.array([10.0])
        pred = np.array([20.0])
        # |10 - 20| / ((10 + 20) / 2) * 100 = 10 / 15 * 100
        assert _smape(actual, pred) == pytest.approx(10 / 15 * 100)

    def test_symmetric_unlike_mape(self):
        # sMAPE treats over- and under-prediction of the same magnitude
        # symmetrically when actual/pred are swapped in the pair.
        over = _smape(np.array([10.0]), np.array([20.0]))
        under = _smape(np.array([20.0]), np.array([10.0]))
        assert over == pytest.approx(under)

    def test_defined_when_actual_is_zero_but_pred_is_not(self):
        # MAPE is undefined (division by zero) here; sMAPE is not - the
        # specific blind spot sMAPE closes.
        actual = np.array([0.0])
        pred = np.array([5.0])
        assert _smape(actual, pred) == pytest.approx(200.0)

    def test_both_zero_is_excluded_not_nan(self):
        actual = np.array([0.0, 10.0])
        pred = np.array([0.0, 10.0])
        assert _smape(actual, pred) == pytest.approx(0.0)


class TestWape:
    def test_perfect_prediction_is_zero(self):
        actual = np.array([10.0, 20.0])
        assert _wape(actual, actual.copy()) == pytest.approx(0.0)

    def test_known_answer(self):
        actual = np.array([10.0, 20.0])
        pred = np.array([12.0, 18.0])
        # sum(|diff|) / sum(|actual|) * 100 = (2 + 2) / 30 * 100
        assert _wape(actual, pred) == pytest.approx(4 / 30 * 100)

    def test_volume_weighted_unlike_mape(self):
        # A large relative error on a low-volume observation barely moves
        # WAPE, unlike MAPE/sMAPE which average per-observation ratios.
        actual = np.array([1000.0, 1.0])
        pred = np.array([1000.0, 100.0])  # 1.0 -> 100.0 is a 9900% miss
        assert _wape(actual, pred) == pytest.approx(99 / 1001 * 100)

    def test_all_zero_actual_is_nan(self):
        actual = np.array([0.0, 0.0])
        pred = np.array([1.0, 2.0])
        assert np.isnan(_wape(actual, pred))


class TestBias:
    def test_unbiased_prediction_is_zero(self):
        actual = np.array([10.0, 20.0])
        pred = np.array([12.0, 18.0])  # +2, -2
        assert _bias(actual, pred) == pytest.approx(0.0)

    def test_known_answer_over_prediction(self):
        actual = np.array([10.0, 10.0])
        pred = np.array([12.0, 14.0])
        assert _bias(actual, pred) == pytest.approx(3.0)

    def test_known_answer_under_prediction(self):
        actual = np.array([10.0, 10.0])
        pred = np.array([8.0, 6.0])
        assert _bias(actual, pred) == pytest.approx(-3.0)

    def test_large_offsetting_errors_can_still_be_unbiased(self):
        # bias is signed mean error - it does not detect this the way
        # MAE/RMSE do, which is exactly why both are reported.
        actual = np.array([0.0, 0.0])
        pred = np.array([100.0, -100.0])
        assert _bias(actual, pred) == pytest.approx(0.0)
        assert _mae(actual, pred) == pytest.approx(100.0)


class TestResidualAutocorrelationStats:
    def test_fewer_than_two_residuals_is_nan(self):
        lag1, dw = _residual_autocorrelation_stats(np.array([1.0]))
        assert np.isnan(lag1)
        assert np.isnan(dw)

    def test_constant_residuals_lag1_is_nan_but_dw_is_defined(self):
        # Zero variance makes the correlation coefficient undefined; DW is
        # still well-defined (zero, since consecutive residuals never change).
        lag1, dw = _residual_autocorrelation_stats(np.array([5.0, 5.0, 5.0, 5.0]))
        assert np.isnan(lag1)
        assert dw == pytest.approx(0.0)

    def test_all_zero_residuals_is_nan_for_both(self):
        lag1, dw = _residual_autocorrelation_stats(np.zeros(5))
        assert np.isnan(lag1)
        assert np.isnan(dw)

    def test_synthetic_near_zero_autocorrelation_case(self):
        # A fixed, seeded white-noise residual series (no temporal
        # structure by construction) - a large n so the sample lag-1
        # coefficient converges close to the true value of 0.
        residuals = np.random.default_rng(42).normal(size=300)
        lag1, dw = _residual_autocorrelation_stats(residuals)
        assert abs(lag1) < 0.2
        # Durbin-Watson near 2 is the "no strong autocorrelation" reading.
        assert dw == pytest.approx(2.0, abs=0.3)

    def test_synthetic_positive_autocorrelation_case(self):
        # A smooth linear drift: each residual is close to its predecessor,
        # the textbook positive-autocorrelation case (under-fit trend).
        residuals = np.linspace(-5.0, 5.0, 30)
        lag1, dw = _residual_autocorrelation_stats(residuals)
        assert lag1 > 0.9
        # Strong positive autocorrelation pulls Durbin-Watson well below 2.
        assert dw < 0.5

    def test_negative_autocorrelation_case(self):
        # Strict sign alternation of equal magnitude - textbook negative
        # lag-1 autocorrelation, distinct from both cases above. DW's exact
        # value for this finite sequence (n=8, 7 lag differences) is 3.5,
        # not the asymptotic 2*(1-corr)=4 the approximation would suggest -
        # both are still on the same "strong negative autocorrelation" side
        # of 2.
        residuals = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
        lag1, dw = _residual_autocorrelation_stats(residuals)
        assert lag1 == pytest.approx(-1.0)
        assert dw == pytest.approx(3.5)
