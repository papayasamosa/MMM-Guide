import io
import json
import os
import zipfile
from dataclasses import asdict, replace
from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import (
    ApprovalMismatchError,
    ModelApproval,
    fingerprint_model_approval,
)
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactMetadata,
    CurveArtifactStoreError,
    compute_curve_artifact_fingerprints,
    load_curve_artifact_store,
    validate_portable_path_component,
    write_curve_artifact,
)
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig,
    MarketCurrency,
    MarketProfile,
    MarketSpecConfig,
)
from ancestry_mmm.core.optimization import SpendConstraint, evaluate_scenario
from ancestry_mmm.core.outcomes import DNA, FAMILY_HISTORY, OutcomeDefinition
from ancestry_mmm.core.planning import CURRENT_PLANNING_EVALUATION_SEMANTICS
from ancestry_mmm.core.planning.value import CurrencyContext, OutcomeValueMapping
from ancestry_mmm.core.pathways import (
    ResolvedPathwayComponent,
    ResolvedPathwayMasks,
)
from ancestry_mmm.core.scenario_governance import CounterfactualPolicy
from ancestry_mmm.core.persistence import (
    UnsafeZipEntryError,
    _count_loaded_curve_artifacts,
    _is_safe_zip_member,
    _safe_extract_zip,
    audit_project_resumability,
    export_excel_summary,
    export_project,
    import_project,
    reconstruct_model_state,
    replace_curve_artifact_store,
    resolve_imported_causal_graphs,
    resolve_imported_outcome_approvals,
    verify_imported_approval,
)
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame


# ---------------------------------------------------------------------------
# Zip-slip / path-traversal protection
# ---------------------------------------------------------------------------


class TestIsSafeZipMember:
    @pytest.mark.parametrize(
        "name",
        [
            "data/raw_media.parquet",
            "config/model_spec.json",
            "a/b/c.txt",
            "curve_bank/1700000000_abc.json",
            "trailing_slash_dir/",
        ],
    )
    def test_accepts_plain_relative_paths(self, name):
        assert _is_safe_zip_member(name) is True

    @pytest.mark.parametrize(
        "name",
        [
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
        ],
    )
    def test_rejects_absolute_or_traversal_paths(self, name):
        assert _is_safe_zip_member(name) is False


class TestSafeExtractZip:
    def test_extracts_a_well_formed_archive(self, tmp_path):
        zip_path = tmp_path / "good.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(
                "data/raw_media.parquet", b"not really parquet but fine for this test"
            )
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

    def test_rejects_traversal_entry_inside_curve_artifacts_subtree(self, tmp_path):
        # PR 96B: the official curve artifact store subtree (curve_artifacts/)
        # shares _safe_extract_zip with every other bundle subtree - no new
        # path-safety mechanism was added, so this closes the requirement's
        # own "safe path validation" bullet with a named regression test.
        zip_path = tmp_path / "malicious_curve_artifacts.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr(zipfile.ZipInfo("curve_artifacts/../../evil.json"), "pwned")

        with pytest.raises(UnsafeZipEntryError):
            import_project(zip_path)


# ---------------------------------------------------------------------------
# PR 96B: minimal official curve artifact fixtures (mirrors
# test_curve_artifact.py's own fixtures - built directly via write_curve_artifact
# rather than through the full CurveService governance chain, since these
# tests exercise the persistence/bundle layer, not curve generation).
# ---------------------------------------------------------------------------


def _official_artifact_metadata(artifact_id: str = "art-1") -> CurveArtifactMetadata:
    base = CurveArtifactMetadata(
        artifact_id=artifact_id,
        creation_timestamp="2026-08-01T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": "run-1",
            "data_fingerprint": "d1",
            "model_spec_fingerprint": "s1",
            "posterior_fingerprint": "p1",
        },
        approval_snapshot={"approval_id": "apr-1", "status": "approved"},
        threshold_policy_snapshot={"policy_id": "pol-1", "version": "1.0"},
        readiness_snapshot={"readiness_id": "rd-1", "overall_ready": True},
        diagnostics_snapshot={"artefact_id": "diag-1", "schema_version": 2},
        outcome_definition_snapshot={
            "outcome_id": "fh_new_gsa",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-o1",
            "allowed_uses": ["curve_publication"],
        },
        activity_governance_snapshot={"activities": ["tv-paid"]},
        pathway_governance_snapshot={"pathways": ["direct"]},
        reference_context_snapshot={"market": "UK", "mode": "steady_state_reference"},
        support_snapshot={"observed_support_status": "available"},
        cost_currency_snapshot={"currency": "GBP", "fx_as_of_date": "2026-07-01"},
    )
    return replace(base, fingerprints=dict(compute_curve_artifact_fingerprints(base)))


def _official_artifact_draws() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-1",
                "reference_context_id": "ctx-1",
                "market": "UK",
                "product": "fh",
                "segment": "New",
                "outcome_id": "fh_new_gsa",
                "metric_key": "fh_gsa",
                "channel": "TV",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "posterior_draw": 0,
                "incremental_response": 1.0,
            }
        ]
    )


def _official_artifact_summaries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-1",
                "reference_context_id": "ctx-1",
                "market": "UK",
                "product": "fh",
                "segment": "New",
                "outcome_id": "fh_new_gsa",
                "metric_key": "fh_gsa",
                "channel": "TV",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "incremental_response": 1.0,
            }
        ]
    )


def _write_official_artifact(store_dir, artifact_id: str = "art-1"):
    directory = store_dir / artifact_id
    write_curve_artifact(
        directory,
        metadata=_official_artifact_metadata(artifact_id),
        draws=_official_artifact_draws(),
        summaries=_official_artifact_summaries(),
    )
    return directory


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
        "media": pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3),
                "TV_Brand": [100.0, 200.0, 150.0],
            }
        ),
        "outcomes": pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=3),
                "fh_new_gsa": [10.0, 12.0, 11.0],
            }
        ),
    }
    transformed_data = raw_sources["media"].merge(raw_sources["outcomes"], on="date")
    pipeline_steps = [
        {
            "step_id": "step_001",
            "operation": "rename_column",
            "params": {"old": "a", "new": "b"},
        }
    ]
    model_spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    constraint = SpendConstraint(
        kind="locked_cell", channel="TV_Brand", month="2024-01", value=100.0
    )
    scenarios = [
        {
            "name": "manual-uk",
            "market": "UK",
            "spend_plan": {"2024-01": {"TV_Brand": 100.0}},
            "objective": "value",
            "constraints": [constraint],
            "notes": "manual",
            "predicted": pd.DataFrame(
                {"month": ["2024-01"], "segment": ["New"], "predicted_gsa": [11.0]}
            ),
        }
    ]
    model_approval = {
        "approved_by": "Jane Analyst",
        "approved_at": 1700000000.0,
        "run_label": "uk-v1",
        "notes": "looks fine",
        "known_limitations": "",
        "diagnostics_accepted": ["convergence"],
    }
    return dict(
        raw_sources=raw_sources,
        transformed_data=transformed_data,
        pipeline_steps=pipeline_steps,
        model_spec=model_spec,
        prior_config=prior_config,
        dna_lag_weeks=4,
        trace=sample_trace,
        scenarios=scenarios,
        model_approval=model_approval,
    )


def test_export_then_import_reproduces_raw_and_transformed_data(
    tmp_path, sample_project
):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    assert output_path.exists()

    imported = import_project(output_path)

    for name, df in sample_project["raw_sources"].items():
        pd.testing.assert_frame_equal(
            imported["raw_sources"][name], df, check_dtype=False
        )
    pd.testing.assert_frame_equal(
        imported["transformed_data"],
        sample_project["transformed_data"],
        check_dtype=False,
    )


def test_export_then_import_reproduces_config(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["pipeline_steps"] == sample_project["pipeline_steps"]
    assert imported["model_spec"] == sample_project["model_spec"]
    assert imported["prior_config"] == sample_project["prior_config"]
    assert imported["dna_lag_weeks"] == sample_project["dna_lag_weeks"]
    assert imported["model_approval"] == sample_project["model_approval"]


def test_media_input_and_cost_governance_round_trip(tmp_path, sample_project):
    project = dict(sample_project)
    project["media_input_specs"] = [
        {
            "market": "UK",
            "channel": "TV_Brand",
            "column": "tv_impressions",
            "unit": "impressions",
            "unit_scale": 1000.0,
            "source": "delivery feed",
            "schema_version": 1,
        }
    ]
    project["media_cost_mappings"] = {
        "schema_version": 1,
        "mappings": [
            {
                "mapping_id": "uk-tv-base",
                "method": "fixed_cost_per_unit",
                "market": "UK",
                "channel": "TV_Brand",
                "currency": "GBP",
                "cost_context_id": "base",
                "cost_per_media_input": 2.5,
                "source": "finance",
                "approval_status": "approved",
                "approved_by": "owner",
            }
        ],
    }
    project["media_input_support"] = [
        {
            "axis_type": "model_input",
            "market": "UK",
            "channel": "TV_Brand",
            "unit": "impressions",
            "current": 50.0,
            "observed_min": 0.0,
            "observed_max": 100.0,
        }
    ]
    project["monetary_spend_support"] = [
        {
            "axis_type": "monetary",
            "market": "UK",
            "channel": "TV_Brand",
            "local_currency": "GBP",
            "current_local": 125.0,
            "cost_mapping_fingerprint": "cost-fp",
        }
    ]
    project["activity_definitions"] = [
        {
            "activity_id": "tv-paid",
            "channel": "TV_Brand",
            "activity_ownership": "paid",
            "model_role": "intervention",
            "economic_treatment": "paid_media_cost",
            "planning_eligibility": "optimisable",
            "source": "media plan",
        }
    ]
    imported = import_project(
        export_project(tmp_path / "cost-governance.zip", **project)
    )
    assert imported["media_input_specs"] == project["media_input_specs"]
    assert imported["media_cost_mappings"] == project["media_cost_mappings"]
    assert imported["media_input_support"] == project["media_input_support"]
    assert imported["monetary_spend_support"] == project["monetary_spend_support"]
    from ancestry_mmm.core.activities import ActivityDefinition

    assert imported["activity_definitions"] == [
        ActivityDefinition.from_dict(item).to_dict()
        for item in project["activity_definitions"]
    ]


def test_export_then_import_reproduces_scenarios_and_constraints(
    tmp_path, sample_project
):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert len(imported["scenarios"]) == 1
    restored_scenario = imported["scenarios"][0]
    assert restored_scenario["name"] == "manual-uk"
    # G2A.7a.10: a legacy "value" objective with no governed currency on
    # record must not be migrated with an invented placeholder currency
    # (the old "UNSPECIFIED" behaviour this test used to assert) - it stays
    # loadable but unverified instead. schema_version reaches 4 (PR 88B:
    # bumped from 3) because the scenario also predates the
    # governance_dependencies block and planning_semantics_fingerprint.
    assert restored_scenario["schema_version"] == 4
    assert restored_scenario["_migrated_from_schema"] == 1
    assert restored_scenario["objective"] == "value"
    assert restored_scenario["planning_objective"] is None
    assert restored_scenario["_legacy_unverified_reason"] == "missing_value_currency"
    assert restored_scenario["scenario_plan"] == {
        "monetary_decisions_by_period": {"2024-01": {"TV_Brand": 100.0}},
        "activity_quantity_assumptions_by_period": {},
        "activity_units": None,
        "schema_version": 1,
    }
    assert [c.to_dict() for c in restored_scenario["constraints"]] == [
        {
            "kind": "locked_cell",
            "channel": "TV_Brand",
            "month": "2024-01",
            "months": None,
            "value": 100.0,
            "max_pct_move": None,
            "label": "",
        }
    ]
    pd.testing.assert_frame_equal(
        restored_scenario["predicted"],
        sample_project["scenarios"][0]["predicted"],
        check_dtype=False,
    )


def test_legacy_value_scenario_without_currency_stays_loadable_and_blocked(
    tmp_path,
    sample_project,
):
    """G2A.7a.10 (brief section 14.2): a legacy objective="value" scenario
    with no governed currency on record must remain technically loadable
    (including through a second export/import cycle) while staying blocked
    from official planning - "loadable does not mean officially usable"."""
    from ancestry_mmm.core.optimization import (
        resolve_planning_objective,
        scenario_dependency_status,
    )

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    restored_scenario = imported["scenarios"][0]

    # legacy_unverified, not "current" - even though governance_mode was
    # never explicitly set to "official" on this old record.
    assert scenario_dependency_status(restored_scenario) == "legacy_unverified"

    # Official planning must still refuse to invent a currency for it.
    with pytest.raises(ValueError, match="governed currency"):
        resolve_planning_objective(
            objective_kind="expected_value",
            meta=FHModelMeta(
                markets=["UK"],
                outcome_ids=["New"],
                channels=["TV_Brand"],
                dna_channels=[],
                dna_channel_idx=[],
                non_dna_idx=[0],
                dna_outcome_id=None,
                dna_lag_weeks=1,
                unpooled_markets=[],
                control_names=[],
            ),
            operation="planning",
            ltv={"New": 5.0},
        )

    # Re-exporting the migrated scenario and importing it again must not
    # raise or lose the legacy-unverified marker (a second round trip is
    # still loadable, not a fresh crash surface).
    reexport_project = dict(sample_project)
    reexport_project["scenarios"] = imported["scenarios"]
    second_output_path = export_project(tmp_path / "bundle2.zip", **reexport_project)
    reimported = import_project(second_output_path)
    assert reimported["scenarios"][0]["objective"] == "value"
    assert reimported["scenarios"][0]["planning_objective"] is None
    assert scenario_dependency_status(reimported["scenarios"][0]) == "legacy_unverified"


def test_export_then_import_reproduces_trace(tmp_path, sample_project):
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    original = sample_project["trace"].posterior["intercept"].values
    restored = imported["trace"].posterior["intercept"].values
    np.testing.assert_allclose(restored, original)


def test_bundle_manifest_workflow_diagnostics_notes_and_curve_state_round_trip(
    tmp_path, sample_project
):
    project = dict(sample_project)
    project["model_meta"] = FHModelMeta(
        markets=["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=0,
        unpooled_markets=[],
        control_names=[],
    )
    project["workflow_state"] = {
        "checkpoint": "scenarios",
        "current_page": 11,
        "active_scenario": "manual-uk",
    }
    project["diagnostics"] = {
        "scorecard": {"status": "reviewed"},
        "backtest_results": pd.DataFrame({"fold": [1], "smape": [0.12]}),
    }
    project["notes"] = "# Analyst notes\nReady to resume."
    project["calibration_records"] = [{"channel": "TV_Brand", "lift": 0.2}]
    project["model_comparison_candidates"] = [{"run_id": "shared-v1"}]
    curve_dir = tmp_path / "curves"
    curve_dir.mkdir()
    (curve_dir / "curve-1.json").write_text('{"channel": "TV_Brand"}')
    project["curve_bank_source_dir"] = curve_dir

    imported = import_project(export_project(tmp_path / "resume.zip", **project))

    assert imported["manifest"]["schema_version"] >= 3
    assert imported["workflow_state"]["active_scenario"] == "manual-uk"
    assert imported["diagnostics"]["scorecard"]["status"] == "reviewed"
    pd.testing.assert_frame_equal(
        imported["diagnostics"]["backtest_results"],
        project["diagnostics"]["backtest_results"],
    )
    assert imported["notes"] == project["notes"]
    assert imported["calibration_records"] == project["calibration_records"]
    assert (
        imported["model_comparison_candidates"]
        == project["model_comparison_candidates"]
    )
    assert "curve-1.json" in imported["curve_bank_files"]
    assert audit_project_resumability(imported)["resumable"]


# ---------------------------------------------------------------------------
# PR 96B: official curve artifact store project-bundle portability
# ---------------------------------------------------------------------------


def test_bundle_manifest_reports_official_curve_artifacts_presence(
    tmp_path, sample_project
):
    with_store = dict(sample_project)
    artifact_source = tmp_path / "artifact-source"
    _write_official_artifact(artifact_source)
    with_store["curve_artifact_store_source_dir"] = artifact_source
    imported_with = import_project(
        export_project(tmp_path / "with-store.zip", **with_store)
    )
    assert imported_with["manifest"]["contains"]["official_curve_artifacts"] is True

    without_store = dict(sample_project)
    imported_without = import_project(
        export_project(tmp_path / "without-store.zip", **without_store)
    )
    assert imported_without["manifest"]["contains"]["official_curve_artifacts"] is False


def test_export_then_import_official_curve_artifact_store_clean_environment_round_trip(
    tmp_path, sample_project
):
    """Build an official artifact in one temp directory (the "source"
    environment), export it into a bundle, import that bundle into a second,
    unrelated temp directory (the "clean" environment), and confirm the
    artifact reloads with identical fingerprints/metadata - REQ-CURVE-001's
    "project export and import (round-trip)" coverage gap, closed."""
    project = dict(sample_project)
    artifact_source = tmp_path / "source-env" / "artifact-store"
    original_directory = _write_official_artifact(artifact_source, "art-shared")
    project["curve_artifact_store_source_dir"] = artifact_source

    imported = import_project(export_project(tmp_path / "bundle.zip", **project))

    clean_env = tmp_path / "clean-env" / "restored-store"
    for filename, contents in imported["curve_artifact_files"].items():
        target = clean_env / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents)
    for filename, contents in imported["curve_artifact_binary_files"].items():
        target = clean_env / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)

    original_result = load_curve_artifact_store(
        artifact_source, raise_on_malformed=False
    )
    restored_result = load_curve_artifact_store(clean_env, raise_on_malformed=False)
    assert not restored_result.malformed
    assert len(restored_result.loaded) == 1
    original_artifact = original_result.loaded[0]
    restored_artifact = restored_result.loaded[0]
    assert (
        restored_artifact.metadata.artifact_id == original_artifact.metadata.artifact_id
    )
    assert (
        restored_artifact.metadata.fingerprints
        == original_artifact.metadata.fingerprints
    )
    pd.testing.assert_frame_equal(restored_artifact.draws, original_artifact.draws)
    pd.testing.assert_frame_equal(
        restored_artifact.summaries, original_artifact.summaries
    )
    # Sanity: the source directory really was untouched by the restore.
    assert original_directory.exists()


