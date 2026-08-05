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
confirmation -> Curve Bank shows both official curve artifacts -> Scenario
Planner shows the imported saved scenario.
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from ancestry_mmm.tests.support.lifecycle_fixture import build_lifecycle_project_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 60


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def bundle_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bundle_dir = tmp_path_factory.mktemp("lifecycle-browser-bundle")
    return build_lifecycle_project_bundle(bundle_dir / "lifecycle-bundle.zip")


@pytest.fixture(scope="module")
def streamlit_base_url() -> Iterator[str]:
    port = _free_port()
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
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
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
            # Terminate before reading stdout: if the process is still alive
            # (e.g. a slow/hung import rather than a clean exit), `read()`
            # blocks until EOF and would ignore STARTUP_TIMEOUT_SECONDS
            # entirely, leaving CI to sit until the outer job timeout kills
            # pytest with no useful RuntimeError.
            if proc.poll() is None:
                proc.terminate()
            try:
                output = proc.communicate(timeout=10)[0]
            except subprocess.TimeoutExpired:
                proc.kill()
                output = proc.communicate(timeout=10)[0]
            text = output.decode(errors="replace") if output else ""
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
    expect(
        page.get_by_test_id("stSidebarUserContent").get_by_text(
            "Marketing Mix Modelling"
        )
    ).to_be_visible(timeout=30_000)

    # --- Project Export/Import page: upload the deterministic bundle -----
    # `exact=True` throughout this test: Streamlit renders a visually-hidden
    # anchor-link duplicate of every heading's text (`#some-heading`), and
    # some captions/labels are near-duplicates of a heading's text - both
    # trip Playwright's strict-mode "resolved to N elements" check on a
    # plain substring `get_by_text` match.
    page.get_by_role("link", name="Project Export & Recovery").click()
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
    expect(
        page.get_by_text(re.compile(r"Restored \d+ official curve artifact"))
    ).to_be_visible(timeout=30_000)

    # --- Curve Bank: both official curve artifacts are visible -----------
    page.get_by_role("link", name="Results & Curve Bank").click()
    expect(page.get_by_text("Official curve artifacts", exact=True)).to_be_visible(
        timeout=30_000
    )
    # `.first`: the artifact ID legitimately appears twice (the artifact's
    # own expander label, and a row in the curve-bank history grid) -
    # either is sufficient proof the artifact rendered.
    expect(page.get_by_text("lifecycle-model-input", exact=True).first).to_be_visible(
        timeout=30_000
    )
    expect(page.get_by_text("lifecycle-monetary", exact=True).first).to_be_visible(
        timeout=30_000
    )

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
    expect(page.get_by_text("Saved scenarios", exact=True)).to_be_visible(
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
