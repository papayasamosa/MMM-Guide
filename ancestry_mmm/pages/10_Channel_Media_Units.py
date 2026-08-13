"""Configure governed activity mappings and physical media-unit inputs.

The activity workspace captures reporting, modelling, planning, evidence, and
provenance fields before the page's separate Search-object and media-unit
configuration sections.
"""

import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    clear_model_state,
    get_state,
    init_session_state,
    readable_label,
    set_state,
    display_enum_frame,
    display_enum_options,
    restore_enum_frame,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    page_readiness,
    render_workspace_note,
    SectionCard,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig,
    MarketSpecConfig,
    UNIT_TYPE_SUGGESTIONS,
    COST_BASIS_SUGGESTIONS,
)
from ancestry_mmm.core.activities import (
    APPROVAL_STATUSES,
    ECONOMIC_TREATMENTS,
    FUNNEL_STAGES,
    MODEL_ROLES,
    OWNERSHIP,
    PLANNING_ELIGIBILITY,
    ActivityDefinition,
    activity_invalidation,
    legacy_activity_definitions_from_model_spec,
)
from ancestry_mmm.core.search_objects import (
    SEARCH_OBJECT_STATES,
    SEARCH_ROLES,
    SEARCH_UNITS,
    SearchObjectDefinition,
    new_search_object_version,
    validate_search_object_catalogue,
)
from ancestry_mmm.data import detect_column_types

st.set_page_config(
    page_title="Activity Mapping | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("channel_media_units")
render_page_header(
    "channel_media_units",
    task_prompt="Are model inputs, delivery measures, and caps mapped as separate objects?",
    badges=[page_readiness("channel_media_units")],
)
render_workspace_note(
    "Separate concepts",
    "Fitted inputs, Search objects, physical delivery, caps, and cost mappings stay distinct for reporting and planning.",
    kind="governed",
)

spec_dict = get_state("model_spec")
df = get_state("transformed_data")
if df is None:
    st.markdown("---")
    render_empty_state(
        "No prepared data yet. Complete Prepare Data first.",
        button_label="Go to Prepare Data",
        target_key="transform_pipeline",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict) if spec_dict else None
date_col = get_state("date_col")
market_col = get_state("market_col")
hints = detect_column_types(df)
numeric_cols = hints["numeric"]
if market_col and market_col in df.columns:
    mapping_markets = sorted(df[market_col].dropna().astype(str).unique().tolist())
else:
    mapping_markets = ["default"]
mapping_markets = mapping_markets or ["default"]
existing_activity_items = get_state("activity_definitions") or []
legacy_activity_rows = (
    legacy_activity_definitions_from_model_spec(spec) if spec is not None else []
)
activity_seed_rows = existing_activity_items or [
    definition.to_dict() for definition in legacy_activity_rows
]
available_model_inputs = list(numeric_cols)
for item in activity_seed_rows:
    input_column = str(item.get("model_input_column") or item.get("channel") or "")
    if input_column and input_column not in available_model_inputs:
        available_model_inputs.append(input_column)
if spec is not None:
    for input_column in spec.channels:
        if input_column not in available_model_inputs:
            available_model_inputs.append(input_column)
render_definition_help(
    "a response curve",
    "A range of predicted incremental outcomes as a media input changes. It is interpreted on the outcome scale and carries its own observed-support and governance status.",
)
render_decision_help(
    "How should I map media and Search inputs?",
    controls="The relationship between the fitted model input, monetary spend, physical delivery, Search demand, Search delivery, and any cap.",
    why="These are different objects. Keeping them separate prevents a spend value, a delivery measure, a demand signal, and a cap from being silently used as one another.",
    options={
        "Model input": "Choose the observed series the fitted response uses; it may be spend, impressions, clicks, TVRs, GRPs, or another governed unit.",
        "Physical delivery": "Map the observed delivery measure when you need delivery or response-unit reporting.",
        "Search demand / delivery / cap": "Register the Search role explicitly. A cap constrains delivery and is never realised spend; demand and delivery are not interchangeable.",
        "Planning eligibility": "Allow planning only when the input, evidence, cost translation, and governance support it.",
    },
    normal_path="Map the model input first, add separate activity and Search objects where relevant, then add physical and cost mappings only when the source supports them.",
    downstream="The mappings determine attribution labels, response-unit views, monetary conversion, and whether a channel can be used by Planning Curves or Scenario Planner.",
    invalidates="Changing a mapping or Search role changes fit identity or planning evidence as applicable. Save the mapping, then refit or regenerate the affected governed artefact before relying on it.",
)
st.caption(
    "Keep fitted inputs, Search demand/delivery/caps, and physical delivery or cost mappings "
    "separate. These fields answer different causal, reporting, and planning questions."
)

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)
saved_search_object_items = get_state("search_objects") or []
saved_media_unit_count = sum(
    1
    for config in market_config.channel_media_units.values()
    if config.has_media_unit()
)

