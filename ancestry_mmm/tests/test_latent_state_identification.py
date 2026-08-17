"""REQ-LATENT-001 (Work Package 3, second record): tests for
core.latent_state_identification."""

from __future__ import annotations

import pytest

from ancestry_mmm.core.latent_state_identification import (
    LATENT_IDENTIFICATION_STATUS_IDENTIFIED,
    LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED,
    LATENT_IDENTIFICATION_STATUS_REVIEW_REQUIRED,
    LATENT_IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
    LATENT_STATE_IDENTIFICATION_DISCLAIMER,
    STRATEGY_ANCHORED_TO_OBSERVED,
    LatentStateIdentificationDeclaration,
    LatentStateIdentificationResult,
    assess_latent_state_identification,
    is_eligible_for_official_use,
)


def _declaration(latent_state_id: str = "search_latent_branded_demand"):
    return LatentStateIdentificationDeclaration(
        latent_state_id=latent_state_id,
        strategy_kind=STRATEGY_ANCHORED_TO_OBSERVED,
        description="anchored to observed branded search clicks at a fixed CTR",
        anchor_reference="branded_search_clicks",
    )


# ---------------------------------------------------------------------------
# LatentStateIdentificationDeclaration validation / round-trip
# ---------------------------------------------------------------------------


class TestDeclarationValidation:
    def test_requires_latent_state_id(self):
        with pytest.raises(ValueError, match="latent_state_id is required"):
            LatentStateIdentificationDeclaration(
                latent_state_id="",
                strategy_kind=STRATEGY_ANCHORED_TO_OBSERVED,
                description="x",
            )

    def test_rejects_invalid_strategy_kind(self):
        with pytest.raises(ValueError, match="invalid strategy_kind"):
            LatentStateIdentificationDeclaration(
                latent_state_id="s1",
                strategy_kind="not_a_kind",
                description="x",
            )

    def test_requires_description(self):
        with pytest.raises(ValueError, match="description is required"):
            LatentStateIdentificationDeclaration(
                latent_state_id="s1",
                strategy_kind=STRATEGY_ANCHORED_TO_OBSERVED,
                description="",
            )

    def test_round_trip(self):
        original = _declaration()
        restored = LatentStateIdentificationDeclaration.from_dict(original.to_dict())
        assert restored == original


# ---------------------------------------------------------------------------
# No declaration -> not_identified regardless of chain_draws
# ---------------------------------------------------------------------------


class TestNoDeclaration:
    def test_missing_declaration_is_not_identified(self):
        result = assess_latent_state_identification("s1", None)
        assert result.status == LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED
        assert result.declaration is None

    def test_missing_declaration_ignores_supplied_chain_draws(self):
        result = assess_latent_state_identification(
            "s1", None, chain_draws=((1.0, 2.0), (1.0, 2.0))
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED

    def test_disclaimer_always_present(self):
        result = assess_latent_state_identification("s1", None)
        assert result.disclaimer == LATENT_STATE_IDENTIFICATION_DISCLAIMER


# ---------------------------------------------------------------------------
# Declared but unverified
# ---------------------------------------------------------------------------


class TestDeclaredButUnverified:
    def test_declared_without_chain_draws_is_review_required(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand", _declaration()
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_REVIEW_REQUIRED
        assert result.declaration is not None


# ---------------------------------------------------------------------------
# Insufficient chains for empirical check
# ---------------------------------------------------------------------------


class TestInsufficientChains:
    def test_single_chain_is_unsupported(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.1, 0.9),),
        )
        assert (
            result.status == LATENT_IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER
        )
        assert result.chains_checked == 1

    def test_rejects_empty_chain(self):
        with pytest.raises(ValueError, match="at least one draw"):
            assess_latent_state_identification(
                "search_latent_branded_demand",
                _declaration(),
                chain_draws=((1.0, 1.1), ()),
            )


# ---------------------------------------------------------------------------
# Sign-flip detection across chains
# ---------------------------------------------------------------------------


