<#
Safe merge gate (Work Package 0, `Media-Mix-Lab: Coding LLM Next Steps
Post WP5`): this repository has no effective required-check branch
protection on `main`, so a bare `gh pr merge --auto` merges as soon as it
is invoked rather than waiting for checks - this is exactly what let
PR #258 merge while `main`'s own CI was still red (see
REPO_REVIEW_AND_NEXT_STEPS.md's WP4/WP5 history paragraph). This script is
the substitute gate: poll every normal blocking check to a real terminal
state, merge only when every one has succeeded (deliberately skipped
schedule/manual-only jobs are allowed), then poll the push-triggered `main`
workflow run to a real terminal state before reporting done.

This script does not itself decide whether the expensive Candidate A
posterior-recovery job must have a manual run before merging a PR that
changes Candidate A model mathematics (REQ-SEARCH-002 affected modules) -
that is a human/agent judgement call the caller makes with -RequireCandidateARecovery.

Usage:
    pwsh scripts/wait_for_pr_green_then_merge.ps1 -PRNumber 261
    pwsh scripts/wait_for_pr_green_then_merge.ps1  # auto-detects the PR for the current branch

Requires: GitHub CLI (`gh`), authenticated, with access to this repository.
#>

param(
    [int]$PRNumber = 0,
    [string]$Repo = "papayasamosa/Media-Mix-Lab",
    [string[]]$RequiredChecks = @(
        "Compile + Import",
        "Ruff",
        "Windows tooling",
        "Browser lifecycle journey",
        "Requirements index",
        "Mypy",
        "Bandit",
        "Streamlit AppTest",
        "Bundle round-trip",
        "Python 3.12 tests",
        "Python 3.11 tests",
        "pip-audit"
    ),
    [string[]]$AllowedSkippedChecks = @(
        "Deterministic attribution recovery",
        "Candidate A posterior recovery"
    ),
    [switch]$RequireCandidateARecovery,
    [string]$MergeMethod = "squash",
    [int]$PollIntervalSeconds = 30,
    [int]$TimeoutMinutes = 60,
    [switch]$SkipMainVerification
)

$ErrorActionPreference = "Stop"