with st.container(border=True):
    st.markdown("### Mapping summary")
    st.caption(
        "Saved mappings only. The editors below keep model input, monetary spend, physical delivery, Search roles, and planning eligibility distinct."
    )
    summary_cols = st.columns(4)
    summary_cols[0].metric(
        "Markets", len(spec.markets) if spec is not None else len(mapping_markets)
    )
    summary_cols[1].metric("Governed activities", len(existing_activity_items))
    summary_cols[2].metric("Saved Search objects", len(saved_search_object_items))
    summary_cols[3].metric("Physical mappings", saved_media_unit_count)
render_technical_details(
    details={
        "Persisted values": "Editor labels are display-only. Raw activity roles, Search roles, units, approval states, and planning states are restored before validation and saving.",
        "Search identity": "Search object IDs are versioned by market and lineage; editing a saved row creates a new version and keeps the prior version in history.",
        "Provenance": "Source, effective dates, approval fields, and cost-mapping assumptions remain part of the governed mapping record.",
    }
)

with SectionCard(
    "Activity mapping",
    description=(
        "Identify each activity first. Edit its model, planning, evidence, and "
        "provenance details only when needed."
    ),
):
    st.caption(
        "Use one row per market and activity. Multiple activities may share a "
        "reporting channel when their model-input columns differ."
    )

    activity_definitions = [
        ActivityDefinition.from_dict(item) for item in activity_seed_rows
    ]
    overview_rows = [
        {
            "Market": item.market,
            "Activity": item.activity_id,
            "Reporting channel": item.channel,
            "Platform": item.platform,
            "Funnel stage": readable_label(item.funnel_stage),
            "Media input": item.resolved_model_input_column,
            "Planning eligibility": readable_label(item.planning_eligibility),
            "Review status": readable_label(item.approval_status),
        }
        for item in activity_definitions
    ]
    if overview_rows:
        st.dataframe(pd.DataFrame(overview_rows), width="stretch", hide_index=True)
        st.caption(
            "Overview fields are for comparison. Select an activity below to edit "
            "its complete governed record."
        )
    else:
        st.info(
            "No governed activities exist yet. Add the first activity below and "
            "choose its media input explicitly; numeric columns are candidates "
            "only and are never classified automatically."
        )

    activity_mode = st.session_state.setdefault(
        "activity_detail_mode", "edit" if activity_definitions else "add"
    )
    selected_index = 0
    if activity_definitions:
        selected_index = st.selectbox(
            "Selected activity",
            list(range(len(activity_definitions))),
            index=min(
                int(st.session_state.get("activity_selected_index", 0)),
                len(activity_definitions) - 1,
            ),
            format_func=lambda index: (
                f"{activity_definitions[index].market} · "
                f"{activity_definitions[index].activity_id} · "
                f"{activity_definitions[index].channel} · "
                f"{activity_definitions[index].resolved_model_input_column}"
            ),
            key="activity_selected_index",
        )
        selected_index = int(selected_index)
        selected_activity = activity_definitions[selected_index]
        actions = st.columns(3)
        if actions[0].button("Add activity", key="add_activity_detail"):
            st.session_state["activity_detail_mode"] = "add"
            st.rerun()
        if actions[1].button("Edit selected activity", key="edit_activity_detail"):
            st.session_state["activity_detail_mode"] = "edit"
            st.rerun()
        remove_confirmation = st.checkbox(
            "I understand this removes the selected mapping",
            key="remove_activity_confirmation",
        )
        if actions[2].button(
            "Remove selected activity",
            key="remove_activity_detail",
            disabled=not remove_confirmation,
        ):
            remaining = [
                item
                for index, item in enumerate(activity_definitions)
                if index != selected_index
            ]
            set_state("activity_definitions", [item.to_dict() for item in remaining])
            clear_model_state()
            set_state("scenarios", [])
            st.warning(
                "Removed the selected activity. The fitted model, approval, curves, "
                "and scenarios were cleared because the model scope changed."
            )
            activity_definitions = remaining
            st.session_state["activity_detail_mode"] = "edit"
            st.session_state["remove_activity_confirmation"] = False
            selected_activity = (
                activity_definitions[0] if activity_definitions else None
            )
        else:
            selected_activity = activity_definitions[selected_index]
    else:
        selected_activity = None
        if st.button("Add activity", key="add_activity_first"):
            st.session_state["activity_detail_mode"] = "add"

    is_new_activity = activity_mode == "add" or selected_activity is None
    if is_new_activity:
        detail = SimpleNamespace(
            activity_id="",
            market=mapping_markets[0],
            channel="",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="activity governance UI",
            model_input_column=(
                available_model_inputs[0] if available_model_inputs else ""
            ),
            resolved_model_input_column=(
                available_model_inputs[0] if available_model_inputs else ""
            ),
            platform="",
            campaign_type="",
            product_advertised="",
            message_type="",
            marketing_objective="",
            funnel_stage="unclassified",
            pooling_group_id=None,
            pathway_ids=(),
            evidence_status="not_assessed",
            evidence_source="",
            rationale="",
            limitations="",
            approval_status="draft",
            reviewed_by="",
            reviewed_at="",
            approved_by=None,
            approved_at=None,
            governance_notes="",
            supersedes_activity_id=None,
            schema_version=4,
            change_history=(),
        )
    else:
        detail = selected_activity

    def _text(value: object) -> str:
        return "" if value is None else str(value)

    def _options(values, current: str) -> list[str]:
        options = list(values)
        if current and current not in options:
            options.insert(0, current)
        return options or [""]

    with st.form("activity_detail_form", clear_on_submit=False):
        st.markdown(
            "### Add activity"
            if activity_mode == "add" or selected_activity is None
            else f"### Edit {detail.activity_id}"
        )
        st.caption(
            "The detail form keeps every governed field accessible while the "
            "overview stays compact."
        )

        st.markdown("#### Identity and reporting")
        identity_a, identity_b = st.columns(2)
        activity_id = identity_a.text_input(
            "Activity ID *",
            value=_text(detail.activity_id),
            help="Stable identity for this activity in its market.",
        )
        market = identity_b.selectbox(
            "Market *",
            _options(mapping_markets, detail.market),
            index=_options(mapping_markets, detail.market).index(detail.market),
        )
        report_a, report_b = st.columns(2)
        channel = report_a.text_input(
            "Reporting channel *",
            value=_text(detail.channel),
            help="A shared reporting label; it is separate from the model input.",
        )
        platform = report_b.text_input(
            "Platform / supplier", value=_text(detail.platform)
        )
        campaign_a, campaign_b = st.columns(2)
        campaign_type = campaign_a.text_input(
            "Campaign / tactic", value=_text(detail.campaign_type)
        )
        product_advertised = campaign_b.text_input(
            "Product advertised", value=_text(detail.product_advertised)
        )
        message_a, message_b = st.columns(2)
        message_type = message_a.text_input(
            "Message / content", value=_text(detail.message_type)
        )
        marketing_objective = message_b.text_input(
            "Marketing objective",
            value=_text(detail.marketing_objective),
            help="Optional normalized business purpose; never inferred from names or platform.",
        )
        funnel_stage = st.selectbox(
            "Funnel stage *",
            _options(FUNNEL_STAGES, detail.funnel_stage),
            index=_options(FUNNEL_STAGES, detail.funnel_stage).index(
                detail.funnel_stage
            ),
            format_func=readable_label,
        )
        pooling_group_id = st.text_input(
            "Comparable activity group",
            value=_text(detail.pooling_group_id),
            help="Stable cross-market reporting identity only; it does not choose statistical pooling.",
        )

        st.markdown("#### Model and planning")
        model_input_column = st.selectbox(
            "Media input column *",
            _options(available_model_inputs, detail.resolved_model_input_column),
            index=_options(
                available_model_inputs, detail.resolved_model_input_column
            ).index(detail.resolved_model_input_column),
            format_func=readable_label,
            help="The observed model input. It may be spend, impressions, clicks, TVRs, GRPs, or another governed unit.",
        )
        model_a, model_b = st.columns(2)
        activity_ownership = model_a.selectbox(
            "Activity ownership *",
            sorted(OWNERSHIP),
            index=sorted(OWNERSHIP).index(detail.activity_ownership)
            if detail.activity_ownership in OWNERSHIP
            else 0,
            format_func=readable_label,
        )
        model_role = model_b.selectbox(
            "Model role *",
            sorted(MODEL_ROLES),
            index=sorted(MODEL_ROLES).index(detail.model_role)
            if detail.model_role in MODEL_ROLES
            else 0,
            format_func=readable_label,
        )
        economics_a, economics_b = st.columns(2)
        economic_treatment = economics_a.selectbox(
            "Cost treatment *",
            sorted(ECONOMIC_TREATMENTS),
            index=sorted(ECONOMIC_TREATMENTS).index(detail.economic_treatment)
            if detail.economic_treatment in ECONOMIC_TREATMENTS
            else 0,
            format_func=readable_label,
        )
        planning_eligibility = economics_b.selectbox(
            "Planning eligibility *",
            sorted(PLANNING_ELIGIBILITY),
            index=sorted(PLANNING_ELIGIBILITY).index(detail.planning_eligibility)
            if detail.planning_eligibility in PLANNING_ELIGIBILITY
            else 0,
            format_func=readable_label,
        )
        pathway_ids = st.text_input(
            "Linked pathways",
            value=", ".join(detail.pathway_ids),
            help="Comma-separated governed pathway IDs.",
        )

        st.markdown("#### Evidence and review")
        evidence_a, evidence_b = st.columns(2)
        evidence_status = evidence_a.text_input(
            "Evidence status", value=_text(detail.evidence_status)
        )
        evidence_source = evidence_b.text_input(
            "Evidence source", value=_text(detail.evidence_source)
        )
        rationale = st.text_area(
            "Reason for this mapping", value=_text(detail.rationale)
        )
        limitations = st.text_area("Known limitations", value=_text(detail.limitations))
        review_a, review_b = st.columns(2)
        approval_status = review_a.selectbox(
            "Review status *",
            sorted(APPROVAL_STATUSES),
            index=sorted(APPROVAL_STATUSES).index(detail.approval_status)
            if detail.approval_status in APPROVAL_STATUSES
            else 0,
            format_func=readable_label,
        )
        reviewed_by = review_b.text_input(
            "Reviewed by", value=_text(detail.reviewed_by)
        )
        review_dates_a, review_dates_b = st.columns(2)
        reviewed_at = review_dates_a.text_input(
            "Reviewed on", value=_text(detail.reviewed_at)
        )
        approved_by = review_dates_b.text_input(
            "Approved by", value=_text(detail.approved_by)
        )
        approved_at = st.text_input("Approved on", value=_text(detail.approved_at))

        with st.expander("Technical and provenance", expanded=False):
            source = st.text_input("Source / provenance", value=_text(detail.source))
            governance_notes = st.text_area(
                "Governance notes", value=_text(detail.governance_notes)
            )
            supersedes_activity_id = st.text_input(
                "Supersedes activity ID", value=_text(detail.supersedes_activity_id)
            )
            st.caption(
                f"Schema version: {detail.schema_version}. "
                f"Change-history entries: {len(detail.change_history)}."
            )

        save_activity = st.form_submit_button(
            "Save required activity governance", type="primary"
        )

    if save_activity:
        try:
            if not activity_id.strip() or not channel.strip() or not source.strip():
                raise ValueError(
                    "Activity ID, reporting channel, and source / provenance are required."
                )
            candidate_values = {
                "activity_id": activity_id.strip(),
                "market": market,
                "channel": channel.strip(),
                "platform": platform.strip(),
                "campaign_type": campaign_type.strip(),
                "product_advertised": product_advertised.strip(),
                "message_type": message_type.strip(),
                "marketing_objective": marketing_objective.strip(),
                "funnel_stage": funnel_stage,
                "model_input_column": model_input_column,
                "activity_ownership": activity_ownership,
                "model_role": model_role,
                "economic_treatment": economic_treatment,
                "planning_eligibility": planning_eligibility,
                "pooling_group_id": pooling_group_id.strip() or None,
                "pathway_ids": tuple(
                    item.strip() for item in pathway_ids.split(",") if item.strip()
                ),
                "evidence_status": evidence_status.strip() or "not_assessed",
                "evidence_source": evidence_source.strip(),
                "rationale": rationale.strip(),
                "limitations": limitations.strip(),
                "approval_status": approval_status,
                "reviewed_by": reviewed_by.strip(),
                "reviewed_at": reviewed_at.strip(),
                "approved_by": approved_by.strip() or None,
                "approved_at": approved_at.strip() or None,
                "source": source.strip(),
                "governance_notes": governance_notes.strip(),
                "supersedes_activity_id": supersedes_activity_id.strip() or None,
            }
            candidate = (
                ActivityDefinition(**candidate_values)
                if is_new_activity
                else replace(cast(ActivityDefinition, detail), **candidate_values)
            )
            updated = list(activity_definitions)
            if is_new_activity:
                updated.append(candidate)
            else:
                updated[selected_index] = candidate
            seen_keys = set()
            seen_inputs = set()
            for item in updated:
                if item.activity_key in seen_keys:
                    raise ValueError(
                        f"duplicate market/activity_id {item.activity_key}"
                    )
                if (item.market, item.resolved_model_input_column) in seen_inputs:
                    raise ValueError(
                        "duplicate market/model input column "
                        f"{(item.market, item.resolved_model_input_column)}"
                    )
                seen_keys.add(item.activity_key)
                seen_inputs.add((item.market, item.resolved_model_input_column))

            previous = [
                ActivityDefinition.from_dict(item) for item in existing_activity_items
            ]
            previous_by_key = {item.activity_key: item for item in previous}
            refit_required = set(previous_by_key) != {
                item.activity_key for item in updated
            }
            rebuild_curves = refit_required
            rebuild_scenarios = refit_required
            for definition in updated:
                prior = previous_by_key.get(definition.activity_key)
                if prior is None:
                    continue
                impact = activity_invalidation(prior, definition)
                refit_required = refit_required or impact.refit_model
                rebuild_curves = (
                    rebuild_curves or impact.rebuild_curves or impact.rebuild_economics
                )
                rebuild_scenarios = rebuild_scenarios or impact.rebuild_scenarios
            set_state("activity_definitions", [item.to_dict() for item in updated])
            activity_definitions = updated
            if refit_required and get_state("model_trained"):
                clear_model_state()
                set_state("scenarios", [])
                st.warning(
                    "Saved. The activity role or media-input mapping changed, so "
                    "the fitted model, approval, curves, and scenarios were invalidated."
                )
            else:
                if rebuild_curves:
                    set_state("curve_bank_entry_id", None)
                if rebuild_scenarios:
                    set_state("scenarios", [])
                if rebuild_curves or rebuild_scenarios:
                    st.warning(
                        "Saved. A downstream governance field changed, so stale "
                        "curve/economics references and affected scenarios were "
                        "invalidated according to the activity change matrix."
                    )
                else:
                    st.success("Required activity governance saved.")
            st.session_state["activity_detail_mode"] = "edit"
        except (TypeError, ValueError) as exc:
            st.error(f"Nothing was saved. Resolve this activity first: {exc}")