class TestSignFlipDetection:
    def test_disagreeing_signs_across_chains_is_not_identified(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.1, 0.9), (-1.0, -1.1, -0.9)),
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED
        assert result.sign_flip_detected is True
        assert result.chains_checked == 2

    def test_three_chains_one_disagreeing_is_flagged(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.2), (1.1, 0.9), (-1.0, -1.2)),
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED
        assert result.sign_flip_detected is True

    def test_zero_median_chain_counts_as_a_distinct_sign(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.0), (0.0, 0.0)),
        )
        assert result.sign_flip_detected is True


# ---------------------------------------------------------------------------
# Stable across chains -> identified
# ---------------------------------------------------------------------------


class TestStableAcrossChains:
    def test_agreeing_signs_is_identified(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.1, 0.9), (1.05, 0.95, 1.0)),
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_IDENTIFIED
        assert result.sign_flip_detected is False

    def test_scale_drift_ratio_is_reported_descriptively(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((2.0, 2.0), (4.0, 4.0)),
        )
        assert result.status == LATENT_IDENTIFICATION_STATUS_IDENTIFIED
        assert result.scale_drift_ratio == pytest.approx(2.0)

    def test_identified_result_still_carries_limitations(self):
        result = assess_latent_state_identification(
            "search_latent_branded_demand",
            _declaration(),
            chain_draws=((1.0, 1.0), (1.0, 1.0)),
        )
        assert result.limitations


# ---------------------------------------------------------------------------
# Caller contract errors
# ---------------------------------------------------------------------------


class TestCallerContractErrors:
    def test_requires_latent_state_id(self):
        with pytest.raises(ValueError, match="latent_state_id is required"):
            assess_latent_state_identification("", None)

    def test_mismatched_declaration_latent_state_id_raises(self):
        with pytest.raises(ValueError, match="does not match"):
            assess_latent_state_identification(
                "other_state", _declaration("search_latent_branded_demand")
            )


# ---------------------------------------------------------------------------
# Fail-closed use-eligibility gate
# ---------------------------------------------------------------------------


class TestUseEligibilityGate:
    def test_identified_is_eligible(self):
        result = assess_latent_state_identification(
            "s1", _declaration("s1"), chain_draws=((1.0, 1.0), (1.0, 1.0))
        )
        assert is_eligible_for_official_use(result) is True

    def test_not_identified_is_not_eligible(self):
        result = assess_latent_state_identification("s1", None)
        assert is_eligible_for_official_use(result) is False

    def test_review_required_is_not_eligible(self):
        result = assess_latent_state_identification("s1", _declaration("s1"))
        assert is_eligible_for_official_use(result) is False

    def test_unsupported_is_not_eligible(self):
        result = assess_latent_state_identification(
            "s1", _declaration("s1"), chain_draws=((1.0, 1.0),)
        )
        assert is_eligible_for_official_use(result) is False


# ---------------------------------------------------------------------------
# LatentStateIdentificationResult validation / round-trip
# ---------------------------------------------------------------------------


class TestResultValidation:
    def test_requires_latent_state_id(self):
        with pytest.raises(ValueError, match="latent_state_id is required"):
            LatentStateIdentificationResult(
                latent_state_id="",
                status=LATENT_IDENTIFICATION_STATUS_IDENTIFIED,
                declaration=None,
            )

    def test_rejects_invalid_status(self):
        with pytest.raises(ValueError, match="invalid status"):
            LatentStateIdentificationResult(
                latent_state_id="s1",
                status="not_a_status",
                declaration=None,
            )

    def test_round_trip_with_declaration(self):
        original = assess_latent_state_identification(
            "s1", _declaration("s1"), chain_draws=((1.0, 1.1), (0.9, 1.0))
        )
        restored = LatentStateIdentificationResult.from_dict(original.to_dict())
        assert restored == original

    def test_round_trip_without_declaration(self):
        original = assess_latent_state_identification("s1", None)
        restored = LatentStateIdentificationResult.from_dict(original.to_dict())
        assert restored == original
