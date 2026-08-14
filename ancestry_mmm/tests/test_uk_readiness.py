"""WP5 tests for the metadata-only UK lifecycle readiness harness."""

from __future__ import annotations

import json
import ntpath
from pathlib import Path

import pytest

from ancestry_mmm.application.uk_readiness import (
    ReadinessInputError,
    ensure_d_drive_path,
    run_uk_readiness,
)
from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    DOMAIN_OUTCOMES,
)
from ancestry_mmm.data.template_downloads import build_standard_template
from ancestry_mmm.tests.support.lifecycle_fixture import build_lifecycle_project_bundle


def _stage(report, name: str):
    return next(stage for stage in report.stages if stage.name == name)


def test_d_drive_guard_rejects_relative_and_non_d_paths() -> None:
    accepted = ensure_d_drive_path(
        r"D:\Ancestry-MMM\test artifacts\uk-readiness", label="output"
    )
    assert ntpath.splitdrive(str(accepted))[0].upper() == "D:"

    with pytest.raises(ReadinessInputError, match="absolute D-drive"):
        ensure_d_drive_path(r"C:\Ancestry-MMM\test-artifacts", label="output")
    with pytest.raises(ReadinessInputError, match="absolute D-drive"):
        ensure_d_drive_path(r"..\test-artifacts\uk-readiness", label="output")
    with pytest.raises(ReadinessInputError, match="absolute D-drive"):
        ensure_d_drive_path(r"D:relative\test-artifacts", label="output")


def test_synthetic_pass_exercises_existing_lifecycle_without_source_rows(
    tmp_path: Path,
) -> None:
    report = run_uk_readiness(
        synthetic_case="pass",
        output_dir=tmp_path,
        enforce_d_drive=False,
        lifecycle_bundle_builder=build_lifecycle_project_bundle,
    )

    assert report.status == "pass"
    assert _stage(report, "calendar_coverage_preparation").status == "pass"
    assert _stage(report, "engine_capability").status == "pass"
    assert _stage(report, "model_preparation_and_fit").status == "pass"
    assert _stage(report, "validation_and_approval").status == "pass"
    assert _stage(report, "curve_generation_eligibility").status == "pass"
    assert _stage(report, "scenario_planning_eligibility").status == "pass"
    assert _stage(report, "project_import_resumability").status == "pass"
    assert _stage(report, "synthetic_deterministic_lifecycle").status == "pass"

    report_path = Path(report.report_path or "")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert "1000.0" not in report_path.read_text(encoding="utf-8")
    assert "source_rows" not in payload


def test_mixed_frequency_stops_without_conversion(tmp_path: Path) -> None:
    report = run_uk_readiness(
        synthetic_case="mixed_frequency",
        output_dir=tmp_path,
        enforce_d_drive=False,
        lifecycle_bundle_builder=build_lifecycle_project_bundle,
    )

    assert report.status == "unsupported"
    stage = _stage(report, "calendar_coverage_preparation")
    assert stage.status == "unsupported"
    assert stage.details["conversion_performed"] is False
    assert stage.details["native_data_preserved"] is True
    assert not any(
        item.name == "synthetic_deterministic_lifecycle" and item.status == "pass"
        for item in report.stages
    )


def test_coverage_gap_is_decision_required_and_not_inferred(tmp_path: Path) -> None:
    report = run_uk_readiness(
        synthetic_case="coverage_gap",
        output_dir=tmp_path,
        enforce_d_drive=False,
        lifecycle_bundle_builder=build_lifecycle_project_bundle,
    )

    assert report.status == "decision_required"
    stage = _stage(report, "calendar_coverage_preparation")
    assert stage.status == "decision_required"
    assert stage.details["ready"] is False
    assert any(
        "coverage" in decision.lower()
        for decision in stage.details["decisions_required"]
    )


def test_local_source_paths_report_identity_but_do_not_claim_a_fit(
    tmp_path: Path,
) -> None:
    domains = (
        DOMAIN_OUTCOMES,
        DOMAIN_ACTIVITY_AND_MEDIA,
        DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
        DOMAIN_EXPERIMENT_EVIDENCE,
    )
    source_paths: list[tuple[str, Path]] = []
    for domain in domains:
        path = tmp_path / f"source pack {domain}.xlsx"
        path.write_bytes(build_standard_template(domain))
        source_paths.append((domain, path))

    report = run_uk_readiness(
        source_paths=source_paths,
        output_dir=tmp_path / "readiness-output",
        enforce_d_drive=False,
        governed_start="2026-01-05",
        governed_end="2026-01-12",
        governed_frequency="weekly",
    )

    assert report.status == "decision_required"
    assert _stage(report, "source_version_identity").status == "pass"
    assert _stage(report, "calendar_coverage_preparation").status == "pass"
    assert _stage(report, "model_preparation_and_fit").status == "decision_required"
    assert _stage(report, "governance_readiness").status == "decision_required"