st.markdown("---")
_search_section = SectionCard(
    "Search object governance",
    description=(
        "Branded-search demand, Paid Search spend/delivery/cap, organic-search and "
        "direct-navigation capture - distinct governed objects, never inferred by name."
    ),
)
_search_section.__enter__()
render_definition_help(
    "a Search cap",
    "A budget, delivery, or operational limit on Paid Search. It is a constraint, not a promise that the same amount will be spent or delivered.",
)
st.caption(
    "Branded-search demand, Paid Search spend/delivery/cap, organic-search "
    "capture, and direct-navigation capture are separate governed objects - "
    "never inferred by name-matching a column. A source column already assigned "
    "one Search role cannot also be registered under another role. A Paid Search "
    "cap must be linked to the matching Paid Search spend or delivery object in "
    "the same market; a cap without a matching object is rejected."
)
existing_search_object_items = saved_search_object_items
if existing_search_object_items:
    search_object_rows = [
        SearchObjectDefinition.from_dict(item).to_dict()
        for item in existing_search_object_items
    ]
else:
    search_object_rows = []

search_object_columns = [
    "market",
    "search_object_id",
    "search_role",
    "channel",
    "source_column",
    "unit",
    "currency",
    "product",
    "state",
    "planning_eligibility",
    "model_input_column",
    "source",
    "effective_period_start",
    "effective_period_end",
    "approval_status",
    "approved_by",
    "approved_at",
    "search_object_version",
]
_search_enum_values = {
    "search_role": SEARCH_ROLES,
    "unit": SEARCH_UNITS,
    "state": SEARCH_OBJECT_STATES,
    "planning_eligibility": PLANNING_ELIGIBILITY,
    "approval_status": APPROVAL_STATUSES,
}
_search_object_df = pd.DataFrame(search_object_rows).reindex(
    columns=search_object_columns
)
for _text_col in (
    "search_object_id",
    "channel",
    "source_column",
    "currency",
    "product",
    "model_input_column",
    "source",
    "effective_period_start",
    "effective_period_end",
):
    # An empty (or all-null) reindexed column infers float64, which
    # TextColumn rejects outright - force object dtype so the column
    # renders as editable text even with no rows yet.
    _search_object_df[_text_col] = _search_object_df[_text_col].astype("object")
