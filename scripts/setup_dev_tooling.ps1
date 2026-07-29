<#
.SYNOPSIS
    One-time provisioning of MCP development-tooling directory structure.

.DESCRIPTION
    Creates operational directories under D:\Ancestry-MMM\ that are needed
    by launcher, checker, npm cache, Playwright browsers and test artefacts.

    By default creates only operational paths. Supply -IncludeOptional to
    also create optional/reserved directories (tools\mcp, secrets).

    Never creates secrets, tokens, or credentials. Never writes to C:.
#>

param(
    [switch]$IncludeOptional
)

$ErrorActionPreference = "Stop"

# Source canonical path contract
. (Join-Path $PSScriptRoot "mcp_paths.ps1")

Write-Host "Creating operational directories under $DriveRoot ..." -ForegroundColor Cyan
foreach ($p in $OperationalPaths) {
    New-Item -ItemType Directory -Force -Path $p | Out-Null
    Write-Host "  [OK] $p"
}

if ($IncludeOptional) {
    Write-Host "Optional/reserved directories:" -ForegroundColor Cyan
    foreach ($p in $OptionalPaths) {
        if (-not (Test-Path $p)) {
            New-Item -ItemType Directory -Force -Path $p | Out-Null
            Write-Host "  [i] $p (created)"
        } else {
            Write-Host "  [ ] $p (already exists)"
        }
    }
}

Write-Host ""
Write-Host "Setup complete. Run scripts/check_mcp_prereqs.ps1 to verify." -ForegroundColor Green
exit 0
