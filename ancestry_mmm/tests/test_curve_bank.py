import numpy as np
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.curve_bank import (
    CURVE_STATUS_LEGACY,
    CURVE_STATUS_SHARED,
    OVERALL,
    CurveBankEntry,
    compare_to_test,
    entries_to_dataframe,
    load_all_entries,
    make_entries,
    make_media_unit_entries,
    save_entries,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.predict import FHPosteriorParams

SEGMENTS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV_Brand", "DNA_Media"]


@pytest.fixture
def shared_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], outcome_ids=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def shared_params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={"TV_Brand": 40000.0, "DNA_Media": 15000.0},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={s: {c: 0.1 for c in CHANNELS} for s in SEGMENTS},
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0},
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={}, outcome_control_coef={},
    )


@pytest.fixture
def market_specific_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK", "Australia"], outcome_ids=SEGMENTS, channels=CHANNELS,
        dna_channels=["DNA_Media"], dna_channel_idx=[1], non_dna_idx=[0],
        dna_outcome_id="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def market_specific_params() -> FHMarketSpecificPosteriorParams:
    markets = ["UK", "Australia"]
    return FHMarketSpecificPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={m: {"TV_Brand": 40000.0, "DNA_Media": 15000.0} for m in markets},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={m: {s: {c: 0.1 for c in CHANNELS} for s in SEGMENTS} for m in markets},
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0},
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={m: {"New": 0.0, "DNA_CrossSell": 0.0} for m in markets},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={}, outcome_control_coef={},
    )


IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


@pytest.fixture
def approval() -> ModelApproval:
    """A model-bound approval matching IDENTITY - the normal, valid case."""
    return ModelApproval(approved_by="Jane Analyst", diagnostics_accepted=["convergence"], **IDENTITY)


class TestMakeEntriesRequiresMatchingApproval:
    def test_missing_approval_argument_raises(self, shared_meta, shared_params):
        with pytest.raises(TypeError):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1",
                model_type="shared", **IDENTITY,
            )  # no approval

    def test_wrong_type_for_approval_raises(self, shared_meta, shared_params):
        with pytest.raises(ApprovalMismatchError):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1",
                approval={"not": "a ModelApproval"}, model_type="shared", **IDENTITY,
            )

    def test_legacy_unbound_approval_raises(self, shared_meta, shared_params):
        legacy = ModelApproval(approved_by="Jane Analyst")  # no identity fields at all
        with pytest.raises(ApprovalMismatchError):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", legacy,
                model_type="shared", **IDENTITY,
            )

    def test_mismatched_run_id_raises(self, shared_meta, shared_params, approval):
        current = dict(IDENTITY)
        current["model_run_id"] = "a-different-run"
        with pytest.raises(ApprovalMismatchError):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
                model_type="shared", **current,
            )

    def test_mismatched_data_fingerprint_raises(self, shared_meta, shared_params, approval):
        current = dict(IDENTITY)
        current["data_fingerprint"] = "different-data"
        with pytest.raises(ApprovalMismatchError):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
                model_type="shared", **current,
            )


class TestMakeEntriesValidation:
    def test_unknown_model_type_raises(self, shared_meta, shared_params, approval):
        with pytest.raises(ValueError, match="model_type must be"):
            make_entries(
                shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
                model_type="not_a_real_type", **IDENTITY,
            )

    def test_market_specific_without_evidence_tiers_raises(self, market_specific_meta, market_specific_params, approval):
        with pytest.raises(ValueError, match="evidence_tiers is required"):
            make_entries(
                market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
                model_type="market_specific", **IDENTITY,
            )


