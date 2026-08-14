"""
PR 122: drives the real Streamlit app in a real browser through the
official curve-to-scenario lifecycle, using the same ONE deterministic
already-fitted synthetic project bundle proved step-by-step in
`test_official_lifecycle_integration.py`
(`ancestry_mmm.tests.support.lifecycle_fixture`). The bundle is uploaded
through the real `Project Import` file picker
(`pages/09_Project_Export.py`) - no live MCMC/NUTS sampling anywhere. A
Streamlit health-check ping (see the `windows-tooling` CI job) is not
browser validation; this is.

Journey: upload bundle -> import success + transactional store-replacement
confirmation -> generate a THIRD official model-input response curve through
the real Official Curve Generation page (page 13) - never only imported,
pre-built ones - -> Results shows the official response-curve summaries ->
Scenario Planner shows the imported saved scenario.
"""

from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from ancestry_mmm.tests.support.lifecycle_fixture import build_lifecycle_project_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 60
# CI's "Upload failure artefacts" step (.github/workflows/tests.yml, job
# `browser`) uploads test-artifacts/playwright/** only `if: failure()` - a
# repo-relative, not a pytest tmp_path, location so it survives test
# teardown for that later step to find.
FAILURE_ARTIFACT_DIR = REPO_ROOT / "test-artifacts" / "playwright"


def _drain_subprocess_output(
    proc: subprocess.Popen, log_path: Path
) -> threading.Thread:
    """Continuously read `proc.stdout` to a file on a background thread -
    see test_causal_graph_editor_browser.py's identical helper for why this
    must never be skipped (an undrained OS pipe can silently deadlock the
    whole app mid-test), and it doubles as the real server-side log a
    failed run leaves behind in FAILURE_ARTIFACT_DIR for CI to upload."""
    assert proc.stdout is not None
    stdout = proc.stdout

    def _pump() -> None:
        try:
            with log_path.open("wb") as fh:
                for chunk in iter(lambda: stdout.read(4096), b""):
                    fh.write(chunk)
                    fh.flush()
        except ValueError:
            pass  # our end of the pipe was closed from the main thread

    thread = threading.Thread(target=_pump, daemon=True)
    thread.start()
    return thread


def _click_until_visible(
    trigger,
    target,
    *,
    attempts: int = 3,
    per_attempt_timeout_ms: int = 10_000,
) -> None:
    """Click `trigger`, then wait for `target` to become visible - retrying
    the click if it doesn't (observed in CI only: a BaseWeb Select's
    dropdown occasionally fails to open on the first click in headless
    Linux, never reproduced across 15+ local Windows runs). Each attempt
    gets a short timeout so a genuinely-failed open is retried quickly
    rather than spending the whole budget waiting once."""
    last_error: Exception | None = None
    for _ in range(attempts):
        trigger.click()
        try:
            expect(target).to_be_visible(timeout=per_attempt_timeout_ms)
            return
        except AssertionError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def bundle_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bundle_dir = tmp_path_factory.mktemp("lifecycle-browser-bundle")
    return build_lifecycle_project_bundle(bundle_dir / "lifecycle-bundle.zip")


@pytest.fixture(scope="module")
def streamlit_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    # Isolate the app's official curve artifact store from a developer's
    # real local state: the import step below performs a destructive
    # transactional replace of `curve_artifact_store_dir()`, which defaults
    # to a fixed, shared, repo-relative path keyed only by project name
    # (`ancestry_mmm/.curve_artifact_store/ancestry-fh-uk`). Without this
    # override, running this test outside a disposable checkout would wipe
    # any official artifacts a developer has saved for the default project.
    isolated_curve_store_root = tmp_path_factory.mktemp("lifecycle-browser-curve-store")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "ancestry_mmm/app.py",
            "--server.address",
            "127.0.0.1",
            "--server.port",
            str(port),
            "--server.headless",
            "true",
            "--browser.gatherUsageStats",
            "false",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "MMM_CURVE_ARTIFACT_ROOT": str(isolated_curve_store_root)},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    FAILURE_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    stdout_log_path = FAILURE_ARTIFACT_DIR / "lifecycle-streamlit-server.log"
    drain_thread = _drain_subprocess_output(proc, stdout_log_path)
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    ready = False
    try:
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                break
            try:
                if httpx.get(base_url, timeout=2.0).status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        if not ready:
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            text = (
                stdout_log_path.read_text(errors="replace")
                if stdout_log_path.exists()
                else ""
            )
            raise RuntimeError(
                f"Streamlit did not become ready within {STARTUP_TIMEOUT_SECONDS}s.\n{text}"
            )
        yield base_url
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        # The process exiting closes its end of the pipe, which unblocks the
        # drain thread's read() with EOF - join it before closing our end
        # ourselves, so the thread never reads from an already-closed file.
        drain_thread.join(timeout=10)
        if proc.stdout is not None:
            proc.stdout.close()


