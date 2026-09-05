"""AppTest coverage for PR 96B: 09_Project_Export.py's official curve
artifact store portability.

Focuses on the export-side checkpoint computation (reachable via a real
button click without a fitted model) - the riskiest UI change in this PR,
since it determines whether a bundle is later recognised as having reached
the distinct `official_curves` checkpoint versus falling back to `curves`
(the legacy parameter-snapshot checkpoint) or an earlier one.

The Excel/report buttons (which require a fitted model in session state) are
not driven through the UI here - that logic is already covered end-to-end at
the core/application layer in test_persistence.py, test_project_service.py,
test_curve_service.py, and test_report.py.

PR 122: the import side (file upload) IS driven through the UI below -
`streamlit.testing.v1`'s `FileUploader.set_value()` (available in the
Streamlit version this repo currently pins) can simulate an uploaded file,
closing the gap the docstring above used to describe as untestable. This
proves the page's real "Import bundle" button click reaches
`replace_curve_artifact_store` and transactionally replaces (not merges) the
destination project's official curve artifact store - using the same
deterministic lifecycle fixture builders as
`test_official_lifecycle_integration.py`, not a second hand-rolled fixture.
"""

import dataclasses
import json
import zipfile
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.curve_artifact import (
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    load_curve_artifact_store,
    write_curve_artifact,
)
from ancestry_mmm.core.persistence import (
    export_project,
    import_project,
    resolve_imported_causal_graphs,
)
from ancestry_mmm.core.search_intent_taxonomy import SearchIntentGroup
from ancestry_mmm.tests.support.lifecycle_fixture import (
    UNRELATED_ARTIFACT_ID,
    build_lifecycle_project,
    build_lifecycle_project_bundle,
    create_official_artifacts,
    write_unrelated_artifact,
)

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "09_Project_Export.py"


