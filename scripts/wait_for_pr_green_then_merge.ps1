<#
Safe merge gate (Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps
Post WP5`; hardened by Work Package 2 of `...Post PR262`): this repository
has no effective required-check branch protection on `main`, so a bare
`gh pr merge --auto` merges as soon as it is invoked rather than waiting for
checks - this is exactly what let PR #258 merge while `main`'s own CI was
still red (see REPO_REVIEW_AND_NEXT_STEPS.md's WP4/WP5 history paragraph).
This script is the substitute gate: verify remote/auth state, capture the
PR's exact head SHA, poll every normal blocking check (plus an automatically
dispatched Candidate A posterior recovery run when the PR touches Candidate
A model mathematics) to a real terminal state, refuse any unclassified CI
check, re-verify the head has not moved immediately before merging with an
expected-head guard, then poll the push-triggered `main` workflow run to a
real terminal state before reporting done.

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
        "Candidate A posterior recovery",
        "Fold refit recovery"
    ),
    # Checks that are known to exist, never block merge on their own
    # (pull_request-only, informational annotations), and must not trip the
    # fail-closed "unexpected check" guard below.
    [string[]]$InformationalChecks = @(
        "Candidate A recovery gate check",
        "Fold refit recovery gate check"
    ),
    # Kept in sync by hand with .github/workflows/tests.yml's
    # candidate-a-recovery-gate-check job's candidate_a_paths array and
    # docs/approved_requirements/REQ-SEARCH-002.md's "Affected modules" -
    # both describe the same governed boundary from different angles
    # (CI annotation vs. this merge gate's automatic dispatch decision).
    [string[]]$CandidateAPaths = @(
        "ancestry_mmm/core/search_capacity.py",
        "ancestry_mmm/core/search_candidate_a_recovery.py",
        "ancestry_mmm/core/search_decision_package.py",
        "ancestry_mmm/core/graph_model_compiler.py",
        "ancestry_mmm/core/hierarchical_model.py",
        "ancestry_mmm/core/causal_graph.py"
    ),
    [switch]$RequireCandidateARecovery,
    # Work Package 0 (structural-causal authority reconciliation, after PR
    # #286): PR #286 added the "Fold refit recovery" schedule/manual job
    # but no analogous automatic path-based recovery requirement existed
    # for it, unlike Candidate A above - a future PR could alter
    # fold-refit/validation mathematics while the expensive recovery job
    # stayed skipped unless an operator remembered to run it. Scoped, via
    # actual import inspection (not guesswork), to the fold-refit evidence
    # pipeline's own three modules - deliberately excludes the shared
    # production fit path they call through (model_fit_service.py,
    # models.py, predict.py, market_specific_predict.py,
    # hierarchical_model.py, market_specific_model.py), which is already
    # exercised by every PR's blocking test suite (including
    # test_fold_refit_service.py's own tiny real fit) and would make this
    # expensive job fire on nearly every modelling PR if included - the
    # same narrow-scoping precedent $CandidateAPaths above already
    # establishes (it excludes predict.py despite Candidate A depending on
    # it transitively). Kept in sync by hand with .github/workflows/
    # tests.yml's fold-refit-recovery-gate-check job's fold_refit_paths
    # array.
    [string[]]$FoldRefitPaths = @(
        "ancestry_mmm/application/fold_refit_service.py",
        "ancestry_mmm/core/validation_folds.py",
        "ancestry_mmm/core/structural_stability.py"
    ),
    [switch]$RequireFoldRefitRecovery,
    [string]$MergeMethod = "squash",
    [int]$PollIntervalSeconds = 30,
    [int]$TimeoutMinutes = 60,
    # Deliberately not named "-SkipMainVerification" (brief §5.13: "Consider
    # deprecating/removing that bypass from the normal agent path" - the
    # required contract is "green PR -> merge -> green main -> next work
    # package", not merely "green PR -> merge"). The autonomous flow must
    # never pass this. It exists only for a human operator's manual/debug use.
    [switch]$DangerouslySkipMainVerification
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

# ---------------------------------------------------------------------------
# Dispatched-recovery-job verification (fixes a genuine tooling defect found
# while merging PR #288 - see docs/decision_log.md "Fix Fold refit
# recovery/Candidate A posterior recovery dispatch verification"): GitHub
# creates a *separate* check-suite per trigger event, so a `workflow_dispatch`
# run of `Tests` and the PR's own `pull_request`-triggered run of `Tests`
# produce two distinct check-suites for the identical head SHA. This
# repository has no branch-protection required-checks configuration (see this
# script's own header comment), so there is no context-name-based merge of
# same-named checks across suites - `gh pr checks`/the PR's
# `statusCheckRollup` only ever reflect the *first* (pull_request) suite's
# result for a given check name. A dispatched recovery job's own outcome is
# real and independently verifiable (`gh run view <run-id> --json jobs`), but
# never becomes visible through `gh pr checks`, however long the caller waits
# - confirmed by direct comparison of `gh pr checks`, `gh pr view --json
# statusCheckRollup`, `gh api .../commits/<sha>/check-runs`, and `gh api
# .../commits/<sha>/check-suites` against the same head SHA. Verifying job
# success directly against the specific dispatched run ID is therefore the
# only reliable mechanism - this function replaces the previous
# `-RequiredChecks`/`-AllowedSkippedChecks` dance for these two specific
# check names, which could never observe a real pass this way.
function Wait-ForDispatchedRecoveryJobSuccess {
    param(
        [Parameter(Mandatory)][string]$Repo,
        [Parameter(Mandatory)][string]$WorkflowName,
        [Parameter(Mandatory)][string]$HeadRefName,
        [Parameter(Mandatory)][string]$ExpectedHeadSha,
        [Parameter(Mandatory)][string]$JobName,
        [Parameter(Mandatory)][datetime]$DispatchedAfterUtc,
        [Parameter(Mandatory)][int]$TimeoutMinutes,
        [Parameter(Mandatory)][int]$PollIntervalSeconds
    )

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)

    Write-Host "  Locating the dispatched '$WorkflowName' run for $HeadRefName (head $ExpectedHeadSha)..."
    $runId = $null
    while ((Get-Date) -lt $deadline) {
        $runsJson = Get-GhOrFail @("run", "list", "--repo", $Repo, "--workflow", $WorkflowName, "--branch", $HeadRefName, "--event", "workflow_dispatch", "--limit", "10", "--json", "databaseId,headSha,createdAt")
        $runs = @()
        if ($runsJson -and $runsJson.Trim().Length -gt 0) {
            $runs = $runsJson | ConvertFrom-Json
        }
        $candidate = $runs |
            Where-Object { $_.headSha -eq $ExpectedHeadSha -and ([datetime]$_.createdAt) -ge $DispatchedAfterUtc } |
            Sort-Object createdAt -Descending | Select-Object -First 1
        if ($candidate) {
            $runId = $candidate.databaseId
            Write-Host "  Found dispatched run $runId (created $($candidate.createdAt))."
            break
        }
        Write-Host "    no matching workflow_dispatch run for head $ExpectedHeadSha yet, retrying in ${PollIntervalSeconds}s..."
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    if (-not $runId) {
        throw "Timed out after $TimeoutMinutes minute(s) waiting for the dispatched '$WorkflowName' run to appear for head $ExpectedHeadSha. Not merging."
    }

    Write-Host "  Polling dispatched run $runId for job '$JobName' to reach a terminal state..."
    while ((Get-Date) -lt $deadline) {
        $runJson = Get-GhOrFail @("run", "view", "$runId", "--repo", $Repo, "--json", "headSha,jobs")
        $run = $runJson | ConvertFrom-Json
        if ($run.headSha -ne $ExpectedHeadSha) {
            throw "Dispatched run $runId's headSha ($($run.headSha)) does not match the " +
                "expected head ($ExpectedHeadSha) - refusing to trust it. Not merging."
        }
        $job = $run.jobs | Where-Object { $_.name -eq $JobName } | Select-Object -First 1
        if (-not $job) {
            throw "Dispatched run $runId has no job named '$JobName' - the workflow may " +
                "have changed since this script's -FoldRefitPaths/-CandidateAPaths were " +
                "written; investigate manually before merging."
        }
        if ($job.status -eq "completed") {
            if ($job.conclusion -eq "success") {
                Write-Host "  '$JobName' succeeded in dispatched run $runId ($($job.url))."
                return
            }
            throw "'$JobName' completed with conclusion '$($job.conclusion)' in dispatched " +
                "run $runId ($($job.url)) - not merging. Fix and push a new commit, then " +
                "re-run this script (this dispatches a fresh recovery run)."
        }
        Write-Host "    '$JobName' status: $($job.status), retrying in ${PollIntervalSeconds}s..."
        Start-Sleep -Seconds $PollIntervalSeconds
    }
    throw "Timed out after $TimeoutMinutes minute(s) waiting for '$JobName' to complete in " +
        "dispatched run $runId. Not merging."
}

# ---------------------------------------------------------------------------
# Remote/auth preflight (brief §5.13/§8.5) - never trust local state without
# verifying it against the actual remote first.
# ---------------------------------------------------------------------------

Write-Host "Verifying origin remote identity..."
$remoteUrl = (git remote get-url origin 2>&1)
if ($LASTEXITCODE -ne 0) {
    throw "git remote get-url origin failed: $remoteUrl"
}
if ($remoteUrl -notmatch [regex]::Escape($Repo)) {
    throw "origin remote ($remoteUrl) does not reference the expected repository " +
        "($Repo). Refusing to continue against a mismatched remote."
}
Write-Host "  origin -> $remoteUrl (matches expected repo $Repo)"

Write-Host "Fetching origin..."
git fetch origin --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "git fetch origin failed."
}

