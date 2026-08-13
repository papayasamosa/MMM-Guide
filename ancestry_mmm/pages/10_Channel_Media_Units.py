"""Map each channel's spend column to a physical
media-unit column, per market - optional data capture for the
market-specific redesign (see docs/media_units_and_inflation.md). Feeds
core.media_units's CPA/response-unit-curve calculations and is part of the
model-specification fingerprint once mapped (core.fingerprint).
"""

import sys
from dataclasses import replace
from pathlib import Path

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
    render_glossary,
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
    MODEL_ROLES,
    OWNERSHIP,
    PLANNING_ELIGIBILITY,
    ActivityDefinition,
    activity_invalidation,
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
    page_title="Media Mapping | Ancestry Family History & DNA MMM",
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
if not spec_dict or df is None:
    st.markdown("---")
    render_empty_state(
        "No model structure defined yet. Complete Model Structure first.",
        button_label="Go to Model Structure",
        target_key="structure",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
render_glossary(["Response curve"])
st.caption(
    "Keep fitted inputs, Search demand/delivery/caps, and physical delivery or cost mappings "
    "separate. These fields answer different causal, reporting, and planning questions."
)

hints = detect_column_types(df)
numeric_cols = hints["numeric"]

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)
existing_activity_items = get_state("activity_definitions") or []
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
    summary_cols[0].metric("Markets", len(spec.markets))
    summary_cols[1].metric("Model-input channels", len(spec.channels))
    summary_cols[2].metric("Saved Search objects", len(saved_search_object_items))
    summary_cols[3].metric("Physical mappings", saved_media_unit_count)

_activity_section = SectionCard(
    "Activity and causal-role mapping",
    description=(
        "The fitted model-input column, ownership, causal role, economic treatment, and planning eligibility for each activity."
    ),
)
_activity_section.__enter__()
st.caption(
    "Use one row per market and activity. Add rows to distinguish paid and "
    "organic social, promotional/lifecycle/transactional CRM, PR campaigns, "
    "and named external events even when they share a reporting channel."
)
if existing_activity_items:
    activity_rows = [
        ActivityDefinition.from_dict(item).to_dict() for item in existing_activity_items
    ]
else:
    activity_rows = [
        ActivityDefinition(
            activity_id=f"{market}:{channel}",
            market=market,
            channel=channel,
            platform="",
            campaign_type="",
            product_advertised="",
            message_type="",
            model_input_column=channel,
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="activity governance UI",
        ).to_dict()
        for market in spec.markets
        for channel in spec.channels
    ]

