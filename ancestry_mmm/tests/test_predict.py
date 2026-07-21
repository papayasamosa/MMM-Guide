"""Tests for core.predict.generate_channel_curve - the Model A ("shared
curve") equivalent of core.market_specific_predict.generate_market_channel_curve,
added in Phase 3b so CPA/media-unit code (core.media_units) can work on
either model type's curve DataFrame uniformly. The rest of core.predict
(predict_mu, extract_posterior_params, steady_state_segment_response) is
established, shipped code with no dedicated test file, per this project's
convention of not unit-testing every existing NumPy-replay function - see
docs/decision_log.md and the equivalent note in test_market_specific_model.py."""

import numpy as np
import pytest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams, generate_channel_curve

SEGMENTS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_segment="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={"TV_Brand": 1000.0, "DNA_Media": 500.0},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={"New": {"TV_Brand": 0.10, "DNA_Media": 0.05}, "DNA_CrossSell": {"TV_Brand": 0.02, "DNA_Media": 0.20}},
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0},
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={}, segment_control_coef={},
    )


class TestGenerateChannelCurve:
    def test_unknown_channel_raises(self, meta, params):
        with pytest.raises(ValueError, match="not one of this model's channels"):
            generate_channel_curve("Radio", meta, params)

    def test_zero_spend_gives_zero_response(self, meta, params):
        df = generate_channel_curve("TV_Brand", meta, params, spend_range=np.array([0.0, 100.0, 500.0]))
        assert df.iloc[0]["overall_response"] == pytest.approx(0.0)
        assert df.iloc[0]["saturation"] == pytest.approx(0.0)

    def test_overall_response_is_sum_of_segment_responses(self, meta, params):
        df = generate_channel_curve("DNA_Media", meta, params, spend_range=np.array([0.0, 250.0, 1000.0]))
        seg_cols = [f"{s}_response" for s in SEGMENTS]
        np.testing.assert_allclose(df["overall_response"], df[seg_cols].sum(axis=1))

    def test_dna_channel_halo_scales_non_dna_segment_response(self, meta, params):
        df = generate_channel_curve("DNA_Media", meta, params, spend_range=np.array([500.0]))
        row = df.iloc[0]
        raw_new = params.beta["New"]["DNA_Media"] * row["saturation"]
        assert row["New_response"] == pytest.approx(raw_new * params.halo_strength["New"])

    def test_response_increases_with_spend(self, meta, params):
        df = generate_channel_curve("TV_Brand", meta, params, spend_range=np.array([0.0, 500.0, 5000.0]))
        assert df["overall_response"].is_monotonic_increasing

    def test_column_shape_matches_market_specific_curve_for_downstream_compatibility(self, meta, params):
        # core.media_units's functions rely on this shape being identical to
        # generate_market_channel_curve's output (minus the "market" column).
        df = generate_channel_curve("TV_Brand", meta, params, spend_range=np.array([0.0, 100.0]))
        assert {"channel", "spend", "saturation", "overall_response"} <= set(df.columns)
        assert all(f"{s}_response" in df.columns for s in SEGMENTS)

    def test_default_spend_range_is_derived_from_k(self, meta, params):
        df = generate_channel_curve("TV_Brand", meta, params, n_points=10)
        assert len(df) == 10
        assert df["spend"].max() == pytest.approx(params.hill_K["TV_Brand"] * 3)

    def test_max_spend_overrides_the_default_cap(self, meta, params):
        df = generate_channel_curve("TV_Brand", meta, params, n_points=5, max_spend=50.0)
        assert df["spend"].max() == pytest.approx(50.0)
