<#
Read-only prerequisite checker for the MCP dev tooling described in
docs/development/mcp_development_tooling.md. Never prints token/secret
values - only presence/absence and paths. Attempts no authentication.

Uses the canonical directory contract from mcp_paths.ps1 so the list of
required directories stays consistent with setup and launcher scripts.
#>

$ErrorActionPreference = "Stop"

# Source canonical path contract
. (Join-Path $PSScriptRoot "mcp_paths.ps1")
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
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

# 1. Repo location
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

# 3. npm (use the installed executable, not npx --yes npm@latest which
#    introduces registry drift and a network round trip).
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($npm) {
    $npmVersion = (& npm --version) -replace "^v", ""
    Test-Check "npm available" $true "found v$npmVersion at $($npm.Source)"
} else {
    Test-Check "npm available" $false "npm not found on PATH"
}

# 4. npx
$npx = Get-Command npx -ErrorAction SilentlyContinue
Test-Check "npx available" ($null -ne $npx) $(if ($npx) { $npx.Source } else { "npx not found on PATH" })

# 5. npm cache resolves under D (use the installed npm, not npm@latest)
if ($npm) {
    $env:npm_config_cache = $NpmCachePath
    $npmCache = (& npm config get cache 2>$null | Select-Object -Last 1)
    $expectedCache = [System.IO.Path]::GetFullPath($NpmCachePath).TrimEnd('\')
    $actualCache = [System.IO.Path]::GetFullPath($npmCache.Trim()).TrimEnd('\')
    $cacheMatches = [StringComparer]::OrdinalIgnoreCase.Equals($actualCache, $expectedCache)
    Test-Check "npm cache matches configured root" $cacheMatches "expected: $expectedCache, resolved: $npmCache"
} else {
    Test-Check "npm cache matches configured root" $false "skipped - npm not found"
}

# 5. uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
Test-Check "uv available" ($null -ne $uv) $(if ($uv) { $uv.Source } else { "uv not found on PATH" })

# 6. Playwright browsers path under D + chromium present
$chromiumPresent = (Test-Path $BrowsersPath) -and ((Get-ChildItem $BrowsersPath -Directory -Filter "chromium-*" -ErrorAction SilentlyContinue).Count -gt 0)
Test-Check "Chromium installed under D:" $chromiumPresent "path: $BrowsersPath"

# 7. Streamlit importable via uv
Push-Location $repoRoot
try {
    & uv run --no-sync python -c "import streamlit" 2>&1 | Out-Null
    Test-Check "Streamlit importable (uv)" ($LASTEXITCODE -eq 0) "uv run --no-sync python -c 'import streamlit'"
} catch {
    Test-Check "Streamlit importable (uv)" $false "exception: $_"
} finally {
    Pop-Location
}

# 8. Operational D-drive directories (required for day-to-day use)
foreach ($p in $OperationalPaths) {
    Test-Check "Operational dir: $(Split-Path $p -Leaf)" (Test-Path $p) $p
}

# 9. Optional/reserved directories (informational only)
foreach ($p in $OptionalPaths) {
    $leaf = Split-Path $p -Leaf
    if (Test-Path $p) {
        Write-Host "[i]    Optional dir: $leaf - $p (present)"
    } else {
        Write-Host "[i]    Optional dir: $leaf - $p (absent, not required)"
    }
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All MCP prerequisite checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Failed checks: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
