"""Tests for ancestry_mmm.core.market_config: market descriptors, currency,
and channel media-unit mappings - Phase 1 of the market-specific redesign.
"""

from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig,
    MarketCurrency,
    MarketDescriptors,
    MarketProfile,
    MarketSpecConfig,
    market_data_quality_status,
)


class TestMarketDescriptors:
    def test_default_is_empty(self):
        assert MarketDescriptors().is_empty()

    def test_any_field_set_is_not_empty(self):
        assert not MarketDescriptors(population=1000).is_empty()

    def test_round_trip(self):
        d = MarketDescriptors(population=67_000_000, market_maturity="Mature", region="Europe")
        assert MarketDescriptors.from_dict(d.to_dict()) == d

    def test_from_dict_ignores_unknown_keys(self):
        d = MarketDescriptors.from_dict({"population": 100, "not_a_real_field": "x"})
        assert d.population == 100

    def test_from_dict_none_is_empty(self):
        assert MarketDescriptors.from_dict(None) == MarketDescriptors()


class TestMarketCurrency:
    def test_round_trip(self):
        c = MarketCurrency(local_currency="GBP", reporting_currency="USD", exchange_rate_to_reporting=1.27)
        assert MarketCurrency.from_dict(c.to_dict()) == c

    def test_default_local_currency_is_empty_string(self):
        assert MarketCurrency().local_currency == ""


class TestMarketProfile:
    def test_round_trip(self):
        profile = MarketProfile(
            market="UK",
            currency=MarketCurrency(local_currency="GBP"),
            descriptors=MarketDescriptors(population=1000),
        )
        back = MarketProfile.from_dict(profile.to_dict())
        assert back.market == "UK"
        assert back.currency.local_currency == "GBP"
        assert back.descriptors.population == 1000


class TestChannelMediaUnitConfig:
    def test_has_media_unit_true_when_response_unit_column_set(self):
        c = ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP")
        assert c.has_media_unit()

    def test_has_media_unit_false_when_unset(self):
        c = ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend")
        assert not c.has_media_unit()

    def test_round_trip(self):
        c = ChannelMediaUnitConfig(
            market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP",
            unit_type="GRPs", currency="GBP", cost_basis="Cost per GRP", date_frequency="Weekly",
        )
        assert ChannelMediaUnitConfig.from_dict(c.to_dict()) == c


class TestMarketSpecConfig:
    def test_get_profile_returns_empty_profile_for_unknown_market(self):
        cfg = MarketSpecConfig()
        profile = cfg.get_profile("UK")
        assert profile.market == "UK"
        assert profile.descriptors.is_empty()

    def test_set_and_get_profile(self):
        cfg = MarketSpecConfig()
        cfg.set_profile(MarketProfile(market="UK", currency=MarketCurrency(local_currency="GBP")))
        assert cfg.get_profile("UK").currency.local_currency == "GBP"

    def test_set_and_get_media_unit_config(self):
        cfg = MarketSpecConfig()
        cfg.set_media_unit_config(ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP"))
        found = cfg.get_media_unit_config("UK", "TV")
        assert found is not None
        assert found.response_unit_column == "TV_GRP"

    def test_media_unit_config_is_keyed_per_market_and_channel(self):
        cfg = MarketSpecConfig()
        cfg.set_media_unit_config(ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP"))
        assert cfg.get_media_unit_config("Australia", "TV") is None

    def test_coverage_for_market(self):
        cfg = MarketSpecConfig()
        cfg.set_media_unit_config(ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP"))
        coverage = cfg.coverage_for_market("UK", ["TV", "Search"])
        assert coverage == {"TV": True, "Search": False}

    def test_round_trip_preserves_profiles_and_media_units(self):
        cfg = MarketSpecConfig()
        cfg.set_profile(MarketProfile(market="UK", currency=MarketCurrency(local_currency="GBP")))
        cfg.set_media_unit_config(ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRP"))
        back = MarketSpecConfig.from_dict(cfg.to_dict())
        assert back.get_profile("UK").currency.local_currency == "GBP"
        assert back.get_media_unit_config("UK", "TV").response_unit_column == "TV_GRP"

    def test_from_dict_none_is_empty_config(self):
        cfg = MarketSpecConfig.from_dict(None)
        assert cfg.market_profiles == {}
        assert cfg.channel_media_units == {}


class TestMarketDataQualityStatus:
    def test_plenty_of_observations_is_sufficient(self):
        assert market_data_quality_status(104) == "Likely sufficient for a local curve"

    def test_moderate_observations_needs_pooling(self):
        assert market_data_quality_status(26) == "Likely needs pooling"

    def test_few_observations_is_insufficient(self):
        assert market_data_quality_status(4) == "Insufficient - would rely on a transferred estimate"

    def test_boundary_at_min_observations_for_local(self):
        assert market_data_quality_status(52) == "Likely sufficient for a local curve"
        assert market_data_quality_status(51) != "Likely sufficient for a local curve"
