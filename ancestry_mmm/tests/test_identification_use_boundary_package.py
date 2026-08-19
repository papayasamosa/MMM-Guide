"""Work Package 3 (`Media-Mix-Lab: Coding LLM Next Steps After PR #291`):
anti-drift conformance for the identification/latent-state use-boundary
determination. These are narrow, literal checks against facts the WP3
decision package records - the compiler has no adjustment-set surface, the
back-door assessor is diagnostics-only, Requirement 5 / Requirement 3
remain deferred, and VL-026 / MD-021 remain open. They are not a competing
requirements authority; they catch a future change silently reclassifying
an unresolved decision as implemented."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PACKAGE = REPO_ROOT / "docs" / "wp3_identification_use_boundary_decision_package.md"
IDENT_RECORD = REPO_ROOT / "docs" / "approved_requirements" / "REQ-IDENT-001.md"
LATENT_RECORD = REPO_ROOT / "docs" / "approved_requirements" / "REQ-LATENT-001.md"
COMPILER = REPO_ROOT / "ancestry_mmm" / "core" / "graph_model_compiler.py"
IDENT_CHECKER = REPO_ROOT / "ancestry_mmm" / "core" / "estimand_identification.py"
LATENT_MODULE = REPO_ROOT / "ancestry_mmm" / "core" / "latent_state_identification.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_decision_package_exists_and_states_the_blocking_decisions():
    text = _read(PACKAGE)
    # The marker sentence may wrap across lines - assert its words, not one
    # exact single-line string.
    assert "No candidate in this package is" in text
    assert "selected." in text
    assert "VL-026" in text
    assert "MD-021" in text
    assert "Requirement 5" in text
    assert "Requirement 3" in text


def test_records_still_mark_the_compiler_extensions_deferred():
    ident = _read(IDENT_RECORD)
    assert "Not yet implemented: Requirement 5" in ident
    assert "deferred" in ident.lower()
    latent = _read(LATENT_RECORD)
    assert "Not yet implemented: Requirement 3" in latent


def test_compiler_takes_no_adjustment_set_input():
    """The WP3 mechanical determination: compilation never receives a
    conditioning set, so REQ-IDENT-001 Requirement 5 has no surface to
    fire on until the VL-026 decision lands. Guard the fact itself, not
    prose about it."""
    compiler = _read(COMPILER)
    assert "adjustment" not in compiler.lower()
    assert "estimand_identification" not in compiler
    assert "LatentStateIdentification" not in compiler
    # The compile entry point is the graph and nothing else.
    assert (
        "def compile(self, graph: CausalGraph) -> GraphCompilationResult:" in compiler
    )


def test_backdoor_assessor_has_no_official_use_consumer():
    """`assess_backdoor_identification` is diagnostics-only today - no
    official artefact builder imports it. If that changes, the VL-026
    "when mandatory" decision must exist first."""
    checker = _read(IDENT_CHECKER)
    assert "def assess_backdoor_identification" in checker
    for py_file in (REPO_ROOT / "ancestry_mmm").rglob("*.py"):
        if py_file.name == "estimand_identification.py":
            continue
        text = _read(py_file)
        if "assess_backdoor_identification" in text:
            assert py_file.name == "diagnostics_service.py" or "test" in py_file.name, (
                f"{py_file} consumes assess_backdoor_identification outside "
                "Diagnostics - an official-use boundary now exists, which "
                "requires the VL-026 decision before wiring."
            )


def test_latent_use_eligibility_gate_exists_and_fails_closed():
    """REQ-LATENT-001 Requirement 5's approved gate exists; the only
    latent state's official use is blocked upstream (Candidate A replay
    boundary). The gate must remain present and fail-closed."""
    text = _read(LATENT_MODULE)
    assert "def is_eligible_for_official_use" in text
    assert "only `identified` is eligible" in text or "identified" in text
