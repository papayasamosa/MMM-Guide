"""Tests for core.report - the reproducible project report generator
(Phase 4). No PyMC involved: build_report_sections consumes plain
dicts/dataclasses (scorecard, ModelApproval, CurveBankEntry, scenario
dicts), matching this project's established test conventions."""

import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.curve_bank import make_entries
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_config import (
    ChannelMediaUnitConfig, MarketCurrency, MarketProfile, MarketSpecConfig,
)
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.core.report import build_report_sections, render_html, render_markdown
from ancestry_mmm.core.schema import ModelSpec

SEGMENTS = ["New", "DNA_CrossSell"]
CHANNELS = ["TV", "Search"]

IDENTITY = dict(
    model_run_id="run-1", data_fingerprint="data-1",
    model_spec_fingerprint="spec-1", posterior_fingerprint="posterior-1",
)


@pytest.fixture
def spec() -> ModelSpec:
    return ModelSpec(
        date_col="date", market_col="market", markets=["UK"],
        segment_outcomes={"New": "fh_new_gsa", "DNA_CrossSell": "fh_dna_gsa"},
        channels=CHANNELS, dna_channels=["TV"],
    )


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=SEGMENTS, channels=CHANNELS,
        dna_channels=["TV"], dna_channel_idx=[0], non_dna_idx=[1],
        dna_segment="DNA_CrossSell", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV": 0.5, "Search": 0.3}, hill_K={"TV": 1000.0, "Search": 500.0},
        hill_S={"TV": 1.0, "Search": 1.0},
        beta={"New": {"TV": 0.1, "Search": 0.05}, "DNA_CrossSell": {"TV": 0.02, "Search": 0.01}},
        halo_strength={"New": 0.1, "DNA_CrossSell": 1.0}, promo_coef={"New": 0.1, "DNA_CrossSell": 0.1},
        market_offset={"UK": {"New": 0.0, "DNA_CrossSell": 0.0}}, intercept={"New": 3.0, "DNA_CrossSell": 2.0},
        trend_coef={"New": 0.0, "DNA_CrossSell": 0.0},
        gamma_fourier={"New": np.zeros(6), "DNA_CrossSell": np.zeros(6)},
        alpha={"New": 5.0, "DNA_CrossSell": 5.0}, control_coef={}, segment_control_coef={},
    )


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", diagnostics_accepted=["convergence"], **IDENTITY)


@pytest.fixture
def curve_bank_entries(meta, params, approval):
    return make_entries(
        meta, params, ("2023-01-01", "2024-01-01"), "uk-v1", approval,
        model_type="shared", **IDENTITY,
    )


@pytest.fixture
def scorecard():
    return {
        "convergence": {"rhat_max": 1.01, "ess_min": 500, "divergences": 0, "converged": True},
        "in_sample_fit": [{"segment": "New", "r_squared": 0.9, "mape_pct": 5.0}],
        "ppc_coverage": [{"segment": "New", "coverage_pct": 90.0}],
        "plausibility_flags": [],
    }


@pytest.fixture
def scenarios():
    predicted = pd.DataFrame({"month": ["2024-01"], "segment": ["New"], "predicted_gsa": [10.0], "value": [10.0]})
    return [{
        "name": "manual-uk", "market": "UK", "spend_plan": {"2024-01": {"TV": 100.0}},
        "objective": "value", "constraints": [], "notes": "manual", "predicted": predicted,
    }]


