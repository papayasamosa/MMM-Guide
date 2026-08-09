"""Tests for core.coverage (REQ-COVERAGE-001 Work Package 3 Phase 1):
framework-independent variable-coverage/mixed-frequency domain contracts.
"""

import json
from pathlib import Path

import pytest

from ancestry_mmm.core.coverage import (
    COVERAGE_STATES,
    STATE_ESTIMATED,
    STATE_MISSING_EXPECTED,
    STATE_NOT_APPLICABLE,
    STATE_OBSERVED_ZERO,
    STATE_UNAVAILABLE_SOURCE,
    STATE_UNKNOWN,
    VARIABLE_CLASSES,
    CoverageSegment,
    DefinitionBreak,
    FrequencyMetadata,
    SourceVersion,
    VariableCoverageMatrix,
    VariableCoverageRecord,
    compute_checksum,
    current_source_versions,
    new_variable_coverage_matrix_version,
    official_fit_blocking_issues,
    variable_coverage_records_fingerprint,
)


def _frequency(**overrides) -> FrequencyMetadata:
    defaults = dict(
        native_frequency="weekly",
        target_frequency="weekly",
        variable_class="flow_count",
    )
    defaults.update(overrides)
    return FrequencyMetadata(**defaults)


def _record(**overrides) -> VariableCoverageRecord:
    defaults = dict(
        variable_id="TV_spend",
        source_id="src-1",
        source_version=1,
        market="UK",
        frequency=_frequency(),
        coverage_segments=(
            CoverageSegment(
                period_start="2025-01-06",
                period_end="2025-12-29",
                state=STATE_ESTIMATED,
            ),
        ),
    )
    defaults.update(overrides)
    return VariableCoverageRecord(**defaults)


# ---------------------------------------------------------------------------
# Canonical vocabulary - must stay in lockstep with REQ-COVERAGE-001's own
# index.json declaration (docs/approved_requirements/index.json), never
# drift silently between the two authorities.
# ---------------------------------------------------------------------------


class TestCanonicalVocabularyMatchesRequirementAuthority:
    def test_coverage_states_match_index_json_declaration(self):
        index_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "index.json"
        )
        data = json.loads(index_path.read_text())
        req = next(
            r for r in data["requirements"] if r["requirement_id"] == "REQ-COVERAGE-001"
        )
        assert tuple(req["missingness_states"]) == COVERAGE_STATES

    def test_eight_states_exactly(self):
        assert len(COVERAGE_STATES) == 8
        assert len(set(COVERAGE_STATES)) == 8


# ---------------------------------------------------------------------------
# FrequencyMetadata
# ---------------------------------------------------------------------------


class TestFrequencyMetadata:
    def test_valid_variable_classes_accepted(self):
        for vc in VARIABLE_CLASSES:
            fm = _frequency(variable_class=vc)
            assert fm.variable_class == vc

    def test_unknown_variable_class_rejected(self):
        with pytest.raises(ValueError, match="variable_class"):
            _frequency(variable_class="not_a_real_class")

    def test_negative_publication_lag_rejected(self):
        with pytest.raises(ValueError, match="publication_lag_periods"):
            _frequency(publication_lag_periods=-1)

    def test_round_trip(self):
        fm = _frequency(publication_lag_periods=2, method="carry_forward")
        assert FrequencyMetadata.from_dict(fm.to_dict()) == fm


# ---------------------------------------------------------------------------
# DefinitionBreak
# ---------------------------------------------------------------------------


class TestDefinitionBreak:
    def test_approved_bridge_requires_attribution(self):
        with pytest.raises(ValueError, match="approved_by"):
            DefinitionBreak(
                break_date="2025-06-01",
                description="methodology change",
                bridge_treatment_approved=True,
            )

    def test_approved_bridge_with_attribution_succeeds(self):
        db = DefinitionBreak(
            break_date="2025-06-01",
            description="methodology change",
            bridge_treatment_approved=True,
            approved_by="Analyst",
            approved_at="2025-06-02",
        )
        assert db.bridge_treatment_approved

    def test_malformed_date_rejected(self):
        with pytest.raises(ValueError):
            DefinitionBreak(break_date="not-a-date", description="x")


