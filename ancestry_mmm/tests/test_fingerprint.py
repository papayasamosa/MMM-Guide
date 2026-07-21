import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig,
    MarketCurrency,
    MarketDescriptors,
    MarketProfile,
    MarketSpecConfig,
)


# ---------------------------------------------------------------------------
# Data fingerprint
# ---------------------------------------------------------------------------

@pytest.fixture
def base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=4, freq="W"),
        "market": ["UK", "UK", "UK", "UK"],
        "TV_Brand": [100.0, 200.0, 150.0, 175.0],
        "fh_new_gsa": [10, 12, 11, 13],
    })


class TestFingerprintDataframe:
    def test_identical_data_same_fingerprint(self, base_df):
        assert fingerprint_dataframe(base_df) == fingerprint_dataframe(base_df.copy())

    def test_changed_value_changes_fingerprint(self, base_df):
        changed = base_df.copy()
        changed.loc[0, "TV_Brand"] = 999.0
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(changed)

    def test_changed_row_order_changes_fingerprint(self, base_df):
        reordered = base_df.iloc[::-1].reset_index(drop=True)
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(reordered)

    def test_changed_column_order_changes_fingerprint(self, base_df):
        reordered = base_df[["market", "date", "fh_new_gsa", "TV_Brand"]]
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(reordered)

    def test_changed_dtype_changes_fingerprint(self, base_df):
        recast = base_df.copy()
        recast["fh_new_gsa"] = recast["fh_new_gsa"].astype(float)
        assert fingerprint_dataframe(base_df) != fingerprint_dataframe(recast)

    def test_missing_values_are_deterministic(self):
        df1 = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        df2 = pd.DataFrame({"a": [1.0, np.nan, 3.0]})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        # ... and distinguishable from a genuinely different value in the same slot.
        df3 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_date_columns_are_deterministic(self):
        df1 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)})
        df2 = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3)})
        df3 = pd.DataFrame({"date": pd.date_range("2024-02-01", periods=3)})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_categorical_columns_are_deterministic(self):
        df1 = pd.DataFrame({"segment": pd.Categorical(["New", "Winback", "New"])})
        df2 = pd.DataFrame({"segment": pd.Categorical(["New", "Winback", "New"])})
        df3 = pd.DataFrame({"segment": pd.Categorical(["New", "New", "New"])})
        assert fingerprint_dataframe(df1) == fingerprint_dataframe(df2)
        assert fingerprint_dataframe(df1) != fingerprint_dataframe(df3)

    def test_empty_dataframe_does_not_raise(self):
        fingerprint_dataframe(pd.DataFrame({"a": []}))
        fingerprint_dataframe(pd.DataFrame())


# ---------------------------------------------------------------------------
# Model-specification fingerprint
# ---------------------------------------------------------------------------

class TestFingerprintModelSpec:
    def test_key_insertion_order_does_not_matter(self):
        spec_a = {"markets": ["UK"], "channels": ["TV", "Search"]}
        spec_b = {"channels": ["TV", "Search"], "markets": ["UK"]}
        assert fingerprint_model_spec(spec_a, {"decay_mu": 0.5}, 4) == fingerprint_model_spec(spec_b, {"decay_mu": 0.5}, 4)

    def test_changed_spec_changes_fingerprint(self):
        spec_a = {"markets": ["UK"], "channels": ["TV"]}
        spec_b = {"markets": ["UK", "Australia"], "channels": ["TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(spec_b, {}, 4)

    def test_changed_prior_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {"decay_mu": 0.5}, 4) != fingerprint_model_spec(spec, {"decay_mu": 0.7}, 4)

    def test_changed_dna_lag_weeks_changes_fingerprint(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) != fingerprint_model_spec(spec, {}, 6)

    def test_list_order_is_preserved_and_meaningful(self):
        spec_a = {"channels": ["TV", "Search"]}
        spec_b = {"channels": ["Search", "TV"]}
        assert fingerprint_model_spec(spec_a, {}, 4) != fingerprint_model_spec(spec_b, {}, 4)

    def test_model_type_defaults_to_shared_and_is_backward_compatible(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, model_type="shared")

    def test_market_specific_model_type_changes_the_fingerprint(self):
        spec = {"markets": ["UK", "Australia"]}
        shared_fp = fingerprint_model_spec(spec, {}, 4, model_type="shared")
        market_specific_fp = fingerprint_model_spec(spec, {}, 4, model_type="market_specific")
        assert shared_fp != market_specific_fp

    def test_switching_model_type_changes_the_fingerprint_even_with_identical_spec_and_priors(self):
        # The scenario this guards against: a user retrains under a different
        # model structure without touching the spec/priors/lag at all - the
        # fingerprint must still change so a stale approval gets invalidated.
        spec = {"markets": ["UK", "Australia"]}
        prior_config = {"decay_mu": 0.5}
        fp_a = fingerprint_model_spec(spec, prior_config, 4, model_type="shared")
        fp_c = fingerprint_model_spec(spec, prior_config, 4, model_type="market_specific")
        assert fp_a != fp_c


# ---------------------------------------------------------------------------
# Model-specification fingerprint: pipeline_steps + market_spec_config
# (PR1 3.3 - see docs/decision_log.md for the descriptive/model-relevant
# boundary this codifies)
# ---------------------------------------------------------------------------

class TestFingerprintModelSpecPipelineSteps:
    def test_no_pipeline_steps_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, pipeline_steps=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, pipeline_steps=[])

    def test_changed_pipeline_steps_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        steps_a = [{"op": "log_transform", "column": "TV_Brand"}]
        steps_b = [{"op": "log_transform", "column": "TV_Brand"}, {"op": "fill_na", "column": "Search"}]
        fp_a = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_b)
        assert fp_a != fp_b

    def test_pipeline_step_order_is_meaningful(self):
        spec = {"markets": ["UK"]}
        steps_a = [{"op": "a"}, {"op": "b"}]
        steps_b = [{"op": "b"}, {"op": "a"}]
        fp_a = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps_b)
        assert fp_a != fp_b

    def test_identical_pipeline_steps_same_fingerprint(self):
        spec = {"markets": ["UK"]}
        steps = [{"op": "log_transform", "column": "TV_Brand"}]
        assert fingerprint_model_spec(spec, {}, 4, pipeline_steps=steps) == fingerprint_model_spec(
            spec, {}, 4, pipeline_steps=list(steps)
        )


