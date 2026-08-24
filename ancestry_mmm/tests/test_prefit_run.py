"""Tests for `core.prefit_run` (`REQ-PREFIT-001`, Work Package 1 correction):
the one consolidated pre-fit-run readiness state and the durable `PrefitRun`
persistence contract.

These tests exist specifically to prove the defect the review found is
fixed: `core.prefit_identifiability` and `core.prefit_screening` previously
exposed *different* top-level readiness vocabularies (`ready`/
`review_recommended`/`blocked` vs. `computed`/`blocked_pending_analyst_
rationale`), and nothing consolidated them - submission logic re-derived its
own blocking decision by inspecting scattered sub-fields independently. This
module is the single place that decision is made.
"""

from __future__ import annotations

import pytest

from ancestry_mmm.core.prefit_run import (
    BLOCKED,
    CANNOT_VERIFY,
    PREFIT_RUN_SCHEMA_VERSION,
    PREPARED_FRAME_ONLY,
    POINT_IN_TIME_SOURCE_RECONSTRUCTION,
    READY,
    REVIEW_RECOMMENDED,
    PrefitRun,
    build_prefit_run,
    build_run_id,
    consolidate_prefit_readiness,
    official_submission_allowed,
    prefit_run_is_stale,
)


class TestConsolidatePrefitReadiness:
    def test_any_component_blocked_wins_over_everything_else(self):
        result = consolidate_prefit_readiness(
            identifiability_readiness=BLOCKED,
            screening_readiness=READY,
            prior_predictive_readiness=READY,
            analyst_rationale_retained=True,
        )
        assert result["readiness"] == BLOCKED
        assert "identifiability is blocked" in result["reasons"]

    def test_blocked_is_never_overridden_by_rationale(self):
        result = consolidate_prefit_readiness(
            identifiability_readiness=READY,
            screening_readiness=BLOCKED,
            analyst_rationale_retained=True,
        )
        assert result["readiness"] == BLOCKED

    def test_missing_prior_predictive_keeps_run_at_review_recommended(self):
        result = consolidate_prefit_readiness(
            identifiability_readiness=READY,
            screening_readiness=READY,
            prior_predictive_readiness=None,
            analyst_rationale_retained=True,
        )
        assert result["readiness"] == REVIEW_RECOMMENDED

    def test_every_component_ready_without_rationale_stays_review_recommended(self):
        """REQ-PREFIT-001: review_recommended permits submission only with
        retained analyst rationale - a run cannot silently become `ready`
        just because every individual evidence component happens to be
        `ready`."""
        result = consolidate_prefit_readiness(
            identifiability_readiness=READY,
            screening_readiness=READY,
            prior_predictive_readiness=READY,
            analyst_rationale_retained=False,
        )
        assert result["readiness"] == REVIEW_RECOMMENDED
        assert "retained analyst" in " ".join(result["reasons"])

    def test_every_component_ready_with_rationale_is_ready(self):
        result = consolidate_prefit_readiness(
            identifiability_readiness=READY,
            screening_readiness=READY,
            prior_predictive_readiness=READY,
            analyst_rationale_retained=True,
        )
        assert result["readiness"] == READY

    def test_a_review_recommended_component_keeps_the_run_at_review_recommended(self):
        result = consolidate_prefit_readiness(
            identifiability_readiness=READY,
            screening_readiness=REVIEW_RECOMMENDED,
            prior_predictive_readiness=READY,
            analyst_rationale_retained=True,
        )
        assert result["readiness"] == REVIEW_RECOMMENDED

    def test_rejects_a_readiness_value_outside_the_closed_vocabulary(self):
        with pytest.raises(ValueError, match="identifiability_readiness"):
            consolidate_prefit_readiness(
                identifiability_readiness="computed",
                screening_readiness=READY,
            )
        with pytest.raises(ValueError, match="screening_readiness"):
            consolidate_prefit_readiness(
                identifiability_readiness=READY,
                screening_readiness="blocked_pending_analyst_rationale",
            )


