import numpy as np
import pandas as pd
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.optimization import compare_scenarios, evaluate_scenario, optimize_scenario, VALID_OBJECTIVES
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, DNA, METRIC_GSA, METRIC_KIT_SALE, OutcomeDefinition
from ancestry_mmm.core.predict import FHPosteriorParams
from ancestry_mmm.tests.conftest import pathway_strength_from_flat

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], outcome_ids=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
        beta={"New": {"TV_Brand": 0.1}}, pathway_strength={}, promo_coef={"New": 0.1},
        market_offset={"UK": {"New": 0.0}}, intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0}, control_coef={}, outcome_control_coef={},
    )


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", **IDENTITY)


@pytest.fixture
def reference_context():
    return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0}, "controls": {}, "outcome_controls": {}}}


@pytest.fixture
def spend_plan():
    return {"2024-01": {"TV_Brand": 1000.0}}


@pytest.fixture
def market_specific_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK", "Australia"], outcome_ids=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def market_specific_params() -> FHMarketSpecificPosteriorParams:
    markets = ["UK", "Australia"]
    return FHMarketSpecificPosteriorParams(
        decay_rate={"TV_Brand": 0.5},
        hill_K={"UK": {"TV_Brand": 1000.0}, "Australia": {"TV_Brand": 600.0}},
        hill_S={"TV_Brand": 1.0},
        beta={"UK": {"New": {"TV_Brand": 0.1}}, "Australia": {"New": {"TV_Brand": 0.15}}},
        pathway_strength={}, promo_coef={"New": 0.1},
        market_offset={m: {"New": 0.0} for m in markets},
        intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0},
        control_coef={}, outcome_control_coef={},
    )


class TestEvaluateScenarioApprovalEnforcement:
    def test_unapproved_model_cannot_be_evaluated(self, meta, params, spend_plan, reference_context):
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )

    def test_correctly_approved_model_can_be_evaluated(self, meta, params, approval, spend_plan, reference_context):
        result = evaluate_scenario(
            spend_plan, "UK", meta, params, reference_context,
            approval=approval, **IDENTITY,
        )
        assert not result.empty
        assert set(result.columns) >= {"month", "outcome_id", "predicted_outcome", "value"}

    def test_stale_approval_cannot_be_used(self, meta, params, approval, spend_plan, reference_context):
        stale_identity = dict(IDENTITY)
        stale_identity["posterior_fingerprint"] = "a-different-posterior"  # e.g. model was retrained
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=approval, **stale_identity,
            )

    def test_legacy_approval_cannot_be_used(self, meta, params, spend_plan, reference_context):
        legacy = ModelApproval(approved_by="Jane Analyst")
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=legacy, **IDENTITY,
            )

    def test_the_core_planning_path_rejects_invalid_approval_directly(self, meta, params, spend_plan, reference_context):
        """Calling evaluate_scenario directly - not via the Streamlit page - must still
        be blocked, proving enforcement lives in core, not only in page-level checks."""
        with pytest.raises(ApprovalMismatchError):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                approval=None, model_run_id="", data_fingerprint="", model_spec_fingerprint="", posterior_fingerprint="",
            )


class TestOptimizeScenarioApprovalEnforcement:
    def test_unapproved_model_cannot_be_optimized(self, meta, params, spend_plan, reference_context):
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )

    def test_correctly_approved_model_can_be_optimized(self, meta, params, approval, spend_plan, reference_context):
        result = optimize_scenario(
            spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
            approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result and "predicted" in result

    def test_stale_or_mismatched_approval_cannot_be_used(self, meta, params, approval, spend_plan, reference_context):
        stale_identity = dict(IDENTITY)
        stale_identity["model_run_id"] = "a-newer-run"
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=approval, **stale_identity,
            )

    def test_rejected_before_running_the_optimiser(self, meta, params, spend_plan, reference_context, monkeypatch):
        """Approval is checked up front - the (potentially slow) SLSQP call must never
        run for an invalid approval, not just get its result discarded afterwards."""
        import ancestry_mmm.core.optimization as optimization_module

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("minimize() should not be called when approval is invalid")

        monkeypatch.setattr(optimization_module, "minimize", _fail_if_called)
        with pytest.raises(ApprovalMismatchError):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                approval=None, **IDENTITY,
            )


