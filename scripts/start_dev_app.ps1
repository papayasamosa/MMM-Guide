<#
Starts the Streamlit dev server on localhost only, for use by Playwright MCP
verification and manual testing. Keeps caches/temp/logs on D:\Ancestry-MMM.
#>

$ErrorActionPreference = "Stop"
$DriveRoot = "D:\Ancestry-MMM"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$logDir = Join-Path $DriveRoot "logs\mcp"
$tempDir = Join-Path $DriveRoot "temp"
# Ensure all required D-drive directories exist
foreach ($dir in @($logDir, $tempDir)) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
}
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

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "Venv Python not found at $venvPython — cannot start Streamlit." -ForegroundColor Red
    exit 1
}

Push-Location $repoRoot
try {
    Write-Host "Starting Streamlit dev server on http://127.0.0.1:$port (log: $logFile)"
    & $venvPython -m streamlit run ancestry_mmm/app.py `
        --server.address 127.0.0.1 `
        --server.port $port `
        --server.headless true `
        --browser.gatherUsageStats false 2>&1 | Tee-Object -FilePath $logFile
} finally {
    Pop-Location
}
