"""Page 5: build and fit the joint hierarchical FH model, with a live progress indicator."""

import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import streamlit as st

from ancestry_mmm.utils import init_session_state, get_state, set_state
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import extract_posterior_params

st.set_page_config(page_title="Model Training - Ancestry FH MMM", page_icon="🧬", layout="wide")
init_session_state()

st.title("🚀 Model Training")

frame = get_state("frame")
spec_dict = get_state("model_spec")
if frame is None or not spec_dict:
    st.warning("Prepare the modelling frame first on **Model Configuration**.")
    st.stop()

spec = ModelSpec.from_dict(spec_dict)

st.markdown(f"""
- **Observations:** {frame['X_media'].shape[0]}
- **Markets:** {', '.join(frame['markets'])}
- **Segments:** {', '.join(frame['segments'])}
- **Channels:** {', '.join(frame['channels'])} (DNA: {', '.join(frame['channels'][i] for i in frame['dna_channel_idx']) or 'none'})
- **MCMC:** {get_state('mcmc_draws')} draws, {get_state('mcmc_tune')} tune, {get_state('mcmc_chains')} chains
""")

st.info(
    "Model training runs sequentially (one core) here so progress can be shown live in the UI. "
    "A full run with several thousand draws can take from a few minutes to significantly longer "
    "depending on data size and hardware - this does not block the rest of the app once started."
)

if st.button("Build & fit model", type="primary"):
    prior_config = get_state("prior_config")
    dna_lag_weeks = get_state("dna_lag_weeks", 4)

    with st.spinner("Building model..."):
        model, meta = build_fh_hierarchical_model(frame, spec, dna_lag_weeks=dna_lag_weeks, prior_config=prior_config)
    st.success("Model built.")

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
        status.caption(f"Sampling: {progress_state['done']} / {progress_state['total']} draws")
        time.sleep(0.5)
    thread.join()
    progress_bar.progress(1.0)

    if progress_state["error"]:
        st.error(f"Sampling failed: {progress_state['error']}")
    else:
        trace = progress_state["trace"]
        set_state("model", model)
        set_state("model_meta", meta)
        set_state("trace", trace)
        set_state("model_trained", True)
        set_state("posterior_params", extract_posterior_params(trace, meta))
        # A fresh fit is a new model run, full stop - mint a new identity and
        # drop any approval that was sitting in session state, even if this
        # is a re-run of the same spec on the same data (retraining always
        # invalidates the previous approval; clear_model_state() covers the
        # "upstream config changed" path, this covers "user just refit").
        set_state("model_run_id", str(uuid.uuid4()))
        set_state("model_approval", None)
        st.success("Model trained.")

if get_state("model_trained"):
    st.markdown("---")
    st.success("A trained model is available.")
    if st.button("Continue to Diagnostics Scorecard →", type="primary"):
        st.switch_page("pages/06_Diagnostics.py")