class TestMakeEntriesSharedModel:
    def test_one_entry_per_channel_segment_plus_overall(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        # 2 channels x (2 segments + 1 overall) = 6
        assert len(entries) == 6
        assert all(e.market is None for e in entries)
        assert all(e.curve_status == CURVE_STATUS_SHARED for e in entries)
        assert all(e.model_type == "shared" for e in entries)

    def test_overall_beta_is_sum_of_segment_betas(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        overall = next(e for e in entries if e.channel == "TV_Brand" and e.segment_or_overall == OVERALL)
        expected = sum(shared_params.beta[s]["TV_Brand"] for s in SEGMENTS)
        assert overall.beta == pytest.approx(expected)

    def test_dna_channel_carries_halo_strength_non_dna_channel_does_not(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        dna_entry = next(e for e in entries if e.channel == "DNA_Media" and e.segment_or_overall == "New")
        non_dna_entry = next(e for e in entries if e.channel == "TV_Brand" and e.segment_or_overall == "New")
        assert dna_entry.dna_channel is True
        assert dna_entry.halo_strength == pytest.approx(0.15)
        assert non_dna_entry.dna_channel is False
        assert non_dna_entry.halo_strength is None

    def test_entries_retain_all_model_identifiers(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **IDENTITY,
            model_type="shared",
        )
        for e in entries:
            assert e.model_run_id == IDENTITY["model_run_id"]
            assert e.data_fingerprint == IDENTITY["data_fingerprint"]
            assert e.model_spec_fingerprint == IDENTITY["model_spec_fingerprint"]
            assert e.posterior_fingerprint == IDENTITY["posterior_fingerprint"]
            assert e.legacy_approval is False
            assert e.legacy_format is False


class TestMakeEntriesMarketSpecificModel:
    EVIDENCE_TIERS = {
        "UK": {"TV_Brand": "Locally estimated", "DNA_Media": "Locally estimated"},
        "Australia": {"TV_Brand": "Partially pooled", "DNA_Media": "Transferred estimate"},
    }

    def test_one_entry_per_market_channel_segment_plus_overall(self, market_specific_meta, market_specific_params, approval):
        entries = make_entries(
            market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=self.EVIDENCE_TIERS, **IDENTITY,
        )
        # 2 markets x 2 channels x (2 segments + 1 overall) = 12
        assert len(entries) == 12
        assert {e.market for e in entries} == {"UK", "Australia"}
        assert all(e.model_type == "market_specific" for e in entries)

    def test_curve_status_comes_from_evidence_tiers_per_market_and_channel(self, market_specific_meta, market_specific_params, approval):
        entries = make_entries(
            market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=self.EVIDENCE_TIERS, **IDENTITY,
        )
        uk_tv = next(e for e in entries if e.market == "UK" and e.channel == "TV_Brand" and e.segment_or_overall == "New")
        au_dna = next(e for e in entries if e.market == "Australia" and e.channel == "DNA_Media" and e.segment_or_overall == "New")
        assert uk_tv.curve_status == "Locally estimated"
        assert au_dna.curve_status == "Transferred estimate"

    def test_currency_by_market_is_applied_per_market(self, market_specific_meta, market_specific_params, approval):
        entries = make_entries(
            market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=self.EVIDENCE_TIERS,
            currency_by_market={"UK": "GBP", "Australia": "AUD"}, **IDENTITY,
        )
        uk_entry = next(e for e in entries if e.market == "UK")
        au_entry = next(e for e in entries if e.market == "Australia")
        assert uk_entry.currency == "GBP"
        assert au_entry.currency == "AUD"

    def test_missing_currency_for_a_market_defaults_to_none(self, market_specific_meta, market_specific_params, approval):
        entries = make_entries(
            market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=self.EVIDENCE_TIERS,
            currency_by_market={"UK": "GBP"}, **IDENTITY,
        )
        au_entry = next(e for e in entries if e.market == "Australia")
        assert au_entry.currency is None

    def test_beta_differs_between_markets_when_params_do(self, market_specific_meta, approval):
        markets = ["UK", "Australia"]
        params = FHMarketSpecificPosteriorParams(
            decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
            hill_K={m: {"TV_Brand": 40000.0, "DNA_Media": 15000.0} for m in markets},
            hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
            beta={
                "UK": {s: {c: 0.2 for c in CHANNELS} for s in SEGMENTS},
                "Australia": {s: {c: 0.05 for c in CHANNELS} for s in SEGMENTS},
            },
            halo_strength={"New": 0.15, "DNA_CrossSell": 1.0},
            promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
            market_offset={m: {"New": 0.0, "DNA_CrossSell": 0.0} for m in markets},
            intercept={"New": 3.0, "DNA_CrossSell": 2.0},
            trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
            gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
            alpha={"New": 5.0, "DNA_CrossSell": 5.0},
            control_coef={}, outcome_control_coef={},
        )
        entries = make_entries(
            market_specific_meta, params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=self.EVIDENCE_TIERS, **IDENTITY,
        )
        uk_beta = next(e for e in entries if e.market == "UK" and e.channel == "TV_Brand" and e.segment_or_overall == "New").beta
        au_beta = next(e for e in entries if e.market == "Australia" and e.channel == "TV_Brand" and e.segment_or_overall == "New").beta
        assert uk_beta == pytest.approx(0.2)
        assert au_beta == pytest.approx(0.05)


class TestCurveBankEntryRoundtrip:
    def test_current_format_roundtrip(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", notes="first run", **IDENTITY,
        )
        for entry in entries:
            restored = CurveBankEntry.from_dict(entry.to_dict())
            assert restored == [entry]


class TestLegacyEntryExpansion:
    LEGACY_DICT = {
        "entry_id": "abc123", "created_at": 1700000000.0, "run_label": "legacy-run",
        "data_window": ("2023-01-01", "2023-12-31"), "markets": ["UK"], "segments": SEGMENTS,
        "channels": CHANNELS, "dna_channels": ["DNA_Media"], "dna_segment": "DNA_CrossSell",
        "decay_rate": {"TV_Brand": 0.5, "DNA_Media": 0.4},
        "hill_K": {"TV_Brand": 1000.0, "DNA_Media": 500.0},
        "hill_S": {"TV_Brand": 1.0, "DNA_Media": 1.1},
        "beta": {"New": {"TV_Brand": 0.1, "DNA_Media": 0.05}, "DNA_CrossSell": {"TV_Brand": 0.02, "DNA_Media": 0.2}},
        "halo_strength": {"New": 0.15, "DNA_CrossSell": 1.0}, "promo_coef": {"New": 0.1, "DNA_CrossSell": 0.2},
        # no approved_by / approved_at / model_run_id / fingerprints - simulates a
        # curve bank file from before either the approval gate or model-binding existed.
    }

    def test_expands_into_one_entry_per_segment_plus_overall_per_channel(self):
        entries = CurveBankEntry.from_dict(self.LEGACY_DICT)
        # 2 channels x (2 segments + 1 overall) = 6
        assert len(entries) == 6
        assert all(e.legacy_format for e in entries)
        assert all(e.curve_status == CURVE_STATUS_LEGACY for e in entries)
        assert all(e.market is None for e in entries)
        assert all(e.model_type == "shared" for e in entries)

    def test_backfills_missing_approval_fields_instead_of_raising(self):
        entries = CurveBankEntry.from_dict(self.LEGACY_DICT)
        assert all("unknown" in e.approved_by.lower() for e in entries)
        assert all(e.approved_at == self.LEGACY_DICT["created_at"] for e in entries)
        assert all(e.legacy_approval is True for e in entries)
        assert all(e.model_run_id == "" for e in entries)

    def test_overall_beta_is_sum_of_segment_betas(self):
        entries = CurveBankEntry.from_dict(self.LEGACY_DICT)
        overall = next(e for e in entries if e.channel == "TV_Brand" and e.segment_or_overall == OVERALL)
        assert overall.beta == pytest.approx(0.1 + 0.02)

    def test_dna_halo_only_carried_for_the_dna_channel(self):
        entries = CurveBankEntry.from_dict(self.LEGACY_DICT)
        dna_entry = next(e for e in entries if e.channel == "DNA_Media" and e.segment_or_overall == "New")
        non_dna_entry = next(e for e in entries if e.channel == "TV_Brand" and e.segment_or_overall == "New")
        assert dna_entry.halo_strength == pytest.approx(0.15)
        assert non_dna_entry.halo_strength is None

    def test_entry_ids_are_deterministic_and_unique(self):
        entries = CurveBankEntry.from_dict(self.LEGACY_DICT)
        ids = [e.entry_id for e in entries]
        assert len(ids) == len(set(ids))
        assert all(id_.startswith("abc123::") for id_ in ids)


def test_new_entries_are_not_marked_legacy(shared_meta, shared_params, approval):
    entries = make_entries(
        shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
        model_type="shared", **IDENTITY,
    )
    assert all(not e.legacy_approval and not e.legacy_format for e in entries)


def test_curve_bank_is_append_only_and_versioned(tmp_path, shared_meta, shared_params, approval):
    entries_1 = make_entries(
        shared_meta, shared_params, ("2024-01-01", "2024-06-30"), "uk-v1", approval,
        model_type="shared", **IDENTITY,
    )
    entries_2 = make_entries(
        shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v2", approval,
        model_type="shared", **IDENTITY,
    )

    save_entries(tmp_path, entries_1)
    save_entries(tmp_path, entries_2)

    loaded = load_all_entries(tmp_path)
    assert {e.entry_id for e in loaded} == {e.entry_id for e in entries_1} | {e.entry_id for e in entries_2}
    # Never overwritten in place: every file exists independently on disk.
    assert len(list(tmp_path.glob("*.json"))) == len(entries_1) + len(entries_2)


def test_entries_to_dataframe_includes_approval_and_status_columns(shared_meta, shared_params, approval):
    entries = make_entries(
        shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
        model_type="shared", **IDENTITY,
    )
    df = entries_to_dataframe(entries)
    assert len(df) == len(entries)
    assert "approved_by" in df.columns
    assert (df["approved_by"] == "Jane Analyst").all()
    assert "model_run_id" in df.columns
    assert "curve_status" in df.columns
    assert (df["curve_status"] == CURVE_STATUS_SHARED).all()
    assert "legacy_approval" in df.columns
    assert (df["legacy_approval"] == False).all()  # noqa: E712
    assert (df["market"] == "(shared)").all()


class TestCompareToTest:
    def test_agrees_when_inside_credible_interval(self):
        assert compare_to_test(model_estimate=2.5, test_estimate=2.0, test_ci=(2.0, 3.0)) == "agrees"

    def test_diverges_when_outside_credible_interval(self):
        assert compare_to_test(model_estimate=5.0, test_estimate=2.0, test_ci=(2.0, 3.0)) == "diverges"

    def test_falls_back_to_tolerance_percent_without_ci(self):
        assert compare_to_test(model_estimate=1.05, test_estimate=1.0, tolerance_pct=10.0) == "agrees"
        assert compare_to_test(model_estimate=1.5, test_estimate=1.0, tolerance_pct=10.0) == "diverges"


class TestMakeMediaUnitEntries:
    def test_only_mirrors_channels_with_a_media_unit_mapping(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        media_unit_info = {(None, "TV_Brand"): {"unit_type": "GRPs", "currency": "GBP", "avg_cost_per_unit": 25.0}}
        mirrored = make_media_unit_entries(entries, media_unit_info)
        assert {e.channel for e in mirrored} == {"TV_Brand"}
        assert all(e.input_type == "media_unit" for e in mirrored)
        # 1 channel x (2 segments + overall) = 3 mirrored entries
        assert len(mirrored) == 3

    def test_mirrored_entries_carry_the_cost_context(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        media_unit_info = {(None, "TV_Brand"): {"unit_type": "GRPs", "currency": "GBP", "avg_cost_per_unit": 25.0}}
        mirrored = make_media_unit_entries(entries, media_unit_info)
        m = mirrored[0]
        assert m.unit_type == "GRPs"
        assert m.currency == "GBP"
        assert m.cost_per_unit == pytest.approx(25.0)

    def test_mirrored_entries_carry_the_same_curve_parameters_as_the_source(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        media_unit_info = {(None, "TV_Brand"): {"unit_type": "GRPs", "currency": "GBP", "avg_cost_per_unit": 25.0}}
        mirrored = make_media_unit_entries(entries, media_unit_info)
        source = next(e for e in entries if e.channel == "TV_Brand" and e.segment_or_overall == mirrored[0].segment_or_overall)
        assert mirrored[0].beta == pytest.approx(source.beta)
        assert mirrored[0].hill_K == pytest.approx(source.hill_K)
        assert mirrored[0].entry_id != source.entry_id  # a distinct record, not the same one mutated

    def test_no_mapping_means_no_mirrored_entries(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        assert make_media_unit_entries(entries, {}) == []

    def test_does_not_mirror_an_already_media_unit_entry(self, shared_meta, shared_params, approval):
        entries = make_entries(
            shared_meta, shared_params, ("2024-01-01", "2024-12-31"), "uk-v1", approval,
            model_type="shared", **IDENTITY,
        )
        media_unit_info = {(None, "TV_Brand"): {"unit_type": "GRPs", "currency": "GBP", "avg_cost_per_unit": 25.0}}
        once = make_media_unit_entries(entries, media_unit_info)
        twice = make_media_unit_entries(once, media_unit_info)
        assert twice == []

    def test_matches_by_market_for_a_market_specific_run(self, market_specific_meta, market_specific_params, approval):
        evidence_tiers = {
            "UK": {"TV_Brand": "Locally estimated", "DNA_Media": "Locally estimated"},
            "Australia": {"TV_Brand": "Partially pooled", "DNA_Media": "Transferred estimate"},
        }
        entries = make_entries(
            market_specific_meta, market_specific_params, ("2024-01-01", "2024-12-31"), "uk-au-v1", approval,
            model_type="market_specific", evidence_tiers=evidence_tiers, **IDENTITY,
        )
        media_unit_info = {
            ("UK", "TV_Brand"): {"unit_type": "GRPs", "currency": "GBP", "avg_cost_per_unit": 25.0},
        }
        mirrored = make_media_unit_entries(entries, media_unit_info)
        assert all(e.market == "UK" and e.channel == "TV_Brand" for e in mirrored)
        assert len(mirrored) == 3  # 2 segments + overall, for UK/TV_Brand only
