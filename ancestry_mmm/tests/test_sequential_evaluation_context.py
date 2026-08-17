"""Tests for core.sequential_evaluation_context (WP3, `Media-Mix-Lab:
Coding LLM Next Steps Post PR262`, brief §9.5)."""

from __future__ import annotations

import numpy as np
import pytest

from ancestry_mmm.core.sequential_evaluation_context import (
    MismatchedSequentialEvaluationContextError,
    SequentialEvaluationContext,
    compute_incremental_outcome_with_context,
    require_matching_context,
)
from ancestry_mmm.core.sequential_simulation import SequentialSimulationResult


def _context(**overrides) -> SequentialEvaluationContext:
    values = dict(
        model_identity="model-a-fp",
        posterior_identity="trace-fp",
        market="UK",
        canonical_calendar_identity="cal-fp",
        historical_state_source_identity="hist-fp",
        evaluation_semantics_identity="sequential_weekly",
        phasing_policy_identity="calendar_day_overlap_v1",
        future_assumption_identity="future-fp",
        cost_context_identity="cost-fp",
        counterfactual_policy_identity="zero_future_media",
    )
    values.update(overrides)
    return SequentialEvaluationContext(**values)


def _result(mu: np.ndarray) -> SequentialSimulationResult:
    n_weeks = mu.shape[0]
    return SequentialSimulationResult(
        market="UK",
        period_labels=tuple(f"w{i}" for i in range(n_weeks)),
        outcome_ids=("New",),
        mu=mu,
        sat_media=np.zeros((n_weeks, 1)),
        ending_state=None,  # type: ignore[arg-type]
    )


class TestSequentialEvaluationContext:
    def test_requires_every_field_non_empty(self):
        with pytest.raises(ValueError, match="model_identity"):
            _context(model_identity="")

    def test_to_dict_from_dict_round_trip(self):
        ctx = _context()
        restored = SequentialEvaluationContext.from_dict(ctx.to_dict())
        assert restored == ctx

    def test_fingerprint_stable_for_identical_context(self):
        assert _context().fingerprint() == _context().fingerprint()

    def test_fingerprint_changes_when_a_field_changes(self):
        assert _context().fingerprint() != _context(market="IE").fingerprint()

    def test_from_dict_rejects_future_schema_version(self):
        payload = _context().to_dict()
        payload["schema_version"] = 999
        with pytest.raises(ValueError, match="schema_version"):
            SequentialEvaluationContext.from_dict(payload)


class TestRequireMatchingContext:
    def test_identical_contexts_pass(self):
        require_matching_context(_context(), _context())  # must not raise

    def test_mismatched_market_raises(self):
        with pytest.raises(MismatchedSequentialEvaluationContextError, match="market"):
            require_matching_context(_context(), _context(market="IE"))

    def test_mismatched_model_identity_raises(self):
        with pytest.raises(
            MismatchedSequentialEvaluationContextError, match="model_identity"
        ):
            require_matching_context(
                _context(), _context(model_identity="different-model-fp")
            )

    def test_explicitly_allowed_difference_does_not_raise(self):
        require_matching_context(
            _context(),
            _context(cost_context_identity="different-cost-fp"),
            allowed_to_differ=frozenset({"cost_context_identity"}),
        )

    def test_unknown_allowed_field_name_raises(self):
        with pytest.raises(ValueError, match="unknown context field"):
            require_matching_context(
                _context(), _context(), allowed_to_differ=frozenset({"not_a_field"})
            )

    def test_a_difference_outside_the_allowed_set_still_raises(self):
        with pytest.raises(MismatchedSequentialEvaluationContextError):
            require_matching_context(
                _context(),
                _context(market="IE", cost_context_identity="different-cost-fp"),
                allowed_to_differ=frozenset({"cost_context_identity"}),
            )


class TestComputeIncrementalOutcomeWithContext:
    def test_matching_contexts_computes_incremental_outcome(self):
        candidate = _result(np.array([[10.0], [12.0]]))
        reference = _result(np.array([[8.0], [9.0]]))
        incremental = compute_incremental_outcome_with_context(
            candidate, _context(), reference, _context()
        )
        np.testing.assert_allclose(incremental, [[2.0], [3.0]])

    def test_mismatched_contexts_block_even_with_valid_results(self):
        # compute_incremental_outcome alone cannot see this - both results
        # share market/period/outcome identity, so only the context guard
        # catches a headline result built from an unrelated non-decision
        # context (brief §5.6/§9.5).
        candidate = _result(np.array([[10.0]]))
        reference = _result(np.array([[8.0]]))
        with pytest.raises(MismatchedSequentialEvaluationContextError):
            compute_incremental_outcome_with_context(
                candidate,
                _context(),
                reference,
                _context(future_assumption_identity="different-future-fp"),
            )
