import io
import zipfile
from dataclasses import asdict, replace

import arviz as az
import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
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
from ancestry_mmm.core.pathways import (
    ResolvedPathwayComponent,
    ResolvedPathwayMasks,
)
from ancestry_mmm.core.persistence import (
    UnsafeZipEntryError,
    _is_safe_zip_member,
    _safe_extract_zip,
    audit_project_resumability,
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
    assert (
        imported["monetary_spend_support"]
        == project["monetary_spend_support"]
    )
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
    assert restored_scenario["schema_version"] == 2
    assert restored_scenario["scenario_plan"] == {
        "monetary_decisions_by_period": {
            "2024-01": {"TV_Brand": 100.0}
        },
        "activity_quantity_assumptions_by_period": {},
        "activity_units": None,
        "schema_version": 1,
    }
    assert restored_scenario["planning_objective"]["estimand"] == (
        "incremental_value"
    )
    assert restored_scenario["planning_objective"]["value_currency"] == (
        "UNSPECIFIED"
    )
    assert restored_scenario["constraints"] == [
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
        io.BytesIO(
            imported["curve_bank_binary_files"][
                "canonical_curve_draws.parquet"
            ]
        )
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
        raw_sources={
            "joined": consistent_project["transformed_data"].copy()
        },
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
    assert imported["migration_review"]["replacement_model_run_id"] == (
        imported["model_run_id"]
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
    workbook_sheets = pd.ExcelFile(output_path).sheet_names
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
    workbook_sheets = pd.ExcelFile(output_path).sheet_names
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
            pathway_masks=ResolvedPathwayMasks(
                components=ordered_components
            ),
        )
        imported = import_project(
            export_project(tmp_path / f"component-order-{index}.zip", **project)
        )
        restored = reconstruct_model_state(imported)
        assert restored["posterior_params"] is not None
        restored_masks.append(restored["model_meta"].pathway_masks)

    for masks in restored_masks:
        assert masks.lag_for_component("New", "TV_Brand") == 3
        assert (
            masks.prior_for_component("New", "TV_Brand", default=1.0)
            == 0.2
        )
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
def test_end_to_end_resume_at_each_checkpoint(
    tmp_path, consistent_project, checkpoint
):
    project = dict(consistent_project)
    project["raw_sources"] = {
        "joined": consistent_project["transformed_data"].copy()
    }
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

    imported = import_project(
        export_project(tmp_path / f"{checkpoint}.zip", **project)
    )
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
    expected_params = extract_posterior_params(
        project["trace"], project["model_meta"]
    )
    assert fingerprint_posterior(reconstructed["posterior_params"]) == (
        fingerprint_posterior(expected_params)
    )
    if checkpoint not in {"fitted", "pre_fit"}:
        verified, message = verify_imported_approval(imported, reconstructed)
        assert verified is not None, message
    if checkpoint == "curves":
        assert imported["curve_bank_files"] == {
            "curve.json": '{"channel": "TV_Brand"}'
        }
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

        first = import_project(
            export_project(tmp_path / "legacy-first.zip", **project)
        )
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
