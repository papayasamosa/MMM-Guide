"""Shared page chrome and guidance components: theme CSS, grouped sidebar
navigation, the project context bar, compact page headers, panel
primitives, next-step panels, empty/blocked/stale states, status cards and
a compact glossary. Every page uses these instead of re-implementing its
own header/sidebar/footer markup, so behaviour and styling stay consistent.

Phase 1 of the Streamlit UI/UX overhaul (see docs/decision_log.md) added:
grouped nav with per-page readiness indicators, the project context bar, a
compact page header (title/description/task prompt/badges/actions), and the
SectionCard/InfoPanel/WarningPanel/BlockingPanel container primitives. All
of it is presentation only - readiness/context signals are read from
existing session-state getters (ancestry_mmm.utils.session_state), never
invented, and no analytical/governance behaviour changed.
"""

import contextlib
import html as _html
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional

import streamlit as st

from ancestry_mmm.utils.config import THEME_COLORS
from ancestry_mmm.utils.display import GLOSSARY
from ancestry_mmm.utils.session_state import get_state
from ancestry_mmm.utils.workflow import (
    get_step,
    nav_groups,
    step_number,
    workflow_label,
)
from ancestry_mmm.utils.workflow_state import (
    next_workflow_step_key,
    resolve_workflow_navigation,
    workflow_page_states,
    workflow_page_state,
)
from ancestry_mmm.components.tokens import (
    HIGHLIGHT_BORDER,
    HIGHLIGHT_SURFACE,
    shell_css,
)
from ancestry_mmm.components.status import render_status_badges
from ancestry_mmm.core.outcomes import BLOCKING_DRIFT_STATUSES, outcomes_drift_dataframe


