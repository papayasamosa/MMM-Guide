<#
.SYNOPSIS
    Canonical Graphify tool-install path contract for Media-Mix-Lab.

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

.DESCRIPTION
    PR 88C: containment is exact - $Path must equal $Root, or start with
    $Root plus a directory separator. A bare string-prefix check (the
    previous implementation) is not sufficient: "D:\Ancestry-MMM-Evil"
    starts with the substring "D:\Ancestry-MMM" even though it is a
    completely different, sibling directory. Requiring the separator
    immediately after the root closes that gap, and rejects every other
    sibling-prefix shape (D:\Ancestry-MMM2, D:\Ancestry-MMMSomethingElse)
    the same way.
#>
function Test-GraphifyPathUnderRoot {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
    if ([StringComparer]::OrdinalIgnoreCase.Equals($fullPath, $fullRoot)) {
        return $true
    }
    return $fullPath.StartsWith(
        $fullRoot + [System.IO.Path]::DirectorySeparatorChar,
        [System.StringComparison]::OrdinalIgnoreCase
    )
}

<#
.SYNOPSIS
    Returns $true if $Path, or any existing ancestor directory between
    $Root and $Path (inclusive of both), is an NTFS reparse point
    (junction or symlink).

.DESCRIPTION
    PR 91A: Test-GraphifyPathUnderRoot is a purely textual containment
    check - it has no way to know that a directory or file it approved is
    a junction/symlink whose physical target lies somewhere else entirely
    (e.g. a junction textually under D:\Ancestry-MMM\tools\uv\bin that
    physically targets C:\Windows\System32, or a sibling D:\Other
    install). A path can pass textual containment and still let Graphify
    execute a binary that does not physically live under the configured
    D-drive root.

    This walks every path segment from $Path up to $Root and fails
    closed - returns $true - the moment any segment is a reparse point,
    regardless of what it points to, rather than attempting to resolve
    and compare final physical targets (which .NET/PowerShell 5.1 has no
    single built-in primitive for). Only existing segments are inspected;
    a missing segment is not a reparse point, it is simply absent -
    callers report that separately as a clear "not found" failure.

    Callers pass the same $Root used for Test-GraphifyPathUnderRoot, and
    should call this only after that containment check has already
    passed, so the walk never has to reason about segments outside the
    governed root.
#>
function Test-GraphifyPathHasReparsePoint {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string]$Root
    )
    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')

    $segments = New-Object System.Collections.Generic.List[string]
    $current = $fullPath
    while ($true) {
        $segments.Add($current)
        if ([StringComparer]::OrdinalIgnoreCase.Equals($current, $fullRoot)) {
            break
        }
        $parent = Split-Path $current -Parent
        if (-not $parent -or [StringComparer]::OrdinalIgnoreCase.Equals($parent, $current)) {
            # Walked up to a filesystem root without ever reaching $Root -
            # $Path is not under $Root at all. Test-GraphifyPathUnderRoot
            # is responsible for rejecting that; nothing further to check.
            break
        }
        $current = $parent
    }

    foreach ($segment in $segments) {
        if (Test-Path -LiteralPath $segment) {
            $item = Get-Item -LiteralPath $segment -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                return $true
            }
        }
    }
    return $false
}
