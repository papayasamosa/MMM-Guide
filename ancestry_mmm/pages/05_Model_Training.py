"""Page 5: build and fit the joint hierarchical FH model, with a live progress indicator."""

import sys
import threading
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    format_number,
    dataframe_column_config,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_empty_state,
    render_drift_status,
    render_workspace_note,
    SectionCard,
    InfoPanel,
    render_status_badge,
)
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.causal_graph import GRAPH_STATUS_APPROVED, CausalGraph
from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.market_specific_predict import (
    extract_market_specific_posterior_params,
)
from ancestry_mmm.core.model_comparison import ModelComparisonCandidate
from ancestry_mmm.core.market_specific_diagnostics import (
    compute_scorecard_market_specific,
)
from ancestry_mmm.core.diagnostics import compute_scorecard, prior_predictive_summary
from ancestry_mmm.core.fingerprint import fingerprint_dataframe, fingerprint_model_spec
from ancestry_mmm.core.outcomes import outcome_catalogue_fingerprint_payload
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.activities import activity_fit_fingerprint
from ancestry_mmm.core.search_objects import search_object_fit_fingerprint
from ancestry_mmm.core.coverage import VariableCoverageMatrix

MODEL_TYPE_LABELS = {
    "shared": "Model A - shared curve",
    "market_specific": "Model C - market-specific, partially pooled",
}

