"""Work Package 2 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`,
brief §5.13/§8.5): contract coverage for
`scripts/wait_for_pr_green_then_merge.ps1`, the substitute merge gate this
repository relies on because it has no effective required-check branch
protection on `main`.

This is not PowerShell unit testing (this repository has no Pester
tooling, and the Python test jobs run on `ubuntu-latest` with no
guaranteed `pwsh`/`powershell` binary - the authoritative syntax check is
`.github/workflows/tests.yml`'s "Windows tooling" job, which parses every
`scripts/*.ps1` file under Windows PowerShell 5.1). These are static,
literal assertions against the script's own text - the same style
`test_repository_status_conformance.py` already uses for anti-drift
checks - guarding the specific safety properties the brief requires so a
future edit cannot silently drop one of them.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "wait_for_pr_green_then_merge.ps1"


def _read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_exists():
    assert SCRIPT.exists(), f"{SCRIPT} must exist - the required autonomous merge gate."


def test_script_parses_under_powershell_if_available():
    """Mirrors (does not replace) the authoritative Windows-PowerShell-5.1
    parse check in the "Windows tooling" CI job - skipped here if no
    PowerShell binary is present (e.g. the Linux Python test runners)."""
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if exe is None:
        pytest.skip("no pwsh/powershell binary available on this runner")
    result = subprocess.run(
        [
            exe,
            "-NoProfile",
            "-Command",
            "$e=$null; [System.Management.Automation.Language.Parser]::"
            f"ParseFile('{SCRIPT}', [ref]$null, [ref]$e) | Out-Null; "
            "if ($e.Count -gt 0) { $e | Format-List; exit 1 } else { exit 0 }",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{SCRIPT} failed to parse:\n{result.stdout}\n{result.stderr}"
    )


class TestRemoteAuthPreflight:
    """Brief §5.13 "Auth/remote preflight": before trusting local state,
    verify the origin remote, fetch it, and verify gh authentication,
    handling a stale invalid GITHUB_TOKEN override safely."""

    def test_verifies_origin_remote_matches_expected_repo(self):
        text = _read()
        assert "git remote get-url origin" in text
        assert "does not reference the expected repository" in text

    def test_fetches_origin_before_trusting_local_state(self):
        text = _read()
        assert "git fetch origin --quiet" in text

    def test_verifies_gh_authentication(self):
        text = _read()
        assert "gh auth status" in text

    def test_handles_stale_invalid_github_token_override(self):
        text = _read()
        assert "GITHUB_TOKEN" in text
        assert "Remove-Item Env:\\GITHUB_TOKEN" in text


class TestPrHeadRaceGuard:
    """Brief §5.13 "PR-head race": capture the head SHA once, before
    waiting, and refuse to merge if it moved - gh's own
    --match-head-commit is a second, server-side layer on top."""

    def test_captures_head_sha_before_waiting_for_checks(self):
        text = _read()
        capture_index = text.index("$capturedHeadSha = $pr.headRefOid")
        wait_index = text.index(
            "Write-Host \"Waiting for PR #$PRNumber's checks to appear"
        )
        assert capture_index < wait_index, (
            "the head SHA must be captured before the script starts waiting "
            "for checks, not derived only at merge time"
        )

    def test_re_verifies_head_immediately_before_merge(self):
        text = _read()
        assert "Re-checking PR #$PRNumber's head SHA immediately before merge" in text
        assert "$prNow.headRefOid -ne $capturedHeadSha" in text

    def test_merge_call_uses_match_head_commit_guard(self):
        text = _read()
        merge_line = next(line for line in text.splitlines() if '"pr", "merge"' in line)
        assert "--match-head-commit" in merge_line
        assert "$capturedHeadSha" in merge_line


class TestUnclassifiedCheckFailsClosed:
    """Brief §5.13 "Static check list": a newly-added CI job not on any
    known list must block merge, not be silently ignored."""

    def test_computes_unexpected_checks_against_all_three_lists(self):
        text = _read()
        assert "InformationalChecks" in text
        assert (
            "$knownChecks = @($RequiredChecks) + @($AllowedSkippedChecks) + @($InformationalChecks)"
            in text
        )
        assert "reports unclassified CI check(s)" in text


class TestCandidateARecoveryIsAutomatic:
    """Brief §5.13 "Candidate A recovery remains caller-selected": the
    gate must detect Candidate A model-mathematics changes itself, not
    depend solely on the caller remembering -RequireCandidateARecovery."""

    def test_diffs_the_pr_for_candidate_a_affected_modules(self):
        text = _read()
        assert '"pr", "diff", "$PRNumber"' in text
        assert "CandidateAPaths" in text

    def test_candidate_a_paths_match_the_ci_gate_check_job(self):
        """This script's -CandidateAPaths default must list the same
        files as .github/workflows/tests.yml's
        candidate-a-recovery-gate-check job's candidate_a_paths array -
        the two are separately maintained (a PowerShell merge-gate
        decision vs. a bash CI annotation) but must agree on the governed
        boundary (REQ-SEARCH-002's affected modules)."""
        script_text = _read()
        workflow_text = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        expected_paths = [
            "ancestry_mmm/core/search_capacity.py",
            "ancestry_mmm/core/search_candidate_a_recovery.py",
            "ancestry_mmm/core/search_decision_package.py",
            "ancestry_mmm/core/graph_model_compiler.py",
            "ancestry_mmm/core/hierarchical_model.py",
            "ancestry_mmm/core/causal_graph.py",
        ]
        for path in expected_paths:
            assert path in script_text, (
                f"{SCRIPT} is missing Candidate A affected module {path!r} "
                "in -CandidateAPaths."
            )
            assert path in workflow_text, (
                f".github/workflows/tests.yml's candidate-a-recovery-gate-check "
                f"job is missing Candidate A affected module {path!r} - it has "
                "drifted from the merge-gate script's -CandidateAPaths."
            )

    def test_auto_detection_dispatches_the_recovery_workflow(self):
        text = _read()
        assert '"workflow", "run", "Tests"' in text
        assert "--ref" in text


class TestFoldRefitRecoveryIsAutomatic:
    """Work Package 0 (structural-causal authority reconciliation, after PR
    #286): the gate must detect Fold refit recovery module changes itself,
    mirroring TestCandidateARecoveryIsAutomatic above, not depend solely on
    the caller remembering -RequireFoldRefitRecovery."""

    def test_diffs_the_pr_for_fold_refit_affected_modules(self):
        text = _read()
        assert '"pr", "diff", "$PRNumber"' in text
        assert "FoldRefitPaths" in text

    def test_fold_refit_paths_match_the_ci_gate_check_job(self):
        """This script's -FoldRefitPaths default must list the same files
        as .github/workflows/tests.yml's fold-refit-recovery-gate-check
        job's fold_refit_paths array - the two are separately maintained
        (a PowerShell merge-gate decision vs. a bash CI annotation) but
        must agree on the governed boundary (REQ-LEAK-001/REQ-STAB-001
        affected modules)."""
        script_text = _read()
        workflow_text = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(
            encoding="utf-8"
        )
        expected_paths = [
            "ancestry_mmm/application/fold_refit_service.py",
            "ancestry_mmm/core/validation_folds.py",
            "ancestry_mmm/core/structural_stability.py",
        ]
        for path in expected_paths:
            assert path in script_text, (
                f"{SCRIPT} is missing Fold refit recovery affected module "
                f"{path!r} in -FoldRefitPaths."
            )
            assert path in workflow_text, (
                f".github/workflows/tests.yml's fold-refit-recovery-gate-check "
                f"job is missing Fold refit recovery affected module {path!r} "
                "- it has drifted from the merge-gate script's -FoldRefitPaths."
            )

    def test_fold_refit_paths_excludes_the_shared_production_fit_path(self):
        """Deliberate scoping decision (docs/decision_log.md, "Structural-
        causal authority reconciliation (Work Package 0)"): the shared
        production fit path fold-refit-service calls through must not be
        in the automatic trigger set, or the expensive recovery job would
        fire on nearly every modelling PR."""
        script_text = _read()
        fold_refit_block = script_text.split("[string[]]$FoldRefitPaths = @(", 1)[
            1
        ].split(")", 1)[0]
        excluded_paths = [
            "model_fit_service.py",
            "core/models.py",
            "core/predict.py",
            "market_specific_predict.py",
            "hierarchical_model.py",
            "market_specific_model.py",
        ]
        for path in excluded_paths:
            assert path not in fold_refit_block, (
                f"-FoldRefitPaths must not include {path!r} - it is part of "
                "the shared production fit path, already exercised by every "
                "PR's blocking test suite; including it would make the "
                "expensive recovery job fire on nearly every modelling PR"
            )

    def test_auto_detection_dispatches_the_recovery_workflow(self):
        text = _read()
        assert '"workflow", "run", "Tests"' in text
        assert "RequireFoldRefitRecovery" in text

    def test_fold_refit_recovery_verified_via_dispatched_run_not_pr_checks(self):
        """Tooling-defect fix (found while merging PR #288, part of Work
        Package 1): `Fold refit recovery` is required by calling
        `Wait-ForDispatchedRecoveryJobSuccess` directly, never by adding it
        to `-RequiredChecks` and trusting `gh pr checks` to observe a
        `workflow_dispatch` run's outcome - see
        `TestDispatchedRecoveryJobVerificationFixesPRChecksBlindSpot`."""
        text = _read()
        assert (
            'Wait-ForDispatchedRecoveryJobSuccess -Repo $Repo -WorkflowName "Tests" '
            "-HeadRefName $headRefName -ExpectedHeadSha $capturedHeadSha "
            '-JobName "Fold refit recovery"' in text
        )
        # The old, broken mechanism must not have crept back in - it could
        # never observe a real pass for this check (see the class above's
        # docstring and Wait-ForDispatchedRecoveryJobSuccess's own comment).
        assert (
            '$AllowedSkippedChecks = $AllowedSkippedChecks | Where-Object { $_ -ne "Fold refit recovery" }'
            not in text
        )
        assert '$RequiredChecks = $RequiredChecks + "Fold refit recovery"' not in text

    def test_fold_refit_recovery_gate_check_is_informational(self):
        text = _read()
        assert '"Fold refit recovery gate check"' in text


class TestDispatchedRecoveryJobVerificationFixesPRChecksBlindSpot:
    """Tooling-defect fix, found and diagnosed while merging PR #288 (Work
    Package 1 part 2): GitHub creates a *separate* check-suite per trigger
    event, so a `workflow_dispatch` run of `Tests` and the PR's own
    `pull_request`-triggered run of `Tests` produce two distinct
    check-suites for the identical head SHA. This repository has no
    branch-protection required-checks configuration, so `gh pr checks`/the
    PR's `statusCheckRollup` only ever reflect the *first* (pull_request)
    suite's result for a given check name - confirmed live: a genuinely
    successful, manually verified `Fold refit recovery` dispatched run
    still showed as `SKIPPED` in both `gh pr checks` and `gh pr view --json
    statusCheckRollup`, while `gh api .../commits/<sha>/check-runs` (which
    lists every check-suite's check-runs, not just one) showed the real
    `conclusion: success` for that exact run ID. Both `Candidate A
    posterior recovery` and `Fold refit recovery` are required via
    `Wait-ForDispatchedRecoveryJobSuccess`, which resolves the specific
    dispatched run by `gh run list --event workflow_dispatch` (filtered to
    the expected head SHA and a dispatch timestamp) and polls that run's
    specific job by name via `gh run view <run-id> --json headSha,jobs` -
    never trusting the PR-level checks view for these two check names."""

    def test_helper_function_is_defined_before_first_use(self):
        text = _read()
        definition_index = text.index("function Wait-ForDispatchedRecoveryJobSuccess")
        first_call_index = text.index("Wait-ForDispatchedRecoveryJobSuccess -Repo")
        assert definition_index < first_call_index

    def test_helper_locates_the_run_by_workflow_dispatch_event_and_head_sha(self):
        text = _read()
        helper_body = text.split("function Wait-ForDispatchedRecoveryJobSuccess", 1)[
            1
        ].split("\n}\n", 1)[0]
        assert '"run", "list"' in helper_body
        assert '"--event", "workflow_dispatch"' in helper_body
        assert "ExpectedHeadSha" in helper_body

    def test_helper_verifies_the_specific_job_not_the_whole_run_conclusion(self):
        """A dispatched run also runs unrelated schedule-only jobs (e.g.
        Deterministic attribution recovery) that may independently fail,
        making the *run's* overall conclusion an unreliable proxy - the
        helper must inspect the named job's own status/conclusion inside
        `.jobs`, never `run.conclusion`."""
        text = _read()
        helper_body = text.split("function Wait-ForDispatchedRecoveryJobSuccess", 1)[
            1
        ].split("\n}\n", 1)[0]
        assert '"run", "view", "$runId", "--repo", $Repo, "--json", "headSha,jobs"' in (
            helper_body
        )
        assert "$run.jobs | Where-Object { $_.name -eq $JobName }" in helper_body
        assert "$job.status" in helper_body
        assert "$job.conclusion" in helper_body

    def test_helper_refuses_to_trust_a_run_for_the_wrong_head_sha(self):
        text = _read()
        helper_body = text.split("function Wait-ForDispatchedRecoveryJobSuccess", 1)[
            1
        ].split("\n}\n", 1)[0]
        assert "$run.headSha -ne $ExpectedHeadSha" in helper_body

    def test_helper_retries_a_not_yet_visible_job_within_a_grace_window(self):
        """Live regression (found while merging PR #288, after PR #289's fix
        was already on `main`): a dispatched run's `jobs` list can briefly
        lag the run itself becoming queryable - locating a real dispatched
        run succeeded on the very first poll, then an immediate `gh run
        view --json jobs` call for that same run did not yet include `Fold
        refit recovery` in a ~17-job workflow, even though the job was
        present moments later. Treating "not found yet" as an immediate
        hard failure (the original version of this helper) makes the gate
        fail closed on a false positive; the fix must retry within a grace
        window before concluding the job is genuinely absent (a real
        `-FoldRefitPaths`/`-CandidateAPaths` workflow drift)."""
        text = _read()
        helper_body = text.split("function Wait-ForDispatchedRecoveryJobSuccess", 1)[
            1
        ].split("\n}\n", 1)[0]
        assert "jobNeverSeenGraceDeadline" in helper_body
        not_found_index = helper_body.index("if (-not $job) {")
        grace_check_index = helper_body.index(
            "(Get-Date) -lt $jobNeverSeenGraceDeadline"
        )
        continue_index = helper_body.index("continue", not_found_index)
        throw_index = helper_body.index("still has no job named", not_found_index)
        # The grace check and a `continue` (retry) must appear before the
        # hard failure inside the same "not found" branch - never the other
        # way around.
        assert not_found_index < grace_check_index < continue_index < throw_index

    def test_candidate_a_recovery_also_verified_via_dispatched_run_not_pr_checks(self):
        """The same PR-checks blind spot applies symmetrically to Candidate
        A's dispatch path - fixed with the identical mechanism, not a
        one-off special case for fold-refit only."""
        text = _read()
        assert (
            'Wait-ForDispatchedRecoveryJobSuccess -Repo $Repo -WorkflowName "Tests" '
            "-HeadRefName $headRefName -ExpectedHeadSha $capturedHeadSha "
            '-JobName "Candidate A posterior recovery"' in text
        )
        assert (
            '$AllowedSkippedChecks = $AllowedSkippedChecks | Where-Object { $_ -ne "Candidate A posterior recovery" }'
            not in text
        )
        assert (
            '$RequiredChecks = $RequiredChecks + "Candidate A posterior recovery"'
            not in text
        )

    def test_both_recovery_checks_remain_classified_as_allowed_skipped(self):
        """The PR-checks view will still forever show both check names as
        `skipping` (from the permanent, always-skipped pull_request-suite
        entry) - that must stay a harmless, recognised state (never
        `-RequiredChecks`, which would re-introduce the bug), not trip the
        unclassified-check fail-closed guard."""
        text = _read()
        allowed_skipped_block = text.split("[string[]]$AllowedSkippedChecks = @(", 1)[
            1
        ].split(")", 1)[0]
        assert "Candidate A posterior recovery" in allowed_skipped_block
        assert "Fold refit recovery" in allowed_skipped_block


class TestPostMergeVerificationCannotBeSilentlyBypassed:
    """Brief §5.13 "Post-merge verification must not be bypassed": the
    required contract is green PR -> merge -> green main -> next work
    package, not merely green PR -> merge. The bypass flag must not be
    named so it could be reached for by habit ("-SkipMainVerification")."""

    def test_bypass_flag_is_not_named_skip_main_verification(self):
        text = _read()
        assert "$SkipMainVerification" not in text, (
            "the unsafe post-merge-verification bypass must not be named "
            "-SkipMainVerification - it was deliberately renamed to "
            "-DangerouslySkipMainVerification so it cannot be reached for by "
            "habit, and so it greps distinctly from ordinary usage."
        )
        assert "DangerouslySkipMainVerification" in text

    def test_bypass_emits_a_warning_naming_the_broken_contract(self):
        text = _read()
        assert "green PR -> merge -> green main -> next work package" in text

    def test_default_path_waits_for_the_push_triggered_main_workflow(self):
        text = _read()
        assert (
            'Where-Object { $_.headSha -eq $mergeSha -and $_.event -eq "push" }' in text
        )


class TestBrowserLifecycleInstallIsBounded:
    """The Browser lifecycle journey's Chromium install step once hung for
    over two hours (`uv run playwright install --with-deps chromium` stalled
    in Ubuntu/Azure package-mirror dependency installation before any
    browser test started). The fix is bounded time, not weakened tests: a
    job-level timeout, a step-level timeout, one bounded retry of the
    install, and the real browser tests untouched. CI must still fail when
    the install genuinely cannot complete.

    A second, subtler failure mode is also guarded: when attempt 1 timed
    out, playwright's `sudo apt-get` child survived `timeout`'s process-
    group signal and kept holding /var/lib/dpkg/lock-frontend, so attempt 2
    died immediately with "E: Could not get lock" and main went red. The
    step must therefore reap orphaned apt/dpkg processes and wait for the
    dpkg lock between attempts."""

    WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "tests.yml"

    @classmethod
    def _browser_job_text(cls) -> str:
        workflow_text = cls.WORKFLOW_PATH.read_text(encoding="utf-8")
        start = workflow_text.index("  browser:\n")
        # The next top-level job after `browser:` in this workflow file.
        end_marker = "\n  # -- Deterministic attribution recovery"
        end = workflow_text.index(end_marker, start)
        return workflow_text[start:end]

    def test_browser_job_has_a_bounded_overall_timeout(self):
        browser_job = self._browser_job_text()
        job_header = browser_job.split("- name:", 1)[0]
        assert "timeout-minutes:" in job_header, (
            "the browser job must carry a job-level timeout-minutes so it can "
            "never hang a CI/merge wait indefinitely."
        )

    def test_chromium_install_step_is_bounded_with_one_retry(self):
        browser_job = self._browser_job_text()
        assert "Install Chromium" in browser_job
        install_step = browser_job.split("- name: Install Chromium", 1)[1].split(
            "- name:", 1
        )[0]
        assert "timeout-minutes:" in install_step, (
            "the Chromium install step must carry its own bounded timeout-minutes."
        )
        # One bounded retry: a fixed two-attempt loop, each attempt killed
        # by `timeout` so a hung apt/mirror install cannot stall again.
        assert "for attempt in 1 2" in install_step
        assert "timeout --signal=TERM" in install_step
        assert "after 2 bounded attempts" in install_step
        assert "exit 1" in install_step

    def test_chromium_install_reaps_orphaned_apt_between_attempts(self):
        """A timed-out attempt must not leave an orphaned apt-get/dpkg
        holding /var/lib/dpkg/lock-frontend - the 2026-08-19 main-CI
        failure mode where attempt 2 died immediately with 'E: Could not
        get lock'. The step must reap orphans, repair dpkg, and wait for
        the lock before retrying."""
        browser_job = self._browser_job_text()
        install_step = browser_job.split("- name: Install Chromium", 1)[1].split(
            "- name:", 1
        )[0]
        assert "reap_orphaned_apt" in install_step
        assert "pkill -KILL -x apt-get" in install_step
        assert "pkill -KILL -x dpkg" in install_step
        assert "dpkg --configure -a" in install_step
        assert "wait_for_dpkg_lock" in install_step
        assert "pgrep -x apt-get" in install_step

    def test_browser_tests_are_not_weakened_or_skipped(self):
        """The install hang must never be worked around by weakening or
        skipping the actual browser lifecycle tests - they keep running
        with their own bounded timeout."""
        browser_job = self._browser_job_text()
        test_step = browser_job.split(
            "- name: Run deterministic browser lifecycle journey", 1
        )[1].split("- name:", 1)[0]
        assert (
            "uv run pytest ancestry_mmm/tests/test_official_lifecycle_browser.py"
            in test_step
        )
        assert "test_causal_graph_editor_browser.py" in test_step
        assert "--browser chromium" in test_step
        assert "timeout-minutes:" in test_step