Write-Host "Verifying gh authentication..."
$authCheck = & gh auth status 2>&1
if ($LASTEXITCODE -ne 0) {
    if ($env:GITHUB_TOKEN -or $env:GH_TOKEN) {
        Write-Host "  gh auth status failed with GITHUB_TOKEN/GH_TOKEN set in the " +
            "environment - clearing the override for this script and retrying " +
            "against a keyring-stored login..."
        Remove-Item Env:\GITHUB_TOKEN -ErrorAction SilentlyContinue
        Remove-Item Env:\GH_TOKEN -ErrorAction SilentlyContinue
    }
    $authRetry = & gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gh is not authenticated against github.com even after clearing " +
            "GITHUB_TOKEN/GH_TOKEN:`n$authRetry"
    }
}
$authWhoAmI = & gh api user --jq .login 2>&1
if ($LASTEXITCODE -ne 0 -or -not $authWhoAmI) {
    throw "gh auth status passed but 'gh api user' failed - authentication is not usable: $authWhoAmI"
}
Write-Host "  gh authenticated as $authWhoAmI"

# ---------------------------------------------------------------------------
# Resolve the PR and capture its exact head SHA now, before any waiting -
# this is the value every later check/merge step is verified against
# (brief §5.13 "PR-head race").
# ---------------------------------------------------------------------------

