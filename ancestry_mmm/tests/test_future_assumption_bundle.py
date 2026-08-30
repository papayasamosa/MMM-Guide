"""Tests for `ancestry_mmm.core.planning.future_assumption_bundle`
(Decision 14 continuation: future-assumption bundle architecture). See
`docs/future_assumption_bundle_architecture_decision_record.md` for the
decisions (B, M, F) these tests verify."""

import dataclasses

import numpy as np
import pytest

from ancestry_mmm.core.planning.future_assumption_bundle import (
    EXTERNAL_FORECASTER_INTEGRATION_POLICY,
    FUTURE_ASSUMPTION_BUNDLE_MATERIALITY_POLICY,
    FutureAssumptionBundle,
    current_bundle_versions,
    new_bundle_version,
    summarise_bundle_control_provenance,
)
from ancestry_mmm.core.planning.future_context import (
    EXPLICIT_ASSUMPTION,
    HOLD_LAST_OBSERVED_ASSUMPTION,
    OFFICIAL_MODE,
    FutureContextResult,
    FutureControlAssumption,
)

# Forbidden verdict-shaped field-name fragments - mirrors
# core.calibration_comparison's own established regression test exactly
# (decision M3: never a fabricated materiality score or verdict field).
FORBIDDEN_FIELD_NAME_FRAGMENTS = (
    "verdict",
    "recommend",
    "is_material",
    "materiality_score",
    "pass_fail",
    "should_block",
)


def _context(
    market: str, control_assumptions=(), n_weeks: int = 4
) -> FutureContextResult:
    return FutureContextResult(
        market=market,
        period_labels=tuple(f"w{i}" for i in range(n_weeks)),
        mode=OFFICIAL_MODE,
        trend=np.zeros(n_weeks),
        fourier=np.zeros((n_weeks, 4)),
        promo=np.zeros((n_weeks, 1)),
        outcome_ids=("New",),
        control_names=tuple(a.name for a in control_assumptions),
        X_controls=np.zeros((n_weeks, len(control_assumptions))),
        outcome_controls={},
        outcome_control_names={},
        control_assumptions=tuple(control_assumptions),
    )


class TestFutureAssumptionBundle:
    def test_requires_at_least_one_context(self):
        with pytest.raises(ValueError, match="at least one context"):
            FutureAssumptionBundle(bundle_id="b1", bundle_version=1, context_by_key={})

    def test_requires_bundle_id(self):
        with pytest.raises(ValueError, match="bundle_id"):
            FutureAssumptionBundle(
                bundle_id="", bundle_version=1, context_by_key={"UK": _context("UK")}
            )

    def test_decision_ready_true_when_all_contexts_ready(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={
                "UK": _context(
                    "UK",
                    [FutureControlAssumption("promo_flag", EXPLICIT_ASSUMPTION, True)],
                ),
                "US": _context(
                    "US",
                    [FutureControlAssumption("promo_flag", EXPLICIT_ASSUMPTION, True)],
                ),
            },
        )
        assert bundle.is_decision_ready is True

    def test_decision_ready_false_if_any_context_used_hold_last_observed(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={
                "UK": _context(
                    "UK",
                    [FutureControlAssumption("promo_flag", EXPLICIT_ASSUMPTION, True)],
                ),
                "US": _context(
                    "US",
                    [
                        FutureControlAssumption(
                            "promo_flag", HOLD_LAST_OBSERVED_ASSUMPTION, False
                        )
                    ],
                ),
            },
        )
        assert bundle.is_decision_ready is False

    def test_fingerprint_uses_each_contexts_own_fingerprint(self):
        context_uk = _context("UK")
        bundle = FutureAssumptionBundle(
            bundle_id="b1", bundle_version=1, context_by_key={"UK": context_uk}
        )
        # Same bundle, same underlying context -> same fingerprint (determinism).
        bundle_again = FutureAssumptionBundle(
            bundle_id="b1", bundle_version=1, context_by_key={"UK": context_uk}
        )
        assert bundle.fingerprint() == bundle_again.fingerprint()

    def test_fingerprint_changes_when_context_changes(self):
        bundle_a = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={"UK": _context("UK", n_weeks=4)},
        )
        bundle_b = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={"UK": _context("UK", n_weeks=5)},
        )
        assert bundle_a.fingerprint() != bundle_b.fingerprint()

    def test_new_version_increments(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1", bundle_version=1, context_by_key={"UK": _context("UK")}
        )
        updated = new_bundle_version(bundle, notes="revised")
        assert updated.bundle_version == 2
        assert updated.notes == "revised"

    def test_new_version_rejects_identity_change(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1", bundle_version=1, context_by_key={"UK": _context("UK")}
        )
        with pytest.raises(ValueError):
            new_bundle_version(bundle, bundle_id="other")

    def test_current_versions_resolves_latest(self):
        v1 = FutureAssumptionBundle(
            bundle_id="b1", bundle_version=1, context_by_key={"UK": _context("UK")}
        )
        v2 = new_bundle_version(v1, notes="v2")
        current = current_bundle_versions([v1, v2])
        assert len(current) == 1
        assert current[0].bundle_version == 2