_search_editor_df = display_enum_frame(_search_object_df, _search_enum_values.keys())
search_object_editor = st.data_editor(
    _search_editor_df,
    num_rows="dynamic",
    width="stretch",
    key="search_object_governance_editor",
    column_config={
        "market": st.column_config.SelectboxColumn(
            "Market", options=mapping_markets, required=True
        ),
        "search_role": st.column_config.SelectboxColumn(
            "Search object",
            options=display_enum_options(SEARCH_ROLES),
            required=True,
        ),
        "search_object_id": st.column_config.TextColumn(
            "Search object ID", required=True
        ),
        "channel": st.column_config.TextColumn("Channel"),
        "source_column": st.column_config.TextColumn("Source column", required=True),
        "unit": st.column_config.SelectboxColumn(
            "Measurement unit",
            options=display_enum_options(SEARCH_UNITS),
            required=True,
        ),
        "currency": st.column_config.TextColumn("Currency"),
        "product": st.column_config.TextColumn("Product"),
        "state": st.column_config.SelectboxColumn(
            "Data status",
            options=display_enum_options(SEARCH_OBJECT_STATES),
            required=True,
        ),
        "planning_eligibility": st.column_config.SelectboxColumn(
            "Planning eligibility",
            options=display_enum_options(PLANNING_ELIGIBILITY),
            required=True,
        ),
        "model_input_column": st.column_config.TextColumn("Model input column"),
        "source": st.column_config.TextColumn("Source / provenance"),
        "approval_status": st.column_config.SelectboxColumn(
            "Review status",
            options=display_enum_options(APPROVAL_STATUSES),
            required=True,
        ),
        "effective_period_start": st.column_config.TextColumn(
            "Effective from (YYYY-MM-DD)"
        ),
        "effective_period_end": st.column_config.TextColumn(
            "Effective to (YYYY-MM-DD)"
        ),
        "search_object_version": st.column_config.NumberColumn(
            "Version", disabled=True, help="System-managed - see Save behaviour below."
        ),
    },
)
search_object_editor = restore_enum_frame(
    search_object_editor,
    _search_enum_values.keys(),
    _search_enum_values,
)
st.caption(
    "Editing an already-saved row does not overwrite it in place - Save creates "
    "a new, higher-numbered version of that row's "
    "(market, search_object_id) lineage, resets its Approval to draft, and "
    "keeps the version it replaced in the version history below. A brand "
    "new row (a search_object_id not already saved) starts at version 1."
)

