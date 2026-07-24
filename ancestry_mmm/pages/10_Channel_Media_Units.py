"""Page (step 4 of 12): map each channel's spend column to a physical
media-unit column, per market - optional data capture for the
market-specific redesign (see docs/media_units_and_inflation.md). Feeds
core.media_units's CPA/response-unit-curve calculations and is part of the
model-specification fingerprint once mapped (core.fingerprint).
"""

import sys
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
)
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_glossary
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig, MarketSpecConfig, UNIT_TYPE_SUGGESTIONS, COST_BASIS_SUGGESTIONS,
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
from ancestry_mmm.data import detect_column_types

st.set_page_config(page_title="Channel & Media Units - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("channel_media_units")
render_page_header("channel_media_units")

spec_dict = get_state("model_spec")
df = get_state("transformed_data")
if not spec_dict or df is None:
    st.markdown("---")
    render_empty_state(
        "No structure defined yet. Complete Structure: Segments & Markets first.",
        button_label="Go to Structure: Segments & Markets", target_key="structure",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
render_glossary(["Response curve"])

st.markdown("---")
st.info(
    "**Activity and causal-role governance is required before model approval.** "
    "Physical media-unit and cost mapping is a separate optional section."
)
st.caption("See docs/media_units_and_inflation.md for the full design this mapping feeds into.")

hints = detect_column_types(df)
numeric_cols = hints["numeric"]

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)
existing_activity_items = get_state("activity_definitions") or []

st.markdown("### Required: activity and causal-role governance")
st.caption(
    "Use one row per market and activity. Add rows to distinguish paid and "
    "organic social, promotional/lifecycle/transactional CRM, PR campaigns, "
    "and named external events even when they share a reporting channel."
)
if existing_activity_items:
    activity_rows = [
        ActivityDefinition.from_dict(item).to_dict()
        for item in existing_activity_items
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
activity_editor = st.data_editor(
    pd.DataFrame(activity_rows).reindex(columns=activity_columns),
    num_rows="dynamic",
    width="stretch",
    key="activity_governance_editor",
    column_config={
        "market": st.column_config.SelectboxColumn(
            "Market", options=spec.markets, required=True
        ),
        "channel": st.column_config.TextColumn(
            "Reporting channel", required=True,
            help=(
                "Shared reporting label, such as Social. Multiple activities "
                "may share it when their model-input columns differ."
            ),
        ),
        "model_input_column": st.column_config.SelectboxColumn(
            "Model-input column", options=spec.channels, required=True
        ),
        "activity_ownership": st.column_config.SelectboxColumn(
            "Ownership", options=sorted(OWNERSHIP), required=True
        ),
        "model_role": st.column_config.SelectboxColumn(
            "Causal role", options=sorted(MODEL_ROLES), required=True
        ),
        "economic_treatment": st.column_config.SelectboxColumn(
            "Economic treatment",
            options=sorted(ECONOMIC_TREATMENTS),
            required=True,
        ),
        "planning_eligibility": st.column_config.SelectboxColumn(
            "Planning", options=sorted(PLANNING_ELIGIBILITY), required=True
        ),
        "approval_status": st.column_config.SelectboxColumn(
            "Approval", options=sorted(APPROVAL_STATUSES), required=True
        ),
    },
)

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
            raise ValueError(
                f"duplicate market/model_input_column {input_key}"
            )
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
            ActivityDefinition.from_dict(item)
            for item in existing_activity_items
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
                rebuild_curves
                or impact.rebuild_curves
                or impact.rebuild_economics
            )
            rebuild_scenarios = (
                rebuild_scenarios or impact.rebuild_scenarios
            )
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

st.markdown("---")
st.markdown("### Optional: physical media-unit and cost mapping")
st.caption(
    "Record impressions, GRPs, clicks, cost basis, and currency where these "
    "are available. Response-only activity does not need an artificial cost."
)

for market in spec.markets:
    with st.expander(f"Market: {market}", expanded=len(spec.markets) == 1):
        for channel in spec.channels:
            existing = market_config.get_media_unit_config(market, channel)
            st.markdown(f"**{readable_label(channel)}**")
            c1, c2, c3 = st.columns(3)
            response_col = c1.selectbox(
                "Response-unit column", ["(none)"] + numeric_cols,
                index=(["(none)"] + numeric_cols).index(existing.response_unit_column)
                if existing and existing.response_unit_column in numeric_cols else 0,
                format_func=lambda c: c if c == "(none)" else readable_label(c),
                key=f"unit_col_{market}_{channel}",
                help="The column that measures physical delivery for this channel, e.g. impressions or GRPs.",
            )
            unit_type = c2.selectbox(
                "Unit type", ["(none)"] + UNIT_TYPE_SUGGESTIONS,
                index=(["(none)"] + UNIT_TYPE_SUGGESTIONS).index(existing.unit_type)
                if existing and existing.unit_type in UNIT_TYPE_SUGGESTIONS else 0,
                key=f"unit_type_{market}_{channel}",
            )
            cost_basis = c3.selectbox(
                "Cost basis", ["(none)"] + COST_BASIS_SUGGESTIONS,
                index=(["(none)"] + COST_BASIS_SUGGESTIONS).index(existing.cost_basis)
                if existing and existing.cost_basis in COST_BASIS_SUGGESTIONS else 0,
                key=f"cost_basis_{market}_{channel}",
            )
            currency = st.text_input(
                "Currency (ISO code, e.g. GBP)", value=(existing.currency if existing else "") or "",
                key=f"currency_{market}_{channel}",
            )

            market_config.set_media_unit_config(ChannelMediaUnitConfig(
                market=market,
                channel=channel,
                spend_column=channel,
                response_unit_column=None if response_col == "(none)" else response_col,
                unit_type=None if unit_type == "(none)" else unit_type,
                cost_basis=None if cost_basis == "(none)" else cost_basis,
                currency=currency or None,
            ))
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

render_next_step("channel_media_units")