class TestSummariseBundleControlProvenance:
    def test_separates_explicit_and_exploratory(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={
                "UK": _context(
                    "UK",
                    [
                        FutureControlAssumption(
                            "promo_flag", EXPLICIT_ASSUMPTION, True
                        ),
                        FutureControlAssumption(
                            "macro_index", HOLD_LAST_OBSERVED_ASSUMPTION, False
                        ),
                    ],
                )
            },
        )
        summary = summarise_bundle_control_provenance(bundle)
        assert summary.analyst_supplied_control_names == ("promo_flag",)
        assert summary.exploratory_hold_last_observed_control_names == ("macro_index",)

    def test_deduplicates_across_contexts(self):
        bundle = FutureAssumptionBundle(
            bundle_id="b1",
            bundle_version=1,
            context_by_key={
                "UK": _context(
                    "UK",
                    [FutureControlAssumption("promo_flag", EXPLICIT_ASSUMPTION, True)],
                ),
                "US": _context(
                    "US",
                    [FutureControlAssumption("promo_flag", EXPLICIT_ASSUMPTION, True)],
                ),
            },
        )
        summary = summarise_bundle_control_provenance(bundle)
        assert summary.analyst_supplied_control_names == ("promo_flag",)


class TestGovernedPolicies:
    def test_materiality_policy_is_m3(self):
        assert (
            FUTURE_ASSUMPTION_BUNDLE_MATERIALITY_POLICY
            == "M3_disclosed_ungraded_evidence_only"
        )

    def test_forecaster_policy_is_f1(self):
        assert EXTERNAL_FORECASTER_INTEGRATION_POLICY == "F1_no_production_integration"


class TestNoVerdictFieldAnywhere:
    """Decision M3: mirrors core.calibration_comparison's own established
    test - never a fabricated materiality score or verdict field."""

    def test_no_dataclass_in_this_module_has_a_verdict_shaped_field(self):
        import ancestry_mmm.core.planning.future_assumption_bundle as module

        checked_any = False
        for name in dir(module):
            obj = getattr(module, name)
            if dataclasses.is_dataclass(obj):
                checked_any = True
                for f in dataclasses.fields(obj):
                    lowered = f.name.lower()
                    for fragment in FORBIDDEN_FIELD_NAME_FRAGMENTS:
                        assert fragment not in lowered, (
                            f"{obj.__name__}.{f.name} looks like a forbidden "
                            f"verdict-shaped field ('{fragment}') - decision M3 "
                            "requires disclosed, ungraded evidence only."
                        )
        assert checked_any, "expected at least one dataclass in this module"
