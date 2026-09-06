"""Static invariant checks for the Claude fallback PR-review workflow.

These do not execute the workflow (that requires a real GitHub Actions run
triggered by a genuine Codex quota comment). They guard the security
properties that make it safe to keep on `main`: the review prompt must come
from the trusted default branch rather than the PR under review, the exact
PR head must be re-verified before/after the review, a given head can only
consume one Claude review, third-party Actions must be pinned to a commit
SHA, and the trigger stays fallback-only (never a plain `pull_request`
review)."""

import re
from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "claude-fallback-review.yml"
)
PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "claude"
    / "fallback-review-prompt.md"
)

CODEX_BOT_LOGIN = "chatgpt-codex-connector[bot]"
QUOTA_MESSAGE = "You have reached your Codex usage limits for code reviews"
COMPLETION_MARKER_PREFIX = "<!-- claude-fallback-review:"
SHA_PINNED_USES = re.compile(r"^[^@]+@[0-9a-f]{40}(\s|$)")


def _load_workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _load_workflow_yaml() -> dict:
    return yaml.safe_load(_load_workflow_text())


def _job(doc: dict) -> dict:
    return doc["jobs"]["claude-fallback-review"]


def _steps(doc: dict) -> list:
    return _job(doc)["steps"]


def _step(doc: dict, name: str) -> dict:
    for step in _steps(doc):
        if step.get("name") == name:
            return step
    raise AssertionError(f"no workflow step named {name!r}")


class TestWorkflowFilesExist:
    def test_workflow_file_exists(self):
        assert WORKFLOW_PATH.is_file()

    def test_prompt_file_exists(self):
        assert PROMPT_PATH.is_file()


class TestYamlSyntax:
    def test_workflow_is_valid_yaml(self):
        doc = _load_workflow_yaml()
        assert isinstance(doc, dict)

    def test_workflow_has_the_expected_job(self):
        doc = _load_workflow_yaml()
        assert "claude-fallback-review" in doc["jobs"]


class TestTriggerIsFallbackOnly:
    def test_trigger_is_issue_comment_only(self):
        doc = _load_workflow_yaml()
        # PyYAML 1.1 parses the unquoted `on:` key as boolean True.
        trigger = doc.get("on", doc.get(True))
        assert trigger is not None, "no top-level trigger found"
        assert set(trigger.keys()) == {"issue_comment"}, (
            "workflow must trigger only on issue_comment - a plain "
            "pull_request trigger would review every PR/commit, defeating "
            "the fallback-only design"
        )
        assert trigger["issue_comment"]["types"] == ["created"]

    def test_no_pull_request_trigger_anywhere_in_the_file(self):
        text = _load_workflow_text()
        # Guards against a `pull_request:` trigger being reintroduced even
        # if `on:` still nominally parses as issue_comment-only above.
        assert not re.search(r"^\s*pull_request\s*:", text, re.MULTILINE)


class TestGateConditions:
    def test_job_requires_exact_codex_bot_login(self):
        doc = _load_workflow_yaml()
        condition = _job(doc)["if"]
        assert CODEX_BOT_LOGIN in condition

    def test_job_requires_exact_quota_message(self):
        doc = _load_workflow_yaml()
        condition = _job(doc)["if"]
        assert QUOTA_MESSAGE in condition

    def test_job_condition_does_not_allow_arbitrary_bots(self):
        doc = _load_workflow_yaml()
        condition = _job(doc)["if"]
        assert "allowed_bots" not in condition  # not the gate; see Claude step
        # the gate string itself must name one exact login, not a wildcard
        assert "*" not in condition


