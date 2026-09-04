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
from ancestry_mmm.core.search_intent_taxonomy import (
    APPROVED_MINIMUM_SEARCH_INTENT_GROUPS,
    BRAND_CLASS_GENERIC_NON_BRAND,
    SEARCH_INTENT_GROUP_ID_BRAND,
    SEARCH_INTENT_GROUP_ID_NON_BRAND,
    SearchIntentGroup,
    SEARCH_PLATFORMS,
    governed_search_intent_groups,
    resolve_search_intent_model_grain,
    validate_activity_search_taxonomy,
    validate_search_intent_group_catalogue,
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

try:
    _custom_search_groups = [
        SearchIntentGroup.from_dict(item)
        for item in (get_state("search_intent_groups") or [])
        if isinstance(item, dict)
        and str(item.get("search_intent_group_id", ""))
        not in {SEARCH_INTENT_GROUP_ID_BRAND, SEARCH_INTENT_GROUP_ID_NON_BRAND}
    ]
    search_intent_groups = governed_search_intent_groups(_custom_search_groups)
except (TypeError, ValueError) as exc:
    search_intent_groups = APPROVED_MINIMUM_SEARCH_INTENT_GROUPS
    st.error(f"Stored Search intent taxonomy is invalid and cannot be used: {exc}")
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

# Codex review (PR #348, P2): the save handlers below persist a notice here
# instead of calling st.warning()/st.success() directly, because they then
# call st.rerun() (UX-009) so the "Mapping summary" above reflects the just-
# saved state in the same view - but a message rendered immediately before
# st.rerun() is discarded by that rerun before the analyst can ever see it.
# This is most important for the invalidation warning ("the fitted model,
# approval, curves, and scenarios were invalidated"), which is actionable
# governance information, not a transient confirmation - losing it silently
# would leave the analyst unaware their save just cleared a trained model.
# Shown once, on the render immediately following the save, then cleared so
# a later unrelated rerun does not keep re-showing a stale notice.
_pending_activity_notice = get_state("activity_mapping_notice")
if _pending_activity_notice:
    getattr(st, _pending_activity_notice["kind"])(_pending_activity_notice["message"])
    set_state("activity_mapping_notice", None)

with st.container(border=True):
    st.markdown("#### Mapping stages")
    _mapping_stage_columns = st.columns(3)
    for _stage_column, _stage_label in zip(
        _mapping_stage_columns,
        ("1. Activities", "2. Search setup", "3. Delivery & cost"),
    ):
        _stage_column.markdown(f"**{_stage_label}**")
    st.caption(
        "Start with the governed activity, then register Search objects and delivery or cost mappings only where the source supports them."
    )
render_technical_details(
    details={
        "Persisted values": "Editor labels are display-only. Raw activity roles, Search roles, units, approval states, and planning states are restored before validation and saving.",
        "Search identity": "Search object IDs are versioned by market and lineage; editing a saved row creates a new version and keeps the prior version in history.",
        "Provenance": "Source, effective dates, approval fields, and cost-mapping assumptions remain part of the governed mapping record.",
    }
)

with st.expander("Governed deeper Non-Brand intent groups", expanded=False):
    st.caption(
        "Brand and Non-Brand are the approved minimum. Add a deeper Non-Brand "
        "child only when the source supports that exact group; the child starts "
        "as draft and inherits no reporting, economics, planning, or optimisation "
        "eligibility. Parent and child are never fitted flat together."
    )
    child_id = st.text_input("Child group ID", key="new_search_child_id")
    child_name = st.text_input("Child group name", key="new_search_child_name")
    child_description = st.text_area(
        "Business description", key="new_search_child_description"
    )
    if st.button("Save Non-Brand child as draft", key="save_search_child"):
        try:
            if not child_id.strip() or not child_name.strip():
                raise ValueError("Child group ID and name are required.")
            if child_id.strip() in {
                group.search_intent_group_id for group in search_intent_groups
            }:
                raise ValueError("That Search intent group ID already exists.")
            child = SearchIntentGroup(
                search_intent_group_id=child_id.strip(),
                search_intent_group_name=child_name.strip(),
                brand_class=BRAND_CLASS_GENERIC_NON_BRAND,
                parent_search_intent_group_id=SEARCH_INTENT_GROUP_ID_NON_BRAND,
                business_description=child_description.strip(),
                product_scope="Family History / DNA as explicitly observed",
                owner="",
                approval_status="draft",
            )
            candidate_groups = _custom_search_groups + [child]
            issues = validate_search_intent_group_catalogue(
                tuple(APPROVED_MINIMUM_SEARCH_INTENT_GROUPS) + tuple(candidate_groups)
            )
            if issues:
                raise ValueError("; ".join(issues))
            set_state(
                "search_intent_groups", [item.to_dict() for item in candidate_groups]
            )
            existing_versions = {
                (
                    str(item.get("search_intent_group_id")),
                    int(item.get("search_intent_group_version", 1)),
                ): item
                for item in (get_state("search_intent_group_versions") or [])
                if isinstance(item, dict)
            }
            for item in candidate_groups:
                existing_versions[item.version_key] = item.to_dict()
            set_state(
                "search_intent_group_versions",
                list(existing_versions.values()),
            )
            st.success("Saved the deeper Non-Brand group as a governed draft.")
            st.rerun()
        except ValueError as exc:
            st.error(f"Could not save Search intent group: {exc}")

_model_grain_options = [group.search_intent_group_id for group in search_intent_groups]
_saved_model_grain = tuple(get_state("search_intent_model_grain") or ())
_model_grain_default = [
    group_id for group_id in _saved_model_grain if group_id in _model_grain_options
]
if not _model_grain_default:
    _model_grain_default = ["brand_search", "non_brand_search"]
_selected_model_grain = st.multiselect(
    "Explicit Search model/reporting grain",
    options=_model_grain_options,
    default=_model_grain_default,
    key="search_intent_model_grain_input",
    help="Select parent Brand/Non-Brand or an explicitly governed deeper child. Parent and child cannot be fitted together.",
)
try:
    _resolved_model_grain = resolve_search_intent_model_grain(
        _selected_model_grain,
        search_intent_groups,
    )
except ValueError as exc:
    st.error(f"Search model grain is invalid: {exc}")
else:
    set_state("search_intent_model_grain", list(_resolved_model_grain))
    st.caption(
        "The selected grain is explicit and persisted. Deeper-child economics, "
        "planning, and optimisation remain unavailable until that child has its "
        "own observed and governed cost support; parent totals are not duplicated."
    )

if _custom_search_groups:
    st.caption(
        "Project Search intent groups: "
        + ", ".join(
            f"{item.search_intent_group_id} ({item.approval_status})"
            for item in _custom_search_groups
        )
    )

st.markdown("### 1. Activities")
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
            "Search intent": item.search_intent_group_id or "Not classified",
            "Search platform": item.search_platform or "Not classified",
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
            search_intent_group_id=None,
            search_platform="",
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
        search_a, search_b = st.columns(2)
        search_group_options = [""] + [
            group.search_intent_group_id for group in search_intent_groups
        ]
        search_intent_group_id = search_a.selectbox(
            "Search intent group",
            search_group_options,
            index=(
                search_group_options.index(detail.search_intent_group_id)
                if detail.search_intent_group_id in search_group_options
                else 0
            ),
            format_func=lambda value: (
                "Not classified"
                if not value
                else next(
                    (
                        group.search_intent_group_name
                        for group in search_intent_groups
                        if group.search_intent_group_id == value
                    ),
                    value,
                )
            ),
            help="Optional governed Brand or Non-Brand intent. Leave blank when the activity is not a Search activity or the source cannot support classification.",
        )
        search_platform_options = [""] + list(SEARCH_PLATFORMS)
        search_platform = search_b.selectbox(
            "Search platform",
            search_platform_options,
            index=(
                search_platform_options.index(detail.search_platform)
                if detail.search_platform in search_platform_options
                else 0
            ),
            format_func=lambda value: value.title() if value else "Not classified",
            help="Separate platform axis for Search reporting; it does not replace the intent group and does not classify PMax, Demand Gen, or YouTube as Paid Search.",
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

        save_activity = st.form_submit_button("Save activity mapping", type="primary")

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
                "search_intent_group_id": search_intent_group_id or None,
                "search_platform": search_platform,
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
            search_taxonomy_errors = validate_activity_search_taxonomy(
                updated, search_intent_groups
            )
            if search_taxonomy_errors:
                raise ValueError("; ".join(search_taxonomy_errors))

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
                set_state(
                    "activity_mapping_notice",
                    {
                        "kind": "warning",
                        "message": (
                            "Saved. The activity role or media-input mapping changed, "
                            "so the fitted model, approval, curves, and scenarios "
                            "were invalidated."
                        ),
                    },
                )
            else:
                if rebuild_curves:
                    set_state("curve_bank_entry_id", None)
                if rebuild_scenarios:
                    set_state("scenarios", [])
                if rebuild_curves or rebuild_scenarios:
                    _cleared_outputs = []
                    if rebuild_curves:
                        _cleared_outputs.append("affected curve/economics references")
                    if rebuild_scenarios:
                        _cleared_outputs.append("affected scenarios")
                    set_state(
                        "activity_mapping_notice",
                        {
                            "kind": "warning",
                            "message": (
                                "Activity mapping saved. "
                                + " and ".join(_cleared_outputs).capitalize()
                                + " were cleared because this change affects "
                                "downstream results."
                            ),
                        },
                    )
                else:
                    set_state(
                        "activity_mapping_notice",
                        {"kind": "success", "message": "Activity mapping saved."},
                    )
            st.session_state["activity_detail_mode"] = "edit"
            # Overnight UI/UX pass (2026-08-29, UX-009): "Mapping summary"
            # above (Governed activities/Saved Search objects/Physical
            # mappings counts) is computed earlier in this same script run,
            # before this form's handler - live-reproduced showing "0" here
            # immediately after a successful save while sections lower on
            # the page (rendered after this handler) already reflected the
            # new activity. Same rerun-after-state-change fix as UX-003/
            # UX-004; safe here since save_activity is a one-shot
            # st.form_submit_button flag. The notice set above (rather than
            # an st.warning()/st.success() called here) is what survives
            # this rerun - see its definition near "Mapping summary".
            st.rerun()
        except (TypeError, ValueError) as exc:
            st.error(f"Nothing was saved. Resolve this activity first: {exc}")

st.markdown("---")
st.markdown("### 2. Search setup")
_search_section = SectionCard(
    "Search setup",
    description=(
        "Branded-search demand, Paid Search spend/delivery/cap, organic-search and "
        "direct-navigation capture - distinct governed objects, never inferred by name."
    ),
)
_search_section.__enter__()
st.markdown("#### Search object governance")
render_definition_help(
    "a Search cap",
    "A budget, delivery, or operational limit on Paid Search. It is a constraint, not a promise that the same amount will be spent or delivered.",
)
st.caption(
    "Keep demand, spend, delivery, caps, organic search, and direct navigation as "
    "separate Search objects. A cap is a constraint, not realised spend, and every "
    "cap must match its market's Paid Search spend or delivery object."
)
existing_search_object_items = saved_search_object_items
if existing_search_object_items:
    search_object_rows = [
        SearchObjectDefinition.from_dict(item).to_dict()
        for item in existing_search_object_items
    ]
else:
    search_object_rows = []


def _search_overview_label(row: dict) -> str:
    """Return a routine Search label without exposing the technical ID."""
    role = readable_label(str(row.get("search_role") or ""))
    channel = readable_label(str(row.get("channel") or ""))
    return role or channel or "Unnamed Search object"


_search_overview_rows = [
    {
        "Search object": _search_overview_label(row),
        "Market": str(row.get("market") or "All markets"),
        "Source field": readable_label(str(row.get("source_column") or ""))
        or "Not set",
        "Measurement": readable_label(str(row.get("unit") or "")) or "Not set",
        "Planning use": readable_label(
            str(row.get("planning_eligibility") or "excluded")
        ),
        "Review status": readable_label(str(row.get("approval_status") or "draft")),
    }
    for row in search_object_rows
]
_saved_search_definitions = [
    SearchObjectDefinition.from_dict(item) for item in search_object_rows
]
_saved_search_errors = [
    f"{issue.search_object_id} (market {issue.market}): {issue.detail}"
    for issue in validate_search_object_catalogue(_saved_search_definitions)
]
for search_error in _saved_search_errors:
    st.error(search_error)
st.markdown("#### Search object overview")
if _search_overview_rows:
    st.caption(
        "Compare the governed Search roles at a glance. Stable references and the complete field set remain in the detailed editor."
    )
    st.dataframe(pd.DataFrame(_search_overview_rows), width="stretch", hide_index=True)
else:
    st.info(
        "No Search objects are registered yet. Add the first demand, spend, delivery, cap, organic, or direct-navigation object in the detailed setup below."
    )

if "search_detail_mode" not in st.session_state:
    st.session_state["search_detail_mode"] = "edit" if search_object_rows else "add"

selected_search_index = 0
if search_object_rows:
    selected_search_index = st.selectbox(
        "Selected Search object",
        list(range(len(search_object_rows))),
        index=min(
            int(st.session_state.get("search_selected_index", 0)),
            len(search_object_rows) - 1,
        ),
        format_func=lambda index: (
            f"{search_object_rows[index].get('market') or 'All markets'} · "
            f"{_search_overview_label(search_object_rows[index])}"
        ),
        key="search_selected_index",
    )
    selected_search_index = int(selected_search_index)
    if st.button("Add Search object", key="add_search_object"):
        st.session_state["search_detail_mode"] = "add"
        st.rerun()
else:
    st.button("Add Search object", key="add_search_object", type="primary")

if st.session_state.get("search_detail_mode") == "add" or not search_object_rows:
    detail = SimpleNamespace(
        search_object_id="",
        search_role=SEARCH_ROLES[0],
        source_column="",
        unit=SEARCH_UNITS[0],
        market=mapping_markets[0] if mapping_markets else "*",
        channel="",
        product="",
        currency="",
        grain="market_week",
        state="observed",
        planning_eligibility="excluded",
        model_input_column="",
        source="channel & media units UI",
        evidence_status="not_assessed",
        approval_status="draft",
        approved_by="",
        approved_at="",
        effective_period_start="",
        effective_period_end="",
        search_object_version=1,
    )
    _is_new_search_object = True
else:
    detail = SearchObjectDefinition.from_dict(search_object_rows[selected_search_index])
    _is_new_search_object = False


def _search_text(value: object) -> str:
    return "" if value is None else str(value)


def _search_options(values, current: str) -> list[str]:
    options = list(values)
    if current and current not in options:
        options.insert(0, current)
    return options or [""]


with st.expander(
    "Add Search object" if _is_new_search_object else "Edit Search object details",
    expanded=True,
):
    st.caption(
        "Choose one Search object at a time. The overview compares saved objects; "
        "the detail form keeps identity, measurement, planning, validity, and review fields readable."
    )
    with st.form("search_object_detail_form", clear_on_submit=False):
        st.markdown("#### Identity and role")
        identity_a, identity_b = st.columns(2)
        search_object_id = identity_a.text_input(
            "Search object reference *",
            value=_search_text(detail.search_object_id),
            help="Stable technical identity for this Search object; the overview uses the human role label instead.",
        )
        market = identity_b.selectbox(
            "Market *",
            _search_options([*mapping_markets, "*"], _search_text(detail.market)),
            index=_search_options(
                [*mapping_markets, "*"], _search_text(detail.market)
            ).index(_search_text(detail.market)),
        )
        role_a, role_b = st.columns(2)
        search_role = role_a.selectbox(
            "Search role *",
            SEARCH_ROLES,
            index=SEARCH_ROLES.index(detail.search_role)
            if detail.search_role in SEARCH_ROLES
            else 0,
            format_func=readable_label,
            help="Classify demand, Paid Search spend, delivery, cap, organic capture, or direct navigation explicitly.",
        )
        channel = role_b.text_input(
            "Channel / relationship",
            value=_search_text(detail.channel),
            help="Used to relate a Paid Search cap to its matching spend or delivery object.",
        )
        product = st.text_input("Product", value=_search_text(detail.product))

        st.markdown("#### Measurement and model use")
        measure_a, measure_b = st.columns(2)
        source_column = measure_a.text_input(
            "Source field *",
            value=_search_text(detail.source_column),
            help="Observed source column; it is not inferred from the Search object reference.",
        )
        unit = measure_b.selectbox(
            "Measurement unit *",
            SEARCH_UNITS,
            index=SEARCH_UNITS.index(detail.unit) if detail.unit in SEARCH_UNITS else 0,
            format_func=readable_label,
        )
        model_a, model_b = st.columns(2)
        currency = model_a.text_input(
            "Currency",
            value=_search_text(detail.currency),
            help="Required for monetary Paid Search spend or cap; leave blank for non-monetary units.",
        )
        model_input_column = model_b.text_input(
            "Model input column",
            value=_search_text(detail.model_input_column),
        )
        state_a, state_b = st.columns(2)
        state = state_a.selectbox(
            "Data status",
            SEARCH_OBJECT_STATES,
            index=SEARCH_OBJECT_STATES.index(detail.state)
            if detail.state in SEARCH_OBJECT_STATES
            else 0,
            format_func=readable_label,
        )
        planning_eligibility = state_b.selectbox(
            "Planning eligibility",
            sorted(PLANNING_ELIGIBILITY),
            index=sorted(PLANNING_ELIGIBILITY).index(detail.planning_eligibility)
            if detail.planning_eligibility in PLANNING_ELIGIBILITY
            else 0,
            format_func=readable_label,
        )

        st.markdown("#### Validity period")
        validity_a, validity_b = st.columns(2)
        effective_period_start = validity_a.text_input(
            "Effective from (YYYY-MM-DD)",
            value=_search_text(detail.effective_period_start),
        )
        effective_period_end = validity_b.text_input(
            "Effective to (YYYY-MM-DD)",
            value=_search_text(detail.effective_period_end),
        )

        st.markdown("#### Review")
        review_a, review_b = st.columns(2)
        evidence_status = review_a.text_input(
            "Evidence status", value=_search_text(detail.evidence_status)
        )
        approval_status = review_b.selectbox(
            "Review status",
            sorted(APPROVAL_STATUSES),
            index=sorted(APPROVAL_STATUSES).index(detail.approval_status)
            if detail.approval_status in APPROVAL_STATUSES
            else 0,
            format_func=readable_label,
        )
        approved_a, approved_b = st.columns(2)
        approved_by = approved_a.text_input(
            "Approved by", value=_search_text(detail.approved_by)
        )
        approved_at = approved_b.text_input(
            "Approved on", value=_search_text(detail.approved_at)
        )

        with st.expander("Technical details", expanded=False):
            source = st.text_input(
                "Source / provenance", value=_search_text(detail.source)
            )
            grain = st.text_input("Data grain", value=_search_text(detail.grain))
            st.caption(
                f"Current saved version: {detail.search_object_version}. "
                "Saving a change creates a new version and retains the previous record."
            )

        save_search = st.form_submit_button("Save Search setup", type="primary")

if save_search:
    try:
        editable_fields = dict(
            search_role=search_role,
            source_column=source_column.strip(),
            unit=unit,
            channel=channel.strip(),
            product=product.strip(),
            currency=currency.strip(),
            grain=grain.strip() or "market_week",
            state=state,
            planning_eligibility=planning_eligibility,
            model_input_column=model_input_column.strip(),
            source=source.strip() or "channel & media units UI",
            evidence_status=evidence_status.strip() or "not_assessed",
            approval_status=approval_status,
            approved_by=approved_by.strip() or None,
            approved_at=approved_at.strip() or None,
            effective_period_start=effective_period_start.strip() or None,
            effective_period_end=effective_period_end.strip() or None,
        )
        market = market.strip() or "*"
        search_object_id = search_object_id.strip()
        if not search_object_id:
            raise ValueError("Search object reference is required.")
        if _is_new_search_object:
            candidate = SearchObjectDefinition(
                search_object_id=search_object_id,
                market=market,
                **editable_fields,
            )
            updated = [*search_object_rows, candidate.to_dict()]
            version_to_record = candidate
        else:
            prior = SearchObjectDefinition.from_dict(
                search_object_rows[selected_search_index]
            )
            if market != prior.market or search_object_id != prior.search_object_id:
                raise ValueError(
                    "A saved Search object's reference and market identify its lineage; "
                    "add a new Search object for a different identity."
                )
            unversioned_edit = replace(prior, **editable_fields)
            candidate = (
                prior
                if unversioned_edit.to_dict() == prior.to_dict()
                else new_search_object_version(prior, **editable_fields)
            )
            updated = list(search_object_rows)
            updated[selected_search_index] = candidate.to_dict()
            version_to_record = None if candidate is prior else candidate

        candidate_definitions = [
            SearchObjectDefinition.from_dict(item) for item in updated
        ]
        search_object_errors = [
            f"{issue.search_object_id} (market {issue.market}): {issue.detail}"
            for issue in validate_search_object_catalogue(candidate_definitions)
        ]
        if search_object_errors:
            for search_error in search_object_errors:
                st.error(search_error)
            st.error("Nothing was saved. Resolve every Search object error first.")
        else:
            set_state("search_objects", updated)
            if version_to_record is not None:
                set_state(
                    "search_object_versions",
                    (get_state("search_object_versions") or [])
                    + [version_to_record.to_dict()],
                )
            st.session_state["search_detail_mode"] = "edit"
            if _is_new_search_object:
                st.session_state["search_selected_index"] = len(updated) - 1
            st.success("Search setup saved.")
            # UX-009 (see "Save activity mapping" above): same fix - the
            # "Mapping summary" Saved Search objects count is computed
            # earlier in this run. save_search is a one-shot
            # st.form_submit_button flag, so this is safe.
            st.rerun()
    except (TypeError, ValueError) as exc:
        st.error(f"Nothing was saved. Resolve this Search object first: {exc}")

with st.expander("Technical details · Search version history"):
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
st.markdown("### 3. Delivery & cost")
_media_unit_section = SectionCard(
    "Delivery & cost",
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

for _market in unit_markets:
    for _channel in unit_channels:
        _response_key = f"unit_col_{_market}_{_channel}"
        _unit_type_key = f"unit_type_{_market}_{_channel}"
        _cost_basis_key = f"cost_basis_{_market}_{_channel}"
        _currency_key = f"currency_{_market}_{_channel}"
        if any(
            _key in st.session_state
            for _key in (_response_key, _unit_type_key, _cost_basis_key, _currency_key)
        ):
            market_config.set_media_unit_config(
                ChannelMediaUnitConfig(
                    market=_market,
                    channel=_channel,
                    spend_column=_channel,
                    response_unit_column=(
                        None
                        if st.session_state.get(_response_key) in (None, "(none)")
                        else st.session_state.get(_response_key)
                    ),
                    unit_type=(
                        None
                        if st.session_state.get(_unit_type_key) in (None, "(none)")
                        else st.session_state.get(_unit_type_key)
                    ),
                    cost_basis=(
                        None
                        if st.session_state.get(_cost_basis_key) in (None, "(none)")
                        else st.session_state.get(_cost_basis_key)
                    ),
                    currency=st.session_state.get(_currency_key) or None,
                )
            )

_delivery_overview_rows = []
for _market in unit_markets:
    for _channel in unit_channels:
        _config = market_config.get_media_unit_config(_market, _channel)
        _delivery_overview_rows.append(
            {
                "Market": _market,
                "Reporting channel": readable_label(_channel),
                "Delivery measure": readable_label(
                    _config.response_unit_column if _config else ""
                )
                or "Not mapped",
                "Unit": readable_label(_config.unit_type if _config else "")
                or "Not set",
                "Cost basis": readable_label(_config.cost_basis if _config else "")
                or "Not set",
                "Currency": (_config.currency if _config else None) or "Not set",
                "Mapping status": "Mapped"
                if _config and _config.has_media_unit()
                else "Not mapped",
            }
        )
st.markdown("#### Delivery & cost overview")
if _delivery_overview_rows:
    st.caption(
        "Review delivery and cost coverage by market and reporting channel, then select one mapping below to edit."
    )
    st.dataframe(
        pd.DataFrame(_delivery_overview_rows), width="stretch", hide_index=True
    )

if unit_channels:
    st.markdown("#### Edit selected mapping")
    selected_market = st.selectbox(
        "Selected market", unit_markets, key="media_unit_selected_market"
    )
    selected_channel = st.selectbox(
        "Selected reporting channel",
        unit_channels,
        format_func=readable_label,
        key="media_unit_selected_channel",
    )
    existing = market_config.get_media_unit_config(selected_market, selected_channel)
    st.caption(
        f"Editing {selected_market} · {readable_label(selected_channel)}. These fields describe observed delivery and cost translation; they do not change the fitted model input."
    )
    c1, c2, c3 = st.columns(3)
    response_col = c1.selectbox(
        "Response-unit column",
        ["(none)"] + numeric_cols,
        index=(["(none)"] + numeric_cols).index(existing.response_unit_column)
        if existing and existing.response_unit_column in numeric_cols
        else 0,
        format_func=lambda c: c if c == "(none)" else readable_label(c),
        key=f"unit_col_{selected_market}_{selected_channel}",
        help="The column that measures physical delivery for this channel, e.g. impressions or GRPs.",
    )
    unit_type = c2.selectbox(
        "Unit type",
        ["(none)"] + UNIT_TYPE_SUGGESTIONS,
        index=(["(none)"] + UNIT_TYPE_SUGGESTIONS).index(existing.unit_type)
        if existing and existing.unit_type in UNIT_TYPE_SUGGESTIONS
        else 0,
        key=f"unit_type_{selected_market}_{selected_channel}",
    )
    cost_basis = c3.selectbox(
        "Cost basis",
        ["(none)"] + COST_BASIS_SUGGESTIONS,
        index=(["(none)"] + COST_BASIS_SUGGESTIONS).index(existing.cost_basis)
        if existing and existing.cost_basis in COST_BASIS_SUGGESTIONS
        else 0,
        key=f"cost_basis_{selected_market}_{selected_channel}",
    )
    currency = st.text_input(
        "Currency (ISO code, e.g. GBP)",
        value=(existing.currency if existing else "") or "",
        key=f"currency_{selected_market}_{selected_channel}",
    )

    market_config.set_media_unit_config(
        ChannelMediaUnitConfig(
            market=selected_market,
            channel=selected_channel,
            spend_column=selected_channel,
            response_unit_column=None if response_col == "(none)" else response_col,
            unit_type=None if unit_type == "(none)" else unit_type,
            cost_basis=None if cost_basis == "(none)" else cost_basis,
            currency=currency or None,
        )
    )

if st.button("Save delivery & cost mapping"):
    set_state("market_spec_config", market_config.to_dict())
    mapped = sum(
        1
        for config in market_config.channel_media_units.values()
        if config.has_media_unit()
    )
    st.success(
        f"Saved delivery & cost mapping. {mapped} of "
        f"{len(unit_markets) * len(unit_channels)} channel/market "
        "combinations have a media-unit mapping."
    )
    # UX-009 (see "Save activity mapping" above): same fix - the "Mapping
    # summary" Physical mappings count is computed earlier in this run.
    st.rerun()
_media_unit_section.__exit__(None, None, None)

render_next_step("channel_media_units")
