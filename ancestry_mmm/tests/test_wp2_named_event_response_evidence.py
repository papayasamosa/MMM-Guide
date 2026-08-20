"""Anti-drift conformance tests for the WP2 named-event response
evidence package (`scripts/wp2_named_event_response/`,
`docs/wp2_named_event_response_evidence.md`,
`docs/wp2_named_event_response_results.json`).

Decision support only: these tests assert the evidence is recorded
honestly and stays out of production - they never run MCMC and never
assert any candidate "won".
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVIDENCE_PATH = REPO_ROOT / "docs" / "wp2_named_event_response_evidence.md"
RESULTS_PATH = REPO_ROOT / "docs" / "wp2_named_event_response_results.json"
DECISION_PACKAGE_PATH = (
    REPO_ROOT / "docs" / "wp2_named_event_statistical_method_decision_package.md"
)
EVALUATION_DIR = REPO_ROOT / "scripts" / "wp2_named_event_response"

EXPECTED_CANDIDATES = (
    "S1_fixed_profile",
    "S2_parametric",
    "S3_spline_basis",
    "S4_dummies",
    "S5_pooled_basis",
)

EXPECTED_SCENARIOS = (
    "contemporaneous",
    "anticipatory",
    "post_event",
    "anticipatory_and_post_event",
    "event_plus_promotion",
    "event_plus_media_burst",
    "event_plus_seasonal_peak",
    "sparse_repeats",
    "multi_market",
)


def _load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text())


def test_evidence_document_exists_and_selects_no_candidate():
    assert EVIDENCE_PATH.exists()
    content = EVIDENCE_PATH.read_text()
    flattened = " ".join(content.split())
    assert "Decision support only" in flattened
    assert "enabled, selected, or implemented" in flattened
    for phrase in (
        "No statistical response method is approved",
        "workflow",
        "PyMC 5.28.5",
        "PyTensor 2.38.3",
        "ArviZ 0.23.4",
    ):
        assert phrase.lower() in flattened.lower(), f"evidence doc missing: {phrase}"


def test_results_json_exists_with_versions():
    data = _load_results()
    assert set(data["versions"]) >= {
        "python",
        "pymc",
        "pytensor",
        "arviz",
        "numpy",
        "scipy",
    }


def test_main_grid_is_complete():
    """Every single-market scenario x S1-S4 combination must be recorded
    in the main grid - a silently dropped fit would hide a missing
    measurement."""
    data = _load_results()
    main = [
        r
        for r in data["results"]
        if r["run"] == "main" and r["scenario"] != "multi_market"
    ]
    pairs = {(r["scenario"], r["candidate"]) for r in main}
    for scenario in EXPECTED_SCENARIOS:
        if scenario == "multi_market":
            continue
        for candidate in EXPECTED_CANDIDATES[:4]:
            assert (scenario, candidate) in pairs, (
                f"main grid missing ({scenario}, {candidate})"
            )


def test_multi_market_and_sensitivity_runs_recorded():
    data = _load_results()
    runs = {(r["run"], r["scenario"], r["candidate"]) for r in data["results"]}
    for candidate in EXPECTED_CANDIDATES[:4]:
        assert ("multi_market_shared", "multi_market", candidate) in runs
    assert ("multi_market_model_c", "multi_market", "S2_parametric") in runs
    assert ("multi_market_model_c", "multi_market", "S5_pooled_basis") in runs
    assert ("sensitivity_wrong_window", "anticipatory", "S2_parametric") in runs
    assert ("sensitivity_oracle_fixed", "anticipatory", "S1_fixed_profile") in runs
    assert ("sensitivity_wide_prior", "anticipatory", "S2_parametric") in runs
    for candidate in EXPECTED_CANDIDATES[:4]:
        assert ("holdout", "anticipatory", candidate) in runs


def test_every_record_has_metrics_keys_or_an_error():
    data = _load_results()
    for record in data["results"]:
        metrics = record["metrics"]
        if metrics.get("status") == "failed":
            assert isinstance(metrics.get("error"), str) and metrics["error"]
        else:
            for key in ("status", "runtime_s", "event_rmse"):
                assert key in metrics, f"record missing {key!r}: {record}"
            assert isinstance(metrics["runtime_s"], float)


def test_evaluation_code_is_not_importable_from_production():
    """The evaluation package must stay out of the application - no
    module under `ancestry_mmm/` may import it."""
    import subprocess
    import sys

    hits = []
    for py_file in (REPO_ROOT / "ancestry_mmm").rglob("*.py"):
        if "tests" in py_file.parts:
            continue  # tests may legitimately reference the package by name
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if "wp2_named_event_response" in text:
            hits.append(str(py_file))
    assert not hits, f"production modules reference the evaluation code: {hits}"
    # Also: importing the evaluation package must not import ancestry_mmm.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, 'scripts'); "
            "import wp2_named_event_response; "
            "import sys as s; "
            "assert not any(m.startswith('ancestry_mmm') for m in s.modules)",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr


def test_evaluation_models_compile():
    """Every candidate model graph must build and prior-sample cleanly
    (no MCMC) - a broken graph in the schedule-only evidence job would
    otherwise only surface when a human next dispatches it."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.wp2_named_event_response.validate_builds",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, (
        f"evaluation model build validation failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "all builds ok" in result.stdout


def test_decision_package_points_at_the_evidence_doc():
    content = DECISION_PACKAGE_PATH.read_text()
    assert "wp2_named_event_response_evidence.md" in content


def test_merge_gate_allows_the_new_skipped_check():
    script = (REPO_ROOT / "scripts" / "wait_for_pr_green_then_merge.ps1").read_text()
    assert "Named-event response evidence" in script
