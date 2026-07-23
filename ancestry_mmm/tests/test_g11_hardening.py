import numpy as np
import pandas as pd
import pytest
from ancestry_mmm.core.net_billthrough import (
    NetBillthroughCompletenessMetadata,
    validate_supplied_net_billthrough,
    assert_supplied_net_billthrough_complete,
)
from ancestry_mmm.core.pathways import (
    MediaOutcomePathway,
    resolve_pathway_masks,
    validate_media_outcome_pathways,
)
from ancestry_mmm.core.brand_search import fit_experimental_brand_search_mediation


def metadata(**kw):
    d = dict(
        data_as_of_date="2024-02-01",
        model_start_week="2024-01-01",
        model_end_week="2024-01-15",
        latest_complete_net_billthrough_week="2024-01-15",
        maturity_rule_description="authoritative upstream finalisation",
        source_owner="Finance Analytics",
    )
    d.update(kw)
    return NetBillthroughCompletenessMetadata(**d)


def valid_data():
    return pd.DataFrame(
        {
            "week_start": pd.date_range("2024-01-01", periods=3, freq="7D"),
            "market": ["UK"] * 3,
            "segment": ["new"] * 3,
            "fh_net_billthrough_count": [1, 2, 3],
        }
    )


def test_authoritative_nbt_validation_and_training_block():
    assert (
        validate_supplied_net_billthrough(
            valid_data(),
            metadata(),
            configured_markets=["UK"],
            configured_segments=["new"],
        )
        == []
    )
    with pytest.raises(ValueError, match="training blocked"):
        assert_supplied_net_billthrough_complete(
            valid_data(),
            metadata(latest_complete_net_billthrough_week="2024-01-08"),
            configured_markets=["UK"],
            configured_segments=["new"],
        )


def test_nbt_duplicate_missing_negative_fractional():
    df = valid_data().iloc[[0, 0, 2]].copy()
    df["fh_net_billthrough_count"] = df["fh_net_billthrough_count"].astype(float)
    df.iloc[0, 3] = -1
    df.iloc[1, 3] = 1.5
    errors = validate_supplied_net_billthrough(
        df, metadata(), configured_markets=["UK"], configured_segments=["new"]
    )
    assert any("duplicate" in e for e in errors)
    assert any("missing" in e for e in errors)
    assert any("non-negative" in e for e in errors)
    assert any("integer-like" in e for e in errors)


def test_components_lags_priors_coexist():
    direct = MediaOutcomePathway("TV", "Family History", "fh", component_type="direct")
    delayed = MediaOutcomePathway(
        "TV",
        "Family History",
        "fh",
        role="active_cross_product",
        component_type="cross_product",
        lag_type="fixed_weeks",
        lag_weeks=3,
        prior_scale=0.15,
        include_in_planning=False,
    )
    assert (
        validate_media_outcome_pathways(
            [direct, delayed], channels=["TV"], outcome_ids=["fh"]
        )
        == []
    )
    masks = resolve_pathway_masks(
        ["fh"],
        ["TV"],
        [direct, delayed],
        dna_channel_idx=[],
        dna_outcome_id=None,
        direct_dna_outcome_ids=[],
        dna_lag_weeks=0,
    )
    assert masks.primary_matrix(["fh"], ["TV"])[0, 0] == 1
    assert masks.active_cells(["fh"], ["TV"]) == [(0, 0)]
    assert masks.lag_for_cell((0, 0)) == 3 and masks.prior_for_cell((0, 0), 1) == 0.15


def test_experimental_mediation_recovers_simulation():
    rng = np.random.default_rng(3)
    x = rng.normal(size=1000)
    brand = 0.7 * x + rng.normal(scale=0.5, size=1000)
    y = 0.3 * x + 0.5 * brand + rng.normal(scale=0.05, size=1000)
    result = fit_experimental_brand_search_mediation(
        brand, y, {"TV": x}, permitted_upstream_edges=["TV"]
    )
    assert result.direct_effect["TV"] == pytest.approx(0.3, abs=0.02)
    assert result.indirect_effect["TV"] == pytest.approx(0.35, abs=0.02)
    assert result.total_effect["TV"] == pytest.approx(0.65, abs=0.02)