class TestModelTypeDispatch:
    def test_default_model_type_is_shared(self, meta, params, approval, spend_plan, reference_context):
        # No model_type kwarg at all - must behave exactly as before Phase 3c.
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        assert not result.empty

    def test_invalid_model_type_raises(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="model_type must be"):
            evaluate_scenario(
                spend_plan, "UK", meta, params, reference_context,
                model_type="not_a_real_type", approval=approval, **IDENTITY,
            )

    def test_market_specific_evaluate_scenario_uses_that_markets_own_curve(
        self, market_specific_meta, market_specific_params, approval, spend_plan, reference_context,
    ):
        uk_result = evaluate_scenario(
            spend_plan, "UK", market_specific_meta, market_specific_params, reference_context,
            model_type="market_specific", approval=approval, **IDENTITY,
        )
        au_result = evaluate_scenario(
            spend_plan, "Australia", market_specific_meta, market_specific_params, reference_context,
            model_type="market_specific", approval=approval, **IDENTITY,
        )
        # Different beta/K between markets -> different predicted GSAs for the same spend plan.
        assert uk_result["predicted_outcome"].iloc[0] != pytest.approx(au_result["predicted_outcome"].iloc[0])

    def test_market_specific_optimize_scenario_runs_end_to_end(
        self, market_specific_meta, market_specific_params, approval, spend_plan, reference_context,
    ):
        result = optimize_scenario(
            spend_plan, ["2024-01"], ["TV_Brand"], "UK", market_specific_meta, market_specific_params,
            reference_context, model_type="market_specific", approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result and "predicted" in result
        assert not result["predicted"].empty


class TestAverageCpa:
    def test_avg_cpa_is_total_spend_over_total_predicted_gsa(self, meta, params, approval, spend_plan, reference_context):
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        total_spend = result["total_spend"].iloc[0]
        total_gsa = result["predicted_outcome"].sum()
        assert result["avg_cpa"].iloc[0] == pytest.approx(total_spend / total_gsa)

    def test_avg_cpa_is_repeated_across_every_segment_row_for_the_same_month(
        self, market_specific_meta, market_specific_params, approval, reference_context,
    ):
        # A multi-segment month should carry one avg_cpa value (computed from the
        # month's *total* predicted GSA across segments), not a different one per segment row.
        meta_two_segments = FHModelMeta(
            markets=["UK"], outcome_ids=["New", "Winback"], channels=["TV_Brand"], dna_channels=[],
            dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="New", dna_lag_weeks=4,
            unpooled_markets=[], control_names=[],
        )
        params = FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
            beta={"New": {"TV_Brand": 0.1}, "Winback": {"TV_Brand": 0.05}},
            pathway_strength={}, promo_coef={"New": 0.1, "Winback": 0.1},
            market_offset={"UK": {"New": 0.0, "Winback": 0.0}}, intercept={"New": 3.0, "Winback": 2.0},
            trend_coef={"New": 0.0, "Winback": 0.0},
            gamma_fourier={"New": np.zeros(6), "Winback": np.zeros(6)},
            alpha={"New": 5.0, "Winback": 5.0}, control_coef={}, outcome_control_coef={},
        )
        ref = {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "Winback": 0.0}, "controls": {}, "outcome_controls": {}}}
        result = evaluate_scenario(
            {"2024-01": {"TV_Brand": 1000.0}}, "UK", meta_two_segments, params, ref,
            approval=approval, **IDENTITY,
        )
        assert len(result) == 2  # one row per segment
        assert result["avg_cpa"].nunique() == 1

    def test_whole_plan_cost_per_fh_gsa_alias_matches_avg_cpa(self, meta, params, approval, spend_plan, reference_context):
        # PR E.2 #8 - the explicit-spend-scope name must never silently
        # diverge from the bare avg_cpa/cost_per_fh_gsa numbers.
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        assert np.array_equal(
            result["whole_plan_cost_per_fh_gsa"].to_numpy(dtype=float), result["avg_cpa"].to_numpy(dtype=float), equal_nan=True,
        )