st.set_page_config(
    page_title="Model Training | Ancestry Family History & DNA MMM",
    page_icon="🧬",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("model_training")
render_page_header(
    "model_training",
    task_prompt="Is the prepared frame ready for an honest fit?",
)
render_workspace_note(
    "Proposed fit",
    "The prepared frame is read-only here; fitting creates the posterior evidence reviewed in Diagnostics.",
    kind="derived",
)

frame = get_state("frame")
spec_dict = get_state("model_spec")
if frame is None or not spec_dict:
    render_empty_state(
        "No modelling frame ready yet. Complete Model Configuration first.",
        button_label="Go to Model Configuration",
        target_key="model_config",
    )
    st.stop()

spec = ModelSpec.from_dict(spec_dict)
if get_state("model_meta") is not None:
    render_drift_status(frame.get("outcomes") or [], get_state("model_meta"))
model_type = get_state("model_type", "shared")
if model_type == "market_specific" and len(frame["markets"]) < 2:
    st.warning(
        "This project has only 1 market, so market-specific curves aren't available - fitting the "
        "shared-curve model (Model A) instead. Change this on Model Configuration for future fits."
    )
    model_type = "shared"

dna_kit_outcome_ids = get_state("direct_dna_outcome_ids") or []

with SectionCard(
    "Proposed model",
    description="What would be built and fit if you click 'Build & fit model' below.",
):
    st.markdown(f"""
- **Model structure:** {MODEL_TYPE_LABELS[model_type]}
- **Observations:** {format_number(frame["X_media"].shape[0])}
- **Markets:** {", ".join(frame["markets"])}
- **Segments / outcomes:** {", ".join(frame["outcome_ids"])}{f" (DNA-product, direct media response: {', '.join(dna_kit_outcome_ids)})" if dna_kit_outcome_ids else ""}
- **Channels:** {", ".join(frame["channels"])} (DNA: {", ".join(frame["channels"][i] for i in frame["dna_channel_idx"]) or "none"})
""")

with InfoPanel(
    "Resource expectations",
    description="Sequential (single-core) sampling so live progress can be shown honestly below.",
):
    st.markdown(f"""
- **MCMC draws:** {format_number(get_state("mcmc_draws"))}
- **Tune steps:** {format_number(get_state("mcmc_tune"))}
- **Chains:** {get_state("mcmc_chains")}
""")
    st.caption(
        "A full run with several thousand draws can take from a few minutes to significantly "
        "longer depending on data size and hardware - this does not block the rest of the app "
        "once started."
    )


def _resolve_causal_graph():
    # REQ-GRAPH-001 work package D/E: an approved causal graph, when one
    # exists for this project, is the sole authoritative structural input -
    # resolve_pathway_masks_preferring_graph (inside both builders below)
    # ignores the raw MediaOutcomePathway catalogue entirely once this is
    # supplied. None (every project without a graph, or with only a draft
    # graph) reproduces exactly today's pathway-catalogue-driven behaviour.
    causal_graph_dict = get_state("causal_graph")
    if causal_graph_dict and causal_graph_dict.get("status") == GRAPH_STATUS_APPROVED:
        return CausalGraph.from_dict(causal_graph_dict)
    return None


def _build_proposed_model(build_model_type: str):
    """Build the unfit `(model, meta)` for the CURRENT proposed
    configuration (live `model_spec`/`prior_config`/`dna_lag_weeks`/causal
    graph) - the exact same builder call "Build & fit model" below uses,
    just never followed by `fit_model`. Shared by the pre-fit prior
    predictive preview and the real fit so they can never silently diverge
    on what "the proposed model" means."""
    prior_config = get_state("prior_config")
    dna_lag_weeks = get_state("dna_lag_weeks", 4)
    direct_dna_outcome_ids = get_state("direct_dna_outcome_ids") or None
    causal_graph = _resolve_causal_graph()
    builder = (
        build_fh_market_specific_model
        if build_model_type == "market_specific"
        else build_fh_hierarchical_model
    )
    return builder(
        frame,
        spec,
        dna_lag_weeks=dna_lag_weeks,
        prior_config=prior_config,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=causal_graph,
    )


def _proposed_model_fingerprint(fingerprint_model_type: str) -> str:
    """The pre-fit analogue of `06_Diagnostics.py`'s `ModelIdentity`
    construction - the same `fingerprint_model_spec` call it uses for
    `model_spec_fingerprint`, fed with exactly the values a build right now
    would use (read directly from live session state and `frame`'s own
    snapshotted `outcomes`/`media_outcome_pathways` -
    `core.hierarchical_model.build_fh_hierarchical_model` derives
    `outcome_catalogue_at_fit`/`pathway_catalogue_at_fit` from those exact
    frame keys, never from live `get_state` directly), combined with
    `fingerprint_dataframe(frame["df"])` - the same `data_fingerprint`
    component `ModelIdentity` binds separately alongside `model_spec_
    fingerprint`. Both matter here: the builders derive the default
    intercept prior from `Y`, and the sampled prior predictive distribution
    depends on the frame's media/controls too, so a spec/prior match alone
    is not enough to certify this preview still describes the current
    proposal - a re-uploaded or re-transformed dataset with an unchanged
    spec must also mark a previous preview stale. Cheap to recompute on
    every rerun (hashing only, no PyMC model build) purely to detect
    whether the proposal has since changed."""
    causal_graph = _resolve_causal_graph()
    activity_definitions = get_state("activity_definitions") or []
    search_objects = get_state("search_objects") or []
    coverage_matrix_dict = get_state("variable_coverage_matrix")
    model_spec_fingerprint = fingerprint_model_spec(
        spec_dict,
        get_state("prior_config") or {},
        int(get_state("dna_lag_weeks", 4)),
        model_type=fingerprint_model_type,
        pipeline_steps=get_state("pipeline_steps") or [],
        market_spec_config=get_state("market_spec_config"),
        direct_dna_outcome_ids=get_state("direct_dna_outcome_ids") or None,
        outcome_catalogue=outcome_catalogue_fingerprint_payload(
            frame.get("outcomes") or []
        ),
        funnel_links=get_state("funnel_links"),
        media_outcome_pathways=pathway_catalogue_fingerprint_payload(
            frame.get("media_outcome_pathways") or []
        ),
        activity_fit_fingerprint=(
            activity_fit_fingerprint(activity_definitions)
            if activity_definitions
            else None
        ),
        causal_graph_structural_fingerprint=(
            causal_graph.structural_fingerprint() if causal_graph is not None else ""
        ),
        search_object_fit_fingerprint=(
            search_object_fit_fingerprint(
                search_objects, consumed_model_input_columns=spec.channels
            )
            if search_objects
            else None
        ),
        variable_coverage_fingerprint=(
            VariableCoverageMatrix.from_dict(coverage_matrix_dict).fingerprint()
            if coverage_matrix_dict
            else None
        ),
    )
    return f"{fingerprint_dataframe(frame['df'])}:{model_spec_fingerprint}"


st.markdown("---")
st.markdown("### Preview: prior predictive check (before fitting)")
st.caption(
    "Samples from the PROPOSED model's declared priors - never a "
    "posterior, no MCMC, no trace - before committing to the fit below, "
    "reusing REQ-VAL-001's prior-predictive sampling function in a new "
    "pre-fit context. Builds the model from the current spec/prior "
    "configuration exactly as 'Build & fit model' would, but stops after "
    "sampling priors; this preview is never written as this project's "
    "official fit-time evidence (see Diagnostics' own 'Prior predictive "
    "check', computed against the actual fitted model, for that) and is "
    "not itself an approved REQ-VAL-001 work package."
)
preview_col1, preview_col2 = st.columns(2)
preview_n_samples = preview_col1.number_input(
    "Prior draws",
    min_value=50,
    max_value=5000,
    value=500,
    step=50,
    key="preview_prior_predictive_n_samples",
)
preview_seed = preview_col2.number_input(
    "Random seed",
    min_value=0,
    max_value=2**31 - 1,
    value=42,
    step=1,
    key="preview_prior_predictive_seed",
)
if st.button("Preview prior predictive (no fitting)"):
    try:
        with st.spinner("Building proposed model..."):
            preview_model, preview_meta = _build_proposed_model(model_type)
    except ValueError as e:
        set_state(
            "prior_predictive_preview",
            {
                "status": "failed",
                "error": f"Could not build the proposed model: {e} Set the FH DNA cross-sell outcome on the Structure page if needed, and try again.",
            },
        )
    else:
        try:
            with st.spinner("Sampling priors..."):
                preview_result = prior_predictive_summary(
                    preview_model,
                    frame,
                    preview_meta,
                    n_samples=int(preview_n_samples),
                    random_seed=int(preview_seed),
                )
        except Exception as e:
            set_state(
                "prior_predictive_preview",
                {
                    "status": "failed",
                    "error": f"Prior predictive sampling failed: {e}",
                },
            )
        else:
            set_state(
                "prior_predictive_preview",
                {
                    "status": "computed",
                    "model_type": model_type,
                    "payload": preview_result,
                    "proposed_model_fingerprint": _proposed_model_fingerprint(
                        model_type
                    ),
                },
            )

_preview = get_state("prior_predictive_preview")
# Prior-predictive preview status badge - reuses the exact same staleness
# signal the warning/detail below already computed (proposed_model_
# fingerprint vs. _proposed_model_fingerprint(model_type)); no new
# staleness check is invented here.
if not _preview:
    render_status_badge("not_configured", label="Preview: not yet run")
elif _preview.get("status") == "failed":
    render_status_badge("failed", label="Preview: failed")
elif _preview.get("proposed_model_fingerprint") != _proposed_model_fingerprint(
    model_type
):
    render_status_badge("stale", label="Preview: stale")
else:
    render_status_badge("validated", label="Preview: current")

if _preview and _preview.get("status") == "failed":
    st.error(_preview["error"])
elif _preview and _preview.get("status") == "computed":
    if _preview.get("proposed_model_fingerprint") != _proposed_model_fingerprint(
        model_type
    ):
        st.warning(
            "This preview no longer reflects the current proposed "
            "configuration - the spec, priors, DNA lag, causal graph, or "
            "another model-identity input changed since it was run. "
            "Re-run the preview above to see priors for what would "
            "actually be fit now."
        )
    else:
        _preview_payload = _preview["payload"]
        st.caption(
            f"Model type: {MODEL_TYPE_LABELS.get(_preview['model_type'], _preview['model_type'])} | "
            f"Prior draws: {format_number(_preview_payload.get('n_samples'))} | "
            f"Seed: {_preview_payload.get('random_seed')}"
        )
        _preview_df = pd.DataFrame(_preview_payload["rows"])
        st.dataframe(
            _preview_df,
            width="stretch",
            column_config=dataframe_column_config(_preview_df),
        )
        for w in _preview_payload.get("warnings", []):
            st.caption(f"Sampling warning: {w}")

if st.button("Build & fit model", type="primary"):
    try:
        with st.spinner("Building model..."):
            model, meta = _build_proposed_model(model_type)
    except ValueError as e:
        st.error(
            f"Could not build the model: {e} Set the FH DNA cross-sell outcome on the Structure page if needed, and try again."
        )
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
                progress_callback=lambda done, total: progress_state.update(
                    done=done, total=total
                ),
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
        status.caption(
            f"Sampling: {format_number(progress_state['done'])} / {format_number(progress_state['total'])} draws"
        )
        time.sleep(0.5)
    thread.join()
    progress_bar.progress(1.0)

    if progress_state["error"]:
        st.error(
            f"Sampling failed: {progress_state['error']} Try fewer draws/chains, or simplify the hierarchy, and fit again."
        )
    else:
        trace = progress_state["trace"]
        posterior_params = (
            extract_market_specific_posterior_params(trace, meta)
            if model_type == "market_specific"
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
        migration_review = get_state("migration_review")
        if (
            isinstance(migration_review, dict)
            and migration_review.get("migration_review_status")
            == "reviewed_refit_required"
        ):
            migration_review = dict(migration_review)
            migration_review.update(
                migration_review_status="refit_completed",
                replacement_model_run_id=get_state("model_run_id"),
            )
            set_state("migration_review", migration_review)
        st.success(f"Model trained ({MODEL_TYPE_LABELS[model_type]}).")

if get_state("model_trained"):
    st.markdown("---")
    with SectionCard(
        "Completed fit",
        description="The identity of the model run currently in session.",
    ):
        render_status_badge("validated", label="Trained")
        _completed_run_id = get_state("model_run_id") or ""
        st.markdown(f"""
- **Model run:** `{_completed_run_id[:8] if _completed_run_id else "(unknown)"}`
- **Model structure:** {MODEL_TYPE_LABELS[get_state("model_type")]}
- **MCMC:** {format_number(get_state("mcmc_draws"))} draws, {format_number(get_state("mcmc_tune"))} tune, {get_state("mcmc_chains")} chains
- **Approval status:** {"Approved" if get_state("model_approval") else "Not yet approved"}
""")

    st.markdown("### Save as a comparison candidate")
    st.caption(
        "Optional: record this fit's scorecard so it can be compared side by side with other "
        "candidates (a different model structure, or the same structure on a different market "
        "selection) on Compare Models."
    )
    candidate_label = st.text_input(
        "Candidate label",
        value=f"{MODEL_TYPE_LABELS[get_state('model_type')]} - {', '.join(frame['markets'])}",
    )
    if st.button("Save this fit as a comparison candidate"):
        trace = get_state("trace")
        current_meta = get_state("model_meta")
        current_type = get_state("model_type")
        with st.spinner("Computing scorecard for comparison..."):
            scorecard = (
                compute_scorecard_market_specific(trace, frame, current_meta)
                if current_type == "market_specific"
                else compute_scorecard(trace, frame, current_meta)
            )
        candidate = ModelComparisonCandidate.from_scorecard(
            model_type="C" if current_type == "market_specific" else "A",
            label=candidate_label,
            model_run_id=get_state("model_run_id"),
            fitted_at=time.time(),
            scorecard=scorecard,
            market=frame["markets"][0] if len(frame["markets"]) == 1 else None,
        )
        candidates = get_state("model_comparison_candidates") or []
        candidates.append(candidate.to_dict())
        set_state("model_comparison_candidates", candidates)
        st.success(f"Saved '{candidate_label}' as a comparison candidate.")

    render_next_step("model_training")