activity_columns = [
    "market",
    "activity_id",
    "channel",
    "platform",
    "campaign_type",
    "product_advertised",
    "message_type",
    "model_input_column",
    "activity_ownership",
    "model_role",
    "economic_treatment",
    "planning_eligibility",
    "pathway_ids",
    "evidence_status",
    "evidence_source",
    "rationale",
    "limitations",
    "approval_status",
    "reviewed_by",
    "reviewed_at",
    "approved_by",
    "approved_at",
    "source",
]
_activity_enum_values = {
    "activity_ownership": OWNERSHIP,
    "model_role": MODEL_ROLES,
    "economic_treatment": ECONOMIC_TREATMENTS,
    "planning_eligibility": PLANNING_ELIGIBILITY,
    "approval_status": APPROVAL_STATUSES,
}
_activity_editor_df = display_enum_frame(
    pd.DataFrame(activity_rows).reindex(columns=activity_columns),
    _activity_enum_values.keys(),
)
_activity_editor_df["pathway_ids"] = _activity_editor_df["pathway_ids"].map(
    lambda value: (
        ", ".join(value) if isinstance(value, (list, tuple, set)) else str(value or "")
    )
)
activity_editor = st.data_editor(
    _activity_editor_df,
    num_rows="dynamic",
    width="stretch",
    key="activity_governance_editor",
    column_config={
        "market": st.column_config.SelectboxColumn(
            "Market", options=spec.markets, required=True
        ),
        "activity_id": st.column_config.TextColumn(
            "Activity ID",
            required=True,
            help="Stable identity for this activity in this market.",
        ),
        "channel": st.column_config.TextColumn(
            "Reporting channel",
            required=True,
            help=(
                "Shared reporting label, such as Social. Multiple activities "
                "may share it when their model-input columns differ."
            ),
        ),
        "platform": st.column_config.TextColumn("Platform"),
        "campaign_type": st.column_config.TextColumn("Campaign type"),
        "product_advertised": st.column_config.TextColumn("Product advertised"),
        "message_type": st.column_config.TextColumn("Message type"),
        "model_input_column": st.column_config.SelectboxColumn(
            "Media input column",
            options=spec.channels,
            required=True,
            help="The observed column used by the fitted model; it is not assumed to be monetary spend.",
        ),
        "activity_ownership": st.column_config.SelectboxColumn(
            "Activity ownership",
            options=display_enum_options(sorted(OWNERSHIP)),
            required=True,
        ),
        "model_role": st.column_config.SelectboxColumn(
            "Model role",
            options=display_enum_options(sorted(MODEL_ROLES)),
            required=True,
        ),
        "economic_treatment": st.column_config.SelectboxColumn(
            "Cost treatment",
            options=display_enum_options(sorted(ECONOMIC_TREATMENTS)),
            required=True,
        ),
        "planning_eligibility": st.column_config.SelectboxColumn(
            "Planning eligibility",
            options=display_enum_options(sorted(PLANNING_ELIGIBILITY)),
            required=True,
        ),
        "pathway_ids": st.column_config.TextColumn(
            "Pathway IDs",
            help="Comma-separated pathway records linked to this activity.",
        ),
        "evidence_status": st.column_config.TextColumn("Evidence status"),
        "evidence_source": st.column_config.TextColumn("Evidence source"),
        "rationale": st.column_config.TextColumn("Reason for this mapping"),
        "limitations": st.column_config.TextColumn("Known limitations"),
        "approval_status": st.column_config.SelectboxColumn(
            "Review status",
            options=display_enum_options(sorted(APPROVAL_STATUSES)),
            required=True,
        ),
        "reviewed_by": st.column_config.TextColumn("Reviewed by"),
        "reviewed_at": st.column_config.TextColumn("Reviewed on"),
        "approved_by": st.column_config.TextColumn("Approved by"),
        "approved_at": st.column_config.TextColumn("Approved on"),
        "source": st.column_config.TextColumn("Source / provenance"),
    },
)
activity_editor = restore_enum_frame(
    activity_editor,
    _activity_enum_values.keys(),
    _activity_enum_values,
)

# REQ-DATAIN-001 review finding: pooling_group_id is not an editable
# column in this grid (activity_columns above), so reconstructing every
# row's ActivityDefinition without carrying it forward would silently wipe
# a previously-set cross-market identity on *any* unrelated edit through
# this page. Look it up by (market, activity_id) - the same key already
# used for duplicate detection below - from the pre-edit roster.
_existing_pooling_group_ids = {
    (str(item.get("market", "*")), str(item.get("activity_id", ""))): item.get(
        "pooling_group_id"
    )
    for item in existing_activity_items
}