# ---------------------------------------------------------------------------
# CoverageSegment - structural zero governance
# ---------------------------------------------------------------------------


class TestCoverageSegmentStructuralZero:
    def test_structural_zero_requires_justification(self):
        with pytest.raises(ValueError, match="justification"):
            CoverageSegment(
                period_start="2025-01-06",
                period_end="2025-03-31",
                state=STATE_OBSERVED_ZERO,
                structural_zero=True,
            )

    def test_structural_zero_requires_observed_zero_state(self):
        with pytest.raises(ValueError, match="state='observed_zero'"):
            CoverageSegment(
                period_start="2025-01-06",
                period_end="2025-03-31",
                state=STATE_UNKNOWN,
                structural_zero=True,
                justification="pre-launch, channel did not exist",
            )

    def test_structural_zero_with_justification_succeeds(self):
        seg = CoverageSegment(
            period_start="2025-01-06",
            period_end="2025-03-31",
            state=STATE_OBSERVED_ZERO,
            structural_zero=True,
            justification="channel launched 2025-04-01, genuinely no prior activity",
        )
        assert seg.structural_zero

    def test_plain_observed_zero_does_not_require_justification(self):
        seg = CoverageSegment(
            period_start="2025-01-06",
            period_end="2025-03-31",
            state=STATE_OBSERVED_ZERO,
        )
        assert not seg.structural_zero

    def test_invalid_state_rejected(self):
        with pytest.raises(ValueError, match="invalid coverage state"):
            CoverageSegment(
                period_start="2025-01-06", period_end="2025-03-31", state="missing"
            )

    def test_never_infers_state_from_a_numeric_value(self):
        """REQ-COVERAGE-001's core invariant: a coverage state is declared
        metadata, never derived from "the value happens to be 0 or NaN" -
        CoverageSegment structurally has no numeric value field at all to
        derive from."""
        assert "value" not in CoverageSegment.__dataclass_fields__


# ---------------------------------------------------------------------------
# SourceVersion
# ---------------------------------------------------------------------------


class TestSourceVersion:
    def _version(self, **overrides):
        defaults = dict(
            source_id="src-1",
            version=1,
            original_filename="media.csv",
            checksum=compute_checksum(b"hello world"),
            size_bytes=11,
            uploaded_at="2026-08-09T00:00:00Z",
            parsed_representation_version="pandas-2.x-v1",
        )
        defaults.update(overrides)
        return SourceVersion(**defaults)

    def test_valid_construction(self):
        v = self._version()
        assert v.source_key == ("src-1", 1)

    def test_checksum_must_be_sha256_hex(self):
        with pytest.raises(ValueError, match="checksum"):
            self._version(checksum="not-a-checksum")

    def test_checksum_wrong_length_rejected(self):
        with pytest.raises(ValueError, match="64-character"):
            self._version(checksum="abc123")

    def test_version_must_be_positive(self):
        with pytest.raises(ValueError, match="version"):
            self._version(version=0)

    def test_negative_size_rejected(self):
        with pytest.raises(ValueError, match="size_bytes"):
            self._version(size_bytes=-1)

    def test_compute_checksum_deterministic(self):
        assert compute_checksum(b"abc") == compute_checksum(b"abc")
        assert compute_checksum(b"abc") != compute_checksum(b"abd")

    def test_current_source_versions_resolves_highest_per_lineage(self):
        v1 = self._version(version=1)
        v2 = self._version(version=2)
        other = self._version(source_id="src-2", version=1)
        current = current_source_versions([v1, v2, other])
        by_source = {v.source_id: v.version for v in current}
        assert by_source == {"src-1": 2, "src-2": 1}


# ---------------------------------------------------------------------------
# VariableCoverageRecord
# ---------------------------------------------------------------------------


