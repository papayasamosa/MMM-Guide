<#
.SYNOPSIS
    Canonical Graphify tool-install path contract for MMM-Guide.

.DESCRIPTION
    Single source of truth for the D-drive paths used to install and run
    Graphify as an isolated `uv tool` (separate from the npm/Playwright
    paths in mcp_paths.ps1, and separate from the project's own Python
    environment). Sourced by setup, checker and launcher scripts so they
    never disagree about where the tool, its executables, and its caches
    live.

    This script is pure data - it does not create, install, or modify
    anything.
#>

# Default local root. Override via MMM_DEV_ROOT for CI or isolated testing
# (e.g. $env:MMM_DEV_ROOT = "D:\Ancestry-MMM-CI"). Normal local setup must
# not silently fall back to a C:-drive or %USERPROFILE% location.
$script:GraphifyDriveRoot = if ($env:MMM_DEV_ROOT) {
    $env:MMM_DEV_ROOT
} else {
    "D:\Ancestry-MMM"
}

$script:GraphifyPinnedVersion = "0.9.30"
$script:GraphifyPackageSpec = "graphifyy[mcp]==$script:GraphifyPinnedVersion"

# --- uv tool install directories (isolated from the project venv) ---
$script:GraphifyToolDir    = Join-Path $script:GraphifyDriveRoot "tools\uv\tools"
$script:GraphifyToolBinDir = Join-Path $script:GraphifyDriveRoot "tools\uv\bin"
$script:GraphifyUvCacheDir = Join-Path $script:GraphifyDriveRoot "cache\uv"
$script:GraphifyTempDir    = Join-Path $script:GraphifyDriveRoot "temp"

# --- Resolved executables ---
$script:GraphifyCliExe = Join-Path $script:GraphifyToolBinDir "graphify.exe"
$script:GraphifyMcpExe = Join-Path $script:GraphifyToolBinDir "graphify-mcp.exe"

# --- Repo-relative graph output (never moved to D: - see graphify.md,
#     "What's committed vs rebuilt locally": this is a cheap, gitignored,
#     repo-scoped build artefact, not an installed tool/cache/dependency) ---
$script:GraphifyRepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:GraphifyGraphJson = Join-Path $script:GraphifyRepoRoot "graphify-out\graph.json"

<#
.SYNOPSIS
    Returns $true only if the given path's drive letter is D:.
#>
function Test-GraphifyPathOnDDrive {
    param([Parameter(Mandatory)][string]$Path)
    $full = [System.IO.Path]::GetFullPath($Path)
    $drive = [System.IO.Path]::GetPathRoot($full).TrimEnd('\')
    return [StringComparer]::OrdinalIgnoreCase.Equals($drive, "D:")
}

<#
.SYNOPSIS
    Returns $true only if $Path resolves inside $Root (no escape via ..,
    a differently-rooted override, or a relative path).
#>
function Test-GraphifyPathUnderRoot {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    return $fullPath.StartsWith($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)
}