def test_official_curve_artifact_import_audit_reports_malformed_entries(tmp_path):
    """A store with one loaded and one malformed artifact round-trips with
    both reported (never silently dropped) - only the loaded one counts
    toward the official_curves checkpoint."""
    store_dir = tmp_path / "mixed-store"
    _write_official_artifact(store_dir, "art-good")
    _write_official_artifact(store_dir, "art-bad")
    # Tamper the second artifact's metadata envelope after writing it via
    # the real write path, so it fails fingerprint verification on load -
    # a genuinely malformed artifact, not a hand-built invalid payload.
    bad_metadata_path = store_dir / "art-bad" / "curve_artifact_metadata.json"
    envelope = json.loads(bad_metadata_path.read_text(encoding="utf-8"))
    envelope["metadata"]["fingerprints"] = {"chain_fingerprint": "tampered"}
    bad_metadata_path.write_text(json.dumps(envelope), encoding="utf-8")

    text_files = {}
    binary_files = {}
    for artifact_dir in (store_dir / "art-good", store_dir / "art-bad"):
        for f in artifact_dir.rglob("*.json"):
            text_files[str(f.relative_to(store_dir))] = f.read_text()
        for f in artifact_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() != ".json":
                binary_files[str(f.relative_to(store_dir))] = f.read_bytes()

    imported = {
        "curve_artifact_files": text_files,
        "curve_artifact_binary_files": binary_files,
    }
    assert _count_loaded_curve_artifacts(imported) == 1


def _bundle_files_for_store(store_dir) -> dict:
    """Materialise a store directory's artifact files into the
    curve_artifact_files/curve_artifact_binary_files shape an imported
    bundle dict carries them in (mirrors export_project's own encoding)."""
    text_files = {}
    binary_files = {}
    for artifact_dir in sorted(p for p in store_dir.iterdir() if p.is_dir()):
        for f in artifact_dir.rglob("*.json"):
            text_files[str(f.relative_to(store_dir))] = f.read_text()
        for f in artifact_dir.rglob("*"):
            if f.is_file() and f.suffix.lower() != ".json":
                binary_files[str(f.relative_to(store_dir))] = f.read_bytes()
    return {
        "curve_artifact_files": text_files,
        "curve_artifact_binary_files": binary_files,
    }


