<#
The single named command for "run the complete suite with the real,
blocking coverage floor" - mirrors exactly what the Python 3.11/3.12 tests
CI jobs run (.github/workflows/tests.yml). pyproject.toml's own
[tool.pytest.ini_options] --cov-fail-under is deliberately a lenient 30,
because several CI jobs and ad-hoc local runs only exercise a narrow slice
of the package; the project's real 75% floor only exists here and on the
matching CI command line, and previously had no single documented local
entry point - a developer had to already know to add --cov-fail-under=75
by hand to get a result that means anything.

test_persistence.py, test_official_lifecycle_browser.py and
test_causal_graph_editor_browser.py are excluded because CI runs them as
their own separate, focused jobs (Bundle round-trip, Browser lifecycle
journey) - see run_persistence_tests.ps1 / the Playwright browser job for
those.
#>

$ErrorActionPreference = "Stop"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    uv run pytest ancestry_mmm/tests/ -q `
        --ignore=ancestry_mmm/tests/test_persistence.py `
        --ignore=ancestry_mmm/tests/test_official_lifecycle_browser.py `
        --ignore=ancestry_mmm/tests/test_causal_graph_editor_browser.py `
        --cov --cov-report=term-missing:skip-covered --cov-fail-under=75
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
