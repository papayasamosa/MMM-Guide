"""Diagnostics top-line answer and domain-health rail rendering (Phase 5 of
the Streamlit UI/UX overhaul - see docs/decision_log.md; REQ-VAL-001).

Presentation only: renders the ``DomainHealth``/``TopLineReadiness`` objects
already derived by ``ancestry_mmm.application.diagnostics_summary`` through
the shared status-badge vocabulary (``ancestry_mmm.components.status``) -
this module computes nothing about governance state itself. A domain row or
the top-line badge rendering "pass"/"ready" is a presentation of
already-computed evidence, never itself approval; the caller is responsible
for keeping the real ``ModelApproval``/``ApprovalReadiness`` state as the
sole source of approval truth (REQ-VAL-001, root AGENTS.md "Governance").
"""

from typing import List, Optional

import streamlit as st

from ancestry_mmm.application.diagnostics_summary import DomainHealth, TopLineReadiness
from ancestry_mmm.components.status import badge_html, render_status_badge


def render_top_line(topline: TopLineReadiness) -> None:
    """The single top-of-page answer to "can this fitted model be trusted
    for the requested use?" - a status badge, a short headline, and a
    detail line (which carries the outstanding-issue count where relevant).
    """
    st.markdown(
        f'<div class="mmm-header-desc" style="font-size:1.1rem; margin-bottom:4px;">'
        f"{badge_html(topline.status_key)} <strong>{topline.headline}</strong></div>",
        unsafe_allow_html=True,
    )
    if topline.detail:
        st.caption(topline.detail)
    st.caption(
        "This summary reflects computed evidence only - a passing badge here is not "
        "itself approval; see Model approval below for the actual governed approval decision."
    )


def render_primary_concern(sentence: Optional[str]) -> None:
    """The single most significant issue, if one is deterministically
    derivable from computed evidence - omitted entirely otherwise (never a
    speculative placeholder)."""
    if sentence:
        st.warning(sentence)


_MAX_COLS_PER_ROW = 4


def render_domain_health_rail(rows: List[DomainHealth]) -> None:
    """One compact bordered card per evidence domain - not four equal
    st.metric cards. Each card names the domain, its status via the shared
    badge vocabulary, and a one-line deterministic detail.

    Wrapped into rows of at most ``_MAX_COLS_PER_ROW`` columns rather than
    one ``st.columns(len(rows))`` call: st.columns never reflows on its
    own, so seven equal-width columns in one row become unreadably cramped
    (truncated labels) at narrower viewports (~1024px) even though nothing
    actually overflows/scrolls. Multiple row-sized st.columns() calls give
    every card a readable minimum width at any of the app's supported
    resolutions."""
    if not rows:
        return
    for row_start in range(0, len(rows), _MAX_COLS_PER_ROW):
        row_chunk = rows[row_start : row_start + _MAX_COLS_PER_ROW]
        cols = st.columns(len(row_chunk))
        for col, row in zip(cols, row_chunk):
            with col:
                with st.container(border=True):
                    st.caption(row.domain)
                    render_status_badge(row.status)
                    st.caption(row.detail)
