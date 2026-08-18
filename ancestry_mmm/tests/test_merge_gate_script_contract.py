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

    def test_fold_refit_recovery_removed_from_allowed_skipped_when_required(self):
        text = _read()
        assert (
            '$AllowedSkippedChecks = $AllowedSkippedChecks | Where-Object { $_ -ne "Fold refit recovery" }'
            in text
        )
        assert '$RequiredChecks = $RequiredChecks + "Fold refit recovery"' in text

    def test_fold_refit_recovery_gate_check_is_informational(self):
        text = _read()
        assert '"Fold refit recovery gate check"' in text


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
