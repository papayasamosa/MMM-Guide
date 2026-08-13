"""Compare fitted candidate models side by side before
choosing which to take forward to Model Diagnostics for approval - the model
comparison workflow."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import streamlit as st

from ancestry_mmm.utils import (
    init_session_state,
    get_state,
    set_state,
    dataframe_column_config,
)
from ancestry_mmm.components import (
    apply_theme,
    render_sidebar,
    render_page_header,
    render_next_step,
    render_definition_help,
    render_decision_help,
    render_technical_details,
    render_workspace_note,
    SectionCard,
    render_status_badge,
)
from ancestry_mmm.core.model_comparison import (
    ModelComparisonCandidate,
    candidates_decision_summary_dataframe,
    candidates_to_dataframe,
)

st.set_page_config(
    page_title="Model Comparison | Ancestry Family History & DNA MMM",
    layout="wide",
)
init_session_state()
apply_theme()
render_sidebar("compare_models")
render_page_header(
    "compare_models",
    task_prompt="Which fitted candidate should be taken forward?",
)
render_decision_help(
    "How should I compare fitted candidates?",
    controls="Convergence, predictive fit, posterior predictive coverage, and plausibility are reviewed as separate evidence dimensions.",
    why="A candidate can converge cleanly and still fit poorly, or fit well while its effects remain difficult to distinguish. One score would hide those trade-offs.",
    options={
        "Convergence": "Check R-hat, effective sample size, and divergences for reliable posterior sampling.",
        "Predictive fit": "Review in-sample fit and error metrics for how closely the model follows observed outcomes.",
        "Posterior predictive coverage": "Check whether simulated outcomes cover the observed data at the intended level.",
        "Plausibility": "Inspect flags and domain knowledge before taking a candidate forward.",
    },
    normal_path="Review the independent dimensions, inspect the chosen candidate in detail, then take it to Diagnostics for the formal readiness and approval workflow.",
    downstream="The selected candidate determines which model identity, posterior evidence, curves, and diagnostics are carried forward.",
    invalidates="Selecting a candidate does not alter a fit. Any changed candidate configuration or newly fitted posterior requires fresh diagnostics and approval.",
)
render_definition_help(
    "R-hat",
    "A convergence check comparing variation within and between sampling chains; values close to 1 indicate the chains are behaving consistently.",
)
render_definition_help(
    "effective sample size",
    "An estimate of how much independent information remains in the posterior draws after accounting for autocorrelation.",
)
render_definition_help(
    "posterior predictive coverage",
    "The share of observed outcomes that falls inside the model's posterior predictive interval.",
)
render_workspace_note(
    "Decision rule",
    "Use convergence, predictive fit, and plausibility together; this view does not rank candidates with a composite score.",
    kind="governed",
)

st.markdown(
    "Three candidate model structures are worth comparing before trusting a market-specific fit: "
    "**Shared response across markets** (Model A), **independent single-market response** (Model B), "
    "and **market-specific response with partial pooling** (Model C). The partially pooled model isn't "
    "adopted just for being more sophisticated - it should show comparable-or-better prediction, "
    "credible market differentiation, and acceptable diagnostics."
)
st.caption(
    "To get an independent single-market candidate: go to Model Structure, select a single market, save, "
    "then fit and save a candidate on Fit Model as usual - fitting the shared-response model "
    "against one market's data *is* an independent single-market fit."
)

candidate_dicts = get_state("model_comparison_candidates") or []
with st.container(border=True):
    st.markdown("### Comparison dashboard")
    st.caption(
        "Choose using independent evidence dimensions. The page never converts them into a composite score or automatic ranking."
    )
    summary_cols = st.columns(3)
    summary_cols[0].metric("Saved candidates", len(candidate_dicts))
    summary_cols[1].metric("Evidence dimensions", "3")
    summary_cols[2].metric(
        "Next action", "Select a candidate" if candidate_dicts else "Fit a candidate"
    )
if not candidate_dicts:
    st.info(
        "No comparison candidates saved yet. Fit a model on Fit Model, then use "
        '"Save this fit as a comparison candidate" to add it here.'
    )
else:
    candidates = [ModelComparisonCandidate.from_dict(d) for d in candidate_dicts]

    with SectionCard(
        "Candidates at a glance",
        description=(
            "The dimensions that help decide what to inspect next - not a ranking. Deeper "
            "evidence (R-hat, ESS, mean R-squared/MAPE, PPC coverage) is available below."
        ),
    ):
        summary_table = candidates_decision_summary_dataframe(candidates)
        st.dataframe(
            summary_table,
            width="stretch",
            column_config=dataframe_column_config(summary_table),
        )
        st.caption(
            "Shown separately by design: convergence, predictive fit, and plausibility are "
            "independent dimensions - a model that converges cleanly can still fit poorly, and a "
            "model that fits well can still raise plausibility flags. No composite score collapses "
            "them into one ranking number."
        )

    with st.expander(
        "Full comparison table (R-hat, ESS, mean R-squared/MAPE, PPC coverage)"
    ):
        table = candidates_to_dataframe(candidates)
        st.dataframe(
            table, width="stretch", column_config=dataframe_column_config(table)
        )

    st.markdown("### Selected candidate detail")
    labels = [c.label for c in candidates]
    chosen_label = st.selectbox("Candidate", labels)
    chosen = next(c for c in candidates if c.label == chosen_label)
    st.caption(
        f"{chosen.n_plausibility_flags} plausibility flag(s) for this candidate."
    )
    render_technical_details(
        details={
            "Model run ID": chosen.model_run_id,
            "Candidate label": chosen.label,
            "Stored evidence": "The full comparison table retains convergence, fit, predictive coverage, and plausibility evidence separately; no composite score is stored.",
        }
    )

    tab_conv, tab_fit, tab_ppc = st.tabs(
        ["Convergence", "In-sample fit", "Posterior predictive coverage"]
    )
    with tab_conv:
        render_status_badge(
            "validated" if chosen.convergence.get("converged") else "failed",
            label="Converged"
            if chosen.convergence.get("converged")
            else "Not converged",
        )
        c1, c2, c3 = st.columns(3)
        c1.metric(
            "Max R-hat",
            f"{chosen.convergence.get('rhat_max', float('nan')):.3f}"
            if chosen.convergence.get("rhat_max") is not None
            else "n/a",
        )
        c2.metric(
            "Min ESS",
            f"{chosen.convergence.get('ess_min', 0):.0f}"
            if chosen.convergence.get("ess_min") is not None
            else "n/a",
        )
        c3.metric("Divergences", chosen.convergence.get("divergences", "n/a"))

    with tab_fit:
        if chosen.in_sample_fit:
            st.dataframe(pd.DataFrame(chosen.in_sample_fit), width="stretch")
        else:
            st.info("No in-sample fit evidence recorded for this candidate.")

    with tab_ppc:
        if chosen.ppc_coverage:
            st.dataframe(pd.DataFrame(chosen.ppc_coverage), width="stretch")
        else:
            st.info(
                "No posterior predictive coverage evidence recorded for this candidate."
            )

    if st.button(f"Remove '{chosen_label}'"):
        candidate_dicts = [d for d in candidate_dicts if d.get("label") != chosen_label]
        set_state("model_comparison_candidates", candidate_dicts)
        st.rerun()

render_next_step("compare_models")