class TestReplaceCurveArtifactStore:
    """Corrective PR A5 (review-debt finding 11, PR #104): importing a
    bundle must atomically replace the destination's official-artifact
    store, never merge into it."""

    def test_populates_an_empty_destination(self, tmp_path):
        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        destination = tmp_path / "destination"
        replace_curve_artifact_store(imported, destination)

        result = load_curve_artifact_store(destination)
        assert {a.metadata.artifact_id for a in result.loaded} == {"art-new"}

    def test_replaces_rather_than_merges_when_destination_has_prior_artifacts(
        self, tmp_path
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        replace_curve_artifact_store(imported, destination)

        result = load_curve_artifact_store(destination)
        artifact_ids = {a.metadata.artifact_id for a in result.loaded}
        assert artifact_ids == {"art-new"}
        assert "art-old" not in artifact_ids
        assert not (destination / "art-old").exists()

    def test_empty_bundle_clears_a_non_empty_destination(self, tmp_path):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        assert (destination / "art-old").exists()

        # A bundle with genuinely zero official curve artifacts - the key
        # may be entirely absent, not just an empty dict.
        imported: dict = {}
        replace_curve_artifact_store(imported, destination)

        assert not (destination / "art-old").exists()
        result = load_curve_artifact_store(destination)
        assert result.loaded == ()

    def test_empty_bundle_leaves_a_nonexistent_destination_absent(self, tmp_path):
        destination = tmp_path / "destination-never-created"
        replace_curve_artifact_store({}, destination)
        assert not destination.exists()


def _snapshot_store(store_dir: Path) -> dict:
    """Byte-for-byte snapshot of every file under ``store_dir``, keyed by
    relative path - used to assert the old store survives a failed
    transaction untouched."""
    if not store_dir.exists():
        return {}
    return {
        str(f.relative_to(store_dir)): f.read_bytes()
        for f in sorted(store_dir.rglob("*"))
        if f.is_file()
    }


def _no_stray_staging_dirs(store_root: Path) -> bool:
    return not any(
        ".stage-" in p.name or ".backup-" in p.name
        for p in store_root.iterdir()
        if p.is_dir()
    )


class TestReplaceCurveArtifactStoreTransactional:
    """Corrective PR E3.1: ``replace_curve_artifact_store`` stages the
    imported bundle on a sibling directory, verifies it through the
    canonical loader, and only then swaps it in - backing up (and
    restoring) the previous store around the swap - instead of deleting the
    destination before anything is validated or written."""

    def test_stage_write_failure_preserves_the_old_store(self, tmp_path, monkeypatch):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        monkeypatch.setattr(
            Path,
            "write_text",
            lambda self, *a, **k: (_ for _ in ()).throw(
                OSError("simulated stage write failure")
            ),
        )
        with pytest.raises(OSError):
            replace_curve_artifact_store(imported, destination)

        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def test_binary_write_failure_preserves_the_old_store(self, tmp_path, monkeypatch):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)
        assert imported["curve_artifact_binary_files"], (
            "fixture must carry at least one binary file for this test to "
            "exercise the binary write path"
        )

        monkeypatch.setattr(
            Path,
            "write_bytes",
            lambda self, *a, **k: (_ for _ in ()).throw(
                OSError("simulated binary write failure")
            ),
        )
        with pytest.raises(OSError):
            replace_curve_artifact_store(imported, destination)

        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def test_audit_failure_before_promotion_never_touches_the_destination(
        self, tmp_path, monkeypatch
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        def fake_load(*args, **kwargs):
            raise CurveArtifactStoreError("simulated malformed staged store")

        monkeypatch.setattr(
            "ancestry_mmm.core.persistence.load_curve_artifact_store", fake_load
        )
        with pytest.raises(CurveArtifactStoreError):
            replace_curve_artifact_store(imported, destination)

        # The destination was never even renamed to a backup - it is the
        # exact same directory, untouched.
        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def _patch_os_replace(self, monkeypatch, *, fail_when):
        real_replace = os.replace

        def fake_replace(src, dst, *args, **kwargs):
            if fail_when(Path(src), Path(dst)):
                raise OSError("simulated os.replace failure")
            return real_replace(src, dst, *args, **kwargs)

        monkeypatch.setattr(os, "replace", fake_replace)

    def test_backup_rename_failure_leaves_the_original_destination_in_place(
        self, tmp_path, monkeypatch
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        self._patch_os_replace(
            monkeypatch, fail_when=lambda src, dst: ".backup-" in dst.name
        )
        with pytest.raises(OSError):
            replace_curve_artifact_store(imported, destination)

        assert destination.exists()
        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def test_promotion_failure_restores_the_backup(self, tmp_path, monkeypatch):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        self._patch_os_replace(
            monkeypatch, fail_when=lambda src, dst: ".stage-" in src.name
        )
        with pytest.raises(OSError):
            replace_curve_artifact_store(imported, destination)

        assert destination.exists()
        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def test_final_verification_failure_restores_the_backup(
        self, tmp_path, monkeypatch
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        real_load = load_curve_artifact_store
        calls = {"count": 0}

        def flaky_load(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise CurveArtifactStoreError("simulated post-promotion audit failure")
            return real_load(*args, **kwargs)

        monkeypatch.setattr(
            "ancestry_mmm.core.persistence.load_curve_artifact_store", flaky_load
        )
        with pytest.raises(CurveArtifactStoreError):
            replace_curve_artifact_store(imported, destination)

        assert calls["count"] >= 2  # staging audit, then the post-promotion audit
        assert destination.exists()
        assert _snapshot_store(destination) == before
        assert _no_stray_staging_dirs(tmp_path)

    def test_rollback_failure_raises_an_actionable_error_and_keeps_the_backup(
        self, tmp_path, monkeypatch
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")
        before = _snapshot_store(destination)

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        # Trigger a rollback via a failing final verification, and also
        # fail the rollback's own restore-from-backup rename (src name
        # contains ".backup-" only for that specific call).
        real_load = load_curve_artifact_store
        calls = {"count": 0}

        def flaky_load(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] >= 2:
                raise CurveArtifactStoreError("simulated post-promotion audit failure")
            return real_load(*args, **kwargs)

        monkeypatch.setattr(
            "ancestry_mmm.core.persistence.load_curve_artifact_store", flaky_load
        )
        self._patch_os_replace(
            monkeypatch, fail_when=lambda src, dst: ".backup-" in src.name
        )

        with pytest.raises(CurveArtifactStoreError, match="rollback also failed"):
            replace_curve_artifact_store(imported, destination)

        # The previous store was not lost - it survives at the reported
        # backup path (the error message names it), even though it could
        # not be moved back to the original destination automatically.
        store_root = destination.parent
        backups = [
            p for p in store_root.iterdir() if p.is_dir() and ".backup-" in p.name
        ]
        assert len(backups) == 1
        assert _snapshot_store(backups[0]) == before

    def test_successful_replacement_leaves_no_staging_or_backup_directories(
        self, tmp_path
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")

        bundle_store = tmp_path / "bundle-store"
        _write_official_artifact(bundle_store, "art-new")
        imported = _bundle_files_for_store(bundle_store)

        replace_curve_artifact_store(imported, destination)

        assert _no_stray_staging_dirs(tmp_path)
        result = load_curve_artifact_store(destination)
        assert {a.metadata.artifact_id for a in result.loaded} == {"art-new"}

    def test_empty_replacement_is_staged_and_audited_like_any_other(
        self, tmp_path, monkeypatch
    ):
        destination = tmp_path / "destination"
        _write_official_artifact(destination, "art-old")

        real_load = load_curve_artifact_store
        calls = {"count": 0}

        def counting_load(*args, **kwargs):
            calls["count"] += 1
            return real_load(*args, **kwargs)

        monkeypatch.setattr(
            "ancestry_mmm.core.persistence.load_curve_artifact_store", counting_load
        )
        replace_curve_artifact_store({}, destination)

        # The empty bundle still went through the staging + audit + promote
        # + post-promotion-audit sequence - not a delete-only shortcut.
        assert calls["count"] >= 2
        assert _no_stray_staging_dirs(tmp_path)
        result = load_curve_artifact_store(destination)
        assert result.loaded == ()


class TestRejectsUnsafeCurveArtifactPaths:
    """Corrective PR E3.2: every relative path a bundle supplies for
    ``replace_curve_artifact_store`` must resolve to safe, portable path
    components on every operating system before anything is written."""

    @pytest.mark.parametrize(
        "unsafe_rel_path",
        [
            "/absolute/metadata.json",
            "C:/evil/metadata.json",
            "C:\\evil\\metadata.json",
            "../escape/metadata.json",
            "art-1/../../../etc/passwd",
            "..",
            ".",
            "",
            "  ",
            "art-1/CON",
            "art-1/con.json",
            "art-1/PRN.json",
            "art-1/COM1",
            "art-1/LPT1.json",
            "art-1/trailing-dot.",
            "art-1/trailing-space ",
            "art-1/ leading-space",
            "art-1/\x00null-byte",
            "art-1/\x1fcontrol-char",
        ],
    )
    def test_rejects_unsafe_relative_paths(self, tmp_path, unsafe_rel_path):
        destination = tmp_path / "destination"
        imported = {
            "curve_artifact_files": {unsafe_rel_path: "{}"},
            "curve_artifact_binary_files": {},
        }
        with pytest.raises(CurveArtifactStoreError):
            replace_curve_artifact_store(imported, destination)
        # Nothing must have been written outside (or inside) the store.
        assert not destination.exists()
        assert _no_stray_staging_dirs(tmp_path)

    @pytest.mark.parametrize(
        "forbidden_component",
        [
            "bad<name",
            "bad>name",
            "bad:name",
            'bad"name',
            "bad|name",
            "bad?name",
            "bad*name",
        ],
    )
    def test_validate_portable_path_component_rejects_forbidden_characters(
        self, forbidden_component
    ):
        with pytest.raises(CurveArtifactStoreError):
            validate_portable_path_component(forbidden_component)

    def test_validate_portable_path_component_accepts_safe_ascii_and_unicode(self):
        for name in ("art-2026.08.04-v1", "art_1", "café-artefact", "モデル-1"):
            validate_portable_path_component(name)  # must not raise

    def test_case_insensitive_top_level_collision_is_rejected(self, tmp_path):
        destination = tmp_path / "destination"
        imported = {
            "curve_artifact_files": {
                "Art-1/metadata.json": "{}",
                "art-1/metadata.json": "{}",
            },
            "curve_artifact_binary_files": {},
        }
        with pytest.raises(CurveArtifactStoreError):
            replace_curve_artifact_store(imported, destination)
        assert not destination.exists()
        assert _no_stray_staging_dirs(tmp_path)


@pytest.mark.parametrize(
    "checkpoint",
    ["official_curves"],
)
def test_end_to_end_resume_at_official_curves_checkpoint(
    tmp_path, consistent_project, checkpoint
):
    project = dict(consistent_project)
    project["raw_sources"] = {"joined": consistent_project["transformed_data"].copy()}
    project["workflow_state"] = {"checkpoint": checkpoint, "current_page": 9}
    artifact_source = tmp_path / "artifact-source"
    _write_official_artifact(artifact_source, "art-resume")
    project["curve_artifact_store_source_dir"] = artifact_source

    imported = import_project(export_project(tmp_path / f"{checkpoint}.zip", **project))
    audit = audit_project_resumability(imported)
    assert audit["resumable"], audit
    assert audit["checkpoint"] == checkpoint
    assert any(
        Path(key) == Path("art-resume") / "curve_artifact_metadata.json"
        for key in imported["curve_artifact_files"]
    )


def test_legacy_curve_bank_alone_never_satisfies_official_curves_checkpoint(
    tmp_path, consistent_project
):
    """REQ-CURVE-001 / PR 96B: legacy CurveBankEntry parameter snapshots
    (curve_bank_source_dir) must never satisfy the distinct official_curves
    checkpoint, even when explicitly declared."""
    project = dict(consistent_project)
    curve_dir = tmp_path / "curve-source"
    curve_dir.mkdir()
    (curve_dir / "curve.json").write_text('{"channel": "TV_Brand"}')
    project["curve_bank_source_dir"] = curve_dir
    project["workflow_state"] = {"checkpoint": "official_curves"}

    imported = import_project(export_project(tmp_path / "bundle.zip", **project))
    audit = audit_project_resumability(imported)
    assert audit["checkpoint"] == "official_curves"
    assert not audit["resumable"]
    assert "curve_artifact_files" in audit["missing_required"]


def test_malformed_only_official_artifact_store_never_satisfies_checkpoint():
    """A store where every artifact directory fails to load (0 loaded) must
    not satisfy the official_curves checkpoint - format/historical integrity
    is required, not merely files-on-disk."""
    imported = {
        "curve_artifact_files": {
            "art-bad/curve_artifact_metadata.json": "{not valid json",
        },
        "curve_artifact_binary_files": {},
    }
    assert _count_loaded_curve_artifacts(imported) == 0
    audit = audit_project_resumability(
        {
            **imported,
            "raw_sources": {"joined": pd.DataFrame({"x": [1]})},
            "workflow_state": {"checkpoint": "official_curves"},
            "manifest": {
                "workflow_checkpoint": "official_curves",
                "schema_version": 9,
            },
        }
    )
    assert audit["checkpoint"] == "official_curves"
    assert "curve_artifact_files" in audit["missing_required"]


def test_resumability_audit_covers_prefit_and_legacy_bundle_migration(
    tmp_path, sample_project
):
    prefit = dict(sample_project)
    prefit.update(trace=None, scenarios=[], model_approval=None)
    prefit["workflow_state"] = {"checkpoint": "pre_fit"}
    imported = import_project(export_project(tmp_path / "prefit.zip", **prefit))
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["checkpoint"] == "pre_fit"

    legacy = dict(imported)
    legacy["manifest"] = None
    legacy_audit = audit_project_resumability(legacy)
    assert legacy_audit["resumable"]
    assert legacy_audit["warnings"]


def test_resumability_audit_reports_legacy_mask_only_governance():
    audit = audit_project_resumability(
        {
            "raw_sources": {"source": pd.DataFrame({"x": [1]})},
            "model_meta": {
                "pathway_masks": {
                    "primary_channels_by_outcome": {"fh": ["TV"]},
                    "active_channels_by_outcome": {},
                    "exploratory_channels_by_outcome": {},
                }
            },
        }
    )
    assert any("mask-only" in warning for warning in audit["warnings"])
    assert any("planning remain blocked" in warning for warning in audit["warnings"])


# ---------------------------------------------------------------------------
# G2A.7a.1 (REQ-OUT-002 section 12): outcome-approval migration lives in
# core, and official resumability is reported separately from technical
# loadability.
# ---------------------------------------------------------------------------


def test_resolve_imported_outcome_approvals_legacy_bundle_with_persisted_outcomes_creates_legacy_unapproved():
    imported = {
        "model_spec": None,
        "outcome_definitions": [
            {
                "outcome_id": "fh_new_gsa",
                "product": FAMILY_HISTORY,
                "segment": "New",
                "metric": "GSA",
                "source_column": "GSA_New",
            },
            {
                "outcome_id": "fh_new_signup",
                "product": FAMILY_HISTORY,
                "segment": "New",
                "metric": "Sign-up",
                "source_column": "Signup_New",
            },
        ],
        "outcome_approvals": None,
    }
    approvals, warnings = resolve_imported_outcome_approvals(imported)
    assert warnings == []
    assert {a["outcome_id"] for a in approvals} == {"fh_new_gsa", "fh_new_signup"}
    assert all(a["status"] == "legacy_unapproved" for a in approvals)


def test_resolve_imported_outcome_approvals_legacy_bundle_with_derived_outcomes_creates_legacy_unapproved():
    # No outcome_definitions.json at all (predates PR2) - outcomes must be
    # derived live from model_spec.segment_outcomes, same as every other
    # consumer of resolve_outcome_definitions.
    model_spec = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa", "Winback": "fh_winback_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    imported = {
        "model_spec": model_spec,
        "outcome_definitions": None,
        "outcome_approvals": None,
    }
    approvals, warnings = resolve_imported_outcome_approvals(imported)
    assert warnings == []
    # fh_outcomes_from_spec derives outcome_id as f"fh_{segment.lower()}".
    assert {a["outcome_id"] for a in approvals} == {"fh_new", "fh_winback"}
    assert all(a["status"] == "legacy_unapproved" for a in approvals)


def test_resolve_imported_outcome_approvals_no_legacy_migration_when_approvals_file_present():
    imported = {
        "model_spec": None,
        "outcome_definitions": [],
        "outcome_approvals": [
            {
                "approval_id": "apr-1",
                "outcome_id": "fh_new_gsa",
                "definition_fingerprint": "fp1",
                "status": "approved",
                "allowed_uses": ["planning"],
                "approved_by": "Jane",
                "approved_at": "2026-01-01",
            },
        ],
    }
    approvals, warnings = resolve_imported_outcome_approvals(imported)
    assert warnings == []
    assert len(approvals) == 1
    assert approvals[0]["status"] == "approved"


def test_resolve_imported_outcome_approvals_reports_malformed_records_by_index():
    imported = {
        "model_spec": None,
        "outcome_definitions": [],
        "outcome_approvals": [
            {
                "approval_id": "apr-1",
                "outcome_id": "fh_new_gsa",
                "definition_fingerprint": "fp1",
                "status": "not_a_real_status",
            },
        ],
    }
    approvals, warnings = resolve_imported_outcome_approvals(imported)
    assert approvals == []
    assert len(warnings) == 1
    assert "0" in warnings[0] and "apr-1" in warnings[0]


def test_export_then_import_causal_graphs_round_trip(tmp_path, sample_project):
    """REQ-GRAPH-001 S10: config/causal_graphs.json round-trips through
    export_project/import_project like every other project-level governed
    file (counterfactual_policy, currency_context, ...)."""
    from ancestry_mmm.core.causal_graph import CausalGraph, CausalNode

    graph = CausalGraph(
        graph_id="g1",
        graph_version=1,
        nodes=[
            CausalNode(node_id="tv_spend", role="intervention"),
            CausalNode(node_id="fh_new", role="outcome"),
        ],
    )
    project = dict(sample_project)
    project["causal_graphs"] = [graph.to_dict()]

    bundle_path = export_project(tmp_path / "bundle.zip", **project)
    imported = import_project(bundle_path)

    graphs, warnings = resolve_imported_causal_graphs(imported)
    assert warnings == []
    assert len(graphs) == 1
    assert graphs[0]["graph_id"] == "g1"
    restored = CausalGraph.from_dict(graphs[0])
    assert restored.structural_fingerprint() == graph.structural_fingerprint()


def test_import_project_causal_graphs_absent_for_legacy_bundle(
    tmp_path, sample_project
):
    bundle_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(bundle_path)
    assert imported["causal_graphs"] is None
    graphs, warnings = resolve_imported_causal_graphs(imported)
    assert graphs == []
    assert warnings == []


def test_resolve_imported_causal_graphs_quarantines_malformed_records():
    imported = {
        "causal_graphs": [
            {"graph_id": "good", "nodes": [], "edges": []},
            {"graph_id": "future-schema", "schema_version": 999},
            "not-a-mapping",
            {"nodes": []},  # missing required graph_id
        ]
    }
    graphs, warnings = resolve_imported_causal_graphs(imported)
    assert len(graphs) == 1
    assert graphs[0]["graph_id"] == "good"
    assert len(warnings) == 3
    assert any("future-schema" in w for w in warnings)
    assert any("not a mapping" in w for w in warnings)


def test_audit_resumability_officially_resumable_false_without_approvals():
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "trace": object(),
        "model_meta": {},
        "model_approval": {"approved_by": "Jane"},
        "outcome_definitions": None,
        "outcome_approvals": None,
        "manifest": {"workflow_checkpoint": "approved"},
    }
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["officially_resumable"] is False
    assert audit["outcome_governance_warnings"]


def test_audit_resumability_officially_resumable_true_with_active_approval():
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "trace": object(),
        "model_meta": {},
        "model_approval": {"approved_by": "Jane"},
        "outcome_definitions": None,
        "outcome_approvals": [
            {
                "approval_id": "apr-1",
                "outcome_id": "fh_new_gsa",
                "definition_fingerprint": "fp1",
                "status": "approved",
                "allowed_uses": ["planning"],
                "approved_by": "Jane",
                "approved_at": "2026-01-01",
            },
        ],
        "manifest": {"workflow_checkpoint": "approved"},
    }
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["officially_resumable"] is True
    assert audit["outcome_governance_warnings"] == []


def test_audit_resumability_officially_resumable_not_gated_before_fitted_checkpoint():
    # A pre_fit checkpoint has no official-use claim at all - official
    # resumability should not spuriously block it for lack of approvals.
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "manifest": {"workflow_checkpoint": "pre_fit"},
    }
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["officially_resumable"] is True


def test_audit_resumability_fails_closed_when_fit_graph_evidence_is_missing():
    """REQ-GRAPH-001 work package (graph portability): a fit that was bound
    to a causal graph (FHModelMeta.causal_graph_structural_fingerprint) but
    whose bundle carries no matching causal_graphs.json record must not be
    officially resumable - the authoritative structural input for that fit
    cannot be verified."""
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "trace": object(),
        "model_meta": {
            "causal_graph_id": "g1",
            "causal_graph_structural_fingerprint": "deadbeef",
        },
        "manifest": {"workflow_checkpoint": "fitted"},
    }
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["officially_resumable"] is False
    assert any(
        r["artefact_type"] == "causal_graph" and r["artefact_id"] == "g1"
        for r in audit["official_blocking_reasons"]
    )


def test_audit_resumability_true_when_fit_graph_evidence_matches():
    from ancestry_mmm.core.causal_graph import CausalGraph, CausalNode

    graph = CausalGraph(
        graph_id="g1",
        graph_version=2,
        nodes=[
            CausalNode(node_id="tv_spend", role="intervention"),
            CausalNode(node_id="fh_new", role="outcome"),
        ],
    )
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "trace": object(),
        "model_meta": {
            "causal_graph_id": "g1",
            "causal_graph_structural_fingerprint": graph.structural_fingerprint(),
        },
        "causal_graphs": [graph.to_dict()],
        "manifest": {"workflow_checkpoint": "fitted"},
    }
    audit = audit_project_resumability(imported)
    assert audit["resumable"]
    assert audit["officially_resumable"] is True
    assert audit["official_blocking_reasons"] == []


def test_audit_resumability_unaffected_when_no_graph_was_used_at_fit():
    # Every bundle before this capability existed, and every fit today
    # without an approved graph - model_meta has no causal_graph_structural_
    # fingerprint at all (or it's falsy), so this check is inert.
    imported = {
        "raw_sources": {"source": pd.DataFrame({"x": [1]})},
        "transformed_data": pd.DataFrame({"x": [1]}),
        "model_spec": ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict(),
        "trace": object(),
        "model_meta": {"causal_graph_structural_fingerprint": ""},
        "manifest": {"workflow_checkpoint": "fitted"},
    }
    audit = audit_project_resumability(imported)
    assert audit["officially_resumable"] is True
    assert audit["official_blocking_reasons"] == []


def test_export_then_import_reproduces_market_spec_config(tmp_path, sample_project):
    market_spec_config = MarketSpecConfig()
    market_spec_config.set_profile(
        MarketProfile(market="UK", currency=MarketCurrency(local_currency="GBP"))
    )
    market_spec_config.set_media_unit_config(
        ChannelMediaUnitConfig(
            market="UK",
            channel="TV_Brand",
            spend_column="TV_Brand",
            response_unit_column="TV_Brand_GRP",
        )
    )
    sample_project = dict(sample_project)
    sample_project["market_spec_config"] = market_spec_config.to_dict()

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    restored = MarketSpecConfig.from_dict(imported["market_spec_config"])
    assert restored.get_profile("UK").currency.local_currency == "GBP"
    assert (
        restored.get_media_unit_config("UK", "TV_Brand").response_unit_column
        == "TV_Brand_GRP"
    )


def test_legacy_bundle_without_market_spec_config_imports_with_none(
    tmp_path, sample_project
):
    """A bundle exported before the market-specific redesign has no
    market_spec_config.json - import must not fail, and MarketSpecConfig
    must treat the missing data as an empty (not corrupt) config."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["market_spec_config"] is None
    restored = MarketSpecConfig.from_dict(imported["market_spec_config"])
    assert restored.market_profiles == {}
    assert restored.channel_media_units == {}


def test_export_then_import_reproduces_model_type(tmp_path, sample_project):
    # Regression test: export_project's caller (pages/09_Project_Export.py)
    # previously never passed model_type through at all, so every exported
    # Model C bundle silently re-imported as Model A. Covered here at the
    # persistence layer directly (the round trip itself has always worked
    # once the caller passes it - the bug was the caller omitting it).
    sample_project = dict(sample_project)
    sample_project["model_type"] = "market_specific"
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    assert imported["model_type"] == "market_specific"


def test_legacy_bundle_without_model_type_imports_as_shared(tmp_path, sample_project):
    """A bundle exported before Model C existed has no model_type.json -
    "shared" (Model A) is the correct default, not an error."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    assert imported["model_type"] == "shared"


def test_export_then_import_reproduces_outcome_definitions(tmp_path, sample_project):
    outcome_definitions = [
        OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            source_column="fh_new_gsa",
            value_weight=180.0,
        ).to_dict(),
        OutcomeDefinition(
            outcome_id="dna_new_kit",
            product=DNA,
            segment="New Customer",
            metric="Kit sale",
            source_column="DNA_Kit_New",
        ).to_dict(),
    ]
    sample_project = dict(sample_project)
    sample_project["outcome_definitions"] = outcome_definitions

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["outcome_definitions"] == outcome_definitions


