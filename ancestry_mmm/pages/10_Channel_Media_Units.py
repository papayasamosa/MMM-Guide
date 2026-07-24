"""Page (step 4 of 12): map each channel's spend column to a physical
media-unit column, per market - optional data capture for the
market-specific redesign (see docs/media_units_and_inflation.md). Feeds
core.media_units's CPA/response-unit-curve calculations and is part of the
model-specification fingerprint once mapped (core.fingerprint).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, readable_label
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_glossary
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig, MarketSpecConfig, UNIT_TYPE_SUGGESTIONS, COST_BASIS_SUGGESTIONS,
)
from ancestry_mmm.core.activities import (
    ECONOMIC_TREATMENTS,
    MODEL_ROLES,
    OWNERSHIP,
    PLANNING_ELIGIBILITY,
    ActivityDefinition,
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
    "This step is optional - it records how spend relates to physical delivery "
    "(impressions, GRPs, clicks, ...) for CPA-by-media-unit reporting and media inflation "
    "tracking. Skip it and continue if you don't have this information yet."
)
st.caption("See docs/media_units_and_inflation.md for the full design this mapping feeds into.")

hints = detect_column_types(df)
numeric_cols = hints["numeric"]

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)
existing_activities = {
    item["channel"]: item
    for item in (get_state("activity_definitions") or [])
}

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

st.markdown("### Activity ownership and planning governance")
st.caption(
    "Owned and earned activity can be measured without inventing a zero cost. "
    "Mediators, controls, and events cannot be freely optimised."
)
activity_definitions = []
activity_errors = []
for channel in spec.channels:
    existing = existing_activities.get(channel, {})
    with st.expander(f"Activity: {readable_label(channel)}"):
        c1, c2, c3, c4 = st.columns(4)
        ownership = c1.selectbox(
            "Ownership",
            sorted(OWNERSHIP),
            index=sorted(OWNERSHIP).index(
                existing.get("activity_ownership", "paid")
            ),
            key=f"activity_owner_{channel}",
        )
        role = c2.selectbox(
            "Model role",
            sorted(MODEL_ROLES),
            index=sorted(MODEL_ROLES).index(
                existing.get("model_role", "intervention")
            ),
            key=f"activity_role_{channel}",
        )
        economics = c3.selectbox(
            "Economic treatment",
            sorted(ECONOMIC_TREATMENTS),
            index=sorted(ECONOMIC_TREATMENTS).index(
                existing.get("economic_treatment", "paid_media_cost")
            ),
            key=f"activity_economics_{channel}",
        )
        planning = c4.selectbox(
            "Planning eligibility",
            sorted(PLANNING_ELIGIBILITY),
            index=sorted(PLANNING_ELIGIBILITY).index(
                existing.get("planning_eligibility", "optimisable")
            ),
            key=f"activity_planning_{channel}",
        )
        try:
            activity_definitions.append(
                ActivityDefinition(
                    activity_id=existing.get("activity_id", channel),
                    channel=channel,
                    activity_ownership=ownership,
                    model_role=role,
                    economic_treatment=economics,
                    planning_eligibility=planning,
                    source=existing.get("source", "channel mapping UI"),
                    evidence_status=existing.get(
                        "evidence_status", "not_assessed"
                    ),
                    governance_notes=existing.get("governance_notes", ""),
                )
            )
        except ValueError as error:
            activity_errors.append(f"{readable_label(channel)}: {error}")
            st.error(f"{readable_label(channel)}: {error}")

if st.button("Save channel & media-unit mapping", type="primary"):
    if activity_errors:
        st.error(
            "Nothing was saved. Resolve every activity-governance error first."
        )
    else:
        set_state("market_spec_config", market_config.to_dict())
        set_state(
            "activity_definitions",
            [definition.to_dict() for definition in activity_definitions],
        )
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
