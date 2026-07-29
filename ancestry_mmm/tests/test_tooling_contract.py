"""Source-inspection tests for development-tooling contract (PR 70A).

These tests verify that the MCP configuration, launcher, checker and
documentation follow the agreed contract without needing a full shell
environment. They inspect committed files for expected patterns.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MCP_JSON = REPO_ROOT / ".mcp.json"
START_DEV_APP = REPO_ROOT / "scripts" / "start_dev_app.ps1"
CHECK_PREREQS = REPO_ROOT / "scripts" / "check_mcp_prereqs.ps1"
MCP_PATHS = REPO_ROOT / "scripts" / "mcp_paths.ps1"
SETUP_TOOLING = REPO_ROOT / "scripts" / "setup_dev_tooling.ps1"
DOCS_FILE = REPO_ROOT / "docs" / "development" / "mcp_development_tooling.md"
VERIFICATION_REPORT = (
    REPO_ROOT / "docs" / "development" / "mcp_verification_2026-07-29.md"
)


# ── Helper ──


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ps1_read_text(path: Path) -> str:
    """Read a PowerShell script, normalising line endings."""
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


# ── MCP package pinning ──


class TestMcpPackagesArePinned:
    """Every MCP package in .mcp.json must use an exact version, not @latest."""

    def _load_mcp_json(self) -> dict:
        return json.loads(MCP_JSON.read_text(encoding="utf-8"))

    def test_no_at_latest_in_context7(self):
        config = self._load_mcp_json()
        args = config["mcpServers"]["context7"]["args"]
        joined = " ".join(args)
        assert "@latest" not in joined, f"Context7 args contain @latest: {args}"
        # Must be pinned to an exact version
        assert re.search(r"@upstash/context7-mcp@\d+\.\d+\.\d+", joined), (
            f"Context7 not pinned to semver: {args}"
        )

    def test_no_at_latest_in_playwright(self):
        config = self._load_mcp_json()
        args = config["mcpServers"]["playwright"]["args"]
        joined = " ".join(args)
        assert "@latest" not in joined, f"Playwright args contain @latest: {args}"
        assert re.search(r"@playwright/mcp@\d+\.\d+\.\d+", joined), (
            f"Playwright not pinned to semver: {args}"
        )

    def test_context7_has_exact_version(self):
        config = self._load_mcp_json()
        args = config["mcpServers"]["context7"]["args"]
        joined = " ".join(args)
        match = re.search(r"@upstash/context7-mcp@(\d+\.\d+\.\d+)", joined)
        assert match is not None, f"Cannot parse Context7 version from: {args}"
        version = match.group(1)
        parts = [int(x) for x in version.split(".")]
        assert len(parts) == 3, f"Version {version} is not semver"
        assert parts[0] >= 0, f"Malformed version: {version}"

    def test_playwright_has_exact_version(self):
        config = self._load_mcp_json()
        args = config["mcpServers"]["playwright"]["args"]
        joined = " ".join(args)
        match = re.search(r"@playwright/mcp@(\d+\.\d+\.\d+)", joined)
        assert match is not None, f"Cannot parse Playwright version from: {args}"
        version = match.group(1)
        parts = [int(x) for x in version.split(".")]
        assert len(parts) == 3, f"Version {version} is not semver"


# ── Launcher contract (uv, not .venv) ──


class TestStartDevAppUsesUv:
    """start_dev_app.ps1 must use uv run, not a hard-coded .venv path."""

    def test_does_not_reference_venv_scripts_python(self):
        content = _ps1_read_text(START_DEV_APP)
        # The forbidden pattern: anything that hard-codes .venv\Scripts\python.exe
        forbidden = re.compile(r"\.venv[\\/]Scripts[\\/]python\.exe", re.IGNORECASE)
        assert not forbidden.search(content), (
            "start_dev_app.ps1 hard-codes .venv\\Scripts\\python.exe"
        )

    def test_uses_uv_run(self):
        content = _ps1_read_text(START_DEV_APP)
        assert "uv run" in content, "start_dev_app.ps1 does not contain 'uv run'"

    def test_checks_uv_on_path(self):
        content = _ps1_read_text(START_DEV_APP)
        assert "Get-Command uv" in content or "uv" in content, (
            "start_dev_app.ps1 does not reference uv"
        )

    def test_sources_mcp_paths(self):
        content = _ps1_read_text(START_DEV_APP)
        assert "mcp_paths.ps1" in content, (
            "start_dev_app.ps1 does not source mcp_paths.ps1"
        )


# ── Checker contract (uv, canonical paths) ──


class TestCheckMcpPrereqsUsesUv:
    """check_mcp_prereqs.ps1 must use uv, not a hard-coded .venv path."""

    def test_does_not_reference_venv_scripts_python(self):
        content = _ps1_read_text(CHECK_PREREQS)
        forbidden = re.compile(r"\.venv[\\/]Scripts[\\/]python\.exe", re.IGNORECASE)
        assert not forbidden.search(content), (
            "check_mcp_prereqs.ps1 hard-codes .venv\\Scripts\\python.exe"
        )

    def test_uses_uv_run(self):
        content = _ps1_read_text(CHECK_PREREQS)
        assert "uv run" in content, "check_mcp_prereqs.ps1 does not contain 'uv run'"

    def test_sources_mcp_paths(self):
        content = _ps1_read_text(CHECK_PREREQS)
        assert "mcp_paths.ps1" in content, (
            "check_mcp_prereqs.ps1 does not source mcp_paths.ps1"
        )


# ── Directory contract consistency ──


class TestDirectoryContractConsistency:
    """mcp_paths.ps1, start_dev_app.ps1 and check_mcp_prereqs.ps1 must agree
    on the operational and optional directory lists."""

    def test_mcp_paths_defines_operational_dirs(self):
        content = _ps1_read_text(MCP_PATHS)
        assert "OperationalDirs" in content
        assert "OptionalDirs" in content

    def test_setup_tooling_sources_mcp_paths(self):
        content = _ps1_read_text(SETUP_TOOLING)
        assert "mcp_paths.ps1" in content

    def test_setup_tooling_creates_operational_dirs(self):
        content = _ps1_read_text(SETUP_TOOLING)
        assert "$OperationalPaths" in content

    def test_checker_sources_mcp_paths(self):
        content = _ps1_read_text(CHECK_PREREQS)
        assert "mcp_paths.ps1" in content

    def test_checker_uses_operational_paths(self):
        content = _ps1_read_text(CHECK_PREREQS)
        assert "$OperationalPaths" in content


# ── Documentation wording ──


class TestDocumentationWording:
    """Documentation must not claim Playwright is localhost-only or that
    Hugging Face is configured."""

    def test_no_localhost_only_playwright_claim_in_docs(self):
        content = _read_text(DOCS_FILE)
        assert "localhost-only" not in content, (
            "Docs describe Playwright as 'localhost-only'"
        )

    def test_hugging_face_not_configured(self):
        content = _read_text(DOCS_FILE)
        # Should say "Documented, not connected" or similar, not "Configured"
        assert "Documented, not connected" in content, (
            "Docs do not correctly state Hugging Face is documented, not connected"
        )

    def test_allowed_origins_not_security_boundary(self):
        content = _read_text(DOCS_FILE)
        # The phrase may appear with bold markers (**...**); use a flexible match.
        assert re.search(r"not a network security boundary", content, re.IGNORECASE), (
            "Docs do not state --allowed-origins is not a security boundary"
        )


# ── Verification report exists ──


class TestVerificationReport:
    """A sanitised verification report must exist and contain expected sections."""

    def test_verification_report_exists(self):
        assert VERIFICATION_REPORT.exists(), (
            "mcp_verification_2026-07-29.md does not exist"
        )

    def test_verification_report_has_mcp_sections(self):
        content = _read_text(VERIFICATION_REPORT)
        for mcp in ("GitHub MCP", "Context7 MCP", "Playwright MCP", "Hugging Face"):
            assert mcp in content, f"Verification report missing section for {mcp}"

    def test_verification_report_has_write_statement(self):
        content = _read_text(VERIFICATION_REPORT)
        assert "Write calls made" in content, (
            "Verification report missing write-call statement"
        )

    def test_verification_report_has_known_limitations(self):
        content = _read_text(VERIFICATION_REPORT)
        assert "Known limitations" in content, (
            "Verification report missing known limitations"
        )
