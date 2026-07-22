"""Tests for core.brand_search - Brand Search treatment modes (PR G1).
Required test cases covered: Brand Search direct/excluded/mediator modes
all fit (via brand_search_pathway_role's mapping onto core.pathways roles),
mediator decomposition reconciles."""

import pandas as pd
import pytest

from ancestry_mmm.core.brand_search import (
    MODE_DEMAND_CAPTURE_MEDIATOR,
    MODE_DIRECT_CHANNEL,
    MODE_EXCLUDED,
    MODE_EXPERIMENT_CALIBRATED_INCREMENTAL,
    BrandSearchConfig,
    apply_experiment_calibration,
    brand_search_pathway_role,
    mediator_reallocation,
    validate_brand_search_configs,
)


class TestBrandSearchPathwayRoleMapping:
    """Required test case: Brand Search direct/excluded/mediator modes all
    fit - proven here by confirming each mode maps onto a valid
    core.pathways role (the only touchpoint into actual model fitting)."""

    def test_direct_channel_maps_to_primary_direct(self):
        assert brand_search_pathway_role(MODE_DIRECT_CHANNEL) == "primary_direct"

    def test_excluded_maps_to_excluded(self):
        assert brand_search_pathway_role(MODE_EXCLUDED) == "excluded"

    def test_demand_capture_mediator_maps_to_primary_direct(self):
        # Fits exactly like direct_channel - only reporting differs.
        assert brand_search_pathway_role(MODE_DEMAND_CAPTURE_MEDIATOR) == "primary_direct"

    def test_experiment_calibrated_incremental_maps_to_primary_direct(self):
        assert brand_search_pathway_role(MODE_EXPERIMENT_CALIBRATED_INCREMENTAL) == "primary_direct"

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unknown Brand Search mode"):
            brand_search_pathway_role("not_a_real_mode")


class TestBrandSearchConfigValidation:
    def test_direct_channel_needs_nothing_else(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_DIRECT_CHANNEL)
        assert config.validate() == []

    def test_excluded_needs_nothing_else(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_EXCLUDED)
        assert config.validate() == []

    def test_demand_capture_mediator_requires_mediator_of(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR, mediation_share=0.5)
        errors = validate_brand_search_configs([config])
        assert any("mediator_of" in e for e in errors)

    def test_demand_capture_mediator_requires_mediation_share(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR, mediator_of=["TV"])
        errors = validate_brand_search_configs([config])
        assert any("mediation_share" in e for e in errors)

    def test_demand_capture_mediator_rejects_out_of_range_mediation_share(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR, mediator_of=["TV"], mediation_share=1.5,
        )
        errors = validate_brand_search_configs([config])
        assert any("mediation_share" in e for e in errors)

    def test_demand_capture_mediator_rejects_self_reference(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR,
            mediator_of=["Brand_Search"], mediation_share=0.5,
        )
        errors = validate_brand_search_configs([config])
        assert any("own mediator_of" in e for e in errors)

    def test_demand_capture_mediator_rejects_unknown_channel_when_checked(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR, mediator_of=["Nonexistent"], mediation_share=0.5,
        )
        errors = validate_brand_search_configs([config], known_channels=["TV", "Brand_Search"])
        assert any("unknown channel" in e for e in errors)

    def test_valid_demand_capture_mediator_config_passes(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR, mediator_of=["TV", "YouTube"], mediation_share=0.4,
        )
        assert config.validate(known_channels=["TV", "YouTube", "Brand_Search"]) == []

    def test_experiment_calibrated_requires_calibration_factor(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_EXPERIMENT_CALIBRATED_INCREMENTAL)
        errors = validate_brand_search_configs([config])
        assert any("calibration_factor" in e for e in errors)

    def test_experiment_calibrated_rejects_out_of_range_calibration_factor(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_EXPERIMENT_CALIBRATED_INCREMENTAL, calibration_factor=1.2)
        errors = validate_brand_search_configs([config])
        assert any("calibration_factor" in e for e in errors)

    def test_unknown_mode_is_rejected(self):
        config = BrandSearchConfig(channel="Brand_Search", mode="not_a_real_mode")
        errors = validate_brand_search_configs([config])
        assert any("unknown Brand Search mode" in e for e in errors)

    def test_duplicate_channel_configs_rejected(self):
        configs = [
            BrandSearchConfig(channel="Brand_Search", mode=MODE_DIRECT_CHANNEL),
            BrandSearchConfig(channel="Brand_Search", mode=MODE_EXCLUDED),
        ]
        errors = validate_brand_search_configs(configs)
        assert any("Duplicate" in e for e in errors)

    def test_round_trip_to_dict_from_dict(self):
        config = BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR,
            mediator_of=["TV"], mediation_share=0.3, notes="Q3 2024 config",
        )
        assert BrandSearchConfig.from_dict(config.to_dict()) == config