class TestProductAwareScenarioOutputs:
    """avg_cpa must be Family-History-scoped (never a dollars-per-mixed-unit
    blend of FH GSAs and DNA kits), with dna_avg_cpa broken out separately -
    the instruction document's audit-confirmed defect this fixes."""

    @pytest.fixture
    def meta_with_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["New", "DNA_Kit"],
        )

    @pytest.fixture
    def params_with_kit_segment(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5, "DNA_Ad": 0.5},
            hill_K={"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            hill_S={"TV_Brand": 1.0, "DNA_Ad": 1.0},
            beta={"New": {"TV_Brand": 0.1, "DNA_Ad": 0.05}, "DNA_Kit": {"TV_Brand": 0.0, "DNA_Ad": 0.2}},
            pathway_strength=pathway_strength_from_flat({"New": 0.3, "DNA_Kit": 0.0}, "DNA_Ad"), promo_coef={"New": 0.1, "DNA_Kit": 0.1},
            market_offset={"UK": {"New": 0.0, "DNA_Kit": 0.0}}, intercept={"New": 3.0, "DNA_Kit": 2.0},
            trend_coef={"New": 0.0, "DNA_Kit": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_Kit": np.zeros(6)},
            alpha={"New": 5.0, "DNA_Kit": 5.0}, control_coef={}, outcome_control_coef={},
        )

    @pytest.fixture
    def ref_with_kit_segment(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "DNA_Kit": 0.0}, "controls": {}, "outcome_controls": {}}}

    def test_fh_gsa_excludes_kit_only_segments_dna_kits_includes_only_them(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, approval=approval, **IDENTITY)
        new_row = result[result["outcome_id"] == "New"].iloc[0]
        kit_row = result[result["outcome_id"] == "DNA_Kit"].iloc[0]
        assert new_row["fh_gsa"] == pytest.approx(new_row["predicted_outcome"])
        assert new_row["dna_kits"] == pytest.approx(kit_row["predicted_outcome"])
        # fh_gsa/dna_kits are month-level totals repeated on every row for that month.
        assert kit_row["fh_gsa"] == pytest.approx(new_row["fh_gsa"])
        assert kit_row["dna_kits"] == pytest.approx(new_row["dna_kits"])

    def test_avg_cpa_is_fh_scoped_not_mixed_with_dna_kits(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, approval=approval, **IDENTITY)
        total_spend = result["total_spend"].iloc[0]
        fh_gsa = result["fh_gsa"].iloc[0]
        dna_kits = result["dna_kits"].iloc[0]
        assert fh_gsa > 0 and dna_kits > 0  # both non-trivial - a genuinely mixed scenario
        assert result["avg_cpa"].iloc[0] == pytest.approx(total_spend / fh_gsa)
        assert result["avg_cpa"].iloc[0] != pytest.approx(total_spend / (fh_gsa + dna_kits))
        assert result["dna_avg_cpa"].iloc[0] == pytest.approx(total_spend / dna_kits)
        assert result["whole_plan_cost_per_fh_gsa"].iloc[0] == pytest.approx(result["avg_cpa"].iloc[0])
        assert result["whole_plan_cost_per_dna_kit"].iloc[0] == pytest.approx(result["dna_avg_cpa"].iloc[0])

    def test_dna_avg_cpa_is_none_when_no_kit_only_segments(self, meta, params, approval, spend_plan, reference_context):
        result = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        assert result["dna_avg_cpa"].iloc[0] is None

    def test_total_value_sums_ltv_weighted_value_across_every_segment(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0, "DNA_Kit": 50.0}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        assert result["total_value"].iloc[0] == pytest.approx(result["value"].sum())

    def test_compare_scenarios_splits_fh_gsa_and_dna_kits_without_double_counting(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        # Two months, so a naive sum-without-dedup over the duplicated
        # per-row fh_gsa/dna_kits columns would double the true total.
        plan = {
            "2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            "2024-02": {"TV_Brand": 1000.0, "DNA_Ad": 500.0},
        }
        predicted = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, approval=approval, **IDENTITY)
        compare_df = compare_scenarios([{"name": "Plan A", "market": "UK", "spend_plan": plan, "predicted": predicted}])
        expected_fh_gsa = predicted.groupby("month")["fh_gsa"].first().sum()
        expected_dna_kits = predicted.groupby("month")["dna_kits"].first().sum()
        assert compare_df["total_fh_gsa"].iloc[0] == pytest.approx(expected_fh_gsa)
        assert compare_df["total_dna_kits"].iloc[0] == pytest.approx(expected_dna_kits)
        # No ltv given - value is "not configured" throughout (PR E.2), so
        # total_value is NaN, not a fake 0.0 raw-unit total.
        assert pd.isna(compare_df["total_value"].iloc[0])
        assert predicted["value"].isna().all()

    def test_compare_scenarios_falls_back_when_predicted_has_no_product_split(self, meta, params, approval, spend_plan, reference_context):
        # Defensive against a hand-built/legacy `predicted` DataFrame that
        # predates the fh_gsa/dna_kits columns.
        predicted = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        legacy_predicted = predicted.drop(columns=["fh_gsa", "dna_kits"])
        compare_df = compare_scenarios([{"name": "Legacy", "market": "UK", "spend_plan": spend_plan, "predicted": legacy_predicted}])
        assert compare_df["total_fh_gsa"].iloc[0] == pytest.approx(legacy_predicted["predicted_outcome"].sum())
        assert compare_df["total_dna_kits"].iloc[0] == pytest.approx(0.0)


