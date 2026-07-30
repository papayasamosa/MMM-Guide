<#
.SYNOPSIS
    Launches the Graphify MCP server from its resolved D-drive install.

.DESCRIPTION
    Invoked by .mcp.json instead of relying on an ambient `graphify-mcp` on
    PATH. Resolves the exact executable installed by scripts/setup_graphify.ps1
    and fails clearly (non-zero exit, no partial launch) instead of silently
    falling back to a PATH lookup or a C:-drive location, so a misconfigured
    or half-provisioned machine cannot silently start the wrong binary or
    write outside D:\Ancestry-MMM\.

    Fails when:
      - the configured root does not resolve to a D:-drive path;
      - the resolved tool-bin directory (the one directory that determines
        which binary gets executed) escapes the configured D-drive root;
      - the graphify-mcp executable is absent;
      - graphify-out/graph.json is absent (nothing to serve).

    TEMP/TMP for the spawned process are set explicitly to the governed
    D-drive path below rather than merely validated - an unrelated,
    already-D:-drive ambient TEMP from the parent shell (e.g. a per-user
    scratch convention outside this project) is not itself a governance
    violation, so it is overridden rather than treated as a hard failure.
#>

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "graphify_paths.ps1")

function Fail {
    param([string]$Message)
    Write-Host "[graphify-mcp launcher] FAIL: $Message" -ForegroundColor Red
    exit 1
}

# 1. Root must be on D:
if (-not (Test-GraphifyPathOnDDrive $GraphifyDriveRoot)) {
    Fail "MMM_DEV_ROOT ($GraphifyDriveRoot) is not on the D: drive. Set MMM_DEV_ROOT to a D:\ path or unset it to use the default D:\Ancestry-MMM."
}

# 1b. PR 91A: textual containment below cannot detect a reparse point
#     (junction/symlink) physically escaping the configured root - reject
#     the root itself if it is one.
if (Test-GraphifyPathHasReparsePoint $GraphifyDriveRoot $GraphifyDriveRoot) {
    Fail "Configured root ($GraphifyDriveRoot) is an NTFS junction or symlink - refusing to trust its physical target."
}

# 2. The tool-bin directory determines which binary gets executed below -
#    a stray UV_TOOL_BIN_DIR pointing at %USERPROFILE%\.local\bin or any
#    other location outside the configured root must not be silently
#    honoured.
$effectiveBinDir = if ($env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR } else { $GraphifyToolBinDir }
if (-not (Test-GraphifyPathUnderRoot $effectiveBinDir $GraphifyDriveRoot)) {
    Fail "UV_TOOL_BIN_DIR ($effectiveBinDir) resolves outside the configured D-drive root ($GraphifyDriveRoot)."
}

# 2b. PR 91A: reject a tool-bin directory (or any existing parent between
#     it and the root) that is a reparse point, even though it passed
#     textual containment above - it may physically target C: or an
#     unrelated D:-drive install.
if (Test-GraphifyPathHasReparsePoint $effectiveBinDir $GraphifyDriveRoot) {
    Fail "Resolved tool-bin path ($effectiveBinDir) contains an NTFS junction or symlink between it and the configured root - refusing to trust its physical target."
}

# Own TEMP/TMP for the spawned process (matches scripts/start_dev_app.ps1's
# convention) rather than trusting whatever the parent shell had.
$env:TEMP = $GraphifyTempDir
$env:TMP = $GraphifyTempDir

# 3. Executable must exist at the resolved D-drive location.
$exePath = Join-Path $effectiveBinDir "graphify-mcp.exe"
if (-not (Test-Path $exePath)) {
    Fail "graphify-mcp executable not found at $exePath. Run scripts\setup_graphify.ps1 first."
}
if (-not (Test-GraphifyPathOnDDrive $exePath)) {
    Fail "Resolved graphify-mcp executable ($exePath) is not on D:."
}

# 3b. PR 91A: the executable file itself must not be a reparse point
#     (symlink) whose physical target lies outside the configured root.
if (Test-GraphifyPathHasReparsePoint $exePath $GraphifyDriveRoot) {
    Fail "Resolved graphify-mcp executable ($exePath) is an NTFS junction or symlink - refusing to trust its physical target."
}

# 4. Graph must exist - nothing to serve otherwise.
if (-not (Test-Path $GraphifyGraphJson)) {
    Fail "Graph not found at $GraphifyGraphJson. Run 'scripts\run_graphify_cli.ps1 extract . --code-only' then 'scripts\run_graphify_cli.ps1 cluster-only . --no-label' from the repo root first."
}

# All checks passed - hand off to the resolved D-drive executable. This
# process becomes graphify-mcp (stdio transport, matching context7/playwright
# entries in .mcp.json); its exit code is propagated unchanged.
& $exePath $GraphifyGraphJson
exit $LASTEXITCODE
