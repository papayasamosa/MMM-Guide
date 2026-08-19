"""AppTest coverage for Work Package 2 (canonical Diagnostics evidence
integration, `Media-Mix-Lab: Coding LLM Next Steps After PR #286`): the six
new schema-v8 sections wired into pages/06_Diagnostics.py -
posterior_predictive_metric_distributions (REQ-PPD-001), historical_
validation/structural_stability (REQ-LEAK-001/REQ-STAB-001), graphical_
identification (REQ-IDENT-001), latent_state_identification
(REQ-LATENT-001), and experiment_calibration (REQ-EXPMODE-001/
REQ-CALIB-001).

Mirrors the fixture pattern already used by test_diagnostics_rail_apptest.py
and test_diagnostics_approval_apptest.py. The expensive real per-fold PyMC
refit ("Run historical validation & structural stability") is exercised only
via its fast failure path (no transformed_data seeded - mirrors the existing
"Run backtest" failure-path test), never a real fit, to keep this suite fast
and deterministic for blocking CI.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import arviz as az
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.causal_graph import CausalEdge, CausalGraph, CausalNode
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import resolve_pathway_masks
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "06_Diagnostics.py"


def _trace_frame_meta():
    """A minimal, single-outcome, single-channel real trace/frame/meta
    triple - enough for DiagnosticsService.evaluate() to run for real,
    without raising (same construction as test_diagnostics_rail_apptest.py's
    fixture)."""
    rng = np.random.default_rng(11)
    n_obs, n_chain, n_draw = 16, 2, 20
    oids = ["fh_new_gsa"]
    chs = ["TV"]

    Y = rng.uniform(5, 30, size=(n_obs, 1))
    trace = az.from_dict(
        posterior={
            "mu": np.maximum(
                Y[None, None, :, 0] + rng.normal(0, 0.5, size=(n_chain, n_draw, n_obs)),
                0.1,
            )[..., None],
            "alpha": np.full((n_chain, n_draw, 1), 8.0),
            "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
            "hill_K": np.ones((n_chain, n_draw, 1)),
            "hill_S": np.full((n_chain, n_draw, 1), 4.0),
            "beta": np.ones((n_chain, n_draw, 1, 1)),
            "intercept": np.zeros((n_chain, n_draw, 1)),
            "trend_coef": np.zeros((n_chain, n_draw, 1)),
            "promo_coef": np.zeros((n_chain, n_draw, 1)),
            "market_offset": np.zeros((n_chain, n_draw, 1, 1)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
        },
        coords={
            "obs": list(range(n_obs)),
            "outcome": oids,
            "channel": chs,
            "market": ["UK"],
            "fourier": list(range(4)),
        },
        dims={
            "mu": ["obs", "outcome"],
            "alpha": ["outcome"],
            "decay_rate": ["channel"],
            "hill_K": ["channel"],
            "hill_S": ["channel"],
            "beta": ["outcome", "channel"],
            "intercept": ["outcome"],
            "trend_coef": ["outcome"],
            "promo_coef": ["outcome"],
            "market_offset": ["market", "outcome"],
            "gamma_fourier": ["fourier", "outcome"],
        },
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )

    meta = FHModelMeta(
        markets=["UK"],
        outcome_ids=oids,
        channels=chs,
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id=oids[0],
        dna_lag_weeks=1,
        unpooled_markets=[],
        control_names=[],
        pathway_masks=resolve_pathway_masks(
            oids,
            chs,
            [],
            dna_channel_idx=[],
            dna_outcome_id=oids[0],
            direct_dna_outcome_ids=[],
            dna_lag_weeks=1,
        ),
    )

    dates = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    x_media = rng.uniform(0, 100, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": x_media,
        "markets": ["UK"],
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "outcome_ids": oids,
        "dates": dates.to_numpy(),
        "df": pd.DataFrame(
            {"date": dates, "market": "UK", "TV": x_media[:, 0], "fh_new_gsa": Y[:, 0]}
        ),
    }
    return trace, frame, meta


def _seed_fully_identified_model(at: AppTest) -> None:
    trace, frame, meta = _trace_frame_meta()
    at.session_state["trace"] = trace
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["model_spec"] = ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV"],
    ).to_dict()
    at.session_state["posterior_params"] = {"beta": [[1.0]]}
    at.session_state["model_run_id"] = "run-test-wp2-1"
    at.session_state["activity_definitions"] = [
        ActivityDefinition(
            activity_id="a1",
            channel="TV",
            activity_ownership="paid",
            model_role="intervention",
            economic_treatment="paid_media_cost",
            planning_eligibility="optimisable",
            source="test",
            approval_status="approved",
            approved_by="Test Reviewer",
            approved_at="2026-07-29T00:00:00+00:00",
        ).to_dict()
    ]


def _all_markdown_text(at: AppTest) -> str:
    parts = [(m.value or "") for m in at.markdown]
    parts += [(c.value or "") for c in at.caption]
    parts += [(i.value or "") for i in at.info]
    return "\n".join(parts)


def _simple_confounder_graph_dict() -> dict:
    """X <- Z -> Y, X -> Y - the same minimal scenario
    test_estimand_identification.py uses."""
    graph = CausalGraph(
        graph_id="wp2-apptest-graph",
        graph_version=1,
        nodes=[CausalNode(node_id=n, label=n) for n in ("X", "Y", "Z")],
        edges=[
            CausalEdge(source_node_id="Z", target_node_id="X"),
            CausalEdge(source_node_id="Z", target_node_id="Y"),
            CausalEdge(source_node_id="X", target_node_id="Y"),
        ],
    )
    return graph.to_dict()


def test_scorecard_computes_posterior_predictive_metric_distributions():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.posterior_predictive_metric_distributions.status == "computed"
    text = _all_markdown_text(at)
    assert "Posterior predictive metric distributions" in text


def test_scorecard_reports_not_applicable_latent_state_and_experiment_sections():
    """An ordinary (non-Candidate-A) fit with no experiment evidence
    supplied must show not_applicable for both sections - never a
    fabricated pass, and never silently blank."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.latent_state_identification.status == "not_applicable"
    assert artefact.experiment_calibration.status == "not_applicable"
    text = _all_markdown_text(at)
    assert "No latent causal states are declared or fitted" in text
    assert "No experiment evidence or calibrated-model comparison" in text