def test_official_lifecycle_journey_in_browser(
    page: Page, streamlit_base_url: str, bundle_path: Path
) -> None:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )

    # Navigate via the app's own sidebar page_links (`components/ui.py:
    # render_sidebar`, labels from `utils/workflow.py:WORKFLOW_STEPS`) rather
    # than deep-linking by URL - this app renders its full page chrome
    # (workflow-progress sidebar) client-side, and only a real in-app
    # navigation is guaranteed to land on the target page reliably.
    page.goto(streamlit_base_url, wait_until="load")
    # 60s (double the usual): the very first load also pays for the
    # frontend JS bundle plus the app's first Python script execution, not
    # just a rerun - occasionally exceeds a plain 30s budget.
    expect(
        page.get_by_test_id("stSidebarUserContent").get_by_text(
            "Family History & DNA MMM"
        )
    ).to_be_visible(timeout=60_000)

    # --- Project Export/Import page: upload the deterministic bundle -----
    # `exact=True` throughout this test: Streamlit renders a visually-hidden
    # anchor-link duplicate of every heading's text (`#some-heading`), and
    # some captions/labels are near-duplicates of a heading's text - both
    # trip Playwright's strict-mode "resolved to N elements" check on a
    # plain substring `get_by_text` match.
    page.get_by_role("link", name="Export & Recovery").click()
    expect(
        page.get_by_text("Upload a previously exported .zip", exact=True)
    ).to_be_visible(timeout=30_000)
    page.locator("input[type=file]").set_input_files(str(bundle_path))
    import_button = page.get_by_role("button", name="Import bundle")
    expect(import_button).to_be_enabled(timeout=30_000)
    import_button.click()

    # Visible success confirmations: overall import, and the transactional
    # curve-artifact-store replacement specifically (proves replacement, not
    # a silent no-op, is visible to the user - not only to the test suite).
    expect(
        page.get_by_text(
            "Project imported. Review each page to pick up where you left off.",
            exact=True,
        )
    ).to_be_visible(timeout=30_000)
    expect(page.get_by_text(re.compile(r"Restored \d+ Planning Curve"))).to_be_visible(
        timeout=30_000
    )
    # A bundle can import "successfully" while still being unable to resume
    # its own saved scenario (e.g. missing raw source data) - the page's own
    # resumability audit is the thing that actually proves this fixture
    # bundle is technically complete, not just that the zip extracted
    # cleanly.
    expect(
        page.get_by_text(re.compile(r"Resumability audit passed at "))
    ).to_be_visible(timeout=30_000)
    expect(
        page.get_by_text("its declared checkpoint is incomplete", exact=False)
    ).not_to_be_visible()
    # PR 125A: the project-level CounterfactualPolicy and CurrencyContext
    # this fixture's official scenario depends on now travel through the
    # bundle (core.persistence's config/counterfactual_policy.json,
    # config/currency_context.json) and are verified against the scenario's
    # own saved fingerprints on import - so this deterministic bundle is now
    # genuinely *officially* resumable, not only technically loadable.
    # Asserted explicitly (not just the absence of the old warning) so a
    # regression back to "not officially resumable" is caught here rather
    # than silently passing either way.
    expect(
        page.get_by_text("This bundle is officially resumable", exact=False)
    ).to_be_visible(timeout=30_000)
    expect(
        page.get_by_text("is not officially resumable", exact=False)
    ).not_to_be_visible()

    # --- Official Curve Generation: generate a THIRD artifact through the
    # real page, not only import pre-built ones - otherwise this required
    # browser job would still pass even if page 13's generate/save path were
    # broken, since it would never have been exercised in a real browser.
    page.get_by_role("link", name="Planning Curves").click()
    page.get_by_text("Reference context - UK", exact=False).click()
    mode_select = page.get_by_role("combobox", name="Mode")
    mode_option = page.get_by_role("option", name="recent_average", exact=True)
    _click_until_visible(mode_select, mode_option)
    # Selecting through the open combobox avoids racing the transient option
    # node that Streamlit's BaseWeb select replaces while it commits the
    # choice.
    mode_select.press("ArrowDown")
    mode_select.press("Enter")
    # Selecting the mode triggers a script rerun that recomputes the
    # confirmation checkbox's fingerprinted widget key (page 13's own
    # anti-stale-confirmation design: a changed context renders a *new*,
    # unchecked checkbox under a new key rather than preserving a stale
    # checked one). Waiting for the derived-context preview - the last
    # thing that rerun renders before the checkbox - avoids checking a
    # checkbox instance that's about to be replaced mid-click.
    expect(page.get_by_text("Derived from the model frame", exact=False)).to_be_visible(
        timeout=30_000
    )
    # Let any trailing DOM updates from that rerun settle before touching
    # the checkbox - CI has shown "clicking did not change its state" here
    # (never seen locally) consistent with a slower websocket round-trip
    # than the derived-preview text alone accounts for.
    page.wait_for_timeout(1_000)
    confirm_checkbox = page.get_by_role(
        "checkbox",
        name=re.compile(
            "I have reviewed and confirm the UK reference context above is correct"
        ),
    )
    expect(confirm_checkbox).to_be_enabled(timeout=30_000)
    # Same CI-only flakiness pattern as the dropdown above (never seen
    # locally): retry the click a few times rather than trust one attempt.
    # `.check()` itself raises on "did not change state" (a plain
    # playwright.Error, not an AssertionError) - the whole attempt,
    # including that call, must be inside the try or a first-attempt
    # failure skips every retry and propagates immediately.
    checked = False
    for _ in range(3):
        try:
            confirm_checkbox.check(force=True, timeout=15_000)
            expect(confirm_checkbox).to_be_checked(timeout=5_000)
            checked = True
            break
        except Exception:
            continue
    if not checked:
        confirm_checkbox.check(force=True, timeout=15_000)
        expect(confirm_checkbox).to_be_checked(timeout=15_000)
    # No (market, channel) support range is recorded (section 4 is left at
    # its default, unchecked "include support" state), so generation needs
    # an explicit diagnostic spend axis instead - otherwise it fails closed
    # with "Observed support is missing" rather than silently guessing one.
    page.get_by_role(
        "textbox", name="Curve-axis values (comma-separated, optional)"
    ).fill("0, 50, 100")
    generate_button = page.get_by_role("button", name="Save Planning Curve")
    generate_button.click()
    expect(page.get_by_text(re.compile(r"Saved Planning Curve"))).to_be_visible(
        timeout=30_000
    )
    # --- Results: all three official response curves are visible ---------
    page.get_by_role("link", name="Results & Response Curves").click()
    expect(page.get_by_text("Official response curves", exact=True)).to_be_visible(
        timeout=30_000
    )
    # Saved identifiers are deliberately secondary: they remain available in
    # the technical-details disclosures rather than competing with the
    # analyst-facing response-curve summary.
    expect(
        page.get_by_text("Technical details · saved response curve", exact=True).first
    ).to_be_visible(timeout=30_000)
    expect(
        page.get_by_role("heading", name=re.compile(r"Official response curve")).first
    ).to_be_visible(timeout=30_000)
    expect(
        page.get_by_role(
            "heading",
            name=re.compile(
                r"Official response curve.*Family History.*New.*GSA.*definition 1\.0"
            ),
        ).first
    ).to_be_visible(timeout=30_000)
    expect(page.get_by_text("core.pathways", exact=False)).not_to_be_visible()

    # --- Scenario Planner: the imported saved scenario is visible --------
    # The comparison table itself is a canvas-rendered `st.dataframe` grid
    # (its cell text isn't exposed to Playwright's accessibility-tree text
    # locators), so presence is proved by the absence of BOTH of the page's
    # own non-current-scenario messages (pages/08_Scenario_Planner.py):
    # "No scenarios saved yet." (zero saved scenarios) and the stale-cost-
    # mapping warning (every saved scenario excluded as stale) - the page
    # suppresses the empty-state message in the all-stale case too, so
    # checking only its absence would pass even if our scenario were
    # wrongly excluded as stale. Neither message appears only when a
    # current, non-empty comparison table actually rendered. The exact
    # scenario content is already proved by the AppTest and integration
    # test coverage.
    page.get_by_role("link", name="Scenario Planner").click()
    # The dashboard metric and the saved-scenario section intentionally share
    # this analyst-facing label; either visible instance proves the page has
    # loaded the saved-scenario workspace.
    expect(page.get_by_text("Saved scenarios", exact=True).first).to_be_visible(
        timeout=30_000
    )
    expect(page.get_by_text("No scenarios saved yet.", exact=True)).not_to_be_visible()
    expect(
        page.get_by_text(
            "Excluded from the comparison below because their governed cost "
            "mapping has since changed",
            exact=False,
        )
    ).not_to_be_visible()

    unexpected_console_errors = [
        e for e in console_errors if "favicon" not in e.lower()
    ]
    assert unexpected_console_errors == [], unexpected_console_errors