def _write_official_artifact(store_dir: Path, artifact_id: str = "art-1") -> None:
    directory = store_dir / artifact_id
    metadata = CurveArtifactMetadata(
        artifact_id=artifact_id,
        creation_timestamp="2026-08-01T00:00:00+00:00",
        model_identity_snapshot={"model_run_id": "run-1"},
        outcome_definition_snapshot={
            "outcome_id": "fh_new_gsa",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-1",
            "allowed_uses": ["curve_publication"],
        },
    )
    metadata = dataclasses.replace(
        metadata, fingerprints=dict(compute_curve_artifact_fingerprints(metadata))
    )
    row = {
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
    draws = pd.DataFrame([row])
    summaries = pd.DataFrame([{k: v for k, v in row.items() if k != "posterior_draw"}])
    write_curve_artifact(directory, metadata=metadata, draws=draws, summaries=summaries)


def _run_export(monkeypatch, tmp_path, *, project_name: str) -> Path:
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["project_name"] = project_name
    build_button = next(b for b in at.button if b.label == "Build export bundle")
    build_button.click().run()
    assert not at.exception, f"export click raised: {at.exception}"

    # Codex review (PR #348, P1 follow-up): the build no longer writes to
    # (or leaves behind) `export_root / f"{project_name}.zip"` - each build
    # uses a session-unique temporary filename, read into memory, then
    # deleted (see 09_Project_Export.py) - specifically so two sessions
    # building the same project name can never race on one shared path.
    # Callers that need an actual file to hand to `import_project()` write
    # the session's own cached bytes out to their own fresh path instead of
    # relying on any canonical on-disk location.
    bundle_path = tmp_path / f"{project_name}-readback.zip"
    bundle_path.write_bytes(at.session_state["export_last_bundle_bytes"])
    return bundle_path


def test_export_reaches_official_curves_checkpoint_with_a_loaded_artifact(
    monkeypatch, tmp_path
):
    artifact_root = tmp_path / "artifact-root"
    _write_official_artifact(artifact_root / "proj-official")

    bundle_path = _run_export(monkeypatch, tmp_path, project_name="proj-official")

    assert bundle_path.exists()
    imported = import_project(bundle_path)
    assert imported["manifest"]["workflow_checkpoint"] == "official_curves"
    assert imported["manifest"]["contains"]["official_curve_artifacts"] is True


def test_export_falls_back_to_legacy_curves_checkpoint_without_official_artifacts(
    monkeypatch, tmp_path
):
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["project_name"] = "proj-legacy"
    # No artifact store written - only the legacy curve-bank marker, mirroring
    # how the page itself infers "curves" from curve_bank_entry_id.
    at.session_state["curve_bank_entry_id"] = "legacy-entry-1"
    build_button = next(b for b in at.button if b.label == "Build export bundle")
    build_button.click().run()
    assert not at.exception, f"export click raised: {at.exception}"

    bundle_path = tmp_path / "proj-legacy-readback.zip"
    bundle_path.write_bytes(at.session_state["export_last_bundle_bytes"])
    imported = import_project(bundle_path)
    assert imported["manifest"]["workflow_checkpoint"] == "curves"
    assert imported["manifest"]["contains"]["official_curve_artifacts"] is False


def test_import_bundle_transactionally_replaces_the_destination_artifact_store(
    monkeypatch, tmp_path
):
    """PR 122: uploading a bundle via the real "Import bundle" button
    replaces (never merges into) the destination project's official curve
    artifact store - the old unrelated artifact is gone afterwards and the
    two artifacts from the imported bundle are present."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"
    project_name = "proj-destination"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    destination_store = artifact_root / project_name
    write_unrelated_artifact(destination_store)
    pre_existing = load_curve_artifact_store(destination_store)
    assert {a.metadata.artifact_id for a in pre_existing.loaded} == {
        UNRELATED_ARTIFACT_ID
    }

    project = build_lifecycle_project()
    source_store = tmp_path / "source-curve-artifacts"
    create_official_artifacts(project, source_store)
    bundle_path = export_project(
        tmp_path / "lifecycle-bundle.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
        curve_artifact_store_source_dir=source_store,
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = project_name

    uploader = at.file_uploader[0]
    uploader.set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    assert not at.exception, f"file upload raised: {at.exception}"

    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    replaced = load_curve_artifact_store(destination_store)
    assert not replaced.malformed
    replaced_ids = {a.metadata.artifact_id for a in replaced.loaded}
    assert UNRELATED_ARTIFACT_ID not in replaced_ids
    assert replaced_ids == {"lifecycle-model-input", "lifecycle-monetary"}
    assert any("Restored 2 Planning Curve(s)" in (s.value or "") for s in at.success)


def test_import_restores_custom_search_child_under_approved_parent(
    monkeypatch, tmp_path
):
    """REQ-SEARCH-004: exercise the real clean-session import path."""

    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    child = SearchIntentGroup(
        search_intent_group_id="non_brand_search_genealogy",
        search_intent_group_name="Genealogy Non-Brand",
        brand_class="generic_non_brand",
        parent_search_intent_group_id="non_brand_search",
        business_description="Generic genealogy discovery terms.",
        product_scope="Family History",
        intent_type="genealogy",
        owner="Search Governance",
        search_intent_group_version=2,
    )
    activity = ActivityDefinition(
        activity_id="paid-search-genealogy",
        channel="Paid Search",
        activity_ownership="paid",
        model_role="intervention",
        economic_treatment="paid_media_cost",
        planning_eligibility="excluded",
        source="sa360",
        market="UK",
        platform="SA360",
        campaign_type="search",
        product_advertised="Family History",
        model_input_column="paid_search_genealogy",
        search_intent_group_id=child.search_intent_group_id,
        search_platform="google",
    )
    bundle_path = export_project(
        tmp_path / "custom-search-child.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
        project_display_name="Imported Human Project",
        activity_definitions=[activity.to_dict()],
        search_intent_groups=[child.to_dict()],
        search_intent_model_grain=[child.search_intent_group_id],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "UK Production 2026"
    at.file_uploader[0].set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    next(
        button for button in at.button if button.label == "Import bundle"
    ).click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    groups = at.session_state["search_intent_groups"]
    group_ids = [group["search_intent_group_id"] for group in groups]
    assert group_ids.count("non_brand_search") == 1
    assert group_ids.count("brand_search") == 1
    assert child.search_intent_group_id in group_ids
    assert not any(
        "Search intent taxonomy was quarantined" in (w.value or "") for w in at.warning
    )
    assert at.session_state["activity_definitions"][0]["search_platform"] == "google"
    assert at.session_state["activity_definitions"][0]["platform"] == "SA360"
    assert at.session_state["project_name"] == "Imported Human Project"
    assert (
        at.session_state["activity_definitions"][0]["model_input_column"]
        == "paid_search_genealogy"
    )


def test_import_quarantines_malformed_search_taxonomy_history_only(
    monkeypatch, tmp_path
):
    """Malformed audit history must not discard a valid current child."""

    export_root = tmp_path / "exports"
    monkeypatch.setattr("ancestry_mmm.utils.PROJECT_EXPORT_ROOT", export_root)
    child = SearchIntentGroup(
        search_intent_group_id="non_brand_search_genealogy",
        search_intent_group_name="Genealogy Non-Brand",
        brand_class="generic_non_brand",
        parent_search_intent_group_id="non_brand_search",
    )
    bundle_path = export_project(
        tmp_path / "malformed-taxonomy-history.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
        search_intent_groups=[child.to_dict()],
        search_intent_group_versions=[
            {**child.to_dict(), "search_intent_group_version": "bad"}
        ],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    at.file_uploader[0].set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    next(
        button for button in at.button if button.label == "Import bundle"
    ).click().run()

    assert not at.exception, f"malformed history import raised: {at.exception}"
    restored_ids = {
        item["search_intent_group_id"]
        for item in at.session_state["search_intent_groups"]
    }
    assert child.search_intent_group_id in restored_ids
    assert at.session_state["search_intent_group_versions"] == []
    assert any(
        "version record" in (warning.value or "")
        and "quarantined" in (warning.value or "")
        for warning in at.warning
    )


def test_import_quarantines_malformed_current_search_taxonomy_without_crashing_readiness(
    monkeypatch, tmp_path
):
    """Regression for review 5120876238 (thread PRRT_kwDOTd28Js6fiZaZ):
    quarantining a malformed *current* search_intent_groups record must not
    just clear session state - `current_model_identity_fingerprints` (called
    by `verify_imported_approval`/`audit_project_resumability` right after
    this handler, in the same import) re-reads `imported["search_intent_groups"]`
    directly, not session state. Leaving the raw malformed collection there
    used to crash a bundle that also carries a model approval (or reaches
    the official_curves/scenarios checkpoint) after the rest of the project
    had already been installed, instead of completing the advertised
    quarantine."""

    export_root = tmp_path / "exports"
    monkeypatch.setattr("ancestry_mmm.utils.PROJECT_EXPORT_ROOT", export_root)

    project = build_lifecycle_project()
    bundle_path = export_project(
        tmp_path / "malformed-current-taxonomy.zip",
        raw_sources={"joined": project.fitted.transformed_data.copy()},
        transformed_data=project.fitted.transformed_data,
        pipeline_steps=[],
        model_spec=project.fitted.model_spec_dict,
        prior_config=project.fitted.prior_config,
        dna_lag_weeks=project.fitted.dna_lag_weeks,
        trace=project.fitted.trace,
        scenarios=[],
        model_approval=project.approval.to_dict(),
        model_run_id=project.fitted.model_run_id,
        model_meta=project.fitted.meta,
        # A current record missing required fields - SearchIntentGroup.from_dict
        # raises constructing it, which resolve_imported_search_intent_groups
        # turns into the ValueError this handler is meant to quarantine.
        search_intent_groups=[{"search_intent_group_id": "malformed_record"}],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.file_uploader[0].set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    next(
        button for button in at.button if button.label == "Import bundle"
    ).click().run()

    assert not at.exception, (
        "malformed current taxonomy import crashed downstream readiness/"
        f"approval verification instead of completing the quarantine: {at.exception}"
    )
    assert at.session_state["search_intent_groups"] == []
    assert at.session_state["search_intent_group_versions"] == []
    assert at.session_state["search_intent_model_grain"] == []
    assert any(
        "Search intent taxonomy was quarantined" in (w.value or "") for w in at.warning
    )


def test_import_clears_stale_cached_optimiser_results(monkeypatch, tmp_path):
    """Fresh review finding: a cached constrained_result/unconstrained_result
    left over from a DIFFERENT project earlier in this same Streamlit
    session is only invalidated by Scenario Planner's own staleness guard,
    which compares governance_mode and counterfactual_policy_fingerprint -
    not currency context or value mapping. An imported project sharing the
    same counterfactual policy but a different currency/value mapping could
    therefore still show and allow saving the PREVIOUS project's cached
    result under the newly imported one. A project import must clear both -
    session-only cached results are never the system of record (this
    module's own docstring)."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-import-clear"
    at.session_state["constrained_result"] = {"governance_mode": "exploratory"}
    at.session_state["unconstrained_result"] = {"governance_mode": "exploratory"}

    uploader = at.file_uploader[0]
    uploader.set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    assert at.session_state["constrained_result"] is None
    assert at.session_state["unconstrained_result"] is None


def test_export_includes_causal_graph_state(monkeypatch, tmp_path):
    """REQ-GRAPH-001 work package (graph portability): the real "Build
    export bundle" button click carries the project's causal graph state
    into the bundle, via graph_versions_for_export."""
    from ancestry_mmm.core.causal_graph import CausalGraph, CausalNode

    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    graph = CausalGraph(
        graph_id="g1",
        graph_version=1,
        nodes=[
            CausalNode(node_id="tv_spend", role="intervention"),
            CausalNode(node_id="fh_new", role="outcome"),
        ],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-with-graph"
    at.session_state["causal_graph"] = graph.to_dict()
    at.session_state["causal_graph_versions"] = [graph.to_dict()]

    build_button = next(b for b in at.button if b.label == "Build export bundle")
    build_button.click().run()
    assert not at.exception, f"export click raised: {at.exception}"

    bundle_path = tmp_path / "proj-with-graph-readback.zip"
    bundle_path.write_bytes(at.session_state["export_last_bundle_bytes"])
    imported = import_project(bundle_path)
    graphs, warnings = resolve_imported_causal_graphs(imported)
    assert warnings == []
    assert {g["graph_id"] for g in graphs} == {"g1"}


def test_import_restores_causal_graph_history_and_current_graph(monkeypatch, tmp_path):
    """REQ-GRAPH-001 work package (graph portability): the real "Import
    bundle" button click restores every quarantine-checked graph version
    and makes the highest-numbered one current."""
    import dataclasses as dc

    from ancestry_mmm.core.causal_graph import CausalGraph, CausalNode

    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    v1 = CausalGraph(
        graph_id="g1",
        graph_version=1,
        nodes=[
            CausalNode(node_id="tv_spend", role="intervention"),
            CausalNode(node_id="fh_new", role="outcome"),
        ],
    )
    v2 = dc.replace(v1, graph_version=2, status="approved")

    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
        causal_graphs=[v1.to_dict(), v2.to_dict()],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-import-graph"

    uploader = at.file_uploader[0]
    uploader.set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    restored_versions = at.session_state["causal_graph_versions"]
    assert {(g["graph_id"], g["graph_version"]) for g in restored_versions} == {
        ("g1", 1),
        ("g1", 2),
    }
    current = at.session_state["causal_graph"]
    assert current["graph_version"] == 2
    assert current["status"] == "approved"


def test_import_with_no_causal_graphs_leaves_graph_state_empty(monkeypatch, tmp_path):
    """A legacy bundle (or a project with no graph configured) round-trips
    to "no graph", never fabricated evidence."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-no-graph"
    at.session_state["causal_graph"] = {"graph_id": "stale-from-previous-project"}
    at.session_state["causal_graph_versions"] = [{"graph_id": "stale"}]

    uploader = at.file_uploader[0]
    uploader.set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    assert at.session_state["causal_graph_versions"] == []
    assert at.session_state["causal_graph"] is None


def _rewrite_bundle_diagnostics_artefact(
    bundle_path: Path, tmp_path: Path, **overrides
) -> Path:
    """Return a copy of `bundle_path` with config/diagnostics_artefact.json's
    content mutated by `overrides` - simulates a diagnostics artefact that
    has drifted after the readiness proof binding it was computed, without
    touching anything else in the bundle (in particular, leaving the
    already-computed approval_readiness / model_approval / validation_policy
    files exactly as exported)."""
    extract_dir = tmp_path / "bundle-edit"
    with zipfile.ZipFile(bundle_path) as zf:
        zf.extractall(extract_dir)
    artefact_path = extract_dir / "config" / "diagnostics_artefact.json"
    artefact = json.loads(artefact_path.read_text())
    artefact.update(overrides)
    artefact_path.write_text(json.dumps(artefact))
    edited_path = tmp_path / "edited-bundle.zip"
    with zipfile.ZipFile(edited_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in extract_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(extract_dir))
    return edited_path


def test_officially_resumable_message_withheld_when_diagnostics_artefact_has_drifted(
    monkeypatch, tmp_path
):
    """Corrective review finding (P2): audit_project_resumability()'s
    policy-backed-approval check only verifies approval_readiness's own
    recorded fingerprints are internally self-consistent - it cannot also
    recompute a fresh DiagnosticsArtefact fingerprint (an application-layer
    type core must not import), so it reports officially_resumable=True even
    when the bundle's actual diagnostics_artefact content has drifted since
    the readiness proof was computed. Previously the page showed "This
    bundle is officially resumable" from that audit alone; the fuller
    verify_imported_readiness/verify_imported_approval checks further down
    the same script then rejected the readiness and approval, contradicting
    the claim already on screen. The success message must only appear once
    both agree."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    bundle_path = build_lifecycle_project_bundle(tmp_path / "lifecycle-bundle.zip")
    edited_bundle_path = _rewrite_bundle_diagnostics_artefact(
        bundle_path, tmp_path, market_scope="DRIFTED"
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-drifted"

    uploader = at.file_uploader[0]
    uploader.set_value(
        (edited_bundle_path.name, edited_bundle_path.read_bytes(), "application/zip")
    ).run()
    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    assert not any(
        "This bundle is officially resumable" in (s.value or "") for s in at.success
    )
    assert any("not **officially** resumable" in (w.value or "") for w in at.warning)


# Phase 6 of the dashboard UX/UI brief: the shared shell applied to this page,
# an Export & Recovery dashboard that keeps the durable bundle primary, and a
# manifest-driven contents checklist after a real build/import. Presentation
# only - every assertion below reads a value the page derives from session
# state or from the bundle's own manifest.json, never a new computation.


def test_session_state_not_durable_banner_and_empty_project_status(
    monkeypatch, tmp_path
):
    """Before any build/import, the recovery dashboard reports no activity
    and keeps the durable bundle visibly ahead of secondary outputs."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    assert any("Export & Recovery dashboard" in (m.value or "") for m in at.markdown)
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Primary recovery object"] == "Durable bundle"
    assert metrics["Bundle activity"] == "Not started"
    assert metrics["Secondary outputs"] == "Report only"
    assert any(
        "No bundle has been built yet this session" in (c.value or "")
        for c in at.caption
    )
    assert any(
        "No bundle has been imported yet this session" in (c.value or "")
        for c in at.caption
    )
    visible_copy = " ".join(
        (element.value or "") for element in [*at.caption, *at.markdown]
    )
    assert "Activity taxonomy entries saved" in visible_copy
    assert "Legacy curve bank entries" not in visible_copy
    assert "logical-domain" not in visible_copy
    # Header readiness badge matches the sidebar's own readiness vocabulary
    # for this page (ancestry_mmm.components.page_readiness("export")) - no
    # data loaded yet, so "not_started".
    assert any("Not started" in (m.value or "") for m in at.markdown)


def test_build_bundle_updates_project_status_and_shows_included_checklist(
    monkeypatch, tmp_path
):
    """A real "Build export bundle" click records this session's bundle
    activity (for the "Project status" panel) and shows a checklist of
    what the bundle actually contains, read back from the bundle's own
    manifest.json rather than re-derived - so it can never disagree with
    what import_project() itself reports for the same bundle.

    Pass 4 redesign (closing the gap passes 2-3 identified but deliberately
    left unfixed): the checklist and download button are now rendered from
    the already-persisted `export_last_bundle_summary` state, not from the
    button's own transient scope - this test proves both (a) they appear
    immediately after the build (the original working behaviour, still
    intact) and (b) they survive a later, unrelated rerun instead of
    vanishing (the actual regression fix - previously this exact rerun
    would have made the download button disappear until the analyst
    clicked "Build export bundle" again)."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"

    at.session_state["project_name"] = "proj-status"
    build_button = next(b for b in at.button if b.label == "Build export bundle")
    build_button.click().run()
    assert not at.exception, f"export click raised: {at.exception}"

    summary = at.session_state["export_last_bundle_summary"]
    assert summary["project_name"] == "proj-status"
    assert summary["checkpoint"] == "uploaded"  # nothing fitted/approved in this test
    assert summary["built_at"]

    assert any("What's included in this bundle" in e.label for e in at.expander), (
        "the manifest-driven checklist expander must be present after a real build"
    )
    checklist_copy = " ".join(
        (element.value or "") for element in [*at.caption, *at.markdown]
    )
    assert "Original source files and tables" in checklist_copy
    assert "Coverage and frequency review history" in checklist_copy
    assert any(
        d.label == "Download project bundle (.zip)" for d in at.download_button
    ), "the download control must be present immediately after a real build"

    # A fresh, unrelated rerun (e.g. the analyst's next interaction, or
    # simply revisiting the page) must NOT re-click the button (so it must
    # not rebuild the bundle), reflects the updated activity in the
    # "Project status" panel, AND - the actual regression this redesign
    # fixes - must still show the checklist and a working download button,
    # since both are now derived from persisted state rather than the
    # button's own transient scope.
    at.run()
    assert not at.exception, f"follow-up rerun raised: {at.exception}"
    assert any("Last bundle built this session" in (c.value or "") for c in at.caption)
    assert any("proj-status" in (c.value or "") for c in at.caption)
    assert any("What's included in this bundle" in e.label for e in at.expander), (
        "the checklist must still be present after an unrelated rerun, not just "
        "immediately after the click"
    )
    assert any(
        d.label == "Download project bundle (.zip)" for d in at.download_button
    ), (
        "the download control must still be present (and usable) after an unrelated rerun"
    )

    # A second, unrelated rerun again - proves this is stable, not a
    # one-off artefact of exactly one extra rerun, and that re-reading the
    # manifest/file from disk on every render does not itself raise or
    # regress anything.
    at.run()
    assert not at.exception, f"second follow-up rerun raised: {at.exception}"
    assert any(
        d.label == "Download project bundle (.zip)" for d in at.download_button
    ), "the download control must remain usable across repeated reruns"


def test_build_bundle_download_degrades_gracefully_when_session_bytes_are_lost(
    monkeypatch, tmp_path
):
    """Pass-4 originally re-read the bundle from
    `PROJECT_EXPORT_ROOT/<project_name>.zip` on every rerun; Codex review on
    PR #348 (P1) flagged that as a cross-session data leak, since that path
    is shared filesystem state, not session-scoped - a second session
    building the same-named project in between could silently overwrite it,
    and this session would then read and offer *that* session's bundle for
    download. Fixed by caching the built bytes/manifest in this session's own
    private `st.session_state` at build time and never re-opening the shared
    path afterwards.

    This test proves the resulting degrade-gracefully behaviour for the
    realistic case that replaces "the shared file was deleted": this
    session's own cached bytes are gone (e.g. a full app/server restart,
    which clears `st.session_state`) - not a crash, not a stale/foreign
    bundle, just a clear message - while the session's own record of having
    built a bundle is not erased just because the in-memory bytes are gone.
    """
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    at.session_state["project_name"] = "proj-deleted"
    build_button = next(b for b in at.button if b.label == "Build export bundle")
    build_button.click().run()
    assert not at.exception, f"export click raised: {at.exception}"
    assert at.session_state["export_last_bundle_bytes"], (
        "the build must cache this session's own bundle bytes privately"
    )

    # Simulate this session's cached bytes being gone (e.g. a server
    # restart) without touching any shared filesystem path - the bug this
    # test now guards against was specifically about that shared path, so a
    # correct fix must not depend on it at all any more.
    del at.session_state["export_last_bundle_bytes"]
    del at.session_state["export_last_bundle_manifest"]

    at.run()
    assert not at.exception, f"rerun after losing session bytes raised: {at.exception}"
    assert not any(
        d.label == "Download project bundle (.zip)" for d in at.download_button
    ), "no download control should be offered once this session's bytes are gone"
    assert any(
        "no longer available in memory" in (w.value or "") for w in at.warning
    ), "a clear, actionable message must explain why the download is unavailable"
    # The session's own record of having built a bundle is not erased just
    # because the in-memory bytes were lost - it stays an honest log.
    assert any("Last bundle built this session" in (c.value or "") for c in at.caption)
    assert any("proj-deleted" in (c.value or "") for c in at.caption)


def test_build_bundle_download_is_isolated_from_a_shared_project_name_being_overwritten(
    monkeypatch, tmp_path
):
    """Codex review on PR #348 (P1): reproduce the actual multi-session leak
    scenario directly, not just the degrade-gracefully path. Two sessions
    build a project under the same name (a realistic default/duplicate
    project name in a multi-user deployment); the second session's build
    overwrites the first session's file on the shared
    `PROJECT_EXPORT_ROOT/<project_name>.zip` path. The first session's next
    rerun must still offer *its own* bundle for download, never the second
    session's, because it must not depend on that shared path at all any
    more."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    session_a = AppTest.from_file(str(PAGE), default_timeout=60)
    session_a.run()
    session_a.session_state["project_name"] = "shared-name"
    session_a.session_state["project_notes"] = "session-a-marker"
    build_a = next(b for b in session_a.button if b.label == "Build export bundle")
    build_a.click().run()
    assert not session_a.exception, (
        f"session A export click raised: {session_a.exception}"
    )
    bytes_a = session_a.session_state["export_last_bundle_bytes"]

    # A second, independent session (a different analyst, or the same
    # analyst in another tab) builds a project under the identical name,
    # overwriting the shared on-disk file session A's old code would have
    # re-read from.
    session_b = AppTest.from_file(str(PAGE), default_timeout=60)
    session_b.run()
    session_b.session_state["project_name"] = "shared-name"
    session_b.session_state["project_notes"] = "session-b-marker"
    build_b = next(b for b in session_b.button if b.label == "Build export bundle")
    build_b.click().run()
    assert not session_b.exception, (
        f"session B export click raised: {session_b.exception}"
    )
    bytes_b = session_b.session_state["export_last_bundle_bytes"]
    assert bytes_a != bytes_b, (
        "test setup sanity check: the two sessions' bundles must actually differ"
    )

    # Codex review follow-up (PR #348, P1): "fresh evidence beyond the
    # earlier comment is that this revision only isolates the bytes after
    # the shared-path write has completed... [and] does not cover this
    # write/read race" - true of running the two builds strictly
    # sequentially (as the AppTest calls above do; genuinely concurrent
    # writes aren't reliably reproducible in a synchronous unit test). The
    # deterministic property this second fix actually provides - and that a
    # sequential test *can* prove - is structural, not timing-dependent:
    # each build now writes to a session-unique temporary filename, so two
    # sessions building "shared-name" can never target the same path at all,
    # racing or not. Confirmed directly: the shared canonical path was never
    # written to by either build, and neither build leaves a temp file
    # behind (each session's own bytes/manifest were already cached in
    # memory and the on-disk temp file deleted before this assertion).
    shared_canonical_path = export_root / "shared-name.zip"
    assert not shared_canonical_path.exists(), (
        "no build should ever write to the shared project-name path - each "
        "build must use a session-unique filename instead"
    )
    leftover_files = sorted(p.name for p in export_root.glob("*.zip"))
    assert leftover_files == [], (
        "each build's temporary file must be deleted once its bytes/manifest "
        f"are cached, not left on disk to accumulate or collide; found: {leftover_files}"
    )

    # Session A's next, unrelated rerun (its actual regression-fix scenario)
    # must still serve session A's own bytes, not session B's, even though
    # the shared filesystem path now holds session B's file.
    session_a.run()
    assert not session_a.exception, (
        f"session A follow-up rerun raised: {session_a.exception}"
    )
    assert session_a.session_state["export_last_bundle_bytes"] == bytes_a, (
        "session A's cached bundle bytes must never be affected by another "
        "session's build under the same project name"
    )
    assert any(
        d.label == "Download project bundle (.zip)" for d in session_a.download_button
    ), "session A's download control must still be present after its follow-up rerun"
    # `st.download_button`'s underlying bytes are not introspectable via
    # AppTest's DownloadButton element (it exposes only label/help/value),
    # so the strongest available proof that session A is offered its own
    # bundle - not session B's, silently substituted via the shared on-disk
    # path - is that the exact session-private state the widget is built
    # from (asserted above) is untouched by session B's build.


def test_import_bundle_updates_project_status_and_shows_included_checklist(
    monkeypatch, tmp_path
):
    """A real "Import bundle" click records this session's import activity
    and shows what the imported bundle actually contained, read from the
    same manifest.json import_project() already parsed - not a second,
    possibly-drifting notion of bundle contents."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    bundle_path = export_project(
        tmp_path / "bundle.zip",
        raw_sources={},
        transformed_data=None,
        pipeline_steps=[],
        model_spec=None,
        prior_config=None,
        dna_lag_weeks=0,
        trace=None,
        scenarios=[],
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-import-status"

    uploader = at.file_uploader[0]
    uploader.set_value(
        (bundle_path.name, bundle_path.read_bytes(), "application/zip")
    ).run()
    import_button = next(b for b in at.button if b.label == "Import bundle")
    import_button.click().run()
    assert not at.exception, f"import click raised: {at.exception}"

    summary = at.session_state["export_last_import_summary"]
    assert summary["bundle_name"] == bundle_path.name
    assert summary["imported_at"]

    assert any(
        "What was included in the imported bundle" in e.label for e in at.expander
    ), "the manifest-driven checklist expander must be present after a real import"

    at.run()
    assert not at.exception, f"follow-up rerun raised: {at.exception}"
    assert any(
        "Last bundle imported this session" in (c.value or "") for c in at.caption
    )
    assert any(bundle_path.name in (c.value or "") for c in at.caption)


def test_project_status_reflects_curve_bank_and_official_artifact_counts(
    monkeypatch, tmp_path
):
    """The "Project status" panel's curve bank / official curve artifact
    counts come from the same single top-of-page reads the Excel/report
    builders further down the page reuse (no duplicated disk read, no
    second notion of "how many artifacts exist") - proven here by writing
    one official artifact to disk and confirming the panel reflects it."""
    export_root = tmp_path / "exports"
    artifact_root = tmp_path / "artifact-root"

    import ancestry_mmm.utils as utils_pkg
    import ancestry_mmm.utils.session_state as ss

    monkeypatch.setattr(utils_pkg, "PROJECT_EXPORT_ROOT", export_root)
    monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"initial load raised: {at.exception}"
    at.session_state["project_name"] = "proj-artifact-status"
    _write_official_artifact(artifact_root / "proj-artifact-status", "art-status-1")

    at.run()
    assert not at.exception, f"rerun after writing artifact raised: {at.exception}"
    assert any("Saved Planning Curves: 1" in (c.value or "") for c in at.caption)
