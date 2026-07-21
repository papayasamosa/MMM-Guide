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
from ancestry_mmm.core.predict import generate_channel_curve
from ancestry_mmm.core.market_specific_predict import generate_market_channel_curve
from ancestry_mmm.core.media_units import (
    compute_cpa, cpa_stability_flags, extract_cost_per_unit_series, historical_cost_trend,
    response_unit_curve, equivalent_delivery, equivalent_response,
)
from ancestry_mmm.components.charts import create_waterfall_chart, create_response_curve

st.set_page_config(page_title="Results & Curve Bank - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("curve_bank")
render_page_header("curve_bank")


def _render_curve_with_cpa(curve_df: pd.DataFrame, title: str) -> None:
    """Response chart + CPA table (docs/media_units_and_inflation.md) for
    any curve DataFrame - shared by both model types since
    core.predict.generate_channel_curve and
    core.market_specific_predict.generate_market_channel_curve produce the
    same column shape."""
    st.plotly_chart(
        create_response_curve(curve_df["spend"].to_numpy(), curve_df["overall_response"].to_numpy(), title),
        width="stretch",
    )
    cpa_df = compute_cpa(curve_df)
    st.markdown("**Spend curve with CPA**")
    st.caption(
        "Average CPA = spend / incremental outcomes; marginal CPA = change in spend / change in "
        "incremental outcomes - both shown together since they diverge near saturation. Left blank "
        "wherever response (or its change between points) is zero or negative."
    )
    st.dataframe(cpa_df, width="stretch", column_config=dataframe_column_config(cpa_df))
    for f in cpa_stability_flags(curve_df)[:5]:
        st.warning(f["message"])


def _render_media_unit_section(curve_df: pd.DataFrame, market_config: MarketSpecConfig, market: str, channel: str) -> None:
    """Historical cost trend, response-unit curve, and equivalent delivery/
    response calculators for one (market, channel) - only shown where a
    media-unit mapping exists (Channel & Media Units page)."""
    config = market_config.get_media_unit_config(market, channel)
    if not (config and config.has_media_unit()):
        st.caption(
            f"No media-unit mapping for {market} / {channel} yet - add one on Channel & Media Units "
            "to see a response-unit curve, historical cost trend, and delivery/response equivalence "
            "calculators here."
        )
        return

    try:
        cost_df = extract_cost_per_unit_series(frame["df"], spec.date_col, spec.market_col, market, config)
    except ValueError as e:
        st.warning(f"Could not compute a cost-per-unit history for {market} / {channel}: {e}")
        return

    trend = historical_cost_trend(cost_df, spec.date_col)
    if trend["avg_cost_per_unit"] is None:
        st.caption(f"No valid cost-per-unit observations for {market} / {channel} yet.")
        return

    unit_label = config.unit_type or "units"
    st.markdown(f"**Historical cost per {unit_label}**")
    c1, c2 = st.columns(2)
    c1.metric(f"Average cost per {unit_label}", f"{trend['avg_cost_per_unit']:,.2f}")
    c2.metric(
        "Year-on-year inflation",
        f"{trend['yoy_inflation_pct']:.1f}%" if trend["yoy_inflation_pct"] is not None else "n/a (< 2 years of data)",
    )
    st.dataframe(trend["indexed_trend"], width="stretch", column_config=dataframe_column_config(trend["indexed_trend"]))
    st.caption("`indexed` = cost per unit relative to the first year with data (100 = that year's average).")

    st.markdown(f"**Response-unit curve ({unit_label})**")
    ru_df = response_unit_curve(curve_df, trend["avg_cost_per_unit"])
    st.plotly_chart(
        create_response_curve(ru_df["media_units"].to_numpy(), ru_df["overall_response"].to_numpy(), f"{channel} ({unit_label})"),
        width="stretch",
    )
    st.caption(
        "Derived from the spend curve using the average historical cost per unit - a documented "
        "simplification (docs/media_units_and_inflation.md), not an independently observed "
        "spend-to-delivery relationship at every spend level."
    )

    st.markdown("**Equivalent delivery / response**")
    key_suffix = f"{market}_{channel}"
    c1, c2 = st.columns(2)
    with c1:
        st.caption(f"How much to spend to buy a target number of {unit_label}?")
        target_units = st.number_input(f"Target {unit_label}", min_value=0.0, value=100.0, key=f"target_units_{key_suffix}")
        future_cost = st.number_input(
            f"Assumed future cost per {unit_label}", min_value=0.0, value=float(trend["avg_cost_per_unit"]),
            key=f"future_cost_{key_suffix}",
        )
        st.metric("Required spend", f"{equivalent_delivery(target_units, future_cost):,.0f}")
    with c2:
        st.caption(f"What response would a target number of {unit_label} produce?")
        target_units2 = st.number_input(f"Target {unit_label} (response)", min_value=0.0, value=100.0, key=f"target_units2_{key_suffix}")
        cost_assumption = st.number_input(
            f"Cost per {unit_label} assumption", min_value=0.0, value=float(trend["avg_cost_per_unit"]),
            key=f"cost_assumption_{key_suffix}",
        )
        response = equivalent_response(target_units2, cost_assumption, curve_df)
        st.metric("Modelled response", f"{response:,.1f}")


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
market_config = MarketSpecConfig.from_dict(get_state("market_spec_config"))

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
    _render_curve_with_cpa(curve_df, f"{viewer_market} - {viewer_channel}")
    st.dataframe(curve_df, width="stretch", column_config=dataframe_column_config(curve_df))

    st.markdown("---")
    st.markdown("### Media units & inflation")
    _render_media_unit_section(curve_df, market_config, viewer_market, viewer_channel)

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
    dna_kit_segments_in_fit = [s for s in meta.direct_dna_segments if s != meta.dna_segment]
    fh_segments_in_fit = [s for s in meta.segments if s not in dna_kit_segments_in_fit]
    if dna_kit_segments_in_fit:
        st.caption(
            f"Total impact per FH channel across FH segments only ({', '.join(fh_segments_in_fit)}) - "
            f"DNA-product segments ({', '.join(dna_kit_segments_in_fit)}) are excluded from this total "
            "since a kit-sale count and a GSA count aren't the same unit; see their own rows in the "
            "segment x channel detail below."
        )
    else:
        st.caption("Total impact per channel across all segments, plus which segment that impact falls into and LTV-weighted value.")
    total_df = total_fh_contribution(frame, meta, params, contributions, ltv, segments=fh_segments_in_fit)
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
    st.markdown("### Channel curve viewer")
    st.caption(
        "Spend -> incremental response for one channel, per segment and overall (overall = sum of "
        "segment responses) - the same curve every market uses, since it's shared across markets in "
        "this model structure. Point estimates only (posterior means)."
    )
    viewer_channel = st.selectbox("Channel", meta.channels)
    curve_df = generate_channel_curve(viewer_channel, meta, params)
    _render_curve_with_cpa(curve_df, viewer_channel)
    st.dataframe(curve_df, width="stretch", column_config=dataframe_column_config(curve_df))

    st.markdown("---")
    st.markdown("### Media units & inflation")
    st.caption(
        "Cost-per-unit history is inherently market-specific, even though the curve above is shared "
        "across markets - choose a reference market to see its own cost data."
    )
    viewer_market = st.selectbox("Reference market (for cost data)", meta.markets)
    _render_media_unit_section(curve_df, market_config, viewer_market, viewer_channel)

    st.markdown("---")
    st.markdown("### DNA halo strength by segment")
    halo_df = pd.DataFrame([{"segment": s, "halo_strength": params.halo_strength.get(s)} for s in meta.segments])
    st.dataframe(halo_df, width="stretch", column_config=dataframe_column_config(halo_df))
    st.caption(
        f"DNA cross-sell segment ('{meta.dna_segment}') is fixed at 1.0 (full weight). "
        "Other segments' values are the estimated halo effect strength, shrunk toward zero by prior "
        "default and only pulled away from zero where the data supports it."
    )

# --- Curve bank: available for both model types - a market-
# specific fit saves one set of curves per market, each labelled with its
# own evidence tier (docs/market_hierarchy.md section 4); a shared-curve
# fit saves one set of curves labelled "Shared". Media-unit curve entries
# are only auto-saved for a market-specific fit - a shared
# curve's cost-per-unit context is inherently market-specific, so there's
# no single market to attribute it to at save time (see docs/decision_log.md);
# the viewer above still shows media-unit context for a chosen reference
# market, it just isn't persisted to the curve bank for a shared curve.
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
        "model_spec_fingerprint": fingerprint_model_spec(
            spec_dict, prior_config, dna_lag_weeks, model_type=model_type,
            pipeline_steps=get_state("pipeline_steps") or [], market_spec_config=get_state("market_spec_config"),
        ),
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
                currency_by_market = {
                    m: market_config.get_profile(m).currency.local_currency
                    for m in meta.markets if market_config.get_profile(m).currency.local_currency
                }
                entries = cb.make_entries(
                    meta, params, data_window, run_label, approval, model_type=model_type,
                    evidence_tiers=evidence_tiers, currency_by_market=currency_by_market,
                    notes=notes, **current_identity,
                )
                media_unit_info = {}
                for m in meta.markets:
                    for ch in meta.channels:
                        cfg = market_config.get_media_unit_config(m, ch)
                        if not (cfg and cfg.has_media_unit()):
                            continue
                        try:
                            cost_df = extract_cost_per_unit_series(frame["df"], spec.date_col, spec.market_col, m, cfg)
                            trend = historical_cost_trend(cost_df, spec.date_col)
                        except ValueError:
                            continue
                        if trend["avg_cost_per_unit"] is None:
                            continue
                        media_unit_info[(m, ch)] = {
                            "unit_type": cfg.unit_type,
                            "currency": cfg.currency or currency_by_market.get(m),
                            "avg_cost_per_unit": trend["avg_cost_per_unit"],
                        }
                if media_unit_info:
                    entries = entries + cb.make_media_unit_entries(entries, media_unit_info)
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
            "channel/segment - each was one shared, run-level record, expanded into this "
            "table's shape for display; their `curve_status` is always `Legacy`."
        )

    st.markdown("#### Log a geo-test / in-platform calibration result")
    entry_options = {
        f"{e.run_label} - {e.market or '(shared)'} / {e.channel} / {e.segment_or_overall} / {e.input_type} "
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
