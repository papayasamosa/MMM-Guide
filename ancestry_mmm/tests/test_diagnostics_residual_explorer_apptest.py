"""AppTest coverage for WP2.11 item 7 (Residual Explorer): the schema-v9
`residual_series` evidence (item 6) rendered as an interactive weekly
actual-vs-modelled/residual view in pages/06_Diagnostics.py, under the
"In-sample fit & error metrics" tab.

Mirrors the fixture pattern already used by
test_diagnostics_wp2_evidence_apptest.py. The Residual Explorer must never
recompute a residual independently of `DiagnosticsService.evaluate()`'s own
`residual_series`/`shared_residual_evidence` evidence - these tests check
the rendered numbers against that same artefact, not against a page-local
recalculation.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import arviz as az
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.pathways import resolve_pathway_masks
from ancestry_mmm.core.schema import ModelSpec

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "06_Diagnostics.py"


def _single_outcome_trace_frame_meta():
    """A minimal, single-market, single-outcome, single-channel real
    trace/frame/meta triple (same construction as
    test_diagnostics_wp2_evidence_apptest.py's fixture)."""
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


def _two_outcome_trace_frame_meta(*, with_mu: bool = True, with_group: bool = True):
    """A minimal, single-market, two-outcome, single-channel real
    trace/frame/meta triple - enough for DiagnosticsService.evaluate() to
    run for real, so the Residual Explorer's outcome selector, comparison
    overlay, group-total view, and shared-residual-weeks evidence all have
    something real to show."""
    rng = np.random.default_rng(19)
    n_obs, n_chain, n_draw = 16, 2, 20
    oids = ["fh_new_gsa", "fh_winback_gsa"]
    chs = ["TV"]

    Y = rng.uniform(5, 30, size=(n_obs, 2))
    posterior = {
        "alpha": np.full((n_chain, n_draw, 2), 8.0),
        "decay_rate": np.full((n_chain, n_draw, 1), 0.5),
        "hill_K": np.ones((n_chain, n_draw, 1)),
        "hill_S": np.full((n_chain, n_draw, 1), 4.0),
        "beta": np.ones((n_chain, n_draw, 2, 1)),
        "intercept": np.zeros((n_chain, n_draw, 2)),
        "trend_coef": np.zeros((n_chain, n_draw, 2)),
        "promo_coef": np.zeros((n_chain, n_draw, 2)),
        "market_offset": np.zeros((n_chain, n_draw, 1, 2)),
        "gamma_fourier": np.zeros((n_chain, n_draw, 4, 2)),
    }
    dims = {
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
    }
    if with_mu:
        posterior["mu"] = np.maximum(
            Y[None, None, :, :] + rng.normal(0, 0.5, size=(n_chain, n_draw, n_obs, 2)),
            0.1,
        )
        dims["mu"] = ["obs", "outcome"]

    trace = az.from_dict(
        posterior=posterior,
        coords={
            "obs": list(range(n_obs)),
            "outcome": oids,
            "channel": chs,
            "market": ["UK"],
            "fourier": list(range(4)),
        },
        dims=dims,
        sample_stats={"diverging": np.zeros((n_chain, n_draw), dtype=bool)},
    )

    outcome_groups_at_fit = (
        [
            {
                "group_id": "fh_total_gsa",
                "group_label": "Total Family History GSA",
                "product": "Family History",
                "outcome_family_key": "fh_gsa",
                "segment_dimension": "unspecified",
                "member_outcome_ids": oids,
            }
        ]
        if with_group
        else []
    )
    outcome_group_treatments_at_fit = (
        [{"group_id": "fh_total_gsa", "treatment": "components_joint"}]
        if with_group
        else []
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
        outcome_groups_at_fit=outcome_groups_at_fit,
        outcome_group_treatments_at_fit=outcome_group_treatments_at_fit,
    )

    dates = pd.date_range("2024-01-01", periods=n_obs, freq="W")
    x_media = rng.uniform(0, 100, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": x_media,
        "markets": ["UK"],
        "market_bounds": [(0, n_obs)],
        "market_idx": np.zeros(n_obs, dtype=int),
        "promo": np.zeros((n_obs, 2)),
        "trend": np.arange(n_obs, dtype=float),
        "fourier": np.zeros((n_obs, 4)),
        "outcome_ids": oids,
        "dates": dates.to_numpy(),
        "df": pd.DataFrame(
            {
                "date": dates,
                "market": "UK",
                "TV": x_media[:, 0],
                "fh_new_gsa": Y[:, 0],
                "fh_winback_gsa": Y[:, 1],
            }
        ),
    }
    return trace, frame, meta


def _two_market_single_outcome_trace_frame_meta():
    """A minimal, two-market, single-outcome, single-channel real
    trace/frame/meta triple - only for the Residual Explorer's market
    selector/boundary test, kept separate from the two-outcome fixture
    above to avoid combining two independent axes of complexity in one
    fixture."""
    rng = np.random.default_rng(29)
    n_per_market, n_chain, n_draw = 8, 2, 10
    n_obs = n_per_market * 2
    oids = ["fh_new_gsa"]
    chs = ["TV"]
    markets = ["UK", "US"]

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
            "market_offset": np.zeros((n_chain, n_draw, 2, 1)),
            "gamma_fourier": np.zeros((n_chain, n_draw, 4, 1)),
        },
        coords={
            "obs": list(range(n_obs)),
            "outcome": oids,
            "channel": chs,
            "market": markets,
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
        markets=markets,
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

    dates_per_market = pd.date_range("2024-01-01", periods=n_per_market, freq="W")
    dates = np.concatenate([dates_per_market.to_numpy(), dates_per_market.to_numpy()])
    x_media = rng.uniform(0, 100, size=(n_obs, 1))
    frame = {
        "Y": Y,
        "X_media": x_media,
        "markets": markets,
        "market_bounds": [(0, n_per_market), (n_per_market, n_obs)],
        "market_idx": np.array([0] * n_per_market + [1] * n_per_market),
        "promo": np.zeros((n_obs, 1)),
        "trend": np.concatenate(
            [
                np.arange(n_per_market, dtype=float),
                np.arange(n_per_market, dtype=float),
            ]
        ),
        "fourier": np.zeros((n_obs, 4)),
        "outcome_ids": oids,
        "dates": dates,
        "df": pd.DataFrame(
            {
                "date": dates,
                "market": ["UK"] * n_per_market + ["US"] * n_per_market,
                "TV": x_media[:, 0],
                "fh_new_gsa": Y[:, 0],
            }
        ),
    }
    return trace, frame, meta


def _seed(at: AppTest, trace, frame, meta, segment_outcomes) -> None:
    at.session_state["trace"] = trace
    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["model_spec"] = ModelSpec(
        date_col="date",
        market_col="market",
        markets=list(meta.markets),
        segment_outcomes=segment_outcomes,
        channels=["TV"],
    ).to_dict()
    at.session_state["posterior_params"] = {"beta": [[1.0]]}
    at.session_state["model_run_id"] = "run-test-residual-explorer"


def _compute_scorecard(at: AppTest) -> None:
    at.run()
    compute_button = next(b for b in at.button if b.label == "Compute scorecard")
    compute_button.click().run()
    assert not at.exception, f"page raised after computing scorecard: {at.exception}"


def _residual_view_select(at: AppTest):
    return next(s for s in at.selectbox if s.key == "residual_explorer_view")


def _all_captions(at: AppTest) -> str:
    return "\n".join((c.value or "") for c in at.caption)


def _all_markdown(at: AppTest) -> str:
    return "\n".join((m.value or "") for m in at.markdown)


def test_residual_explorer_renders_with_one_outcome_and_matches_sign_convention():
    """7.7: exact residual sign convention, and the app renders with one
    outcome without crashing."""
    trace, frame, meta = _single_outcome_trace_frame_meta()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa"})
    _compute_scorecard(at)

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.residual_series.status == "computed"
    rows = artefact.residual_series.payload["rows"]
    assert rows
    for row in rows:
        assert row["residual"] == pytest.approx(row["actual"] - row["predicted"])

    assert "Residual Explorer" in _all_markdown(at)
    assert "residual = actual - predicted" in _all_captions(at)


def test_residual_explorer_offers_the_level_shift_diagnostic(monkeypatch):
    """Production integration (Decision 15, REQ-BASELINE-001): the
    diagnostic-only residual level-shift check reads this exact page's own
    already-computed residual series - never a separately recomputed one -
    and is genuinely reachable by an analyst, not just present in code."""
    trace, frame, meta = _single_outcome_trace_frame_meta()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa"})
    _compute_scorecard(at)

    assert not at.exception, f"page raised: {at.exception}"
    assert any(
        e.label == "Residual level-shift diagnostic (Decision 15)" for e in at.expander
    )
    assert any(m.label == "Shift detected" for m in at.metric)
    disclaimer_present = any(
        "never automatically-modelled" in (c.value or "")
        or "never an automatically-modelled" in (c.value or "")
        for c in at.caption
    )
    assert disclaimer_present, "expected the module's own disclaimer text to render"


def test_residual_explorer_table_matches_the_canonical_artefact_exactly():
    """7.7: no recomputation mismatch between the artefact and the UI - the
    Biggest misses table's residual values must be a subset of the
    canonical residual_series rows' values, never a page-local
    recalculation."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    artefact = at.session_state["diagnostics_artefact"]
    rows = pd.DataFrame(artefact.residual_series.payload["rows"])

    view_select = _residual_view_select(at)
    first_outcome_option = next(
        label for label in view_select.options if label.startswith("Individual outcome")
    )
    view_select.set_value(first_outcome_option).run()
    assert not at.exception, f"page raised: {at.exception}"

    table = next(
        df.value for df in at.dataframe if "abs_residual_rank_pct" in df.value.columns
    )
    known_residuals = set(rows["residual"].round(6))
    assert set(table["residual"].round(6)) <= known_residuals
    assert len(table) == len(frame["Y"])


def test_residual_explorer_market_selector_isolates_each_market():
    """7.7: market boundaries - switching markets shows only that market's
    rows, never a mix."""
    trace, frame, meta = _two_market_single_outcome_trace_frame_meta()
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa"})
    _compute_scorecard(at)

    market_select = next(s for s in at.selectbox if s.key == "residual_explorer_market")
    assert set(market_select.options) == {"UK", "US"}

    for market in ("UK", "US"):
        market_select.set_value(market).run()
        assert not at.exception, f"page raised for market {market}: {at.exception}"
        table = next(
            df.value
            for df in at.dataframe
            if "abs_residual_rank_pct" in df.value.columns
        )
        assert len(table) == 8


def test_residual_explorer_offers_group_total_only_when_configured():
    """7.7: compatible group totals only - a group view is offered when a
    components_joint group is configured and every member is fitted."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=True)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    view_select = _residual_view_select(at)
    assert any(label.startswith("Outcome group") for label in view_select.options)

    group_option = next(
        label for label in view_select.options if label.startswith("Outcome group")
    )
    view_select.set_value(group_option).run()
    assert not at.exception, f"page raised for group view: {at.exception}"
    captions = _all_captions(at)
    assert "Outcome-group total" in captions
    assert "not shown for group totals" in captions


def test_residual_explorer_withholds_group_view_when_not_configured():
    """7.7: no group view is offered at all when no compatible group is
    configured - never an arbitrary/inferred total."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    view_select = _residual_view_select(at)
    assert not any(label.startswith("Outcome group") for label in view_select.options)


def test_residual_explorer_labels_the_expected_mean_interval_when_available():
    """7.7: interval labelling - a genuine expected-mean credible interval
    is captioned explicitly as not a posterior predictive interval."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_mu=True, with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    captions = _all_captions(at)
    assert "credible interval for the fitted expected mean" in captions
    assert "not a posterior predictive interval" in captions


def test_residual_explorer_does_not_crash_without_an_expected_mean_interval():
    """7.7: no crash when uncertainty intervals are unavailable."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_mu=False, with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.residual_series.status == "computed"
    rows = artefact.residual_series.payload["rows"]
    assert rows and "expected_mean_lower" not in rows[0]
    assert "credible interval for the fitted expected mean" not in _all_captions(at)


def test_residual_explorer_renders_with_multiple_outcomes_and_comparison_overlay():
    """7.7: app renders with multiple outcomes, including the optional
    multi-outcome comparison overlay."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    compare_multiselect = next(
        m for m in at.multiselect if m.key == "residual_explorer_compare"
    )
    assert compare_multiselect.options
    compare_multiselect.set_value([compare_multiselect.options[0]]).run()
    assert not at.exception, f"page raised with comparison overlay: {at.exception}"


def test_residual_explorer_shared_weeks_view_uses_neutral_non_causal_wording():
    """7.7 + item 7.5's explicit constraint: neutral wording, no causal
    inference language anywhere in the shared-residual-weeks section."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    captions = _all_captions(at)
    assert "Shared residual weeks" in _all_markdown(at)
    assert "not a causal claim" in captions
    assert "nothing here is added to the model automatically" in captions
    assert "causes" not in captions.lower()


def test_residual_explorer_preserves_existing_aggregate_residual_diagnostics():
    """7.6: the Residual Explorer is additive - the existing aggregate
    lag-1 autocorrelation / Durbin-Watson evidence must still render."""
    trace, frame, meta = _two_outcome_trace_frame_meta(with_group=False)
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    _seed(at, trace, frame, meta, {"New": "fh_new_gsa", "Winback": "fh_winback_gsa"})
    _compute_scorecard(at)

    artefact = at.session_state["diagnostics_artefact"]
    assert artefact.residual_diagnostics.status == "computed"
    assert artefact.error_metrics.status == "computed"
    assert "Durbin-Watson" in _all_captions(at)
