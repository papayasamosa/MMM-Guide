"""Tests for `application.data_support_service` - the real integration glue
between `core.data_support_classification` (REQ-DATASUPPORT-001, Decision
17) and the three diagnostic sources already computed elsewhere in the app
(`core.prefit_identifiability`'s session-state report, the canonical
`DiagnosticsService` identification artefact payload, and the
`variable_coverage_matrix` session-state dict).

These are integration tests against the real shapes each source actually
produces today (confirmed by reading `pages/04_Model_Config.py`,
`pages/06_Diagnostics.py`, `core.identification_diagnostics`, and
`core.coverage`), not just unit tests of `core.data_support_classification`
in isolation (that module already has its own suite,
`test_data_support_classification.py`)."""

from ancestry_mmm.application.data_support_service import (
    assemble_channel_data_support_evidence,
    assemble_project_data_support_overview,
    classify_channel_data_support,
    preview_channel_data_support_state,
)
from ancestry_mmm.core.data_support_classification import (
    DATA_SUPPORT_NOT_SUFFICIENT,
    DATA_SUPPORT_SUFFICIENT,
    DATA_SUPPORT_WEAK,
    DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY,
    DIMENSION_COLLINEARITY,
    DIMENSION_MISSINGNESS,
    GOVERNED_RESPONSE_PARTIAL_POOLING,
    SEVERITY_MODERATE_CONCERN,
    SEVERITY_NO_CONCERN,
    SEVERITY_NOT_AVAILABLE,
    SEVERITY_SEVERE_CONCERN,
)


def _prefit_report(rows):
    return {
        "support_identifiability": {"rows": rows},
    }


class TestAssembleChannelDataSupportEvidenceFromPrefitReport:
    def test_ready_row_maps_to_no_concern_severity(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "TV",
                    "target_weeks": 104,
                    "positive_weeks": 90,
                    "longest_zero_run": 1,
                    "effective_adstock_cv": 0.5,
                    "positive_max_to_median": 2.0,
                    "support_status": "strong",
                    "review_recommendation": {"review_status": "ready"},
                }
            ]
        )
        evidence = assemble_channel_data_support_evidence(
            "TV", prefit_report=prefit_report
        )
        by_dim = evidence.by_dimension()
        assert by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].value == "strong"
        assert (
            by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].severity
            == SEVERITY_NO_CONCERN
        )
        assert by_dim["total_observed_weeks"].value == 104

    def test_review_recommended_row_maps_to_moderate_concern(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "Radio",
                    "target_weeks": 30,
                    "positive_weeks": 10,
                    "support_status": "weak",
                    "review_recommendation": {"review_status": "review_recommended"},
                }
            ]
        )
        evidence = assemble_channel_data_support_evidence(
            "Radio", prefit_report=prefit_report
        )
        by_dim = evidence.by_dimension()
        assert (
            by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].severity
            == SEVERITY_MODERATE_CONCERN
        )

    def test_blocked_row_maps_to_severe_concern(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "OOH",
                    "target_weeks": 0,
                    "positive_weeks": 0,
                    "support_status": "very_weak",
                    "review_recommendation": {"review_status": "blocked"},
                }
            ]
        )
        evidence = assemble_channel_data_support_evidence(
            "OOH", prefit_report=prefit_report
        )
        by_dim = evidence.by_dimension()
        assert (
            by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].severity
            == SEVERITY_SEVERE_CONCERN
        )

    def test_channel_missing_from_prefit_report_is_unavailable_not_invented(self):
        prefit_report = _prefit_report(
            [{"channel": "TV", "review_recommendation": {"review_status": "ready"}}]
        )
        evidence = assemble_channel_data_support_evidence(
            "Radio", prefit_report=prefit_report
        )
        by_dim = evidence.by_dimension()
        assert by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].available is False
        assert (
            by_dim[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY].severity
            == SEVERITY_NOT_AVAILABLE
        )

    def test_none_prefit_report_is_unavailable(self):
        evidence = assemble_channel_data_support_evidence("TV", prefit_report=None)
        by_dim = evidence.by_dimension()
        assert by_dim["total_observed_weeks"].available is False


class TestCollinearityAdaptationFromIdentificationPayload:
    def test_correlation_matrix_and_matching_flag_are_picked_up(self):
        identification_payload = {
            "correlation_matrix": {
                "TV": {"TV": 1.0, "Radio": 0.92, "OOH": 0.1},
                "Radio": {"TV": 0.92, "Radio": 1.0, "OOH": 0.05},
            },
            "flags": [
                {
                    "level": "warning",
                    "channel": "TV / Radio",
                    "message": "'TV' and 'Radio' spend are highly correlated",
                }
            ],
        }
        evidence = assemble_channel_data_support_evidence(
            "TV", identification_payload=identification_payload
        )
        by_dim = evidence.by_dimension()
        collinearity = by_dim[DIMENSION_COLLINEARITY]
        assert collinearity.available is True
        assert collinearity.value["max_abs_correlation_with_other_channels"] == 0.92
        assert len(collinearity.value["flagged_messages"]) == 1
        # No approved threshold exists for this dimension - severity must
        # never be invented here, mirroring the Identification & collinearity
        # tab's own explicit non-escalation policy.
        assert collinearity.severity == SEVERITY_NOT_AVAILABLE

    def test_channel_with_no_correlation_row_and_no_flag_is_unavailable(self):
        identification_payload = {
            "correlation_matrix": {"TV": {"TV": 1.0, "Radio": 0.1}},
            "flags": [],
        }
        evidence = assemble_channel_data_support_evidence(
            "OOH", identification_payload=identification_payload
        )
        by_dim = evidence.by_dimension()
        assert by_dim[DIMENSION_COLLINEARITY].available is False


