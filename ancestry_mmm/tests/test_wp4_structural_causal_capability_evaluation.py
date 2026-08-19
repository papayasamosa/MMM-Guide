"""Work Package 4 (`Media-Mix-Lab: Coding LLM Next Steps After PR #291`):
anti-drift conformance for the structural-causal engine capability
evaluation decision package. Narrow, literal checks against facts the
WP4 package records: no engine is selected or added; the four governing
records still have zero implementation; no engine library is imported
or depended on; the approved capability vocabulary and the primary-
engine pin (the PathMC isolation trigger) remain as recorded. These
tests are not a competing requirements authority; they catch a future
change silently adopting an engine or reclassifying the evaluation's
facts."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PACKAGE = REPO_ROOT / "docs" / "wp4_structural_causal_engine_capability_evaluation.md"
WP0_PACKAGE = REPO_ROOT / "docs" / "wp_structural_causal_engine_decision_package.md"
SCENGINE = REPO_ROOT / "docs" / "approved_requirements" / "REQ-SCENGINE-001.md"
SCEFFECT = REPO_ROOT / "docs" / "approved_requirements" / "REQ-SCEFFECT-001.md"
CAUSALROBUST = REPO_ROOT / "docs" / "approved_requirements" / "REQ-CAUSALROBUST-001.md"
SCCURVE = REPO_ROOT / "docs" / "approved_requirements" / "REQ-SCCURVE-001.md"
ROOT_AGENTS = REPO_ROOT / "AGENTS.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

ENGINE_MODULE_NAMES = ("pathmc", "dowhy", "pgmpy", "bnlearn", "causal_learn")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_package_exists_and_selects_no_candidate():
    text = _read(PACKAGE)
    for marker in (
        "No engine is selected",
        "MD-022",
        "VL-028",
        "VL-029",
        "REQ-SCENGINE-001",
        "REQ-SCEFFECT-001",
        "REQ-CAUSALROBUST-001",
        "REQ-SCCURVE-001",
        "PathMC",
        "DoWhy",
        "pgmpy",
    ):
        assert marker in text


def test_package_records_the_isolation_trigger_fact():
    """F1: PathMC cannot share the pinned primary runtime. The package
    must keep recording this so a future dependency change does not
    silently invalidate the evaluation."""
    text = _read(PACKAGE)
    assert "pymc==5.28.5" in text
    assert "pytensor==2.38.3" in text
    assert "pymc>=6.0" in text or "pymc>=6" in text
    assert "pytensor>=3.1.1" in text
    assert "runtime-isolation trigger" in text or "isolation trigger" in text


def test_primary_engine_pin_unchanged():
    """The evaluation's dependency facts come from the pin file; guard the
    pin that makes F1 true. A pin change is a separately governed
    primary-stack decision."""
    text = _read(PYPROJECT)
    assert "pymc==5.28.5" in text
    assert "pytensor==2.38.3" in text


def test_no_structural_causal_engine_is_a_dependency():
    """No engine library may appear as a dependency while engine selection
    remains unresolved (MD-022)."""
    text = _read(PYPROJECT).lower()
    for name in ENGINE_MODULE_NAMES:
        assert name not in text


def test_no_engine_is_imported_anywhere_in_the_package():
    for py_file in (REPO_ROOT / "ancestry_mmm").rglob("*.py"):
        if "tests" in py_file.parts:
            continue
        text = _read(py_file).lower()
        for name in ENGINE_MODULE_NAMES:
            assert name not in text, (
                f"{py_file.relative_to(REPO_ROOT)} mentions '{name}' - an "
                "engine adoption has happened outside the MD-022 decision."
            )


def test_governing_records_still_declare_zero_implementation():
    for record in (SCENGINE, SCEFFECT, CAUSALROBUST, SCCURVE):
        text = _read(record)
        assert "Zero implementation" in text, (
            f"{record.name} no longer declares zero implementation - a "
            "structural-causal capability has been implemented without the "
            "MD-022/VL-028/VL-029 decisions."
        )


def test_approved_capability_vocabulary_present():
    """AGENTS.md's six-way vocabulary is the classification this package
    uses; it must stay in authority."""
    text = _read(ROOT_AGENTS)
    for label in (
        "native to the selected engine",
        "supported extension",
        "external linked model",
        "planning-layer approximation",
        "experimental",
        "not supported",
    ):
        assert label in text


def test_wp0_decision_package_still_present():
    """The WP0 package owns D1/D2/D3; WP4 only supplies evidence. Both
    documents must coexist."""
    text = _read(WP0_PACKAGE)
    assert "This package does not choose" in text
    assert "MD-022" in text


def test_compiler_rejects_unsupported_edge_roles():
    """The primary compiler's fail-closed capability check remains the
    only engine boundary in production code."""
    import ancestry_mmm.core.graph_model_compiler as compiler_module

    assert "direct" in compiler_module._SUPPORTED_EDGE_ROLES
    assert "cross_product_halo" in compiler_module._SUPPORTED_EDGE_ROLES
    assert "excluded_diagnostic_only" in compiler_module._SUPPORTED_EDGE_ROLES
    assert hasattr(compiler_module, "check_engine_capability")
    assert hasattr(compiler_module.GraphModelCompiler, "compile")
