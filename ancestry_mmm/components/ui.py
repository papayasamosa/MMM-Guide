"""Shared page chrome and guidance components: theme CSS, grouped sidebar
navigation, the project context bar, compact page headers, panel
primitives, next-step panels, empty/blocked/stale states, status cards and
a compact glossary. Every page uses these instead of re-implementing its
own header/sidebar/footer markup, so behaviour and styling stay consistent.

Phase 1 of the Streamlit UI/UX overhaul (see docs/decision_log.md) added:
grouped nav with per-page readiness indicators, the project context bar, a
compact page header (title/description/badges/actions, with detailed
step-by-step guidance moved into a collapsed expander), and the
SectionCard/InfoPanel/WarningPanel/BlockingPanel container primitives. All
of it is presentation only - readiness/context signals are read from
existing session-state getters (ancestry_mmm.utils.session_state), never
invented, and no analytical/governance behaviour changed.
"""

import contextlib
import html as _html
from typing import Any, Callable, Dict, Iterable, List, Optional

import streamlit as st

from ancestry_mmm.utils.config import THEME_COLORS
from ancestry_mmm.utils.display import GLOSSARY
from ancestry_mmm.utils.session_state import get_state
from ancestry_mmm.utils.workflow import (
    HOME_KEY,
    get_step,
    nav_groups,
    next_step_key,
    step_number,
)
from ancestry_mmm.utils.workflow_state import (
    next_workflow_step_key,
    workflow_page_states,
    workflow_page_state,
)
from ancestry_mmm.components.tokens import shell_css
from ancestry_mmm.components.status import render_status_badges
from ancestry_mmm.core.outcomes import BLOCKING_DRIFT_STATUSES, outcomes_drift_dataframe