class TestMissingnessAdaptationFromCoverageMatrixDict:
    def test_unresolved_segments_are_counted(self):
        coverage_matrix_dict = {
            "records": [
                {
                    "variable_id": "TV",
                    "coverage_segments": [
                        {
                            "period_start": "2024-01-01",
                            "period_end": "2024-06-01",
                            "state": "observed_zero",
                        },
                        {
                            "period_start": "2024-06-02",
                            "period_end": "2024-12-31",
                            "state": "unknown",
                        },
                    ],
                }
            ]
        }
        evidence = assemble_channel_data_support_evidence(
            "TV", coverage_matrix_dict=coverage_matrix_dict
        )
        by_dim = evidence.by_dimension()
        missingness = by_dim[DIMENSION_MISSINGNESS]
        assert missingness.available is True
        assert missingness.value == {"unresolved_segments": 1, "total_segments": 2}

    def test_channel_with_no_coverage_record_is_unavailable(self):
        coverage_matrix_dict = {
            "records": [{"variable_id": "Radio", "coverage_segments": []}]
        }
        evidence = assemble_channel_data_support_evidence(
            "TV", coverage_matrix_dict=coverage_matrix_dict
        )
        by_dim = evidence.by_dimension()
        assert by_dim[DIMENSION_MISSINGNESS].available is False


class TestPreviewAndClassifyRoundTrip:
    def test_preview_matches_classify_for_sufficient_channel(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "TV",
                    "target_weeks": 104,
                    "support_status": "strong",
                    "review_recommendation": {"review_status": "ready"},
                }
            ]
        )
        evidence = assemble_channel_data_support_evidence(
            "TV", prefit_report=prefit_report
        )
        state, reasons = preview_channel_data_support_state(evidence)
        assert state == DATA_SUPPORT_SUFFICIENT
        classification = classify_channel_data_support(evidence)
        assert classification.state == state
        assert classification.reasons == reasons
        assert classification.governed_response is None

    def test_preview_flags_non_sufficient_before_a_governed_response_exists(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "OOH",
                    "target_weeks": 0,
                    "positive_weeks": 0,
                    "support_status": "very_weak",
                    "review_recommendation": {"review_status": "blocked"},
                }
            ]
        )
        evidence = assemble_channel_data_support_evidence(
            "OOH", prefit_report=prefit_report
        )
        state, reasons = preview_channel_data_support_state(evidence)
        assert state == DATA_SUPPORT_NOT_SUFFICIENT
        assert reasons == (DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY,)
        # Constructing the real classification without a governed_response
        # still fails closed exactly as core.data_support_classification
        # documents - preview never bypasses that invariant, it only lets a
        # caller find out about it without triggering the exception.
        import pytest

        with pytest.raises(ValueError):
            classify_channel_data_support(evidence)
        classification = classify_channel_data_support(
            evidence, governed_response=GOVERNED_RESPONSE_PARTIAL_POOLING
        )
        assert classification.state == DATA_SUPPORT_NOT_SUFFICIENT
        assert classification.governed_response == GOVERNED_RESPONSE_PARTIAL_POOLING


class TestAssembleProjectDataSupportOverview:
    def test_sufficient_channel_gets_classification_with_no_response_needed(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "TV",
                    "target_weeks": 104,
                    "support_status": "strong",
                    "review_recommendation": {"review_status": "ready"},
                }
            ]
        )
        overview = assemble_project_data_support_overview(
            ["TV"], prefit_report=prefit_report
        )
        assert len(overview) == 1
        row = overview[0]
        assert row["channel"] == "TV"
        assert row["state"] == DATA_SUPPORT_SUFFICIENT
        assert row["needs_governed_response"] is False
        assert row["classification"] is not None
        assert row["classification"].governed_response is None

    def test_non_sufficient_channel_without_a_response_choice_yields_no_classification(
        self,
    ):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "OOH",
                    "target_weeks": 0,
                    "positive_weeks": 0,
                    "support_status": "very_weak",
                    "review_recommendation": {"review_status": "blocked"},
                }
            ]
        )
        overview = assemble_project_data_support_overview(
            ["OOH"], prefit_report=prefit_report
        )
        row = overview[0]
        assert row["state"] == DATA_SUPPORT_NOT_SUFFICIENT
        assert row["needs_governed_response"] is True
        assert row["classification"] is None

    def test_non_sufficient_channel_with_a_chosen_response_yields_classification(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "OOH",
                    "target_weeks": 0,
                    "positive_weeks": 0,
                    "support_status": "very_weak",
                    "review_recommendation": {"review_status": "blocked"},
                }
            ]
        )
        overview = assemble_project_data_support_overview(
            ["OOH"],
            prefit_report=prefit_report,
            governed_response_by_channel={"OOH": GOVERNED_RESPONSE_PARTIAL_POOLING},
        )
        row = overview[0]
        assert row["classification"] is not None
        assert (
            row["classification"].governed_response == GOVERNED_RESPONSE_PARTIAL_POOLING
        )

    def test_multiple_channels_are_each_classified_independently(self):
        prefit_report = _prefit_report(
            [
                {
                    "channel": "TV",
                    "target_weeks": 104,
                    "support_status": "strong",
                    "review_recommendation": {"review_status": "ready"},
                },
                {
                    "channel": "Radio",
                    "target_weeks": 30,
                    "positive_weeks": 10,
                    "support_status": "weak",
                    "review_recommendation": {"review_status": "review_recommended"},
                },
            ]
        )
        overview = assemble_project_data_support_overview(
            ["TV", "Radio"], prefit_report=prefit_report
        )
        assert overview[0]["state"] == DATA_SUPPORT_SUFFICIENT
        assert overview[1]["state"] == DATA_SUPPORT_WEAK
        assert overview[1]["needs_governed_response"] is True
