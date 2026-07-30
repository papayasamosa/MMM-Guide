<#
Read-only prerequisite checker for the Graphify dev tooling described in
docs/development/graphify.md. Never installs, uninstalls, or modifies
anything - only reports presence/absence and resolved paths. Never prints
token/secret values (Graphify itself needs none).

Uses the canonical path contract from graphify_paths.ps1 so this checker
never disagrees with setup_graphify.ps1 or run_graphify_mcp.ps1 about where
Graphify is expected to live.
#>

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "graphify_paths.ps1")
$failures = @()

function Test-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    if ($Ok) {
        Write-Host "[OK]   $Name - $Detail"
    } else {
        Write-Host "[FAIL] $Name - $Detail" -ForegroundColor Red
        $script:failures += $Name
    }
}

# 1. MMM_DEV_ROOT (or its default) must resolve to a D:-drive path. This is
#    the check that must reject a C-drive tool root.
Test-Check "MMM_DEV_ROOT resolves to D:" (Test-GraphifyPathOnDDrive $GraphifyDriveRoot) "root: $GraphifyDriveRoot"

# 2. uv on PATH
$uv = Get-Command uv -ErrorAction SilentlyContinue
Test-Check "uv available" ($null -ne $uv) $(if ($uv) { $uv.Source } else { "uv not found on PATH" })

# 3. Graphify tool directories exist under the configured root
foreach ($dir in @($GraphifyToolDir, $GraphifyToolBinDir, $GraphifyUvCacheDir)) {
    $onRoot = Test-GraphifyPathUnderRoot $dir $GraphifyDriveRoot
    Test-Check "Directory under root: $(Split-Path $dir -Leaf)" ((Test-Path $dir) -and $onRoot) $dir
}

# 4. Resolved executables exist, and are themselves on D:
foreach ($exe in @($GraphifyCliExe, $GraphifyMcpExe)) {
    $exists = Test-Path $exe
    $onD = $exists -and (Test-GraphifyPathOnDDrive $exe)
    Test-Check "Executable resolved: $(Split-Path $exe -Leaf)" $onD $exe
}

# 5. No ambient-PATH graphify-mcp is relied upon - the launcher must use the
#    resolved D-drive path, not whatever `graphify-mcp` on PATH happens to
#    be. This is informational: an ambient copy elsewhere is not itself a
#    failure (it may be a different project's install), only a reminder
#    that .mcp.json must call the launcher, not the bare command.
$ambient = Get-Command graphify-mcp -ErrorAction SilentlyContinue
if ($ambient) {
    Write-Host "[i]    Ambient 'graphify-mcp' also found on PATH at $($ambient.Source) - not used; the launcher resolves the D-drive copy directly."
}

# 6. .graphifyignore committed
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$ignoreFile = Join-Path $repoRoot ".graphifyignore"
Test-Check ".graphifyignore present" (Test-Path $ignoreFile) $ignoreFile

# 7. Graph output (informational only - built on demand, not a prerequisite
#    for installation itself)
if (Test-Path $GraphifyGraphJson) {
    Write-Host "[i]    Graph present: $GraphifyGraphJson"
} else {
    Write-Host "[i]    Graph not yet built: $GraphifyGraphJson (run 'scripts\run_graphify_cli.ps1 extract . --code-only' then 'scripts\run_graphify_cli.ps1 cluster-only . --no-label')"
}

Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "All Graphify prerequisite checks passed." -ForegroundColor Green
    exit 0
} else {
    Write-Host "Failed checks: $($failures -join ', ')" -ForegroundColor Red
    exit 1
}
