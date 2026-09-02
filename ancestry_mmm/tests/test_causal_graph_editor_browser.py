"""
REQ-GRAPH-001 work package E: drives the real Streamlit app in a real
browser through the graph-first causal-configuration editor
(pages/14_Causal_Graph.py), using the same deterministic synthetic project
bundle test_official_lifecycle_browser.py uses
(ancestry_mmm.tests.support.lifecycle_fixture) - no live MCMC/NUTS sampling.

Journey: load synthetic project -> open Causal Graph -> seed a media
(intervention) node and an outcome node from Structure -> create a
branded-demand mediator node and its edge (engine-unsupported - the
current PyMC engine cannot compile a mediated pathway yet, REQ-GRAPH-001's
own engine-capability boundary) -> attempt a prohibited reverse edge
(outcome -> intervention) -> the graph is reported invalid and Approve is
disabled - a categorical, deterministic rejection, not merely discouraged
-> remove both the bad reverse edge and the mediated edge via the property
panel (the mediator node itself is left as a harmless orphan) -> add the
real, engine-supported TV_Brand -> New edge -> inspect the model-plan
preview -> save a draft -> approve -> prepare model configuration succeeds
and binds a structural fingerprint -> move a node (layout-only) -> the
prepared configuration stays current -> edit the surviving edge's lag (a
structural change) -> the prepared configuration goes stale -> build a
project export bundle and verify the downloaded file actually carries this
approved graph (graph portability). Every removal in this journey goes
through the property panel's explicit Remove-edge button, never a
canvas-side delete gesture.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
from typing import Iterator

import httpx
import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, expect

from ancestry_mmm.tests.support.lifecycle_fixture import build_lifecycle_project_bundle

REPO_ROOT = Path(__file__).resolve().parents[2]
STARTUP_TIMEOUT_SECONDS = 60
TV_BRAND_ACTIVITY_NODE_ID = "activity:UK:tv-brand-paid"
NEW_OUTCOME_NODE_LABEL = "Family History · New · GSA (definition 1.0)"
# CI's "Upload failure artefacts" step (.github/workflows/tests.yml, job
# `browser`) uploads test-artifacts/playwright/** only `if: failure()` - a
# repo-relative, not a pytest tmp_path, location so it survives test
# teardown for that later step to find.
FAILURE_ARTIFACT_DIR = REPO_ROOT / "test-artifacts" / "playwright"


def _select_option(
    page: Page,
    combobox_name: str,
    option_name,
    *,
    nth: int = 0,
    verify_text: str | None = None,
) -> None:
    """Select an option in the `combobox_name` selectbox (by exact string
    or a compiled regex `option_name`), verifying the combobox's own
    displayed text afterward and retrying the entire open -> select
    sequence (not just the open) if it doesn't stick - BaseWeb Select's
    dropdown has been observed to occasionally accept a click without the
    underlying Streamlit widget value actually changing, a step short of
    the already-documented "dropdown fails to open" flakiness alone.
    A Streamlit rerun can also swap the open listbox out from under the
    click between the visibility check and the click landing, which raises
    a PlaywrightTimeoutError (not an AssertionError) from `option.click()`
    itself - that must be retried the same way, not left to escape.
    `verify_text` overrides what to expect in the combobox afterward when
    `option_name` is a regex (there is no single literal string to compare
    against otherwise)."""
    combobox = page.get_by_role("combobox", name=combobox_name).nth(nth)
    is_literal = isinstance(option_name, str)
    expected_text = verify_text if verify_text is not None else option_name
    last_error: Exception | None = None
    for _ in range(4):
        try:
            combobox.click()
            option = (
                page.get_by_role("option", name=option_name, exact=True)
                if is_literal
                else page.get_by_role("option", name=option_name)
            )
            expect(option).to_be_visible(timeout=8_000)
            option.click(timeout=8_000)
            expect(combobox).to_have_value(expected_text, timeout=5_000)
            return
        except (AssertionError, PlaywrightTimeoutError) as exc:
            last_error = exc
            page.keyboard.press("Escape")
    assert last_error is not None
    raise last_error


def _click_until_condition(
    button, condition, *, attempts: int = 5, wait_ms: int = 3000
) -> None:
    """Click `button` and wait up to `wait_ms`, retrying the whole click if
    `condition()` (a zero-arg callable returning bool) isn't true afterward.
    A handful of this page's mutating buttons have been observed to not
    reliably register their Python-side effect on every single click in
    this environment (root cause not conclusively identified - possibly a
    Streamlit rerun still settling); this generic guard papers over exactly
    that by re-clicking rather than trusting one attempt, mirroring
    _select_option's already-established retry-and-verify shape.

    The property panel re-renders its form (and thus this button) around a
    selectbox change that itself triggers a rerun, so `button` can briefly
    not exist yet when the previous rerun hasn't settled - a plain
    `.click()` would then burn its own ~30s actionability wait and raise
    instead of giving this function a chance to retry. Each attempt here
    uses a short per-click timeout and treats "not there yet" the same as
    "condition still false", not as a hard failure.

    Each attempt polls `condition()` every 200ms up to `wait_ms` instead of
    sleeping the full `wait_ms` once and checking - a shared, contended CI
    runner has been observed to occasionally settle a Streamlit rerun well
    past the previous fixed 1200ms single check (PR #131, Browser lifecycle
    journey: `Prepare model configuration` timed out with only 5 * 1200ms =
    6s of total budget), so budget per attempt is both larger and spent
    polling rather than in one blind sleep - a fast rerun still returns
    almost immediately, a slow one now has room to land before this gives
    up and re-clicks."""
    for _ in range(attempts):
        try:
            button.click(timeout=8_000)
        except PlaywrightTimeoutError:
            button.page.wait_for_timeout(wait_ms)
            continue
        elapsed_ms = 0
        poll_interval_ms = 200
        while elapsed_ms < wait_ms:
            if condition():
                return
            button.page.wait_for_timeout(poll_interval_ms)
            elapsed_ms += poll_interval_ms
    assert condition(), "condition still false after repeated clicks"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _drain_subprocess_output(
    proc: subprocess.Popen, log_path: Path
) -> threading.Thread:
    """Continuously read `proc.stdout` to a file on a background thread.

    This journey drives dozens of sequential reruns of a real Streamlit
    server subprocess. `subprocess.PIPE` is a fixed-size OS pipe: if nothing
    ever reads it, it fills up once the server has printed enough (Streamlit
    logs plus warnings emitted on every rerun), and the child's next write()
    blocks forever - silently freezing the whole app mid-test with no
    exception on either side. Draining continuously is the fix; writing to a
    file (rather than discarding) also gives a real server-side log to
    inspect if a step ever times out."""
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


@pytest.fixture(scope="module")
def bundle_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    bundle_dir = tmp_path_factory.mktemp("causal-graph-browser-bundle")
    return build_lifecycle_project_bundle(bundle_dir / "causal-graph-bundle.zip")


@pytest.fixture(scope="module")
def streamlit_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    port = _free_port()
    isolated_curve_store_root = tmp_path_factory.mktemp(
        "causal-graph-browser-curve-store"
    )
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
    stdout_log_path = FAILURE_ARTIFACT_DIR / "causal-graph-streamlit-server.log"
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


def _add_node(page: Page, node_id: str, role: str) -> None:
    page.get_by_role("textbox", name="Node id").fill(node_id)
    _select_option(page, "Role", role, nth=0)
    # Streamlit can briefly retain the previous form submit button across a
    # rerender, so the accessible role may resolve to two equivalent buttons.
    # The last form is the live node-creation form.
    page.get_by_role("button", name="Add node").last.click()
    page.wait_for_timeout(1500)


def _add_edge(page: Page, source: str, target: str, role: str) -> None:
    _select_option(page, "Source node", source)
    _select_option(page, "Target node", target)
    _select_option(page, "Role", role, nth=1)
    page.get_by_role("button", name="Add edge").click()
    page.wait_for_timeout(1500)


def test_causal_graph_editor_journey_in_browser(
    page: Page, streamlit_base_url: str, bundle_path: Path
) -> None:
    console_errors: list[str] = []
    page.on(
        "console",
        lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
    )

    # --- load synthetic project -------------------------------------------
    page.goto(streamlit_base_url, wait_until="load")
    expect(
        page.get_by_test_id("stSidebarUserContent").get_by_text(
            "Family History & DNA MMM"
        )
    ).to_be_visible(timeout=60_000)
    page.get_by_role("link", name="Export & Recovery").click()
    expect(
        page.get_by_text("Upload a previously exported .zip", exact=True)
    ).to_be_visible(timeout=30_000)
    page.get_by_label("Upload a previously exported .zip", exact=True).get_by_test_id(
        "stFileUploaderDropzoneInput"
    ).set_input_files(str(bundle_path))
    import_button = page.get_by_role("button", name="Import bundle")
    expect(import_button).to_be_enabled(timeout=30_000)
    import_button.click()
    expect(
        page.get_by_text(
            "Project imported. Review each page to pick up where you left off.",
            exact=True,
        )
    ).to_be_visible(timeout=30_000)

    # --- open Causal Graph --------------------------------------------------
    page.get_by_role("link", name="Causal Graph").click()
    expect(page.get_by_text("Build the graph", exact=False)).to_be_visible(
        timeout=30_000
    )

    # --- seed the media node and outcome node from Structure ---------------
    page.get_by_text("Seed nodes from current Structure", exact=False).click()
    _click_until_condition(
        page.get_by_role("button", name="Add these as nodes"),
        lambda: (
            page.get_by_role("combobox", name="Source node").count() > 0
            and page.get_by_role("combobox", name="Source node").input_value()
            == "TV Brand"
        ),
        attempts=8,
        wait_ms=2000,
    )

    # --- attempt a prohibited reverse edge (outcome -> intervention) -------
    _add_node(page, "branded_demand", "Funnel mediator")
    _add_edge(page, "TV Brand", "branded demand", "Mediated")
    _add_edge(page, NEW_OUTCOME_NODE_LABEL, "TV Brand", "Direct")

    # --- deterministic rejection: the graph is reported invalid, and
    # Approve is disabled - it is categorically impossible to approve an
    # invalid graph through this UI, not merely discouraged -----------------
    expect(page.get_by_text("targets an intervention node", exact=False)).to_be_visible(
        timeout=15_000
    )
    approve_button = page.get_by_role("button", name="Approve")
    expect(approve_button).to_be_disabled(timeout=15_000)
    expect(page.get_by_text("Draft", exact=False).first).to_be_visible(timeout=15_000)

    # --- remove both non-final edges via the property panel: the bad
    # reverse edge, and the mediated edge (the current PyMC engine cannot
    # compile a mediated pathway yet - REQ-GRAPH-001's own engine-capability
    # boundary; the mediator node itself is left as a harmless orphan,
    # engine capability being checked per-edge, not per-node) ---------------
    page.get_by_role("radio", name="Edge").click(force=True)
    for pattern, label in (
        (
            re.compile(rf"^{re.escape(NEW_OUTCOME_NODE_LABEL)} -> TV Brand"),
            f"{NEW_OUTCOME_NODE_LABEL} -> TV Brand (Direct)",
        ),
        (
            re.compile(r"^TV Brand -> branded demand"),
            "TV Brand -> branded demand (Mediated)",
        ),
    ):
        _select_option(page, "Edge", pattern, verify_text=label)
        edge_combobox = page.get_by_role("combobox", name="Edge")

        def _edge_gone(label=label):
            try:
                return edge_combobox.input_value(timeout=1_000) != label
            except Exception:
                return True  # the Edge section itself disappeared - also gone

        _click_until_condition(
            page.get_by_role("button", name="Remove edge"), _edge_gone
        )

    # --- add the real, engine-supported edge -------------------------------
    _add_edge(page, "TV Brand", NEW_OUTCOME_NODE_LABEL, "Direct")

    # --- inspect the model-plan preview -------------------------------------
    expect(page.get_by_text("Outcome nodes", exact=True).first).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text("Model inputs", exact=True).first).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text("Structural links", exact=True).first).to_be_visible(
        timeout=15_000
    )
    page.get_by_text("Technical details · compilation plan", exact=True).click()
    # `.first` (same pattern as the "draft" status-badge check above): a
    # Streamlit rerun can transiently render both the old and new fragment
    # of the technical preview for one frame, which a strict-mode
    # `get_by_text(..., exact=True)` treats as an ambiguous match (a real
    # duplicate-element error) rather than a timing artifact - `.first`
    # asserts the same content is visible without being sensitive to that
    # transient double-render.
    expect(page.get_by_text("Outcome ordering", exact=True).first).to_be_visible(
        timeout=15_000
    )
    expect(page.get_by_text("Modelling columns", exact=True).first).to_be_visible(
        timeout=15_000
    )

    # --- save a draft, then approve (now valid) -----------------------------
    # st.metric("Version", ...) is the second of the three status metrics
    # (Status, Version, Structural fingerprint).
    version_metric = page.get_by_test_id("stMetricValue").nth(1)
    version_before = version_metric.inner_text()
    _click_until_condition(
        page.get_by_role("button", name="Save draft"),
        lambda: version_metric.inner_text() != version_before,
    )

    approve_button = page.get_by_role("button", name="Approve")
    expect(approve_button).to_be_enabled(timeout=15_000)
    _click_until_condition(
        approve_button,
        lambda: page.locator(".mmm-badge").filter(has_text="Approved").count() > 0,
    )

    # --- prepare model configuration: succeeds, binds a structural
    # fingerprint --------------------------------------------------------------
    _click_until_condition(
        page.get_by_role("button", name="Prepare model configuration"),
        lambda: (
            page.get_by_text(
                "Model configuration prepared. Structural fingerprint bound",
                exact=False,
            ).count()
            > 0
        ),
    )
    expect(
        page.get_by_text("is current with this graph's structure", exact=False)
    ).to_be_visible(timeout=15_000)

    # --- move a node (layout-only): the prepared configuration stays current
    # streamlit_flow (like all Streamlit custom components) renders inside
    # its own sandboxed iframe, so the canvas node must be located through
    # a frame_locator rather than the top-level page.
    node_locator = page.frame_locator("iframe").locator(
        f'.react-flow__node[data-id="{TV_BRAND_ACTIVITY_NODE_ID}"]'
    )
    expect(node_locator).to_be_visible(timeout=15_000)
    box = node_locator.bounding_box()
    assert box is not None
    start_x, start_y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    page.mouse.move(start_x, start_y)
    page.mouse.down()
    page.mouse.move(start_x + 160, start_y + 90, steps=10)
    page.mouse.up()
    expect(
        page.get_by_text("is current with this graph's structure", exact=False)
    ).to_be_visible(timeout=15_000)

    # --- change a structural edge (lag): the prepared configuration goes
    # stale -----------------------------------------------------------------
    page.get_by_role("radio", name="Edge").click(force=True)
    _select_option(
        page,
        "Edge",
        re.compile(rf"^TV Brand -> {re.escape(NEW_OUTCOME_NODE_LABEL)}"),
        verify_text=f"TV Brand -> {NEW_OUTCOME_NODE_LABEL} (Direct)",
    )
    _select_option(page, "Lag type", "Media carryover")
    _click_until_condition(
        page.get_by_role("button", name="Save edge"),
        lambda: page.get_by_text("it is now stale", exact=False).count() > 0,
    )

    # --- graph portability: the real "Build export bundle" click on
    # Project Export must carry this session's approved, structurally-
    # edited graph into the downloaded bundle (REQ-GRAPH-001 work package,
    # graph portability - "an authoritative graph can therefore be lost
    # across the actual user export/import workflow"). The import side of
    # this same round trip is covered at the AppTest layer
    # (test_project_export_page_apptest.py), which drives the identical
    # button-click code path without the added flakiness risk of a second
    # real browser session boundary in this already-long journey. ---------
    page.get_by_role("link", name="Export & Recovery").click()
    expect(page.get_by_text("Build export bundle", exact=True)).to_be_visible(
        timeout=30_000
    )
    with page.expect_download(timeout=30_000) as download_info:
        page.get_by_role("button", name="Build export bundle").click()
        page.get_by_role("button", name="Download project bundle (.zip)").click(
            timeout=30_000
        )
    downloaded_path = download_info.value.path()
    assert downloaded_path is not None
    with zipfile.ZipFile(downloaded_path) as zf:
        assert "config/causal_graphs.json" in zf.namelist()
        exported_graphs = json.loads(zf.read("config/causal_graphs.json"))
    assert exported_graphs
    assert any(g.get("status") == "approved" for g in exported_graphs)

    unexpected_console_errors = [
        e for e in console_errors if "favicon" not in e.lower()
    ]
    assert unexpected_console_errors == [], unexpected_console_errors
