"""Page 5: build and fit the joint hierarchical FH model, with a live progress indicator."""

import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state, format_number
from ancestry_mmm.components import apply_theme, render_sidebar, render_page_header, render_next_step, render_empty_state
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.market_specific_predict import extract_market_specific_posterior_params
from ancestry_mmm.core.model_comparison import ModelComparisonCandidate
from ancestry_mmm.core.market_specific_diagnostics import compute_scorecard_market_specific
from ancestry_mmm.core.diagnostics import compute_scorecard

MODEL_TYPE_LABELS = {"shared": "Model A - shared curve", "market_specific": "Model C - market-specific, partially pooled"}

st.set_page_config(page_title="Model Training - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()
apply_theme()
render_sidebar("model_training")
render_page_header("model_training")

frame = get_state("frame")
spec_dict = get_state("model_spec")
if frame is None or not spec_dict:
    st.markdown("---")
    render_empty_state(
        "No modelling frame ready yet. Complete Model Configuration first.",
        button_label="Go to Model Configuration", target_key="model_config",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
model_type = get_state("model_type", "shared")
if model_type == "market_specific" and len(frame["markets"]) < 2:
    st.warning(
        "This project has only 1 market, so market-specific curves aren't available - fitting the "
        "shared-curve model (Model A) instead. Change this on Model Configuration for future fits."
    )
    model_type = "shared"

dna_kit_outcome_ids = get_state("direct_dna_outcome_ids") or []

st.markdown("---")
st.markdown(f"""
- **Model structure:** {MODEL_TYPE_LABELS[model_type]}
- **Observations:** {format_number(frame['X_media'].shape[0])}
- **Markets:** {', '.join(frame['markets'])}
- **Outcomes:** {', '.join(frame['outcome_ids'])}{f" (DNA-product, direct media response: {', '.join(dna_kit_outcome_ids)})" if dna_kit_outcome_ids else ""}
- **Channels:** {', '.join(frame['channels'])} (DNA: {', '.join(frame['channels'][i] for i in frame['dna_channel_idx']) or 'none'})
- **MCMC:** {format_number(get_state('mcmc_draws'))} draws, {format_number(get_state('mcmc_tune'))} tune, {get_state('mcmc_chains')} chains
""")

st.info(
    "Model training runs sequentially (one core) here so progress can be shown live in the UI. "
    "A full run with several thousand draws can take from a few minutes to significantly longer "
    "depending on data size and hardware - this does not block the rest of the app once started."
)

if st.button("Build & fit model", type="primary"):
    prior_config = get_state("prior_config")
    dna_lag_weeks = get_state("dna_lag_weeks", 4)
    direct_dna_outcome_ids = get_state("direct_dna_outcome_ids") or None

    try:
        with st.spinner("Building model..."):
            if model_type == "market_specific":
                model, meta = build_fh_market_specific_model(
                    frame, spec, dna_lag_weeks=dna_lag_weeks, prior_config=prior_config,
                    dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                    direct_dna_outcome_ids=direct_dna_outcome_ids,
                )
            else:
                model, meta = build_fh_hierarchical_model(
                    frame, spec, dna_lag_weeks=dna_lag_weeks, prior_config=prior_config,
                    dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
                    direct_dna_outcome_ids=direct_dna_outcome_ids,
                )
    except ValueError as e:
        st.error(f"Could not build the model: {e} Set the FH DNA cross-sell outcome on the Structure page if needed, and try again.")
        st.stop()
    st.success(f"Model built ({MODEL_TYPE_LABELS[model_type]}).")

    # Read MCMC settings on the main thread: st.session_state (get_state) is
    # bound to Streamlit's script-run context, which a plain background
    # thread doesn't have - calling get_state() from inside _run() silently
    # returns None instead of the real value.
    mcmc_draws = get_state("mcmc_draws")
    mcmc_tune = get_state("mcmc_tune")
    mcmc_chains = get_state("mcmc_chains")
    mcmc_target_accept = get_state("mcmc_target_accept")

    progress_state = {"done": 0, "total": 1, "error": None, "trace": None}

    def _run():
        try:
            trace = fit_model(
                model,
                draws=mcmc_draws,
                tune=mcmc_tune,
                chains=mcmc_chains,
                target_accept=mcmc_target_accept,
                progress_callback=lambda done, total: progress_state.update(done=done, total=total),
                cores=1,
            )
            progress_state["trace"] = trace
        except Exception as e:  # surfaced in the UI, not swallowed
            progress_state["error"] = str(e)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    progress_bar = st.progress(0.0)
    status = st.empty()
    while thread.is_alive():
        frac = min(1.0, progress_state["done"] / max(progress_state["total"], 1))
        progress_bar.progress(frac)
        status.caption(f"Sampling: {format_number(progress_state['done'])} / {format_number(progress_state['total'])} draws")
        time.sleep(0.5)
    thread.join()
    progress_bar.progress(1.0)

    if progress_state["error"]:
        st.error(f"Sampling failed: {progress_state['error']} Try fewer draws/chains, or simplify the hierarchy, and fit again.")
    else:
        trace = progress_state["trace"]
        posterior_params = (
            extract_market_specific_posterior_params(trace, meta) if model_type == "market_specific"
            else extract_posterior_params(trace, meta)
        )
        set_state("model", model)
        set_state("model_meta", meta)
        set_state("trace", trace)
        set_state("model_trained", True)
        set_state("posterior_params", posterior_params)
        set_state("model_type", model_type)
        # A fresh fit is a new model run, full stop - mint a new identity and
        # drop any approval that was sitting in session state, even if this
        # is a re-run of the same spec on the same data (retraining always
        # invalidates the previous approval; clear_model_state() covers the
        # "upstream config changed" path, this covers "user just refit").
        set_state("model_run_id", str(uuid.uuid4()))
        set_state("model_approval", None)
        st.success(f"Model trained ({MODEL_TYPE_LABELS[model_type]}).")

if get_state("model_trained"):
    st.markdown("---")
    st.markdown("### Save as a comparison candidate")
    st.caption(
        "Optional: record this fit's scorecard so it can be compared side by side with other "
        "candidates (a different model structure, or the same structure on a different market "
        "selection) on Compare Models."
    )
    candidate_label = st.text_input(
        "Candidate label", value=f"{MODEL_TYPE_LABELS[get_state('model_type')]} - {', '.join(frame['markets'])}",
    )
    if st.button("Save this fit as a comparison candidate"):
        trace = get_state("trace")
        current_meta = get_state("model_meta")
        current_type = get_state("model_type")
        with st.spinner("Computing scorecard for comparison..."):
            scorecard = (
                compute_scorecard_market_specific(trace, frame, current_meta) if current_type == "market_specific"
                else compute_scorecard(trace, frame, current_meta)
            )
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="C" if current_type == "market_specific" else "A",
            label=candidate_label, model_run_id=get_state("model_run_id"), fitted_at=time.time(),
            scorecard=scorecard, market=frame["markets"][0] if len(frame["markets"]) == 1 else None,
        )
        candidates = get_state("model_comparison_candidates") or []
        candidates.append(candidate.to_dict())
        set_state("model_comparison_candidates", candidates)
        st.success(f"Saved '{candidate_label}' as a comparison candidate.")

    render_next_step("model_training")
