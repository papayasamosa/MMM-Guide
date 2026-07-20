import zipfile
from dataclasses import asdict

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec, fingerprint_posterior
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_config import ChannelMediaUnitConfig, MarketCurrency, MarketProfile, MarketSpecConfig
from ancestry_mmm.core.optimization import SpendConstraint
from ancestry_mmm.core.persistence import (
    UnsafeZipEntryError,
    _is_safe_zip_member,
    _safe_extract_zip,
    export_excel_summary,
    export_project,
    import_project,
    reconstruct_model_state,
    verify_imported_approval,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame


# ---------------------------------------------------------------------------
# Zip-slip / path-traversal protection
# ---------------------------------------------------------------------------

class TestIsSafeZipMember:
    @pytest.mark.parametrize("name", [
        "data/raw_media.parquet",
        "config/model_spec.json",
        "a/b/c.txt",
        "curve_bank/1700000000_abc.json",
        "trailing_slash_dir/",
    ])
    def test_accepts_plain_relative_paths(self, name):
        assert _is_safe_zip_member(name) is True

    @pytest.mark.parametrize("name", [
        "../evil.txt",
        "../../etc/passwd",
        "data/../../evil.txt",
        "/etc/passwd",
        "/absolute/path.txt",
        "\\windows\\absolute.txt",
        "C:\\evil.txt",
        "C:evil.txt",
        "a/b/../../../evil.txt",
        "",
    ])
    def test_rejects_absolute_or_traversal_paths(self, name):
        assert _is_safe_zip_member(name) is False


class TestSafeExtractZip:
    def test_extracts_a_well_formed_archive(self, tmp_path):
        zip_path = tmp_path / "good.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("data/raw_media.parquet", b"not really parquet but fine for this test")
            zf.writestr("config/model_spec.json", "{}")

        dest = tmp_path / "extracted"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            _safe_extract_zip(zf, dest)

        assert (dest / "data" / "raw_media.parquet").exists()
        assert (dest / "config" / "model_spec.json").exists()

    def test_rejects_relative_traversal_entry_and_extracts_nothing(self, tmp_path):
        # Build the archive with raw ZipInfo so we control the member name
        # exactly (bypassing any path handling zipfile.write() might apply).
        zip_path = tmp_path / "malicious.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(zipfile.ZipInfo("safe_first_entry.txt"), "fine")
            zf.writestr(zipfile.ZipInfo("../escaped.txt"), "pwned")

        dest = tmp_path / "extract_here"
        dest.mkdir()
        outside_marker = tmp_path / "escaped.txt"

        with zipfile.ZipFile(zip_path) as zf:
            with pytest.raises(UnsafeZipEntryError):
                _safe_extract_zip(zf, dest)

        assert not outside_marker.exists()
        # All-or-nothing: the safe entry that sorted before the malicious one
        # must not have been extracted either.
        assert list(dest.iterdir()) == []

    def test_rejects_absolute_path_entry(self, tmp_path):
        zip_path = tmp_path / "malicious_abs.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(zipfile.ZipInfo("/tmp/absolute_evil.txt"), "pwned")

        dest = tmp_path / "extract_here"
        dest.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            with pytest.raises(UnsafeZipEntryError):
                _safe_extract_zip(zf, dest)

    def test_import_project_rejects_malicious_bundle(self, tmp_path):
        zip_path = tmp_path / "malicious_project.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(zipfile.ZipInfo("../../evil.json"), "{}")

        with pytest.raises(UnsafeZipEntryError):
            import_project(zip_path)


# ---------------------------------------------------------------------------
# Core project persistence behaviour: export -> import round trip
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_trace() -> az.InferenceData:
    rng = np.random.default_rng(0)
    return az.from_dict(posterior={"intercept": rng.normal(size=(2, 25))})


@pytest.fixture
def sample_project(sample_trace):
    raw_sources = {
        "media": pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "TV_Brand": [100.0, 200.0, 150.0]}),
        "outcomes": pd.DataFrame({"date": pd.date_range("2024-01-01", periods=3), "fh_new_gsa": [10.0, 12.0, 11.0]}),
    }
    transformed_data = raw_sources["media"].merge(raw_sources["outcomes"], on="date")
    pipeline_steps = [{"step_id": "step_001", "operation": "rename_column", "params": {"old": "a", "new": "b"}}]
    model_spec = ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"}, channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    constraint = SpendConstraint(kind="locked_cell", channel="TV_Brand", month="2024-01", value=100.0)
    scenarios = [{
        "name": "manual-uk", "market": "UK", "spend_plan": {"2024-01": {"TV_Brand": 100.0}},
        "objective": "value", "constraints": [constraint], "notes": "manual",
        "predicted": pd.DataFrame({"month": ["2024-01"], "segment": ["New"], "predicted_gsa": [11.0]}),
    }]
    model_approval = {
        "approved_by": "Jane Analyst", "approved_at": 1700000000.0, "run_label": "uk-v1",
        "notes": "looks fine", "known_limitations": "", "diagnostics_accepted": ["convergence"],
    }
    return dict(
        raw_sources=raw_sources, transformed_data=transformed_data, pipeline_steps=pipeline_steps,
        model_spec=model_spec, prior_config=prior_config, dna_lag_weeks=4, trace=sample_trace,
        scenarios=scenarios, model_approval=model_approval,
    )


