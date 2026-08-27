"""Work Package 2 (2026-08-27): lightweight CI coverage for the
decision-critical/evidence scripts under `scripts/`.

Before this package, `scripts/*.py` sat entirely outside the normal
Python lint/compile gates (`Ruff`/`Compile + Import` targeted
`ancestry_mmm` only) - real drift went undetected until someone tried to
run a script. This package found and fixed two genuine defects that
exact way: `scripts/run_historical_mmm_validation.py` imported
`GOVERNED_START`/`GOVERNED_END` from `scripts.run_uk_production_fit`,
names that script had since renamed to `COMMON_WINDOW_START`/
`COMMON_WINDOW_END` - a broken import that made the whole script
uninvokable; and three scripts (`resolve_search_spend_coverage.py`,
`run_historical_mmm_remediation.py`, `run_uk_transform_identifiability_
experiment.py`) were missing the `sys.path` shim every other script here
already carries, so `python scripts/<name>.py` (the exact invocation
style this repository already uses elsewhere, e.g. `run_uk_readiness.py`
in `.github/workflows/tests.yml`) would fail with `ModuleNotFoundError:
No module named 'ancestry_mmm'`.

This module does not run real Ancestry data, real MCMC, or any expensive
fit - see `docs/decision_critical_scripts_inventory.md` for the boundary
between this lightweight coverage, the ordinary `ancestry_mmm` package
CI, and the separate expensive scheduled/manual recovery evidence jobs
(`candidate-a-recovery`, `fold-refit-recovery`,
`named-event-response-recovery`) - none of which this package touches.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"


def _discover_top_level_scripts() -> list[Path]:
    # Only scripts/*.py directly - scripts/wp2_named_event_response/ is
    # its own dedicated evidence package with its own existing coverage
    # (ancestry_mmm/tests/test_wp2_named_event_response_evidence.py, the
    # scheduled `named-event-response-recovery` job) - not duplicated here.
    return sorted(SCRIPTS_DIR.glob("*.py"))


SCRIPT_PATHS = _discover_top_level_scripts()

# Scripts still actively reused - either as ongoing operational
# infrastructure (the production fit runner, the pre-fit/readiness
# governance runners, the WP1 preflight tools) or for the still-open
# WP2.11 hierarchy decision (the H1/H2 full-posterior fit scripts, the
# prepared-frame backtest script) - see docs/decision_critical_scripts_
# inventory.md for the full classification and reasoning. These get an
# additional real CLI smoke test below; every script (reusable or
# historical) already gets the cheaper import-only check.
REUSABLE_OPERATIONAL_SCRIPT_NAMES = frozenset(
    {
        "resolve_search_spend_coverage.py",
        "run_historical_mmm_remediation.py",
        "run_historical_mmm_validation.py",
        "run_uk_prefit_governance.py",
        "run_uk_production_fit.py",
        "run_uk_readiness.py",
        "run_uk_source_model_preflight.py",
        "run_uk_transform_identifiability_experiment.py",
        "run_uk_wp2_11_h1_complete_pooling.py",
        "run_uk_wp2_11_h2_shared_pooling_scale.py",
        "run_uk_wp2_11_prepared_frame_backtest.py",
    }
)


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_discovered_scripts_is_non_empty() -> None:
    """Anti-drift guard: if the `scripts/*.py` glob itself breaks (e.g. a
    directory-structure change), this fails loudly instead of the
    parametrized tests below silently collecting zero cases."""
    assert len(SCRIPT_PATHS) >= 20


def test_every_reusable_operational_script_name_exists_on_disk() -> None:
    """Anti-drift guard: if a reusable script is renamed or removed, this
    inventory (and the CLI smoke-test coverage below) must be updated in
    the same PR - never silently left pointing at a script that no longer
    exists."""
    actual_names = {p.name for p in SCRIPT_PATHS}
    missing = REUSABLE_OPERATIONAL_SCRIPT_NAMES - actual_names
    assert not missing, (
        f"Listed in REUSABLE_OPERATIONAL_SCRIPT_NAMES but missing from "
        f"scripts/: {sorted(missing)}"
    )


@pytest.mark.parametrize("script_path", SCRIPT_PATHS, ids=lambda p: p.name)
def test_script_imports_without_error(script_path: Path) -> None:
    """Every `scripts/*.py` file must import cleanly at module level - no
    PyMC model is built and no data is loaded merely by importing (`main`
    only ever runs behind `if __name__ == "__main__":`). Catches a broken
    symbol reference (an upstream rename never propagated, exactly the
    `GOVERNED_START`/`GOVERNED_END` defect this package fixed), a missing
    dependency, or a syntax error - before it is discovered only when
    someone tries to actually run the script."""
    _load_module(script_path)


@pytest.mark.parametrize("script_name", sorted(REUSABLE_OPERATIONAL_SCRIPT_NAMES))
def test_reusable_operational_script_help_exits_cleanly(script_name: str) -> None:
    """Reusable/decision-critical scripts additionally get a real
    subprocess CLI smoke test: `--help` must exit 0 without needing real
    data, a real fit, or any network access. Catches an argparse contract
    break a pure import cannot see (e.g. a required positional argument
    silently added, breaking every existing caller's invocation) - and is
    exactly the check that would have caught the missing-`sys.path`-shim
    defect this package fixed (a pure in-process import via
    `importlib.util.spec_from_file_location` does not exercise the same
    `python scripts/<name>.py` invocation path a real caller uses)."""
    script_path = SCRIPTS_DIR / script_name
    assert script_path.exists(), f"{script_name} not found in scripts/"
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        capture_output=True,
        text=True,
        timeout=90,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, (
        f"{script_name} --help exited {result.returncode} (expected 0)\n"
        f"stdout (tail): {result.stdout[-2000:]}\n"
        f"stderr (tail): {result.stderr[-2000:]}"
    )