class TestBuildReportSectionsEmptyState:
    def test_no_spec_gives_a_placeholder_objective_section(self):
        sections = build_report_sections(spec=None)
        objective = next(s for s in sections if s.title == "Objective")
        assert "No model specification" in objective.paragraphs[0]

    def test_missing_scorecard_says_so_rather_than_erroring(self, spec):
        sections = build_report_sections(spec=spec)
        diagnostics = next(s for s in sections if s.title == "Diagnostics")
        assert "No scorecard" in diagnostics.paragraphs[0]

    def test_missing_approval_says_so(self, spec):
        sections = build_report_sections(spec=spec)
        approval_section = next(s for s in sections if s.title == "Approval")
        assert "not been approved" in approval_section.paragraphs[0]

    def test_empty_curve_bank_and_scenarios_say_so(self, spec):
        sections = build_report_sections(spec=spec)
        curve_bank = next(s for s in sections if s.title == "Curve bank")
        scenarios_section = next(s for s in sections if s.title == "Scenarios")
        assert "No curves" in curve_bank.paragraphs[0]
        assert "No scenarios" in scenarios_section.paragraphs[0]

    def test_renders_without_error_in_the_fully_empty_state(self):
        sections = build_report_sections(spec=None)
        md = render_markdown("empty-project", sections)
        html = render_html("empty-project", sections)
        assert "empty-project" in md
        assert "empty-project" in html


class TestBuildReportSectionsFullState:
    def test_objective_mentions_segments_and_markets(self, spec):
        sections = build_report_sections(spec=spec, model_type="shared")
        objective = next(s for s in sections if s.title == "Objective")
        text = " ".join(objective.paragraphs)
        assert "New" in text and "DNA_CrossSell" in text and "UK" in text

    def test_diagnostics_section_includes_convergence_and_in_sample_table(self, spec, scorecard):
        sections = build_report_sections(spec=spec, scorecard=scorecard)
        diagnostics = next(s for s in sections if s.title == "Diagnostics")
        assert "1.01" in diagnostics.paragraphs[0]
        assert diagnostics.table is not None
        assert list(diagnostics.table["segment"]) == ["New"]

    def test_approval_section_includes_approver_and_diagnostics_reviewed(self, spec, approval):
        sections = build_report_sections(spec=spec, approval=approval)
        approval_section = next(s for s in sections if s.title == "Approval")
        assert "Jane Analyst" in approval_section.paragraphs[0]
        assert any("convergence" in b for b in approval_section.bullets)

    def test_curve_bank_section_summarises_by_market_and_status(self, spec, curve_bank_entries):
        sections = build_report_sections(spec=spec, curve_bank_entries=curve_bank_entries)
        curve_bank = next(s for s in sections if s.title == "Curve bank")
        assert str(len(curve_bank_entries)) in curve_bank.paragraphs[0]
        assert curve_bank.table is not None
        assert "curve_status" in curve_bank.table.columns

    def test_scenarios_section_includes_the_comparison_table(self, spec, scenarios):
        sections = build_report_sections(spec=spec, scenarios=scenarios)
        scenarios_section = next(s for s in sections if s.title == "Scenarios")
        assert scenarios_section.table is not None
        assert "manual-uk" in scenarios_section.table["scenario"].tolist()


class TestOutcomesSection:
    def test_no_spec_gives_a_placeholder(self):
        sections = build_report_sections(spec=None)
        outcomes = next(s for s in sections if s.title == "Outcomes")
        assert "No model specification" in outcomes.paragraphs[0]

    def test_derives_fh_outcomes_from_spec_when_none_saved(self, spec):
        sections = build_report_sections(spec=spec, outcome_definitions=None)
        outcomes = next(s for s in sections if s.title == "Outcomes")
        assert "2 outcome(s) catalogued: 2 Family History, 0 DNA" in outcomes.paragraphs[0]
        assert outcomes.table is not None
        assert set(outcomes.table["product"]) == {"Family History"}
        assert outcomes.table["modelled_today"].all()

    def test_includes_dna_outcomes_and_flags_them_as_opt_in(self, spec):
        outcome_definitions = [
            {"outcome_id": "fh_new", "product": "Family History", "segment": "New", "metric": "GSA", "column": "fh_new_gsa", "value_weight": 180.0},
            {"outcome_id": "dna_new_kit", "product": "DNA", "segment": "New Customer", "metric": "Kit sale", "column": "DNA_Kit_New", "value_weight": 90.0},
        ]
        sections = build_report_sections(spec=spec, outcome_definitions=outcome_definitions)
        outcomes = next(s for s in sections if s.title == "Outcomes")
        assert "1 Family History, 1 DNA" in outcomes.paragraphs[0]
        assert any("opt-in" in p for p in outcomes.paragraphs)
        dna_row = outcomes.table[outcomes.table["product"] == "DNA"].iloc[0]
        assert dna_row["modelled_today"] == False  # noqa: E712

    def test_renders_without_error_with_dna_outcomes(self, spec):
        outcome_definitions = [
            {"outcome_id": "dna_new_kit", "product": "DNA", "segment": "New Customer", "metric": "Kit sale", "column": "DNA_Kit_New"},
        ]
        sections = build_report_sections(spec=spec, outcome_definitions=outcome_definitions)
        md = render_markdown("proj", sections)
        html = render_html("proj", sections)
        assert "DNA" in md and "DNA" in html


