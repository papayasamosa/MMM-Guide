"""AppTest coverage for WP2D-ui: the historical Results economic
valuation & ROI section on 07_Results_Curve_Bank.py. Seeds a real fitted
model via `prepare_fh_modeling_frame` (mirroring
test_curve_bank_page_apptest.py's fixture recipe) and drives the actual
page end-to-end, including through `OutcomeValuationReportingService`
- no page-internal function is unit-tested in isolation."""

from pathlib import Path

import arviz as az
import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest

from ancestry_mmm.core.coverage import STATE_ESTIMATED
from ancestry_mmm.core.fingerprint import (
    fingerprint_dataframe,
    fingerprint_model_spec,
    fingerprint_posterior,
)
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.outcome_valuation import (
    VALUATION_KIND_FH_LTR,
    WeeklyOutcomeValuationRecord,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    OutcomeDefinition,
    outcome_catalogue_fingerprint_payload,
)
from ancestry_mmm.core.pathways import pathway_catalogue_fingerprint_payload
from ancestry_mmm.core.predict import extract_posterior_params
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame

st.page_link = lambda *a, **k: None

ROOT = Path(__file__).parent.parent
PAGE = ROOT / "pages" / "07_Results_Curve_Bank.py"

MARKET = "UK"
SEGMENT = "All"


def _outcome_def() -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id="New",
        product=FAMILY_HISTORY,
        segment="New",
        metric="GSA",
        metric_key=METRIC_KEY_FH_GSA,
        source_column="fh_new_gsa",
        unit="GSA",
        aggregation_type="count",
        event_definition="A new subscriber",
        date_basis="event_date",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 12 weeks",
        exclusions="Excludes internal test accounts",
        reconciliation_source="Finance report",
        business_owner="Analytics",
        definition_version="1.0",
    )


