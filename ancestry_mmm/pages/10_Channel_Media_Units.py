"""Page (step 4 of 11): map each channel's spend column to a physical
media-unit column, per market - optional Phase 1 data capture for the
market-specific redesign (see docs/media_units_and_inflation.md). Nothing
downstream reads this yet; it only stores the mapping for Phase 2/3.
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
    "This step is optional in Phase 1 - it records how spend relates to physical delivery "
    "(impressions, GRPs, clicks, ...) for later CPA-by-media-unit reporting and media inflation "
    "tracking. Skip it and continue if you don't have this information yet."
)
st.caption("See docs/media_units_and_inflation.md for the full design this mapping feeds into.")

hints = detect_column_types(df)
numeric_cols = hints["numeric"]

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)

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

if st.button("Save channel & media-unit mapping", type="primary"):
    set_state("market_spec_config", market_config.to_dict())
    mapped = sum(1 for c in market_config.channel_media_units.values() if c.has_media_unit())
    st.success(f"Saved. {mapped} of {len(spec.markets) * len(spec.channels)} channel/market combinations have a media-unit mapping.")

render_next_step("channel_media_units")
