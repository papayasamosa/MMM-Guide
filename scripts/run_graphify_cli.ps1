<#
.SYNOPSIS
    Runs the Graphify CLI (build/refresh subcommands) from its resolved
    D-drive install.

.DESCRIPTION
    PR 88C: the repository wrapper for `graphify extract`, `graphify
    update`, `graphify cluster-only`, and any other graphify CLI
    subcommand - resolves the exact D-drive executable the same way
    scripts/run_graphify_mcp.ps1 resolves graphify-mcp, so a build/refresh
    is never silently satisfied by an ambient `graphify` on PATH (an
    unrelated install, a different pinned version, or a project on another
    drive). docs/development/graphify.md's build and refresh instructions
    call this script instead of a bare `graphify` command.

    Fails (non-zero exit, nothing launched) when:
      - the configured root does not resolve to a D:-drive path;
      - the resolved tool-bin directory (the one directory that determines
        which binary gets executed) escapes the configured D-drive root -
        exact containment via Test-GraphifyPathUnderRoot, not a bare
        string-prefix check, so a similarly-named sibling directory
        (e.g. D:\Ancestry-MMM-Evil) cannot be selected;
      - the graphify executable is absent at the resolved location;
      - no subcommand/arguments were supplied.

    All arguments are passed through unchanged to the resolved executable;
    its exit code is propagated unchanged.

.EXAMPLE
    scripts\run_graphify_cli.ps1 extract . --code-only

.EXAMPLE
    scripts\run_graphify_cli.ps1 cluster-only . --no-label

.EXAMPLE
    scripts\run_graphify_cli.ps1 update .
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "graphify_paths.ps1")

function Fail {
    param([string]$Message)
    Write-Host "[graphify-cli wrapper] FAIL: $Message" -ForegroundColor Red
    exit 1
}

# 1. Root must be on D:
if (-not (Test-GraphifyPathOnDDrive $GraphifyDriveRoot)) {
    Fail "MMM_DEV_ROOT ($GraphifyDriveRoot) is not on the D: drive. Set MMM_DEV_ROOT to a D:\ path or unset it to use the default D:\Ancestry-MMM."
}

# 2. The tool-bin directory determines which binary gets executed below - a
#    stray UV_TOOL_BIN_DIR pointing outside the configured root (including a
#    similarly-named sibling directory) must not be silently honoured.
$effectiveBinDir = if ($env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR } else { $GraphifyToolBinDir }
if (-not (Test-GraphifyPathUnderRoot $effectiveBinDir $GraphifyDriveRoot)) {
    Fail "UV_TOOL_BIN_DIR ($effectiveBinDir) resolves outside the configured D-drive root ($GraphifyDriveRoot)."
}

# Own TEMP/TMP for the spawned process (matches run_graphify_mcp.ps1's
# convention) rather than trusting whatever the parent shell had.
$env:TEMP = $GraphifyTempDir
$env:TMP = $GraphifyTempDir

# 3. Executable must exist at the resolved D-drive location - never fall
#    back to an ambient `graphify` on PATH.
$exePath = Join-Path $effectiveBinDir "graphify.exe"
if (-not (Test-Path $exePath)) {
    Fail "graphify executable not found at $exePath. Run scripts\setup_graphify.ps1 first."
}
if (-not (Test-GraphifyPathOnDDrive $exePath)) {
    Fail "Resolved graphify executable ($exePath) is not on D:."
}

if (-not $Arguments -or $Arguments.Count -eq 0) {
    Fail "No graphify subcommand supplied. Example: scripts\run_graphify_cli.ps1 extract . --code-only"
}

# All checks passed - hand off to the resolved D-drive executable; its exit
# code is propagated unchanged.
& $exePath @Arguments
exit $LASTEXITCODE
