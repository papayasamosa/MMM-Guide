"""Tests for core.net_billthrough - the deterministic net bill-through
transformation (PR G1). Required test cases covered: net bill-through ->
signup-date mapping, immature-cohort exclusion, finance-date GSA stays
separate (structurally, by this module never touching that metric_key at
all - see the standalone test at the bottom of this file)."""

import pandas as pd
import pytest

from ancestry_mmm.core.net_billthrough import (
    NetBillthroughOfferRule,
    cohort_maturity_status,
    compute_net_billthrough_cohorts,
    immature_cohort_summary,
    net_billthrough_weekly_series,
    validate_offer_rules,
)

RULES = [
    NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=30),
    NetBillthroughOfferRule(offer_id="trial-30", market="US", maturity_days=45),
]


class TestNetBillthroughOfferRuleValidation:
    def test_valid_rule_has_no_errors(self):
        rule = NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=30)
        assert rule.validate() == []

    def test_missing_offer_id_is_an_error(self):
        rule = NetBillthroughOfferRule(offer_id="", market="UK", maturity_days=30)
        assert any("offer_id" in e for e in rule.validate())

    def test_negative_maturity_days_is_an_error(self):
        rule = NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=-1)
        assert any("maturity_days" in e for e in rule.validate())

    def test_duplicate_market_offer_pair_is_rejected(self):
        rules = [
            NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=30),
            NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=45),
        ]
        errors = validate_offer_rules(rules)
        assert any("Duplicate" in e for e in errors)

    def test_round_trip_to_dict_from_dict(self):
        rule = NetBillthroughOfferRule(offer_id="trial-30", market="UK", maturity_days=30, description="Free trial")
        assert NetBillthroughOfferRule.from_dict(rule.to_dict()) == rule


class TestCohortMaturityStatus:
    def test_cohort_past_maturity_window_is_mature(self):
        cohorts = pd.DataFrame({"market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"]})
        result = cohort_maturity_status(cohorts, RULES, as_of_date="2024-03-01")
        assert result["is_mature"].iloc[0]
        assert result["matures_on"].iloc[0] == pd.Timestamp("2024-01-31")

    def test_cohort_within_maturity_window_is_not_mature(self):
        cohorts = pd.DataFrame({"market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"]})
        result = cohort_maturity_status(cohorts, RULES, as_of_date="2024-01-15")
        assert not result["is_mature"].iloc[0]

    def test_exactly_on_the_maturity_boundary_counts_as_mature(self):
        cohorts = pd.DataFrame({"market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"]})
        result = cohort_maturity_status(cohorts, RULES, as_of_date="2024-01-31")
        assert result["is_mature"].iloc[0]

    def test_missing_offer_rule_raises_rather_than_assuming_a_default(self):
        cohorts = pd.DataFrame({"market": ["Australia"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"]})
        with pytest.raises(ValueError, match="No net bill-through offer rule configured"):
            cohort_maturity_status(cohorts, RULES, as_of_date="2024-03-01")

    def test_different_markets_use_their_own_maturity_window(self):
        cohorts = pd.DataFrame({
            "market": ["UK", "US"], "signup_date": ["2024-01-01", "2024-01-01"], "offer_id": ["trial-30", "trial-30"],
        })
        result = cohort_maturity_status(cohorts, RULES, as_of_date="2024-02-01")
        uk_matures = result[result["market"] == "UK"]["matures_on"].iloc[0]
        us_matures = result[result["market"] == "US"]["matures_on"].iloc[0]
        assert uk_matures != us_matures
        assert (us_matures - uk_matures).days == 15  # 45 - 30 day maturity difference


class TestComputeNetBillthroughCohorts:
    def test_net_billthrough_is_gross_signups_minus_cancellations(self):
        signups = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "gross_signups": [100.0],
        })
        cancellations = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "cancellations": [30.0],
        })
        result = compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-03-01")
        assert result["net_billthroughs"].iloc[0] == pytest.approx(70.0)

    def test_net_billthrough_is_clipped_at_zero_not_negative(self):
        # Cancellations exceeding gross signups indicates a data/join error
        # upstream - net_billthroughs must never go negative regardless.
        signups = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "gross_signups": [10.0],
        })
        cancellations = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "cancellations": [15.0],
        })
        result = compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-03-01")
        assert result["net_billthroughs"].iloc[0] == pytest.approx(0.0)

    def test_a_cohort_with_no_cancellations_at_all_defaults_to_zero_cancelled(self):
        signups = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "gross_signups": [50.0],
        })
        cancellations = pd.DataFrame(columns=["market", "signup_date", "offer_id", "cancellations"])
        result = compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-03-01")
        assert result["net_billthroughs"].iloc[0] == pytest.approx(50.0)

    def test_carries_maturity_status_through(self):
        signups = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-01-01"], "offer_id": ["trial-30"], "gross_signups": [50.0],
        })
        cancellations = pd.DataFrame(columns=["market", "signup_date", "offer_id", "cancellations"])
        result = compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-01-05")
        assert not result["is_mature"].iloc[0]