def test_legacy_bundle_without_outcome_definitions_imports_with_none(
    tmp_path, sample_project
):
    """A bundle exported before the outcome-schema work (PR2) has no
    outcome_definitions.json - import must not fail, and
    core.outcomes.resolve_outcome_definitions(None, ...) must derive an
    equivalent FH-only set rather than treating this as an error."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    assert imported["outcome_definitions"] is None


def test_export_then_import_reproduces_funnel_links(tmp_path, sample_project):
    from ancestry_mmm.core.funnel import FunnelLink

    funnel_links = [
        FunnelLink(
            upstream_outcome_id="fh_new_signup", downstream_outcome_id="fh_new_gsa"
        ).to_dict()
    ]
    sample_project = dict(sample_project)
    sample_project["funnel_links"] = funnel_links

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["funnel_links"] == funnel_links


def test_legacy_bundle_without_funnel_links_imports_with_none(tmp_path, sample_project):
    """A bundle exported before PR E.2 has no funnel_links.json - import
    must not fail, and None must mean "no funnel diagnostics configured",
    not an error."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    assert imported["funnel_links"] is None


def test_export_then_import_reproduces_media_outcome_pathways(tmp_path, sample_project):
    from ancestry_mmm.core.pathways import MediaOutcomePathway

    pathways = [
        MediaOutcomePathway(
            channel="DNA_Media", source_product="DNA", target_outcome_id="dna_new_kit"
        ).to_dict(),
    ]
    sample_project = dict(sample_project)
    sample_project["media_outcome_pathways"] = pathways

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    assert imported["media_outcome_pathways"] == pathways


def test_export_then_import_preserves_migration_review_audit(tmp_path, sample_project):
    audit = {
        "migration_review_status": "reviewed_refit_required",
        "migration_reviewed_by": "Reviewer",
        "migration_reviewed_at": "2026-07-23T12:00:00+00:00",
        "migration_review_note": "Direct effect replaced by delayed halo.",
        "migrated_from_model_run_id": "old-run",
        "migration_change_summary": {
            "component_type_changes": [
                {
                    "channel": "DNA",
                    "target_outcome_id": "fh_new",
                    "before_component_type": "direct",
                    "after_component_type": "cross_product",
                }
            ],
            "excluded": [],
        },
        "model_invalidated": True,
        "replacement_model_run_id": None,
    }
    project = dict(sample_project)
    project["migration_review"] = audit
    imported = import_project(
        export_project(tmp_path / "migration-review.zip", **project)
    )
    assert imported["migration_review"] == audit


def test_public_bundle_round_trip_preserves_canonical_curve_artifacts(
    tmp_path, sample_project
):
    from ancestry_mmm.core.canonical_curves import export_canonical_curve_bank

    curve_dir = tmp_path / "canonical-curves"
    draws = pd.DataFrame(
        {
            "model_run_id": ["run"],
            "reference_context_id": ["recent"],
            "posterior_draw": ["0:0"],
            "incremental_response": [12.0],
        }
    )
    summaries = pd.DataFrame(
        {
            "model_run_id": ["run"],
            "reference_context_id": ["recent"],
            "posterior_mean": [12.0],
        }
    )
    export_canonical_curve_bank(draws, summaries, curve_dir)
    project = dict(sample_project)
    project["curve_bank_source_dir"] = curve_dir
    imported = import_project(
        export_project(tmp_path / "canonical-bundle.zip", **project)
    )
    assert {
        "canonical_curve_draws.parquet",
        "canonical_curve_summaries.parquet",
    } <= set(imported["curve_bank_binary_files"])
    assert "canonical_curve_schema.json" in imported["curve_bank_files"]
    restored_draws = pd.read_parquet(
        io.BytesIO(imported["curve_bank_binary_files"]["canonical_curve_draws.parquet"])
    )
    pd.testing.assert_frame_equal(restored_draws, draws)


def test_post_migration_refit_approval_curves_scenario_restore_public_api(
    tmp_path, consistent_project
):
    """Final half of the UI migration journey: refit -> approve -> export ->
    restore, including the migration audit and corrected curve artifacts."""
    from ancestry_mmm.core.canonical_curves import export_canonical_curve_bank

    curve_dir = tmp_path / "reviewed-canonical-curves"
    export_canonical_curve_bank(
        pd.DataFrame(
            {
                "model_run_id": [consistent_project["model_run_id"]],
                "reference_context_id": ["recent"],
                "incremental_response": [9.0],
            }
        ),
        pd.DataFrame(
            {
                "model_run_id": [consistent_project["model_run_id"]],
                "reference_context_id": ["recent"],
                "posterior_mean": [9.0],
            }
        ),
        curve_dir,
    )
    project = dict(consistent_project)
    project.update(
        raw_sources={"joined": consistent_project["transformed_data"].copy()},
        migration_review={
            "migration_review_status": "refit_completed",
            "migration_reviewed_by": "Migration Reviewer",
            "migration_reviewed_at": "2026-07-23T12:00:00+00:00",
            "migration_review_note": "Reclassified and refitted.",
            "migrated_from_model_run_id": "legacy-run",
            "migration_change_summary": {
                "component_type_changes": [
                    {
                        "channel": "TV_Brand",
                        "target_outcome_id": "New",
                        "before_component_type": "direct",
                        "after_component_type": "cross_product",
                    }
                ],
                "excluded": [],
            },
            "model_invalidated": True,
            "replacement_model_run_id": consistent_project["model_run_id"],
        },
        curve_bank_source_dir=curve_dir,
        scenarios=[
            {
                "name": "reviewed-plan",
                "predicted": pd.DataFrame(
                    {"month": ["2026-07"], "predicted_outcome": [9.0]}
                ),
            }
        ],
        workflow_state={"checkpoint": "scenarios", "current_page": 9},
    )
    imported = import_project(
        export_project(tmp_path / "reviewed-complete.zip", **project)
    )
    reconstructed = reconstruct_model_state(imported)
    approval, message = verify_imported_approval(imported, reconstructed)
    assert approval is not None, message
    assert imported["migration_review"]["migration_review_status"] == (
        "refit_completed"
    )
    assert (
        imported["migration_review"]["replacement_model_run_id"]
        == (imported["model_run_id"])
    )
    assert imported["curve_bank_binary_files"]
    assert imported["scenarios"][0]["name"] == "reviewed-plan"
    assert audit_project_resumability(imported)["resumable"]