def apply_theme() -> None:
    """Inject the small amount of CSS not reachable via Streamlit theme config."""
    st.markdown(
        f"""
        <style>
        .muted {{ color: {THEME_COLORS["text_secondary"]}; }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
            background-color: {HIGHLIGHT_SURFACE["info"]} !important;
            border: 1px solid {HIGHLIGHT_BORDER["info"]} !important;
        }}
        [data-testid="stAlertContentInfo"] {{ color: {THEME_COLORS["text_primary"]} !important; }}
        div.stButton > button[kind="primary"] {{
            background: {THEME_COLORS["action_primary"]};
            border-color: {THEME_COLORS["action_primary"]};
            color: #FFFFFF;
        }}
        div.stButton > button[kind="primary"]:hover {{
            background: {THEME_COLORS["action_primary_hover"]};
            border-color: {THEME_COLORS["action_primary_hover"]};
            color: #FFFFFF;
        }}
        div.stButton > button:focus-visible, input:focus-visible, textarea:focus-visible {{
            outline: 3px solid {THEME_COLORS["focus_ring"]} !important;
            outline-offset: 2px;
        }}
        .stMarkdown hr {{
            border: 0;
            border-top: 1px solid {THEME_COLORS["border_subtle"]};
            margin: 1.5rem 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(shell_css(), unsafe_allow_html=True)


# Readiness -> sidebar icon. Deliberately show icons only for attention states;
# the page link label remains authoritative. Reuse one cue for review/stale/
# unavailable and one for blocked so the sidebar does not become a second,
# decorative status legend (UX/UI coherence Phase 11, brief Finding 18).
_READINESS_ICON = {
    "stale": ":material/warning:",
    "review": ":material/warning:",
    "unavailable": ":material/warning:",
    "blocked": ":material/block:",
}
_ATTENTION_STATUSES = {"stale", "review", "unavailable", "blocked"}


def page_readiness(key: str) -> str:
    """Return the canonical lifecycle/access status for one workflow page."""
    return workflow_page_state(key, getter=get_state).display_status


def group_readiness(keys: Iterable[str]) -> str:
    """Aggregate canonical page states into one workflow-area status.

    Overnight UI/UX pass (2026-08-29, severity semantics / empty-state
    finding): a plain per-page ``"blocked"`` status by itself only ever
    means "this page's own upstream prerequisite in the same workflow
    hasn't been done yet" (see ``workflow_page_state`` - e.g. "Load data
    before joining and transforming sources"). On a brand-new project
    every not-yet-reached group is in exactly this state, so treating it
    the same as a genuine attention condition previously made 4 of 5
    Home workflow-map areas render the same red "Blocked" badge used for
    a real problem, before the analyst had done anything at all
    (violates the severity semantics in the UX guidance: Error/Blocking
    should mean the workflow cannot safely continue, not "you haven't
    started this yet"). ``"stale"``/``"review"``/``"unavailable"`` remain
    genuine attention conditions (something changed or became invalid
    after real progress was made) and still surface as "blocked" here;
    only the ordinary sequential-gate case is now reported as
    "not_started", matching the neutral treatment every other
    not-yet-started group already receives.
    """
    scored = [s for s in (page_readiness(k) for k in keys) if s != "optional"]
    if not scored:
        return "not_started"
    satisfied = {
        "complete",
        "configured",
        "saved",
        "validated",
        "approved",
        "draft",
    }
    done = sum(1 for s in scored if s in satisfied)
    if done == len(scored):
        return "complete"
    if done > 0:
        return "current"
    if any(s in {"stale", "review", "unavailable"} for s in scored):
        return "blocked"
    return "not_started"


def next_recommended_step_key() -> Optional[str]:
    """Return the first actionable unsatisfied required page, if any."""
    return next_workflow_step_key(getter=get_state)


def render_sidebar(active_key: str) -> None:
    """Render the grouped sidebar nav shared by every page (Phase 1: pages
    grouped into workflow areas per ancestry_mmm.utils.workflow.NAV_GROUPS,
    with a lightweight readiness icon per page). `active_key` is accepted
    for callers that want to reason about the current page, though
    highlighting the active link is handled automatically by st.page_link.
    Every existing route/key/label is unchanged - this only changes how the
    same sidebar_entries() are visually grouped.
    """
    with st.sidebar:
        st.markdown(
            '<div class="mmm-brand-lockup">'
            '<div class="mmm-brand-product">Family History &amp; DNA MMM</div>'
            '<div class="mmm-brand-function">Marketing Measurement &amp; Planning</div>'
            '<div class="mmm-brand-context">Ancestry internal analytics</div>'
            "</div>",
            unsafe_allow_html=True,
        )
        for group in nav_groups():
            st.markdown(
                f'<div class="mmm-nav-group">{group["label"]}</div>',
                unsafe_allow_html=True,
            )
            for entry in group["entries"]:
                key = entry["key"]
                status = page_readiness(key)
                icon = (
                    _READINESS_ICON.get(status)
                    if status in _ATTENTION_STATUSES
                    else None
                )
                st.page_link(entry["path"], label=entry["label"], icon=icon)
        states = workflow_page_states(getter=get_state)
        required = [state for state in states if not state.optional]
        satisfied = sum(1 for state in required if state.satisfied)
        exploratory = sum(
            1 for state in required if state.display_status == "exploratory"
        )
        progress = f"{satisfied} of {len(required)} workflow stages complete"
        if exploratory:
            progress += f" · {exploratory} exploratory"
        st.markdown(
            f'<div class="mmm-sidebar-footnote">{progress} · iterative workflow</div>',
            unsafe_allow_html=True,
        )
    _ = active_key  # reserved for future explicit-highlight use


def render_context_bar() -> None:
    """Compact project-context strip for the top of the shell (Phase 1 item
    #3): project name, synthetic/demo vs uploaded data, market scope, model
    window, and model status - each shown only when actually derivable from
    existing session-state getters. A missing field is omitted, never
    defaulted or invented. Synthetic/demo data is always clearly labelled as
    synthetic, never presented as though it were an upload.
    """
    items: List["tuple[str, str]"] = []

    project_name = get_state("project_name")
    if project_name:
        items.append(("Project", _html.escape(str(project_name))))

    raw_sources = get_state("raw_sources") or {}
    if raw_sources:
        active_upload_versions = get_state("active_source_upload_version") or {}
        is_demo = not active_upload_versions
        items.append(
            ("Data source", "Synthetic demo data" if is_demo else "Uploaded data")
        )

    spec = get_state("model_spec")
    if isinstance(spec, dict) and spec.get("markets"):
        markets = ", ".join(str(m) for m in spec["markets"])
        items.append(("Market scope", _html.escape(markets)))
    if isinstance(spec, dict) and spec.get("segment_outcomes"):
        segments = ", ".join(str(s) for s in spec["segment_outcomes"])
        items.append(("Segments", _html.escape(segments)))

    df = get_state("transformed_data")
    date_col = get_state("date_col")
    if df is not None and date_col and date_col in getattr(df, "columns", []):
        try:
            from ancestry_mmm.utils.display import format_date

            start, end = df[date_col].min(), df[date_col].max()
            items.append(
                (
                    "Model window",
                    _html.escape(f"{format_date(start)} to {format_date(end)}"),
                )
            )
        except (TypeError, ValueError, KeyError):
            pass

    if get_state("model_trained"):
        status = "Approved" if get_state("model_approval") else "Trained, not approved"
        items.append(("Model status", status))
    elif get_state("frame") is not None:
        items.append(("Model status", "Prepared, not trained"))

    if not items:
        return

    parts = ['<div class="mmm-context-bar">']
    for label, value in items:
        parts.append(
            f'<div class="mmm-context-item"><span class="mmm-context-label">{label}</span>'
            f'<span class="mmm-context-value">{value}</span></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_page_header(
    key: str,
    *,
    description: Optional[str] = None,
    task_prompt: Optional[str] = None,
    badges: Optional[Iterable[str]] = None,
    primary_action: Optional[Dict[str, Any]] = None,
    secondary_actions: Optional[Iterable[Dict[str, Any]]] = None,
) -> None:
    """Compact top-of-page block: workflow context, title, one-sentence task
    description, an optional page-specific task prompt, status badges, and up
    to one dominant primary action plus optional secondary actions.

    Workflow metadata retains its detailed steps for navigation and Home's
    overview, but the shared header does not render a generic tutorial on
    every page. Guidance belongs beside the decision it explains.

    Every parameter is optional and additive - `render_page_header(key)`
    behaves the same as existing title/description call sites.
    `task_prompt`, `badges`, `primary_action`, and `secondary_actions` are
    opt-in for pages that need the fuller header.

    `primary_action`/entries in `secondary_actions` are plain dicts:
    ``{"label": str, "target_key": Optional[str], "on_click": Optional[Callable[[], None]], "key": Optional[str]}``.
    A `target_key` switches to that workflow page (like render_next_step);
    `on_click` is called first if given. This is UI chrome only - it must
    never itself contain model/business logic, only route to it.
    """
    step = get_step(key)
    if step is None:
        return
    n = step_number(key)
    if n is not None:
        group_label = next(
            (
                group["label"]
                for group in nav_groups()
                if key in {entry["key"] for entry in group["entries"]}
            ),
            "WORKFLOW",
        )
        st.caption(f"{group_label} · {step['label']}")

    canonical_status = page_readiness(key)
    badge_keys = list(badges or [])
    if canonical_status not in badge_keys:
        badge_keys.insert(0, canonical_status)

    has_actions = bool(primary_action) or bool(secondary_actions)
    if has_actions:
        title_col, action_col = st.columns([3, 1])
    else:
        title_col, action_col = st.container(), None

    with title_col:
        st.title(step["title"])
        desc = description if description is not None else step.get("purpose")
        if desc:
            st.markdown(
                f'<div class="mmm-header-desc">{desc}</div>', unsafe_allow_html=True
            )
        if task_prompt:
            st.markdown(
                f'<div class="mmm-task-prompt"><span>Focus</span>{_html.escape(task_prompt)}</div>',
                unsafe_allow_html=True,
            )
        if badge_keys:
            render_status_badges(badge_keys)

    if action_col is not None:
        with action_col:
            if primary_action:
                _render_header_action(primary_action, primary=True, idx=0)
            for i, action in enumerate(secondary_actions or [], start=1):
                _render_header_action(action, primary=False, idx=i)


def _render_header_action(action: Dict[str, Any], *, primary: bool, idx: int) -> None:
    label = action.get("label", "Action")
    btn_key = action.get("key") or f"header_action_{idx}_{label}"
    clicked = st.button(
        label,
        type="primary" if primary else "secondary",
        key=btn_key,
        width="stretch",
    )
    if not clicked:
        return
    on_click: Optional[Callable[[], None]] = action.get("on_click")
    if on_click is not None:
        on_click()
    target_key = action.get("target_key")
    if target_key:
        target = get_step(target_key)
        if target:
            st.switch_page(target["path"])


@contextlib.contextmanager
def _panel(
    kind: str,
    title: str,
    *,
    description: Optional[str] = None,
    icon: str = "",
):
    """Shared implementation behind SectionCard/InfoPanel/WarningPanel/
    BlockingPanel - a bordered st.container() carrying a hidden marker span
    that tokens.shell_css()'s :has() rules use to tint the container by
    kind. Falls back to a plain bordered container (no tint) if the marker
    selector ever stops matching a future Streamlit release's DOM - the
    title/description content itself is unaffected either way.
    """
    with st.container(border=kind != "neutral"):
        st.markdown(
            f'<span class="mmm-panel-marker-{kind}" style="display:none"></span>'
            f'<div class="mmm-panel-title">{icon} {title}</div>'.strip(),
            unsafe_allow_html=True,
        )
        if description:
            st.caption(description)
        yield


def SectionCard(title: str, *, description: Optional[str] = None):
    """A borderless workspace section for grouping related content."""
    return _panel("neutral", title, description=description)


def InfoPanel(title: str, *, description: Optional[str] = None):
    """A bordered, info-tinted panel for neutral contextual information."""
    return _panel("info", title, description=description, icon="i")


def WarningPanel(title: str, *, description: Optional[str] = None):
    """A bordered, caution-tinted panel for a non-blocking warning."""
    return _panel("caution", title, description=description, icon="!")


def BlockingPanel(title: str, *, description: Optional[str] = None):
    """A bordered, negative-tinted panel for a condition that blocks the
    page's primary action until resolved."""
    return _panel("negative", title, description=description, icon="×")


def render_next_step(key: str, *, key_suffix: str = "") -> None:
    """Bottom-of-page next action without another full-width divider or card.

    Routed through `resolve_workflow_navigation` (UI-WP1) rather than the
    raw registry order, so this footer can never present an optional page
    (Coverage & Gaps, Causal Graph, Model Comparison, ...) as though it were
    the required next step, and never offers a dead-end continue button for
    a required page that is still blocked by an earlier prerequisite.
    """
    step = get_step(key)
    if step is None:
        return
    nav = resolve_workflow_navigation(key, getter=get_state)

    target = nav.target
    if target is None:
        copy = "No further required workflow stage remains."
    else:
        target_step = get_step(target.key)
        purpose = (target_step or {}).get("purpose", "")
        copy = f"{target.label}" + (f" - {purpose}" if purpose else "")
        if nav.kind == "blocked" and target.reason:
            copy += f" ({target.reason})"

    st.markdown(
        '<div class="mmm-next-step">'
        '<span class="mmm-next-step-label">NEXT STEP</span>'
        f'<span class="mmm-next-step-copy">{_html.escape(copy)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    if nav.kind == "required" and target is not None:
        target_step = get_step(target.key)
        if target_step and st.button(
            f"Continue to {target.label} →",
            type="primary",
            key=f"next_{key}{key_suffix}",
        ):
            st.switch_page(target_step["path"])

    if nav.optional_targets:
        st.caption("Optional: " + " · ".join(t.label for t in nav.optional_targets))
        cols = st.columns(len(nav.optional_targets))
        for col, opt in zip(cols, nav.optional_targets):
            opt_step = get_step(opt.key)
            if opt_step is None:
                continue
            with col:
                if st.button(
                    opt.label,
                    key=f"next_optional_{key}_{opt.key}{key_suffix}",
                    width="stretch",
                ):
                    st.switch_page(opt_step["path"])


def render_empty_state(
    message: str,
    *,
    button_label: Optional[str] = None,
    target_key: Optional[str] = None,
    key_suffix: str = "",
    what_for: Optional[str] = None,
    dependency: Optional[str] = None,
    next_action: Optional[str] = None,
    blocking: bool = False,
) -> None:
    """Explain why a page can't be used yet (or is blocked) and offer one
    button to the prerequisite page, instead of a bare warning.

    `message` remains the required, freeform explanation and is always the
    primary line shown - every existing call site (`render_empty_state(msg,
    button_label=..., target_key=...)`) behaves identically to before this
    change. The optional `what_for`/`dependency`/`next_action` remain visible
    as quieter supporting captions (Phase 1 item #7): what this workspace is
    for, which dependency is missing, and the next action to take.
    `blocking=True` renders as `st.error` instead of `st.info`, for a page
    that must stop rather than just flag a gap.
    """
    if blocking:
        st.error(message)
    else:
        st.info(message)

    if what_for:
        st.caption(f"Purpose: {what_for}")
    if dependency:
        st.caption(f"Dependency: {dependency}")
    if next_action:
        st.caption(f"Next action: {next_action}")
    if target_key:
        target = get_step(target_key)
        if target:
            label = (
                f"Go to {workflow_label(target_key)}"
                if not button_label or button_label.lower().startswith("go to ")
                else button_label
            )
            if st.button(label, key=f"empty_state_{target_key}{key_suffix}"):
                st.switch_page(target["path"])


def render_workspace_note(label: str, message: str, *, kind: str = "") -> None:
    """Render a compact page-local cue about editing or derived state.

    This is intentionally lighter than an InfoPanel: it gives analysts the
    one consequence or ownership cue needed at the current workspace without
    creating another bordered card.
    """
    safe_kind = kind if kind in {"editable", "derived", "governed"} else ""
    st.markdown(
        f'<div class="mmm-workbench-note {safe_kind}">'
        f'<span class="mmm-workbench-note-label">{_html.escape(label)}</span>'
        f'<span class="mmm-workbench-note-copy">{_html.escape(message)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_status_card(label: str, value: str, ready: bool) -> None:
    """One compact bordered status card, used on the Home page."""
    with st.container(border=True):
        st.caption(label)
        st.markdown(f"{'✓' if ready else '○'} **{value}**")


def render_glossary(terms: Optional[Iterable[str]] = None) -> None:
    """On-demand definitions for the current workspace.

    Callers should pass only terms that affect the current decision. The full
    glossary remains available to code that needs it, but is not presented as
    routine page furniture.
    """
    entries: Dict[str, Any] = (
        {t: GLOSSARY[t] for t in terms if t in GLOSSARY} if terms else GLOSSARY
    )
    if not entries:
        return
    with st.popover("Help for this workspace"):
        for term, definition in entries.items():
            st.markdown(f"**{term}** - {definition}")


def render_definition_help(term: str, definition: str) -> None:
    """Render one short, page-local definition on demand.

    Definitions answer what a concept means.  They are deliberately separate
    from decision guidance and technical provenance so a small question does
    not open a wall of implementation detail.
    """
    with st.popover(f"What is {term}?"):
        st.markdown(f"### What is {term}?")
        st.write(definition)


def render_decision_help(
    title: str,
    *,
    controls: str,
    why: str,
    options: Optional[Mapping[str, str]] = None,
    normal_path: str,
    downstream: str,
    invalidates: str,
) -> None:
    """Render structured guidance for a real modelling or workflow choice."""
    with st.popover(title):
        st.markdown("**What this controls**")
        st.write(controls)
        st.markdown("**Why it matters**")
        st.write(why)
        if options:
            st.markdown("**When to use each option**")
            for option, guidance in options.items():
                st.markdown(f"- **{option}:** {guidance}")
        st.markdown("**Normal path**")
        st.write(normal_path)
        st.markdown("**What changes downstream**")
        st.write(downstream)
        st.markdown("**Does changing it invalidate a fit or approval?**")
        st.write(invalidates)


def render_technical_details(
    *,
    details: Optional[Mapping[str, str]] = None,
    body: Optional[str] = None,
    title: str = "Technical details",
    expanded: bool = False,
) -> None:
    """Keep implementation identity and provenance available, but secondary."""
    if not details and not body:
        return
    with st.expander(title, expanded=expanded):
        if body:
            st.markdown(body)
        for label, value in (details or {}).items():
            st.markdown(f"**{label}:** {value}")


def render_drift_status(
    outcome_definitions: list,
    model_meta: object,
    *,
    available_columns: Optional[set] = None,
    blocking: bool = False,
) -> bool:
    """
    Shared drift-status panel (PR E.2 requirement #10 - "make drift status
    first-class in the UI") for every page that reads a fitted model against
    a live outcome catalogue: Structure, Model Configuration, Model
    Training, Diagnostics, Results & Curve Bank, Scenario Planner, Project
    Export. Shows consequence-oriented outcome-definition changes and keeps
    exact technical status in secondary detail, not just a bare "stale" flag.
    Returns `True` if calculation-relevant drift was found
    (`core.outcomes.BLOCKING_DRIFT_STATUSES` - a changed or removed
    outcome) so a caller can gate on it; `blocking=True` renders that case
    as `st.error` instead of `st.warning`, for a page (Scenario Planner)
    that must stop rather than just flag it.

    No-op (returns `False`, renders nothing) when there's no fitted model
    to compare against (`model_meta=None`) or nothing has drifted.
    """
    if model_meta is None:
        return False
    drift_df = outcomes_drift_dataframe(
        outcome_definitions, model_meta, available_columns=available_columns
    )
    if drift_df.empty:
        return False
    drifted = drift_df[drift_df["drift_status"] != "Fitted and current"]
    if drifted.empty:
        return False
    has_blocking = bool(drifted["drift_status"].isin(BLOCKING_DRIFT_STATUSES).any())
    message = (
        f"The fitted model no longer matches {len(drifted)} outcome definition(s)."
    )
    consequence = (
        "Refit the model or restore the fitted definitions before using "
        "results that depend on this fit."
        if has_blocking
        else "Review the changes before interpreting current evidence."
    )
    if has_blocking and blocking:
        st.error(message + " " + consequence)
    elif has_blocking:
        st.warning(message + " " + consequence)
    else:
        st.info(message + " " + consequence)
    with st.expander("See outcome changes"):
        detail = drifted.copy()
        detail["Outcome"] = detail.apply(
            lambda row: " · ".join(
                str(value).replace("_", " ").title()
                for value in (
                    row.get("product", "Outcome"),
                    row.get("segment", ""),
                    row.get("metric", ""),
                )
                if value
            ),
            axis=1,
        )
        detail["What changed"] = (
            detail["drift_status"]
            .map(
                {
                    "Changed since fit": "Definition changed; refit required",
                    "Removed since fit": "Definition no longer exists; refit required",
                    "Missing source column": "Source data is unavailable",
                    "New since fit": "Not included in this fit",
                    "Excluded from next fit": "Excluded from a future fit",
                }
            )
            .fillna("Review the definition change")
        )
        st.dataframe(detail[["Outcome", "What changed"]], width="stretch")
    render_technical_details(
        title="Technical details · outcome definition changes",
        details={
            "Exact outcome IDs": ", ".join(
                str(row.outcome_id) for row in drifted.itertuples()
            ),
            "Status keys": ", ".join(
                f"{row.outcome_id}: {row.drift_status}" for row in drifted.itertuples()
            ),
        },
    )
    return has_blocking
