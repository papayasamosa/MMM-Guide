"""End-to-end integration tests proving `core.capacity_plan_application`'s
`CapacityLimitDefinition` application (`REQ-CAP-001`/`REQ-OPT-001`
Requirement 4, Decision 18) actually reaches `optimize_scenario`'s real
SLSQP call and changes its returned allocation - not a parallel module
sitting beside the optimiser unused (production-integration phase, per the
2026-08-31 "post-UI/UX business decisions" instructions).

Unlike `test_capacity_plan_application.py` (which tests
`apply_capacity_limits_to_bounds` in isolation against hand-built bounds
arithmetic), this file runs the actual `optimize_scenario` function end to
end and asserts the *optimised spend plan itself* changes, that capacity
limits compose with the governed constraint vocabulary in the same run
(Decision 18's own "both must be usable together" instruction), and that a
capacity limit conflicting with another constraint blocks SLSQP entirely
rather than silently producing a wrong or clamped result.
"""

import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.capacity import CapacityLimitDefinition
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.optimization import (
    CapacityLimitInfeasibleError,
    optimize_scenario,
)
from ancestry_mmm.core.optimization_constraint_vocabulary import (
    GovernedSpendConstraint,
)
from ancestry_mmm.core.predict import FHPosteriorParams

IDENTITY = dict(
    model_run_id="run-capacity-limits",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)


@pytest.fixture
def two_channel_meta() -> FHModelMeta:
    return FHModelMeta(
        markets=["UK"],
        outcome_ids=["New"],
        channels=["TV_Brand", "Digital"],
        dna_channels=[],
        dna_channel_idx=[],
        non_dna_idx=[0],
        dna_outcome_id="New",
        dna_lag_weeks=4,
        unpooled_markets=[],
        control_names=[],
    )


@pytest.fixture
def two_channel_params() -> FHPosteriorParams:
    return FHPosteriorParams(
        decay_rate={"TV_Brand": 0.5, "Digital": 0.5},
        hill_K={"TV_Brand": 1000.0, "Digital": 1000.0},
        hill_S={"TV_Brand": 1.0, "Digital": 1.0},
        beta={"New": {"TV_Brand": 0.1, "Digital": 0.1}},
        pathway_strength={},
        promo_coef={"New": 0.1},
        market_offset={"UK": {"New": 0.0}},
        intercept={"New": 3.0},
        trend_coef={"New": 0.0},
        gamma_fourier={"New": np.zeros(6)},
        alpha={"New": 5.0},
        control_coef={},
        outcome_control_coef={},
    )


@pytest.fixture
def reference_context():
    return {
        "2024-01": {
            "trend": 1.0,
            "fourier": np.zeros(6),
            "promo": {"New": 0.0},
            "controls": {},
            "outcome_controls": {},
        }
    }


@pytest.fixture
def spend_plan():
    return {"2024-01": {"TV_Brand": 500.0, "Digital": 500.0}}


@pytest.fixture
def approval() -> ModelApproval:
    return ModelApproval(approved_by="Jane Analyst", **IDENTITY)


def _optimize(meta, params, spend_plan, reference_context, approval, **kwargs):
    return optimize_scenario(
        spend_plan,
        ["2024-01"],
        ["TV_Brand", "Digital"],
        "UK",
        meta,
        params,
        reference_context,
        objective="fh_gsa",
        approval=approval,
        governance_mode="exploratory",
        **IDENTITY,
        **kwargs,
    )


