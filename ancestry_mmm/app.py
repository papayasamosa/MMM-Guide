"""
Family History & DNA MMM (Home)

An in-house Family History & DNA marketing-measurement and scenario-planning tool built around
Ancestry's actual FH measurement problem: three acquisition paths (New,
DNA cross-sell, Winback) with different media response, different
promotional sensitivity and different value, modelled jointly rather than
as one blended KPI - plus an explicit DNA halo pathway, a versioned curve
bank, and constrained scenario planning.

Phase 2 of the Streamlit UI/UX overhaul (see docs/decision_log.md)
redesigns this page as a compact project-state dashboard: the single next
recommended action, current project state, open issues, a workflow map, and
a synthetic-demo entry point for a new project. Every signal shown is read from existing session-state getters
or tested `ancestry_mmm.core` functions (outcome drift, validation
readiness) - never invented. The old numbered workflow tutorial is kept,
unchanged, in a collapsed expander rather than removed outright.

See docs/ancestry_fh_mmm.md for the full requirements this build serves.

Run with: streamlit run ancestry_mmm/app.py
"""

import streamlit as st
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from ancestry_mmm.utils import init_session_state, get_state, clear_model_state
from ancestry_mmm.utils.workflow import (
    WORKFLOW_STEPS,
    get_step,
    nav_groups,
    workflow_label,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_context_bar,
    render_status_badges,
    page_readiness,
    group_readiness,
    next_recommended_step_key,
    SectionCard,
    InfoPanel,
)
from ancestry_mmm.data import load_all_sample_sources
from ancestry_mmm.core.coverage import (
    SourceDefinition,
    DOMAIN_OUTCOMES,
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.outcomes import (
    resolve_outcome_definitions,
    outcomes_drift_dataframe,
)

_QUICK_LINKS = [
    ("Data Sources", "pages/01_Data_Upload.py"),
    ("Coverage & Gaps", "pages/15_Data_Coverage.py"),
    ("Model Diagnostics", "pages/06_Diagnostics.py"),
    ("Results & Response Curves", "pages/07_Results_Curve_Bank.py"),
    ("Scenario Planner", "pages/08_Scenario_Planner.py"),
    ("Export & Recovery", "pages/09_Project_Export.py"),
]


def setup_page_config():
    st.set_page_config(
        page_title="Ancestry | Family History & DNA MMM",
        layout="wide",
        initial_sidebar_state="expanded",
    )


def _load_synthetic_demo() -> None:
    """Load the built-in synthetic demo sources into session state.

    Mirrors pages/01_Data_Upload.py's "Load synthetic demo sources" action
    exactly - same session-state keys, same logical-domain classification
    (REQ-DATAIN-001) - so a demo loaded from Home behaves identically to
    one loaded from Data Upload. Duplicated rather than imported because a
    Streamlit page script isn't an importable module in this app; nothing
    here is model/business logic, only the same session-state wiring the
    Data Upload page already performs.
    """
    frames, err = load_all_sample_sources()
    if err:
        st.error(err)
        return
    ltv_df = frames.pop("ltv")
    st.session_state["raw_sources"] = frames
    st.session_state["sample_ltv"] = {
        row.segment: row.ltv for row in ltv_df.itertuples()
    }
    st.session_state["active_source_upload_version"] = {}
    demo_domains = {
        "media": DOMAIN_ACTIVITY_AND_MEDIA,
        "outcomes": DOMAIN_OUTCOMES,
        "controls": DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    }
    st.session_state["source_definitions"] = [
        SourceDefinition(source_id=name, name=name, logical_domain=domain).to_dict()
        for name, domain in demo_domains.items()
        if name in frames
    ]
    st.session_state["data_loaded"] = True
    clear_model_state()
    st.success(
        "Loaded synthetic demo sources: "
        + ", ".join(
            f"{k} ({v.shape[0]} rows x {v.shape[1]} cols)" for k, v in frames.items()
        )
    )


def _command_targets() -> list:
    """Fixed command list for the command palette: one navigation command
    per workflow page, plus "load the demo" only while there is no real or
    demo data loaded yet (so the palette can never silently overwrite an
    existing upload the way it could if offered unconditionally)."""
    commands = [
        {"label": f"Go to {step['label']}", "path": step["path"]}
        for step in WORKFLOW_STEPS
    ]
    if not get_state("data_loaded"):
        commands.insert(0, {"label": "Load demo data", "action": "load_demo"})
    return commands


@st.dialog("Command palette")
def _command_palette_dialog() -> None:
    query = st.text_input(
        "Filter commands",
        key="home_palette_filter",
        placeholder="Type to filter, e.g. 'diagnostics'",
    )
    commands = _command_targets()
    if query:
        q = query.lower()
        commands = [c for c in commands if q in c["label"].lower()]
    if not commands:
        st.caption("No matching commands.")
    for i, cmd in enumerate(commands):
        if st.button(cmd["label"], key=f"palette_cmd_{i}", width="stretch"):
            if cmd.get("action") == "load_demo":
                _load_synthetic_demo()
            else:
                st.switch_page(cmd["path"])
            st.rerun()


def _render_next_action(*, compact: bool = False) -> None:
    """Item 1: the single dominant "what should I do next" element,
    derived from `next_recommended_step_key()` (Phase 1's
    `page_readiness()`, extended by composition). Doubles as item 4 (the
    synthetic-demo entry point) when no project data is loaded yet, since
    that *is* the next recommended action in that state.
    """
    card = (
        st.container(border=True) if compact else SectionCard("Next recommended action")
    )
    with card:
        if compact:
            st.markdown("### Next recommended action")
        if not get_state("data_loaded"):
            st.markdown(
                "No project data loaded yet. Load the built-in **synthetic demo "
                "dataset** to explore the app end-to-end - clearly not real "
                "Ancestry data - or upload your own sources."
            )
            col_demo, col_upload = st.columns(2)
            with col_demo:
                if st.button(
                    "Load demo data",
                    type="primary",
                    width="stretch",
                    key="home_load_demo",
                ):
                    _load_synthetic_demo()
                    st.rerun()
            with col_upload:
                if st.button(
                    "Upload your own data", width="stretch", key="home_go_upload"
                ):
                    st.switch_page("pages/01_Data_Upload.py")
            return

        next_key = next_recommended_step_key()
        if next_key is None:
            st.markdown(
                "Every required workflow stage is ready. Review results in "
                "**Results & Response Curves**, plan a scenario, or export the "
                "project bundle."
            )
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button(
                    "Go to Results & Response Curves",
                    type="primary",
                    width="stretch",
                    key="home_go_results",
                ):
                    st.switch_page("pages/07_Results_Curve_Bank.py")
            with col_b:
                if st.button(
                    "Go to Export & Recovery", width="stretch", key="home_go_export"
                ):
                    st.switch_page("pages/09_Project_Export.py")
            return

        step = get_step(next_key)
        st.markdown(f"**{step['label']}**")
        if step.get("purpose"):
            st.caption(step["purpose"])
        if st.button(
            f"Continue to {step['label']} →",
            type="primary",
            key="home_next_action",
        ):
            st.switch_page(step["path"])


def _render_topology() -> None:
    """Render workflow-area lifecycle state from the canonical page model.

    The OVERVIEW group (Home itself) is omitted because it has no page
    lifecycle of its own. Optional pages are shown as optional/configured and
    do not count as required-stage completion.
    """
    with SectionCard(
        "Workflow map",
        description="Current stage and attention state across the analytical workflow.",
    ):
        groups = [g for g in nav_groups() if g["label"] != "OVERVIEW"]
        cols = st.columns(len(groups))
        for col, group in zip(cols, groups):
            keys = [e["key"] for e in group["entries"]]
            status = group_readiness(keys)
            complete = sum(
                1
                for k in keys
                if page_readiness(k)
                in {"complete", "configured", "saved", "validated", "approved", "draft"}
            )
            with col:
                with st.container():
                    st.caption(group["label"])
                    render_status_badges([status])
                    st.caption(f"{complete} of {len(keys)} stages progressed")


def _collect_issues() -> list[str]:
    """Item 3: concrete, deterministically-derived open issues - never
    speculative text. Each condition below is traced to an existing
    getter or tested core function:

    - outcome-catalogue drift relative to the fitted model
      (`core.outcomes.outcomes_drift_dataframe`, the same function
      `render_drift_status` already uses elsewhere in the app);
    - a fitted model whose validation gates are blocking approval, or
      that simply hasn't been reviewed for approval yet
      (`approval_readiness`/`model_approval` session state, the same
      governance state Diagnostics reads);
    - an approved model with no curves yet saved to the curve bank.
    """
    issues: list = []

    spec_dict = get_state("model_spec")
    model_meta = get_state("model_meta")
    if spec_dict and model_meta is not None:
        spec = ModelSpec.from_dict(spec_dict)
        drift_df = outcomes_drift_dataframe(
            resolve_outcome_definitions(
                get_state("outcome_definitions"),
                spec.segment_outcomes,
                spec.segment_ltv,
            ),
            model_meta,
        )
        if not drift_df.empty:
            drifted = drift_df[drift_df["drift_status"] != "Fitted and current"]
            if not drifted.empty:
                outcome_ids = ", ".join(sorted(drifted["outcome_id"].astype(str)))
                issues.append(
                    f"{len(drifted)} outcome(s) have drifted from the fitted model's "
                    f"catalogue ({outcome_ids}) - review on {workflow_label('diagnostics')} "
                    f"or {workflow_label('curve_bank')}."
                )

    trained = bool(get_state("model_trained"))
    scorecard = get_state("scorecard")
    approval = get_state("model_approval")
    readiness = get_state("approval_readiness")
    if trained and scorecard and not approval:
        if readiness and not readiness.get("overall_ready", False):
            blocking = readiness.get("blocking_failures", []) or []
            gate_names = [
                g.get("gate_name", "") for g in blocking if g.get("gate_name")
            ]
            detail = f" ({', '.join(gate_names)})" if gate_names else ""
            issues.append(
                f"{len(blocking)} blocking validation gate(s) failing{detail} - the "
                f"model cannot be approved until resolved ({workflow_label('diagnostics')})."
            )
        else:
            issues.append(
                "Model fit and diagnostics computed, but not yet approved for "
                f"planning ({workflow_label('diagnostics')})."
            )

    if approval and not get_state("curve_bank_entry_id"):
        issues.append(
            "Model is approved but no curves have been saved to the curve bank "
            f"yet ({workflow_label('curve_bank')})."
        )

    return issues


def _render_project_state() -> None:
    """Show only state that can be derived from the current project bundle."""
    with st.container(border=True):
        st.markdown("### Project state")
        project_name = get_state("project_name") or "Unnamed project"
        st.markdown(f"**{project_name}**")
        raw_sources = get_state("raw_sources") or {}
        if raw_sources:
            source_kind = (
                "Uploaded sources"
                if get_state("active_source_upload_version")
                else "Demo data"
            )
            st.caption(f"Data: {source_kind} · {len(raw_sources)} data sources")
        else:
            st.caption("Data: no sources loaded")
        if get_state("model_approval"):
            st.caption("Model: approved")
        elif get_state("model_trained"):
            st.caption("Model: fitted, review still required")
        elif get_state("transformed_data") is not None:
            st.caption("Model: data prepared, not fitted")
        else:
            st.caption("Model: not started")


def _render_issues(*, compact: bool = False) -> None:
    issues = _collect_issues()
    card = (
        st.container(border=True)
        if compact
        else SectionCard("Issues requiring attention")
    )
    with card:
        if compact:
            st.markdown("### Needs attention")
        if not issues:
            st.caption("No open issues detected from the current project state.")
        else:
            for issue in issues[:3]:
                st.markdown(f"- {issue}")
            if len(issues) > 3:
                st.caption(
                    f"{len(issues) - 3} more issue(s) are visible on the relevant workspace."
                )


def _render_lineage() -> None:
    """Item 5: a light-touch lineage/provenance summary - current model
    run, approval status, curve bank and scenario counts. Renders nothing
    until a model has actually been fit at least once (`model_run_id`),
    rather than showing placeholder fields for data that doesn't exist
    yet.
    """
    model_run_id = get_state("model_run_id")
    if not model_run_id:
        return
    with InfoPanel("Model lineage"):
        approval = get_state("model_approval")
        approval_status = (
            "Approved"
            if approval
            else ("Fit, not approved" if get_state("model_trained") else "Not fit")
        )
        curve_entry = get_state("curve_bank_entry_id")
        curve_status = (
            f"Curve saved (`{str(curve_entry)[:8]}`)"
            if curve_entry
            else "No curves saved yet"
        )
        scenarios = get_state("scenarios") or []
        st.markdown(
            f"**Approval:** {approval_status} &nbsp;·&nbsp; "
            f"**Curve bank:** {curve_status} &nbsp;·&nbsp; "
            f"**Scenarios saved:** {len(scenarios)}"
        )
        with st.expander("Technical details"):
            st.caption(f"Model run ID: {str(model_run_id)[:8]}")


def _render_quick_links() -> None:
    """Item 6: fast navigation for a returning analyst who already knows
    what they want - kept (and modestly extended) so Home doesn't get
    slower for a repeat user just because it now says more to a new one.
    """
    st.caption("Quick links")
    cols = st.columns(len(_QUICK_LINKS))
    for col, (label, path) in zip(cols, _QUICK_LINKS):
        with col:
            if st.button(label, width="stretch", key=f"home_quicklink_{path}"):
                st.switch_page(path)


def main():
    setup_page_config()
    init_session_state()
    apply_theme()
    render_sidebar("home")
    render_context_bar()

    title_col, palette_col = st.columns([3, 1])
    with title_col:
        st.markdown(
            '<div class="mmm-home-identity">'
            '<h1 class="mmm-home-product">Family History &amp; DNA MMM</h1>'
            '<div class="mmm-home-description">Marketing measurement and planning '
            "across Family History and DNA.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
    with palette_col:
        if st.button("Command palette", key="home_open_palette", width="stretch"):
            _command_palette_dialog()

    summary_cols = st.columns([1.35, 1, 1])
    with summary_cols[0]:
        _render_next_action(compact=True)
    with summary_cols[1]:
        _render_project_state()
    with summary_cols[2]:
        _render_issues(compact=True)

    _render_topology()

    _render_lineage()

    _render_quick_links()


if __name__ == "__main__":
    main()