class TestMediatorReallocationReconciles:
    """Required test case: mediator decomposition reconciles."""

    def _config(self, mediation_share: float) -> BrandSearchConfig:
        return BrandSearchConfig(
            channel="Brand_Search", mode=MODE_DEMAND_CAPTURE_MEDIATOR,
            mediator_of=["TV", "YouTube"], mediation_share=mediation_share,
        )

    def test_direct_plus_mediated_sums_to_the_original_contribution(self):
        brand_search_contribution = pd.Series([100.0, 200.0, 0.0, 50.0])
        upstream = {
            "TV": pd.Series([10.0, 40.0, 0.0, 0.0]),
            "YouTube": pd.Series([30.0, 10.0, 0.0, 5.0]),
        }
        result = mediator_reallocation(self._config(0.4), brand_search_contribution, upstream)
        reconstructed = result["direct"] + result["mediated_by_TV"] + result["mediated_by_YouTube"]
        pd.testing.assert_series_equal(reconstructed, brand_search_contribution, check_names=False)

    def test_zero_mediation_share_keeps_everything_direct(self):
        brand_search_contribution = pd.Series([100.0, 200.0])
        upstream = {"TV": pd.Series([10.0, 40.0]), "YouTube": pd.Series([30.0, 10.0])}
        result = mediator_reallocation(self._config(0.0), brand_search_contribution, upstream)
        pd.testing.assert_series_equal(result["direct"], brand_search_contribution, check_names=False)
        assert (result["mediated_by_TV"] == 0.0).all()
        assert (result["mediated_by_YouTube"] == 0.0).all()

    def test_full_mediation_share_reallocates_the_entire_contribution(self):
        brand_search_contribution = pd.Series([100.0])
        upstream = {"TV": pd.Series([10.0]), "YouTube": pd.Series([30.0])}
        result = mediator_reallocation(self._config(1.0), brand_search_contribution, upstream)
        assert result["direct"].iloc[0] == pytest.approx(0.0)
        # TV got 10/40 = 25% of upstream activity, YouTube 75%.
        assert result["mediated_by_TV"].iloc[0] == pytest.approx(25.0)
        assert result["mediated_by_YouTube"].iloc[0] == pytest.approx(75.0)

    def test_zero_upstream_activity_period_keeps_the_mediated_pool_direct(self):
        # No upstream activity to attribute demand capture to that period -
        # the would-be-mediated share folds back onto direct rather than
        # vanishing, so reconciliation still holds exactly.
        brand_search_contribution = pd.Series([100.0])
        upstream = {"TV": pd.Series([0.0]), "YouTube": pd.Series([0.0])}
        result = mediator_reallocation(self._config(0.6), brand_search_contribution, upstream)
        assert result["direct"].iloc[0] == pytest.approx(100.0)
        assert result["mediated_by_TV"].iloc[0] == pytest.approx(0.0)
        assert result["mediated_by_YouTube"].iloc[0] == pytest.approx(0.0)

    def test_wrong_mode_raises(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_DIRECT_CHANNEL)
        with pytest.raises(ValueError, match="only applies to"):
            mediator_reallocation(config, pd.Series([1.0]), {})


class TestExperimentCalibratedIncremental:
    def test_scales_raw_contribution_by_calibration_factor(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_EXPERIMENT_CALIBRATED_INCREMENTAL, calibration_factor=0.3)
        raw = pd.Series([100.0, 200.0])
        result = apply_experiment_calibration(config, raw)
        pd.testing.assert_series_equal(result, pd.Series([30.0, 60.0]))

    def test_zero_calibration_factor_zeroes_out_the_contribution(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_EXPERIMENT_CALIBRATED_INCREMENTAL, calibration_factor=0.0)
        result = apply_experiment_calibration(config, pd.Series([100.0]))
        assert result.iloc[0] == pytest.approx(0.0)

    def test_wrong_mode_raises(self):
        config = BrandSearchConfig(channel="Brand_Search", mode=MODE_DIRECT_CHANNEL)
        with pytest.raises(ValueError, match="only applies to"):
            apply_experiment_calibration(config, pd.Series([1.0]))