function Get-GhOrFail {
    param([string[]]$GhArgs)
    $output = & gh @GhArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gh $($GhArgs -join ' ') failed (exit $LASTEXITCODE):`n$output"
    }
    return $output
}

if ($PRNumber -eq 0) {
    Write-Host "No -PRNumber supplied; resolving PR for the current branch..."
    $prJson = Get-GhOrFail @("pr", "view", "--repo", $Repo, "--json", "number,headRefName,headRefOid")
    $pr = $prJson | ConvertFrom-Json
    $PRNumber = $pr.number
    Write-Host "Resolved PR #$PRNumber (branch $($pr.headRefName), head $($pr.headRefOid))"
}

if ($RequireCandidateARecovery) {
    $AllowedSkippedChecks = $AllowedSkippedChecks | Where-Object { $_ -ne "Candidate A posterior recovery" }
    $RequiredChecks = $RequiredChecks + "Candidate A posterior recovery"
    Write-Host "REQUIRE-CANDIDATE-A-RECOVERY set: a successful, non-skipped 'Candidate A posterior recovery' run is now required before merge."
}

Write-Host "Waiting for PR #$PRNumber's checks to appear..."

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$checksAppeared = $false

while ((Get-Date) -lt $deadline) {
    $checksJson = Get-GhOrFail @("pr", "checks", "$PRNumber", "--repo", $Repo, "--json", "name,state,bucket", "--required")
    $checks = @()
    if ($checksJson -and $checksJson.Trim().Length -gt 0) {
        $checks = $checksJson | ConvertFrom-Json
    }
    if ($checks.Count -gt 0) {
        $checksAppeared = $true
        break
    }
    Write-Host "  no checks reported yet, retrying in ${PollIntervalSeconds}s..."
    Start-Sleep -Seconds $PollIntervalSeconds
}

if (-not $checksAppeared) {
    throw "Timed out after $TimeoutMinutes minute(s) waiting for PR #$PRNumber's checks to appear at all. Not merging."
}

Write-Host "Polling PR #$PRNumber's required checks until every one reaches a terminal state..."

$allGreen = $false

while ((Get-Date) -lt $deadline) {
    $checksJson = Get-GhOrFail @("pr", "checks", "$PRNumber", "--repo", $Repo, "--json", "name,state,bucket")
    $checks = $checksJson | ConvertFrom-Json

    $byName = @{}
    foreach ($check in $checks) {
        $byName[$check.name] = $check
    }

    $notReady = New-Object System.Collections.Generic.List[string]
    $failed = New-Object System.Collections.Generic.List[string]
    $missing = New-Object System.Collections.Generic.List[string]

    foreach ($requiredName in $RequiredChecks) {
        if (-not $byName.ContainsKey($requiredName)) {
            $missing.Add($requiredName)
            continue
        }
        $check = $byName[$requiredName]
        $bucket = $check.bucket
        if ($bucket -eq "pass") {
            continue
        }
        elseif ($bucket -eq "pending") {
            $notReady.Add("$requiredName (state=$($check.state))")
        }
        elseif ($bucket -eq "skipping" -and ($AllowedSkippedChecks -contains $requiredName)) {
            Write-Host "  $requiredName was skipped - allowed (schedule/manual-only job)."
            continue
        }
        else {
            $failed.Add("$requiredName (bucket=$bucket, state=$($check.state))")
        }
    }

    if ($failed.Count -gt 0) {
        throw "PR #$PRNumber has failed/cancelled/unexpectedly-skipped required check(s): $($failed -join '; '). Not merging - fix and push a new commit, then re-run this script."
    }

    if ($missing.Count -gt 0) {
        Write-Host "  still waiting for check(s) to be reported: $($missing -join ', ')"
        Start-Sleep -Seconds $PollIntervalSeconds
        continue
    }

    if ($notReady.Count -gt 0) {
        Write-Host "  still in progress: $($notReady -join ', ')"
        Start-Sleep -Seconds $PollIntervalSeconds
        continue
    }

    $allGreen = $true
    break
}

if (-not $allGreen) {
    throw "Timed out after $TimeoutMinutes minute(s) waiting for PR #$PRNumber's required checks to go green. Not merging."
}

Write-Host "All required checks green for PR #$PRNumber. Merging (method: $MergeMethod)..."

$mergeFlag = "--$MergeMethod"
Get-GhOrFail @("pr", "merge", "$PRNumber", "--repo", $Repo, $mergeFlag, "--delete-branch=false") | Out-Null

$prAfterMerge = Get-GhOrFail @("pr", "view", "$PRNumber", "--repo", $Repo, "--json", "state,mergeCommit,mergedAt")
$prState = $prAfterMerge | ConvertFrom-Json

if ($prState.state -ne "MERGED") {
    throw "PR #$PRNumber does not report state=MERGED after the merge call (got '$($prState.state)'). Investigate manually before continuing."
}

$mergeSha = $prState.mergeCommit.oid
Write-Host "PR #$PRNumber merged. Merge commit: $mergeSha"

Write-Host "Verifying merge commit is reachable from origin/main..."
git fetch origin main --quiet
$isAncestor = git merge-base --is-ancestor $mergeSha origin/main
if ($LASTEXITCODE -ne 0) {
    throw "Merge commit $mergeSha is not (yet) an ancestor of origin/main. Investigate before starting the next work package."
}
Write-Host "Confirmed: $mergeSha is on origin/main."

if ($SkipMainVerification) {
    Write-Host "SkipMainVerification set - not waiting for the push-triggered main workflow. Done."
    exit 0
}

Write-Host "Waiting for the push-triggered main workflow run for $mergeSha..."

$mainDeadline = (Get-Date).AddMinutes($TimeoutMinutes)
$mainRunFound = $false
$mainRun = $null

while ((Get-Date) -lt $mainDeadline) {
    $runsJson = Get-GhOrFail @("run", "list", "--repo", $Repo, "--branch", "main", "--workflow", "Tests", "--limit", "10", "--json", "headSha,status,conclusion,url,event")
    $runs = $runsJson | ConvertFrom-Json
    $matching = $runs | Where-Object { $_.headSha -eq $mergeSha -and $_.event -eq "push" }
    if ($matching) {
        $mainRunFound = $true
        $mainRun = $matching | Select-Object -First 1
        break
    }
    Write-Host "  no push-triggered main run for $mergeSha yet, retrying in ${PollIntervalSeconds}s..."
    Start-Sleep -Seconds $PollIntervalSeconds
}

if (-not $mainRunFound) {
    throw "Timed out after $TimeoutMinutes minute(s) waiting for a push-triggered main workflow run for $mergeSha to appear. Verify manually before starting the next work package."
}

while ((Get-Date) -lt $mainDeadline) {
    $runsJson = Get-GhOrFail @("run", "list", "--repo", $Repo, "--branch", "main", "--workflow", "Tests", "--limit", "10", "--json", "headSha,status,conclusion,url,event")
    $runs = $runsJson | ConvertFrom-Json
    $matching = $runs | Where-Object { $_.headSha -eq $mergeSha -and $_.event -eq "push" } | Select-Object -First 1

    if ($matching.status -eq "completed") {
        if ($matching.conclusion -eq "success") {
            Write-Host "main workflow succeeded for $mergeSha : $($matching.url)"
            exit 0
        }
        else {
            throw "main workflow completed with conclusion '$($matching.conclusion)' for $mergeSha : $($matching.url). main is red - do not start the next work package until this is fixed."
        }
    }

    Write-Host "  main workflow status: $($matching.status), retrying in ${PollIntervalSeconds}s..."
    Start-Sleep -Seconds $PollIntervalSeconds
}

throw "Timed out after $TimeoutMinutes minute(s) waiting for the main workflow run for $mergeSha to complete. Verify manually before starting the next work package."
