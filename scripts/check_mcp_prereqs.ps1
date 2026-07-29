<#
Read-only prerequisite checker for the MCP dev tooling described in
docs/development/mcp_development_tooling.md. Never prints token/secret
values - only presence/absence and paths. Attempts no authentication.
#>

$ErrorActionPreference = "Stop"
$DriveRoot = "D:\Ancestry-MMM"
$failures = @()

function Test-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) {
        Write-Host "[OK]   $Name - $Detail"
    } else {
        Write-Host "[FAIL] $Name - $Detail" -ForegroundColor Red
        $script:failures += $Name
    }
}

# 1. Repo location sanity (informational - this repo is developed from C:,
#    only MCP caches/tools/artefacts are required to live on D:).
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Test-Check "Repository readable" (Test-Path $repoRoot) "root: $repoRoot"

# 2. Node
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVersion = (& node --version) -replace "^v", ""
    $major = [int]($nodeVersion.Split(".")[0])
    Test-Check "Node.js >= 18" ($major -ge 18) "found v$nodeVersion at $($node.Source)"
} else {
    Test-Check "Node.js >= 18" $false "node not found on PATH"
}

# 3. npx
$npx = Get-Command npx -ErrorAction SilentlyContinue
Test-Check "npx available" ($null -ne $npx) $(if ($npx) { $npx.Source } else { "npx not found on PATH" })

# 4. npm cache resolves under D
if ($node) {
    $env:npm_config_cache = Join-Path $DriveRoot "cache\npm"
    $npmCache = (& npx --yes npm@latest config get cache 2>$null | Select-Object -Last 1)
    $onD = $npmCache -and ($npmCache.Trim().ToUpper().StartsWith("D:"))
    Test-Check "npm cache on D:" $onD "resolved: $npmCache"
} else {
    Test-Check "npm cache on D:" $false "skipped - node not found"
}

# 5. uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
Test-Check "uv available" ($null -ne $uv) $(if ($uv) { $uv.Source } else { "uv not found on PATH" })

# 6. Playwright browsers path under D + chromium present
$browsersPath = Join-Path $DriveRoot "cache\ms-playwright"
$chromiumPresent = (Test-Path $browsersPath) -and ((Get-ChildItem $browsersPath -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue).Count -gt 0)
Test-Check "Chromium installed under D:" $chromiumPresent "path: $browsersPath"

# 7. Streamlit importable via the project's venv Python
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    Push-Location $repoRoot
    try {
        & $venvPython -c "import streamlit" 2>&1 | Out-Null
        Test-Check "Streamlit importable (venv)" ($LASTEXITCODE -eq 0) "$venvPython -c 'import streamlit'"
    } finally {
        Pop-Location
    }
} else {
    Test-Check "Streamlit importable (venv)" $false "skipped - $venvPython not found"
}

# 8. Required D-drive directories exist
$requiredDirs = @(
    "tools\mcp", "cache\npm", "cache\ms-playwright",
    "temp", "secrets", "test-artifacts\playwright-mcp",
    "logs\mcp"
)
foreach ($d in $requiredDirs) {
    $full = Join-Path $DriveRoot $d
    Test-Check "D-drive dir: $d" (Test-Path $full) $full
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All MCP prerequisite checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Failed checks: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