existing_search_objects_by_key = {
    (str(item.get("market", "*")), str(item.get("search_object_id", ""))): item
    for item in existing_search_object_items
}

search_object_definitions = []
search_object_versions_to_record = []
search_object_errors = []
for row_number, row in search_object_editor.fillna("").iterrows():
    if not str(row["search_object_id"]):
        continue
    try:
        editable_fields = dict(
            search_role=str(row["search_role"]),
            source_column=str(row["source_column"]),
            unit=str(row["unit"]),
            channel=str(row["channel"]),
            product=str(row["product"]),
            currency=str(row["currency"]),
            state=str(row["state"] or "observed"),
            planning_eligibility=str(row["planning_eligibility"] or "excluded"),
            model_input_column=str(row["model_input_column"]),
            source=str(row["source"] or "channel & media units UI"),
            approval_status=str(row["approval_status"] or "draft"),
            approved_by=str(row["approved_by"]) or None,
            approved_at=str(row["approved_at"]) or None,
            effective_period_start=str(row["effective_period_start"]) or None,
            effective_period_end=str(row["effective_period_end"]) or None,
        )
        market = str(row["market"] or "*")
        search_object_id = str(row["search_object_id"])
        prior_dict = existing_search_objects_by_key.get((market, search_object_id))
        if prior_dict is not None:
            prior = SearchObjectDefinition.from_dict(prior_dict)
            unversioned_edit = replace(prior, **editable_fields)
            if unversioned_edit.to_dict() == prior.to_dict():
                candidate = prior
            else:
                candidate = new_search_object_version(prior, **editable_fields)
                search_object_versions_to_record.append(candidate)
        else:
            candidate = SearchObjectDefinition(
                search_object_id=search_object_id, market=market, **editable_fields
            )
            search_object_versions_to_record.append(candidate)
        search_object_definitions.append(candidate)
    except ValueError as exc:
        search_object_errors.append(f"Row {row_number + 1}: {exc}")

