import numpy as np
import pytest

from ancestry_mmm.core.approval import ApprovalMismatchError, ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.market_specific_predict import FHMarketSpecificPosteriorParams
from ancestry_mmm.core.optimization import compare_scenarios, evaluate_scenario, optimize_scenario, VALID_OBJECTIVES
from ancestry_mmm.core.predict import FHPosteriorParams

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


@pytest.fixture
def meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"], segments=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
        unpooled_markets=[], control_names=[],
    )


@pytest.fixture
def params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
        beta={"New": {"TV_Brand": 0.1}}, halo_strength={"New": 0.0}, promo_coef={"New": 0.1},
        market_offset={"UK": {"New": 0.0}}, intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0}, control_coef={}, segment_control_coef={},
    )


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", **IDENTITY)


@pytest.fixture
def reference_context():
    return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0}, "controls": {}, "segment_controls": {}}}


@pytest.fixture
def spend_plan():
    return {"2024-01": {"TV_Brand": 1000.0}}


@pytest.fixture
def market_specific_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK", "Australia"], segments=["New"], channels=["TV_Brand"], dna_channels=[],
        dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
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
        halo_strength={"New": 0.0}, promo_coef={"New": 0.1},
        market_offset={m: {"New": 0.0} for m in markets},
        intercept={"New": 3.0}, trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)}, alpha={"New": 5.0},
        control_coef={}, segment_control_coef={},
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
        assert set(result.columns) >= {"month", "segment", "predicted_gsa", "value"}

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
        assert uk_result["predicted_gsa"].iloc[0] != pytest.approx(au_result["predicted_gsa"].iloc[0])

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
        total_gsa = result["predicted_gsa"].sum()
        assert result["avg_cpa"].iloc[0] == pytest.approx(total_spend / total_gsa)

    def test_avg_cpa_is_repeated_across_every_segment_row_for_the_same_month(
        self, market_specific_meta, market_specific_params, approval, reference_context,
    ):
        # A multi-segment month should carry one avg_cpa value (computed from the
        # month's *total* predicted GSA across segments), not a different one per segment row.
        meta_two_segments = FHModelMeta(
            markets=["UK"], segments=["New", "Winback"], channels=["TV_Brand"], dna_channels=[],
            dna_channel_idx=[], non_dna_idx=[0], dna_segment="New", dna_lag_weeks=4,
            unpooled_markets=[], control_names=[],
        )
        params = FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5}, hill_K={"TV_Brand": 1000.0}, hill_S={"TV_Brand": 1.0},
            beta={"New": {"TV_Brand": 0.1}, "Winback": {"TV_Brand": 0.05}},
            halo_strength={"New": 0.0, "Winback": 0.0}, promo_coef={"New": 0.1, "Winback": 0.1},
            market_offset={"UK": {"New": 0.0, "Winback": 0.0}}, intercept={"New": 3.0, "Winback": 2.0},
            trend_coef={"New": 0.0, "Winback": 0.0},
            gamma_fourier={"New": np.zeros(6), "Winback": np.zeros(6)},
            alpha={"New": 5.0, "Winback": 5.0}, control_coef={}, segment_control_coef={},
        )
        ref = {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "Winback": 0.0}, "controls": {}, "segment_controls": {}}}
        result = evaluate_scenario(
            {"2024-01": {"TV_Brand": 1000.0}}, "UK", meta_two_segments, params, ref,
            approval=approval, **IDENTITY,
        )
        assert len(result) == 2  # one row per segment
        assert result["avg_cpa"].nunique() == 1


class TestProductAwareScenarioOutputs:
    """avg_cpa must be Family-History-scoped (never a dollars-per-mixed-unit
    blend of FH GSAs and DNA kits), with dna_avg_cpa broken out separately -
    the instruction document's audit-confirmed defect this fixes."""

    @pytest.fixture
    def meta_with_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], segments=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_segment="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_segments=["New", "DNA_Kit"],
        )

    @pytest.fixture
    def params_with_kit_segment(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5, "DNA_Ad": 0.5},
            hill_K={"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            hill_S={"TV_Brand": 1.0, "DNA_Ad": 1.0},
            beta={"New": {"TV_Brand": 0.1, "DNA_Ad": 0.05}, "DNA_Kit": {"TV_Brand": 0.0, "DNA_Ad": 0.2}},
            halo_strength={"New": 0.3, "DNA_Kit": 0.0}, promo_coef={"New": 0.1, "DNA_Kit": 0.1},
            market_offset={"UK": {"New": 0.0, "DNA_Kit": 0.0}}, intercept={"New": 3.0, "DNA_Kit": 2.0},
            trend_coef={"New": 0.0, "DNA_Kit": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_Kit": np.zeros(6)},
            alpha={"New": 5.0, "DNA_Kit": 5.0}, control_coef={}, segment_control_coef={},
        )

    @pytest.fixture
    def ref_with_kit_segment(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "DNA_Kit": 0.0}, "controls": {}, "segment_controls": {}}}

    def test_fh_gsa_excludes_kit_only_segments_dna_kits_includes_only_them(
        self, meta_with_kit_segment, params_with_kit_segment, approval, ref_with_kit_segment,
    ):
        plan = {"2024-01": {"TV_Brand": 1000.0, "DNA_Ad": 500.0}}
        result = evaluate_scenario(plan, "UK", meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment, approval=approval, **IDENTITY)
        new_row = result[result["segment"] == "New"].iloc[0]
        kit_row = result[result["segment"] == "DNA_Kit"].iloc[0]
        assert new_row["fh_gsa"] == pytest.approx(new_row["predicted_gsa"])
        assert new_row["dna_kits"] == pytest.approx(kit_row["predicted_gsa"])
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
        assert compare_df["total_value"].iloc[0] == pytest.approx(predicted["value"].sum())

    def test_compare_scenarios_falls_back_when_predicted_has_no_product_split(self, meta, params, approval, spend_plan, reference_context):
        # Defensive against a hand-built/legacy `predicted` DataFrame that
        # predates the fh_gsa/dna_kits columns.
        predicted = evaluate_scenario(spend_plan, "UK", meta, params, reference_context, approval=approval, **IDENTITY)
        legacy_predicted = predicted.drop(columns=["fh_gsa", "dna_kits"])
        compare_df = compare_scenarios([{"name": "Legacy", "market": "UK", "spend_plan": spend_plan, "predicted": legacy_predicted}])
        assert compare_df["total_fh_gsa"].iloc[0] == pytest.approx(legacy_predicted["predicted_gsa"].sum())
        assert compare_df["total_dna_kits"].iloc[0] == pytest.approx(0.0)


