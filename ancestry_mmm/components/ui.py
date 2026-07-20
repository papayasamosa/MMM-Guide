"""Shared page chrome and guidance components: theme CSS, sidebar navigation,
page headers, step indicators, next-step panels, empty states, status cards
and a compact glossary. Every page uses these instead of re-implementing its
own header/sidebar/footer markup, so behaviour and styling stay consistent.
"""

from typing import Any, Dict, Iterable, Optional

import streamlit as st

from ancestry_mmm.utils.config import THEME_COLORS
from ancestry_mmm.utils.display import GLOSSARY
from ancestry_mmm.utils.session_state import get_workflow_progress
from ancestry_mmm.utils.workflow import TOTAL_STEPS, get_step, next_step_key, sidebar_entries, step_number


def apply_theme() -> None:
    """Inject the small amount of CSS not reachable via .streamlit/config.toml's
    [theme] section. Call once near the top of every page, after
    st.set_page_config(). The base dark-green palette itself comes from the
    theme config, which applies automatically on every page.
    """
    st.markdown(
        f"""
        <style>
        .muted {{ color: {THEME_COLORS['foreground_muted']}; }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        /* st.info() defaults to Streamlit's fixed blue, which reads as "strong
           blue" against an otherwise all-green palette - retint it to a muted
           green-gray so info messages stay calm and on-palette. */
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
            background-color: rgba(107, 139, 122, 0.18) !important;
        }}
        [data-testid="stAlertContentInfo"] {{ color: {THEME_COLORS['foreground_muted']} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(active_key: str) -> None:
    """Render the compact sidebar nav shared by every page. `active_key` is
    accepted for callers that want to reason about the current page, though
    highlighting the active link is handled automatically by st.page_link.
    """
    with st.sidebar:
        st.markdown("**Marketing Mix Modelling**")
        st.caption("New · DNA cross-sell · Winback")
        st.markdown("---")
        for entry in sidebar_entries():
            st.page_link(entry["path"], label=entry["label"])
        st.markdown("---")
        current_step, total_steps = get_workflow_progress()
        st.caption(f"Workflow progress · step {current_step} of {total_steps}")
        st.progress(current_step / total_steps)
    _ = active_key  # reserved for future explicit-highlight use


def render_page_header(key: str) -> None:
    """Top-of-page block: step indicator, title, one-line purpose, numbered steps."""
    step = get_step(key)
    if step is None:
        return
    n = step_number(key)
    if n is not None:
        st.caption(f"Step {n} of {TOTAL_STEPS}: {step['label']}")
    st.title(step["title"])
    if step.get("purpose"):
        st.markdown(step["purpose"])
    if step.get("steps"):
        st.markdown("\n".join(f"{i}. {s}" for i, s in enumerate(step["steps"], start=1)))


def render_next_step(key: str, *, key_suffix: str = "") -> None:
    """Bottom-of-page block: the next recommended action and one primary button."""
    step = get_step(key)
    if step is None or not step.get("next"):
        return
    st.markdown("---")
    st.caption(f"Next: {step['next']}")
    nxt_key = next_step_key(key)
    if nxt_key is not None:
        nxt = get_step(nxt_key)
        if st.button(f"Continue to {nxt['label']} →", type="primary", key=f"next_{key}{key_suffix}"):
            st.switch_page(nxt["path"])


def render_empty_state(
    message: str,
    *,
    button_label: Optional[str] = None,
    target_key: Optional[str] = None,
    key_suffix: str = "",
) -> None:
    """Explain why a page can't be used yet and offer one button to the
    prerequisite page, instead of a bare warning."""
    st.info(message)
    if button_label and target_key:
        target = get_step(target_key)
        if target and st.button(button_label, key=f"empty_state_{target_key}{key_suffix}"):
            st.switch_page(target["path"])


def render_status_card(label: str, value: str, ready: bool) -> None:
    """One compact bordered status card, used on the Home page."""
    with st.container(border=True):
        st.caption(label)
        st.markdown(f"{'✓' if ready else '○'} **{value}**")


def render_glossary(terms: Optional[Iterable[str]] = None) -> None:
    """Compact glossary expander. Pass `terms` to show a subset relevant to
    the current page; omit it to show the full glossary."""
    entries: Dict[str, Any] = {t: GLOSSARY[t] for t in terms if t in GLOSSARY} if terms else GLOSSARY
    with st.expander("Glossary"):
        for term, definition in entries.items():
            st.markdown(f"**{term}** - {definition}")
