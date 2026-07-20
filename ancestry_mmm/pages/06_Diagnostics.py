"""Page 6: model scorecard - convergence, in-sample fit, posterior predictive coverage, plausibility flags, out-of-sample backtest."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st
import pandas as pd

from ancestry_mmm.utils import init_session_state, get_state, set_state
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.diagnostics import compute_scorecard, expanding_window_backtest
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec, fingerprint_posterior
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu
from ancestry_mmm.data import prepare_fh_modeling_frame

st.set_page_config(page_title="Diagnostics - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("🩺 Diagnostics Scorecard")
st.caption("A scorecard, not a single headline R-squared - convergence, fit, posterior predictive coverage and plausibility flags together.")

trace = get_state("trace")
frame = get_state("frame")
meta = get_state("model_meta")
if trace is None or frame is None or meta is None:
    st.warning("Train a model first on **Model Training**.")
    st.stop()

if st.button("Compute scorecard", type="primary"):
    with st.spinner("Computing diagnostics..."):
        scorecard = compute_scorecard(trace, frame, meta)
    set_state("scorecard", scorecard)

scorecard = get_state("scorecard")
if scorecard:
    st.markdown("### Convergence")
    conv = scorecard["convergence"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Max R-hat", f"{conv['rhat_max']:.3f}", help="Should be < 1.01")
    c2.metric("Min ESS", f"{conv['ess_min']:.0f}", help="Effective sample size; higher is better")
    c3.metric("Divergences", conv["divergences"])
    c4.metric("Converged", "✅ Yes" if conv["converged"] else "⚠️ No")
    if not conv["converged"]:
        st.warning(
            "Convergence diagnostics are outside typical thresholds. Consider more draws/tune, "
            "a higher target_accept, or simplifying the hierarchy before trusting these results."
        )

    st.markdown("---")
    st.markdown("### In-sample fit")
    st.dataframe(pd.DataFrame(scorecard["in_sample_fit"]), width="stretch")

    st.markdown("---")
    st.markdown("### Posterior predictive coverage")
    st.caption("% of actual observations falling inside the posterior predictive credible interval - should be close to the target %.")
    st.dataframe(pd.DataFrame(scorecard["ppc_coverage"]), width="stretch")

    st.markdown("---")
    st.markdown("### Curve & ROI plausibility flags")
    flags = scorecard["plausibility_flags"]
    if not flags:
        st.info("No plausibility flags raised.")
    else:
        for f in flags:
            (st.warning if f["level"] == "warning" else st.error)(f"**{f.get('channel', '')}**: {f['message']}")

st.markdown("---")
st.markdown("### Model approval")
st.caption(
    "A high R-squared is not, by itself, a reason to accept a model. Approving here binds the "
    "approval to this exact fitted model (data, specification and posterior) - it's what "
    "authorises saving curves to the curve bank and using the Scenario Planner, and it stops "
    "being valid the moment any of those three things change."
)

posterior_params = get_state("posterior_params")
model_spec_dict = get_state("model_spec")
prior_config = get_state("prior_config") or {}
dna_lag_weeks = get_state("dna_lag_weeks", 4)
model_run_id = get_state("model_run_id")

current_identity = None
if model_run_id and posterior_params is not None and model_spec_dict is not None:
    current_identity = {
        "model_run_id": model_run_id,
        "data_fingerprint": fingerprint_dataframe(frame["df"]),
        "model_spec_fingerprint": fingerprint_model_spec(model_spec_dict, prior_config, dna_lag_weeks),
        "posterior_fingerprint": fingerprint_posterior(posterior_params),
    }

approval_dict = get_state("model_approval")
approval_matches_current = (
    approval_dict is not None
    and current_identity is not None
    and ModelApproval.from_dict(approval_dict).matches_current_model(**current_identity)
)

if approval_dict and not approval_matches_current:
    st.warning(
        "An approval exists in this session, but it no longer matches the current model "
        "(it was granted for a different run, or the data/specification/posterior have "
        "changed since) - it has been invalidated. Review and approve again below."
    )
    set_state("model_approval", None)
    approval_dict = None

if approval_dict:
    approved_at = pd.Timestamp.fromtimestamp(approval_dict["approved_at"])
    st.success(f"Approved by **{approval_dict['approved_by']}** on {approved_at:%Y-%m-%d %H:%M}.")
    with st.expander("Approval details"):
        st.write(f"**Model run:** `{approval_dict.get('model_run_id', '')[:8]}`")
        st.write(f"**Data fingerprint:** `{approval_dict.get('data_fingerprint', '')[:12]}`")
        st.write(f"**Spec fingerprint:** `{approval_dict.get('model_spec_fingerprint', '')[:12]}`")
        st.write(f"**Posterior fingerprint:** `{approval_dict.get('posterior_fingerprint', '')[:12]}`")
        st.write(f"**Notes:** {approval_dict.get('notes') or '(none)'}")
        st.write(f"**Known limitations:** {approval_dict.get('known_limitations') or '(none)'}")
        st.write(f"**Diagnostics reviewed:** {', '.join(approval_dict.get('diagnostics_accepted', [])) or '(none recorded)'}")
    if st.button("Revoke approval"):
        set_state("model_approval", None)
        st.rerun()
elif not scorecard:
    st.info("Compute the scorecard above before approving this model.")
elif current_identity is None:
    st.warning(
        "Can't approve yet: the current model run's identity (run ID, data/specification/"
        "posterior fingerprints) isn't fully available. This shouldn't normally happen once "
        "a model has trained - try recomputing the scorecard, or retrain if the problem persists."
    )
else:
    with st.form("approve_model_form"):
        approved_by = st.text_input("Approved by (name)")
        diagnostics_accepted = st.multiselect(
            "Diagnostics reviewed before approving",
            ["convergence", "in_sample_fit", "ppc_coverage", "plausibility_flags", "backtest"],
            default=["convergence", "in_sample_fit", "ppc_coverage", "plausibility_flags"],
        )
        notes = st.text_area("Notes")
        known_limitations = st.text_area("Known limitations")
        st.caption(
            f"Binding to model run `{current_identity['model_run_id'][:8]}` "
            f"(data `{current_identity['data_fingerprint'][:8]}`, "
            f"spec `{current_identity['model_spec_fingerprint'][:8]}`, "
            f"posterior `{current_identity['posterior_fingerprint'][:8]}`) - identifiers are "
            "captured automatically, not entered by hand."
        )
        submitted = st.form_submit_button("Approve this model for planning", type="primary")
        if submitted:
            if not approved_by.strip():
                st.error("Enter a name before approving.")
            else:
                approval = ModelApproval(
                    approved_by=approved_by.strip(),
                    notes=notes,
                    known_limitations=known_limitations,
                    diagnostics_accepted=diagnostics_accepted,
                    **current_identity,
                )
                set_state("model_approval", approval.to_dict())
                st.success(f"Model approved by {approved_by.strip()}.")
                st.rerun()

st.markdown("---")
st.markdown("### Out-of-sample accuracy (expanding-window backtest)")
st.caption(
    "Each fold refits the full model on an expanding training window and evaluates the next "
    "held-out block - this can take a while (it's a real fit per fold). Use a reduced draws/tune "
    "budget for a quicker check."
)

c1, c2, c3 = st.columns(3)
n_folds = c1.number_input("Folds", min_value=1, max_value=5, value=1)
min_train_frac = c2.slider("Min training fraction", 0.4, 0.9, 0.7, 0.05)
fold_draws = c3.number_input("Draws per fold (reduced for speed)", min_value=200, max_value=3000, value=500, step=100)

if st.button("Run backtest"):
    spec = ModelSpec.from_dict(get_state("model_spec"))
    df = get_state("transformed_data")
    prior_config = get_state("prior_config")
    dna_lag_weeks = get_state("dna_lag_weeks", 4)

    def fit_fold(train_df, test_df):
        train_frame = prepare_fh_modeling_frame(train_df, spec)
        fold_model, fold_meta = build_fh_hierarchical_model(train_frame, spec, dna_lag_weeks=dna_lag_weeks, prior_config=prior_config)
        fold_trace = fit_model(fold_model, draws=int(fold_draws), tune=int(fold_draws), chains=2, cores=1, target_accept=0.9)
        fold_params = extract_posterior_params(fold_trace, fold_meta)

        test_frame = prepare_fh_modeling_frame(test_df, spec)
        mu_test = predict_mu(test_frame, fold_meta, fold_params)

        r2_by_seg, mape_by_seg = {}, {}
        for i, seg in enumerate(fold_meta.segments):
            actual, pred = test_frame["Y"][:, i], mu_test[:, i]
            ss_res = ((actual - pred) ** 2).sum()
            ss_tot = ((actual - actual.mean()) ** 2).sum()
            r2_by_seg[seg] = float(1 - ss_res / ss_tot) if ss_tot > 0 else float("nan")
            mask = actual != 0
            mape_by_seg[seg] = float((abs((actual[mask] - pred[mask]) / actual[mask])).mean() * 100) if mask.any() else float("nan")
        return r2_by_seg, mape_by_seg

    with st.spinner(f"Running {n_folds}-fold backtest (this refits the model per fold)..."):
        results = expanding_window_backtest(df, spec, fit_fold, n_folds=int(n_folds), min_train_frac=min_train_frac)
    set_state("backtest_results", results)
    st.success("Backtest complete.")

backtest_results = get_state("backtest_results")
if backtest_results is not None and not backtest_results.empty:
    st.dataframe(backtest_results, width="stretch")

st.markdown("---")
if st.button("Continue to Results & Curve Bank →", type="primary"):
    st.switch_page("pages/07_Results_Curve_Bank.py")