class TestTrustedPromptBoundary:
    def test_prompt_is_loaded_via_the_github_api_from_the_default_branch(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Load review prompt from trusted default branch")
        run = step["run"]
        assert "contents/.github/claude/fallback-review-prompt.md" in run
        assert "ref=${DEFAULT_BRANCH}" in run
        assert step["env"]["DEFAULT_BRANCH"] == (
            "${{ github.event.repository.default_branch }}"
        )

    def test_prompt_is_never_read_from_the_pr_checkout_working_tree(self):
        text = _load_workflow_text()
        # The historical vulnerable pattern: reading the prompt file straight
        # off disk after checking out the PR head, which lets a PR rewrite
        # its own review instructions.
        assert "cat .github/claude/fallback-review-prompt.md" not in text

    def test_prompt_step_runs_before_the_pr_head_is_checked_out(self):
        doc = _load_workflow_yaml()
        names = [step.get("name") for step in _steps(doc)]
        prompt_index = names.index("Load review prompt from trusted default branch")
        checkout_index = names.index("Checkout exact PR head")
        assert prompt_index < checkout_index


class TestExactHeadHandling:
    def test_checkout_uses_the_exact_pr_head_ref(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Checkout exact PR head")
        assert step["with"]["ref"] == "refs/pull/${{ github.event.issue.number }}/head"

    def test_checked_out_sha_is_verified_against_the_resolved_head(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Verify checked-out SHA did not move")
        assert step["env"]["EXPECTED_HEAD_SHA"] == ("${{ steps.pr.outputs.head_sha }}")
        assert "exit 1" in step["run"]

    def test_moved_head_is_not_reported_as_current(self):
        doc = _load_workflow_yaml()
        recheck = _step(doc, "Re-check PR head before posting review")
        assert "current=false" in recheck["run"]
        assert "current=true" in recheck["run"]

        post = _step(doc, "Post Claude fallback review")
        assert "steps.current.outputs.current == 'true'" in post["if"]

        stale = _step(doc, "Report stale fallback review")
        assert "steps.current.outputs.current == 'false'" in stale["if"]


class TestDuplicatePrevention:
    def test_same_head_sha_cannot_consume_claude_twice(self):
        doc = _load_workflow_yaml()
        dup = _step(doc, "Skip if Claude already reviewed this exact head")
        assert "${HEAD_SHA}" in dup["run"]
        assert dup["env"]["HEAD_SHA"] == "${{ steps.pr.outputs.head_sha }}"

        for name in (
            "Load review prompt from trusted default branch",
            "Checkout exact PR head",
            "Verify checked-out SHA did not move",
            "Run Claude fallback review",
        ):
            step = _step(doc, name)
            condition = step.get("if", "")
            assert "steps.duplicate.outputs.skip != 'true'" in condition, (
                f"step {name!r} must be gated on the duplicate-skip check"
            )

    def test_completion_marker_is_scoped_to_the_head_sha(self):
        doc = _load_workflow_yaml()
        post = _step(doc, "Post Claude fallback review")
        assert COMPLETION_MARKER_PREFIX in post["run"]
        assert "${HEAD_SHA}" in post["run"]


class TestFailureDoesNotFakeCompletion:
    def test_failure_comment_carries_no_completion_marker(self):
        doc = _load_workflow_yaml()
        failure_step = _step(doc, "Report Claude fallback failure")
        assert COMPLETION_MARKER_PREFIX not in failure_step["run"]

    def test_failure_step_only_runs_on_genuine_failure(self):
        doc = _load_workflow_yaml()
        failure_step = _step(doc, "Report Claude fallback failure")
        assert "failure()" in failure_step["if"]


class TestSecretsAreNeverPrinted:
    def test_no_step_echoes_a_secret_directly(self):
        text = _load_workflow_text()
        for line in text.splitlines():
            stripped = line.strip()
            if re.match(r"^(echo|printf)\b", stripped) and "secrets." in stripped:
                raise AssertionError(f"a secret may be printed to logs: {line!r}")

    def test_oauth_token_is_only_referenced_as_an_input_value(self):
        doc = _load_workflow_yaml()
        claude_step = _step(doc, "Run Claude fallback review")
        assert claude_step["with"]["claude_code_oauth_token"] == (
            "${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}"
        )


class TestThirdPartyActionsArePinned:
    def test_every_uses_reference_is_pinned_to_a_full_commit_sha(self):
        doc = _load_workflow_yaml()
        checked = 0
        for step in _steps(doc):
            uses = step.get("uses")
            if uses is None:
                continue
            checked += 1
            assert SHA_PINNED_USES.match(uses), (
                f"{uses!r} is not pinned to a 40-character commit SHA"
            )
        assert checked >= 2, "expected at least checkout + claude-code-action"

    def test_checkout_is_pinned_to_the_documented_v4_4_0(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Checkout exact PR head")
        # YAML strips trailing `# comment`s, so the parsed value is SHA-only;
        # the human-readable version tag is checked against the raw text.
        assert step["uses"] == (
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
        )
        assert (
            "actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
            in _load_workflow_text()
        )

    def test_claude_action_is_pinned_to_the_documented_v1_0_217(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Run Claude fallback review")
        assert step["uses"] == (
            "anthropics/claude-code-action@9c5ddab2e6d17b83ea679153b31f1d5f023cf636"
        )
        assert (
            "anthropics/claude-code-action@9c5ddab2e6d17b83ea679153b31f1d5f023cf636"
            " # v1.0.217" in _load_workflow_text()
        )


class TestPermissionsAreMinimal:
    def test_only_the_needed_scopes_are_granted(self):
        doc = _load_workflow_yaml()
        permissions = doc["permissions"]
        assert permissions == {
            "contents": "read",
            "pull-requests": "read",
            "issues": "write",
            "actions": "read",
        }

    def test_no_id_token_permission_is_requested(self):
        doc = _load_workflow_yaml()
        assert "id-token" not in doc["permissions"]

    def test_contents_permission_is_read_only(self):
        doc = _load_workflow_yaml()
        assert doc["permissions"]["contents"] == "read"


class TestClaudeIsReviewOnly:
    def test_edit_and_write_tools_are_disallowed(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Run Claude fallback review")
        claude_args = step["with"]["claude_args"]
        assert "--disallowedTools" in claude_args
        assert '"Edit,Write"' in claude_args

    def test_no_bash_tool_is_granted(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Run Claude fallback review")
        claude_args = step["with"]["claude_args"]
        assert "allowedTools" not in claude_args or "Bash" not in claude_args

    def test_allowed_bots_is_scoped_to_codex_only(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Run Claude fallback review")
        assert step["with"]["allowed_bots"] == CODEX_BOT_LOGIN

    def test_additional_permissions_is_read_only(self):
        doc = _load_workflow_yaml()
        step = _step(doc, "Run Claude fallback review")
        assert step["with"]["additional_permissions"].strip() == "actions: read"

    def test_structured_output_uses_the_current_action_field_name(self):
        doc = _load_workflow_yaml()
        post = _step(doc, "Post Claude fallback review")
        assert post["env"]["STRUCTURED_OUTPUT"] == (
            "${{ steps.claude.outputs.structured_output }}"
        )