def test_export_then_import_reproduces_raw_and_transformed_data(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    assert output_path.exists()

    imported = import_project(output_path)

    for name, df in sample_project["raw_sources"].items():
        pd.testing.assert_frame_equal(imported["raw_sources"][name], df, check_dtype=False)
    pd.testing.assert_frame_equal(
        imported["transformed_data"], sample_project["transformed_data"], check_dtype=False,
    )


def test_export_then_import_reproduces_config(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["pipeline_steps"] == sample_project["pipeline_steps"]
    assert imported["model_spec"] == sample_project["model_spec"]
    assert imported["prior_config"] == sample_project["prior_config"]
    assert imported["dna_lag_weeks"] == sample_project["dna_lag_weeks"]
    assert imported["model_approval"] == sample_project["model_approval"]


def test_export_then_import_reproduces_scenarios_and_constraints(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert len(imported["scenarios"]) == 1
    restored_scenario = imported["scenarios"][0]
    assert restored_scenario["name"] == "manual-uk"
    assert restored_scenario["constraints"] == [
        {"kind": "locked_cell", "channel": "TV_Brand", "month": "2024-01", "months": None,
         "value": 100.0, "max_pct_move": None, "label": ""}
    ]
    pd.testing.assert_frame_equal(
        restored_scenario["predicted"], sample_project["scenarios"][0]["predicted"], check_dtype=False,
    )


def test_export_then_import_reproduces_trace(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    original = sample_project["trace"].posterior["intercept"].values
    restored = imported["trace"].posterior["intercept"].values
    np.testing.assert_allclose(restored, original)


def test_export_then_import_reproduces_market_spec_config(tmp_path, sample_project):
    market_spec_config = MarketSpecConfig()
    market_spec_config.set_profile(MarketProfile(market="UK", currency=MarketCurrency(local_currency="GBP")))
    market_spec_config.set_media_unit_config(
        ChannelMediaUnitConfig(market="UK", channel="TV_Brand", spend_column="TV_Brand", response_unit_column="TV_Brand_GRP")
    )
    sample_project = dict(sample_project)
    sample_project["market_spec_config"] = market_spec_config.to_dict()

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    restored = MarketSpecConfig.from_dict(imported["market_spec_config"])
    assert restored.get_profile("UK").currency.local_currency == "GBP"
    assert restored.get_media_unit_config("UK", "TV_Brand").response_unit_column == "TV_Brand_GRP"


def test_legacy_bundle_without_market_spec_config_imports_with_none(tmp_path, sample_project):
    """A bundle exported before the market-specific redesign has no
    market_spec_config.json - import must not fail, and MarketSpecConfig
    must treat the missing data as an empty (not corrupt) config."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["market_spec_config"] is None
    restored = MarketSpecConfig.from_dict(imported["market_spec_config"])
    assert restored.market_profiles == {}
    assert restored.channel_media_units == {}


def test_export_without_trace_or_approval_omits_them_on_import(tmp_path, sample_project):
    sample_project = dict(sample_project)
    sample_project["trace"] = None
    sample_project["model_approval"] = None
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)

    imported = import_project(output_path)
    assert imported["trace"] is None
    assert imported["model_approval"] is None


def test_reimporting_a_project_bundle_it_exported_is_a_safe_no_op(tmp_path, sample_project):
    """A project bundle this app produced must always pass its own safety check."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    # Should not raise UnsafeZipEntryError - only crafted/hostile archives should.
    import_project(output_path)


def test_export_excel_summary_writes_a_readable_workbook(tmp_path):
    total_df = pd.DataFrame({"channel": ["TV_Brand"], "volume_contribution": [42.5]})
    output_path = export_excel_summary(tmp_path / "summary.xlsx", None, total_df, None)
    assert output_path.exists()
    reread = pd.read_excel(output_path, sheet_name="Total FH Contribution")
    pd.testing.assert_frame_equal(reread, total_df)


# ---------------------------------------------------------------------------
# Model-run identity: export/import round trip, reconstruction without a
# re-fit, and verifying (or rejecting) an imported approval against the
# imported/reconstructed model artefacts.
# ---------------------------------------------------------------------------

def _make_consistent_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


def _make_trace(meta: FHModelMeta, n_fourier: int = 6, chains: int = 2, draws: int = 10, seed: int = 0) -> az.InferenceData:
    """A structurally-valid (but not really fitted) trace with exactly the
    variables/dims extract_posterior_params(trace, meta) needs, for a meta
    with no DNA channels/control columns (so halo_strength/control_coef/
    segment_control_coef aren't required)."""
    rng = np.random.default_rng(seed)
    n_ch, n_seg, n_mkt = len(meta.channels), len(meta.segments), len(meta.markets)
    posterior = {
        "decay_rate": rng.uniform(0.1, 0.9, size=(chains, draws, n_ch)),
        "hill_K": rng.uniform(500, 2000, size=(chains, draws, n_ch)),
        "hill_S": rng.uniform(0.5, 2.0, size=(chains, draws, n_ch)),
        "intercept": rng.normal(size=(chains, draws, n_seg)),
        "trend_coef": rng.normal(size=(chains, draws, n_seg)),
        "promo_coef": rng.uniform(0, 1, size=(chains, draws, n_seg)),
        "alpha": rng.uniform(1, 10, size=(chains, draws, n_seg)),
        "beta": rng.normal(size=(chains, draws, n_seg, n_ch)),
        "market_offset": rng.normal(size=(chains, draws, n_mkt, n_seg)),
        "gamma_fourier": rng.normal(size=(chains, draws, n_fourier, n_seg)),
    }
    coords = {"channel": meta.channels, "segment": meta.segments, "market": meta.markets, "fourier": list(range(n_fourier))}
    dims = {
        "decay_rate": ["channel"], "hill_K": ["channel"], "hill_S": ["channel"],
        "intercept": ["segment"], "trend_coef": ["segment"], "promo_coef": ["segment"], "alpha": ["segment"],
        "beta": ["segment", "channel"], "market_offset": ["market", "segment"], "gamma_fourier": ["fourier", "segment"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


@pytest.fixture
def consistent_meta() -> FHModelMeta:
    return _make_consistent_meta()


@pytest.fixture
def consistent_trace(consistent_meta) -> az.InferenceData:
    return _make_trace(consistent_meta)


@pytest.fixture
def consistent_project(consistent_meta, consistent_trace):
    """A project bundle that is fully internally consistent: the approval's
    fingerprints genuinely match the data/spec/posterior being exported
    alongside it (computed the same way verify_imported_approval will)."""
    transformed_data = pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=8, freq="W"),
        "market": ["UK"] * 8,
        "TV_Brand": [100.0, 120.0, 90.0, 110.0, 130.0, 95.0, 105.0, 115.0],
        "fh_new_gsa": [10, 12, 9, 11, 13, 9, 10, 11],
    })
    model_spec_dict = ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"}, channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4

    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(consistent_trace, consistent_meta)

    model_run_id = "run-consistent-1"
    approval = ModelApproval(
        approved_by="Jane Analyst",
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(model_spec_dict, prior_config, dna_lag_weeks),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )

    return dict(
        raw_sources={}, transformed_data=transformed_data, pipeline_steps=[],
        model_spec=model_spec_dict, prior_config=prior_config, dna_lag_weeks=dna_lag_weeks,
        trace=consistent_trace, scenarios=[], model_approval=approval.to_dict(),
        model_run_id=model_run_id, model_meta=consistent_meta,
    )


def test_export_then_import_preserves_model_run_id_and_meta(tmp_path, consistent_project):
    output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
    imported = import_project(output_path)

    assert imported["model_run_id"] == consistent_project["model_run_id"]
    assert imported["model_meta"] == asdict(consistent_project["model_meta"])
    assert imported["model_approval"] == consistent_project["model_approval"]


def test_reconstruct_model_state_rebuilds_frame_and_posterior_without_a_refit(tmp_path, consistent_project):
    output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
    imported = import_project(output_path)

    reconstructed = reconstruct_model_state(imported)
    assert reconstructed["frame"] is not None
    assert reconstructed["model_meta"] == consistent_project["model_meta"]
    assert reconstructed["posterior_params"] is not None


def test_reconstruct_model_state_handles_missing_inputs_without_raising():
    assert reconstruct_model_state({}) == {"frame": None, "model_meta": None, "posterior_params": None}


class TestVerifyImportedApproval:
    def test_matching_imported_approval_is_verified(self, tmp_path, consistent_project):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is not None
        assert approval.approved_by == "Jane Analyst"
        assert "verified" in message.lower()

    def test_rejected_when_imported_data_differs(self, tmp_path, consistent_project):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        imported["transformed_data"].loc[0, "TV_Brand"] = 999999.0

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "does not match" in message.lower()

    def test_rejected_when_model_spec_differs(self, tmp_path, consistent_project):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        imported["prior_config"]["decay_mu"] = 0.9

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "does not match" in message.lower()

    def test_rejected_when_posterior_artefacts_differ(self, tmp_path, consistent_meta, consistent_project):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        imported["trace"] = _make_trace(consistent_meta, seed=999)  # structurally valid, numerically different

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "does not match" in message.lower()

    def test_no_approval_in_bundle(self, tmp_path, consistent_project):
        consistent_project = dict(consistent_project)
        consistent_project["model_approval"] = None
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "no approval" in message.lower()

    def test_legacy_bundle_without_model_meta_remains_importable_but_unverified(self, tmp_path, sample_project):
        # sample_project has model_approval but no model_run_id/model_meta at all -
        # simulates a bundle from before model-bound approval existed.
        output_path = export_project(tmp_path / "bundle.zip", **sample_project)
        imported = import_project(output_path)
        assert imported["model_meta"] is None

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "predates" in message.lower() or "unverified" in message.lower()

    def test_legacy_approval_within_an_otherwise_new_bundle_is_unverified(self, tmp_path, consistent_project):
        # The approval itself lacks fingerprints even though model_meta/model_run_id
        # are present - must still be treated as unverified, not "close enough".
        legacy_approval = ModelApproval(approved_by="Old Approver")
        consistent_project = dict(consistent_project)
        consistent_project["model_approval"] = legacy_approval.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "predates" in message.lower()