class TestCapacityLimitsChangeRealAllocation:
    def test_spend_limit_forces_budget_toward_other_channel(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
    ):
        baseline = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
        )
        baseline_tv = baseline["spend_plan"]["2024-01"]["TV_Brand"]

        # A deep cut, not just "a bit below baseline" - see the identical
        # empirical finding recorded for the governed-constraint vocabulary
        # test (test_optimization_governed_constraints_integration.py):
        # with a whole-plan budget-conservation constraint, a shallow cap
        # is not guaranteed to actually bind at the true SLSQP optimum.
        cap_value = max(0.0, baseline_tv * 0.1)
        limit = CapacityLimitDefinition(
            limit_id="tv-cap",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV_Brand",
            value_by_period={"2024-01": cap_value},
        )

        capped = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
            capacity_limits=[limit],
        )
        capped_tv = capped["spend_plan"]["2024-01"]["TV_Brand"]
        capped_digital = capped["spend_plan"]["2024-01"]["Digital"]
        baseline_digital = baseline["spend_plan"]["2024-01"]["Digital"]

        assert capped_tv <= cap_value + 1e-6
        assert capped_tv < baseline_tv, (
            "a CapacityLimitDefinition must actually reach the real SLSQP "
            "bounds and change the optimised allocation, not sit beside "
            "the optimiser unused"
        )
        assert capped_digital > baseline_digital
        assert capped_tv + capped_digital == pytest.approx(
            baseline_tv + baseline_digital
        )
        assert capped["capacity_disclosures"], "capacity_disclosures must be populated"
        assert (
            capped["capacity_plan_application_version"]
            == "capacity-plan-application-v1"
        )

    def test_composes_with_governed_constraint_vocabulary_in_one_run(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
    ):
        """Decision 18's own explicit instruction: capacity limits and the
        constraint vocabulary must be usable together in the same
        optimisation run, never a separate/duplicate rule set."""
        limit = CapacityLimitDefinition(
            limit_id="tv-cap",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV_Brand",
            value_by_period={"2024-01": 50.0},
        )
        result = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
            governed_constraints=[
                GovernedSpendConstraint(
                    kind="minimum_spend",
                    channel="Digital",
                    month="2024-01",
                    value=100.0,
                    label="digital floor",
                )
            ],
            capacity_limits=[limit],
        )
        assert result["spend_plan"]["2024-01"]["TV_Brand"] <= 50.0 + 1e-6
        assert result["spend_plan"]["2024-01"]["Digital"] >= 100.0 - 1e-6
        assert result["governed_constraint_disclosures"]
        assert result["capacity_disclosures"]

    def test_availability_toggle_off_forces_zero_spend(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
    ):
        limit = CapacityLimitDefinition(
            limit_id="tv-availability",
            limit_version=1,
            kind="availability_toggle",
            unit="boolean",
            applies_to="TV_Brand",
            value_by_period={"2024-01": 0.0},
        )
        result = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
            capacity_limits=[limit],
        )
        assert result["spend_plan"]["2024-01"]["TV_Brand"] == pytest.approx(0.0)
        assert result["spend_plan"]["2024-01"]["Digital"] == pytest.approx(1000.0)


class TestCapacityLimitsInfeasibility:
    def test_conflicting_capacity_limit_and_constraint_raise_before_slsqp_runs(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
        monkeypatch,
    ):
        import ancestry_mmm.core.optimization as optimization_module

        def _fail_if_called(*args, **kwargs):
            raise AssertionError(
                "minimize() must never run when a capacity limit conflicts "
                "with another constraint - Requirement 4/5 discipline "
                "requires failing before the slow SLSQP call, not after"
            )

        monkeypatch.setattr(optimization_module, "minimize", _fail_if_called)

        limit = CapacityLimitDefinition(
            limit_id="tv-cap",
            limit_version=1,
            kind="spend_limit",
            unit="GBP",
            applies_to="TV_Brand",
            value_by_period={"2024-01": 100.0},
        )
        with pytest.raises(CapacityLimitInfeasibleError, match="infeasible"):
            _optimize(
                two_channel_meta,
                two_channel_params,
                spend_plan,
                reference_context,
                approval,
                governed_constraints=[
                    GovernedSpendConstraint(
                        kind="minimum_spend",
                        channel="TV_Brand",
                        month="2024-01",
                        value=800.0,
                        label="floor above the cap",
                    )
                ],
                capacity_limits=[limit],
            )
