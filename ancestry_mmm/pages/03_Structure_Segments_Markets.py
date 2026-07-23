"""Page 3: define markets, FH segments, channels, DNA channels, promo columns and LTV as explicit structural dimensions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, clear_model_state, readable_label, FIELD_HELP, dataframe_column_config
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state, render_drift_status
from ancestry_mmm.core.schema import ModelSpec, DEFAULT_SEGMENTS

from ancestry_mmm.core.outcomes import (
    DNA_SEGMENT_NEW, DNA_SEGMENT_EXISTING_FH, DNA_SEGMENT_COMBINED,
    FAMILY_HISTORY, KNOWN_PRODUCTS, OUTCOME_ROLES, METRIC_GSA, METRIC_SIGNUP, METRIC_KIT_SALE,
    OutcomeDefinition, fh_outcomes_from_spec, dna_outcomes_from_columns,
    validate_outcome_definitions, outcomes_to_dataframe,
    validate_fh_dna_cross_sell_outcome_id, infer_legacy_fh_dna_cross_sell_outcome_id,
)
from ancestry_mmm.core.promotions import (
    PromotionEvent, validate_promotion_events, apply_promotion_events_to_frame,
    promotion_events_to_transform_steps, PROMOTION_EVENT_OP,
)
from ancestry_mmm.core.funnel import FunnelLink, validate_funnel_links
from ancestry_mmm.core.pathways import (
    PATHWAY_ROLES, MediaOutcomePathway, validate_media_outcome_pathways, pathways_drift_dataframe,
)
from ancestry_mmm.data import validate_modeling_frame, detect_column_types, pipeline_to_json, pipeline_from_json
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
st.markdown("### Media channels")
# Default to every numeric column that doesn't look like a promo flag, price,
# index/confidence-style control, or a DNA kit purchase outcome - channel
# names rarely contain the literal words "spend"/"cost"/"budget" (e.g.
# "TV_Brand", "Search_NonBrand"), so a strict keyword match against
# potential_media would under-select badly.
_non_channel_hints = ["promo", "price", "confidence", "discount", "offer", "index", "kit"]
default_channels = [c for c in numeric_cols if not any(h in c.lower() for h in _non_channel_hints)]
channels = st.multiselect("Channel spend columns *", numeric_cols, default=default_channels or numeric_cols, format_func=readable_label)
dna_channels = st.multiselect(
    "DNA-targeted media", channels, default=[c for c in channels if "dna" in c.lower()],
    format_func=readable_label,
    help="Which of these channels drive the explicit DNA halo pathway to other segments.",
)

st.markdown("---")
st.markdown("### Outcome catalogue")
st.caption(
    "The **primary workflow** for what this project actually fits (PR E.2) - one row per measurable "
    "outcome, not one weekly GSA column per segment. A sign-up KPI and a GSA KPI on the same segment "
    "are two separate rows here, each with its own `outcome_id`, `metric` and `unit`, so they are fit "
    "as fully independent outcomes - never combined anywhere downstream just because they share a "
    "`segment` (docs/outcomes.md). Add, edit, or remove rows directly below; the quick-start wizards "
    "further down are optional migration/seeding helpers only, not a second required configuration "
    "surface - a sign-up-only or GSA-only project can add its rows here without ever opening them. "
    "`included_in_fit` is the persisted 'exclude from next fit' control: unchecking a row here still "
    "captures and validates it, just holds it back from the next fit."
)

if "structure_outcome_rows" not in st.session_state:
    st.session_state["structure_outcome_rows"] = get_state("outcome_definitions") or []


def _merge_outcome_rows(new_rows: list) -> None:
    """Add/update rows in the session-state catalogue by outcome_id, without
    touching any other row an analyst may already have added or edited -
    the seeding wizards below call this rather than replacing the whole
    catalogue."""
    by_id = {r["outcome_id"]: r for r in st.session_state["structure_outcome_rows"]}
    for o in new_rows:
        by_id[o.outcome_id] = o.to_dict()
    st.session_state["structure_outcome_rows"] = list(by_id.values())
    st.session_state.pop("outcome_catalogue_editor", None)


with st.expander("Quick-start wizard: Create standard FH GSA outcomes (legacy per-segment mapping)"):
    st.caption(
        "Migration/seeding helper only, not required - maps one weekly GSA column per FH segment, "
        "the shape every project used before the general catalogue above existed. A sign-up-only or "
        "GSA-only project can skip this entirely and add rows directly above. Re-running this only "
        "adds/updates the standard GSA rows it creates; it never touches anything else in the "
        "catalogue."
    )
    n_segments = st.number_input("Number of segments", min_value=1, max_value=6, value=3, key="wiz_n_segments")
    wizard_segment_outcomes = {}
    default_keys = DEFAULT_SEGMENTS
    sample_ltv = get_state("sample_ltv") or {}
    wizard_ltv = {}
    for i in range(n_segments):
        c1, c2, c3 = st.columns(3)
        key = c1.text_input(f"Segment {i + 1} name", value=default_keys[i] if i < len(default_keys) else f"segment_{i+1}", key=f"wiz_seg_key_{i}")
        guess_idx = next((j for j, c in enumerate(numeric_cols) if key.lower().replace("_", "") in c.lower().replace("_", "")), 0)
        col = c2.selectbox(
            f"Outcome column for '{key}'", numeric_cols, index=guess_idx if numeric_cols else 0, key=f"wiz_seg_col_{i}",
            format_func=readable_label,
        )
        ltv_val = c3.number_input(f"LTV for '{key}'", min_value=0.0, value=float(sample_ltv.get(key, 100.0)), key=f"wiz_ltv_{i}")
        if key:
            wizard_segment_outcomes[key] = col
            wizard_ltv[key] = ltv_val
    if st.button("Create standard FH GSA outcomes"):
        _merge_outcome_rows(fh_outcomes_from_spec(wizard_segment_outcomes, wizard_ltv))
        st.rerun()

with st.expander("Quick-start wizard: Add DNA kit outcomes"):
    st.caption(
        "DNA kit purchases are a separate business outcome (product='DNA', metric='Kit sale') from any "
        "Family History outcome - a kit sale is never the same KPI as an FH sign-up or an FH GSA, even "
        "for the DNA cross-sell segment. Once added, they're **automatically included in the joint "
        "model fit** on Model Configuration/Training: DNA-targeted media gets full direct response on "
        "these outcomes (not the shrunk halo pathway other outcomes get) - see "
        "docs/dna_fh_causal_structure.md."
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
    if st.button("Add DNA kit outcomes to catalogue"):
        _merge_outcome_rows(dna_outcomes_from_columns(
            new_customer_column=dna_new_col, existing_fh_column=dna_existing_col, combined_column=dna_combined_col,
            value_weight_new=dna_new_weight, value_weight_existing=dna_existing_weight, value_weight_combined=dna_combined_weight,
        ))
        st.rerun()

_default_outcome_df = pd.DataFrame(st.session_state["structure_outcome_rows"]) if st.session_state["structure_outcome_rows"] else pd.DataFrame(
    columns=["outcome_id", "product", "segment", "metric", "source_column", "unit", "value_weight",
             "value_currency", "role", "included_in_fit", "exclusion_reason"]
)
if st.button("Clear outcome catalogue", help="Removes every row below - the wizards above can reseed it."):
    st.session_state["structure_outcome_rows"] = []
    st.session_state.pop("outcome_catalogue_editor", None)
    st.rerun()
outcome_catalogue_df = st.data_editor(
    _default_outcome_df,
    num_rows="dynamic",
    column_config={
        "outcome_id": st.column_config.TextColumn("outcome_id", required=True, help="Stable identity - unique per outcome."),
        "product": st.column_config.SelectboxColumn("product", options=list(KNOWN_PRODUCTS), required=True),
        "segment": st.column_config.TextColumn("segment", required=True, help="Descriptive customer-segment grouping - not unique."),
        "metric": st.column_config.TextColumn(
            "metric", required=True,
            help=f"What's being counted - e.g. '{METRIC_GSA}', '{METRIC_SIGNUP}', '{METRIC_KIT_SALE}'. "
            "A sign-up and a GSA must never share a metric value. Display label only - matching logic "
            "uses the stable metric_key derived from this automatically.",
        ),
        "source_column": st.column_config.SelectboxColumn("source_column", options=numeric_cols, required=True),
        "unit": st.column_config.TextColumn("unit", help="Counting unit - defaults from the metric registry if left blank; a custom metric needs one set explicitly."),
        "value_weight": st.column_config.NumberColumn("value_weight", min_value=0.0, help="Per-unit value (LTV for FH, an analogous per-kit value for DNA)."),
        "value_currency": st.column_config.TextColumn("value_currency", help="e.g. USD - the currency value_weight is denominated in."),
        "role": st.column_config.SelectboxColumn("role", options=list(OUTCOME_ROLES), required=True),
        "included_in_fit": st.column_config.CheckboxColumn("included_in_fit", default=True),
        "exclusion_reason": st.column_config.TextColumn("exclusion_reason"),
    },
    key="outcome_catalogue_editor",
    width="stretch",
)

if get_state("model_meta") is not None:
    _preview_outcomes = [
        OutcomeDefinition.from_dict(r) for r in outcome_catalogue_df.to_dict("records")
        if r.get("outcome_id") and r.get("product") and r.get("segment") and r.get("metric") and r.get("source_column")
    ]
    render_drift_status(_preview_outcomes, get_state("model_meta"), available_columns=set(df.columns))

_fh_candidate_ids = [
    r["outcome_id"] for r in outcome_catalogue_df.to_dict("records")
    if r.get("outcome_id") and r.get("product") == FAMILY_HISTORY
]
_legacy_candidate, _legacy_warning = infer_legacy_fh_dna_cross_sell_outcome_id([
    OutcomeDefinition.from_dict(r) for r in outcome_catalogue_df.to_dict("records")
    if r.get("outcome_id") and r.get("product") and r.get("segment") and r.get("metric") and r.get("source_column")
])
if _legacy_warning:
    st.warning(_legacy_warning)
_cross_sell_options = ["(none)"] + _fh_candidate_ids
_cross_sell_default = _legacy_candidate if _legacy_candidate in _fh_candidate_ids else "(none)"
fh_dna_cross_sell_outcome_id = st.selectbox(
    "FH DNA cross-sell outcome",
    _cross_sell_options,
    index=_cross_sell_options.index(_cross_sell_default) if _cross_sell_default in _cross_sell_options else 0,
    help="Which Family History outcome is the DNA halo pathway's target - required explicitly whenever "
    "DNA-targeted media is configured above. Automatic name-based inference is not used for a live fit "
    "(only offered here as a one-time migration suggestion for a legacy project).",
)
fh_dna_cross_sell_outcome_id = None if fh_dna_cross_sell_outcome_id == "(none)" else fh_dna_cross_sell_outcome_id

st.markdown("---")
st.markdown("### Funnel links (optional)")
st.caption(
    "Declare which sign-up and GSA outcomes (or any other upstream/downstream pair) form a funnel, "
    "e.g. a sign-up that later converts to a GSA. Sign-ups and GSAs are still fitted as independent "
    "outcome equations - this is diagnostics/warnings only (Diagnostics page), not a constrained "
    "funnel model."
)
if "funnel_links" not in st.session_state:
    st.session_state["funnel_links"] = get_state("funnel_links") or []
_all_outcome_ids = [r["outcome_id"] for r in outcome_catalogue_df.to_dict("records") if r.get("outcome_id")]
if len(_all_outcome_ids) < 2:
    st.info("Add at least two outcomes to the catalogue above to define a funnel link.")
else:
    c1, c2, c3 = st.columns([2, 2, 1])
    new_upstream = c1.selectbox("Upstream outcome (e.g. sign-up)", _all_outcome_ids, key="new_funnel_upstream")
    new_downstream = c2.selectbox("Downstream outcome (e.g. GSA)", _all_outcome_ids, key="new_funnel_downstream")
    if c3.button("Add funnel link"):
        if new_upstream == new_downstream:
            st.error("Upstream and downstream must be different outcomes.")
        else:
            pair = (new_upstream, new_downstream)
            existing_pairs = {(fl["upstream_outcome_id"], fl["downstream_outcome_id"]) for fl in st.session_state["funnel_links"]}
            if pair not in existing_pairs:
                st.session_state["funnel_links"].append({"upstream_outcome_id": new_upstream, "downstream_outcome_id": new_downstream})
            st.rerun()
    if st.session_state["funnel_links"]:
        for i, fl in enumerate(list(st.session_state["funnel_links"])):
            fc1, fc2 = st.columns([5, 1])
            fc1.write(f"{fl['upstream_outcome_id']} -> {fl['downstream_outcome_id']}")
            if fc2.button("Remove", key=f"remove_funnel_{i}"):
                st.session_state["funnel_links"].pop(i)
                st.rerun()
funnel_links = [FunnelLink.from_dict(fl) for fl in st.session_state["funnel_links"]]

st.markdown("---")
st.markdown("### Media-outcome pathway catalogue")
st.caption(
    "Declares which `(channel, target outcome)` relationships this project believes exist - a "
    "primary direct effect, a trusted cross-product effect (e.g. DNA media's halo onto FH), an "
    "exploratory one strongly shrunk toward zero and not trusted for planning by default, or an "
    "excluded one with deterministically zero contribution. Operational since PR G1 "
    "(core.pathways.resolve_pathway_masks) - both PyMC model builders read this catalogue directly "
    "to decide which coefficients get estimated and how; a cell left uncovered here falls back to "
    "the legacy default (`dna_channels` above drives that default exactly as before). Can already "
    "target planned future outcome_ids (e.g. a net bill-through count) the moment a matching row "
    "exists in the outcome catalogue above, even before any dedicated transformation computes it - "
    "see docs/media_outcome_pathways.md."
)
if "media_outcome_pathways" not in st.session_state:
    st.session_state["media_outcome_pathways"] = get_state("media_outcome_pathways") or []
_pathway_default_df = pd.DataFrame(st.session_state["media_outcome_pathways"]) if st.session_state["media_outcome_pathways"] else pd.DataFrame(
    columns=["pathway_id", "channel", "source_product", "target_outcome_id", "role", "lag_type",
             "lag_weeks", "prior_scale", "include_in_attribution", "include_in_planning", "evidence_status"]
)
pathway_catalogue_df = st.data_editor(
    _pathway_default_df,
    num_rows="dynamic",
    column_config={
        "pathway_id": None,  # auto-managed identity, not hand-edited
        "channel": st.column_config.SelectboxColumn("channel", options=channels, required=True),
        "source_product": st.column_config.SelectboxColumn("source_product", options=list(KNOWN_PRODUCTS), required=True),
        "target_outcome_id": st.column_config.SelectboxColumn(
            "target_outcome_id", options=[r["outcome_id"] for r in outcome_catalogue_df.to_dict("records") if r.get("outcome_id")],
            required=True,
        ),
        "role": st.column_config.SelectboxColumn("role", options=list(PATHWAY_ROLES), required=True, default=PATHWAY_ROLES[0]),
        "lag_type": st.column_config.TextColumn("lag_type", help="Free text, e.g. 'none', 'fixed_weeks', 'distributed'.", default="none"),
        "lag_weeks": st.column_config.NumberColumn("lag_weeks", min_value=0, help="Only meaningful if lag_type implies a delay."),
        "prior_scale": st.column_config.NumberColumn("prior_scale", min_value=0.0001, default=1.0, help="Smaller = tighter prior for a future estimation PR."),
        "include_in_attribution": st.column_config.CheckboxColumn("include_in_attribution", default=True),
        "include_in_planning": st.column_config.CheckboxColumn("include_in_planning", default=True),
        "evidence_status": st.column_config.TextColumn("evidence_status", help="Free text, e.g. 'untested', 'supported', 'inconclusive', 'contradicted'.", default="untested"),
    },
    key="pathway_catalogue_editor",
    width="stretch",
)

if get_state("model_meta") is not None and st.session_state["media_outcome_pathways"]:
    _preview_pathways = [
        MediaOutcomePathway.from_dict(r) for r in pathway_catalogue_df.to_dict("records")
        if r.get("channel") and r.get("target_outcome_id")
    ]
    _pathway_drift_df = pathways_drift_dataframe(_preview_pathways, get_state("model_meta"))
    if not _pathway_drift_df.empty:
        _changed_pathways = _pathway_drift_df[_pathway_drift_df["drift_status"] != "Fitted and current"]
        if not _changed_pathways.empty:
            st.warning(
                f"{len(_changed_pathways)} pathway(s) differ from this fit's captured pathway metadata - "
                "since PR G1 the pathway catalogue drives which coefficients get estimated, so this fit's "
                "results no longer reflect the catalogue shown above. Re-run Model Training to pick up "
                "the change."
            )
            with st.expander("Pathway drift detail"):
                st.dataframe(_pathway_drift_df, width="stretch")

st.markdown("---")
st.markdown("### Net bill-through completeness")
st.caption("Family History net bill-through is supplied as an authoritative weekly count. Configure and validate its completeness at upload; the app never reconstructs it from customer or billing events.")

# `segment_outcomes`/`segment_ltv` (ModelSpec migration fields) and per-segment
# promo/control mappings are now derived from the catalogue's own segments,
# not from a required separate mapping section - the catalogue is the single
# source of truth (PR E.2). A future PR moves promo/control mappings to
# outcome_id keys directly (docs/decision_log.md); segment-keyed is retained
# here as the current mapping granularity.
_catalogue_rows = outcome_catalogue_df.to_dict("records")
segment_outcomes = {
    r["segment"]: r["source_column"] for r in _catalogue_rows
    if r.get("segment") and r.get("source_column") and r.get("product") == FAMILY_HISTORY
}
segment_ltv = {}
for r in _catalogue_rows:
    seg = r.get("segment")
    weight = r.get("value_weight")
    if seg and weight is not None and seg not in segment_ltv:
        segment_ltv[seg] = float(weight)
_catalogue_segments = sorted({r.get("segment") for r in _catalogue_rows if r.get("segment")})

st.markdown("---")
st.markdown("### Promotional flags (per segment, optional)")
promo_cols = {}
for seg in _catalogue_segments:
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
remaining_numeric = [c for c in numeric_cols if c not in channels and c not in promo_cols.values()]
control_cols = st.multiselect("Global controls (apply to every outcome)", remaining_numeric, format_func=readable_label)

st.markdown("**Product-level controls** (apply to every outcome of one product, e.g. every DNA-product outcome)")
product_control_cols = {}
for product in KNOWN_PRODUCTS:
    cols = st.multiselect(
        f"Controls specific to product '{product}'", [c for c in remaining_numeric if c not in control_cols],
        key=f"prodctrl_{product}", format_func=readable_label,
    )
    if cols:
        product_control_cols[product] = cols

st.markdown("**Segment-specific controls** (legacy - e.g. DNA kit price -> DNA cross-sell only)")
segment_control_cols = {}
for seg in _catalogue_segments:
    cols = st.multiselect(
        f"Controls specific to '{seg}'", [c for c in remaining_numeric if c not in control_cols],
        key=f"segctrl_{seg}", format_func=readable_label,
    )
    if cols:
        segment_control_cols[seg] = cols

_outcome_ids_by_segment: dict = {}
for r in _catalogue_rows:
    oid, seg = r.get("outcome_id"), r.get("segment")
    if oid and seg:
        _outcome_ids_by_segment.setdefault(seg, []).append(oid)
_multi_outcome_segments = {seg: oids for seg, oids in _outcome_ids_by_segment.items() if len(oids) > 1}

outcome_promo_cols = {}
outcome_control_cols = {}
if _multi_outcome_segments:
    st.markdown("---")
    st.markdown("### Outcome-level promo & control overrides (optional)")
    st.caption(
        "Segment-level mappings above apply to every outcome sharing that segment by default "
        "(legacy behaviour). Override per outcome_id here when two KPIs on the same segment (e.g. a "
        "sign-up and a GSA) need genuinely different promo timing or controls - an explicit "
        "outcome_id-keyed mapping always wins over the segment-level one above for that outcome_id. "
        "'Apply to every outcome in this segment' is an explicit bulk action, not implicit inheritance."
    )
    for seg, oids in _multi_outcome_segments.items():
        with st.expander(f"Outcome overrides for segment '{seg}' ({len(oids)} outcomes)"):
            if st.button(f"Apply segment '{seg}' mapping to every outcome in it", key=f"bulk_apply_{seg}"):
                seg_promo = promo_cols.get(seg)
                seg_controls = segment_control_cols.get(seg)
                for oid in oids:
                    if seg_promo:
                        st.session_state[f"outcome_promo_{oid}"] = seg_promo
                    if seg_controls:
                        st.session_state[f"outcome_ctrl_{oid}"] = seg_controls
                st.rerun()
            for oid in oids:
                c1, c2 = st.columns(2)
                promo_choice = c1.selectbox(
                    f"Promo column for '{oid}' (or None)", ["(none)"] + numeric_cols,
                    key=f"outcome_promo_{oid}", format_func=lambda c: c if c == "(none)" else readable_label(c),
                )
                if promo_choice != "(none)":
                    outcome_promo_cols[oid] = promo_choice
                ctrl_choice = c2.multiselect(
                    f"Extra controls for '{oid}'", numeric_cols, key=f"outcome_ctrl_{oid}", format_func=readable_label,
                )
                if ctrl_choice:
                    outcome_control_cols[oid] = ctrl_choice

dna_segment_names = [s for s in _catalogue_segments if s in (DNA_SEGMENT_NEW, DNA_SEGMENT_EXISTING_FH, DNA_SEGMENT_COMBINED)]
dna_promo_cols = {}
dna_segment_control_cols = {}
if dna_segment_names:
    st.markdown("---")
    st.markdown("### DNA promotion calendar (optional, structured)")
    st.caption(
        "Alternative to a hand-built promo column above: define named promotion events (dates, "
        "discount depth, sale price) and a weekly intensity series is derived automatically - "
        "promo stays a term separate from media response either way, so a promotion is never "
        "silently absorbed into a channel's media coefficient. Takes precedence over the promo "
        "column above for the same segment when both are set."
    )
    st.caption(
        "`product`/`market` are optional, more precise targeting than `segment` alone - useful when "
        "a segment covers more than one product or the event is market-specific. `event_id` "
        "(stable identity across re-saves) and `transformation_version` are managed automatically."
    )
    dna_promo_events_df = st.data_editor(
        pd.DataFrame(columns=["event_name", "segment", "product", "market", "start_date", "end_date", "discount_depth", "sale_price", "intensity"]),
        num_rows="dynamic",
        column_config={
            "segment": st.column_config.SelectboxColumn("segment", options=dna_segment_names, required=True),
            "product": st.column_config.SelectboxColumn("product", options=[None] + list(KNOWN_PRODUCTS), help="Optional - narrows this event to one product."),
            "market": st.column_config.TextColumn("market", help="Optional - narrows this event to one market."),
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
            product=row.get("product") or None, market=row.get("market") or None,
        ))

    merged_promo_cols = {**promo_cols, **dna_promo_cols}
    merged_segment_control_cols = {**segment_control_cols, **dna_segment_control_cols}

    promo_event_errors = validate_promotion_events(dna_promotion_events)
    updated_df = None
    if dna_promotion_events and not promo_event_errors:
        updated_df, derived_promo_cols = apply_promotion_events_to_frame(df, date_col, dna_promotion_events)
        merged_promo_cols.update(derived_promo_cols)

    # Persist promotion events as replayable TransformSteps (PR E.2 #11), not
    # just as a materialised column on transformed_data - re-importing this
    # project (or replaying the pipeline against refreshed raw data) then
    # reproduces the same derived promo columns from the versioned event
    # list rather than trusting whatever happens to be sitting in a parquet.
    # Every save fully replaces the prior promotion_event steps with the
    # current event list, so re-saving the same events is idempotent.
    existing_steps = pipeline_from_json(get_state("pipeline_steps") or [])
    non_promo_steps = [s for s in existing_steps if s.op != PROMOTION_EVENT_OP]
    new_promo_steps = promotion_events_to_transform_steps(dna_promotion_events, date_col)
    updated_pipeline_steps = non_promo_steps + new_promo_steps

    spec = ModelSpec(
        date_col=date_col,
        market_col=market_col,
        markets=markets,
        unpooled_markets=unpooled_markets,
        segment_outcomes=segment_outcomes,
        channels=channels,
        dna_channels=dna_channels,
        promo_cols=merged_promo_cols,
        outcome_promo_cols=outcome_promo_cols,
        control_cols=control_cols,
        product_control_cols=product_control_cols,
        segment_control_cols=merged_segment_control_cols,
        outcome_control_cols=outcome_control_cols,
        segment_ltv=segment_ltv,
        fh_dna_cross_sell_outcome_id=fh_dna_cross_sell_outcome_id,
    )
    errors = spec.validate() + promo_event_errors

    # The outcome catalogue editor above (not the FH segment/DNA mappings)
    # is the actual saved source of truth (PR E.1) - built from its edited
    # rows, not re-derived from segment_outcomes/dna_*_col, so an analyst's
    # added/edited rows (e.g. a distinct sign-up outcome on an FH segment)
    # are what gets persisted. A blank row added by num_rows="dynamic" but
    # never filled in is skipped, same convention as the promo-events editor
    # above.
    outcome_definitions = []
    for row in outcome_catalogue_df.to_dict("records"):
        if not (row.get("outcome_id") and row.get("product") and row.get("segment") and row.get("metric") and row.get("source_column")):
            continue
        outcome_definitions.append(OutcomeDefinition.from_dict(row))
    errors += validate_outcome_definitions(outcome_definitions, available_columns=set(df.columns))
    errors += validate_fh_dna_cross_sell_outcome_id(fh_dna_cross_sell_outcome_id, outcome_definitions)
    if dna_channels and not fh_dna_cross_sell_outcome_id:
        errors.append(
            "DNA-targeted media is configured but no FH DNA cross-sell outcome is selected above - "
            "required so the halo pathway has an explicit target (automatic name-based inference is "
            "no longer used for a live fit)."
        )
    errors += validate_funnel_links(funnel_links, [o.outcome_id for o in outcome_definitions])

    media_outcome_pathways = []
    for row in pathway_catalogue_df.to_dict("records"):
        if not (row.get("channel") and row.get("source_product") and row.get("target_outcome_id")):
            continue  # a blank row added by the editor but never filled in
        media_outcome_pathways.append(MediaOutcomePathway.from_dict(row))
    errors += validate_media_outcome_pathways(
        media_outcome_pathways, channels=channels, outcome_ids=[o.outcome_id for o in outcome_definitions],
    )


    if errors:
        for e in errors:
            st.error(e)
    else:
        if updated_df is not None:
            set_state("transformed_data", updated_df)
        set_state("model_spec", spec.to_dict())
        set_state("outcome_definitions", [o.to_dict() for o in outcome_definitions])
        set_state("dna_promotion_events", [e.to_dict() for e in dna_promotion_events])
        set_state("pipeline_steps", pipeline_to_json(updated_pipeline_steps))
        set_state("funnel_links", [fl.to_dict() for fl in funnel_links])
        set_state("media_outcome_pathways", [p.to_dict() for p in media_outcome_pathways])
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
            "Every outcome captured for this project, with its current `status` (see "
            "docs/outcomes.md): `Configured` means captured here only; `Excluded` means captured "
            "but held back from the next fit; `Missing source column` means its mapped column isn't "
            "in the current data; `Included in prepared frame` / `Included in fitted run` reflect "
            "this session's actual Model Configuration / Model Training state, if any; `Stale after "
            "configuration changes` means it used to be prepared or fit but its column has since "
            "disappeared from the data."
        )
        outcomes_df = outcomes_to_dataframe(
            outcome_definitions,
            available_columns=set(df.columns),
            frame_outcome_ids=(get_state("frame") or {}).get("outcome_ids"),
            model_meta_outcome_ids=getattr(get_state("model_meta"), "outcome_ids", None),
        )
        st.dataframe(outcomes_df, width="stretch", column_config=dataframe_column_config(outcomes_df))

if get_state("model_spec"):
    render_next_step("structure")
