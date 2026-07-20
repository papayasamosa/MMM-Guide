"""Tests for ancestry_mmm.core.simulation: the synthetic multi-market panel
generator built for future (Phase 2) parameter-recovery testing.
"""

import numpy as np
import pytest

from ancestry_mmm.core.simulation import (
    ChannelSimSpec,
    MarketSimSpec,
    default_channels,
    default_markets,
    simulate_market_specific_panel,
)


class TestPanelShape:
    def test_returns_one_row_per_market_week(self):
        result = simulate_market_specific_panel(seed=0)
        assert len(result.panel) == sum(m.n_weeks for m in result.markets)

    def test_has_a_row_per_market(self):
        result = simulate_market_specific_panel(seed=0)
        counts = result.panel["market"].value_counts().to_dict()
        for market in result.markets:
            assert counts[market.name] == market.n_weeks

    def test_has_spend_and_unit_columns_per_channel(self):
        result = simulate_market_specific_panel(seed=0)
        for channel in result.channels:
            assert f"{channel.name}_spend" in result.panel.columns
            assert f"{channel.name}_units" in result.panel.columns

    def test_has_outcome_column_per_segment(self):
        result = simulate_market_specific_panel(seed=0)
        for seg in result.segments:
            assert f"{seg}_outcome" in result.panel.columns

    def test_requires_at_least_three_markets(self):
        with pytest.raises(ValueError):
            simulate_market_specific_panel(markets=default_markets()[:2], seed=0)


class TestMarketSizesDiffer:
    def test_default_markets_have_different_sizes(self):
        result = simulate_market_specific_panel(seed=0)
        spend_by_market = result.panel.groupby("market")[f"{result.channels[0].name}_spend"].mean()
        # UK is the largest market by construction (size_multiplier=1.0 vs. smaller others)
        assert spend_by_market["UK"] > spend_by_market["Australia"] > spend_by_market["NewMarket"]

    def test_weak_market_has_fewer_observations(self):
        result = simulate_market_specific_panel(seed=0)
        weak = next(m for m in result.markets if m.name == "NewMarket")
        strong = next(m for m in result.markets if m.name == "UK")
        assert weak.n_weeks < strong.n_weeks


class TestGroundTruthStructure:
    def test_saturation_point_is_market_specific(self):
        result = simulate_market_specific_panel(seed=0)
        k_by_market = {m: ks[result.channels[0].name] for m, ks in result.ground_truth.market_K.items()}
        # With 3 differently-scaled markets, at least two K values should differ meaningfully.
        values = list(k_by_market.values())
        assert max(values) - min(values) > 1e-6

    def test_response_strength_is_market_and_segment_specific(self):
        result = simulate_market_specific_panel(seed=0)
        channel = result.channels[0].name
        betas = [
            result.ground_truth.market_beta[m.name][seg][channel]
            for m in result.markets
            for seg in result.segments
        ]
        assert len(set(np.round(betas, 6))) > 1

    def test_decay_and_hill_shape_are_shared_across_markets(self):
        # decay[channel] and S[channel] are shared, per docs/market_hierarchy.md
        # section 2.3/2.4 "initial production version" - the ground truth only
        # stores one value per channel, not per (market, channel).
        result = simulate_market_specific_panel(seed=0)
        for channel in result.channels:
            assert result.ground_truth.channel_decay[channel.name] == channel.decay
            assert result.ground_truth.channel_S[channel.name] == channel.S


class TestMediaInflation:
    def test_cost_per_unit_increases_over_time_for_a_positive_inflation_channel(self):
        result = simulate_market_specific_panel(seed=0)
        tv = next(c for c in result.channels if c.name == "TV")
        assert tv.annual_inflation > 0
        cost = result.ground_truth.cost_per_unit["UK"]["TV"]
        assert cost[-10:].mean() > cost[:10].mean()

    def test_spend_equals_units_times_cost_per_unit(self):
        result = simulate_market_specific_panel(seed=0)
        uk = result.panel[result.panel["market"] == "UK"].reset_index(drop=True)
        cost = result.ground_truth.cost_per_unit["UK"]["TV"]
        implied_spend = uk["TV_units"].to_numpy() * cost
        np.testing.assert_allclose(uk["TV_spend"].to_numpy(), implied_spend, rtol=1e-8)


class TestDeterminism:
    def test_same_seed_gives_same_panel(self):
        a = simulate_market_specific_panel(seed=42)
        b = simulate_market_specific_panel(seed=42)
        assert a.panel.equals(b.panel)

    def test_different_seed_gives_different_panel(self):
        a = simulate_market_specific_panel(seed=1)
        b = simulate_market_specific_panel(seed=2)
        assert not a.panel["TV_spend"].equals(b.panel["TV_spend"])


class TestCustomMarketsAndChannels:
    def test_custom_market_list_is_respected(self):
        markets = [
            MarketSimSpec(name="A", n_weeks=60, size_multiplier=1.0),
            MarketSimSpec(name="B", n_weeks=60, size_multiplier=0.5),
            MarketSimSpec(name="C", n_weeks=20, size_multiplier=0.1),
        ]
        result = simulate_market_specific_panel(markets=markets, seed=0)
        assert set(result.panel["market"].unique()) == {"A", "B", "C"}

    def test_custom_channel_list_is_respected(self):
        channels = [ChannelSimSpec(name="Radio", decay=0.4, K=50.0, S=1.2, beta=0.5)]
        result = simulate_market_specific_panel(channels=channels, seed=0)
        assert "Radio_spend" in result.panel.columns
        assert "TV_spend" not in result.panel.columns

    def test_default_channels_has_at_least_two_channels(self):
        assert len(default_channels()) >= 2
