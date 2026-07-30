<#
.SYNOPSIS
    Installs Graphify as an isolated, D-drive-only uv tool.

.DESCRIPTION
    Installs the pinned `graphifyy[mcp]` package via `uv tool install` into
    D-drive tool/cache directories only - never into %USERPROFILE%\.local,
    %LOCALAPPDATA%, or any C:-drive path. Does NOT run `uv tool update-shell`
    (the repository's own launcher, scripts/run_graphify_mcp.ps1, resolves
    the exact D-drive executable directly - Graphify is never added to the
    ambient user PATH).

    Does not touch pyproject.toml, uv.lock, or the project's own Python
    environment - graphifyy is a development-only tool, isolated from the
    application's dependency set.
#>

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "graphify_paths.ps1")

if (-not (Test-GraphifyPathOnDDrive $GraphifyDriveRoot)) {
    Write-Host "[FAIL] MMM_DEV_ROOT ($GraphifyDriveRoot) is not on the D: drive." -ForegroundColor Red
    Write-Host "       Graphify must install under a D:-drive root. Set MMM_DEV_ROOT to a D:\ path." -ForegroundColor Red
    exit 1
}

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Write-Host "[FAIL] uv not found on PATH - cannot install Graphify." -ForegroundColor Red
    exit 1
}

Write-Host "Provisioning D-drive tool directories under $GraphifyDriveRoot ..." -ForegroundColor Cyan
foreach ($p in @($GraphifyToolDir, $GraphifyToolBinDir, $GraphifyUvCacheDir, $GraphifyTempDir)) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    Write-Host "  [OK] $p"
}

# Redirect uv's own install/cache/temp behaviour before invoking it - these
# must be set in-process so the child `uv tool install` inherits them.
$env:UV_TOOL_DIR     = $GraphifyToolDir
$env:UV_TOOL_BIN_DIR = $GraphifyToolBinDir
$env:UV_CACHE_DIR    = $GraphifyUvCacheDir
$env:TEMP            = $GraphifyTempDir
$env:TMP             = $GraphifyTempDir

Write-Host "Installing $GraphifyPackageSpec (isolated uv tool, forced reinstall) ..." -ForegroundColor Cyan
& uv tool install --force $GraphifyPackageSpec
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] uv tool install exited with code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

# Deliberately not calling `uv tool update-shell` - see script synopsis.

Write-Host ""
Write-Host "Verifying resolved executables ..." -ForegroundColor Cyan
$verifyFailures = @()

foreach ($exe in @($GraphifyCliExe, $GraphifyMcpExe)) {
    if (Test-Path $exe) {
        if (-not (Test-GraphifyPathOnDDrive $exe)) {
            Write-Host "  [FAIL] $exe resolved but is not on D:" -ForegroundColor Red
            $verifyFailures += $exe
        } else {
            Write-Host "  [OK] $exe"
        }
    } else {
        Write-Host "  [FAIL] not found: $exe" -ForegroundColor Red
        $verifyFailures += $exe
    }
}

if ($verifyFailures.Count -gt 0) {
    Write-Host ""
    Write-Host "Graphify install verification failed for: $($verifyFailures -join ', ')" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Graphify $GraphifyPinnedVersion installed under D:\ only." -ForegroundColor Green
Write-Host "  CLI:        $GraphifyCliExe"
Write-Host "  MCP server: $GraphifyMcpExe"
Write-Host "Run scripts/check_graphify_prereqs.ps1 to re-verify at any time." -ForegroundColor Green
exit 0