class TestLimitationsSectionVariesByModelType:
    def test_shared_model_does_not_mention_market_specific_caveats(self, spec):
        sections = build_report_sections(spec=spec, model_type="shared")
        limitations = next(s for s in sections if s.title == "Known limitations & assumptions")
        assert not any("evidence-tier" in b for b in limitations.bullets)

    def test_market_specific_model_mentions_shared_decay_and_evidence_tiers(self, spec):
        sections = build_report_sections(spec=spec, model_type="market_specific")
        limitations = next(s for s in sections if s.title == "Known limitations & assumptions")
        text = " ".join(limitations.bullets)
        assert "decay" in text.lower()
        assert "evidence-tier" in text.lower()

    def test_media_unit_mapping_adds_a_cost_per_unit_caveat(self, spec):
        config = MarketSpecConfig()
        config.set_profile(MarketProfile(market="UK", currency=MarketCurrency(local_currency="GBP")))
        config.set_media_unit_config(ChannelMediaUnitConfig(
            market="UK", channel="TV", spend_column="tv_spend", response_unit_column="tv_impressions",
        ))
        sections = build_report_sections(spec=spec, model_type="shared", market_spec_config=config)
        limitations = next(s for s in sections if s.title == "Known limitations & assumptions")
        assert any("cost per unit" in b.lower() for b in limitations.bullets)

    def test_no_media_unit_mapping_omits_the_cost_per_unit_caveat(self, spec):
        sections = build_report_sections(spec=spec, model_type="shared", market_spec_config=MarketSpecConfig())
        limitations = next(s for s in sections if s.title == "Known limitations & assumptions")
        assert not any("cost per unit" in b.lower() for b in limitations.bullets)


class TestRenderMarkdown:
    def test_includes_a_title_and_every_section_heading(self, spec):
        sections = build_report_sections(spec=spec)
        md = render_markdown("my-project", sections)
        assert "# my-project - MMM Project Report" in md
        for s in sections:
            assert f"## {s.title}" in md

    def test_renders_a_table_as_markdown_pipes(self, spec, scorecard):
        sections = build_report_sections(spec=spec, scorecard=scorecard)
        md = render_markdown("my-project", sections)
        assert "| segment | r_squared | mape_pct |" in md
        assert "| New | 0.9 | 5.0 |" in md


class TestRenderHtml:
    def test_produces_a_self_contained_document(self, spec):
        sections = build_report_sections(spec=spec)
        out = render_html("my-project", sections)
        assert out.startswith("<!DOCTYPE html>")
        assert "</html>" in out
        assert "<style>" in out  # inline CSS, no external stylesheet link

    def test_escapes_untrusted_content(self, spec):
        # A project name containing HTML/script-like content must not be
        # injected unescaped into the document.
        sections = build_report_sections(spec=spec)
        out = render_html("<script>alert(1)</script>", sections)
        assert "<script>alert(1)</script>" not in out
        assert "&lt;script&gt;" in out

    def test_includes_a_table_element_for_table_sections(self, spec, scorecard):
        sections = build_report_sections(spec=spec, scorecard=scorecard)
        out = render_html("my-project", sections)
        assert "<table" in out