def _minimal_run(**overrides) -> PrefitRun:
    defaults = dict(
        schema_version=PREFIT_RUN_SCHEMA_VERSION,
        run_id="fixed-run-id",
        product="Family History",
        model_name="Model A",
        generated_at="2026-08-24T00:00:00+00:00",
        candidate_spec_fingerprint="a",
        prepared_frame_fingerprint="b",
        causal_graph_fingerprint="c",
        transform_config_fingerprint="d",
        fold_policy_version="v1",
        fold_manifest=(),
        reconstruction_tier=PREPARED_FRAME_ONLY,
        surrogate_method_version="prefit-screening-v1",
        screen_grid_version="bounded-adstock-hill-grid-v1",
        support_threshold_policy_version="support-diagnostic-v1",
        prior_predictive_threshold_policy_version=None,
        identifiability_report={"status": READY},
        screening_report={"review_status": READY},
        readiness=REVIEW_RECOMMENDED,
        readiness_detail={"readiness": REVIEW_RECOMMENDED},
        analyst_review={
            "status": "not_available",
            "rationale": None,
            "rationale_retained": False,
        },
    )
    defaults.update(overrides)
    return PrefitRun(**defaults)


class TestPrefitRunConstruction:
    def test_rejects_wrong_schema_version(self):
        with pytest.raises(ValueError, match="schema_version"):
            _minimal_run(schema_version=999)

    def test_rejects_readiness_outside_closed_vocabulary(self):
        with pytest.raises(ValueError, match="readiness"):
            _minimal_run(readiness="computed")

    def test_rejects_unknown_reconstruction_tier(self):
        with pytest.raises(ValueError, match="reconstruction_tier"):
            _minimal_run(reconstruction_tier="fully_verified")

    def test_ready_requires_retained_analyst_rationale(self):
        """A PrefitRun must never be constructible with readiness=ready
        unless rationale was actually retained - this is the fail-closed
        backstop even if a caller somehow bypassed
        consolidate_prefit_readiness's own rule."""
        with pytest.raises(ValueError, match="rationale_retained"):
            _minimal_run(
                readiness=READY,
                analyst_review={"rationale_retained": False},
            )
        # Construction succeeds once rationale really is retained.
        run = _minimal_run(
            readiness=READY,
            analyst_review={"rationale_retained": True},
        )
        assert run.readiness == READY

    def test_blocked_and_review_recommended_never_require_rationale_to_construct(self):
        _minimal_run(readiness=BLOCKED)
        _minimal_run(readiness=REVIEW_RECOMMENDED)

    def test_downstream_use_restrictions_default_to_the_full_closed_set(self):
        run = _minimal_run()
        assert set(run.downstream_use_restrictions) == {
            "not_official_attribution",
            "not_official_cpa_roi",
            "not_response_curve_approval",
            "not_planning_eligible",
            "not_optimisation_eligible",
        }
        assert run.diagnostic_only is True
        assert run.official_eligibility is False
        assert run.channel_selection_rule is False
        assert run.model_mutation_applied is False


class TestPrefitRunRoundTrip:
    def test_to_dict_from_dict_round_trips_exactly(self):
        run = _minimal_run(
            fold_manifest=({"fold_id": "prefit-fold-1", "leakage_safe": True},)
        )
        payload = run.to_dict()
        restored = PrefitRun.from_dict(payload)
        assert restored == run
        assert restored.to_dict() == payload

    def test_fingerprints_returns_exactly_the_four_bound_identities(self):
        run = _minimal_run()
        assert run.fingerprints() == {
            "candidate_spec_fingerprint": "a",
            "prepared_frame_fingerprint": "b",
            "causal_graph_fingerprint": "c",
            "transform_config_fingerprint": "d",
        }


class TestPrefitRunStaleness:
    def test_current_when_fingerprints_match(self):
        run = _minimal_run()
        result = prefit_run_is_stale(run, run.fingerprints())
        assert result["status"] == "current"
        assert result["stale"] is False

    def test_stale_when_any_fingerprint_changed(self):
        run = _minimal_run()
        changed = dict(run.fingerprints())
        changed["prepared_frame_fingerprint"] = "different"
        result = prefit_run_is_stale(run, changed)
        assert result["status"] == "stale"
        assert "prepared_frame_fingerprint" in result["mismatches"]

    def test_works_on_a_plain_dict_reloaded_from_session_state_or_import(self):
        run = _minimal_run()
        payload = run.to_dict()
        result = prefit_run_is_stale(payload, run.fingerprints())
        assert result["status"] == "current"


