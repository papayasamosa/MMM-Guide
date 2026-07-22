"""Streamlit smoke tests: every page (plus the Home page, app.py) must load
with a genuinely empty session state without raising - the guard against a
page-level `NameError`/`ImportError`/`KeyError` that unit tests on `core`
functions can't catch, since those never execute Streamlit rendering code
at all. Committed per the instruction document's CI requirement ("Start
every Streamlit page") - previously only ever run as an uncommitted,
ad-hoc verification script each session, never in CI."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

# st.page_link requires a real multipage-app file tree that AppTest.from_file
# (loading a single page in isolation) doesn't set up - stub it out so a page
# using it in the sidebar doesn't fail here for a reason that has nothing to
# do with the page's own logic.
st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGES_DIR = ROOT / "pages"
APP_FILE = ROOT / "app.py"

PAGE_FILES = sorted(p.name for p in PAGES_DIR.glob("*.py"))


def test_at_least_one_page_was_discovered():
    # Guards against a path/glob typo silently turning every parametrized
    # test below into a no-op (an empty parametrize list "passes" trivially).
    assert len(PAGE_FILES) >= 10


def test_home_page_loads_with_empty_session_state():
    at = AppTest.from_file(str(APP_FILE), default_timeout=60)
    at.run()
    assert not at.exception, f"app.py raised: {at.exception}"


@pytest.mark.parametrize("page_file", PAGE_FILES)
def test_page_loads_with_empty_session_state(page_file):
    at = AppTest.from_file(str(PAGES_DIR / page_file), default_timeout=60)
    at.run()
    assert not at.exception, f"{page_file} raised: {at.exception}"
