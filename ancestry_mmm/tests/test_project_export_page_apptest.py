"""AppTest coverage for PR 96B: 09_Project_Export.py's official curve
artifact store portability.

Focuses on the export-side checkpoint computation (reachable via a real
button click without a fitted model) - the riskiest UI change in this PR,
since it determines whether a bundle is later recognised as having reached
the distinct `official_curves` checkpoint versus falling back to `curves`
(the legacy parameter-snapshot checkpoint) or an earlier one.

The import side (file upload) and the Excel/report buttons (which require a
fitted model in session state) are not driven through the UI here - Streamlit
AppTest has no API for simulating `st.file_uploader` input, and the
export/import/checkpoint/report-row logic itself is already covered
end-to-end at the core/application layer in test_persistence.py,
test_project_service.py, test_curve_service.py, and test_report.py. This
file's job is only to confirm the page wiring (the new
`curve_artifact_store_source_dir=`/checkpoint-expression additions) actually
fires when a real button is clicked.
"""

import dataclasses
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.curve_artifact import (
    CurveArtifactMetadata,
    compute_curve_artifact_fingerprints,
    write_curve_artifact,
)
from ancestry_mmm.core.persistence import import_project

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
