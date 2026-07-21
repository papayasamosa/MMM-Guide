"""Page (step 5 of 12): market cards - data coverage summary plus optional
currency and market-descriptor capture for the market-specific redesign
(see docs/market_hierarchy.md section 5 and section 17.4). Currency is part
of the model-specification fingerprint once set (core.fingerprint); the
descriptor fields (population, awareness, maturity, ...) remain purely
informational - nothing downstream reads them.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, format_date, format_number
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_glossary
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import (
    MarketCurrency, MarketDescriptors, MarketProfile, MarketSpecConfig, market_data_quality_status,
)

st.set_page_config(page_title="Market Descriptors - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("market_descriptors")
render_page_header("market_descriptors")

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
render_glossary(["Partial pooling"])

st.markdown("---")
st.info(
    "This step is optional - it records context (currency, audience, penetration, "
    "maturity, ...) for reporting and, for currency, the model-specification fingerprint. The "
    "descriptor fields (audience, penetration, maturity, ...) are informational only and not yet "
    "used to explain market-level curve differences. Skip it and continue if you don't have this "
    "information yet."
)
st.caption("See docs/market_hierarchy.md for how this context is used, and docs/decision_log.md for the fingerprint boundary.")

config_dict = get_state("market_spec_config")
market_config = MarketSpecConfig.from_dict(config_dict)

for market in spec.markets:
    market_df = df[df[spec.market_col] == market] if spec.market_col in df.columns else df
    n_obs = len(market_df)
    date_range = (
        f"{format_date(market_df[spec.date_col].min())} to {format_date(market_df[spec.date_col].max())}"
        if n_obs and spec.date_col in market_df.columns else "(no data)"
    )
    quality = market_data_quality_status(n_obs)
    coverage = market_config.coverage_for_market(market, spec.channels)
    mapped_channels = sum(1 for v in coverage.values() if v)

    with st.expander(f"Market: {market} - {quality}", expanded=len(spec.markets) == 1):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Observations", format_number(n_obs))
            c2.metric("Date range", date_range)
            c3.metric("Segments", len(spec.segment_outcomes))
            c4.metric("Media-unit coverage", f"{mapped_channels}/{len(spec.channels)} channels")
            st.caption(f"Channels: {', '.join(spec.channels) or '(none)'}. Data quality: {quality}.")

        profile = market_config.get_profile(market)
        st.markdown("**Currency**")
        c1, c2 = st.columns(2)
        local_currency = c1.text_input(
            "Local currency (ISO code)", value=profile.currency.local_currency, key=f"currency_{market}",
        )
        reporting_currency = c2.text_input(
            "Reporting currency (optional)", value=profile.currency.reporting_currency or "", key=f"reporting_currency_{market}",
        )

        st.markdown("**Market descriptors** (all optional)")
        d = profile.descriptors
        c1, c2, c3 = st.columns(3)
        population = c1.number_input("Population", min_value=0.0, value=float(d.population or 0.0), key=f"population_{market}")
        addressable_audience = c2.number_input("Addressable audience", min_value=0.0, value=float(d.addressable_audience or 0.0), key=f"audience_{market}")
        subscriber_base = c3.number_input("Subscriber base", min_value=0.0, value=float(d.subscriber_base or 0.0), key=f"subs_{market}")
        c1, c2, c3 = st.columns(3)
        brand_penetration = c1.number_input("Brand penetration (%)", min_value=0.0, max_value=100.0, value=float(d.brand_penetration or 0.0), key=f"brandpen_{market}")
        aided_awareness = c2.number_input("Aided awareness (%)", min_value=0.0, max_value=100.0, value=float(d.aided_awareness or 0.0), key=f"aided_{market}")
        unaided_awareness = c3.number_input("Unaided awareness (%)", min_value=0.0, max_value=100.0, value=float(d.unaided_awareness or 0.0), key=f"unaided_{market}")
        c1, c2, c3 = st.columns(3)
        market_maturity = c1.selectbox("Market maturity", ["(unset)", "Emerging", "Growing", "Mature"],
                                        index=["(unset)", "Emerging", "Growing", "Mature"].index(d.market_maturity) if d.market_maturity in ["Emerging", "Growing", "Mature"] else 0,
                                        key=f"maturity_{market}")
        region = c2.text_input("Region", value=d.region or "", key=f"region_{market}")
        language_group = c3.text_input("Language group", value=d.language_group or "", key=f"language_{market}")

        if st.button(f"Save {market} profile", key=f"save_{market}"):
            market_config.set_profile(MarketProfile(
                market=market,
                currency=MarketCurrency(
                    local_currency=local_currency, reporting_currency=reporting_currency or None,
                ),
                descriptors=MarketDescriptors(
                    population=population or None,
                    addressable_audience=addressable_audience or None,
                    subscriber_base=subscriber_base or None,
                    brand_penetration=brand_penetration or None,
                    aided_awareness=aided_awareness or None,
                    unaided_awareness=unaided_awareness or None,
                    market_maturity=None if market_maturity == "(unset)" else market_maturity,
                    region=region or None,
                    language_group=language_group or None,
                ),
            ))
            set_state("market_spec_config", market_config.to_dict())
            st.success(f"Saved profile for {market}.")

render_next_step("market_descriptors")
