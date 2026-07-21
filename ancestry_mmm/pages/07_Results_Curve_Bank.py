"""Page 7: segment + total-FH contributions, ROAS/CPA, LTV-weighted value, and the versioned curve bank."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import init_session_state, get_state, set_state, curve_bank_dir, dataframe_column_config, format_date, FIELD_HELP
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec, fingerprint_posterior
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.market_config import MarketSpecConfig
from ancestry_mmm.core.attribution import (
    compute_shapley_contributions, segment_channel_summary, total_fh_contribution, contribution_waterfall,
)
from ancestry_mmm.core import curve_bank as cb
from ancestry_mmm.core.evidence_tiers import classify_all_markets
from ancestry_mmm.core.market_specific_predict import generate_market_channel_curve
from ancestry_mmm.components.charts import create_waterfall_chart, create_response_curve

st.set_page_config(page_title="Results & Curve Bank - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("curve_bank")
render_page_header("curve_bank")

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
if trace is None or frame is None or meta is None or params is None:
    st.markdown("---")
    render_empty_state(
        "No trained model yet. Complete Model Training first.",
        button_label="Go to Model Training", target_key="model_training",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv
model_type = get_state("model_type", "shared")

if model_type == "market_specific":
    st.markdown("---")
    st.info(
        "Shapley attribution isn't available yet for market-specific models - it's built around a "
        "single shared curve per channel and would misread a market-specific fit. This is planned "
        "for a later phase (see docs/curve_bank.md). In the meantime, explore each market's own "
        "channel curves below - and you can still save market-specific curves to the curve bank "
        "further down this page."
    )

    st.markdown("### Market-specific channel curve viewer")
    st.caption(
        "Spend -> incremental response for one market and channel, per segment and overall "
        "(overall = sum of segment responses). Point estimates only (posterior means) - "
        "credible intervals are also a later-phase addition."
    )
    c1, c2 = st.columns(2)
    viewer_market = c1.selectbox("Market", meta.markets)
    viewer_channel = c2.selectbox("Channel", meta.channels)

    curve_df = generate_market_channel_curve(viewer_market, viewer_channel, meta, params)
    st.plotly_chart(
        create_response_curve(
            curve_df["spend"].to_numpy(), curve_df["overall_response"].to_numpy(),
            f"{viewer_market} - {viewer_channel}",
        ),
        width="stretch",
    )
    st.dataframe(curve_df, width="stretch", column_config=dataframe_column_config(curve_df))

    st.markdown("---")
    st.markdown("### DNA halo strength by segment")
    st.caption("Shared across markets in this model structure (only K and beta are market-specific).")
    halo_df = pd.DataFrame([{"segment": s, "halo_strength": params.halo_strength.get(s)} for s in meta.segments])
    st.dataframe(halo_df, width="stretch", column_config=dataframe_column_config(halo_df))

else:
    st.markdown("---")
    with st.spinner("Computing Shapley contributions..."):
        contributions = compute_shapley_contributions(frame, meta, params, n_permutations=100)

    st.markdown("### Total-FH contribution by channel")
    st.caption("Total impact per channel across all segments, plus which segment that impact falls into and LTV-weighted value.")
    total_df = total_fh_contribution(frame, meta, params, contributions, ltv)
    st.dataframe(total_df, width="stretch", column_config=dataframe_column_config(total_df))

    st.markdown("---")
    st.markdown("### Segment x channel detail")
    seg_df = segment_channel_summary(frame, meta, params, contributions, ltv)
    st.dataframe(seg_df, width="stretch", column_config=dataframe_column_config(seg_df))

    st.markdown("---")
    st.markdown("### Contribution waterfall")
    waterfall_scope = st.selectbox("Scope", ["Total FH"] + meta.segments)
    segment_arg = None if waterfall_scope == "Total FH" else waterfall_scope
    waterfall_df = contribution_waterfall(frame, meta, params, segment=segment_arg, contributions=contributions)
    st.plotly_chart(
        create_waterfall_chart(waterfall_df["category"].tolist(), waterfall_df["value"].tolist(), title=f"{waterfall_scope} contribution waterfall"),
        width="stretch",
    )

    st.markdown("---")
    st.markdown("### DNA halo strength by segment")
    halo_df = pd.DataFrame([{"segment": s, "halo_strength": params.halo_strength.get(s)} for s in meta.segments])
    st.dataframe(halo_df, width="stretch", column_config=dataframe_column_config(halo_df))
    st.caption(
        f"DNA cross-sell segment ('{meta.dna_segment}') is fixed at 1.0 (full weight). "
        "Other segments' values are the estimated halo effect strength, shrunk toward zero by prior "
        "default and only pulled away from zero where the data supports it."
    )

# --- Curve bank: available for both model types (Phase 3a) - a market-
# specific fit saves one set of curves per market, each labelled with its
# own evidence tier (docs/market_hierarchy.md section 4); a shared-curve
# fit saves one set of curves labelled "Shared".
st.markdown("---")
st.markdown("## Curve bank")
st.caption(FIELD_HELP["curve_bank"])

approval_dict = get_state("model_approval")
model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)

current_identity = None
if model_run_id and spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(spec_dict, prior_config, dna_lag_weeks, model_type=model_type),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

approval_matches_current = (
    approval_dict is not None
    and current_identity is not None
    and ModelApproval.from_dict(approval_dict).matches_current_model(**current_identity)
)

if not approval_dict:
    st.markdown("---")
    render_empty_state(
        "This model hasn't been approved yet. Results above are still visible for review, but "
        "saving to the curve bank is blocked until the model is approved on Diagnostics.",
        button_label="Go to Diagnostics", target_key="diagnostics",
    )
elif not approval_matches_current:
    st.markdown("---")
    render_empty_state(
        "This model's approval no longer matches the current fitted model (the data, "
        "specification, posterior, or run have changed since it was approved). Saving to the "
        "curve bank is blocked until it's reviewed and approved again.",
        button_label="Go to Diagnostics", target_key="diagnostics",
    )
else:
    approval = ModelApproval.from_dict(approval_dict)
    st.caption(f"Model approved by **{approval.approved_by}** - saving to the curve bank will record this approval on every curve saved.")

    c1, c2 = st.columns(2)
    run_label = c1.text_input("Run label *", value=f"{spec.markets and spec.markets[0] or 'run'}-v1")
    notes = c2.text_input("Notes (optional)")

    if st.button("Save current curves to curve bank", type="primary"):
        data_window = (str(pd.Timestamp(frame["dates"].min()).date()), str(pd.Timestamp(frame["dates"].max()).date()))
        try:
            if model_type == "market_specific":
                with st.spinner("Classifying market evidence tiers..."):
                    evidence_tiers = classify_all_markets(trace, frame, meta)
                market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))
                currency_by_market = {
                    m: market_config.get_profile(m).currency.local_currency
                    for m in meta.markets if market_config.get_profile(m).currency.local_currency
                }
                entries = cb.make_entries(
                    meta, params, data_window, run_label, approval, model_type=model_type,
                    evidence_tiers=evidence_tiers, currency_by_market=currency_by_market,
                    notes=notes, **current_identity,
                )
            else:
                entries = cb.make_entries(
                    meta, params, data_window, run_label, approval, model_type=model_type,
                    notes=notes, **current_identity,
                )
        except ApprovalMismatchError as e:
            st.error(f"Could not save to the curve bank: {e}")
        else:
            paths = cb.save_entries(curve_bank_dir(), entries)
            set_state("curve_bank_entry_id", entries[0].entry_id if entries else None)
            st.success(f"Saved {len(entries)} curve bank entries to {curve_bank_dir()}.")

entries = cb.load_all_entries(curve_bank_dir())
if entries:
    st.markdown("#### Curve bank history")
    entries_df = cb.entries_to_dataframe(entries)

    f1, f2, f3, f4 = st.columns(4)
    market_filter = f1.multiselect("Filter: market", sorted(entries_df["market"].unique()))
    channel_filter = f2.multiselect("Filter: channel", sorted(entries_df["channel"].unique()))
    segment_filter = f3.multiselect("Filter: segment", sorted(entries_df["segment_or_overall"].unique()))
    status_filter = f4.multiselect("Filter: curve status", sorted(entries_df["curve_status"].unique()))

    filtered_df = entries_df
    if market_filter:
        filtered_df = filtered_df[filtered_df["market"].isin(market_filter)]
    if channel_filter:
        filtered_df = filtered_df[filtered_df["channel"].isin(channel_filter)]
    if segment_filter:
        filtered_df = filtered_df[filtered_df["segment_or_overall"].isin(segment_filter)]
    if status_filter:
        filtered_df = filtered_df[filtered_df["curve_status"].isin(status_filter)]

    st.dataframe(filtered_df, width="stretch", column_config=dataframe_column_config(filtered_df))
    if entries_df["legacy_approval"].any():
        st.caption(
            "Rows marked `legacy_approval = True` were saved before curve bank entries were "
            "bound to a verified model run - their approval could not be checked against a "
            "specific fitted model."
        )
    if entries_df["legacy_format"].any():
        st.caption(
            "Rows marked `legacy_format = True` were saved before curves were stored one-per-market/"
            "channel/segment (Phase 3a) - each was one shared, run-level record, expanded into this "
            "table's shape for display; their `curve_status` is always `Legacy`."
        )

    st.markdown("#### Log a geo-test / in-platform calibration result")
    entry_options = {
        f"{e.run_label} - {e.market or '(shared)'} / {e.channel} / {e.segment_or_overall} "
        f"({e.entry_id[:8]}, {format_date(pd.Timestamp.fromtimestamp(e.created_at))})": e.entry_id
        for e in entries
    }
    chosen_label = st.selectbox("Curve bank entry", list(entry_options.keys()))
    chosen_entry = next(e for e in entries if e.entry_id == entry_options[chosen_label])

    c1, c2 = st.columns(2)
    test_type = c1.selectbox("Test type", ["geo", "in_platform"])
    model_estimate = c2.number_input("Model estimate (e.g. ROAS)", value=float(chosen_entry.beta))
    c1, c2 = st.columns(2)
    test_estimate = c1.number_input("Test estimate", value=0.0)
    tolerance = c2.slider("Agreement tolerance (%)", 5, 100, 25)

    if st.button("Log calibration result"):
        record = cb.record_calibration(
            curve_bank_dir(), chosen_entry.entry_id, chosen_entry.channel, chosen_entry.segment_or_overall,
            test_type, model_estimate, test_estimate, tolerance_pct=tolerance,
        )
        st.success(f"Logged calibration result: **{record.agreement}**")

    calibrations = cb.load_all_calibrations(curve_bank_dir())
    if calibrations:
        st.markdown("#### Calibration history")
        cal_df = cb.calibrations_to_dataframe(calibrations)
        st.dataframe(cal_df, width="stretch", column_config=dataframe_column_config(cal_df))
else:
    st.info("No curve bank entries saved yet.")

render_next_step("curve_bank")
