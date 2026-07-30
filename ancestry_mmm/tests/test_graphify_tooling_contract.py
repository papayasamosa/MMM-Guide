"""Source-inspection tests for the Graphify D-drive tooling contract (PR 82A).

These tests verify the Graphify install/checker/launcher scripts and their
`.mcp.json`/documentation wiring follow the agreed D-drive-only contract
without needing a full Windows shell environment (they run on the ubuntu
Python test jobs too - pure text/JSON inspection only, no PowerShell
execution). Behavioural verification of the scripts themselves (they
actually create only D-drive directories, actually reject a C-drive root,
actually resolve the D-drive executable, actually reject a missing graph)
runs in the `windows-tooling` CI job, which executes the real scripts.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GRAPHIFY_PATHS = REPO_ROOT / "scripts" / "graphify_paths.ps1"
SETUP_GRAPHIFY = REPO_ROOT / "scripts" / "setup_graphify.ps1"
CHECK_GRAPHIFY_PREREQS = REPO_ROOT / "scripts" / "check_graphify_prereqs.ps1"
RUN_GRAPHIFY_MCP = REPO_ROOT / "scripts" / "run_graphify_mcp.ps1"
MCP_JSON = REPO_ROOT / ".mcp.json"
GRAPHIFY_DOC = REPO_ROOT / "docs" / "development" / "graphify.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"

GRAPHIFY_SCRIPTS = [
    GRAPHIFY_PATHS,
    SETUP_GRAPHIFY,
    CHECK_GRAPHIFY_PREREQS,
    RUN_GRAPHIFY_MCP,
]

# A literal Windows user-profile path: C:\Users\<name>\... with a real
# segment after Users (not a doc placeholder like <name> or %USERNAME%).
LITERAL_USER_PATH = re.compile(r"C:\\Users\\[A-Za-z0-9_.\-]+\\", re.IGNORECASE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ps1_read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _ps1_code_only(path: Path) -> str:
    """PowerShell content with `<# ... #>` block comments and `#` line
    comments stripped, so assertions about *instructions/commands* are not
    tripped up by prose that documents what is forbidden (e.g. a synopsis
    explaining "does not call `uv tool update-shell`")."""
    content = _ps1_read(path)
    content = re.sub(r"<#.*?#>", "", content, flags=re.DOTALL)
    lines = [line for line in content.split("\n") if not line.strip().startswith("#")]
    return "\n".join(lines)


class TestGraphifyScriptsExist:
    def test_all_four_scripts_exist(self):
        for path in GRAPHIFY_SCRIPTS:
            assert path.exists(), f"missing required Graphify script: {path}"


class TestGraphifyScriptsAreAscii:
    """PowerShell 5.1 compatibility, matching the existing MCP script contract."""

    def test_all_graphify_ps1_files_are_ascii(self):
        for path in GRAPHIFY_SCRIPTS:
            content = path.read_bytes()
            non_ascii = [i for i, b in enumerate(content) if b > 127]
            assert len(non_ascii) == 0, (
                f"{path.name} has non-ASCII bytes at positions: {non_ascii[:20]}"
            )


class TestGraphifyPinnedVersion:
    """graphifyy[mcp] must be pinned to the documented version, not @latest."""

    def test_paths_script_pins_exact_version(self):
        content = _ps1_read(GRAPHIFY_PATHS)
        match = re.search(r'GraphifyPinnedVersion\s*=\s*"(\d+\.\d+\.\d+)"', content)
        assert match is not None, (
            "graphify_paths.ps1 does not pin an exact semver version"
        )

    def test_setup_installs_pinned_spec_not_latest(self):
        content = _ps1_read(SETUP_GRAPHIFY)
        assert "graphifyy[mcp]==" in content or "GraphifyPackageSpec" in content, (
            "setup_graphify.ps1 does not install a pinned graphifyy[mcp] spec"
        )
        assert "@latest" not in content

    def test_doc_states_pinned_version(self):
        content = _read(GRAPHIFY_DOC)
        assert "graphifyy[mcp]==0.9.30" in content, (
            "graphify.md does not show the pinned install command"
        )


class TestGraphifyNoUpdateShell:
    """Graphify must never call `uv tool update-shell` (D-drive rule). The
    scripts' own docstrings *describe* this prohibition in prose - only
    actual (non-comment) code is checked here."""

    def test_setup_script_never_calls_update_shell(self):
        code = _ps1_code_only(SETUP_GRAPHIFY)
        assert "update-shell" not in code

    def test_launcher_never_calls_update_shell(self):
        code = _ps1_code_only(RUN_GRAPHIFY_MCP)
        assert "update-shell" not in code

    def test_doc_does_not_instruct_update_shell(self):
        content = _read(GRAPHIFY_DOC)
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith("- **"):
                # Prose that explains the prohibition, not an instruction to
                # run it, is fine; only reject actual command lines.
                continue
            assert not re.match(r"^\$?\s*uv tool update-shell", stripped), (
                f"graphify.md instructs running update-shell: {stripped!r}"
            )


class TestGraphifyNoUserProfilePath:
    """Nothing may direct Graphify to install under %USERPROFILE%\\.local as
    an active instruction (only as documentation of what is forbidden)."""

    def test_setup_script_does_not_target_userprofile(self):
        code = _ps1_code_only(SETUP_GRAPHIFY)
        assert "USERPROFILE" not in code

    def test_launcher_does_not_target_userprofile(self):
        code = _ps1_code_only(RUN_GRAPHIFY_MCP)
        assert "USERPROFILE" not in code

    def test_paths_script_does_not_target_userprofile(self):
        code = _ps1_code_only(GRAPHIFY_PATHS)
        assert "USERPROFILE" not in code


class TestNoMachineSpecificUserPaths:
    """No committed Graphify file may hard-code a real C:\\Users\\<literal> path."""

    def test_no_literal_user_path_in_scripts_or_docs(self):
        for path in [*GRAPHIFY_SCRIPTS, GRAPHIFY_DOC, MCP_JSON, CI_WORKFLOW]:
            content = _read(path)
            match = LITERAL_USER_PATH.search(content)
            assert match is None, (
                f"{path.name} contains a literal user path: {match.group(0)!r}"
            )


class TestGraphifyPathsSourcesDDriveDefault:
    def test_defaults_to_d_ancestry_mmm(self):
        content = _ps1_read(GRAPHIFY_PATHS)
        assert "D:\\Ancestry-MMM" in content

    def test_supports_mmm_dev_root_override(self):
        content = _ps1_read(GRAPHIFY_PATHS)
        assert "MMM_DEV_ROOT" in content

    def test_defines_d_drive_check_helper(self):
        content = _ps1_read(GRAPHIFY_PATHS)
        assert "Test-GraphifyPathOnDDrive" in content

    def test_defines_root_containment_helper(self):
        content = _ps1_read(GRAPHIFY_PATHS)
        assert "Test-GraphifyPathUnderRoot" in content


class TestSetupGraphifyContract:
    def test_sources_graphify_paths(self):
        content = _ps1_read(SETUP_GRAPHIFY)
        assert "graphify_paths.ps1" in content

    def test_rejects_non_d_drive_root_before_installing(self):
        code = _ps1_code_only(SETUP_GRAPHIFY)
        assert "Test-GraphifyPathOnDDrive" in code
        # The D-drive check must appear before the actual `uv tool install`
        # invocation (not merely mentioned in a docstring/comment).
        check_idx = code.index("Test-GraphifyPathOnDDrive")
        install_idx = code.index("uv tool install")
        assert check_idx < install_idx, (
            "setup_graphify.ps1 does not verify the D-drive root before installing"
        )

    def test_sets_uv_tool_env_vars_before_install(self):
        content = _ps1_read(SETUP_GRAPHIFY)
        for var in ["UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_CACHE_DIR", "TEMP", "TMP"]:
            assert f"env:{var}" in content, f"setup_graphify.ps1 does not set {var}"

    def test_uses_force_flag(self):
        content = _ps1_read(SETUP_GRAPHIFY)
        assert "--force" in content


class TestCheckGraphifyPrereqsContract:
    def test_sources_graphify_paths(self):
        content = _ps1_read(CHECK_GRAPHIFY_PREREQS)
        assert "graphify_paths.ps1" in content

    def test_checks_d_drive_root(self):
        content = _ps1_read(CHECK_GRAPHIFY_PREREQS)
        assert "Test-GraphifyPathOnDDrive" in content

    def test_is_read_only(self):
        content = _ps1_read(CHECK_GRAPHIFY_PREREQS)
        forbidden = ["uv tool install", "uv tool uninstall", "Remove-Item", "New-Item"]
        for token in forbidden:
            assert token not in content, (
                f"check_graphify_prereqs.ps1 is not read-only: found {token!r}"
            )


class TestRunGraphifyMcpLauncherContract:
    def test_sources_graphify_paths(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "graphify_paths.ps1" in content

    def test_checks_d_drive_root(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "Test-GraphifyPathOnDDrive" in content

    def test_checks_graph_json_exists(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "GraphifyGraphJson" in content
        assert "Test-Path $GraphifyGraphJson" in content

    def test_resolves_executable_by_full_path_not_ambient_command(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        # Must invoke the resolved exe path, never a bare ambient lookup.
        assert "Get-Command graphify-mcp" not in content
        assert "& $exePath" in content

    def test_checks_effective_bin_dir_under_root(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "effectiveBinDir" in content
        assert "Test-GraphifyPathUnderRoot" in content

    def test_owns_temp_for_child_process(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "$env:TEMP = $GraphifyTempDir" in content
        assert "$env:TMP = $GraphifyTempDir" in content

    def test_propagates_exit_code(self):
        content = _ps1_read(RUN_GRAPHIFY_MCP)
        assert "exit $LASTEXITCODE" in content


class TestMcpJsonReferencesLauncher:
    def _load(self) -> dict:
        return json.loads(MCP_JSON.read_text(encoding="utf-8"))

    def test_mcp_json_is_valid_json(self):
        self._load()  # raises on invalid JSON

    def test_graphify_project_entry_exists(self):
        config = self._load()
        assert "graphify-project" in config["mcpServers"]

    def test_graphify_project_calls_launcher_script(self):
        config = self._load()
        entry = config["mcpServers"]["graphify-project"]
        joined = json.dumps(entry)
        assert "run_graphify_mcp.ps1" in joined, (
            "graphify-project entry does not reference the D-drive launcher script"
        )

    def test_graphify_project_does_not_invoke_bare_ambient_command(self):
        config = self._load()
        entry = config["mcpServers"]["graphify-project"]
        assert entry["command"] != "graphify-mcp", (
            "graphify-project still invokes the ambient graphify-mcp command directly"
        )


class TestGraphifyDocDDriveCompliance:
    def test_doc_references_setup_script(self):
        content = _read(GRAPHIFY_DOC)
        assert "setup_graphify.ps1" in content

    def test_doc_references_checker_script(self):
        content = _read(GRAPHIFY_DOC)
        assert "check_graphify_prereqs.ps1" in content

    def test_doc_references_launcher_script(self):
        content = _read(GRAPHIFY_DOC)
        assert "run_graphify_mcp.ps1" in content

    def test_doc_does_not_use_app_projects_path_as_canonical_example(self):
        content = _read(GRAPHIFY_DOC)
        assert 'cwd = "D:\\\\Ancestry-MMM\\\\repos\\\\MMM-Guide"' in content, (
            "graphify.md Codex example does not use the canonical D:\\Ancestry-MMM\\repos\\MMM-Guide path"
        )

    def test_doc_executable_location_is_d_drive(self):
        content = _read(GRAPHIFY_DOC)
        assert "D:\\Ancestry-MMM\\tools\\uv\\bin" in content


class TestGraphifyCiJob:
    """The windows-tooling CI job must actually exercise the Graphify scripts."""

    def test_installs_graphify(self):
        content = _read(CI_WORKFLOW)
        assert "setup_graphify.ps1" in content

    def test_runs_graphify_checker(self):
        content = _read(CI_WORKFLOW)
        assert "check_graphify_prereqs.ps1" in content

    def test_tests_c_drive_rejection(self):
        content = _read(CI_WORKFLOW)
        assert "C:\\Ancestry-MMM-Should-Fail" in content

    def test_tests_missing_graph_rejection(self):
        content = _read(CI_WORKFLOW)
        assert "run_graphify_mcp.ps1" in content
        assert "reject a missing graph" in content.lower()


class TestPyprojectAndLockUntouchedByGraphifyTooling:
    """PR 82A is dev-tooling-only: it must never edit pyproject.toml/uv.lock."""

    def test_graphify_scripts_do_not_reference_pyproject_or_lock(self):
        for path in GRAPHIFY_SCRIPTS:
            code = _ps1_code_only(path)
            assert "pyproject.toml" not in code
            assert "uv.lock" not in code
