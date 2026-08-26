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

import dataclasses

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.diagnostics import (
    _bias,
    _mae,
    _residual_autocorrelation_stats,
    _rmse,
    _smape,
    _wape,
    error_metrics_by_outcome,
    residual_series,
    residual_temporal_diagnostics,
    shared_residual_evidence,
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
        assert set(result["market"]) == {"UK"}
        assert (result["n_observations"] == len(frame["Y"])).all()
        # All-zero residuals: lag1_autocorrelation and durbin_watson are
        # both undefined (nan), not fabricated zeros.
        assert result["lag1_autocorrelation"].isna().all()
        assert result["durbin_watson"].isna().all()


class TestResidualTemporalDiagnosticsMarketSafety:
    """Work Package 2 corrective fix: residual_temporal_diagnostics must
    never form a lag pair across a market boundary. The model frame is
    multi-market; concatenating every market's residuals before computing
    lag-1 autocorrelation/Durbin-Watson creates a synthetic adjacency
    between one market's last observation and a different market's first -
    not a valid time-series lag."""

    @staticmethod
    def _two_market_meta(base_meta: FHModelMeta) -> FHModelMeta:
        return dataclasses.replace(base_meta, markets=["UK", "US"])

    @staticmethod
    def _two_market_params(base_params: FHPosteriorParams) -> FHPosteriorParams:
        return dataclasses.replace(
            base_params,
            market_offset={
                "UK": {"New": 0.0, "DNA_CrossSell": 0.0},
                "US": {"New": 1.5, "DNA_CrossSell": -0.5},
            },
        )

    @staticmethod
    def _two_market_frame(meta, params, n_per_market: int = 6):
        n = n_per_market * 2
        frame = {
            "markets": ["UK", "US"],
            "market_idx": np.array([0] * n_per_market + [1] * n_per_market),
            "market_bounds": [(0, n_per_market), (n_per_market, n)],
            "X_media": np.zeros((n, len(CHANNELS))),
            "promo": np.zeros((n, len(OUTCOME_IDS))),
            "trend": np.concatenate(
                [
                    np.arange(n_per_market, dtype=float),
                    np.arange(n_per_market, dtype=float),
                ]
            ),
            "fourier": np.zeros((n, 6)),
            "control_names": [],
            "X_controls": np.zeros((n, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }
        frame["Y"] = predict_mu(frame, meta, params)
        return frame

    def test_cross_market_discontinuity_does_not_change_within_market_statistics(
        self, meta, params
    ):
        """Reproduces the defect (via the internal helper, computed
        directly on the concatenated vector as the pre-fix production code
        did) and proves the fix: each market's row from the production
        function exactly matches that market's own within-slice
        calculation, unaffected by an extreme discontinuity at the other
        market's boundary."""
        n_per_market = 6
        two_market_meta = self._two_market_meta(meta)
        two_market_params = self._two_market_params(params)
        frame = self._two_market_frame(two_market_meta, two_market_params, n_per_market)

        outcome_idx = meta.outcome_ids.index("New")
        baseline_mu = frame["Y"][:, outcome_idx].copy()

        # Market UK: a mild alternating residual pattern. Market US: the
        # same pattern shifted by an extreme +500 offset - a deliberately
        # extreme discontinuity relative to UK's last residual.
        pattern = np.array([0.0, 5.0, 0.0, 5.0, 0.0, 5.0])
        uk_residuals = pattern.copy()
        us_residuals = pattern.copy() + 500.0
        engineered = np.concatenate([uk_residuals, us_residuals])
        frame["Y"][:, outcome_idx] = baseline_mu + engineered

        result = residual_temporal_diagnostics(
            frame, two_market_meta, two_market_params
        )
        uk_row = result[
            (result["market"] == "UK") & (result["outcome_id"] == "New")
        ].iloc[0]
        us_row = result[
            (result["market"] == "US") & (result["outcome_id"] == "New")
        ].iloc[0]

        expected_uk_lag1, expected_uk_dw = _residual_autocorrelation_stats(uk_residuals)
        expected_us_lag1, expected_us_dw = _residual_autocorrelation_stats(us_residuals)
        assert uk_row["lag1_autocorrelation"] == pytest.approx(expected_uk_lag1)
        assert uk_row["durbin_watson"] == pytest.approx(expected_uk_dw)
        assert us_row["lag1_autocorrelation"] == pytest.approx(expected_us_lag1)
        assert us_row["durbin_watson"] == pytest.approx(expected_us_dw)
        assert uk_row["n_observations"] == n_per_market
        assert us_row["n_observations"] == n_per_market

        # Reproduce the defect explicitly: the old concatenated-vector
        # calculation (computed here directly, independent of the now-fixed
        # production function) disagrees with UK's own true within-market
        # statistic - proof a cross-market lag pair really did corrupt the
        # evidence the pre-fix code would have reported.
        concatenated_lag1, concatenated_dw = _residual_autocorrelation_stats(engineered)
        assert concatenated_lag1 != pytest.approx(expected_uk_lag1, abs=1e-6)
        assert concatenated_dw != pytest.approx(expected_uk_dw, abs=1e-6)

    def test_different_markets_retain_different_residual_evidence(self, meta, params):
        n_per_market = 6
        two_market_meta = self._two_market_meta(meta)
        two_market_params = self._two_market_params(params)
        frame = self._two_market_frame(two_market_meta, two_market_params, n_per_market)

        outcome_idx = meta.outcome_ids.index("New")
        baseline_mu = frame["Y"][:, outcome_idx].copy()
        uk_residuals = np.array([0.0, 1.0, 0.0, 1.0, 0.0, 1.0])
        us_residuals = np.array([0.0, -1.0, 2.0, -3.0, 4.0, -5.0])
        frame["Y"][:, outcome_idx] = baseline_mu + np.concatenate(
            [uk_residuals, us_residuals]
        )

        result = residual_temporal_diagnostics(
            frame, two_market_meta, two_market_params
        )
        uk_lag1 = result.loc[
            (result["market"] == "UK") & (result["outcome_id"] == "New"),
            "lag1_autocorrelation",
        ].iloc[0]
        us_lag1 = result.loc[
            (result["market"] == "US") & (result["outcome_id"] == "New"),
            "lag1_autocorrelation",
        ].iloc[0]
        assert uk_lag1 != pytest.approx(us_lag1, abs=1e-6)

    def test_fewer_than_two_observations_in_a_market_is_explicit_nan(
        self, meta, params
    ):
        """A market slice with fewer than two rows cannot define a lag-1
        pair - explicit NaN, never a fabricated value, and never allowed to
        borrow a row from a different market to make up the pair."""
        two_market_meta = self._two_market_meta(meta)
        two_market_params = self._two_market_params(params)
        n = 7
        frame = {
            "markets": ["UK", "US"],
            "market_idx": np.array([0] * 6 + [1]),
            "market_bounds": [(0, 6), (6, 7)],
            "X_media": np.zeros((n, len(CHANNELS))),
            "promo": np.zeros((n, len(OUTCOME_IDS))),
            "trend": np.concatenate([np.arange(6, dtype=float), np.array([0.0])]),
            "fourier": np.zeros((n, 6)),
            "control_names": [],
            "X_controls": np.zeros((n, 0)),
            "outcome_controls": {},
            "outcome_control_names": {},
        }
        frame["Y"] = predict_mu(frame, two_market_meta, two_market_params)
        result = residual_temporal_diagnostics(
            frame, two_market_meta, two_market_params
        )
        us_rows = result[result["market"] == "US"]
        assert (us_rows["n_observations"] == 1).all()
        assert us_rows["lag1_autocorrelation"].isna().all()
        assert us_rows["durbin_watson"].isna().all()

    def test_row_count_is_markets_times_outcomes(self, meta, params):
        two_market_meta = self._two_market_meta(meta)
        two_market_params = self._two_market_params(params)
        frame = self._two_market_frame(two_market_meta, two_market_params)
        result = residual_temporal_diagnostics(
            frame, two_market_meta, two_market_params
        )
        assert len(result) == len(frame["markets"]) * len(meta.outcome_ids)
        assert set(result["market"]) == {"UK", "US"}
        assert set(result["outcome_id"]) == set(OUTCOME_IDS)


class TestResidualSeriesEndToEnd:
    """WP2.11 item 6: `residual_series` is the canonical per-observation
    evidence backing the Residual Explorer - one row per (market, date,
    outcome_id), never an aggregate statistic."""

    def test_perfect_fit_gives_zero_residuals_one_row_per_observation(
        self, meta, params
    ):
        frame = _frame_with_actuals(meta, params)
        result = residual_series(frame, meta, params)
        assert len(result) == len(frame["Y"]) * len(OUTCOME_IDS)
        assert set(result["outcome_id"]) == set(OUTCOME_IDS)
        assert set(result["market"]) == {"UK"}
        assert (result["residual"].abs() < 1e-9).all()
        assert (result["abs_residual"].abs() < 1e-9).all()

    def test_residual_sign_convention_is_actual_minus_predicted(self, meta, params):
        # `actual - predicted` (never the reverse): a positive offset on
        # the actuals must show up as a positive residual, i.e. the model
        # under-predicted.
        frame = _frame_with_actuals(meta, params)
        offset = 7.0
        frame["Y"] = frame["Y"] + offset
        result = residual_series(frame, meta, params)
        assert np.allclose(result["residual"].to_numpy(), offset)
        assert np.allclose(result["abs_residual"].to_numpy(), abs(offset))

    def test_no_trace_supplied_omits_expected_mean_columns(self, meta, params):
        frame = _frame_with_actuals(meta, params)
        result = residual_series(frame, meta, params, trace=None)
        assert "expected_mean_lower" not in result.columns
        assert "expected_mean_upper" not in result.columns
        assert "expected_mean_credible_mass" not in result.columns

    def test_rank_pct_is_computed_within_market_only(self, meta, params):
        """Reuses `TestResidualTemporalDiagnosticsMarketSafety`'s two-market
        fixture pattern: a large residual in one market must never distort
        the other market's own rank percentiles. Uses strictly-increasing,
        untied values in each market (scaled 500x apart) so the expected
        rank order is unambiguous and not sensitive to floating-point
        noise the way tied values would be."""
        two_market_meta = TestResidualTemporalDiagnosticsMarketSafety._two_market_meta(
            meta
        )
        two_market_params = (
            TestResidualTemporalDiagnosticsMarketSafety._two_market_params(params)
        )
        n_per_market = 6
        frame = TestResidualTemporalDiagnosticsMarketSafety._two_market_frame(
            two_market_meta, two_market_params, n_per_market
        )
        outcome_idx = meta.outcome_ids.index("New")
        baseline_mu = frame["Y"][:, outcome_idx].copy()
        shape = np.array([3.0, 1.0, 5.0, 2.0, 6.0, 4.0])
        uk_residuals = shape
        us_residuals = shape * 500.0
        frame["Y"][:, outcome_idx] = baseline_mu + np.concatenate(
            [uk_residuals, us_residuals]
        )

        result = residual_series(frame, two_market_meta, two_market_params)
        uk_rows = result[
            (result["market"] == "UK") & (result["outcome_id"] == "New")
        ].sort_values("date")
        us_rows = result[
            (result["market"] == "US") & (result["outcome_id"] == "New")
        ].sort_values("date")
        # Both markets have the identical relative ordering, so their rank
        # percentiles must be identical to each other despite the US
        # magnitude being 500x larger - proof ranking never crosses the
        # market boundary.
        assert np.allclose(
            uk_rows["residual_rank_pct"].to_numpy(),
            us_rows["residual_rank_pct"].to_numpy(),
        )


class TestSharedResidualEvidence:
    """WP2.11 item 6.3: cross-outcome shared-residual comparison - no
    causal claim, purely a correlation/co-occurrence summary."""

    def test_empty_frame_returns_empty_evidence(self):
        result = shared_residual_evidence(pd.DataFrame())
        assert result == {"pairwise_correlation": [], "shared_extreme_weeks": []}

    def test_perfectly_correlated_outcomes(self):
        dates = pd.date_range("2024-01-01", periods=10, freq="W")
        residual_df = pd.concat(
            [
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "A",
                        "residual": np.linspace(-5, 5, 10),
                    }
                ),
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "B",
                        "residual": np.linspace(-5, 5, 10) * 2,
                    }
                ),
            ],
            ignore_index=True,
        )
        result = shared_residual_evidence(residual_df)
        assert len(result["pairwise_correlation"]) == 1
        pair = result["pairwise_correlation"][0]
        assert {pair["outcome_a"], pair["outcome_b"]} == {"A", "B"}
        assert pair["residual_correlation"] == pytest.approx(1.0)

    def test_shared_extreme_week_detected_with_sign_agreement(self):
        dates = pd.date_range("2024-01-01", periods=10, freq="W")
        a_residuals = np.array(
            [0.1, 0.2, -0.1, 0.15, 0.05, -0.2, 0.1, -0.05, 0.2, 50.0]
        )
        b_residuals = np.array(
            [0.3, -0.1, 0.2, -0.15, 0.1, 0.05, -0.2, 0.1, -0.1, 40.0]
        )
        residual_df = pd.concat(
            [
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "A",
                        "residual": a_residuals,
                    }
                ),
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "B",
                        "residual": b_residuals,
                    }
                ),
            ],
            ignore_index=True,
        )
        result = shared_residual_evidence(residual_df, top_fraction=0.1)
        shared = result["shared_extreme_weeks"]
        assert len(shared) == 1
        week = shared[0]
        assert week["date"] == dates[-1]
        assert set(week["outcomes"]) == {"A", "B"}
        assert week["all_same_sign"] is True

    def test_correlation_and_shared_weeks_never_cross_a_market_boundary(self):
        """A model frame can carry more than one market even when
        model_type="shared" (the fixture two-market tests elsewhere in this
        file exercise exactly that). Correlating or ranking one market's
        weeks against a different market's weeks on the same calendar date
        would compare unrelated series."""
        dates = pd.date_range("2024-01-01", periods=10, freq="W")
        # UK: A and B perfectly correlated. US: A and B perfectly
        # anti-correlated. If markets were pooled, the true per-market
        # signals would be diluted/contaminated.
        uk = pd.concat(
            [
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "A",
                        "residual": np.linspace(-5, 5, 10),
                    }
                ),
                pd.DataFrame(
                    {
                        "market": "UK",
                        "date": dates,
                        "outcome_id": "B",
                        "residual": np.linspace(-5, 5, 10),
                    }
                ),
            ],
            ignore_index=True,
        )
        us = pd.concat(
            [
                pd.DataFrame(
                    {
                        "market": "US",
                        "date": dates,
                        "outcome_id": "A",
                        "residual": np.linspace(-5, 5, 10),
                    }
                ),
                pd.DataFrame(
                    {
                        "market": "US",
                        "date": dates,
                        "outcome_id": "B",
                        "residual": np.linspace(5, -5, 10),
                    }
                ),
            ],
            ignore_index=True,
        )
        residual_df = pd.concat([uk, us], ignore_index=True)
        result = shared_residual_evidence(residual_df)
        pairwise = {
            (p["market"], p["outcome_a"], p["outcome_b"]): p["residual_correlation"]
            for p in result["pairwise_correlation"]
        }
        assert pairwise[("UK", "A", "B")] == pytest.approx(1.0)
        assert pairwise[("US", "A", "B")] == pytest.approx(-1.0)

        # Every shared-extreme-week row must carry only one market's outcomes.
        for week in result["shared_extreme_weeks"]:
            assert week["market"] in {"UK", "US"}

    def test_no_causal_claim_in_payload_keys(self):
        # Guardrail: the evidence structure itself must never carry a
        # causal/explanatory field name - WP2.11 item 7.5 explicitly
        # forbids inferring a causal explanation from this evidence.
        result = shared_residual_evidence(pd.DataFrame())
        for key in result:
            assert "cause" not in key.lower()
            assert "explan" not in key.lower()


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