activity_definitions = []
activity_errors = []
seen_keys = set()
seen_inputs = set()
for row_number, row in activity_editor.fillna("").iterrows():
    try:
        activity_key = (str(row["market"]), str(row["activity_id"]))
        input_key = (str(row["market"]), str(row["model_input_column"]))
        if activity_key in seen_keys:
            raise ValueError(f"duplicate market/activity_id {activity_key}")
        if input_key in seen_inputs:
            raise ValueError(f"duplicate market/model_input_column {input_key}")
        seen_keys.add(activity_key)
        seen_inputs.add(input_key)
        activity_definitions.append(
            ActivityDefinition(
                activity_id=str(row["activity_id"]),
                market=str(row["market"]),
                channel=str(row["channel"]),
                platform=str(row["platform"]),
                campaign_type=str(row["campaign_type"]),
                product_advertised=str(row["product_advertised"]),
                message_type=str(row["message_type"]),
                model_input_column=str(row["model_input_column"]),
                activity_ownership=str(row["activity_ownership"]),
                model_role=str(row["model_role"]),
                economic_treatment=str(row["economic_treatment"]),
                planning_eligibility=str(row["planning_eligibility"]),
                pooling_group_id=_existing_pooling_group_ids.get(activity_key),
                pathway_ids=tuple(
                    item.strip()
                    for item in str(row["pathway_ids"]).split(",")
                    if item.strip()
                ),
                evidence_status=str(row["evidence_status"] or "not_assessed"),
                evidence_source=str(row["evidence_source"]),
                rationale=str(row["rationale"]),
                limitations=str(row["limitations"]),
                approval_status=str(row["approval_status"] or "draft"),
                reviewed_by=str(row["reviewed_by"]),
                reviewed_at=str(row["reviewed_at"]),
                approved_by=str(row["approved_by"]) or None,
                approved_at=str(row["approved_at"]) or None,
                source=str(row["source"] or "activity governance UI"),
            )
        )
    except ValueError as error:
        activity_errors.append(f"Row {row_number + 1}: {error}")

for error in activity_errors:
    st.error(error)

if st.button("Save required activity governance", type="primary"):
    if activity_errors:
        st.error("Nothing was saved. Resolve every governance error first.")
    else:
        previous = [
            ActivityDefinition.from_dict(item) for item in existing_activity_items
        ]
        previous_by_key = {item.activity_key: item for item in previous}
        refit_required = set(previous_by_key) != {
            item.activity_key for item in activity_definitions
        }
        rebuild_curves = refit_required
        rebuild_scenarios = refit_required
        for definition in activity_definitions:
            prior = previous_by_key.get(definition.activity_key)
            if prior is None:
                continue
            impact = activity_invalidation(prior, definition)
            refit_required = refit_required or impact.refit_model
            rebuild_curves = (
                rebuild_curves or impact.rebuild_curves or impact.rebuild_economics
            )
            rebuild_scenarios = rebuild_scenarios or impact.rebuild_scenarios
        set_state(
            "activity_definitions",
            [definition.to_dict() for definition in activity_definitions],
        )
        if refit_required and get_state("model_trained"):
            clear_model_state()
            set_state("scenarios", [])
            st.warning(
                "Saved. The activity role or model-input mapping changed, so "
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
_activity_section.__exit__(None, None, None)

st.markdown("---")
_search_section = SectionCard(
    "Search object governance",
    description=(
        "Branded-search demand, Paid Search spend/delivery/cap, organic-search and "
        "direct-navigation capture - distinct governed objects, never inferred by name."
    ),
)
_search_section.__enter__()
st.caption(
    "Branded-search demand, Paid Search spend/delivery/cap, organic-search "
    "capture, and direct-navigation capture are separate governed objects "
    "distinct objects here - never inferred by name-matching a column. A "
    "raw column already governed under one Search role cannot also be "
    "registered under a different one. A paid_search_cap row's Channel must "
    "exactly match the Channel of the paid_search_spend/paid_search_delivery "
    "row it constrains, in the same market - a cap with no matching channel "
    "counterpart is rejected."
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
            "Market", options=spec.markets, required=True
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
    except ValueError as error:
        search_object_errors.append(f"Row {row_number + 1}: {error}")

for issue in validate_search_object_catalogue(search_object_definitions):
    search_object_errors.append(
        f"{issue.search_object_id} (market {issue.market}): {issue.detail}"
    )

for error in search_object_errors:
    st.error(error)

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

for market in spec.markets:
    with st.expander(f"Market: {market}", expanded=len(spec.markets) == 1):
        for channel in spec.channels:
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
        f"{len(spec.markets) * len(spec.channels)} channel/market "
        "combinations have a media-unit mapping."
    )
_media_unit_section.__exit__(None, None, None)

render_next_step("channel_media_units")