class TestVariableCoverageRecord:
    def test_valid_construction(self):
        record = _record()
        assert record.variable_key == ("TV_spend", "UK", None, None)

    def test_overlapping_segments_rejected(self):
        with pytest.raises(ValueError, match="overlap"):
            _record(
                coverage_segments=(
                    CoverageSegment(
                        period_start="2025-01-06",
                        period_end="2025-06-30",
                        state=STATE_ESTIMATED,
                    ),
                    CoverageSegment(
                        period_start="2025-06-01",
                        period_end="2025-12-29",
                        state=STATE_UNKNOWN,
                    ),
                )
            )

    def test_non_overlapping_segments_accepted(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-06-30",
                    state=STATE_UNAVAILABLE_SOURCE,
                ),
                CoverageSegment(
                    period_start="2025-07-01",
                    period_end="2025-12-29",
                    state=STATE_ESTIMATED,
                ),
            )
        )
        assert len(record.coverage_segments) == 2

    def test_approved_treatment_requires_attribution(self):
        with pytest.raises(ValueError, match="treatment_status='approved'"):
            _record(treatment_status="approved")

    def test_approved_treatment_with_attribution_succeeds(self):
        record = _record(
            treatment_status="approved",
            approved_treatment="carry_forward_within_publication_window",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-09",
        )
        assert record.treatment_status == "approved"

    def test_invalid_treatment_status_rejected(self):
        with pytest.raises(ValueError, match="invalid treatment_status"):
            _record(treatment_status="maybe")

    def test_market_defaults_required_not_silently_wildcarded(self):
        with pytest.raises(ValueError, match="market"):
            _record(market="")

    def test_round_trip(self):
        record = _record(product="Family History", segment="New")
        assert VariableCoverageRecord.from_dict(record.to_dict()) == record


class TestIsOfficiallyUnresolved:
    def test_unknown_state_without_approval_is_unresolved(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            )
        )
        assert record.is_officially_unresolved

    def test_missing_expected_without_approval_is_unresolved(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_MISSING_EXPECTED,
                ),
            )
        )
        assert record.is_officially_unresolved

    def test_approved_treatment_alone_does_not_clear_the_block(self):
        """A P2 review finding on an earlier version of this record: an
        *approved* treatment of e.g. "exploratory_only" is itself a
        governance decision to keep the record excluded from official use
        - treating approval attribution alone as clearing the block would
        silently promote unresolved coverage to fit-eligible, exactly what
        REQ-COVERAGE-001 S5 forbids. Only the separate
        `approved_for_official_use` flag may clear it."""
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            ),
            treatment_status="approved",
            approved_treatment="exploratory_only",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-09",
        )
        assert record.is_officially_unresolved

    def test_approved_for_official_use_clears_the_block(self):
        record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            ),
            treatment_status="approved",
            approved_treatment="carry_forward_within_publication_window",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-09",
            approved_for_official_use=True,
        )
        assert not record.is_officially_unresolved

    def test_approved_for_official_use_requires_approved_treatment_status(self):
        with pytest.raises(ValueError, match="approved_for_official_use"):
            _record(approved_for_official_use=True)

    def test_resolved_states_never_flagged(self):
        for state in (STATE_OBSERVED_ZERO, STATE_NOT_APPLICABLE, STATE_ESTIMATED):
            record = _record(
                coverage_segments=(
                    CoverageSegment(
                        period_start="2025-01-06",
                        period_end="2025-12-29",
                        state=state,
                    ),
                )
            )
            assert not record.is_officially_unresolved, state

    def test_official_fit_blocking_issues_names_the_variable_and_states(self):
        record = _record(
            variable_id="AU_control",
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            ),
        )
        issues = official_fit_blocking_issues([record])
        assert len(issues) == 1
        assert "AU_control" in issues[0]
        assert "unknown" in issues[0]

    def test_official_fit_blocking_issues_empty_when_nothing_unresolved(self):
        assert official_fit_blocking_issues([_record()]) == []


# ---------------------------------------------------------------------------
# VariableCoverageMatrix
# ---------------------------------------------------------------------------