$viewArgs = @("pr", "view", "--repo", $Repo, "--json", "number,headRefName,headRefOid,baseRefOid")
if ($PRNumber -ne 0) {
    $viewArgs = @("pr", "view", "$PRNumber", "--repo", $Repo, "--json", "number,headRefName,headRefOid,baseRefOid")
}
$pr = (Get-GhOrFail $viewArgs) | ConvertFrom-Json
$PRNumber = $pr.number
$headRefName = $pr.headRefName
$capturedHeadSha = $pr.headRefOid
Write-Host "Resolved PR #$PRNumber (branch $headRefName). Captured head SHA: $capturedHeadSha"

# ---------------------------------------------------------------------------
# Automatic Candidate A path detection (brief §5.13 "Candidate A recovery
# remains caller-selected" - this replaces the caller having to remember
# -RequireCandidateARecovery for a PR that changes Candidate A model
# mathematics).
# ---------------------------------------------------------------------------

if (-not $RequireCandidateARecovery) {
    Write-Host "Checking whether PR #$PRNumber changes any Candidate A model-mathematics file..."
    $diffOutput = Get-GhOrFail @("pr", "diff", "$PRNumber", "--repo", $Repo, "--name-only")
    $changedFiles = ($diffOutput -join "`n") -split "`r?`n" | Where-Object { $_ }
    $hitPaths = $CandidateAPaths | Where-Object { $changedFiles -contains $_ }
    if ($hitPaths.Count -gt 0) {
        Write-Host "  Candidate A affected module(s) changed: $($hitPaths -join ', ')"
        Write-Host "  Automatically requiring Candidate A posterior recovery before merge."
        $RequireCandidateARecovery = $true
    }
    else {
        Write-Host "  No Candidate A affected module changed - recovery not required."
    }
}