def test_historical_validation_button_records_a_failed_section_without_crashing():
    """No transformed_data seeded - run_leakage_safe_fold_refit raises
    before any real (slow) model refit is attempted, exercising the page's
    failure-recording path deterministically and fast, mirroring the
    existing 'Run backtest' failure-path AppTest coverage."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["variable_coverage_matrix"] = {
        "matrix_id": "cm-wp2-apptest",
        "matrix_version": 1,
        "generated_at": "2026-08-18T00:00:00+00:00",
        "records": [],
    }
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    hv_button = next(
        b
        for b in at.button
        if b.label == "Run historical validation & structural stability"
    )
    hv_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.historical_validation.status == "failed"
    assert artefact.structural_stability.status == "failed"
    assert any("Historical validation failed" in (e.value or "") for e in at.error)
    # Fingerprint-changing evidence must invalidate governance evidence in
    # the same action, mirroring every other artefact-updating button.
    assert at.session_state["model_approval"] is None
    assert at.session_state["approval_readiness"] is None


def _canned_fold_refit_result(tier: str):
    """A genuine LeakageSafeFoldRefitResult with no fit performed - the
    page's deep/shallow routing is what these tests exercise, never the
    expensive real per-fold PyMC fit itself."""
    from ancestry_mmm.application.fold_refit_service import LeakageSafeFoldRefitResult
    from ancestry_mmm.core.structural_stability import FoldParameterSnapshot
    from ancestry_mmm.core.validation_folds import (
        LEAKAGE_STATUS_SAFE,
        FoldReconstructionAssessment,
        ValidationFold,
        VariableReconstructionAssessment,
    )

    fold = ValidationFold(
        fold_id="fold-1",
        fold_manifest_version=1,
        train_start="2024-01-01",
        train_end="2024-03-01",
        test_start="2024-03-08",
        test_end="2024-04-01",
    )
    assessment = FoldReconstructionAssessment(
        fold_id="fold-1",
        per_variable=(
            VariableReconstructionAssessment(
                variable_id="tv_spend",
                market="UK",
                status=LEAKAGE_STATUS_SAFE,
                reason="Source version pinned before fold cutoff.",
            ),
        ),
    )
    snapshot = FoldParameterSnapshot(
        fold_id="fold-1", point_values={"hill_K__TV": 100.0}
    )
    return LeakageSafeFoldRefitResult(
        results_df=pd.DataFrame(
            [
                {
                    "fold_id": "fold-1",
                    "outcome_id": "fh_new_gsa",
                    "r_squared": 0.8,
                    "mape_pct": 12.0,
                    "leakage_safe": True,
                    "skipped_reason": None,
                }
            ]
        ),
        folds=(fold,),
        assessments=(assessment,),
        snapshots=(snapshot,),
        reconstruction_tier=tier,
    )


def test_historical_validation_routes_to_deep_path_when_sources_exist(monkeypatch):
    """With raw source tables and outcome definitions available, the page
    must route through run_leakage_safe_fold_refit_from_sources (the
    stronger fold-local reconstruction) and record the
    source-version-aware tier - never the shallower path, never an
    ambiguous tier."""
    from ancestry_mmm.core.outcomes import (
        FAMILY_HISTORY,
        METRIC_GSA,
        OutcomeDefinition,
    )
    from ancestry_mmm.core.validation_folds import (
        RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL,
    )

    seen: dict = {}

    def fake_from_sources(sources, spec, coverage_matrix, outcomes, **kwargs):
        seen["sources"] = sources
        seen["outcomes"] = outcomes
        return _canned_fold_refit_result(
            RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL
        )

    def fail_shallow(*args, **kwargs):
        raise AssertionError("shallow path must not run when deep inputs exist")

    monkeypatch.setattr(
        "ancestry_mmm.application.fold_refit_service.run_leakage_safe_fold_refit_from_sources",
        fake_from_sources,
    )
    monkeypatch.setattr(
        "ancestry_mmm.application.fold_refit_service.run_leakage_safe_fold_refit",
        fail_shallow,
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["variable_coverage_matrix"] = {
        "matrix_id": "cm-wp2-apptest-deep",
        "matrix_version": 1,
        "generated_at": "2026-08-18T00:00:00+00:00",
        "records": [],
    }
    at.session_state["raw_sources"] = {
        "src-1": pd.DataFrame(
            {"date": pd.date_range("2024-01-01", periods=8, freq="W")}
        )
    }
    # A real OutcomeDefinition - the page resolves outcome definitions at
    # the top of the script, so a bare dict would not survive page load.
    at.session_state["outcome_definitions"] = [
        OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric=METRIC_GSA,
            source_column="fh_new_gsa",
        ).to_dict()
    ]
    at.session_state["source_versions"] = []
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    hv_button = next(
        b
        for b in at.button
        if b.label == "Run historical validation & structural stability"
    )
    hv_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.historical_validation.status == "computed"
    assert (
        artefact.historical_validation.payload["reconstruction_tier"]
        == RECONSTRUCTION_TIER_SOURCE_VERSION_AWARE_FOLD_LOCAL
    )
    assert seen["sources"]
    assert seen["outcomes"]
    text = _all_markdown_text(at)
    assert "source-version-aware fold-local reconstruction" in text


def test_historical_validation_labels_the_shallow_path_when_sources_absent(
    monkeypatch,
):
    """Without raw source tables the page may still run the shallower
    coverage-metadata-only path - but it must record and render that
    weaker tier explicitly, never presenting it as the deeper
    reconstruction."""
    from ancestry_mmm.core.validation_folds import (
        RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY,
    )

    def fail_deep(*args, **kwargs):
        raise AssertionError("deep path must not run without raw sources")

    def fake_shallow(*args, **kwargs):
        return _canned_fold_refit_result(RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY)

    monkeypatch.setattr(
        "ancestry_mmm.application.fold_refit_service.run_leakage_safe_fold_refit_from_sources",
        fail_deep,
    )
    monkeypatch.setattr(
        "ancestry_mmm.application.fold_refit_service.run_leakage_safe_fold_refit",
        fake_shallow,
    )

    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["variable_coverage_matrix"] = {
        "matrix_id": "cm-wp2-apptest-shallow",
        "matrix_version": 1,
        "generated_at": "2026-08-18T00:00:00+00:00",
        "records": [],
    }
    at.session_state["transformed_data"] = None
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    hv_button = next(
        b
        for b in at.button
        if b.label == "Run historical validation & structural stability"
    )
    hv_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.historical_validation.status == "computed"
    assert (
        artefact.historical_validation.payload["reconstruction_tier"]
        == RECONSTRUCTION_TIER_COVERAGE_METADATA_ONLY
    )
    text = _all_markdown_text(at)
    assert "coverage-metadata-only assessment" in text
    assert "NOT rebuilt fold-locally" in text


def test_graphical_identification_assesses_a_graph_compatible_total_effect():
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["causal_graph"] = _simple_confounder_graph_dict()
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"

    treatment_select = next(s for s in at.selectbox if s.key == "gi_treatment")
    treatment_select.set_value("X").run()
    outcome_select = next(s for s in at.selectbox if s.key == "gi_outcome")
    outcome_select.set_value("Y").run()
    adjustment_multiselect = next(
        m for m in at.multiselect if m.key == "gi_adjustment_set"
    )
    adjustment_multiselect.set_value(["Z"]).run()

    assess_button = next(b for b in at.button if b.label == "Assess identification")
    assess_button.click().run()
    assert not at.exception, (
        f"page raised after assessing identification: {at.exception}"
    )

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.graphical_identification.status == "computed"
    result = artefact.graphical_identification.payload["results"][0]
    assert result["status"] == "graph_compatible"
    text = _all_markdown_text(at)
    assert "This evaluates the assumed graph." in text
    assert "does not prove" in text


def test_graphical_identification_rejects_unsupported_direct_effect_request():
    """REQ-IDENT-001: a direct-effect request must be reported as
    unsupported_by_current_checker, never silently treated as identified."""
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed_fully_identified_model(at)
    at.session_state["causal_graph"] = _simple_confounder_graph_dict()
    at.run()

    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()

    treatment_select = next(s for s in at.selectbox if s.key == "gi_treatment")
    treatment_select.set_value("X").run()
    outcome_select = next(s for s in at.selectbox if s.key == "gi_outcome")
    outcome_select.set_value("Y").run()
    effect_type_select = next(s for s in at.selectbox if s.key == "gi_effect_type")
    effect_type_select.set_value("direct").run()

    assess_button = next(b for b in at.button if b.label == "Assess identification")
    assess_button.click().run()
    assert not at.exception, f"page raised: {at.exception}"

    artefact = at.session_state["diagnostics_artefact"]
    result = artefact.graphical_identification.payload["results"][0]
    assert result["status"] == "unsupported_by_current_checker"
    assert result["effect_type"] == "direct"