class TestOfficialSubmissionAllowed:
    def test_blocked_never_allowed(self):
        run = _minimal_run(readiness=BLOCKED)
        allowed, _reason = official_submission_allowed(run)
        assert allowed is False

    def test_ready_is_allowed(self):
        run = _minimal_run(readiness=READY, analyst_review={"rationale_retained": True})
        allowed, _reason = official_submission_allowed(run)
        assert allowed is True

    def test_review_recommended_requires_retained_rationale(self):
        run = _minimal_run(
            readiness=REVIEW_RECOMMENDED,
            analyst_review={"rationale_retained": False},
        )
        allowed, reason = official_submission_allowed(run)
        assert allowed is False
        assert "rationale" in reason

    def test_review_recommended_with_retained_rationale_is_allowed(self):
        run = _minimal_run(
            readiness=REVIEW_RECOMMENDED,
            analyst_review={"rationale_retained": True},
        )
        allowed, _reason = official_submission_allowed(run)
        assert allowed is True

    def test_works_on_a_plain_dict_too(self):
        run = _minimal_run(readiness=BLOCKED)
        allowed, _reason = official_submission_allowed(run.to_dict())
        assert allowed is False


class TestBuildRunId:
    def test_deterministic_given_the_same_inputs(self):
        fp = {"a": "1", "b": "2"}
        assert build_run_id(fp, generated_at="t") == build_run_id(fp, generated_at="t")

    def test_differs_when_fingerprints_differ(self):
        assert build_run_id({"a": "1"}, generated_at="t") != build_run_id(
            {"a": "2"}, generated_at="t"
        )


class TestBuildPrefitRun:
    def _reports(self, *, identifiability_status="ready", screening_status="ready"):
        identifiability_report = {
            "status": identifiability_status,
            "review_status": identifiability_status,
            "fingerprints": {
                "candidate_spec_fingerprint": "cs",
                "prepared_frame_fingerprint": "pf",
                "causal_graph_fingerprint": "cg",
                "transform_config_fingerprint": "tc",
            },
            "prior_predictive": {"review_status": "ready"},
        }
        screening_report = {
            "status": "computed",
            "review_status": screening_status,
            "reconstruction_tier": PREPARED_FRAME_ONLY,
            "diagnostic_version": "prefit-screening-v1",
            "screen_grid_version": "bounded-adstock-hill-grid-v1",
            "folds": [{"fold_id": "prefit-fold-1"}],
            "analyst_review": {
                "status": "retained",
                "rationale": "reviewed",
                "rationale_retained": True,
            },
        }
        return identifiability_report, screening_report

    def test_assembles_a_ready_run_when_every_component_is_ready_and_reviewed(self):
        identifiability_report, screening_report = self._reports()
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.readiness == READY
        assert run.reconstruction_tier == PREPARED_FRAME_ONLY
        assert run.diagnostic_only is True
        assert run.official_eligibility is False

    def test_defaults_reconstruction_tier_from_the_screening_report(self):
        identifiability_report, screening_report = self._reports()
        screening_report["reconstruction_tier"] = POINT_IN_TIME_SOURCE_RECONSTRUCTION
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.reconstruction_tier == POINT_IN_TIME_SOURCE_RECONSTRUCTION

    def test_missing_reconstruction_tier_defaults_to_cannot_verify(self):
        identifiability_report, screening_report = self._reports()
        del screening_report["reconstruction_tier"]
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.reconstruction_tier == CANNOT_VERIFY

    def test_blocked_screening_makes_the_whole_run_blocked(self):
        identifiability_report, screening_report = self._reports(
            screening_status=BLOCKED
        )
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.readiness == BLOCKED

    def test_screening_bound_to_different_fingerprints_forces_blocked(self):
        """If the screen was run against a different candidate than the
        current identifiability review (e.g. config changed and only one
        report was rerun), the two reports no longer describe the same
        candidate and the run must block, never silently consolidate."""
        identifiability_report, screening_report = self._reports()
        screening_report["fingerprints"] = {
            "candidate_spec_fingerprint": "DIFFERENT",
            "prepared_frame_fingerprint": "pf",
            "causal_graph_fingerprint": "cg",
            "transform_config_fingerprint": "tc",
        }
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.readiness == BLOCKED
        assert any(
            "different fingerprints" in reason
            for reason in run.readiness_detail["reasons"]
        )

    def test_matching_screening_fingerprints_do_not_block(self):
        identifiability_report, screening_report = self._reports()
        screening_report["fingerprints"] = dict(identifiability_report["fingerprints"])
        run = build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert run.readiness == READY

    def test_neither_input_report_is_mutated(self):
        identifiability_report, screening_report = self._reports()
        import copy

        before_identifiability = copy.deepcopy(identifiability_report)
        before_screening = copy.deepcopy(screening_report)
        build_prefit_run(
            product="Family History",
            model_name="Model A",
            identifiability_report=identifiability_report,
            screening_report=screening_report,
            fold_policy_version="v1",
            support_threshold_policy_version="support-diagnostic-v1",
        )
        assert identifiability_report == before_identifiability
        assert screening_report == before_screening
