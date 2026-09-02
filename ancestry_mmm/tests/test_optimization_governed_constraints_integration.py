"""End-to-end integration tests proving `core.optimization_constraint_
vocabulary`'s `GovernedSpendConstraint` vocabulary (`REQ-OPT-001`
Requirement 2, Decision 16) actually reaches `optimize_scenario`'s real
SLSQP call and changes its returned allocation - not a parallel vocabulary
sitting beside the optimiser unused (production-integration phase, per the
2026-08-31 "post-UI/UX business decisions" instructions).

Unlike `test_optimization_constraint_vocabulary.py` (which tests
`resolve_governed_constraints` in isolation against hand-built bounds
arithmetic), this file runs the actual `optimize_scenario` function end to
end with a real two-channel model and asserts the *optimised spend plan
itself* differs between two governed-constraint configurations, and that
an infeasible governed-constraint pair blocks the SLSQP call entirely
rather than silently producing a wrong or clamped result.
"""

import numpy as np
import pytest

from ancestry_mmm.core.approval import ModelApproval
from ancestry_mmm.core.hierarchical_model import FHModelMeta
from ancestry_mmm.core.optimization import (
    GovernedConstraintInfeasibleError,
    optimize_scenario,
)
from ancestry_mmm.core.optimization_constraint_vocabulary import (
    GovernedSpendConstraint,
)
from ancestry_mmm.core.predict import FHPosteriorParams

IDENTITY = dict(
    model_run_id="run-governed-constraints",
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
    # Identical response shape on both channels so the unconstrained
    # optimum is determined purely by the (also identical) starting spend
    # split - i.e. SLSQP has no reason to move budget unless a constraint
    # forces it to. This isolates the constraint's effect cleanly.
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


class TestGovernedConstraintsChangeRealAllocation:
    def test_maximum_spend_constraint_forces_budget_toward_other_channel(
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
        # A cap set comfortably below the unconstrained TV_Brand allocation -
        # with conserve_total_budget=True (the default), forcing it down
        # must move the freed budget to Digital, not just shrink the total.
        cap_value = max(0.0, baseline_tv - 200.0)

        capped = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
            governed_constraints=[
                GovernedSpendConstraint(
                    kind="maximum_spend",
                    channel="TV_Brand",
                    month="2024-01",
                    value=cap_value,
                    label="test cap",
                )
            ],
        )
        capped_tv = capped["spend_plan"]["2024-01"]["TV_Brand"]
        capped_digital = capped["spend_plan"]["2024-01"]["Digital"]
        baseline_digital = baseline["spend_plan"]["2024-01"]["Digital"]

        assert capped_tv <= cap_value + 1e-6
        assert capped_tv < baseline_tv, (
            "the governed maximum_spend constraint must actually reach the "
            "real SLSQP bounds and change the optimised allocation, not sit "
            "beside the optimiser unused"
        )
        assert capped_digital > baseline_digital, (
            "the total budget is conserved - spend capped out of TV_Brand "
            "must reappear in Digital, not vanish"
        )
        # Total budget conserved exactly (conserve_total_budget=True default).
        assert capped_tv + capped_digital == pytest.approx(
            baseline_tv + baseline_digital
        )

        # Requirement 4: binding-constraint disclosure names this cell as
        # actually binding at the solution, not just "supplied".
        disclosures = capped["governed_constraint_disclosures"]
        assert disclosures, "governed_constraint_disclosures must be populated"
        cap_disclosure = [d for d in disclosures if d["kind"] == "maximum_spend"]
        assert cap_disclosure and cap_disclosure[0]["binding"] is True
        assert (
            capped["governed_constraint_vocabulary_version"]
            == "constraint-kind-vocabulary-v1"
        )

    def test_no_governed_constraints_yields_empty_disclosures(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
    ):
        result = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
        )
        assert result["governed_constraint_disclosures"] == []
        assert result["governed_constraint_vocabulary_version"] is None

    def test_zero_spend_kind_actually_zeroes_the_channel(
        self,
        two_channel_meta,
        two_channel_params,
        spend_plan,
        reference_context,
        approval,
    ):
        result = _optimize(
            two_channel_meta,
            two_channel_params,
            spend_plan,
            reference_context,
            approval,
            governed_constraints=[
                GovernedSpendConstraint(
                    kind="zero_spend",
                    channel="TV_Brand",
                    month="2024-01",
                    label="test zero",
                )
            ],
        )
        assert result["spend_plan"]["2024-01"]["TV_Brand"] == pytest.approx(0.0)
        # All conserved budget lands on the only remaining free channel.
        assert result["spend_plan"]["2024-01"]["Digital"] == pytest.approx(1000.0)


class TestGovernedConstraintsInfeasibility:
    def test_conflicting_governed_constraints_raise_before_slsqp_runs(
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
                "minimize() must never run when governed constraints are "
                "infeasible - Requirement 5 requires failing before the "
                "slow SLSQP call, not after"
            )

        monkeypatch.setattr(optimization_module, "minimize", _fail_if_called)

        with pytest.raises(GovernedConstraintInfeasibleError, match="infeasible"):
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
                        label="floor",
                    ),
                    GovernedSpendConstraint(
                        kind="maximum_spend",
                        channel="TV_Brand",
                        month="2024-01",
                        value=200.0,
                        label="cap",
                    ),
                ],
            )