class TestVariableCoverageMatrix:
    def _matrix(self, **overrides) -> VariableCoverageMatrix:
        defaults = dict(
            matrix_id="matrix-1",
            matrix_version=1,
            generated_at="2026-08-09T00:00:00Z",
            records=(_record(),),
        )
        defaults.update(overrides)
        return VariableCoverageMatrix(**defaults)

    def test_valid_construction(self):
        matrix = self._matrix()
        assert matrix.matrix_key == "matrix-1"

    def test_matrix_id_required(self):
        with pytest.raises(ValueError, match="matrix_id"):
            self._matrix(matrix_id="")

    def test_version_must_be_positive(self):
        with pytest.raises(ValueError, match="matrix_version"):
            self._matrix(matrix_version=0)

    def test_blocking_issues_delegates_to_records(self):
        unresolved_record = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            )
        )
        matrix = self._matrix(records=(unresolved_record,))
        assert len(matrix.blocking_issues) == 1

    def test_fingerprint_is_deterministic(self):
        matrix = self._matrix()
        assert matrix.fingerprint() == matrix.fingerprint()

    def test_fingerprint_changes_when_coverage_changes(self):
        matrix_a = self._matrix()
        matrix_b = self._matrix(
            records=(
                _record(
                    coverage_segments=(
                        CoverageSegment(
                            period_start="2025-01-06",
                            period_end="2025-12-29",
                            state=STATE_UNKNOWN,
                        ),
                    )
                ),
            )
        )
        assert matrix_a.fingerprint() != matrix_b.fingerprint()

    def test_presentation_only_change_does_not_change_fingerprint(self):
        """REQ-COVERAGE-001 S5: a purely presentational metadata change
        must not stale a fit. `notes` is matrix-level presentation, not
        part of any VariableCoverageRecord, so the records fingerprint
        (what a dependent requirement wires into fit identity) is
        untouched by it."""
        matrix_a = self._matrix(notes="")
        matrix_b = self._matrix(notes="reviewed by Jane on 2026-08-09")
        assert matrix_a.fingerprint() == matrix_b.fingerprint()

    def test_round_trip(self):
        matrix = self._matrix()
        assert VariableCoverageMatrix.from_dict(matrix.to_dict()) == matrix

    def test_schema_version_defaults_when_absent_legacy_case(self):
        payload = self._matrix().to_dict()
        del payload["schema_version"]
        reconstructed = VariableCoverageMatrix.from_dict(payload)
        assert reconstructed.schema_version == 1

    def test_schema_version_above_supported_rejected(self):
        payload = self._matrix().to_dict()
        payload["schema_version"] = 999
        with pytest.raises(ValueError, match="Unsupported"):
            VariableCoverageMatrix.from_dict(payload)

    def test_schema_version_bool_rejected_not_coerced(self):
        payload = self._matrix().to_dict()
        payload["schema_version"] = True
        with pytest.raises(ValueError, match="non-integer"):
            VariableCoverageMatrix.from_dict(payload)

    def test_schema_version_numeric_string_rejected_not_coerced(self):
        payload = self._matrix().to_dict()
        payload["schema_version"] = "1"
        with pytest.raises(ValueError, match="non-integer"):
            VariableCoverageMatrix.from_dict(payload)


class TestNewVariableCoverageMatrixVersion:
    def _matrix(self) -> VariableCoverageMatrix:
        return VariableCoverageMatrix(
            matrix_id="matrix-1",
            matrix_version=1,
            generated_at="2026-08-09T00:00:00Z",
            records=(_record(),),
        )

    def test_increments_version(self):
        matrix = self._matrix()
        new_matrix = new_variable_coverage_matrix_version(matrix, notes="updated")
        assert new_matrix.matrix_version == 2
        assert new_matrix.notes == "updated"
        assert matrix.matrix_version == 1  # original untouched

    def test_matrix_id_cannot_be_changed(self):
        matrix = self._matrix()
        with pytest.raises(ValueError, match="matrix_id"):
            new_variable_coverage_matrix_version(matrix, matrix_id="matrix-2")

    def test_matrix_version_cannot_be_set_directly(self):
        matrix = self._matrix()
        with pytest.raises(ValueError, match="matrix_version"):
            new_variable_coverage_matrix_version(matrix, matrix_version=5)


