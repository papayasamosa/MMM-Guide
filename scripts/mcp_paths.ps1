<#
.SYNOPSIS
    Canonical MCP development-tooling path contract for MMM-Guide.

.DESCRIPTION
    Single source of truth for all development-tooling paths under
    D:\Ancestry-MMM\. Sourced by setup, launcher and checker scripts
    so they use one directory list and never disagree about what
    is required vs optional.

    This script is pure data — it does not create or modify anything.
#>

$script:DriveRoot = "D:\Ancestry-MMM"

# ── Operational directories (must exist for day-to-day development) ──
$script:OperationalDirs = @(
    "cache\npm"
    "cache\ms-playwright"
    "temp"
    "test-artifacts\playwright-mcp"
    "logs\mcp"
)

# ── Optional / reserved directories (documented, not required by checker) ──
$script:OptionalDirs = @(
    "tools\mcp"
    "secrets"
)

# ── Resolved full paths ──
$script:DriveRootResolved = $script:DriveRoot
$script:OperationalPaths = $script:OperationalDirs | ForEach-Object {
    Join-Path $script:DriveRoot $_
}
$script:OptionalPaths = $script:OptionalDirs | ForEach-Object {
    Join-Path $script:DriveRoot $_
}
$script:AllPaths = $script:OperationalPaths + $script:OptionalPaths

$script:NpmCachePath     = Join-Path $script:DriveRoot "cache\npm"
$script:BrowsersPath     = Join-Path $script:DriveRoot "cache\ms-playwright"
$script:TempPath         = Join-Path $script:DriveRoot "temp"
$script:TestArtifactsPath = Join-Path $script:DriveRoot "test-artifacts\playwright-mcp"
$script:LogsPath         = Join-Path $script:DriveRoot "logs\mcp"
$script:ToolsPath        = Join-Path $script:DriveRoot "tools\mcp"
$script:SecretsPath      = Join-Path $script:DriveRoot "secrets"
