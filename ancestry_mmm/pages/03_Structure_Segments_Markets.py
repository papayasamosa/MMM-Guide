"""Page 3: define markets, FH segments, channels, DNA channels, promo columns and LTV as explicit structural dimensions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state
from ancestry_mmm.core.schema import ModelSpec, DEFAULT_SEGMENTS
from ancestry_mmm.data import validate_modeling_frame, detect_column_types

st.set_page_config(page_title="Structure - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("🧩 Structure: Segments & Markets")
st.caption(
    "Markets and FH segments (New, DNA cross-sell, Winback) are explicit structural dimensions "
    "here - not just filter values - because the joint hierarchical model needs to know them to "
    "share curves correctly and keep each segment's economics visible throughout."
)

df = get_state("transformed_data")
if df is None:
    st.warning("No transformed data yet. Go to **Transform Pipeline** first.")
    st.stop()

date_col = get_state("date_col")
market_col = get_state("market_col")
hints = detect_column_types(df)
numeric_cols = hints["numeric"]

st.markdown("### Markets")
if market_col:
    available_markets = sorted(df[market_col].dropna().unique().tolist())
    markets = st.multiselect("Markets to include", available_markets, default=available_markets)
    unpooled_markets = st.multiselect(
        "Markets to model unpooled (structurally too different to share strength)",
        markets, default=[],
        help="Everything else defaults to partial pooling across markets.",
    )
else:
    st.info("No market column was set - treating this as a single implicit market.")
    df = df.copy()
    df["_market"] = "default"
    market_col = "_market"
    markets = ["default"]
    unpooled_markets = []

st.markdown("---")
st.markdown("### FH segments")
st.caption("Map each segment to its weekly GSA outcome column.")

n_segments = st.number_input("Number of segments", min_value=1, max_value=6, value=3)
segment_outcomes = {}
default_keys = DEFAULT_SEGMENTS
for i in range(n_segments):
    c1, c2 = st.columns(2)
    key = c1.text_input(f"Segment {i + 1} name", value=default_keys[i] if i < len(default_keys) else f"segment_{i+1}", key=f"seg_key_{i}")
    guess_idx = next((j for j, c in enumerate(numeric_cols) if key.lower().replace("_", "") in c.lower().replace("_", "")), 0)
    col = c2.selectbox(f"Outcome column for '{key}'", numeric_cols, index=guess_idx if numeric_cols else 0, key=f"seg_col_{i}")
    if key:
        segment_outcomes[key] = col

dna_segment_guess = next((s for s in segment_outcomes if "dna" in s.lower()), None)

st.markdown("---")
st.markdown("### Media channels")
spend_hint_cols = [c for c in numeric_cols if c not in segment_outcomes.values()]
# Default to every remaining numeric column that doesn't look like a promo flag,
# price, or index/confidence-style control - channel names rarely contain the
# literal words "spend"/"cost"/"budget" (e.g. "TV_Brand", "Search_NonBrand"),
# so a strict keyword match against potential_media would under-select badly.
_non_channel_hints = ["promo", "price", "confidence", "discount", "offer", "index"]
default_channels = [c for c in spend_hint_cols if not any(h in c.lower() for h in _non_channel_hints)]
channels = st.multiselect("Channel spend columns", spend_hint_cols, default=default_channels or spend_hint_cols)
dna_channels = st.multiselect(
    "Which of these are DNA-targeted media? (drives the explicit DNA halo pathway)",
    channels, default=[c for c in channels if "dna" in c.lower()],
)

st.markdown("---")
st.markdown("### Promotional flags (per segment, optional)")
promo_cols = {}
for seg in segment_outcomes:
    col = st.selectbox(
        f"Promo column for '{seg}' (or None)",
        ["(none)"] + numeric_cols, key=f"promo_{seg}",
        index=(["(none)"] + numeric_cols).index(next((c for c in numeric_cols if "promo" in c.lower() and seg.lower()[:3] in c.lower()), "(none)"))
        if any("promo" in c.lower() for c in numeric_cols) else 0,
    )
    if col != "(none)":
        promo_cols[seg] = col

st.markdown("---")
st.markdown("### Controls")
remaining_numeric = [c for c in numeric_cols if c not in segment_outcomes.values() and c not in channels and c not in promo_cols.values()]
control_cols = st.multiselect("Global controls (apply to all segments)", remaining_numeric)

st.markdown("**Segment-specific controls** (e.g. DNA kit price -> DNA cross-sell only)")
segment_control_cols = {}
for seg in segment_outcomes:
    cols = st.multiselect(f"Controls specific to '{seg}'", [c for c in remaining_numeric if c not in control_cols], key=f"segctrl_{seg}")
    if cols:
        segment_control_cols[seg] = cols

st.markdown("---")
st.markdown("### Segment LTV (used for LTV-weighted optimisation)")
sample_ltv = get_state("sample_ltv") or {}
segment_ltv = {}
for seg in segment_outcomes:
    default_val = sample_ltv.get(seg, 100.0)
    segment_ltv[seg] = st.number_input(f"LTV for '{seg}'", min_value=0.0, value=float(default_val), key=f"ltv_{seg}")

st.markdown("---")
if st.button("Save structure and validate", type="primary"):
    spec = ModelSpec(
        date_col=date_col,
        market_col=market_col,
        markets=markets,
        unpooled_markets=unpooled_markets,
        segment_outcomes=segment_outcomes,
        channels=channels,
        dna_channels=dna_channels,
        promo_cols=promo_cols,
        control_cols=control_cols,
        segment_control_cols=segment_control_cols,
        segment_ltv=segment_ltv,
    )
    errors = spec.validate()
    if errors:
        for e in errors:
            st.error(e)
    else:
        set_state("model_spec", spec.to_dict())
        clear_model_state()
        issues = validate_modeling_frame(
            df if market_col in df.columns else df.assign(**{market_col: "default"}),
            channels=channels, segment_outcomes=segment_outcomes, market_col=market_col,
        )
        set_state("validation_issues", issues)
        st.success("Structure saved.")
        if issues:
            st.markdown("#### Validation flags")
            for issue in issues:
                (st.warning if issue["level"] == "warning" else st.error)(issue["message"])
        else:
            st.info("No validation issues flagged.")

if get_state("model_spec"):
    st.markdown("---")
    if st.button("Continue to Model Configuration →", type="primary"):
        st.switch_page("pages/04_Model_Config.py")
