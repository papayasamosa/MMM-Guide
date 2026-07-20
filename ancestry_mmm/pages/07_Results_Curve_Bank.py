"""Page 7: segment + total-FH contributions, ROAS/CPA, LTV-weighted value, and the versioned curve bank."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import init_session_state, get_state, set_state, curve_bank_dir
from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec, fingerprint_posterior
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.attribution import (
    compute_shapley_contributions, segment_channel_summary, total_fh_contribution, contribution_waterfall,
)
from ancestry_mmm.core import curve_bank as cb
from ancestry_mmm.components.charts import create_waterfall_chart, create_bar_chart_with_ci

st.set_page_config(page_title="Results & Curve Bank - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("📈 Results & Curve Bank")

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
params = get_state("posterior_params")
spec_dict = get_state("model_spec")
if trace is None or frame is None or meta is None or params is None:
    st.warning("Train a model first on **Model Training**.")
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
ltv = spec.segment_ltv

with st.spinner("Computing Shapley contributions..."):
    contributions = compute_shapley_contributions(frame, meta, params, n_permutations=100)

st.markdown("### Total-FH contribution by channel")
st.caption("Total impact per channel across all segments, plus which segment that impact falls into and LTV-weighted value.")
total_df = total_fh_contribution(frame, meta, params, contributions, ltv)
st.dataframe(total_df, width="stretch")

st.markdown("---")
st.markdown("### Segment x channel detail")
seg_df = segment_channel_summary(frame, meta, params, contributions, ltv)
st.dataframe(seg_df, width="stretch")

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
st.dataframe(halo_df, width="stretch")
st.caption(
    f"DNA cross-sell segment ('{meta.dna_segment}') is fixed at 1.0 (full weight). "
    "Other segments' values are the estimated halo effect strength, shrunk toward zero by prior "
    "default and only pulled away from zero where the data supports it."
)

st.markdown("---")
st.markdown("## Curve bank")
st.caption(
    "Every model run's shared curves and segment parameters can be saved as a versioned entry, "
    "traceable to the run, data window and (once logged) any geo/in-platform test calibration."
)

approval_dict = get_state("model_approval")
model_run_id = get_state("model_run_id")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)

current_identity = None
if model_run_id and spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(spec_dict, prior_config, dna_lag_weeks),
        "posterior_fingerprint": fingerprint_posterior(params),
    }

approval_matches_current = (
    approval_dict is not None
    and current_identity is not None
    and ModelApproval.from_dict(approval_dict).matches_current_model(**current_identity)
)

if not approval_dict:
    st.warning(
        "This model hasn't been approved yet. Results above are still visible for review, but "
        "saving to the curve bank is blocked until you approve it on the **Diagnostics Scorecard** "
        "page - only an approved model may populate the curve bank."
    )
elif not approval_matches_current:
    st.warning(
        "This model's approval no longer matches the current fitted model (the data, "
        "specification, posterior, or run have changed since it was approved) - saving to the "
        "curve bank is blocked until it's reviewed and approved again on the "
        "**Diagnostics Scorecard** page."
    )
else:
    approval = ModelApproval.from_dict(approval_dict)
    st.caption(f"Model approved by **{approval.approved_by}** - saving to the curve bank will record this approval on the entry.")

    c1, c2 = st.columns(2)
    run_label = c1.text_input("Run label", value=f"{spec.markets and spec.markets[0] or 'run'}-v1")
    notes = c2.text_input("Notes (optional)")

    if st.button("Save current curves to curve bank", type="primary"):
        data_window = (str(pd.Timestamp(frame["dates"].min()).date()), str(pd.Timestamp(frame["dates"].max()).date()))
        try:
            entry = cb.make_entry(meta, params, data_window, run_label, approval, notes=notes, **current_identity)
        except ApprovalMismatchError as e:
            st.error(f"Could not save to the curve bank: {e}")
        else:
            path = cb.save_entry(curve_bank_dir(), entry)
            set_state("curve_bank_entry_id", entry.entry_id)
            st.success(f"Saved curve bank entry {entry.entry_id[:8]} to {path}")

entries = cb.load_all_entries(curve_bank_dir())
if entries:
    st.markdown("#### Curve bank history")
    entries_df = cb.entries_to_dataframe(entries)
    st.dataframe(entries_df, width="stretch")
    if entries_df["legacy_approval"].any():
        st.caption(
            "⚠️ Rows marked `legacy_approval = True` were saved before curve bank entries were "
            "bound to a verified model run - their approval could not be checked against a "
            "specific fitted model."
        )

    st.markdown("#### Log a geo-test / in-platform calibration result")
    entry_options = {f"{e.run_label} ({e.entry_id[:8]}, {pd.Timestamp.fromtimestamp(e.created_at).date()})": e.entry_id for e in entries}
    chosen_label = st.selectbox("Curve bank entry", list(entry_options.keys()))
    chosen_entry = next(e for e in entries if e.entry_id == entry_options[chosen_label])

    c1, c2, c3 = st.columns(3)
    channel = c1.selectbox("Channel", chosen_entry.channels)
    segment = c2.selectbox("Segment", chosen_entry.segments)
    test_type = c3.selectbox("Test type", ["geo", "in_platform"])
    c1, c2, c3 = st.columns(3)
    model_estimate = c1.number_input("Model estimate (e.g. ROAS)", value=float(chosen_entry.beta.get(segment, {}).get(channel, 0.0)))
    test_estimate = c2.number_input("Test estimate", value=0.0)
    tolerance = c3.slider("Agreement tolerance (%)", 5, 100, 25)

    if st.button("Log calibration result"):
        record = cb.record_calibration(
            curve_bank_dir(), chosen_entry.entry_id, channel, segment, test_type,
            model_estimate, test_estimate, tolerance_pct=tolerance,
        )
        st.success(f"Logged calibration result: **{record.agreement}**")

    calibrations = cb.load_all_calibrations(curve_bank_dir())
    if calibrations:
        st.markdown("#### Calibration history")
        st.dataframe(cb.calibrations_to_dataframe(calibrations), width="stretch")
else:
    st.info("No curve bank entries saved yet.")

st.markdown("---")
if st.button("Continue to Scenario Planner →", type="primary"):
    st.switch_page("pages/08_Scenario_Planner.py")
