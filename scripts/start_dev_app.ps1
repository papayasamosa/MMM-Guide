<#
Starts the Streamlit dev server on localhost only, for use by Playwright MCP
verification and manual testing. Keeps caches/temp/logs on D:\Ancestry-MMM.

Uses `uv run` (not a hard-coded .venv path) so it works with any uv-managed
environment - fresh checkout, UV_PROJECT_ENVIRONMENT override, etc.
#>

$ErrorActionPreference = "Stop"

# Source canonical path contract
. (Join-Path $PSScriptRoot "mcp_paths.ps1")
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

# Ensure operational directories exist
foreach ($p in $OperationalPaths) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
}
$logFile = Join-Path $LogsPath "streamlit-dev.log"

# uv
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "uv not found on PATH - cannot start Streamlit." -ForegroundColor Red
    Write-Host "Install uv (https://docs.astral.sh/uv/) and ensure it is on PATH." -ForegroundColor Yellow
    exit 1
}

# D-drive environment
$env:npm_config_cache         = $NpmCachePath
$env:PLAYWRIGHT_BROWSERS_PATH = $BrowsersPath
$env:TEMP                     = $TempPath
$env:TMP                      = $TempPath

# Port check
$port = 8501
$portInUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "Port $port is already in use - stop the existing process or pick a different port." -ForegroundColor Red
    exit 1
}

Push-Location $repoRoot
try {
    Write-Host "Starting Streamlit dev server on http://127.0.0.1:$port (log: $logFile)"
    & uv run streamlit run ancestry_mmm/app.py `
        --server.address 127.0.0.1 `
        --server.port $port `
        --server.headless true `
        --browser.gatherUsageStats false 2>&1 | ForEach-Object -Process { $_; $_ | Out-File -FilePath $logFile -Append }
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
