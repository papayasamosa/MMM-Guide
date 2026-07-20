from ancestry_mmm.core.schema import ModelSpec


def _valid_spec(**overrides) -> ModelSpec:
    defaults = dict(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa", "DNA_CrossSell": "fh_dna_gsa"},
        channels=["TV_Brand", "DNA_Media"],
        dna_channels=["DNA_Media"],
    )
    defaults.update(overrides)
    return ModelSpec(**defaults)


def test_valid_spec_has_no_errors():
    assert _valid_spec().validate() == []


def test_missing_date_col_is_an_error():
    errors = _valid_spec(date_col="").validate()
    assert any("Date column" in e for e in errors)


def test_missing_markets_is_an_error():
    errors = _valid_spec(markets=[]).validate()
    assert any("market" in e.lower() for e in errors)


def test_missing_segment_outcomes_is_an_error():
    errors = _valid_spec(segment_outcomes={}).validate()
    assert any("segment" in e.lower() for e in errors)


def test_missing_channels_is_an_error():
    errors = _valid_spec(channels=[]).validate()
    assert any("channel" in e.lower() for e in errors)


def test_dna_channel_not_in_channel_list_is_an_error():
    errors = _valid_spec(channels=["TV_Brand"], dna_channels=["DNA_Media"]).validate()
    assert any("DNA channel" in e for e in errors)


def test_ltv_for_unknown_segment_is_an_error():
    errors = _valid_spec(segment_ltv={"NotASegment": 500.0}).validate()
    assert any("LTV" in e for e in errors)


def test_segments_helper_returns_outcome_keys():
    spec = _valid_spec()
    assert spec.segments() == ["New", "DNA_CrossSell"]


def test_pooled_markets_excludes_unpooled():
    spec = _valid_spec(markets=["UK", "Australia"], unpooled_markets=["Australia"])
    assert spec.pooled_markets() == ["UK"]


def test_to_dict_from_dict_roundtrip():
    spec = _valid_spec(segment_ltv={"New": 250.0, "DNA_CrossSell": 400.0})
    restored = ModelSpec.from_dict(spec.to_dict())
    assert restored == spec


def test_from_dict_ignores_unknown_keys():
    d = _valid_spec().to_dict()
    d["some_future_field_this_version_does_not_know_about"] = "ignored"
    restored = ModelSpec.from_dict(d)
    assert restored == _valid_spec()