for issue in validate_search_object_catalogue(search_object_definitions):
    search_object_errors.append(
        f"{issue.search_object_id} (market {issue.market}): {issue.detail}"
    )

for search_error in search_object_errors:
    st.error(search_error)

if st.button("Save Search object governance"):
    if search_object_errors:
        st.error("Nothing was saved. Resolve every Search object error first.")
    else:
        set_state(
            "search_objects",
            [definition.to_dict() for definition in search_object_definitions],
        )
        if search_object_versions_to_record:
            set_state(
                "search_object_versions",
                (get_state("search_object_versions") or [])
                + [defn.to_dict() for defn in search_object_versions_to_record],
            )
        st.success("Search object governance saved.")

with st.expander("Search object version history"):
    _search_object_version_history = get_state("search_object_versions") or []
    if not _search_object_version_history:
        st.caption("No saved Search object versions yet.")
    for _version in sorted(
        _search_object_version_history,
        key=lambda item: (
            str(item.get("market", "")),
            str(item.get("search_object_id", "")),
            int(item.get("search_object_version", 1)),
        ),
    ):
        st.text(
            f"{_version.get('market')} / {_version.get('search_object_id')} - "
            f"v{_version.get('search_object_version')} - "
            f"{_version.get('approval_status')}"
        )
