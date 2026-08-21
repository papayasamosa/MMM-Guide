<#
.SYNOPSIS
    Run the approved UK PyMC production fit with the governed D-drive runtime.

.DESCRIPTION
    The production fit must use PyMC/PyTensor and a locally installed Windows
    C++ compiler.  This wrapper makes the compiler and PyTensor compiledir
    explicit for the child process so an ambient compiler or C-drive cache
    cannot be selected accidentally.

    The wrapper does not install software or modify machine-wide PATH.  Install
    the portable toolchain under D:\Ancestry-MMM\tools\mingw64 first.
#>

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Arguments
)

$ErrorActionPreference = "Stop"

$runtimeRoot = "D:\Ancestry-MMM"
$mingwBin = Join-Path $runtimeRoot "tools\mingw64\bin"
$compiler = Join-Path $mingwBin "g++.exe"
$compiledir = Join-Path $runtimeRoot "cache\pytensor"
$uvCache = Join-Path $runtimeRoot "cache\uv"
$tempDir = Join-Path $runtimeRoot "cache\tmp"

if (-not (Test-Path -LiteralPath $compiler -PathType Leaf)) {
    Write-Error "Approved PyTensor compiler not found at $compiler. Install the governed D-drive MinGW-w64 toolchain first."
    exit 1
}

New-Item -ItemType Directory -Force -Path $compiledir | Out-Null
New-Item -ItemType Directory -Force -Path $uvCache | Out-Null
New-Item -ItemType Directory -Force -Path $tempDir | Out-Null

# Keep these settings process-local.  They are intentionally not written to a
# user or machine environment, and no C-drive compiler/cache is used.
$env:PATH = "$mingwBin;$env:PATH"
$env:PYTENSOR_FLAGS = "cxx=$($compiler.Replace('\', '/')),base_compiledir=$($compiledir.Replace('\', '/'))"
$env:UV_CACHE_DIR = $uvCache
$env:TEMP = $tempDir
$env:TMP = $tempDir

$resolvedCompiler = (Resolve-Path -LiteralPath $compiler).Path
$whereResults = @(where.exe g++ 2>$null)
if (-not $whereResults -or ((Resolve-Path -LiteralPath $whereResults[0]).Path -ne $resolvedCompiler)) {
    Write-Error "The governed D-drive g++ was not selected first by where.exe. Resolved: $($whereResults -join ', ')"
    exit 1
}

if (-not $Arguments -or $Arguments.Count -eq 0) {
    $Arguments = @("scripts\run_uk_production_fit.py")
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $repoRoot
try {
    & uv run python @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