def apply_theme() -> None:
    """Inject the small amount of CSS not reachable via .streamlit/config.toml's
    [theme] section. Call once near the top of every page, after
    st.set_page_config(). The base dark-green palette itself comes from the
    theme config, which applies automatically on every page.
    """
    st.markdown(
        f"""
        <style>
        .muted {{ color: {THEME_COLORS["foreground_muted"]}; }}
        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        /* st.info() defaults to Streamlit's fixed blue, which reads as "strong
           blue" against an otherwise all-green palette - retint it to a muted
           green-gray so info messages stay calm and on-palette. */
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
            background-color: rgba(107, 139, 122, 0.18) !important;
        }}
        [data-testid="stAlertContentInfo"] {{ color: {THEME_COLORS["foreground_muted"]} !important; }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(shell_css(), unsafe_allow_html=True)


# Readiness -> sidebar icon. Deliberately never colour-only: the same
# readiness key also drives a text-labelled badge wherever it's shown
# alongside a page header (components/status.py), this is just the compact
# nav-row form of the same vocabulary.
_READINESS_ICON = {
    "complete": "OK",
    "configured": "~",
    "saved": "OK",
    "validated": "OK",
    "draft": "D",
    "approved": "OK",
    "stale": "!",
    "review": "?",
    "unavailable": "!",
    "ready": "✅",
    "blocked": "🔒",
    "not_started": "⚪",
    "optional": "◽",
}


def page_readiness(key: str) -> str:
    """Return the canonical lifecycle/access status for one workflow page."""
    return workflow_page_state(key, getter=get_state).display_status


def group_readiness(keys: Iterable[str]) -> str:
    """Aggregate canonical page states into one workflow-area status."""
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
    if any(s in {"blocked", "stale", "review", "unavailable"} for s in scored):
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
        st.markdown("**Marketing Mix Modelling**")
        st.caption("New · DNA cross-sell · Winback")
        st.markdown("---")
        for group in nav_groups():
            st.markdown(
                f'<div class="mmm-nav-group">{group["label"]}</div>',
                unsafe_allow_html=True,
            )
            for entry in group["entries"]:
                key = entry["key"]
                icon = (
                    None
                    if key == HOME_KEY
                    else _READINESS_ICON.get(page_readiness(key))
                )
                st.page_link(entry["path"], label=entry["label"], icon=icon)
        st.markdown("---")
        states = workflow_page_states(getter=get_state)
        required = [state for state in states if not state.optional]
        satisfied = sum(1 for state in required if state.satisfied)
        st.caption(
            f"Workflow state: {satisfied}/{len(required)} required stages satisfied; iterative"
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

    df = get_state("transformed_data")
    date_col = get_state("date_col")
    if df is not None and date_col and date_col in getattr(df, "columns", []):
        try:
            start, end = df[date_col].min(), df[date_col].max()
            items.append(("Model window", _html.escape(f"{start} to {end}")))
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
    badges: Optional[Iterable[str]] = None,
    primary_action: Optional[Dict[str, Any]] = None,
    secondary_actions: Optional[Iterable[Dict[str, Any]]] = None,
) -> None:
    """Compact top-of-page block (Phase 1 item #4): workflow context, title,
    one-sentence task description, status badges, and up to one dominant
    primary action plus optional secondary actions - without a multi-step
    tutorial dumped above the workspace on every visit. Detailed
    step-by-step guidance moves into a collapsed "Step-by-step guidance"
    expander, still available, never removed.

    Every parameter is optional and additive - `render_page_header(key)`
    behaves the same as every existing call site (title/description/steps),
    just with the steps list collapsed. `badges`/`primary_action`/
    `secondary_actions` are opt-in for pages that want the fuller header.

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
        st.caption(f"{group_label} Â· {step['label']}")

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
        if badge_keys:
            render_status_badges(badge_keys)

    if action_col is not None:
        with action_col:
            if primary_action:
                _render_header_action(primary_action, primary=True, idx=0)
            for i, action in enumerate(secondary_actions or [], start=1):
                _render_header_action(action, primary=False, idx=i)

    if step.get("steps"):
        with st.expander("Step-by-step guidance", expanded=False):
            st.markdown(
                "\n".join(f"{i}. {s}" for i, s in enumerate(step["steps"], start=1))
            )


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
def _panel(kind: str, title: str, *, description: Optional[str] = None, icon: str = ""):
    """Shared implementation behind SectionCard/InfoPanel/WarningPanel/
    BlockingPanel - a bordered st.container() carrying a hidden marker span
    that tokens.shell_css()'s :has() rules use to tint the container by
    kind. Falls back to a plain bordered container (no tint) if the marker
    selector ever stops matching a future Streamlit release's DOM - the
    title/description content itself is unaffected either way.
    """
    with st.container(border=True):
        st.markdown(
            f'<span class="mmm-panel-marker-{kind}" style="display:none"></span>'
            f'<div class="mmm-panel-title">{icon} {title}</div>'.strip(),
            unsafe_allow_html=True,
        )
        if description:
            st.caption(description)
        yield


def SectionCard(title: str, *, description: Optional[str] = None):
    """A neutral bordered card for grouping related content under one
    heading - the plain building block panels below layer meaning onto."""
    return _panel("neutral", title, description=description)


def InfoPanel(title: str, *, description: Optional[str] = None):
    """A bordered, info-tinted panel for neutral contextual information."""
    return _panel("info", title, description=description, icon="ℹ")


def WarningPanel(title: str, *, description: Optional[str] = None):
    """A bordered, caution-tinted panel for a non-blocking warning."""
    return _panel("caution", title, description=description, icon="⚠")


def BlockingPanel(title: str, *, description: Optional[str] = None):
    """A bordered, negative-tinted panel for a condition that blocks the
    page's primary action until resolved."""
    return _panel("negative", title, description=description, icon="⛔")


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
        if st.button(
            f"Continue to {nxt['label']} →",
            type="primary",
            key=f"next_{key}{key_suffix}",
        ):
            st.switch_page(nxt["path"])


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
    first line shown - every existing call site (`render_empty_state(msg,
    button_label=..., target_key=...)`) behaves identically to before this
    change. The optional `what_for`/`dependency`/`next_action` let a caller
    additionally state, as structured lines under `message` (Phase 1 item
    #7): what this workspace is for, which dependency is missing, and the
    next action to take. `blocking=True` renders as `st.error` instead of
    `st.info`, for a page that must stop rather than just flag a gap.
    """
    lines = [message]
    if what_for:
        lines.append(f"**This workspace is for:** {what_for}")
    if dependency:
        lines.append(f"**Missing dependency:** {dependency}")
    if next_action:
        lines.append(f"**Next action:** {next_action}")
    text = "\n\n".join(lines)
    if blocking:
        st.error(text)
    else:
        st.info(text)
    if button_label and target_key:
        target = get_step(target_key)
        if target and st.button(
            button_label, key=f"empty_state_{target_key}{key_suffix}"
        ):
            st.switch_page(target["path"])


def render_status_card(label: str, value: str, ready: bool) -> None:
    """One compact bordered status card, used on the Home page."""
    with st.container(border=True):
        st.caption(label)
        st.markdown(f"{'✓' if ready else '○'} **{value}**")


def render_glossary(terms: Optional[Iterable[str]] = None) -> None:
    """Compact glossary expander. Pass `terms` to show a subset relevant to
    the current page; omit it to show the full glossary."""
    entries: Dict[str, Any] = (
        {t: GLOSSARY[t] for t in terms if t in GLOSSARY} if terms else GLOSSARY
    )
    with st.expander("Glossary"):
        for term, definition in entries.items():
            st.markdown(f"**{term}** - {definition}")


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
    Export. Shows the exact changed fields per outcome_id
    (`core.outcomes.outcomes_drift_dataframe`), not just a bare "stale"
    flag. Returns `True` if calculation-relevant drift was found
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
        f"{len(drifted)} outcome(s) have drifted from the fitted model's catalogue: "
        f"{', '.join(f'{row.outcome_id} ({row.drift_status})' for row in drifted.itertuples())}."
    )
    if has_blocking and blocking:
        st.error(
            message
            + " Calculation-relevant drift - this must be resolved (re-fit, or revert the catalogue change) before continuing."
        )
    elif has_blocking:
        st.warning(
            message
            + " Calculation-relevant - numbers shown may no longer reflect the live catalogue."
        )
    else:
        st.info(message)
    with st.expander("Drift detail"):
        st.dataframe(drift_df[["outcome_id", "drift_status"]], width="stretch")
    return has_blocking
