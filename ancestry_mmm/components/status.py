"""Central semantic status-badge vocabulary (Phase 1 UI overhaul design
system, item #5 - see docs/decision_log.md).

Every place in the app that shows a lifecycle/governance/readiness status -
sidebar readiness indicators, page-header badges, curve/scenario/approval
labels - should render through ``STATUS_BADGES`` / ``render_status_badge`` /
``render_status_badges`` here instead of re-deriving its own colour+icon
mapping, so there is exactly one status vocabulary in the app.

A badge is never colour-only: every entry always carries an icon and a text
label alongside its semantic colour, so status is legible without relying
on colour perception alone.

This module only renders presentation. It does not decide what status a
page is in - callers pass the status key/label; the underlying governance
state itself continues to come from ``ancestry_mmm.core``/``application``
services and existing session-state getters, never invented here.
"""

from typing import Dict, Iterable, Optional, Tuple

import streamlit as st

from ancestry_mmm.components.tokens import STATUS_COLOR

# status_key -> (display label, icon, semantic colour key from
# tokens.STATUS_COLOR). Keys are the vocabulary named in the Phase 1 brief
# plus the readiness states used by the grouped sidebar navigation.
STATUS_BADGES: Dict[str, Tuple[str, str, str]] = {
    "draft": ("Draft", "✎", "neutral"),
    "running": ("Running", "◐", "info"),
    "failed": ("Failed", "✕", "negative"),
    "exploratory": ("Exploratory", "◇", "neutral"),
    "validated": ("Validated", "✓", "positive"),
    "approved_for_reporting": ("Approved for reporting", "✓", "positive"),
    "approved_for_planning": ("Approved for planning", "✓", "positive"),
    # Generic lifecycle states (e.g. core.causal_graph.GRAPH_STATUSES) that
    # are not specifically about outcome-use approval - additive, presentational
    # only, no existing call site used these keys before.
    "approved": ("Approved", "✓", "positive"),
    "deprecated": ("Deprecated", "×", "negative"),
    "stale": ("Stale", "!", "caution"),
    "superseded": ("Superseded", "»", "neutral"),
    "not_configured": ("Not configured", "○", "neutral"),
    "awaiting_data": ("Awaiting data", "○", "neutral"),
    # Readiness states reused by the grouped sidebar nav (components/ui.py)
    # so a page's nav indicator and its own header badge always agree.
    "ready": ("Ready", "✓", "positive"),
    "blocked": ("Blocked", "⛔", "negative"),
    "not_started": ("Not started", "○", "neutral"),
    "current": ("In progress", "◐", "info"),
    "optional": ("Optional", "·", "neutral"),
}


def _lookup(status_key: str, label: Optional[str]) -> Tuple[str, str, str]:
    text, icon, color_key = STATUS_BADGES.get(
        status_key, (status_key.replace("_", " ").title(), "•", "neutral")
    )
    if label:
        text = label
    return text, icon, color_key


def badge_html(status_key: str, *, label: Optional[str] = None) -> str:
    """Return the inline HTML span for one badge, for callers composing a
    larger markdown block (e.g. a page header title line) rather than
    rendering the badge as its own element."""
    text, icon, color_key = _lookup(status_key, label)
    color = STATUS_COLOR[color_key]
    return (
        f'<span class="mmm-badge" style="color:{color};border-color:{color};">'
        f"{icon} {text}</span>"
    )


def render_status_badge(status_key: str, *, label: Optional[str] = None) -> None:
    """Render one semantic status badge. Falls back to a neutral badge
    (title-cased key as the label) for an unrecognised status_key rather
    than raising - a badge is presentation and should never crash a page."""
    st.markdown(badge_html(status_key, label=label), unsafe_allow_html=True)


def render_status_badges(status_keys: Iterable[str]) -> None:
    """Render several badges inline, left to right, in one markdown block
    so they flow on the same line instead of stacking one per Streamlit
    element."""
    keys = [k for k in status_keys if k]
    if not keys:
        return
    st.markdown("".join(badge_html(k) for k in keys), unsafe_allow_html=True)
