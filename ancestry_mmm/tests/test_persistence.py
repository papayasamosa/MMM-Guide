import zipfile

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.optimization import SpendConstraint
from ancestry_mmm.core.persistence import (
    UnsafeZipEntryError,
    _is_safe_zip_member,
    _safe_extract_zip,
    export_excel_summary,
    export_project,
    import_project,
)
from ancestry_mmm.core.schema import ModelSpec


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
