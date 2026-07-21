"""Page 3: define markets, FH segments, channels, DNA channels, promo columns and LTV as explicit structural dimensions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state, readable_label, FIELD_HELP, dataframe_column_config
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.core.schema import ModelSpec, DEFAULT_SEGMENTS
from ancestry_mmm.core.outcomes import (
    DNA_SEGMENT_NEW, DNA_SEGMENT_EXISTING_FH, DNA_SEGMENT_COMBINED,
    fh_outcomes_from_spec, dna_outcomes_from_columns, validate_outcome_definitions, outcomes_to_dataframe,
)
from ancestry_mmm.core.promotions import PromotionEvent, validate_promotion_events, apply_promotion_events_to_frame
from ancestry_mmm.data import validate_modeling_frame, detect_column_types
import pandas as pd

st.set_page_config(page_title="Structure - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("structure")
render_page_header("structure")
st.caption(
    "Markets and FH segments (New, DNA cross-sell, Winback) are explicit structural dimensions "
    "here - not just filter values - because the joint hierarchical model needs to know them to "
    "share curves correctly and keep each segment's economics visible throughout."
)

df = get_state("transformed_data")
if df is None:
    st.markdown("---")
    render_empty_state(
        "No transformed data yet. Complete Transform Pipeline first.",
        button_label="Go to Transform Pipeline", target_key="transform_pipeline",
    )
    st.stop()

date_col = get_state("date_col")
market_col = get_state("market_col")
hints = detect_column_types(df)
numeric_cols = hints["numeric"]

st.markdown("---")
st.markdown("### Markets")
if market_col:
    available_markets = sorted(df[market_col].dropna().unique().tolist())
    markets = st.multiselect("Markets to include *", available_markets, default=available_markets)
    unpooled_markets = st.multiselect(
        "Markets to model unpooled (structurally too different to share strength)",
        markets, default=[],
        help="Everything else defaults to partial pooling across markets. " + FIELD_HELP["partial_pooling"],
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

n_segments = st.number_input("Number of segments *", min_value=1, max_value=6, value=3)
segment_outcomes = {}
default_keys = DEFAULT_SEGMENTS
for i in range(n_segments):
    c1, c2 = st.columns(2)
    key = c1.text_input(f"Segment {i + 1} name", value=default_keys[i] if i < len(default_keys) else f"segment_{i+1}", key=f"seg_key_{i}")
    guess_idx = next((j for j, c in enumerate(numeric_cols) if key.lower().replace("_", "") in c.lower().replace("_", "")), 0)
    col = c2.selectbox(
        f"Outcome column for '{key}'", numeric_cols, index=guess_idx if numeric_cols else 0, key=f"seg_col_{i}",
        format_func=readable_label,
    )
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
# "kit" excludes DNA kit purchase outcome columns (core.outcomes) - they're
# numeric like a spend column but are an outcome, not media spend.
_non_channel_hints = ["promo", "price", "confidence", "discount", "offer", "index", "kit"]
default_channels = [c for c in spend_hint_cols if not any(h in c.lower() for h in _non_channel_hints)]
channels = st.multiselect("Channel spend columns *", spend_hint_cols, default=default_channels or spend_hint_cols, format_func=readable_label)
dna_channels = st.multiselect(
    "DNA-targeted media", channels, default=[c for c in channels if "dna" in c.lower()],
    format_func=readable_label,
    help="Which of these channels drive the explicit DNA halo pathway to other segments.",
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
        format_func=lambda c: c if c == "(none)" else readable_label(c),
    )
    if col != "(none)":
        promo_cols[seg] = col

st.markdown("---")
st.markdown("### Controls")
remaining_numeric = [c for c in numeric_cols if c not in segment_outcomes.values() and c not in channels and c not in promo_cols.values()]
control_cols = st.multiselect("Global controls (apply to all segments)", remaining_numeric, format_func=readable_label)

st.markdown("**Segment-specific controls** (e.g. DNA kit price -> DNA cross-sell only)")
segment_control_cols = {}
for seg in segment_outcomes:
    cols = st.multiselect(
        f"Controls specific to '{seg}'", [c for c in remaining_numeric if c not in control_cols],
        key=f"segctrl_{seg}", format_func=readable_label,
    )
    if cols:
        segment_control_cols[seg] = cols

st.markdown("---")
st.markdown("### Segment LTV")
st.caption(FIELD_HELP["ltv"])
sample_ltv = get_state("sample_ltv") or {}
segment_ltv = {}
for seg in segment_outcomes:
    default_val = sample_ltv.get(seg, 100.0)
    segment_ltv[seg] = st.number_input(f"LTV for '{seg}'", min_value=0.0, value=float(default_val), key=f"ltv_{seg}")

st.markdown("---")
st.markdown("### DNA outcomes (optional)")
st.info(
    "DNA kit purchases are a separate business outcome from the FH DNA-cross-sell signup GSA above "
    "- map them here so they're captured and, once mapped, **automatically included in the joint "
    "model fit** on Model Configuration/Training: DNA-targeted media gets full direct response on "
    "these segments (not the shrunk halo pathway other segments get) - see "
    "docs/dna_fh_causal_structure.md. Skip this if you don't have the columns yet."
)
dna_mode = st.radio(
    "Data available for DNA kit purchases",
    ["None yet", "Separate New Customer / Existing FH Customer columns", "Single combined column"],
    horizontal=True,
)
dna_new_col = dna_existing_col = dna_combined_col = None
dna_new_weight = dna_existing_weight = dna_combined_weight = None
if dna_mode == "Separate New Customer / Existing FH Customer columns":
    c1, c2 = st.columns(2)
    dna_new_col = c1.selectbox("New Customer DNA kit column", ["(none)"] + numeric_cols, format_func=lambda c: c if c == "(none)" else readable_label(c))
    dna_new_col = None if dna_new_col == "(none)" else dna_new_col
    dna_new_weight = c1.number_input("Value per kit (New Customer)", min_value=0.0, value=90.0)
    dna_existing_col = c2.selectbox("Existing FH Customer DNA kit column", ["(none)"] + numeric_cols, format_func=lambda c: c if c == "(none)" else readable_label(c))
    dna_existing_col = None if dna_existing_col == "(none)" else dna_existing_col
    dna_existing_weight = c2.number_input("Value per kit (Existing FH Customer)", min_value=0.0, value=65.0)
elif dna_mode == "Single combined column":
    dna_combined_col = st.selectbox("Combined DNA kit column", ["(none)"] + numeric_cols, format_func=lambda c: c if c == "(none)" else readable_label(c))
    dna_combined_col = None if dna_combined_col == "(none)" else dna_combined_col
    dna_combined_weight = st.number_input("Value per kit (combined)", min_value=0.0, value=80.0)
    st.caption(
        "A single combined outcome is an explicit fallback for data that can't support the "
        "New/Existing split - it will be labelled as such wherever outcomes are shown."
    )

dna_segment_names = []
if dna_new_col:
    dna_segment_names.append(DNA_SEGMENT_NEW)
if dna_existing_col:
    dna_segment_names.append(DNA_SEGMENT_EXISTING_FH)
if dna_combined_col:
    dna_segment_names.append(DNA_SEGMENT_COMBINED)

dna_promo_cols = {}
dna_segment_control_cols = {}
if dna_segment_names:
    st.markdown("#### DNA promotional & price sensitivity (optional)")
    st.caption(
        "Mapped the same way as FH segments above: a promo flag/intensity column, and any price or "
        "competitive controls specific to this DNA segment (e.g. DNA kit price)."
    )
    for seg in dna_segment_names:
        c1, c2 = st.columns(2)
        promo_col = c1.selectbox(
            f"Promo column for '{seg}' (or None)", ["(none)"] + numeric_cols, key=f"dna_promo_{seg}",
            format_func=lambda c: c if c == "(none)" else readable_label(c),
        )
        if promo_col != "(none)":
            dna_promo_cols[seg] = promo_col
        ctrl_cols = c2.multiselect(f"Price/competitive controls for '{seg}'", numeric_cols, key=f"dna_ctrl_{seg}", format_func=readable_label)
        if ctrl_cols:
            dna_segment_control_cols[seg] = ctrl_cols

    st.markdown("#### DNA promotion calendar (optional, structured)")
    st.caption(
        "Alternative to a hand-built promo column above: define named promotion events (dates, "
        "discount depth, sale price) and a weekly intensity series is derived automatically - "
        "promo stays a term separate from media response either way, so a promotion is never "
        "silently absorbed into a channel's media coefficient. Takes precedence over the promo "
        "column above for the same segment when both are set."
    )
    dna_promo_events_df = st.data_editor(
        pd.DataFrame(columns=["event_name", "segment", "start_date", "end_date", "discount_depth", "sale_price", "intensity"]),
        num_rows="dynamic",
        column_config={
            "segment": st.column_config.SelectboxColumn("segment", options=dna_segment_names, required=True),
            "start_date": st.column_config.TextColumn("start_date", help="YYYY-MM-DD"),
            "end_date": st.column_config.TextColumn("end_date", help="YYYY-MM-DD"),
            "discount_depth": st.column_config.NumberColumn("discount_depth", help="0-1 fraction, e.g. 0.2 for 20% off", min_value=0.0, max_value=1.0),
            "intensity": st.column_config.NumberColumn("intensity", help="Weekly series value while active", default=1.0),
        },
        key="dna_promotion_events_editor",
    )
else:
    dna_promo_events_df = pd.DataFrame()

st.markdown("---")
if st.button("Save structure and validate", type="primary"):
    dna_promotion_events = []
    for row in dna_promo_events_df.to_dict("records"):
        if not (row.get("event_name") or row.get("segment") or row.get("start_date") or row.get("end_date")):
            continue  # a blank row added by the editor but never filled in
        dna_promotion_events.append(PromotionEvent(
            event_name=row.get("event_name") or "", segment=row.get("segment") or "",
            start_date=row.get("start_date") or "", end_date=row.get("end_date") or "",
            discount_depth=row.get("discount_depth"), sale_price=row.get("sale_price"),
            intensity=row.get("intensity") if row.get("intensity") is not None else 1.0,
        ))

    merged_promo_cols = {**promo_cols, **dna_promo_cols}
    merged_segment_control_cols = {**segment_control_cols, **dna_segment_control_cols}

    promo_event_errors = validate_promotion_events(dna_promotion_events)
    updated_df = None
    if dna_promotion_events and not promo_event_errors:
        updated_df, derived_promo_cols = apply_promotion_events_to_frame(df, date_col, dna_promotion_events)
        merged_promo_cols.update(derived_promo_cols)

    spec = ModelSpec(
        date_col=date_col,
        market_col=market_col,
        markets=markets,
        unpooled_markets=unpooled_markets,
        segment_outcomes=segment_outcomes,
        channels=channels,
        dna_channels=dna_channels,
        promo_cols=merged_promo_cols,
        control_cols=control_cols,
        segment_control_cols=merged_segment_control_cols,
        segment_ltv=segment_ltv,
    )
    errors = spec.validate() + promo_event_errors

    outcome_definitions = fh_outcomes_from_spec(segment_outcomes, segment_ltv) + dna_outcomes_from_columns(
        new_customer_column=dna_new_col, existing_fh_column=dna_existing_col, combined_column=dna_combined_col,
        value_weight_new=dna_new_weight, value_weight_existing=dna_existing_weight, value_weight_combined=dna_combined_weight,
    )
    errors += validate_outcome_definitions(outcome_definitions)

    if errors:
        for e in errors:
            st.error(e)
    else:
        if updated_df is not None:
            set_state("transformed_data", updated_df)
        set_state("model_spec", spec.to_dict())
        set_state("outcome_definitions", [o.to_dict() for o in outcome_definitions])
        set_state("dna_promotion_events", [e.to_dict() for e in dna_promotion_events])
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

        st.markdown("#### Outcome catalogue")
        st.caption(
            "Every outcome captured for this project. `modelled_today = True` (Family History) means "
            "always fit; `False` (DNA) means captured here and automatically included the next time "
            "the modelling frame is prepared on Model Configuration - not yet part of a fitted model "
            "until then."
        )
        outcomes_df = outcomes_to_dataframe(outcome_definitions)
        st.dataframe(outcomes_df, width="stretch", column_config=dataframe_column_config(outcomes_df))

if get_state("model_spec"):
    render_next_step("structure")