class TestNetBillthroughWeeklySeriesSignupDateMapping:
    """Required test case: net bill-through -> signup-date mapping - the
    weekly series is keyed by signup_date's own week, not any later
    cancellation-event date."""

    def _mature_cohorts(self) -> pd.DataFrame:
        signups = pd.DataFrame({
            "market": ["UK", "UK"],
            "signup_date": ["2024-01-01", "2024-01-08"],  # two different weeks
            "offer_id": ["trial-30", "trial-30"],
            "gross_signups": [100.0, 80.0],
        })
        cancellations = pd.DataFrame({
            "market": ["UK", "UK"],
            "signup_date": ["2024-01-01", "2024-01-08"],
            "offer_id": ["trial-30", "trial-30"],
            "cancellations": [20.0, 10.0],
        })
        return compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-06-01")

    def test_each_cohorts_net_billthrough_lands_in_its_own_signup_week(self):
        cohorts = self._mature_cohorts()
        series = net_billthrough_weekly_series(cohorts)
        assert len(series) == 2
        week1 = series[series["week_start"] == pd.Timestamp("2024-01-01")]  # W-SUN start containing 2024-01-01
        week2 = series[series["week_start"] == pd.Timestamp("2024-01-08")]  # W-SUN start containing 2024-01-08
        assert week1["fh_net_billthrough_count"].iloc[0] == pytest.approx(80.0)
        assert week2["fh_net_billthrough_count"].iloc[0] == pytest.approx(70.0)

    def test_total_across_weeks_equals_total_net_billthroughs(self):
        cohorts = self._mature_cohorts()
        series = net_billthrough_weekly_series(cohorts)
        assert series["fh_net_billthrough_count"].sum() == pytest.approx(cohorts["net_billthroughs"].sum())


class TestImmatureCohortExclusion:
    """Required test case: immature-cohort exclusion - a cohort that hasn't
    reached its offer's maturity window must never appear in the reported
    weekly series, not even as a zero."""

    def _mixed_maturity_cohorts(self, as_of_date: str) -> pd.DataFrame:
        signups = pd.DataFrame({
            "market": ["UK", "UK"],
            "signup_date": ["2024-01-01", "2024-05-01"],  # first mature, second not (as of 2024-05-10)
            "offer_id": ["trial-30", "trial-30"],
            "gross_signups": [100.0, 60.0],
        })
        cancellations = pd.DataFrame(columns=["market", "signup_date", "offer_id", "cancellations"])
        return compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date=as_of_date)

    def test_immature_cohort_is_excluded_from_the_default_series(self):
        cohorts = self._mixed_maturity_cohorts(as_of_date="2024-05-10")
        series = net_billthrough_weekly_series(cohorts)
        # Only the mature (2024-01-01) cohort's week should appear.
        assert len(series) == 1
        assert series["fh_net_billthrough_count"].iloc[0] == pytest.approx(100.0)

    def test_immature_cohort_is_not_silently_zero_filled(self):
        # Confirms exclusion, not a zero row - a zero would be a fabricated
        # "we know this cohort converted to nothing" claim we cannot make yet.
        cohorts = self._mixed_maturity_cohorts(as_of_date="2024-05-10")
        series = net_billthrough_weekly_series(cohorts)
        immature_week_start = pd.Timestamp("2024-04-29")  # W-SUN week containing 2024-05-01
        assert immature_week_start not in series["week_start"].to_numpy()

    def test_include_immature_true_surfaces_the_excluded_cohort_explicitly(self):
        cohorts = self._mixed_maturity_cohorts(as_of_date="2024-05-10")
        series_with_immature = net_billthrough_weekly_series(cohorts, include_immature=True)
        assert len(series_with_immature) == 2

    def test_immature_cohort_summary_lists_exactly_the_excluded_cohorts(self):
        cohorts = self._mixed_maturity_cohorts(as_of_date="2024-05-10")
        summary = immature_cohort_summary(cohorts)
        assert len(summary) == 1
        assert summary["signup_date"].iloc[0] == pd.Timestamp("2024-05-01")
        assert summary["gross_signups"].iloc[0] == pytest.approx(60.0)

    def test_all_immature_gives_an_empty_series_not_an_error(self):
        signups = pd.DataFrame({
            "market": ["UK"], "signup_date": ["2024-05-01"], "offer_id": ["trial-30"], "gross_signups": [10.0],
        })
        cancellations = pd.DataFrame(columns=["market", "signup_date", "offer_id", "cancellations"])
        cohorts = compute_net_billthrough_cohorts(signups, cancellations, RULES, as_of_date="2024-05-10")
        series = net_billthrough_weekly_series(cohorts)
        assert series.empty
        assert list(series.columns) == ["market", "week_start", "fh_net_billthrough_count"]


class TestFinanceDateGsaStaysSeparate:
    """Required test case: finance-date GSA stays separate - fh_gsa_finance_date
    is a normal source-column outcome untouched by this module; nothing here
    reads or writes that metric_key at all."""

    def test_module_has_no_import_of_the_outcomes_module_at_all(self):
        # Structural proof via the AST, not a string search over prose/
        # docstrings (which legitimately mention fh_gsa_finance_date to
        # explain the distinction) - net_billthrough.py never imports
        # core.outcomes, so it cannot read or write
        # METRIC_KEY_FH_GSA_FINANCE_DATE even accidentally.
        import ast
        import inspect

        import ancestry_mmm.core.net_billthrough as net_billthrough_module

        tree = ast.parse(inspect.getsource(net_billthrough_module))
        imported_modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
        assert not any("outcomes" in m for m in imported_modules)

    def test_metric_registry_keeps_the_two_metric_keys_distinct(self):
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA_FINANCE_DATE, METRIC_KEY_FH_NET_BILLTHROUGH_COUNT

        assert METRIC_KEY_FH_GSA_FINANCE_DATE != METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