def _meta() -> FHModelMeta:
    return FHModelMeta(
        markets=[MARKET],
        outcome_ids=["New"],
        channels=["TV_Brand"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
        outcome_catalogue_at_fit=[_outcome_def()],
        outcome_id_to_segment={"New": SEGMENT},
    )


def _trace(meta: FHModelMeta, n_fourier: int = 6, chains: int = 2, draws: int = 10):
    rng = np.random.default_rng(0)
    n_ch, n_seg, n_mkt = len(meta.channels), len(meta.outcome_ids), len(meta.markets)
    posterior = {
        "decay_rate": rng.uniform(0.1, 0.9, size=(chains, draws, n_ch)),
        "hill_K": rng.uniform(500, 2000, size=(chains, draws, n_ch)),
        "hill_S": rng.uniform(0.5, 2.0, size=(chains, draws, n_ch)),
        "intercept": rng.normal(size=(chains, draws, n_seg)),
        "trend_coef": rng.normal(size=(chains, draws, n_seg)),
        "promo_coef": rng.uniform(0, 1, size=(chains, draws, n_seg)),
        "alpha": rng.uniform(1, 10, size=(chains, draws, n_seg)),
        "beta": rng.normal(size=(chains, draws, n_seg, n_ch)),
        "market_offset": rng.normal(size=(chains, draws, n_mkt, n_seg)),
        "gamma_fourier": rng.normal(size=(chains, draws, n_fourier, n_seg)),
    }
    coords = {
        "channel": meta.channels,
        "outcome": meta.outcome_ids,
        "market": meta.markets,
        "fourier": list(range(n_fourier)),
    }
    dims = {
        "decay_rate": ["channel"],
        "hill_K": ["channel"],
        "hill_S": ["channel"],
        "intercept": ["outcome"],
        "trend_coef": ["outcome"],
        "promo_coef": ["outcome"],
        "alpha": ["outcome"],
        "beta": ["outcome", "channel"],
        "market_offset": ["market", "outcome"],
        "gamma_fourier": ["fourier", "outcome"],
    }
    return az.from_dict(posterior=posterior, coords=coords, dims=dims)


def _january_2024_weeks() -> list[str]:
    """The 4 Sundays fully contained in January 2024, matching
    `prepare_fh_modeling_frame`'s weekly grain for the 16-week fixture
    below (`pd.date_range("2024-01-01", periods=16, freq="W")`)."""
    return ["2024-01-07", "2024-01-14", "2024-01-21", "2024-01-28"]


def _seed_session_state(at: AppTest, *, valuation_records=None) -> None:
    meta = _meta()
    trace = _trace(meta)
    transformed_data = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=16, freq="W"),
            "market": [MARKET] * 16,
            "TV_Brand": np.linspace(100.0, 250.0, 16),
            "fh_new_gsa": np.linspace(10.0, 16.0, 16),
        }
    )
    model_spec_dict = ModelSpec(
        date_col="date",
        market_col="market",
        markets=[MARKET],
        segment_outcomes={"New": "fh_new_gsa"},
        channels=["TV_Brand"],
    ).to_dict()
    prior_config = {"decay_mu": 0.5}
    dna_lag_weeks = 4
    spec = ModelSpec.from_dict(model_spec_dict)
    frame = prepare_fh_modeling_frame(transformed_data, spec)
    posterior_params = extract_posterior_params(trace, meta)

    model_run_id = "run-outcome-valuation-apptest"
    approval = ModelApproval(
        approved_by="Jane Analyst",
        model_run_id=model_run_id,
        data_fingerprint=fingerprint_dataframe(frame["df"]),
        model_spec_fingerprint=fingerprint_model_spec(
            model_spec_dict,
            prior_config,
            dna_lag_weeks,
            model_type="shared",
            pipeline_steps=[],
            market_spec_config=None,
            direct_dna_outcome_ids=meta.direct_dna_outcome_ids,
            outcome_catalogue=outcome_catalogue_fingerprint_payload(
                meta.outcome_catalogue_at_fit
            ),
            funnel_links=None,
            media_outcome_pathways=pathway_catalogue_fingerprint_payload(
                meta.pathway_catalogue_at_fit
            ),
            activity_fit_fingerprint=None,
        ),
        posterior_fingerprint=fingerprint_posterior(posterior_params),
    )

    at.session_state["frame"] = frame
    at.session_state["model_meta"] = meta
    at.session_state["posterior_params"] = posterior_params
    at.session_state["model_spec"] = model_spec_dict
    at.session_state["trace"] = trace
    at.session_state["model_type"] = "shared"
    at.session_state["model_run_id"] = model_run_id
    at.session_state["prior_config"] = prior_config
    at.session_state["dna_lag_weeks"] = dna_lag_weeks
    at.session_state["model_approval"] = approval.to_dict()
    at.session_state["outcome_definitions"] = [
        o.to_dict() for o in meta.outcome_catalogue_at_fit
    ]
    at.session_state["activity_definitions"] = []
    at.session_state["outcome_valuation_records"] = [
        r.to_dict() for r in (valuation_records or [])
    ]


def _january_records() -> list[WeeklyOutcomeValuationRecord]:
    return [
        WeeklyOutcomeValuationRecord(
            valuation_kind=VALUATION_KIND_FH_LTR,
            market=MARKET,
            week=week,
            segment=SEGMENT,
            denominator_outcome_id="New",
            quality_status=STATE_ESTIMATED,
            aggregate_value=500.0,
            currency="GBP",
        )
        for week in _january_2024_weeks()
    ]


class TestEconomicValuationSectionRenders:
    def test_section_heading_present(self):
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()
        assert not at.exception
        headings = [m.value for m in at.markdown]
        assert any("Economic outcome valuation & ROI" in h for h in headings)

    def test_no_catalogue_shows_explicit_empty_state(self):
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=[])
        at.run()
        assert not at.exception
        infos = [i.value for i in at.info]
        assert any("No governed outcome-valuation records yet" in i for i in infos)


