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

    return export_root / f"{project_name}.zip"


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

    imported = import_project(export_root / "proj-legacy.zip")
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
    assert any(
        "Restored 2 official curve artifact(s)" in (s.value or "") for s in at.success
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

    imported = import_project(export_root / "proj-with-graph.zip")
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
