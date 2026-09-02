"""Tests for `ancestry_mmm.core.data_support_classification`
(`REQ-DATASUPPORT-001`; Decision 17). See
`docs/data_support_classification_decision_record.md`."""

import pytest

from ancestry_mmm.core.data_support_classification import (
    DATA_SUPPORT_NOT_SUFFICIENT,
    DATA_SUPPORT_SUFFICIENT,
    DATA_SUPPORT_WEAK,
    EVIDENCE_DIMENSIONS,
    GOVERNED_RESPONSE_PARTIAL_POOLING,
    SEVERITY_MODERATE_CONCERN,
    SEVERITY_NOT_AVAILABLE,
    SEVERITY_SEVERE_CONCERN,
    DataSupportEvidence,
    EvidenceDimensionRecord,
    assemble_data_support_evidence,
    classify_data_support,
)


class TestEvidenceDimensionRecordValidation:
    def test_unknown_dimension_rejected(self):
        with pytest.raises(ValueError):
            EvidenceDimensionRecord(
                dimension="not_a_real_dimension",
                available=True,
                value=1,
                source_module="x",
            )

    def test_severity_on_unavailable_evidence_rejected(self):
        with pytest.raises(ValueError):
            EvidenceDimensionRecord(
                dimension="total_observed_weeks",
                available=False,
                value=None,
                source_module="not_available",
                severity="severe_concern",
            )


class TestDataSupportEvidenceRequiresAllTwelveDimensions:
    def test_missing_dimension_rejected(self):
        partial = [
            EvidenceDimensionRecord(
                dimension=d, available=False, value=None, source_module="not_available"
            )
            for d in EVIDENCE_DIMENSIONS[:-1]
        ]
        with pytest.raises(ValueError):
            DataSupportEvidence(channel="TV", dimension_records=tuple(partial))

    def test_all_twelve_present_is_valid(self):
        records = [
            EvidenceDimensionRecord(
                dimension=d, available=False, value=None, source_module="not_available"
            )
            for d in EVIDENCE_DIMENSIONS
        ]
        evidence = DataSupportEvidence(channel="TV", dimension_records=tuple(records))
        assert len(evidence.dimension_records) == 12
        assert set(evidence.by_dimension()) == set(EVIDENCE_DIMENSIONS)


class TestAssembleDataSupportEvidenceFromPrefitIdentifiability:
    def test_maps_prefit_row_fields_onto_named_dimensions(self):
        prefit_row = {
            "target_weeks": 104,
            "positive_weeks": 60,
            "longest_zero_run": 3,
            "effective_adstock_cv": 0.4,
            "positive_max_to_median": 2.5,
            "support_status": "strong",
        }
        evidence = assemble_data_support_evidence("TV", prefit_support_row=prefit_row)
        by_dim = evidence.by_dimension()
        assert by_dim["total_observed_weeks"].value == 104
        assert by_dim["total_observed_weeks"].available is True
        assert (
            by_dim["total_observed_weeks"].source_module
            == "core.prefit_identifiability"
        )
        assert by_dim["non_zero_active_weeks"].value == 60
        assert by_dim["long_runs_of_zeros"].value == 3
        assert (
            by_dim["ability_to_identify_adstock_saturation_parameters"].value
            == "strong"
        )

    def test_dimensions_with_no_source_are_explicitly_unavailable(self):
        evidence = assemble_data_support_evidence("TV")
        by_dim = evidence.by_dimension()
        assert by_dim["number_of_separate_activity_periods"].available is False
        assert by_dim["correlation_with_trend_seasonality"].available is False

    def test_severity_never_invented_without_caller_input(self):
        prefit_row = {"target_weeks": 2, "positive_weeks": 1}
        evidence = assemble_data_support_evidence("TV", prefit_support_row=prefit_row)
        by_dim = evidence.by_dimension()
        # Value is available, but severity stays not_available unless the
        # caller explicitly supplies a judgement.
        assert by_dim["total_observed_weeks"].available is True
        assert by_dim["total_observed_weeks"].severity == SEVERITY_NOT_AVAILABLE

    def test_severity_by_dimension_is_caller_controlled(self):
        prefit_row = {"target_weeks": 2, "positive_weeks": 1}
        evidence = assemble_data_support_evidence(
            "TV",
            prefit_support_row=prefit_row,
            severity_by_dimension={"total_observed_weeks": SEVERITY_SEVERE_CONCERN},
        )
        by_dim = evidence.by_dimension()
        assert by_dim["total_observed_weeks"].severity == SEVERITY_SEVERE_CONCERN


class TestClassifyDataSupportDefaultCombinationPolicy:
    def test_no_concern_anywhere_is_sufficient(self):
        evidence = assemble_data_support_evidence(
            "TV", prefit_support_row={"target_weeks": 104}
        )
        result = classify_data_support(evidence)
        assert result.state == DATA_SUPPORT_SUFFICIENT
        assert result.governed_response is None
        assert result.reasons == ()

    def test_moderate_concern_is_weak_and_requires_governed_response(self):
        evidence = assemble_data_support_evidence(
            "TV",
            prefit_support_row={"target_weeks": 20},
            severity_by_dimension={"total_observed_weeks": SEVERITY_MODERATE_CONCERN},
        )
        with pytest.raises(ValueError):
            classify_data_support(evidence)  # missing governed_response
        result = classify_data_support(
            evidence, governed_response=GOVERNED_RESPONSE_PARTIAL_POOLING
        )
        assert result.state == DATA_SUPPORT_WEAK
        assert result.reasons == ("total_observed_weeks",)
        assert result.governed_response == GOVERNED_RESPONSE_PARTIAL_POOLING

    def test_severe_concern_wins_over_moderate(self):
        evidence = assemble_data_support_evidence(
            "TV",
            prefit_support_row={"target_weeks": 2, "positive_weeks": 1},
            severity_by_dimension={
                "total_observed_weeks": SEVERITY_MODERATE_CONCERN,
                "non_zero_active_weeks": SEVERITY_SEVERE_CONCERN,
            },
        )
        result = classify_data_support(
            evidence, governed_response=GOVERNED_RESPONSE_PARTIAL_POOLING
        )
        assert result.state == DATA_SUPPORT_NOT_SUFFICIENT
        assert result.reasons == ("non_zero_active_weeks",)

    def test_sufficient_state_must_not_carry_a_governed_response(self):
        evidence = assemble_data_support_evidence(
            "TV", prefit_support_row={"target_weeks": 104}
        )
        with pytest.raises(ValueError):
            classify_data_support(
                evidence, governed_response=GOVERNED_RESPONSE_PARTIAL_POOLING
            )


class TestCustomCombinationPolicy:
    def test_caller_supplied_policy_overrides_default(self):
        evidence = assemble_data_support_evidence(
            "TV", prefit_support_row={"target_weeks": 104}
        )

        def _always_weak(ev):
            return DATA_SUPPORT_WEAK, ("total_observed_weeks",)

        result = classify_data_support(
            evidence,
            governed_response=GOVERNED_RESPONSE_PARTIAL_POOLING,
            combination_policy=_always_weak,
        )
        assert result.state == DATA_SUPPORT_WEAK
        assert result.combination_policy_name == "caller_supplied"