class TestEconomicValuationReportingHappyPath:
    def test_month_view_reports_roi_and_incremental_value(self):
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()
        assert not at.exception

        at.selectbox(key="ev_report_grain").set_value("Month").run()
        assert not at.exception
        at.selectbox(key="ev_report_period").set_value("2024-01").run()
        assert not at.exception

        metric_labels = [m.label for m in at.metric]
        assert "Incremental value" in metric_labels
        assert "Attributable spend" in metric_labels
        assert "ROI" in metric_labels
        captions = [c.value for c in at.caption]
        assert any("4 week(s) covered" in c for c in captions)

    def test_changing_period_changes_the_underlying_weeks_used(self):
        """WP2D-ui verification requirement: changing the selected period
        must change which underlying weeks feed the calculation - checked
        here via the resolved-week-count disclosure caption changing
        between a single week and a full month."""
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()

        at.selectbox(key="ev_report_grain").set_value("Week").run()
        at.selectbox(key="ev_report_week").set_value("2024-01-07").run()
        week_captions = [c.value for c in at.caption]
        assert any("1 week(s) covered" in c for c in week_captions)

        at.selectbox(key="ev_report_grain").set_value("Month").run()
        at.selectbox(key="ev_report_period").set_value("2024-01").run()
        month_captions = [c.value for c in at.caption]
        assert any("4 week(s) covered" in c for c in month_captions)

    def test_channel_dimension_selection_does_not_error(self):
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()

        at.selectbox(key="ev_report_grain").set_value("Month").run()
        at.selectbox(key="ev_report_period").set_value("2024-01").run()
        at.radio(key="ev_report_dimension").set_value("Single channel").run()
        assert not at.exception
        metric_labels = [m.label for m in at.metric]
        assert "ROI" in metric_labels


class TestEconomicValuationFailsClosed:
    def test_a_week_with_no_catalogue_coverage_is_an_explicit_error(self):
        """Only January has valuation records; the fixture's later weeks
        (into April) must fail closed rather than silently reporting."""
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()

        at.selectbox(key="ev_report_grain").set_value("Week").run()
        at.selectbox(key="ev_report_week").set_value("2024-04-21").run()
        assert not at.exception
        errors = [e.value for e in at.error]
        assert any("Missing governed valuation coverage" in e for e in errors)
        metric_labels = [m.label for m in at.metric]
        assert "ROI" not in metric_labels


class TestPeriodComparison:
    """WP2E: explicit two-period comparison section."""

    def test_comparing_two_covered_weeks_shows_change_metrics(self):
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()

        at.selectbox(key="ev_cmp_a_grain").set_value("Week").run()
        at.selectbox(key="ev_cmp_a_week").set_value("2024-01-07").run()
        at.selectbox(key="ev_cmp_b_grain").set_value("Week").run()
        at.selectbox(key="ev_cmp_b_week").set_value("2024-01-14").run()
        assert not at.exception

        metric_labels = [m.label for m in at.metric]
        assert "Incremental value - Period A" in metric_labels
        assert "Incremental value - Period B" in metric_labels
        assert "Incremental value - change" in metric_labels
        assert "ROI - Period A" in metric_labels
        headings = [m.value for m in at.markdown]
        assert any("Change from Period A to Period B" in h for h in headings)

    def test_comparing_an_uncovered_period_shows_error_not_fabricated_comparison(self):
        """Only January has coverage; the fixture's default latest-week
        selection (into April) is uncovered on both sides by default -
        the comparison must show each period's own error, never a
        fabricated delta."""
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()
        assert not at.exception

        errors = [e.value for e in at.error]
        assert any("Missing governed valuation coverage" in e for e in errors)
        metric_labels = [m.label for m in at.metric]
        assert "Incremental value - change" not in metric_labels

    def test_comparing_a_covered_and_an_uncovered_period(self):
        """Period A covered, Period B not - each period's own card
        renders independently and no cross-period delta is fabricated
        from only one side."""
        at = AppTest.from_file(str(PAGE), default_timeout=60)
        _seed_session_state(at, valuation_records=_january_records())
        at.run()

        at.selectbox(key="ev_cmp_a_grain").set_value("Week").run()
        at.selectbox(key="ev_cmp_a_week").set_value("2024-01-07").run()
        at.selectbox(key="ev_cmp_b_grain").set_value("Week").run()
        at.selectbox(key="ev_cmp_b_week").set_value("2024-04-21").run()
        assert not at.exception

        errors = [e.value for e in at.error]
        assert any("Missing governed valuation coverage" in e for e in errors)
        metric_labels = [m.label for m in at.metric]
        assert "Incremental value - change" not in metric_labels
        # Period A's own card still renders successfully.
        assert "Incremental value" in metric_labels
