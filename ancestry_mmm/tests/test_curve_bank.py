import numpy as np
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.curve_bank import (
    CurveBankEntry,
    compare_to_test,
    entries_to_dataframe,
    load_all_entries,
    make_entry,
    save_entry,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.predict import FHPosteriorParams


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        segments=["New", "DNA_CrossSell"],
        channels=["TV_Brand", "DNA_Media"],
        dna_channels=["DNA_Media"],
        dna_channel_idx=[1],
        non_dna_idx=[0],
        dna_segment="DNA_CrossSell",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    segments = ["New", "DNA_CrossSell"]
    channels = ["TV_Brand", "DNA_Media"]
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.7, "DNA_Media": 0.5},
        hill_K={"TV_Brand": 40000.0, "DNA_Media": 15000.0},
        hill_S={"TV_Brand": 1.2, "DNA_Media": 1.0},
        beta={s: {c: 0.1 for c in channels} for s in segments},
        halo_strength={"New": 0.15, "DNA_CrossSell": 1.0},
        promo_coef={"New": 0.2, "DNA_CrossSell": 0.3},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}},
        intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.1, "DNA_CrossSell": 0.05},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0},
        control_coef={},
        segment_control_coef={},
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


class TestMakeEntryRequiresMatchingApproval:
    def test_missing_approval_argument_raises(self, meta, params):
        with pytest.raises(TypeError):
            make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", **IDENTITY)  # no approval

    def test_wrong_type_for_approval_raises(self, meta, params):
        with pytest.raises(ApprovalMismatchError):
            make_entry(
                meta, params, ("2024-01-01", "2024-12-31"), "uk-v1",
                approval={"not": "a ModelApproval"}, **IDENTITY,
            )

    def test_legacy_unbound_approval_raises(self, meta, params):
        legacy = ModelApproval(approved_by="Jane Analyst")  # no identity fields at all
        with pytest.raises(ApprovalMismatchError):
            make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", legacy, **IDENTITY)

    def test_mismatched_run_id_raises(self, meta, params, approval):
        current = dict(IDENTITY)
        current["model_run_id"] = "a-different-run"
        with pytest.raises(ApprovalMismatchError):
            make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **current)

    def test_mismatched_data_fingerprint_raises(self, meta, params, approval):
        current = dict(IDENTITY)
        current["data_fingerprint"] = "different-data"
        with pytest.raises(ApprovalMismatchError):
            make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **current)

    def test_valid_matching_approval_permits_entry_creation(self, meta, params, approval):
        entry = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **IDENTITY)
        assert entry.approved_by == "Jane Analyst"
        assert entry.approved_at == approval.approved_at
        assert entry.diagnostics_accepted == ["convergence"]

    def test_entry_retains_all_model_identifiers(self, meta, params, approval):
        entry = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **IDENTITY)
        assert entry.model_run_id == IDENTITY["model_run_id"]
        assert entry.data_fingerprint == IDENTITY["data_fingerprint"]
        assert entry.model_spec_fingerprint == IDENTITY["model_spec_fingerprint"]
        assert entry.posterior_fingerprint == IDENTITY["posterior_fingerprint"]
        assert entry.legacy_approval is False


def test_curve_bank_entry_roundtrip(meta, params, approval):
    entry = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, notes="first run", **IDENTITY)
    restored = CurveBankEntry.from_dict(entry.to_dict())
    assert restored == entry


def test_legacy_entry_without_approval_fields_backfills_instead_of_raising():
    legacy = {
        "entry_id": "abc123", "created_at": 1700000000.0, "run_label": "legacy-run",
        "data_window": ("2023-01-01", "2023-12-31"), "markets": ["UK"], "segments": ["New"],
        "channels": ["TV_Brand"], "dna_channels": [], "dna_segment": "New",
        "decay_rate": {"TV_Brand": 0.5}, "hill_K": {"TV_Brand": 1000.0}, "hill_S": {"TV_Brand": 1.0},
        "beta": {"New": {"TV_Brand": 0.1}}, "halo_strength": {"New": 0.0}, "promo_coef": {"New": 0.1},
        # no approved_by / approved_at / model_run_id / fingerprints - simulates a
        # curve bank file from before either the approval gate or model-binding existed.
    }
    entry = CurveBankEntry.from_dict(legacy)
    assert "unknown" in entry.approved_by.lower()
    assert entry.approved_at == legacy["created_at"]
    assert entry.legacy_approval is True
    assert entry.model_run_id == ""


def test_new_entry_is_not_marked_legacy(meta, params, approval):
    entry = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **IDENTITY)
    restored = CurveBankEntry.from_dict(entry.to_dict())
    assert restored.legacy_approval is False


def test_curve_bank_is_append_only_and_versioned(tmp_path, meta, params, approval):
    entry_1 = make_entry(meta, params, ("2024-01-01", "2024-06-30"), "uk-v1", approval, **IDENTITY)
    entry_2 = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v2", approval, **IDENTITY)

    save_entry(tmp_path, entry_1)
    save_entry(tmp_path, entry_2)

    loaded = load_all_entries(tmp_path)
    assert {e.entry_id for e in loaded} == {entry_1.entry_id, entry_2.entry_id}
    # Never overwritten in place: both files exist independently on disk.
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_entries_to_dataframe_includes_approval_and_legacy_columns(meta, params, approval):
    entry = make_entry(meta, params, ("2024-01-01", "2024-12-31"), "uk-v1", approval, **IDENTITY)
    df = entries_to_dataframe([entry])
    assert "approved_by" in df.columns
    assert (df["approved_by"] == "Jane Analyst").all()
    assert "model_run_id" in df.columns
    assert "legacy_approval" in df.columns
    assert (df["legacy_approval"] == False).all()  # noqa: E712


class TestCompareToTest:
    def test_agrees_when_inside_credible_interval(self):
        assert compare_to_test(model_estimate=2.5, test_estimate=2.0, test_ci=(2.0, 3.0)) == "agrees"

    def test_diverges_when_outside_credible_interval(self):
        assert compare_to_test(model_estimate=5.0, test_estimate=2.0, test_ci=(2.0, 3.0)) == "diverges"

    def test_falls_back_to_tolerance_percent_without_ci(self):
        assert compare_to_test(model_estimate=1.05, test_estimate=1.0, tolerance_pct=10.0) == "agrees"
        assert compare_to_test(model_estimate=1.5, test_estimate=1.0, tolerance_pct=10.0) == "diverges"