_search_section.__exit__(None, None, None)

st.markdown("---")
_media_unit_section = SectionCard(
    "Physical delivery & cost mapping",
    description=(
        "Physical delivery (impressions, GRPs, clicks) and cost basis/currency, kept separate "
        "from monetary spend and from the fitted model-input column above. Response-only "
        "activity does not need an artificial cost."
    ),
)
_media_unit_section.__enter__()

unit_markets = sorted(
    {
        definition.market
        for definition in activity_definitions
        if definition.market != "*"
    }
    or set(mapping_markets)
)
unit_channels = sorted({definition.channel for definition in activity_definitions})
if not unit_channels:
    st.info(
        "Save at least one governed activity before configuring optional "
        "physical delivery and cost mappings."
    )

for market in unit_markets:
    with st.expander(f"Market: {market}", expanded=len(unit_markets) == 1):
        for channel in unit_channels:
            existing = market_config.get_media_unit_config(market, channel)
            st.markdown(f"**{readable_label(channel)}**")
            c1, c2, c3 = st.columns(3)
            response_col = c1.selectbox(
                "Response-unit column",
                ["(none)"] + numeric_cols,
                index=(["(none)"] + numeric_cols).index(existing.response_unit_column)
                if existing and existing.response_unit_column in numeric_cols
                else 0,
                format_func=lambda c: c if c == "(none)" else readable_label(c),
                key=f"unit_col_{market}_{channel}",
                help="The column that measures physical delivery for this channel, e.g. impressions or GRPs.",
            )
            unit_type = c2.selectbox(
                "Unit type",
                ["(none)"] + UNIT_TYPE_SUGGESTIONS,
                index=(["(none)"] + UNIT_TYPE_SUGGESTIONS).index(existing.unit_type)
                if existing and existing.unit_type in UNIT_TYPE_SUGGESTIONS
                else 0,
                key=f"unit_type_{market}_{channel}",
            )
            cost_basis = c3.selectbox(
                "Cost basis",
                ["(none)"] + COST_BASIS_SUGGESTIONS,
                index=(["(none)"] + COST_BASIS_SUGGESTIONS).index(existing.cost_basis)
                if existing and existing.cost_basis in COST_BASIS_SUGGESTIONS
                else 0,
                key=f"cost_basis_{market}_{channel}",
            )
            currency = st.text_input(
                "Currency (ISO code, e.g. GBP)",
                value=(existing.currency if existing else "") or "",
                key=f"currency_{market}_{channel}",
            )

            market_config.set_media_unit_config(
                ChannelMediaUnitConfig(
                    market=market,
                    channel=channel,
                    spend_column=channel,
                    response_unit_column=None
                    if response_col == "(none)"
                    else response_col,
                    unit_type=None if unit_type == "(none)" else unit_type,
                    cost_basis=None if cost_basis == "(none)" else cost_basis,
                    currency=currency or None,
                )
            )
            st.markdown("---")

if st.button("Save optional media-unit mapping"):
    set_state("market_spec_config", market_config.to_dict())
    mapped = sum(
        1
        for config in market_config.channel_media_units.values()
        if config.has_media_unit()
    )
    st.success(
        f"Saved. {mapped} of "
        f"{len(unit_markets) * len(unit_channels)} channel/market "
        "combinations have a media-unit mapping."
    )
_media_unit_section.__exit__(None, None, None)

render_next_step("channel_media_units")
