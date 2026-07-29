<#
Starts the Streamlit dev server on localhost only, for use by Playwright MCP
verification and manual testing. Keeps caches/temp/logs on D:\Ancestry-MMM.
#>

$ErrorActionPreference = "Stop"
$DriveRoot = "D:\Ancestry-MMM"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $DriveRoot "logs\mcp"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "streamlit-dev.log"

$env:npm_config_cache = Join-Path $DriveRoot "cache\npm"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $DriveRoot "cache\ms-playwright"
$env:TEMP = Join-Path $DriveRoot "temp"
$env:TMP = Join-Path $DriveRoot "temp"

$port = 8501
$portInUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "Port $port already in use - pick a free port or stop the existing process." -ForegroundColor Yellow
}

Push-Location $repoRoot
try {
    Write-Host "Starting Streamlit dev server on http://127.0.0.1:$port (log: $logFile)"
    & uv run streamlit run ancestry_mmm/app.py `
        --server.address 127.0.0.1 `
        --server.port $port `
        --server.headless true `
        --browser.gatherUsageStats false 2>&1 | Tee-Object -FilePath $logFile
} finally {
    Pop-Location
}