def test_legacy_bundle_without_media_outcome_pathways_imports_with_none(
    tmp_path, sample_project
):
    """A bundle exported before PR F has no media_outcome_pathways.json -
    import must not fail, and None must mean "no pathway catalogue
    configured", not an error."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)
    assert imported["media_outcome_pathways"] is None


def test_promotion_event_pipeline_steps_reproduce_derived_columns_on_import(
    tmp_path, sample_project
):
    """PR E.2 #11 - "re-importing a project must reproduce the same derived
    columns from raw data. Do not rely only on the already-mutated
    transformed parquet." Mirrors what pages/09_Project_Export.py's import
    handler does: replay any promotion_event pipeline steps against the
    imported transformed_data, dropping whatever derived column happens to
    already be sitting there first. A bundle whose parquet has a stale/
    hand-edited value for that column must still come back correct."""
    from ancestry_mmm.core.promotions import (
        PROMOTION_EVENT_OP,
        PromotionEvent,
        promotion_events_to_transform_steps,
    )
    from ancestry_mmm.data.pipeline import apply_pipeline, pipeline_from_json

    event = PromotionEvent(
        event_name="Christmas Sale",
        start_date="2024-01-01",
        end_date="2024-01-03",
        segment="New",
        intensity=1.0,
    )
    promo_steps = [
        s.to_dict()
        for s in promotion_events_to_transform_steps([event], date_col="date")
    ]

    sample_project = dict(sample_project)
    sample_project["pipeline_steps"] = promo_steps
    # Simulate a stale/corrupted value already sitting in the exported
    # parquet for the derived column - e.g. from an older, buggy save.
    transformed = sample_project["transformed_data"].copy()
    transformed["_promo_event_New"] = 999.0
    sample_project["transformed_data"] = transformed

    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    imported = import_project(output_path)

    promo_steps_typed = [
        s
        for s in pipeline_from_json(imported["pipeline_steps"])
        if s.op == PROMOTION_EVENT_OP
    ]
    assert len(promo_steps_typed) == 1

    regenerated = imported["transformed_data"].drop(columns=["_promo_event_New"])
    regenerated = apply_pipeline(regenerated, promo_steps_typed)

    dates = pd.to_datetime(regenerated["date"])
    in_window = (dates >= pd.Timestamp("2024-01-01")) & (
        dates <= pd.Timestamp("2024-01-03")
    )
    assert (regenerated.loc[in_window, "_promo_event_New"] == 1.0).all()
    assert (regenerated.loc[~in_window, "_promo_event_New"] == 0.0).all()
    assert not (regenerated["_promo_event_New"] == 999.0).any()


def test_export_without_trace_or_approval_omits_them_on_import(
    tmp_path, sample_project
):
    sample_project = dict(sample_project)
    sample_project["trace"] = None
    sample_project["model_approval"] = None
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)

    imported = import_project(output_path)
    assert imported["trace"] is None
    assert imported["model_approval"] is None


def test_reimporting_a_project_bundle_it_exported_is_a_safe_no_op(
    tmp_path, sample_project
):
    """A project bundle this app produced must always pass its own safety check."""
    output_path = export_project(tmp_path / "bundle.zip", **sample_project)
    # Should not raise UnsafeZipEntryError - only crafted/hostile archives should.
    import_project(output_path)


def test_export_excel_summary_writes_a_readable_workbook(tmp_path):
    total_df = pd.DataFrame({"channel": ["TV_Brand"], "volume_contribution": [42.5]})
    output_path = export_excel_summary(
        tmp_path / "summary.xlsx", {"Total FH Contribution": total_df}
    )
    assert output_path.exists()
    reread = pd.read_excel(output_path, sheet_name="Total FH Contribution")
    pd.testing.assert_frame_equal(reread, total_df)


def test_export_excel_summary_skips_none_and_empty_sheets(tmp_path):
    total_df = pd.DataFrame({"channel": ["TV_Brand"], "volume_contribution": [42.5]})
    output_path = export_excel_summary(
        tmp_path / "summary.xlsx",
        {
            "Total FH Contribution": total_df,
            "Empty": pd.DataFrame(),
            "Missing": None,
        },
    )
    with open(output_path, "rb") as f:
        with pd.ExcelFile(io.BytesIO(f.read())) as workbook:
            workbook_sheets = workbook.sheet_names
    assert workbook_sheets == ["Total FH Contribution"]


def test_export_excel_summary_writes_every_non_empty_sheet(tmp_path):
    sheets = {
        "Curve Bank": pd.DataFrame({"channel": ["TV"], "beta": [0.1]}),
        "Evidence Tiers": pd.DataFrame(
            {"market": ["UK"], "curve_status": ["Locally estimated"]}
        ),
        "CPA": pd.DataFrame({"market": ["UK"], "channel": ["TV"], "avg_cpa": [12.5]}),
    }
    output_path = export_excel_summary(tmp_path / "summary.xlsx", sheets)
    # Read into memory rather than opening ExcelFile directly on the path:
    # openpyxl's own internal archive handle for a path-based read isn't
    # released deterministically by ExcelFile.close() (cyclic references
    # mean it waits for the next GC cycle, which can happen during a later,
    # unrelated test and get misattributed by pytest-playwright's
    # unraisable-exception hook). A BytesIO source has no OS file handle to
    # leak in the first place.
    with open(output_path, "rb") as f:
        with pd.ExcelFile(io.BytesIO(f.read())) as workbook:
            workbook_sheets = workbook.sheet_names
    assert set(workbook_sheets) == set(sheets.keys())


# ---------------------------------------------------------------------------
# Model-run identity: export/import round trip, reconstruction without a
# re-fit, and verifying (or rejecting) an imported approval against the
# imported/reconstructed model artefacts.
# ---------------------------------------------------------------------------


def _make_consistent_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


def _make_trace(
    meta: FHModelMeta,
    n_fourier: int = 6,
    chains: int = 2,
    draws: int = 10,
    seed: int = 0,
) -> az.InferenceData:
    """A structurally-valid (but not really fitted) trace with exactly the
    variables/dims extract_posterior_params(trace, meta) needs, for a meta
    with no DNA channels/control columns (so halo_strength/control_coef/
    segment_control_coef aren't required)."""
    rng = np.random.default_rng(seed)
    n_ch, n_seg, n_mkt = len(meta.channels), len(meta.outcome_ids), len(meta.markets)
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
    coords = {
        "channel": meta.channels,
        "outcome": meta.outcome_ids,
        "market": meta.markets,
        "fourier": list(range(n_fourier)),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "promo_coef": ["outcome"],
        "alpha": ["outcome"],
        "beta": ["outcome", "channel"],
        "market_offset": ["market", "outcome"],
        "gamma_fourier": ["fourier", "outcome"],
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
    transformed_data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=8, freq="W"),
            "market": ["UK"] * 8,
            "TV_Brand": [100.0, 120.0, 90.0, 110.0, 130.0, 95.0, 105.0, 115.0],
            "fh_new_gsa": [10, 12, 9, 11, 13, 9, 10, 11],
        }
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
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
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict,
            prior_config,
            dna_lag_weeks,
            direct_dna_outcome_ids=consistent_meta.direct_dna_outcome_ids,
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )

    return dict(
        raw_sources={},
        transformed_data=transformed_data,
        pipeline_steps=[],
        model_spec=model_spec_dict,
        prior_config=prior_config,
        dna_lag_weeks=dna_lag_weeks,
        trace=consistent_trace,
        scenarios=[],
        model_approval=approval.to_dict(),
        model_run_id=model_run_id,
        model_meta=consistent_meta,
    )


def test_export_then_import_preserves_model_run_id_and_meta(
    tmp_path, consistent_project
):
    output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
    imported = import_project(output_path)

    assert imported["model_run_id"] == consistent_project["model_run_id"]
    assert imported["model_meta"] == asdict(consistent_project["model_meta"])
    assert imported["model_approval"] == consistent_project["model_approval"]


def test_reconstruct_model_state_rebuilds_frame_and_posterior_without_a_refit(
    tmp_path, consistent_project
):
    output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
    imported = import_project(output_path)

    reconstructed = reconstruct_model_state(imported)
    assert reconstructed["frame"] is not None
    assert reconstructed["model_meta"] == consistent_project["model_meta"]
    assert reconstructed["posterior_params"] is not None


def test_reordered_component_bundle_restores_identical_id_keyed_semantics(
    tmp_path, consistent_project
):
    components = [
        ResolvedPathwayComponent(
            outcome_id="New",
            channel="TV_Brand",
            component_type="direct",
            role="primary_direct",
            included_in_fit=True,
        ),
        ResolvedPathwayComponent(
            outcome_id="New",
            channel="TV_Brand",
            component_type="cross_product",
            role="active_cross_product",
            lag_weeks=3,
            prior_scale=0.2,
            include_in_planning=False,
            included_in_fit=True,
        ),
        ResolvedPathwayComponent(
            outcome_id="New",
            channel="TV_Brand",
            component_type="mediated",
            role="active_cross_product",
            lag_weeks=1,
            include_in_planning=False,
            included_in_fit=False,
        ),
    ]
    restored_masks = []
    for index, ordered_components in enumerate(
        (components, list(reversed(components)))
    ):
        project = dict(consistent_project)
        project["model_meta"] = replace(
            consistent_project["model_meta"],
            pathway_masks=ResolvedPathwayMasks(components=ordered_components),
        )
        imported = import_project(
            export_project(tmp_path / f"component-order-{index}.zip", **project)
        )
        restored = reconstruct_model_state(imported)
        assert restored["posterior_params"] is not None
        restored_masks.append(restored["model_meta"].pathway_masks)

    for masks in restored_masks:
        assert masks.lag_for_component("New", "TV_Brand") == 3
        assert masks.prior_for_component("New", "TV_Brand", default=1.0) == 0.2
        assert masks.active_cells(["New"], ["TV_Brand"]) == [(0, 0)]
    assert (
        restored_masks[0].primary_channels_by_outcome
        == restored_masks[1].primary_channels_by_outcome
    )
    assert restored_masks[0].lag_weeks_by_cell == restored_masks[1].lag_weeks_by_cell


@pytest.mark.parametrize(
    "checkpoint",
    [
        "uploaded",
        "transformed",
        "configured",
        "pre_fit",
        "fitted",
        "approved",
        "curves",
        "scenarios",
    ],
)
def test_end_to_end_resume_at_each_checkpoint(tmp_path, consistent_project, checkpoint):
    project = dict(consistent_project)
    project["raw_sources"] = {"joined": consistent_project["transformed_data"].copy()}
    project["workflow_state"] = {"checkpoint": checkpoint, "current_page": 9}
    project["media_outcome_pathways"] = [
        {
            "channel": "TV_Brand",
            "source_product": "Family History",
            "target_outcome_id": "New",
            "component_type": "direct",
            "role": "primary_direct",
            "include_in_headline": True,
            "headline_approval_status": "approved",
            "headline_approval_note": "Reviewed for the resume test.",
            "approved_by": "Jane Analyst",
            "approved_at": "2026-07-23T10:00:00Z",
        }
    ]
    project["net_billthrough_metadata"] = {
        "data_as_of_date": "2026-07-23",
        "model_start_week": "2024-01-07",
        "model_end_week": "2024-02-25",
        "latest_complete_net_billthrough_week": "2024-02-25",
        "maturity_rule_description": "Upstream authoritative finalisation.",
        "source_owner": "Finance Analytics",
    }
    if checkpoint in {"uploaded", "transformed", "configured", "pre_fit"}:
        project["trace"] = None
        project["model_meta"] = None
        project["model_approval"] = None
        project["model_run_id"] = None
    if checkpoint == "uploaded":
        project["transformed_data"] = None
        project["model_spec"] = None
        project["media_outcome_pathways"] = None
        project["net_billthrough_metadata"] = None
    elif checkpoint == "transformed":
        project["model_spec"] = None
        project["media_outcome_pathways"] = None
        project["net_billthrough_metadata"] = None
    if checkpoint == "fitted":
        project["model_approval"] = None
    if checkpoint == "curves":
        curve_dir = tmp_path / "curve-source"
        curve_dir.mkdir()
        (curve_dir / "curve.json").write_text('{"channel": "TV_Brand"}')
        project["curve_bank_source_dir"] = curve_dir
    if checkpoint == "scenarios":
        project["scenarios"] = [
            {
                "name": "resume-plan",
                "predicted": pd.DataFrame(
                    {"month": ["2026-07"], "predicted_outcome": [42.0]}
                ),
            }
        ]

    imported = import_project(export_project(tmp_path / f"{checkpoint}.zip", **project))
    audit = audit_project_resumability(imported)
    assert audit["resumable"], audit
    assert audit["checkpoint"] == checkpoint
    if project["transformed_data"] is not None:
        pd.testing.assert_frame_equal(
            imported["transformed_data"], project["transformed_data"]
        )
    else:
        assert imported["transformed_data"] is None
    assert imported["model_spec"] == project["model_spec"]
    assert imported["media_outcome_pathways"] == project["media_outcome_pathways"]
    assert imported["net_billthrough_metadata"] == project["net_billthrough_metadata"]
    assert imported["workflow_state"] == project["workflow_state"]

    reconstructed = reconstruct_model_state(imported)
    if checkpoint in {"uploaded", "transformed"}:
        assert reconstructed["frame"] is None
        assert reconstructed["posterior_params"] is None
        return
    assert reconstructed["frame"] is not None
    if checkpoint in {"configured", "pre_fit"}:
        assert reconstructed["posterior_params"] is None
        return

    assert reconstructed["posterior_params"] is not None
    expected_params = extract_posterior_params(project["trace"], project["model_meta"])
    assert fingerprint_posterior(reconstructed["posterior_params"]) == (
        fingerprint_posterior(expected_params)
    )
    if checkpoint not in {"fitted", "pre_fit"}:
        verified, message = verify_imported_approval(imported, reconstructed)
        assert verified is not None, message
    if checkpoint == "curves":
        assert imported["curve_bank_files"] == {"curve.json": '{"channel": "TV_Brand"}'}
    if checkpoint == "scenarios":
        assert imported["scenarios"][0]["name"] == "resume-plan"
        pd.testing.assert_frame_equal(
            imported["scenarios"][0]["predicted"],
            project["scenarios"][0]["predicted"],
        )


def test_reconstruct_model_state_handles_missing_inputs_without_raising():
    assert reconstruct_model_state({}) == {
        "frame": None,
        "model_meta": None,
        "posterior_params": None,
    }


class TestReconstructModelStateWithDnaKitOutcomes:
    """The instruction document's audit-confirmed persistence defect:
    reconstruct_model_state used to rebuild the frame from transformed_data
    + model_spec alone, silently dropping any DNA-kit segments (dna_kit_outcomes
    was never passed to prepare_fh_modeling_frame on reimport) - so a
    reimported FH-plus-DNA project's frame came back FH-only, disagreeing
    with model_meta.segments from the very same bundle
    (reimport_frame_matches_meta_segments: False)."""

    @pytest.fixture
    def dna_kit_project(self):
        transformed_data = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=8, freq="W"),
                "market": ["UK"] * 8,
                "TV_Brand": [100.0, 120.0, 90.0, 110.0, 130.0, 95.0, 105.0, 115.0],
                "DNA_Ad": [40.0, 45.0, 35.0, 42.0, 48.0, 36.0, 41.0, 44.0],
                "fh_new_gsa": [10, 12, 9, 11, 13, 9, 10, 11],
                "dna_kit_sales": [3, 4, 2, 3, 5, 2, 3, 4],
            }
        )
        model_spec_dict = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"],
        ).to_dict()
        outcome_definitions = [
            OutcomeDefinition(
                outcome_id="fh_new",
                product=FAMILY_HISTORY,
                segment="New",
                metric="gsa",
                source_column="fh_new_gsa",
            ).to_dict(),
            OutcomeDefinition(
                outcome_id="dna_new_customer",
                product=DNA,
                segment="New Customer",
                metric="kits",
                source_column="dna_kit_sales",
            ).to_dict(),
        ]
        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["fh_new", "dna_new_customer"],
            channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"],
            dna_channel_idx=[1],
            non_dna_idx=[0],
            dna_outcome_id="fh_new",
            dna_lag_weeks=4,
            unpooled_markets=[],
            control_names=[],
            direct_dna_outcome_ids=["fh_new", "dna_new_customer"],
        )
        return dict(
            raw_sources={},
            transformed_data=transformed_data,
            pipeline_steps=[],
            model_spec=model_spec_dict,
            prior_config={},
            dna_lag_weeks=4,
            trace=None,
            scenarios=[],
            model_meta=meta,
            outcome_definitions=outcome_definitions,
        )

    def test_reconstructed_frame_segments_match_model_meta_segments(
        self, tmp_path, dna_kit_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **dna_kit_project)
        imported = import_project(output_path)

        reconstructed = reconstruct_model_state(imported)
        assert reconstructed["frame"] is not None
        assert set(reconstructed["frame"]["outcome_ids"]) == set(
            reconstructed["model_meta"].outcome_ids
        )
        assert "dna_new_customer" in reconstructed["frame"]["outcome_ids"]

    def test_a_legacy_bundle_with_no_outcome_definitions_still_reconstructs_fh_only(
        self, tmp_path, dna_kit_project
    ):
        # No outcome_definitions.json in the bundle (pre-PR2 export) - must
        # fall back to an FH-only frame derived from model_spec alone, not
        # raise or silently invent a DNA-kit segment that was never saved.
        legacy_project = dict(dna_kit_project)
        legacy_project["outcome_definitions"] = None
        output_path = export_project(tmp_path / "bundle.zip", **legacy_project)
        imported = import_project(output_path)

        reconstructed = reconstruct_model_state(imported)
        assert reconstructed["frame"] is not None
        assert "dna_new_customer" not in reconstructed["frame"]["outcome_ids"]
        assert reconstructed["frame"]["outcome_ids"] == ["fh_new"]


