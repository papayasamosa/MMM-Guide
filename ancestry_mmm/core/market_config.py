"""
Market-level and channel-level configuration for the market-specific
hierarchical MMM redesign (see docs/market_hierarchy.md and
docs/media_units_and_inflation.md).

Phase 1 scope: this module only defines and persists the data - market
descriptors, per-market currency, and per-(market, channel) spend/media-unit
mappings. None of it is consumed by the fitting pipeline yet (that starts in
Phase 2, alongside updating the model-specification fingerprint to include
it - see docs/decision_log.md). Storing it now lets users start capturing
this information before the hierarchical model needs it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

# Suggested unit types for a channel's response-unit column - advisory only,
# any string is accepted (see docs/media_units_and_inflation.md).
UNIT_TYPE_SUGGESTIONS = [
    "Impressions", "Clicks", "GRPs", "TVRs", "Reach", "Frequency",
    "Insertions", "Spots", "Circulation", "Video views", "Completed views",
]

# Suggested cost-basis labels for a channel - advisory only.
COST_BASIS_SUGGESTIONS = [
    "CPM", "CPC", "Cost per GRP", "Cost per TVR", "Cost per reach point",
    "Cost per spot", "Cost per insertion",
]


@dataclass
class MarketDescriptors:
    """Optional market context used (in a later phase) to explain
    market-level curve parameters - see docs/market_hierarchy.md section 5.
    Every field is optional: Phase 1 only stores and displays these: nothing
    downstream requires them to be filled in.
    """

    population: Optional[float] = None
    addressable_audience: Optional[float] = None
    subscriber_base: Optional[float] = None
    brand_penetration: Optional[float] = None
    aided_awareness: Optional[float] = None
    unaided_awareness: Optional[float] = None
    market_maturity: Optional[str] = None
    category_penetration: Optional[float] = None
    historical_acquisition_volume: Optional[float] = None
    media_cost_index: Optional[float] = None
    average_product_price: Optional[float] = None
    competitive_intensity: Optional[str] = None
    language_group: Optional[str] = None
    region: Optional[str] = None
    product_availability: Optional[str] = None
    channel_availability: Optional[str] = None

    def is_empty(self) -> bool:
        return all(v is None for v in asdict(self).values())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarketDescriptors":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class MarketCurrency:
    """Currency and exchange-rate context for one market - see
    docs/market_hierarchy.md section 11. `local_currency` is the only field
    that matters for correct reporting; the rest support converting to a
    common reporting currency later.
    """

    local_currency: str = ""
    reporting_currency: Optional[str] = None
    exchange_rate_source: Optional[str] = None
    exchange_rate_date: Optional[str] = None
    exchange_rate_to_reporting: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MarketCurrency":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class MarketProfile:
    """One market's descriptors + currency, keyed by market name. This is
    what the "market card" on the Market Descriptors page reads and writes."""

    market: str
    currency: MarketCurrency = field(default_factory=MarketCurrency)
    descriptors: MarketDescriptors = field(default_factory=MarketDescriptors)

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "currency": self.currency.to_dict(),
            "descriptors": self.descriptors.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MarketProfile":
        return cls(
            market=d["market"],
            currency=MarketCurrency.from_dict(d.get("currency")),
            descriptors=MarketDescriptors.from_dict(d.get("descriptors")),
        )


@dataclass
class ChannelMediaUnitConfig:
    """Spend and physical-delivery mapping for one (market, channel) pair -
    see docs/media_units_and_inflation.md. `spend_column` is required;
    everything else is optional so a channel can be spend-only until a
    response-unit column is mapped.
    """

    market: str
    channel: str
    spend_column: str
    response_unit_column: Optional[str] = None
    unit_type: Optional[str] = None
    currency: Optional[str] = None
    cost_basis: Optional[str] = None
    date_frequency: str = "Weekly"

    def has_media_unit(self) -> bool:
        return bool(self.response_unit_column)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelMediaUnitConfig":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class MarketSpecConfig:
    """Container for every market profile and channel media-unit config in
    the current project. Stored in session state alongside `model_spec` and
    persisted in the project bundle (see core/persistence.py)."""

    market_profiles: Dict[str, MarketProfile] = field(default_factory=dict)
    # keyed by "market::channel" for stable, order-independent lookups
    channel_media_units: Dict[str, ChannelMediaUnitConfig] = field(default_factory=dict)

    @staticmethod
    def _key(market: str, channel: str) -> str:
        return f"{market}::{channel}"

    def get_profile(self, market: str) -> MarketProfile:
        return self.market_profiles.get(market) or MarketProfile(market=market)

    def set_profile(self, profile: MarketProfile) -> None:
        self.market_profiles[profile.market] = profile

    def get_media_unit_config(self, market: str, channel: str) -> Optional[ChannelMediaUnitConfig]:
        return self.channel_media_units.get(self._key(market, channel))

    def set_media_unit_config(self, config: ChannelMediaUnitConfig) -> None:
        self.channel_media_units[self._key(config.market, config.channel)] = config

    def coverage_for_market(self, market: str, channels: List[str]) -> Dict[str, bool]:
        """Which of `channels` have a media-unit mapping for `market` - used
        by the market card's "media-unit coverage" summary."""
        coverage = {}
        for ch in channels:
            config = self.get_media_unit_config(market, ch)
            coverage[ch] = config is not None and config.has_media_unit()
        return coverage

    def to_dict(self) -> dict:
        return {
            "market_profiles": {m: p.to_dict() for m, p in self.market_profiles.items()},
            "channel_media_units": {k: c.to_dict() for k, c in self.channel_media_units.items()},
        }

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "MarketSpecConfig":
        d = d or {}
        return cls(
            market_profiles={
                m: MarketProfile.from_dict(p) for m, p in (d.get("market_profiles") or {}).items()
            },
            channel_media_units={
                k: ChannelMediaUnitConfig.from_dict(c) for k, c in (d.get("channel_media_units") or {}).items()
            },
        )


def market_data_quality_status(
    n_observations: int,
    *,
    min_observations_for_local: int = 52,
    min_observations_for_pooled: int = 12,
) -> str:
    """Coarse, Phase-1 data-quality label for a market card. This is a plain
    observation-count heuristic, not the actual local/pooled/transferred
    curve-status classification from docs/market_hierarchy.md section 4 -
    that requires a fitted model and is Phase 2 scope. Returned labels:
    "Likely sufficient for a local curve", "Likely needs pooling",
    "Insufficient - would rely on a transferred estimate".
    """
    if n_observations >= min_observations_for_local:
        return "Likely sufficient for a local curve"
    if n_observations >= min_observations_for_pooled:
        return "Likely needs pooling"
    return "Insufficient - would rely on a transferred estimate"