class TestExplicitOptimisationObjectives:
    """optimize_scenario's objective must be one of VALID_OBJECTIVES - no
    generic "maximise volume" that silently sums FH GSAs and DNA kits (the
    instruction document's audit-confirmed defect)."""

    @pytest.fixture
    def meta_with_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["New", "DNA_Kit"],
        )

    @pytest.fixture
    def params_with_kit_segment(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5, "DNA_Ad": 0.5},
            hill_K={"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            hill_S={"TV_Brand": 1.0, "DNA_Ad": 1.0},
            beta={"New": {"TV_Brand": 0.1, "DNA_Ad": 0.05}, "DNA_Kit": {"TV_Brand": 0.0, "DNA_Ad": 0.2}},
            pathway_strength=pathway_strength_from_flat({"New": 0.3, "DNA_Kit": 0.0}, "DNA_Ad"), promo_coef={"New": 0.1, "DNA_Kit": 0.1},
            market_offset={"UK": {"New": 0.0, "DNA_Kit": 0.0}}, intercept={"New": 3.0, "DNA_Kit": 2.0},
            trend_coef={"New": 0.0, "DNA_Kit": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_Kit": np.zeros(6)},
            alpha={"New": 5.0, "DNA_Kit": 5.0}, control_coef={}, outcome_control_coef={},
        )

    @pytest.fixture
    def ref_with_kit_segment(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "DNA_Kit": 0.0}, "controls": {}, "outcome_controls": {}}}

    @pytest.fixture
    def plan_with_kit_segment(self):
        return {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}

    def test_invalid_objective_raises_before_optimising(self, meta, params, approval, spend_plan, reference_context, monkeypatch):
        import ancestry_mmm.core.optimization as optimization_module

        def _fail_if_called(*args, **kwargs):
            raise AssertionError("minimize() should not be called for an invalid objective")

        monkeypatch.setattr(optimization_module, "minimize", _fail_if_called)
        with pytest.raises(ValueError, match="objective must be one of"):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                objective="volume", approval=approval, **IDENTITY,
            )

    def test_default_objective_is_fh_gsa_and_excludes_kit_only_segments(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "New"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_dna_kits_objective_raises_when_model_has_no_kit_only_segments(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="no DNA-kit outcomes"):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                objective="dna_kits", approval=approval, **IDENTITY,
            )

    def test_dna_kits_objective_targets_only_kit_only_segments(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            objective="dna_kits", approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "DNA_Kit"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_weighted_mix_without_weights_raises(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="weighted_mix.*requires"):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                objective="weighted_mix", approval=approval, **IDENTITY,
            )

    def test_expected_value_without_ltv_raises(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="expected_value.*requires"):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                objective="expected_value", approval=approval, **IDENTITY,
            )

    def test_expected_value_with_ltv_runs(self, meta, params, approval, spend_plan, reference_context):
        result = optimize_scenario(
            spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
            ltv={"New": 2.0}, objective="expected_value", approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result

    def test_target_outcome_ids_narrows_fh_gsa_to_a_single_segment(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            objective="fh_gsa", target_outcome_ids=["New"], approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "New"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_a_segment_omitted_from_weighted_mix_contributes_nothing(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        # Only "New" weighted - "DNA_Kit" must contribute 0, not an implicit 1.
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            objective="weighted_mix", weights={"New": 3.0}, approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = 3.0 * float(current_predicted[current_predicted["outcome_id"] == "New"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_all_valid_objectives_are_exercised_above(self):
        # Documentation-level check that this test class covers every
        # VALID_OBJECTIVES value, so a future addition doesn't go untested.
        assert set(VALID_OBJECTIVES) == {"fh_gsa", "fh_signups", "dna_kits", "weighted_mix", "expected_value"}


class TestFhSignupVsGsaObjectives:
    """PR E.1: a fit with an FH sign-up outcome AND an FH GSA outcome on the
    SAME segment must never let objective='fh_gsa' silently include the
    sign-up (the confirmed defect: 'fh_gsa' used to mean "every non-DNA-kit
    outcome"). Uses a meta with full catalogue metadata (outcome_id_to_product/
    _metric) so the metric-aware selectors are actually exercised, not the
    legacy no-catalogue-metadata fallback the fixtures above rely on."""

    @pytest.fixture
    def meta_with_signup_and_gsa(self) -> FHModelMeta:
        from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, METRIC_SIGNUP

        return FHModelMeta(
            markets=["UK"], outcome_ids=["fh_new_gsa", "fh_new_signup"], channels=["TV_Brand"],
            dna_channels=[], dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="fh_new_gsa",
            dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            outcome_id_to_product={"fh_new_gsa": FAMILY_HISTORY, "fh_new_signup": FAMILY_HISTORY},
            outcome_id_to_metric={"fh_new_gsa": METRIC_GSA, "fh_new_signup": METRIC_SIGNUP},
            outcome_id_to_segment={"fh_new_gsa": "New", "fh_new_signup": "New"},
        )

    @pytest.fixture
    def params_with_signup_and_gsa(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
            beta={"fh_new_gsa": {"TV_Brand": 0.1}, "fh_new_signup": {"TV_Brand": 0.4}},
            pathway_strength={},
            promo_coef={"fh_new_gsa": 0.1, "fh_new_signup": 0.1},
            market_offset={"UK": {"fh_new_gsa": 0.0, "fh_new_signup": 0.0}},
            intercept={"fh_new_gsa": 3.0, "fh_new_signup": 3.5}, trend_coef={"fh_new_gsa": 0.0, "fh_new_signup": 0.0},
            gamma_fourier={"fh_new_gsa": np.zeros(6), "fh_new_signup": np.zeros(6)},
            alpha={"fh_new_gsa": 5.0, "fh_new_signup": 5.0}, control_coef={}, outcome_control_coef={},
        )

    @pytest.fixture
    def ref_with_signup_and_gsa(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"fh_new_gsa": 0.0, "fh_new_signup": 0.0}, "controls": {}, "outcome_controls": {}}}

    @pytest.fixture
    def plan(self):
        return {"2024-01": {"TV_Brand": 1000.0}}

    def test_evaluate_scenario_fh_gsa_excludes_signup(
        self, meta_with_signup_and_gsa, params_with_signup_and_gsa, approval, ref_with_signup_and_gsa, plan,
    ):
        result = evaluate_scenario(plan, "UK", meta_with_signup_and_gsa, params_with_signup_and_gsa, ref_with_signup_and_gsa, approval=approval, **IDENTITY)
        gsa_row = result[result["outcome_id"] == "fh_new_gsa"].iloc[0]
        signup_row = result[result["outcome_id"] == "fh_new_signup"].iloc[0]
        assert gsa_row["fh_gsa"] == pytest.approx(gsa_row["predicted_outcome"])
        assert gsa_row["fh_signups"] == pytest.approx(signup_row["predicted_outcome"])
        # The confirmed defect this guards against: fh_gsa must not equal
        # the sum of both outcomes.
        assert gsa_row["fh_gsa"] != pytest.approx(gsa_row["predicted_outcome"] + signup_row["predicted_outcome"])

    def test_gsa_objective_targets_only_gsa_outcome(
        self, meta_with_signup_and_gsa, params_with_signup_and_gsa, approval, ref_with_signup_and_gsa, plan,
    ):
        result = optimize_scenario(
            plan, ["2024-01"], ["TV_Brand"], "UK", meta_with_signup_and_gsa, params_with_signup_and_gsa, ref_with_signup_and_gsa,
            objective="fh_gsa", approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "fh_new_gsa"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_signup_objective_targets_only_signup_outcome(
        self, meta_with_signup_and_gsa, params_with_signup_and_gsa, approval, ref_with_signup_and_gsa, plan,
    ):
        result = optimize_scenario(
            plan, ["2024-01"], ["TV_Brand"], "UK", meta_with_signup_and_gsa, params_with_signup_and_gsa, ref_with_signup_and_gsa,
            objective="fh_signups", approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "fh_new_signup"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)
        # And it must differ from the GSA objective's total - proof the two
        # objectives are actually scoped to different outcome_ids, not
        # coincidentally computing the same number.
        gsa_result = optimize_scenario(
            plan, ["2024-01"], ["TV_Brand"], "UK", meta_with_signup_and_gsa, params_with_signup_and_gsa, ref_with_signup_and_gsa,
            objective="fh_gsa", approval=approval, **IDENTITY,
        )
        assert result["current_objective_value"] != pytest.approx(gsa_result["current_objective_value"])

    def test_signup_objective_raises_if_model_has_no_signup_outcome(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="fh_signups"):
            optimize_scenario(
                spend_plan, ["2024-01"], ["TV_Brand"], "UK", meta, params, reference_context,
                objective="fh_signups", approval=approval, **IDENTITY,
            )


class TestOptimiserTargetValidation:
    """PR E.2 requirement #9: harden target-outcome validation across every
    objective - unknown outcome_ids, metric mismatches, outcomes excluded
    from optimisation (diagnostic role or include_in_optimisation=False),
    and raw-unit weighted mixes are all rejected before the (potentially
    slow) optimiser runs."""

    @pytest.fixture
    def meta_with_diagnostic_outcome(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=["fh_new_gsa", "fh_new_signup", "fh_diag"], channels=["TV_Brand"],
            dna_channels=[], dna_channel_idx=[], non_dna_idx=[0], dna_outcome_id="fh_new_gsa",
            dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            outcome_id_to_product={
                "fh_new_gsa": FAMILY_HISTORY, "fh_new_signup": FAMILY_HISTORY, "fh_diag": FAMILY_HISTORY,
            },
            outcome_id_to_metric={"fh_new_gsa": METRIC_GSA, "fh_new_signup": "Sign-up", "fh_diag": METRIC_GSA},
            outcome_id_to_unit={"fh_new_gsa": "GSA", "fh_new_signup": "sign-up", "fh_diag": "GSA"},
            outcome_id_to_role={"fh_new_gsa": "primary", "fh_new_signup": "primary", "fh_diag": "diagnostic"},
        )

    @pytest.fixture
    def params_3(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
            beta={"fh_new_gsa": {"TV_Brand": 0.1}, "fh_new_signup": {"TV_Brand": 0.2}, "fh_diag": {"TV_Brand": 0.05}},
            pathway_strength={},
            promo_coef={"fh_new_gsa": 0.1, "fh_new_signup": 0.1, "fh_diag": 0.1},
            market_offset={"UK": {"fh_new_gsa": 0.0, "fh_new_signup": 0.0, "fh_diag": 0.0}},
            intercept={"fh_new_gsa": 3.0, "fh_new_signup": 3.0, "fh_diag": 3.0},
            trend_coef={"fh_new_gsa": 0.0, "fh_new_signup": 0.0, "fh_diag": 0.0},
            gamma_fourier={"fh_new_gsa": np.zeros(6), "fh_new_signup": np.zeros(6), "fh_diag": np.zeros(6)},
            alpha={"fh_new_gsa": 5.0, "fh_new_signup": 5.0, "fh_diag": 5.0}, control_coef={}, outcome_control_coef={},
        )

    @pytest.fixture
    def ref_3(self):
        return {
            "2024-01": {
                "trend": 1.0, "fourier": np.zeros(6),
                "promo": {"fh_new_gsa": 0.0, "fh_new_signup": 0.0, "fh_diag": 0.0},
                "controls": {}, "outcome_controls": {},
            },
        }

    @pytest.fixture
    def plan_3(self):
        return {"2024-01": {"TV_Brand": 1000.0}}

    def test_unknown_target_outcome_id_is_rejected(self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3):
        with pytest.raises(ValueError, match="not fitted in this model"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="fh_gsa", target_outcome_ids=["does_not_exist"], approval=approval, **IDENTITY,
            )

    def test_metric_mismatched_target_outcome_id_is_rejected(
        self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3,
    ):
        # Required test case 11 - a sign-up outcome must not be passed into
        # objective="fh_gsa" and bypass metric-aware selection.
        with pytest.raises(ValueError, match="do not match this objective's metric"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="fh_gsa", target_outcome_ids=["fh_new_signup"], approval=approval, **IDENTITY,
            )

    def test_diagnostic_outcome_cannot_be_optimised(self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3):
        # Required test case 12.
        with pytest.raises(ValueError, match="not eligible for optimisation"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="fh_gsa", target_outcome_ids=["fh_diag"], approval=approval, **IDENTITY,
            )

    def test_diagnostic_outcome_excluded_from_default_fh_gsa_total(
        self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3,
    ):
        result = optimize_scenario(
            plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
            objective="fh_gsa", approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["outcome_id"] == "fh_new_gsa"]["predicted_outcome"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_weighted_mix_with_raw_unit_mismatch_is_rejected(
        self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3,
    ):
        # Required test case 13 - GSA and sign-up are different units; a
        # naive uniform-weight mix must be blocked without an explicit
        # assertion that the weights already convert to a common scale.
        with pytest.raises(ValueError, match="different units"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="weighted_mix", weights={"fh_new_gsa": 1.0, "fh_new_signup": 1.0},
                approval=approval, **IDENTITY,
            )

    def test_weighted_mix_with_raw_unit_mismatch_allowed_when_explicitly_value_scaled(
        self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3,
    ):
        result = optimize_scenario(
            plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
            objective="weighted_mix", weights={"fh_new_gsa": 2.0, "fh_new_signup": 0.5},
            assume_value_scaled_weights=True, approval=approval, **IDENTITY,
        )
        assert "success" in result
        assert isinstance(result["objective_value"], float)

    def test_weighted_mix_rejects_negative_weight(self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3):
        with pytest.raises(ValueError, match="non-negative"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="weighted_mix", weights={"fh_new_gsa": -1.0}, approval=approval, **IDENTITY,
            )

    def test_weighted_mix_rejects_unknown_outcome_id(self, meta_with_diagnostic_outcome, params_3, approval, ref_3, plan_3):
        with pytest.raises(ValueError, match="not fitted in this model"):
            optimize_scenario(
                plan_3, ["2024-01"], ["TV_Brand"], "UK", meta_with_diagnostic_outcome, params_3, ref_3,
                objective="weighted_mix", weights={"does_not_exist": 1.0}, approval=approval, **IDENTITY,
            )


class TestValueWeightNeverSilentlyDefaultsToOne:
    """PR E.1's second confirmed defect: a *partial* ltv (some outcome_ids
    priced, others not) must never treat the missing entries as weight 1.0."""

    def test_evaluate_scenario_value_is_none_not_predicted_outcome_for_missing_weight(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0}  # DNA_Kit deliberately has no weight
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        kit_row = result[result["outcome_id"] == "DNA_Kit"].iloc[0]
        assert pd.isna(kit_row["value"])
        assert kit_row["value"] != pytest.approx(kit_row["predicted_outcome"])  # would be true if weight silently defaulted to 1.0
        assert not result["total_value_is_complete"].iloc[0]

    def test_evaluate_scenario_total_value_excludes_unpriced_outcomes(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        new_row = result[result["outcome_id"] == "New"].iloc[0]
        assert result["total_value"].iloc[0] == pytest.approx(new_row["predicted_outcome"] * 2.0)

    def test_evaluate_scenario_partial_ltv_reports_value_status_and_unpriced_ids(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        # PR E.2 requirement #4: a priced subtotal, flagged incomplete, with
        # the exact unpriced outcome_ids named - not just a bare boolean.
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        assert (result["value_status"] == "partial").all()
        assert result["unpriced_outcome_ids"].iloc[0] == ["DNA_Kit"]
        assert not result["total_value_is_complete"].iloc[0]

    def test_evaluate_scenario_full_ltv_coverage_reports_complete_status(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0, "DNA_Kit": 50.0}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        assert (result["value_status"] == "complete").all()
        assert result["unpriced_outcome_ids"].iloc[0] == []
        assert result["total_value_is_complete"].iloc[0]

    def test_evaluate_scenario_rejects_mixed_currency_value_weights(
        self, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        # Required test case 7 (PR E.2): value weights in different explicit
        # currencies must never be silently summed into one total_value.
        catalogue = [
            OutcomeDefinition(
                outcome_id="New", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA,
                source_column="c1", value_currency="USD",
            ),
            OutcomeDefinition(
                outcome_id="DNA_Kit", product=DNA, segment="Combined", metric=METRIC_KIT_SALE,
                source_column="c2", value_currency="GBP",
            ),
        ]
        meta = FHModelMeta(
            markets=["UK"], outcome_ids=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["New", "DNA_Kit"], outcome_catalogue_at_fit=catalogue,
        )
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0, "DNA_Kit": 50.0}
        with pytest.raises(ValueError, match="different currencies"):
            evaluate_scenario(plan, "UK", meta, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)

    def test_evaluate_scenario_allows_same_currency_value_weights(
        self, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        catalogue = [
            OutcomeDefinition(
                outcome_id="New", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA,
                source_column="c1", value_currency="USD",
            ),
            OutcomeDefinition(
                outcome_id="DNA_Kit", product=DNA, segment="Combined", metric=METRIC_KIT_SALE,
                source_column="c2", value_currency="USD",
            ),
        ]
        meta = FHModelMeta(
            markets=["UK"], outcome_ids=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["New", "DNA_Kit"], outcome_catalogue_at_fit=catalogue,
        )
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        ltv = {"New": 2.0, "DNA_Kit": 50.0}
        result = evaluate_scenario(plan, "UK", meta, params_with_kit_segment, ref_with_kit_segment, ltv, approval=approval, **IDENTITY)
        assert (result["value_status"] == "complete").all()

    def test_evaluate_scenario_value_is_none_not_raw_units_when_ltv_entirely_omitted(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        # Required test case 6 (PR E.2) - reverses PR E.1's "entirely
        # omitted ltv falls back to raw units" behaviour: raw GSA/sign-up/kit
        # counts are not monetary value and must never be silently presented
        # as one, even when no ltv was supplied at all.
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, approval=approval, **IDENTITY)
        assert not result["total_value_is_complete"].iloc[0]
        assert (result["value_status"] == "not configured").all()
        assert pd.isna(result["total_value"].iloc[0])
        for _, row in result.iterrows():
            assert pd.isna(row["value"])
            assert row["value"] != pytest.approx(row["predicted_outcome"])

    def test_expected_value_objective_fails_closed_on_incomplete_ltv_coverage(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        with pytest.raises(ValueError, match="requires a value weight for every eligible outcome_id"):
            optimize_scenario(
                plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
                meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
                objective="expected_value", ltv={"New": 2.0}, approval=approval, **IDENTITY,
            )

    def test_expected_value_objective_rejects_negative_weight(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        with pytest.raises(ValueError, match="non-negative"):
            optimize_scenario(
                plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
                meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
                objective="expected_value", ltv={"New": 2.0, "DNA_Kit": -5.0}, approval=approval, **IDENTITY,
            )

    def test_expected_value_objective_succeeds_with_complete_coverage(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            objective="expected_value", ltv={"New": 2.0, "DNA_Kit": 50.0}, approval=approval, **IDENTITY,
        )
        assert "spend_plan" in result

    def test_compare_scenarios_flags_incomplete_value_coverage(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        predicted = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, {"New": 2.0}, approval=approval, **IDENTITY)
        compare_df = compare_scenarios([{"name": "Plan A", "market": "UK", "spend_plan": plan, "predicted": predicted}])
        assert not compare_df["total_value_is_complete"].iloc[0]

    @pytest.fixture
    def meta_with_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], outcome_ids=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_outcome_id="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_outcome_ids=["New", "DNA_Kit"],
        )

    @pytest.fixture
    def params_with_kit_segment(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5, "DNA_Ad": 0.5},
            hill_K={"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            hill_S={"TV_Brand": 1.0, "DNA_Ad": 1.0},
            beta={"New": {"TV_Brand": 0.1, "DNA_Ad": 0.05}, "DNA_Kit": {"TV_Brand": 0.0, "DNA_Ad": 0.2}},
            pathway_strength=pathway_strength_from_flat({"New": 0.3, "DNA_Kit": 0.0}, "DNA_Ad"), promo_coef={"New": 0.1, "DNA_Kit": 0.1},
            market_offset={"UK": {"New": 0.0, "DNA_Kit": 0.0}}, intercept={"New": 3.0, "DNA_Kit": 2.0},
            trend_coef={"New": 0.0, "DNA_Kit": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_Kit": np.zeros(6)},
            alpha={"New": 5.0, "DNA_Kit": 5.0}, control_coef={}, outcome_control_coef={},
        )

    @pytest.fixture
    def ref_with_kit_segment(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "DNA_Kit": 0.0}, "controls": {}, "outcome_controls": {}}}

    @pytest.fixture
    def plan_with_kit_segment(self):
        return {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