class TestFingerprintModelSpecMarketConfig:
    def _config_with(self, *, currency=None, descriptors=None, media_unit=None) -> dict:
        profile = MarketProfile(
            market="UK",
            currency=currency or MarketCurrency(),
            descriptors=descriptors or MarketDescriptors(),
        )
        config = MarketSpecConfig(market_profiles={"UK": profile})
        if media_unit is not None:
            config.set_media_unit_config(media_unit)
        return config.to_dict()

    def test_no_market_spec_config_is_backward_compatible_with_omitting_the_argument(self):
        spec = {"markets": ["UK"]}
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, market_spec_config=None)
        assert fingerprint_model_spec(spec, {}, 4) == fingerprint_model_spec(spec, {}, 4, market_spec_config={})

    def test_changed_market_currency_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(currency=MarketCurrency(local_currency="GBP"))
        config_b = self._config_with(currency=MarketCurrency(local_currency="USD"))
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_channel_media_unit_mapping_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend"))
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(
                market="UK", channel="TV", spend_column="TV_Spend", response_unit_column="TV_GRPs", unit_type="GRPs",
            )
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_cost_basis_changes_the_fingerprint(self):
        spec = {"markets": ["UK"]}
        config_a = self._config_with(
            media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", cost_basis="CPM")
        )
        config_b = self._config_with(
            media_unit=ChannelMediaUnitConfig(market="UK", channel="TV", spend_column="TV_Spend", cost_basis="Cost per GRP")
        )
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a != fp_b

    def test_changed_market_descriptors_do_not_change_the_fingerprint(self):
        # The descriptive/model-relevant boundary: population, awareness etc.
        # are never read by any calculation (core/market_config.py's own
        # docstring), so editing them must not invalidate an approval.
        spec = {"markets": ["UK"]}
        config_a = self._config_with(descriptors=MarketDescriptors(population=1_000_000, region="North"))
        config_b = self._config_with(descriptors=MarketDescriptors(population=5_000_000, region="South"))
        fp_a = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_a)
        fp_b = fingerprint_model_spec(spec, {}, 4, market_spec_config=config_b)
        assert fp_a == fp_b


# ---------------------------------------------------------------------------
# Posterior fingerprint
# ---------------------------------------------------------------------------

class TestFingerprintPosterior:
    def _params(self, beta_tv=0.1):
        return {
            "decay_rate": {"TV": 0.5, "Search": 0.2},
            "hill_K": {"TV": 1000.0, "Search": 500.0},
            "beta": {"New": {"TV": beta_tv}, "Winback": {"TV": 0.05}},
            "gamma_fourier": {"New": np.array([1.0, 2.0, 3.0])},
        }

    def test_identical_params_same_fingerprint(self):
        assert fingerprint_posterior(self._params()) == fingerprint_posterior(self._params())

    def test_changed_param_changes_fingerprint(self):
        assert fingerprint_posterior(self._params(beta_tv=0.1)) != fingerprint_posterior(self._params(beta_tv=0.2))

    def test_reordered_dict_keys_do_not_change_fingerprint(self):
        params_a = self._params()
        params_b = {
            "gamma_fourier": params_a["gamma_fourier"],
            "beta": params_a["beta"],
            "hill_K": params_a["hill_K"],
            "decay_rate": params_a["decay_rate"],
        }
        assert fingerprint_posterior(params_a) == fingerprint_posterior(params_b)

    def test_array_order_is_meaningful(self):
        params_a = {"gamma_fourier": {"New": np.array([1.0, 2.0, 3.0])}}
        params_b = {"gamma_fourier": {"New": np.array([3.0, 2.0, 1.0])}}
        assert fingerprint_posterior(params_a) != fingerprint_posterior(params_b)

    def test_array_shape_matters(self):
        params_a = {"gamma_fourier": {"New": np.array([1.0, 2.0])}}
        params_b = {"gamma_fourier": {"New": np.array([[1.0, 2.0]])}}
        assert fingerprint_posterior(params_a) != fingerprint_posterior(params_b)

    def test_works_on_a_real_fh_posterior_params_dataclass(self):
        from ancestry_mmm.core.predict import FHPosteriorParams

        params = FHPosteriorParams(
            decay_rate={"TV": 0.5}, hill_K={"TV": 1000.0}, hill_S={"TV": 1.0},
            beta={"New": {"TV": 0.1}}, halo_strength={"New": 0.0}, promo_coef={"New": 0.1},
            market_offset={"UK": {"New": 0.0}}, intercept={"New": 2.0}, trend_coef={"New": 0.0},
            gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0}, control_coef={}, segment_control_coef={},
        )
        fp1 = fingerprint_posterior(params)
        fp2 = fingerprint_posterior(params)
        assert fp1 == fp2
        assert isinstance(fp1, str) and len(fp1) == 64  # sha256 hexdigest