class TestExplicitOptimisationObjectives:
    """optimize_scenario's objective must be one of VALID_OBJECTIVES - no
    generic "maximise volume" that silently sums FH GSAs and DNA kits (the
    instruction document's audit-confirmed defect)."""

    @pytest.fixture
    def meta_with_kit_segment(self) -> FHModelMeta:
        return FHModelMeta(
            markets=["UK"], segments=["New", "DNA_Kit"], channels=["TV_Brand", "DNA_Ad"],
            dna_channels=["DNA_Ad"], dna_channel_idx=[1], non_dna_idx=[0],
            dna_segment="New", dna_lag_weeks=4, unpooled_markets=[], control_names=[],
            direct_dna_segments=["New", "DNA_Kit"],
        )

    @pytest.fixture
    def params_with_kit_segment(self) -> FHPosteriorParams:
        return FHPosteriorParams(
            decay_rate={"TV_Brand": 0.5, "DNA_Ad": 0.5},
            hill_K={"TV_Brand": 1000.0, "DNA_Ad": 500.0},
            hill_S={"TV_Brand": 1.0, "DNA_Ad": 1.0},
            beta={"New": {"TV_Brand": 0.1, "DNA_Ad": 0.05}, "DNA_Kit": {"TV_Brand": 0.0, "DNA_Ad": 0.2}},
            halo_strength={"New": 0.3, "DNA_Kit": 0.0}, promo_coef={"New": 0.1, "DNA_Kit": 0.1},
            market_offset={"UK": {"New": 0.0, "DNA_Kit": 0.0}}, intercept={"New": 3.0, "DNA_Kit": 2.0},
            trend_coef={"New": 0.0, "DNA_Kit": 0.0},
            gamma_fourier={"New": np.zeros(6), "DNA_Kit": np.zeros(6)},
            alpha={"New": 5.0, "DNA_Kit": 5.0}, control_coef={}, segment_control_coef={},
        )

    @pytest.fixture
    def ref_with_kit_segment(self):
        return {"2024-01": {"trend": 1.0, "fourier": np.zeros(6), "promo": {"New": 0.0, "DNA_Kit": 0.0}, "controls": {}, "segment_controls": {}}}

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
        expected = float(current_predicted[current_predicted["segment"] == "New"]["predicted_gsa"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_dna_kits_objective_raises_when_model_has_no_kit_only_segments(self, meta, params, approval, spend_plan, reference_context):
        with pytest.raises(ValueError, match="no DNA-kit segments"):
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
        expected = float(current_predicted[current_predicted["segment"] == "DNA_Kit"]["predicted_gsa"].sum())
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

    def test_target_segments_narrows_fh_gsa_to_a_single_segment(
        self, meta_with_kit_segment, params_with_kit_segment, approval, plan_with_kit_segment, ref_with_kit_segment,
    ):
        result = optimize_scenario(
            plan_with_kit_segment, ["2024-01"], ["TV_Brand", "DNA_Ad"], "UK",
            meta_with_kit_segment, params_with_kit_segment, ref_with_kit_segment,
            objective="fh_gsa", target_segments=["New"], approval=approval, **IDENTITY,
        )
        current_predicted = result["current_predicted"]
        expected = float(current_predicted[current_predicted["segment"] == "New"]["predicted_gsa"].sum())
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
        expected = 3.0 * float(current_predicted[current_predicted["segment"] == "New"]["predicted_gsa"].sum())
        assert result["current_objective_value"] == pytest.approx(expected)

    def test_all_valid_objectives_are_exercised_above(self):
        # Documentation-level check that this test class covers every
        # VALID_OBJECTIVES value, so a future addition doesn't go untested.
        assert set(VALID_OBJECTIVES) == {"fh_gsa", "dna_kits", "weighted_mix", "expected_value"}