$scheduleWorkflowDispatched = $false
$scheduleWorkflowDispatchedAtUtc = $null

if ($RequireCandidateARecovery) {
    Write-Host "REQUIRE-CANDIDATE-A-RECOVERY set: a successful, non-skipped 'Candidate A posterior recovery' run is now required before merge."
    Write-Host "Dispatching a workflow_dispatch run of 'Tests' on branch $headRefName so 'candidate-a-recovery' runs against this PR's head..."
    $scheduleWorkflowDispatchedAtUtc = (Get-Date).ToUniversalTime().AddSeconds(-30)
    Get-GhOrFail @("workflow", "run", "Tests", "--repo", $Repo, "--ref", $headRefName) | Out-Null
    $scheduleWorkflowDispatched = $true
    Write-Host "  Dispatched. Verifying its 'Candidate A posterior recovery' job directly by dispatched run ID - gh pr checks/statusCheckRollup do not reliably surface a workflow_dispatch run's job outcome for this PR (see Wait-ForDispatchedRecoveryJobSuccess's comment above)."
    Wait-ForDispatchedRecoveryJobSuccess -Repo $Repo -WorkflowName "Tests" -HeadRefName $headRefName -ExpectedHeadSha $capturedHeadSha -JobName "Candidate A posterior recovery" -DispatchedAfterUtc $scheduleWorkflowDispatchedAtUtc -TimeoutMinutes $TimeoutMinutes -PollIntervalSeconds $PollIntervalSeconds
    Write-Host "  Verified: 'Candidate A posterior recovery' succeeded for head $capturedHeadSha."
}

# ---------------------------------------------------------------------------
# Automatic Fold refit recovery path detection (Work Package 0, structural-
# causal authority reconciliation, after PR #286) - mirrors the Candidate A
# detection above for the fold-refit evidence pipeline's own three modules.
# ---------------------------------------------------------------------------

if (-not $RequireFoldRefitRecovery) {
    Write-Host "Checking whether PR #$PRNumber changes any Fold refit recovery module..."
    $diffOutput = Get-GhOrFail @("pr", "diff", "$PRNumber", "--repo", $Repo, "--name-only")
    $changedFiles = ($diffOutput -join "`n") -split "`r?`n" | Where-Object { $_ }
    $hitPaths = $FoldRefitPaths | Where-Object { $changedFiles -contains $_ }
    if ($hitPaths.Count -gt 0) {
        Write-Host "  Fold refit recovery affected module(s) changed: $($hitPaths -join ', ')"
        Write-Host "  Automatically requiring Fold refit recovery before merge."
        $RequireFoldRefitRecovery = $true
    }
    else {
        Write-Host "  No Fold refit recovery affected module changed - recovery not required."
    }
}