class TestOutcomeCatalogueExportImportRoundTrip:
    """PR E.1 test case: 'export/import round trip preserves exact outcome
    catalogue' - every field (including the new value_currency/role) must
    survive a bundle round trip bit-for-bit, not just the fields that
    existed before this PR."""

    @pytest.fixture
    def full_catalogue_project(self):
        transformed_data = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=8, freq="W"),
                "market": ["UK"] * 8,
                "TV_Brand": [100.0] * 8,
                "fh_new_gsa": [10] * 8,
                "fh_new_signup": [20] * 8,
                "dna_new_kit": [3] * 8,
            }
        )
        model_spec_dict = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
            fh_dna_cross_sell_outcome_id="fh_new_gsa",
        ).to_dict()
        outcome_definitions = [
            OutcomeDefinition(
                outcome_id="fh_new_gsa",
                product=FAMILY_HISTORY,
                segment="New",
                metric="GSA",
                source_column="fh_new_gsa",
                value_weight=100.0,
                value_currency="USD",
                role="primary",
                included_in_fit=True,
            ).to_dict(),
            OutcomeDefinition(
                outcome_id="fh_new_signup",
                product=FAMILY_HISTORY,
                segment="New",
                metric="Sign-up",
                source_column="fh_new_signup",
                value_weight=20.0,
                value_currency="USD",
                role="funnel_intermediate",
                included_in_fit=True,
            ).to_dict(),
            OutcomeDefinition(
                outcome_id="dna_new_kit",
                product=DNA,
                segment="New Customer",
                metric="Kit sale",
                source_column="dna_new_kit",
                value_weight=80.0,
                value_currency="GBP",
                role="secondary",
                included_in_fit=False,
                exclusion_reason="held back this run",
            ).to_dict(),
        ]
        return dict(
            raw_sources={},
            transformed_data=transformed_data,
            pipeline_steps=[],
            model_spec=model_spec_dict,
            prior_config={},
            dna_lag_weeks=4,
            trace=None,
            scenarios=[],
            outcome_definitions=outcome_definitions,
        )

    def test_every_outcome_field_survives_the_round_trip_exactly(
        self, tmp_path, full_catalogue_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **full_catalogue_project)
        imported = import_project(output_path)
        assert (
            imported["outcome_definitions"]
            == full_catalogue_project["outcome_definitions"]
        )

    def test_fh_dna_cross_sell_outcome_id_survives_the_round_trip(
        self, tmp_path, full_catalogue_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **full_catalogue_project)
        imported = import_project(output_path)
        assert imported["model_spec"]["fh_dna_cross_sell_outcome_id"] == "fh_new_gsa"

    def test_reconstructed_outcome_definitions_round_trip_through_OutcomeDefinition(
        self, tmp_path, full_catalogue_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **full_catalogue_project)
        imported = import_project(output_path)
        restored = [
            OutcomeDefinition.from_dict(d) for d in imported["outcome_definitions"]
        ]
        original = [
            OutcomeDefinition.from_dict(d)
            for d in full_catalogue_project["outcome_definitions"]
        ]
        assert restored == original
        signup = next(o for o in restored if o.outcome_id == "fh_new_signup")
        assert signup.metric == "Sign-up" and signup.role == "funnel_intermediate"
        excluded = next(o for o in restored if o.outcome_id == "dna_new_kit")
        assert (
            excluded.included_in_fit is False
            and excluded.exclusion_reason == "held back this run"
        )


class TestLegacyBundleMigratesSafely:
    """PR E.1 test case: 'legacy bundles migrate safely' - a bundle from
    before this PR (no fh_dna_cross_sell_outcome_id in model_spec, no
    outcome_catalogue_at_fit on model_meta) must still reconstruct without
    raising, with sensible legacy-fallback behaviour rather than an error."""

    def test_model_spec_without_fh_dna_cross_sell_outcome_id_defaults_to_none(self):
        legacy_dict = {"date_col": "date", "market_col": "market", "markets": ["UK"]}
        spec = ModelSpec.from_dict(legacy_dict)
        assert spec.fh_dna_cross_sell_outcome_id is None

    def test_legacy_model_meta_with_no_outcome_catalogue_at_fit_reconstructs(
        self, tmp_path, consistent_project
    ):
        # consistent_project's meta already has an empty outcome_catalogue_at_fit
        # (the default before this field existed) - export/import/reconstruct
        # must all still work, not raise on the missing field.
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)
        assert reconstructed["frame"] is not None
        assert reconstructed["model_meta"].outcome_catalogue_at_fit == []

    def test_legacy_meta_fingerprint_verification_still_matches(
        self, tmp_path, consistent_project
    ):
        # verify_imported_approval now always passes outcome_catalogue= to
        # fingerprint_model_spec - for a legacy meta with no catalogue at
        # all, this must resolve to the same fingerprint as when the
        # approval was originally granted (also with no catalogue), not a
        # spurious mismatch.
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is not None, message

    def test_mask_only_governance_migration_survives_repeated_bundle_round_trips(
        self, tmp_path, consistent_project
    ):
        legacy_masks = ResolvedPathwayMasks.from_dict(
            {
                "primary_channels_by_outcome": {"New": ["TV_Brand"]},
                "active_channels_by_outcome": {},
                "exploratory_channels_by_outcome": {},
                "cross_product_lag_weeks": 4,
            }
        )
        project = dict(consistent_project)
        project["model_meta"] = replace(
            consistent_project["model_meta"], pathway_masks=legacy_masks
        )

        first = import_project(export_project(tmp_path / "legacy-first.zip", **project))
        first_state = reconstruct_model_state(first)
        first_masks = first_state["model_meta"].pathway_masks
        assert first_masks.legacy_governance_mode
        assert first_masks.migration_report
        assert any(
            "planning remain blocked" in warning
            for warning in audit_project_resumability(first)["warnings"]
        )

        project["model_meta"] = first_state["model_meta"]
        second = import_project(
            export_project(tmp_path / "legacy-second.zip", **project)
        )
        second_masks = reconstruct_model_state(second)["model_meta"].pathway_masks
        assert second_masks.to_dict() == first_masks.to_dict()


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
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                {"2026-07": {"TV_Brand": 100.0}},
                "UK",
                reconstructed["model_meta"],
                reconstructed["posterior_params"],
                {
                    "2026-07": {
                        "trend": 0.0,
                        "fourier": np.zeros(6),
                        "promo": {"New": 0.0},
                        "controls": {},
                        "outcome_controls": {},
                    }
                },
                approval=approval,
                model_run_id=imported["model_run_id"],
                data_fingerprint="stale",
                model_spec_fingerprint="stale",
                posterior_fingerprint="stale",
            )

    def test_rejected_when_model_spec_differs(self, tmp_path, consistent_project):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        imported["prior_config"]["decay_mu"] = 0.9

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "does not match" in message.lower()

    def test_rejected_when_posterior_artefacts_differ(
        self, tmp_path, consistent_meta, consistent_project
    ):
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        imported["trace"] = _make_trace(
            consistent_meta, seed=999
        )  # structurally valid, numerically different

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "does not match" in message.lower()

    def test_rejected_when_fit_time_outcome_catalogue_differs(self, tmp_path):
        # PR E.1 test case: "outcome catalogue change invalidates approval",
        # exercised at the full persistence layer (not just fingerprint_model_spec
        # directly) - an approval granted for one outcome_catalogue_at_fit
        # must not verify against a reimport where that catalogue has since
        # changed (e.g. a GSA outcome relabelled as a sign-up outcome).
        transformed_data = pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=8, freq="W"),
                "market": ["UK"] * 8,
                "TV_Brand": [100.0, 120.0, 90.0, 110.0, 130.0, 95.0, 105.0, 115.0],
                "fh_new_gsa": [10, 12, 9, 11, 13, 9, 10, 11],
            }
        )
        model_spec_dict = ModelSpec(
            date_col="date",
            market_col="market",
            markets=["UK"],
            segment_outcomes={"New": "fh_new_gsa"},
            channels=["TV_Brand"],
        ).to_dict()
        prior_config = {"decay_mu": 0.5}
        dna_lag_weeks = 4
        spec = ModelSpec.from_dict(model_spec_dict)
        frame = prepare_fh_modeling_frame(transformed_data, spec)

        outcome_at_fit = OutcomeDefinition(
            outcome_id="fh_new",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            source_column="fh_new_gsa",
        )
        meta = FHModelMeta(
            markets=["UK"],
            outcome_ids=["fh_new"],
            channels=["TV_Brand"],
            dna_channels=[],
            dna_channel_idx=[],
            non_dna_idx=[0],
            dna_outcome_id="fh_new",
            dna_lag_weeks=4,
            unpooled_markets=[],
            control_names=[],
            outcome_catalogue_at_fit=[outcome_at_fit],
        )
        trace = _make_trace(meta)
        posterior_params = extract_posterior_params(trace, meta)

        from ancestry_mmm.core.outcomes import outcome_catalogue_fingerprint_payload

        model_run_id = "run-catalogue-1"
        approval = ModelApproval(
            approved_by="Jane Analyst",
            model_run_id=model_run_id,
            data_fingerprint=fingerprint_dataframe(frame["df"]),
            model_spec_fingerprint=fingerprint_model_spec(
                model_spec_dict,
                prior_config,
                dna_lag_weeks,
                direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
                outcome_catalogue=outcome_catalogue_fingerprint_payload(
                    [outcome_at_fit]
                ),
            ),
            posterior_fingerprint=fingerprint_posterior(posterior_params),
        )
        project = dict(
            raw_sources={},
            transformed_data=transformed_data,
            pipeline_steps=[],
            model_spec=model_spec_dict,
            prior_config=prior_config,
            dna_lag_weeks=dna_lag_weeks,
            trace=trace,
            scenarios=[],
            model_approval=approval.to_dict(),
            model_run_id=model_run_id,
            model_meta=meta,
        )

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        # Sanity: as exported, it verifies cleanly.
        ok_approval, ok_message = verify_imported_approval(imported, reconstructed)
        assert ok_approval is not None, ok_message

        # Now simulate the catalogue having changed since the fit (e.g. the
        # imported bundle's model_meta reflects a later relabel) - approval
        # must no longer verify.
        from dataclasses import replace as dc_replace

        relabelled = dc_replace(outcome_at_fit, metric="Sign-up")
        reconstructed["model_meta"] = dc_replace(
            reconstructed["model_meta"], outcome_catalogue_at_fit=[relabelled]
        )

        approval_after, message_after = verify_imported_approval(
            imported, reconstructed
        )
        assert approval_after is None
        assert "does not match" in message_after.lower()

    def test_no_approval_in_bundle(self, tmp_path, consistent_project):
        consistent_project = dict(consistent_project)
        consistent_project["model_approval"] = None
        output_path = export_project(tmp_path / "bundle.zip", **consistent_project)
        imported = import_project(output_path)
        reconstructed = reconstruct_model_state(imported)

        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "no approval" in message.lower()

    def test_legacy_bundle_without_model_meta_remains_importable_but_unverified(
        self, tmp_path, sample_project
    ):
        # sample_project has model_approval but no model_run_id/model_meta at all -
        # simulates a bundle from before model-bound approval existed.
        output_path = export_project(tmp_path / "bundle.zip", **sample_project)
        imported = import_project(output_path)
        assert imported["model_meta"] is None

        reconstructed = reconstruct_model_state(imported)
        approval, message = verify_imported_approval(imported, reconstructed)
        assert approval is None
        assert "predates" in message.lower() or "unverified" in message.lower()

    def test_legacy_approval_within_an_otherwise_new_bundle_is_unverified(
        self, tmp_path, consistent_project
    ):
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


