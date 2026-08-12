"""AppTest coverage for the Compare Models page's Phase 5 redesign
(docs/decision_log.md): a decision-oriented "Candidates at a glance" summary
(label/model type/market/converged/plausibility-flag-count - not a ranking),
the full metrics table demoted to an expander as deeper evidence, and
per-candidate detail grouped into tabs instead of one flat sequential
display. No composite model score is introduced anywhere.
"""

from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.model_comparison import ModelComparisonCandidate

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "12_Compare_Models.py"


def _candidate(label, *, model_type="A", market=None, converged=True, n_flags=0):
    return ModelComparisonCandidate(
        model_type=model_type,
        label=label,
        model_run_id=f"run-{label}",
        fitted_at=1700000000.0,
        market=market,
        convergence={
            "rhat_max": 1.0,
            "ess_min": 500,
            "divergences": 0,
            "converged": converged,
        },
        in_sample_fit=[{"outcome_id": "fh_new_gsa", "r_squared": 0.8, "mape_pct": 12.0}],
        ppc_coverage=[{"outcome_id": "fh_new_gsa", "coverage_pct": 91.0, "target_pct": 90.0}],
        n_plausibility_flags=n_flags,
    ).to_dict()


def _all_text(at: AppTest) -> str:
    parts = [(m.value or "") for m in at.markdown]
    parts += [(c.value or "") for c in at.caption]
    return "\n".join(parts)


def test_empty_state_prompts_fitting_a_candidate():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any("No comparison candidates saved yet" in (i.value or "") for i in at.info)


def test_candidates_at_a_glance_table_has_no_composite_score_column():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["model_comparison_candidates"] = [
        _candidate("Model A - shared", model_type="A"),
        _candidate("Model C - UK", model_type="C", market="UK", converged=False, n_flags=2),
    ]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"

    dataframes = list(at.dataframe)
    assert len(dataframes) >= 1
    glance_df = dataframes[0].value
    for col in glance_df.columns:
        for forbidden in ("score", "rank", "overall"):
            assert forbidden not in col.lower(), (
                f"decision-summary table column '{col}' looks like a composite score, "
                "which the brief explicitly forbids"
            )
    assert "converged" in glance_df.columns
    assert "plausibility_flags" in glance_df.columns

    text = _all_text(at)
    assert "No composite score" in text


def test_full_comparison_table_is_available_as_deeper_evidence():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["model_comparison_candidates"] = [_candidate("Model A - shared")]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        "Full comparison table" in (e.label or "") for e in at.expander
    )


def test_candidate_detail_uses_tabs_not_one_flat_block():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["model_comparison_candidates"] = [_candidate("Model A - shared")]
    at.run()
    assert not at.exception, f"page raised: {at.exception}"
    tab_labels = [t.label for t in at.tabs]
    assert tab_labels == ["Convergence", "In-sample fit", "Posterior predictive coverage"]


def test_remove_candidate_button_removes_it_from_state():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.session_state["model_comparison_candidates"] = [
        _candidate("Model A - shared"),
        _candidate("Model C - UK", model_type="C", market="UK"),
    ]
    at.run()
    remove_button = next(
        b for b in at.button if b.label == "Remove 'Model A - shared'"
    )
    at = remove_button.click().run()
    assert not at.exception, f"page raised after remove: {at.exception}"
    remaining_labels = [
        c["label"] for c in at.session_state["model_comparison_candidates"]
    ]
    assert remaining_labels == ["Model C - UK"]