if ($RequireFoldRefitRecovery) {
    Write-Host "REQUIRE-FOLD-REFIT-RECOVERY set: a successful, non-skipped 'Fold refit recovery' run is now required before merge."
    if ($scheduleWorkflowDispatched) {
        Write-Host "  A workflow_dispatch run of 'Tests' was already triggered above (for candidate-a-recovery) - it also runs fold-refit-recovery, so no second dispatch is needed."
    }
    else {
        Write-Host "Dispatching a workflow_dispatch run of 'Tests' on branch $headRefName so 'fold-refit-recovery' runs against this PR's head..."
        $scheduleWorkflowDispatchedAtUtc = (Get-Date).ToUniversalTime().AddSeconds(-30)
        Get-GhOrFail @("workflow", "run", "Tests", "--repo", $Repo, "--ref", $headRefName) | Out-Null
        $scheduleWorkflowDispatched = $true
        Write-Host "  Dispatched."
    }
    Write-Host "  Verifying its 'Fold refit recovery' job directly by dispatched run ID - gh pr checks/statusCheckRollup do not reliably surface a workflow_dispatch run's job outcome for this PR (see Wait-ForDispatchedRecoveryJobSuccess's comment above)."
    Wait-ForDispatchedRecoveryJobSuccess -Repo $Repo -WorkflowName "Tests" -HeadRefName $headRefName -ExpectedHeadSha $capturedHeadSha -JobName "Fold refit recovery" -DispatchedAfterUtc $scheduleWorkflowDispatchedAtUtc -TimeoutMinutes $TimeoutMinutes -PollIntervalSeconds $PollIntervalSeconds
    Write-Host "  Verified: 'Fold refit recovery' succeeded for head $capturedHeadSha."
}

Write-Host "Waiting for PR #$PRNumber's checks to appear..."

$deadline = (Get-Date).AddMinutes($TimeoutMinutes)
$checksAppeared = $false

while ((Get-Date) -lt $deadline) {
    $checksJson = Get-GhOrFail @("pr", "checks", "$PRNumber", "--repo", $Repo, "--json", "name,state,bucket")
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

$knownChecks = @($RequiredChecks) + @($AllowedSkippedChecks) + @($InformationalChecks)
$allGreen = $false

while ((Get-Date) -lt $deadline) {
    $checksJson = Get-GhOrFail @("pr", "checks", "$PRNumber", "--repo", $Repo, "--json", "name,state,bucket")
    $checks = $checksJson | ConvertFrom-Json

    # Fail closed on a check this script does not recognise at all (brief
    # §5.13 "Static check list" - a newly-added CI job must block merge
    # until explicitly classified, not be silently ignored).
    $unexpected = $checks | Where-Object { $knownChecks -notcontains $_.name } |
        Select-Object -ExpandProperty name -Unique
    if ($unexpected.Count -gt 0) {
        throw "PR #$PRNumber reports unclassified CI check(s) this script does not " +
            "recognise: $($unexpected -join ', '). Refusing to merge until each is " +
            "explicitly added to -RequiredChecks, -AllowedSkippedChecks, or " +
            "-InformationalChecks - a newly-added CI job must not be silently ignored."
    }

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

Write-Host "All required checks green for PR #$PRNumber."

# ---------------------------------------------------------------------------
# Re-verify the head immediately before merging (brief §5.13 "PR-head race")
# and merge only the exact head whose checks were observed, using gh's own
# expected-head guard as a second, server-side layer of protection.
# ---------------------------------------------------------------------------

Write-Host "Re-checking PR #$PRNumber's head SHA immediately before merge..."
$prNow = (Get-GhOrFail @("pr", "view", "$PRNumber", "--repo", $Repo, "--json", "headRefOid")) | ConvertFrom-Json
if ($prNow.headRefOid -ne $capturedHeadSha) {
    throw "PR #$PRNumber's head moved from $capturedHeadSha to $($prNow.headRefOid) after " +
        "checks were observed green. Refusing to merge a commit whose checks were not " +
        "verified against this exact head - re-run this script against the new head."
}

Write-Host "Head confirmed unchanged ($capturedHeadSha). Merging (method: $MergeMethod)..."

$mergeFlag = "--$MergeMethod"
Get-GhOrFail @("pr", "merge", "$PRNumber", "--repo", $Repo, $mergeFlag, "--delete-branch=false", "--match-head-commit", $capturedHeadSha) | Out-Null

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

if ($DangerouslySkipMainVerification) {
    Write-Host "WARNING: -DangerouslySkipMainVerification set - not waiting for the push-triggered main workflow."
    Write-Host "WARNING: this bypasses the required 'green PR -> merge -> green main -> next work package' contract."
    Write-Host "WARNING: this flag must never be used by the autonomous work-package loop."
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