class TestScenariosCheckpointOfficialResumability:
    """G2A.7a.10 (brief section 7, 14.4): audit_project_resumability's
    "scenarios" checkpoint path used to read model_approval_fingerprint from
    a "fingerprint" dict key ModelApproval.to_dict() never populates (always
    ""), and passed counterfactual_fingerprint="" - both always blank, so
    ScenarioValidationContext's required-field check rejected every official
    scenario with a generic "incomplete_validation_context" message,
    regardless of whether it was actually current or stale."""

    def _official_scenario(
        self, *, model_run_id, model_approval_fingerprint, counterfactual_fp="cf-fp-1"
    ):
        return {
            "name": "manual-uk",
            "market": "UK",
            "spend_plan": {"2024-01": {"TV_Brand": 100.0}},
            "objective": "fh_gsa",
            "constraints": [],
            "notes": "",
            "scenario_plan": {
                "monetary_decisions_by_period": {"2024-01": {"TV_Brand": 100.0}},
                "activity_quantity_assumptions_by_period": {},
                "activity_units": None,
                "schema_version": 1,
            },
            "planning_objective": {
                "estimand": "incremental_outcome",
                "metric_key": "fh_gsa",
                "target_outcome_ids": ["New"],
                "value_currency": None,
                "spend_scope": "cost_bearing_decisions",
                "activity_scope": "optimisable_interventions",
                "counterfactual_policy_fingerprint": counterfactual_fp,
                "schema_version": 3,
            },
            "artefact_kind": "manual_scenario",
            "governance_mode": "official",
            # PR 88B: bumped from 3 to 4 - schema 4 requires
            # governance_dependencies.planning_semantics_fingerprint for an
            # official scenario to be "current" rather than
            # "legacy_unverified".
            "schema_version": 4,
            "governance_dependencies": {
                "model_run_id": model_run_id,
                "model_approval_fingerprint": model_approval_fingerprint,
                "data_fingerprint": "will-be-filled",
                "model_spec_fingerprint": "will-be-filled",
                "posterior_fingerprint": "will-be-filled",
                "planning_objective_fingerprint": "will-be-filled",
                "outcome_authorisations": [
                    {
                        "outcome_id": "New",
                        "requested_use": "planning",
                        "approval_id": "apr-gsa",
                        "definition_fingerprint": "will-be-filled",
                        "market": "UK",
                        "product": None,
                        "segment": "New",
                    }
                ],
                "activity_definitions_fingerprint": None,
                "cost_mapping_fingerprint": None,
                "counterfactual_policy_fingerprint": counterfactual_fp or None,
                "nbt_completeness_fingerprint": None,
                "planning_semantics_fingerprint": (
                    CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint()
                ),
            },
        }

    def _project_with_official_scenario(
        self, consistent_project, consistent_meta, *, scenario
    ):
        from ancestry_mmm.core.outcome_approval import (
            OutcomeApproval,
            fingerprint_outcome_definition,
        )
        from ancestry_mmm.core.outcomes import (
            FAMILY_HISTORY,
            METRIC_KEY_FH_GSA,
            OutcomeDefinition,
        )
        from ancestry_mmm.core.optimization import (
            PlanningObjective,
            fingerprint_planning_objective,
        )

        outcome_def = OutcomeDefinition(
            outcome_id="New",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="fh_new_gsa",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )
        def_fp = fingerprint_outcome_definition(outcome_def)
        approval_record = OutcomeApproval(
            approval_id="apr-gsa",
            outcome_id="New",
            definition_fingerprint=def_fp,
            status="approved",
            allowed_uses=("planning",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        # Deliberately does NOT add outcome_catalogue_at_fit to model_meta -
        # validate_scenario_dependencies matches saved authorisations against
        # the bundle's outcome_definitions.json by outcome_id, not against
        # model_meta's fitted catalogue, and consistent_project's approval
        # fingerprints were computed against consistent_meta's *empty*
        # catalogue - adding one here would change the reconstructed
        # model_spec_fingerprint and produce a real (not intended) mismatch.
        scenario["governance_dependencies"]["outcome_authorisations"][0][
            "definition_fingerprint"
        ] = def_fp
        scenario["governance_dependencies"]["planning_objective_fingerprint"] = (
            fingerprint_planning_objective(
                PlanningObjective.from_dict(scenario["planning_objective"])
            )
        )
        project = dict(consistent_project)
        # "raw_sources" must be non-empty for the "scenarios" checkpoint's
        # required-artefact check (audit_project_resumability's `resumable`).
        project["raw_sources"] = {"media": project["transformed_data"].copy()}
        project["model_meta"] = consistent_meta
        project["outcome_definitions"] = [outcome_def.to_dict()]
        project["outcome_approvals"] = [approval_record.to_dict()]
        project["scenarios"] = [scenario]
        project["workflow_state"] = {"checkpoint": "scenarios"}
        return project

    def test_current_scenario_reports_officially_resumable_with_canonical_fingerprint(
        self,
        tmp_path,
        consistent_project,
        consistent_meta,
    ):
        approval = ModelApproval.from_dict(consistent_project["model_approval"])
        canonical_fp = fingerprint_model_approval(approval)
        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=canonical_fp,
            counterfactual_fp="",  # this scenario never declared a counterfactual dependency
        )
        project = self._project_with_official_scenario(
            consistent_project,
            consistent_meta,
            scenario=scenario,
        )
        # Fill in the real current data/spec/posterior fingerprints the same
        # way scenario_to_dict would have when this scenario was saved.
        scenario["governance_dependencies"]["data_fingerprint"] = (
            approval.data_fingerprint
        )
        scenario["governance_dependencies"]["model_spec_fingerprint"] = (
            approval.model_spec_fingerprint
        )
        scenario["governance_dependencies"]["posterior_fingerprint"] = (
            approval.posterior_fingerprint
        )

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is True, audit["official_blocking_reasons"]

    def test_mismatched_model_approval_blocks_with_explicit_reason(
        self,
        tmp_path,
        consistent_project,
        consistent_meta,
    ):
        # Corrupt the bundle's *actual* model approval identity (not just
        # the scenario's saved fingerprint) so require_matching_approval
        # itself rejects it against the reconstructed current model -
        # exercising the new early model-identity gate, not the later
        # per-field staleness comparison.
        consistent_project = dict(consistent_project)
        stale_approval = ModelApproval.from_dict(consistent_project["model_approval"])
        stale_approval = replace(
            stale_approval, data_fingerprint="a-different-data-fingerprint"
        )
        consistent_project["model_approval"] = stale_approval.to_dict()

        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=fingerprint_model_approval(stale_approval),
            counterfactual_fp="",
        )
        project = self._project_with_official_scenario(
            consistent_project,
            consistent_meta,
            scenario=scenario,
        )
        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        # Loadable does not mean officially usable.
        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "model_approval_mismatch" in reasons

    def test_scenario_with_counterfactual_dependency_reports_unverifiable(
        self,
        tmp_path,
        consistent_project,
        consistent_meta,
    ):
        approval = ModelApproval.from_dict(consistent_project["model_approval"])
        canonical_fp = fingerprint_model_approval(approval)
        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=canonical_fp,
            counterfactual_fp="cf-fp-real",
        )
        scenario["governance_dependencies"]["data_fingerprint"] = (
            approval.data_fingerprint
        )
        scenario["governance_dependencies"]["model_spec_fingerprint"] = (
            approval.model_spec_fingerprint
        )
        scenario["governance_dependencies"]["posterior_fingerprint"] = (
            approval.posterior_fingerprint
        )
        project = self._project_with_official_scenario(
            consistent_project,
            consistent_meta,
            scenario=scenario,
        )
        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "counterfactual_identity_unverifiable" in reasons
        # Never a generic, uninformative message pretending the scenario
        # was compared against itself.
        assert "incomplete_validation_context" not in reasons

    def _project_with_counterfactual_scenario(
        self, consistent_project, consistent_meta, *, counterfactual_fp
    ):
        approval = ModelApproval.from_dict(consistent_project["model_approval"])
        canonical_fp = fingerprint_model_approval(approval)
        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=canonical_fp,
            counterfactual_fp=counterfactual_fp,
        )
        scenario["governance_dependencies"]["data_fingerprint"] = (
            approval.data_fingerprint
        )
        scenario["governance_dependencies"]["model_spec_fingerprint"] = (
            approval.model_spec_fingerprint
        )
        scenario["governance_dependencies"]["posterior_fingerprint"] = (
            approval.posterior_fingerprint
        )
        return self._project_with_official_scenario(
            consistent_project, consistent_meta, scenario=scenario
        )

    def test_matching_project_level_counterfactual_policy_is_officially_resumable(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # PR 125A: a project-level CounterfactualPolicy now travels through
        # the bundle - a scenario whose saved fingerprint matches it is
        # genuinely, not just technically, resumable.
        policy = CounterfactualPolicy()
        project = self._project_with_counterfactual_scenario(
            consistent_project, consistent_meta, counterfactual_fp=policy.fingerprint()
        )
        project["counterfactual_policy"] = policy.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        assert imported["counterfactual_policy"] == policy.to_dict()
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is True, audit["official_blocking_reasons"]

    def test_mismatched_project_level_counterfactual_policy_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # The scenario's saved fingerprint reflects a policy the project no
        # longer uses (e.g. the demand-capture rule was changed after this
        # scenario was saved) - must fail closed with a precise reason, not
        # be silently treated as current.
        saved_policy = CounterfactualPolicy(demand_capture_rule="zero")
        current_policy = CounterfactualPolicy(demand_capture_rule="hold_plan")
        project = self._project_with_counterfactual_scenario(
            consistent_project,
            consistent_meta,
            counterfactual_fp=saved_policy.fingerprint(),
        )
        project["counterfactual_policy"] = current_policy.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "counterfactual_identity_mismatch" in reasons

    def test_malformed_project_level_counterfactual_policy_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # A tampered or corrupted config/counterfactual_policy.json must
        # fail closed with a precise reason, never crash the audit and
        # never be silently treated as absent (which would fall back to the
        # weaker "unverifiable" legacy path instead of flagging corruption).
        policy = CounterfactualPolicy()
        project = self._project_with_counterfactual_scenario(
            consistent_project, consistent_meta, counterfactual_fp=policy.fingerprint()
        )
        project["counterfactual_policy"] = {"decision_activity_rule": "not-a-real-rule"}

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "counterfactual_policy_malformed" in reasons

    def _project_with_currency_scenario(
        self, consistent_project, consistent_meta, *, currency_context_fp
    ):
        approval = ModelApproval.from_dict(consistent_project["model_approval"])
        canonical_fp = fingerprint_model_approval(approval)
        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=canonical_fp,
            counterfactual_fp="",
        )
        scenario["governance_dependencies"]["data_fingerprint"] = (
            approval.data_fingerprint
        )
        scenario["governance_dependencies"]["model_spec_fingerprint"] = (
            approval.model_spec_fingerprint
        )
        scenario["governance_dependencies"]["posterior_fingerprint"] = (
            approval.posterior_fingerprint
        )
        scenario["governance_dependencies"]["currency_context_fingerprint"] = (
            currency_context_fp
        )
        return self._project_with_official_scenario(
            consistent_project, consistent_meta, scenario=scenario
        )

    def test_matching_project_level_currency_context_is_officially_resumable(
        self, tmp_path, consistent_project, consistent_meta
    ):
        context = CurrencyContext(market_reporting_currency="GBP", value_currency="GBP")
        project = self._project_with_currency_scenario(
            consistent_project,
            consistent_meta,
            currency_context_fp=context.fingerprint(),
        )
        project["currency_context"] = context.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        assert imported["currency_context"]["value_currency"] == "GBP"
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is True, audit["official_blocking_reasons"]

    def test_missing_project_level_currency_context_blocks_as_unverifiable(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # A bundle exported before PR 125A (or one where the analyst never
        # resolved a value currency this session) carries no project-level
        # currency context - a scenario that depends on one must fail
        # closed, never be silently promoted to official.
        context = CurrencyContext(market_reporting_currency="GBP", value_currency="GBP")
        project = self._project_with_currency_scenario(
            consistent_project,
            consistent_meta,
            currency_context_fp=context.fingerprint(),
        )

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        assert imported["currency_context"] is None
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "currency_identity_unverifiable" in reasons

    def test_mismatched_project_level_currency_context_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        saved_context = CurrencyContext(
            market_reporting_currency="GBP", value_currency="GBP"
        )
        current_context = CurrencyContext(
            market_reporting_currency="USD", value_currency="USD"
        )
        project = self._project_with_currency_scenario(
            consistent_project,
            consistent_meta,
            currency_context_fp=saved_context.fingerprint(),
        )
        project["currency_context"] = current_context.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "currency_identity_mismatch" in reasons

    def test_malformed_project_level_currency_context_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        context = CurrencyContext(market_reporting_currency="GBP", value_currency="GBP")
        project = self._project_with_currency_scenario(
            consistent_project,
            consistent_meta,
            currency_context_fp=context.fingerprint(),
        )
        project["currency_context"] = {"market_reporting_currency": "not-iso"}

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "currency_context_malformed" in reasons

    def _project_with_value_mapping_scenario(
        self, consistent_project, consistent_meta, *, value_mapping_fp
    ):
        # PR 125A corrective review finding (P1): an "incremental_value"
        # estimand is the one PlanningObjective shape that actually requires
        # a value mapping (validate_scenario_dependencies's
        # requires_value_and_currency gate) - reuses _official_scenario's
        # shape but swaps the estimand/value_currency so this test exercises
        # the exact workflow the finding named, not incremental_outcome.
        approval = ModelApproval.from_dict(consistent_project["model_approval"])
        canonical_fp = fingerprint_model_approval(approval)
        scenario = self._official_scenario(
            model_run_id=consistent_project["model_run_id"],
            model_approval_fingerprint=canonical_fp,
            counterfactual_fp="",
        )
        scenario["planning_objective"]["estimand"] = "incremental_value"
        scenario["planning_objective"]["value_currency"] = "GBP"
        scenario["governance_dependencies"]["data_fingerprint"] = (
            approval.data_fingerprint
        )
        scenario["governance_dependencies"]["model_spec_fingerprint"] = (
            approval.model_spec_fingerprint
        )
        scenario["governance_dependencies"]["posterior_fingerprint"] = (
            approval.posterior_fingerprint
        )
        scenario["governance_dependencies"]["value_mapping_fingerprint"] = (
            value_mapping_fp
        )
        # An incremental_value objective also requires a current currency
        # context (the same requires_value_and_currency gate) - give it a
        # matching one so this test isolates the value-mapping check.
        currency_context = CurrencyContext(
            market_reporting_currency="GBP", value_currency="GBP"
        )
        scenario["governance_dependencies"]["currency_context_fingerprint"] = (
            currency_context.fingerprint()
        )
        project = self._project_with_official_scenario(
            consistent_project, consistent_meta, scenario=scenario
        )
        project["currency_context"] = currency_context.to_dict()
        return project

    def test_matching_project_level_value_mapping_is_officially_resumable(
        self, tmp_path, consistent_project, consistent_meta
    ):
        mapping = OutcomeValueMapping(
            value_by_outcome_id={"New": 5.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        project = self._project_with_value_mapping_scenario(
            consistent_project,
            consistent_meta,
            value_mapping_fp=mapping.fingerprint,
        )
        project["value_mapping"] = mapping.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        assert imported["value_mapping"]["mapping_fingerprint"] == mapping.fingerprint
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is True, audit["official_blocking_reasons"]

    def test_missing_project_level_value_mapping_blocks_as_unverifiable(
        self, tmp_path, consistent_project, consistent_meta
    ):
        mapping = OutcomeValueMapping(
            value_by_outcome_id={"New": 5.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        project = self._project_with_value_mapping_scenario(
            consistent_project,
            consistent_meta,
            value_mapping_fp=mapping.fingerprint,
        )
        # value_mapping intentionally omitted (project-level file absent).

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        assert imported["value_mapping"] is None
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "value_mapping_identity_unverifiable" in reasons

    def test_mismatched_project_level_value_mapping_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        saved_mapping = OutcomeValueMapping(
            value_by_outcome_id={"New": 5.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        current_mapping = OutcomeValueMapping(
            value_by_outcome_id={"New": 9.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        project = self._project_with_value_mapping_scenario(
            consistent_project,
            consistent_meta,
            value_mapping_fp=saved_mapping.fingerprint,
        )
        project["value_mapping"] = current_mapping.to_dict()

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "value_mapping_identity_mismatch" in reasons

    def test_malformed_project_level_value_mapping_blocks_with_explicit_reason(
        self, tmp_path, consistent_project, consistent_meta
    ):
        mapping = OutcomeValueMapping(
            value_by_outcome_id={"New": 5.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        project = self._project_with_value_mapping_scenario(
            consistent_project,
            consistent_meta,
            value_mapping_fp=mapping.fingerprint,
        )
        project["value_mapping"] = {
            "value_by_outcome_id": {"New": 5.0},
            "currency_by_outcome_id": {"New": "not-iso"},
        }

        output_path = export_project(tmp_path / "bundle.zip", **project)
        imported = import_project(output_path)
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "value_mapping_malformed" in reasons


class TestScenariosCheckpointPolicyBackedApprovalRequiresDiagnostics:
    """PR 122 corrective review finding: fixing the crash where
    audit_project_resumability never loaded a policy-backed approval's
    approval_readiness/validation_policy before calling
    require_matching_approval (always raising an uncaught
    ValidationPolicyBlockedError) exposed a narrower gap -
    require_matching_approval only checks that approval_readiness's own
    recorded fingerprints are internally self-consistent; it cannot also
    verify them against a freshly recomputed diagnostics artefact
    fingerprint, since DiagnosticsArtefact is an application-layer type
    core.persistence must not import (see
    application.project_service.verify_imported_readiness, which does that
    fuller check). A bundle missing its diagnostics_artefact entirely must
    still fail closed here rather than reporting full official
    resumability on an incomplete evidence chain."""

    def test_policy_backed_scenario_without_a_diagnostics_artefact_is_not_officially_resumable(
        self, tmp_path
    ):
        from ancestry_mmm.tests.support.lifecycle_fixture import (
            build_lifecycle_project,
            build_saved_scenario_dict,
            create_official_artifacts,
            evaluate_official_manual_scenario,
        )

        # Mirrors build_lifecycle_project_bundle exactly (the same
        # self-consistent policy-backed governance chain PR 122's browser
        # journey proves resumable), but deliberately omits
        # diagnostics_artefact - everything else that
        # require_matching_approval itself checks (readiness, policy,
        # approval, model identity, scenario) is otherwise complete.
        project = build_lifecycle_project()
        store_dir = tmp_path / "curve-artifacts"
        create_official_artifacts(project, store_dir)
        scenario_result = evaluate_official_manual_scenario(project)
        scenario_dict = build_saved_scenario_dict(project, scenario_result)
        assert project.approval.validation_policy_id

        output_path = export_project(
            tmp_path / "no-diagnostics-bundle.zip",
            raw_sources={"joined": project.fitted.transformed_data.copy()},
            transformed_data=project.fitted.transformed_data,
            pipeline_steps=[],
            model_spec=project.fitted.model_spec_dict,
            prior_config=project.fitted.prior_config,
            dna_lag_weeks=project.fitted.dna_lag_weeks,
            trace=project.fitted.trace,
            scenarios=[scenario_dict],
            curve_artifact_store_source_dir=store_dir,
            model_approval=project.approval.to_dict(),
            model_run_id=project.fitted.model_run_id,
            model_meta=project.fitted.meta,
            outcome_definitions=[project.fitted.outcome_definition.to_dict()],
            activity_definitions=[
                a.to_dict() for a in project.fitted.activity_definitions
            ],
            outcome_approvals=[project.outcome_approval.to_dict()],
            validation_policy=project.policy.to_dict(),
            approval_readiness=project.readiness.to_dict(),
            media_cost_mappings=project.cost_mapping_registry.to_dict(),
            # diagnostics_artefact intentionally omitted (defaults to None).
        )

        reimported = import_project(output_path)
        assert reimported.get("diagnostics_artefact") is None
        audit = audit_project_resumability(reimported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False, audit[
            "official_blocking_reasons"
        ]
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "diagnostics artefact" in reasons

    def test_policy_backed_scenario_with_a_structurally_malformed_diagnostics_artefact_is_not_officially_resumable(
        self, tmp_path
    ):
        from ancestry_mmm.tests.support.lifecycle_fixture import (
            build_lifecycle_project,
            build_saved_scenario_dict,
            create_official_artifacts,
            evaluate_official_manual_scenario,
        )

        # Same self-consistent chain as above, but diagnostics_artefact is
        # present-and-not-None while still structurally invalid (a list, not
        # a dict) - core.persistence cannot import DiagnosticsArtefact to
        # fully re-verify a *well-formed* artefact's fingerprint (that fuller
        # check lives at application.project_service.verify_imported_readiness),
        # but a value that isn't even a dict is a core-detectable gap and
        # must not be treated as present evidence.
        project = build_lifecycle_project()
        store_dir = tmp_path / "curve-artifacts"
        create_official_artifacts(project, store_dir)
        scenario_result = evaluate_official_manual_scenario(project)
        scenario_dict = build_saved_scenario_dict(project, scenario_result)
        assert project.approval.validation_policy_id

        output_path = export_project(
            tmp_path / "malformed-diagnostics-bundle.zip",
            raw_sources={"joined": project.fitted.transformed_data.copy()},
            transformed_data=project.fitted.transformed_data,
            pipeline_steps=[],
            model_spec=project.fitted.model_spec_dict,
            prior_config=project.fitted.prior_config,
            dna_lag_weeks=project.fitted.dna_lag_weeks,
            trace=project.fitted.trace,
            scenarios=[scenario_dict],
            curve_artifact_store_source_dir=store_dir,
            model_approval=project.approval.to_dict(),
            model_run_id=project.fitted.model_run_id,
            model_meta=project.fitted.meta,
            outcome_definitions=[project.fitted.outcome_definition.to_dict()],
            activity_definitions=[
                a.to_dict() for a in project.fitted.activity_definitions
            ],
            outcome_approvals=[project.outcome_approval.to_dict()],
            validation_policy=project.policy.to_dict(),
            approval_readiness=project.readiness.to_dict(),
            media_cost_mappings=project.cost_mapping_registry.to_dict(),
            diagnostics_artefact=["not", "a", "dict"],  # type: ignore[arg-type]
        )

        reimported = import_project(output_path)
        assert reimported.get("diagnostics_artefact") == ["not", "a", "dict"]
        audit = audit_project_resumability(reimported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False, audit[
            "official_blocking_reasons"
        ]
        reasons = " ".join(r["reason"] for r in audit["official_blocking_reasons"])
        assert "diagnostics artefact" in reasons


# ---------------------------------------------------------------------------
# Corrective PR A6 (review-debt finding 10, PR #104): the official_curves
# checkpoint must revalidate each imported curve artifact against the
# reconstructed imported model identity and a matching current outcome
# approval - historical fingerprint self-consistency alone (an artifact
# matching its own stored fingerprints) does not prove the artifact belongs
# to *this* bundle's model.
# ---------------------------------------------------------------------------


def _matching_outcome_def_and_approval(allowed_uses=("curve_publication",)):
    from ancestry_mmm.core.outcome_approval import (
        OutcomeApproval,
        fingerprint_outcome_definition,
    )
    from ancestry_mmm.core.outcomes import (
        FAMILY_HISTORY,
        METRIC_KEY_FH_GSA,
        OutcomeDefinition,
    )

    outcome_def = OutcomeDefinition(
        outcome_id="New",
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="fh_new_gsa",
        unit="GSA",
        aggregation_type="count",
        event_definition="A new subscriber",
        date_basis="event_date",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="Excludes internal/test accounts",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )
    def_fp = fingerprint_outcome_definition(outcome_def)
    approval_record = OutcomeApproval(
        approval_id="apr-gsa",
        outcome_id="New",
        definition_fingerprint=def_fp,
        status="approved",
        allowed_uses=allowed_uses,
        approved_by="Jane Analyst",
        approved_at="2026-01-01",
    )
    return outcome_def, approval_record


class TestOfficialCurvesCheckpointRevalidation:
    def test_matching_official_curve_artifact_satisfies_checkpoint(
        self, tmp_path, consistent_project, consistent_meta
    ):
        outcome_def, approval_record = _matching_outcome_def_and_approval()
        approval = ModelApproval.from_dict(consistent_project["model_approval"])

        project = dict(consistent_project)
        project["raw_sources"] = {"media": project["transformed_data"].copy()}
        project["model_meta"] = consistent_meta
        project["outcome_definitions"] = [outcome_def.to_dict()]
        project["outcome_approvals"] = [approval_record.to_dict()]
        project["workflow_state"] = {"checkpoint": "official_curves"}

        artifact_metadata = replace(
            _official_artifact_metadata("art-matching"),
            model_identity_snapshot={
                "model_run_id": consistent_project["model_run_id"],
                "data_fingerprint": approval.data_fingerprint,
                "model_spec_fingerprint": approval.model_spec_fingerprint,
                "posterior_fingerprint": approval.posterior_fingerprint,
            },
            outcome_definition_snapshot=outcome_def.to_dict(),
            outcome_approval_snapshot=approval_record.to_dict(),
        )
        artifact_metadata = replace(
            artifact_metadata,
            fingerprints=dict(compute_curve_artifact_fingerprints(artifact_metadata)),
        )
        artifact_source = tmp_path / "artifact-source"
        write_curve_artifact(
            artifact_source / "art-matching",
            metadata=artifact_metadata,
            draws=_official_artifact_draws(),
            summaries=_official_artifact_summaries(),
        )
        project["curve_artifact_store_source_dir"] = artifact_source

        imported = import_project(export_project(tmp_path / "bundle.zip", **project))
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is True, audit["official_blocking_reasons"]

    def test_foreign_artifact_identity_mismatch_blocks_checkpoint(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # The artifact's model_identity_snapshot (run-1/d1/s1/p1, from the
        # shared _official_artifact_metadata fixture) does not match
        # consistent_project's actual reconstructed model identity -
        # simulating an artifact copied from a different project/model.
        outcome_def, approval_record = _matching_outcome_def_and_approval()
        project = dict(consistent_project)
        project["raw_sources"] = {"media": project["transformed_data"].copy()}
        project["model_meta"] = consistent_meta
        project["outcome_definitions"] = [outcome_def.to_dict()]
        project["outcome_approvals"] = [approval_record.to_dict()]
        project["workflow_state"] = {"checkpoint": "official_curves"}

        artifact_source = tmp_path / "artifact-source"
        _write_official_artifact(artifact_source, "art-foreign")
        project["curve_artifact_store_source_dir"] = artifact_source

        imported = import_project(export_project(tmp_path / "bundle.zip", **project))
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = [
            r
            for r in audit["official_blocking_reasons"]
            if r["artefact_type"] == "curve_artifact"
        ]
        assert reasons, audit["official_blocking_reasons"]
        assert reasons[0]["artefact_id"] == "art-foreign"
        assert "model_identity_mismatch" in reasons[0]["reason"]

    def test_artifact_bound_to_unrelated_approval_blocks_checkpoint(
        self, tmp_path, consistent_project, consistent_meta
    ):
        # Model identity matches, but the only active approval in the
        # bundle is for a *different* outcome than the one the artifact is
        # actually bound to - a foreign/unrelated approval must not satisfy
        # the checkpoint on the artifact's behalf.
        from ancestry_mmm.core.outcome_approval import fingerprint_outcome_definition

        outcome_def, _matching_approval = _matching_outcome_def_and_approval()
        unrelated_def, unrelated_approval = _matching_outcome_def_and_approval()
        unrelated_def = replace(unrelated_def, outcome_id="fh_returning")
        unrelated_approval = replace(
            unrelated_approval,
            approval_id="apr-unrelated",
            outcome_id="fh_returning",
            definition_fingerprint=fingerprint_outcome_definition(unrelated_def),
        )
        approval = ModelApproval.from_dict(consistent_project["model_approval"])

        project = dict(consistent_project)
        project["raw_sources"] = {"media": project["transformed_data"].copy()}
        project["model_meta"] = consistent_meta
        project["outcome_definitions"] = [
            outcome_def.to_dict(),
            unrelated_def.to_dict(),
        ]
        project["outcome_approvals"] = [unrelated_approval.to_dict()]
        project["workflow_state"] = {"checkpoint": "official_curves"}

        artifact_metadata = replace(
            _official_artifact_metadata("art-unrelated-approval"),
            model_identity_snapshot={
                "model_run_id": consistent_project["model_run_id"],
                "data_fingerprint": approval.data_fingerprint,
                "model_spec_fingerprint": approval.model_spec_fingerprint,
                "posterior_fingerprint": approval.posterior_fingerprint,
            },
            outcome_definition_snapshot=outcome_def.to_dict(),
            outcome_approval_snapshot={"approval_id": "apr-gsa"},
        )
        artifact_metadata = replace(
            artifact_metadata,
            fingerprints=dict(compute_curve_artifact_fingerprints(artifact_metadata)),
        )
        artifact_source = tmp_path / "artifact-source"
        write_curve_artifact(
            artifact_source / "art-unrelated-approval",
            metadata=artifact_metadata,
            draws=_official_artifact_draws(),
            summaries=_official_artifact_summaries(),
        )
        project["curve_artifact_store_source_dir"] = artifact_source

        imported = import_project(export_project(tmp_path / "bundle.zip", **project))
        audit = audit_project_resumability(imported)

        assert audit["resumable"] is True
        assert audit["officially_resumable"] is False
        reasons = [
            r
            for r in audit["official_blocking_reasons"]
            if r["artefact_type"] == "curve_artifact"
        ]
        assert reasons, audit["official_blocking_reasons"]
        assert reasons[0]["artefact_id"] == "art-unrelated-approval"
        assert "no_matching_outcome_approval" in reasons[0]["reason"]