# ---------------------------------------------------------------------------
# variable_coverage_records_fingerprint (module-level helper)
# ---------------------------------------------------------------------------


class TestVariableCoverageRecordsFingerprint:
    def test_order_independent(self):
        record_a = _record(variable_id="TV_spend")
        record_b = _record(variable_id="Radio_spend")
        fp1 = variable_coverage_records_fingerprint([record_a, record_b])
        fp2 = variable_coverage_records_fingerprint([record_b, record_a])
        assert fp1 == fp2

    def test_accepts_dicts_or_dataclass_instances(self):
        record = _record()
        fp_from_instance = variable_coverage_records_fingerprint([record])
        fp_from_dict = variable_coverage_records_fingerprint([record.to_dict()])
        assert fp_from_instance == fp_from_dict

    def test_owner_change_does_not_change_fingerprint(self):
        """P2 review finding on an earlier version: hashing the full
        `to_dict()` payload made administrative fields like `owner` part of
        model identity, so reassigning ownership alone would falsely stale
        a fit."""
        record_a = _record(owner="Alice")
        record_b = _record(owner="Bob")
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_proposed_treatment_change_does_not_change_fingerprint(self):
        record_a = _record(proposed_treatment="carry_forward")
        record_b = _record(proposed_treatment="linear_interpolate")
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_treatment_approval_attribution_change_does_not_change_fingerprint(self):
        base = dict(
            treatment_status="approved",
            approved_treatment="carry_forward_within_publication_window",
        )
        record_a = _record(
            **base, treatment_approved_by="Alice", treatment_approved_at="2026-08-01"
        )
        record_b = _record(
            **base, treatment_approved_by="Bob", treatment_approved_at="2026-08-09"
        )
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_observed_and_expected_window_changes_do_not_change_fingerprint(self):
        record_a = _record(observed_start="2025-01-06", expected_start="2025-01-06")
        record_b = _record(observed_start="2025-02-03", expected_start="2025-02-03")
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_segment_justification_change_does_not_change_fingerprint(self):
        record_a = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-03-31",
                    state=STATE_OBSERVED_ZERO,
                    structural_zero=True,
                    justification="pre-launch, channel did not exist yet",
                ),
            )
        )
        record_b = _record(
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-03-31",
                    state=STATE_OBSERVED_ZERO,
                    structural_zero=True,
                    justification="a differently-worded but equally valid justification",
                ),
            )
        )
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_definition_break_description_and_attribution_do_not_change_fingerprint(
        self,
    ):
        record_a = _record(
            definition_breaks=(
                DefinitionBreak(
                    break_date="2025-06-01", description="original wording"
                ),
            )
        )
        record_b = _record(
            definition_breaks=(
                DefinitionBreak(break_date="2025-06-01", description="reworded later"),
            )
        )
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) == variable_coverage_records_fingerprint([record_b])

    def test_effective_window_change_changes_fingerprint(self):
        record_a = _record(effective_start="2025-01-06", effective_end="2025-12-29")
        record_b = _record(effective_start="2025-04-01", effective_end="2025-12-29")
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) != variable_coverage_records_fingerprint([record_b])

    def test_approved_treatment_change_changes_fingerprint(self):
        base = dict(
            treatment_status="approved",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-09",
        )
        record_a = _record(**base, approved_treatment="carry_forward")
        record_b = _record(**base, approved_treatment="linear_interpolate")
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) != variable_coverage_records_fingerprint([record_b])

    def test_approved_for_official_use_change_changes_fingerprint(self):
        base = dict(
            treatment_status="approved",
            approved_treatment="carry_forward",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-09",
        )
        record_a = _record(**base, approved_for_official_use=False)
        record_b = _record(**base, approved_for_official_use=True)
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) != variable_coverage_records_fingerprint([record_b])

    def test_frequency_change_changes_fingerprint(self):
        record_a = _record(frequency=_frequency(native_frequency="weekly"))
        record_b = _record(frequency=_frequency(native_frequency="monthly"))
        assert variable_coverage_records_fingerprint(
            [record_a]
        ) != variable_coverage_records_fingerprint([record_b])
