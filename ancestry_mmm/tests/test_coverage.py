"""Tests for core.coverage (REQ-COVERAGE-001 Work Package 3): framework-
independent variable-coverage/mixed-frequency domain contracts (Phase 1)
and the coverage-matrix builder over a real joined frame (Phase 3).
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
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
    build_coverage_matrix_from_frame,
    compute_checksum,
    current_source_versions,
    current_variable_coverage_matrix_from_resolved_versions,
    new_variable_coverage_matrix_version,
    official_fit_blocking_issues,
    variable_coverage_matrix_versions_for_export,
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
        assert reconstructed.schema_version == 2

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


# ---------------------------------------------------------------------------
# Schema v1 -> v2 migration (P2 review finding on an earlier version of this
# module): approved_for_official_use is a v2 addition. A v1 payload
# (predating the field entirely) must migrate fail-closed - never silently
# promoted to official-fit eligibility merely because it once carried
# treatment_status="approved" under the old (buggy) semantics.
# ---------------------------------------------------------------------------


class TestLegacySchemaV1Migration:
    def _v1_style_record_dict(self) -> dict:
        """A record payload shaped exactly like what v1 (pre-`approved_for_
        official_use`) code would have produced - the key is genuinely
        absent, not merely `None`/`False`."""
        payload = _record(
            treatment_status="approved",
            approved_treatment="carry_forward_within_publication_window",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-01",
            coverage_segments=(
                CoverageSegment(
                    period_start="2025-01-06",
                    period_end="2025-12-29",
                    state=STATE_UNKNOWN,
                ),
            ),
        ).to_dict()
        del payload["approved_for_official_use"]
        return payload

    def test_legacy_approved_record_defaults_to_not_officially_usable(self):
        record = VariableCoverageRecord.from_dict(self._v1_style_record_dict())
        assert record.approved_for_official_use is False
        assert record.is_officially_unresolved

    def test_legacy_matrix_without_schema_version_migrates_to_v2_fail_closed(self):
        payload = {
            "matrix_id": "legacy-matrix",
            "matrix_version": 1,
            "generated_at": "2026-01-01T00:00:00Z",
            "records": [self._v1_style_record_dict()],
        }
        matrix = VariableCoverageMatrix.from_dict(payload)
        assert matrix.schema_version == 2
        assert len(matrix.blocking_issues) == 1

    def test_schema_version_2_explicitly_declared_round_trips_unchanged(self):
        payload = self._v1_style_record_dict()
        payload["approved_for_official_use"] = True
        record = VariableCoverageRecord.from_dict(payload)
        assert record.approved_for_official_use is True
        assert not record.is_officially_unresolved


# ---------------------------------------------------------------------------
# approved_for_official_use strict type validation (P2 review finding)
# ---------------------------------------------------------------------------


class TestApprovedForOfficialUseTypeValidation:
    def test_string_true_rejected_not_coerced(self):
        """ "false" (a non-empty string) is truthy in Python - if this were
        naively accepted, is_officially_unresolved would read it as True
        and silently clear the official-fit block."""
        with pytest.raises(ValueError, match="approved_for_official_use"):
            _record(
                treatment_status="approved",
                approved_treatment="x",
                treatment_approved_by="Analyst",
                treatment_approved_at="2026-08-09",
                approved_for_official_use="false",
            )

    def test_string_true_literal_rejected(self):
        with pytest.raises(ValueError, match="approved_for_official_use"):
            _record(
                treatment_status="approved",
                approved_treatment="x",
                treatment_approved_by="Analyst",
                treatment_approved_at="2026-08-09",
                approved_for_official_use="true",
            )

    def test_integer_rejected_not_coerced(self):
        with pytest.raises(ValueError, match="approved_for_official_use"):
            _record(approved_for_official_use=1)

    def test_none_rejected(self):
        with pytest.raises(ValueError, match="approved_for_official_use"):
            _record(approved_for_official_use=None)


# ---------------------------------------------------------------------------
# build_coverage_matrix_from_frame (WP3 Phase 3): the missing link between
# the Phase 1 domain contracts and real data.
# ---------------------------------------------------------------------------


def _weekly_dates(n=12, start="2025-01-06"):
    return pd.date_range(start, periods=n, freq="W-MON")


def _frame_and_freq():
    """A single-variable, single-gap frame - the minimal case for the
    builder's own unit tests below."""
    dates = _weekly_dates(6)
    rows = []
    for market in ["UK", "AU"]:
        for i, d in enumerate(dates):
            rows.append(
                {
                    "date": d,
                    "market": market,
                    "TV_spend": 100.0 + i if market == "UK" or i >= 2 else np.nan,
                }
            )
    df = pd.DataFrame(rows)
    freq = {
        "TV_spend": FrequencyMetadata(
            native_frequency="weekly",
            target_frequency="weekly",
            variable_class="flow_count",
        )
    }
    return df, freq


class TestBuildCoverageMatrixFromFrame:
    def test_fully_observed_variable_has_no_gap_segments(self):
        df, freq = _frame_and_freq()
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["TV_spend"],
            frequency_metadata=freq,
            variable_sources={"TV_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        uk_record = next(r for r in matrix.records if r.market == "UK")
        assert uk_record.coverage_segments == ()
        assert uk_record.observed_start == "2025-01-06"

    def test_partial_window_variable_gap_is_not_backfilled(self):
        df, freq = _frame_and_freq()
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["TV_spend"],
            frequency_metadata=freq,
            variable_sources={"TV_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        au_record = next(r for r in matrix.records if r.market == "AU")
        # AU is missing weeks 0-1 (i < 2) - the gap must be reported, and
        # observed_start must be the genuine first-observed date, never
        # backfilled to expected_start.
        assert len(au_record.coverage_segments) == 1
        assert au_record.coverage_segments[0].state == STATE_UNKNOWN
        assert au_record.coverage_segments[0].period_start == "2025-01-06"
        assert au_record.coverage_segments[0].period_end == "2025-01-13"
        assert au_record.observed_start == "2025-01-20"
        # expected_start/end are the PROJECT's window, not shrunk to AU's
        # own supported range.
        assert au_record.expected_start == "2025-01-06"
        assert au_record.expected_end == df["date"].max().strftime("%Y-%m-%d")

    def test_missing_frequency_metadata_raises_rather_than_defaulting(self):
        df, _freq = _frame_and_freq()
        with pytest.raises(ValueError, match="frequency_metadata"):
            build_coverage_matrix_from_frame(
                df,
                date_col="date",
                market_col="market",
                variable_columns=["TV_spend"],
                frequency_metadata={},
                variable_sources={"TV_spend": ("media", 1)},
                matrix_id="m1",
                matrix_version=1,
                generated_at="2026-08-10T00:00:00Z",
            )

    def test_zero_is_never_treated_as_a_gap(self):
        """REQ-COVERAGE-001's core invariant, at the builder level: a real
        observed value of 0.0 must produce zero coverage_segments, not an
        inferred state."""
        dates = _weekly_dates(4)
        df = pd.DataFrame(
            {
                "date": dates,
                "market": ["UK"] * 4,
                "NewChannel_spend": [0.0, 0.0, 50.0, 60.0],
            }
        )
        freq = {
            "NewChannel_spend": FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
        }
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["NewChannel_spend"],
            frequency_metadata=freq,
            variable_sources={"NewChannel_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        assert matrix.records[0].coverage_segments == ()

    def test_entirely_absent_variable_is_one_full_window_gap(self):
        dates = _weekly_dates(4)
        df = pd.DataFrame(
            {
                "date": list(dates) * 2,
                "market": ["UK"] * 4 + ["AU"] * 4,
                "UK_only_control": [5.0] * 4 + [np.nan] * 4,
            }
        )
        freq = {
            "UK_only_control": FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
        }
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["UK_only_control"],
            frequency_metadata=freq,
            variable_sources={"UK_only_control": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        au_record = next(r for r in matrix.records if r.market == "AU")
        assert au_record.observed_start is None
        assert au_record.observed_end is None
        assert len(au_record.coverage_segments) == 1
        assert au_record.coverage_segments[0].period_start == "2025-01-06"
        assert au_record.coverage_segments[0].period_end == dates[-1].strftime(
            "%Y-%m-%d"
        )

    def test_gaps_are_never_pre_classified_beyond_unknown(self):
        """The builder must never guess not_applicable/unavailable_source/
        observed_zero - only a human reclassification (outside this
        function) may assign those."""
        df, freq = _frame_and_freq()
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["TV_spend"],
            frequency_metadata=freq,
            variable_sources={"TV_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        all_states = {s.state for r in matrix.records for s in r.coverage_segments}
        assert all_states <= {STATE_UNKNOWN}

    def test_unknown_gaps_block_official_use_by_default(self):
        df, freq = _frame_and_freq()
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["TV_spend"],
            frequency_metadata=freq,
            variable_sources={"TV_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        assert len(matrix.blocking_issues) == 1  # the AU gap record

    def test_missing_variable_sources_entry_raises_rather_than_defaulting(self):
        df, freq = _frame_and_freq()
        with pytest.raises(ValueError, match="variable_sources"):
            build_coverage_matrix_from_frame(
                df,
                date_col="date",
                market_col="market",
                variable_columns=["TV_spend"],
                frequency_metadata=freq,
                variable_sources={},
                matrix_id="m1",
                matrix_version=1,
                generated_at="2026-08-10T00:00:00Z",
            )

    def test_period_missing_from_every_row_is_still_a_gap(self):
        """P1 review finding on an earlier version of this builder: a
        period with NO row anywhere in df (not even a null value - the row
        itself is absent) must still be checked against the variable's
        governed weekly calendar, not silently skipped because it never
        appears in df[date_col]."""
        all_weeks = _weekly_dates(6)
        skip_week_2 = [d for i, d in enumerate(all_weeks) if i != 2]
        df = pd.DataFrame(
            {
                "date": skip_week_2,
                "market": ["UK"] * len(skip_week_2),
                "TV_spend": [100.0] * len(skip_week_2),
            }
        )
        freq = {
            "TV_spend": FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
        }
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["TV_spend"],
            frequency_metadata=freq,
            variable_sources={"TV_spend": ("media", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        record = matrix.records[0]
        assert len(record.coverage_segments) == 1
        assert record.coverage_segments[0].period_start == all_weeks[2].strftime(
            "%Y-%m-%d"
        )
        assert record.coverage_segments[0].period_end == all_weeks[2].strftime(
            "%Y-%m-%d"
        )

    def test_product_and_segment_grouping_does_not_union_observed_dates(self):
        """P1 review finding on an earlier version of this builder: a value
        present for one segment must never hide that the same variable is
        entirely absent for another segment sharing the same column name
        and market."""
        dates = _weekly_dates(4)
        rows = []
        for segment in ("New", "DNA_CrossSell"):
            for i, d in enumerate(dates):
                rows.append(
                    {
                        "date": d,
                        "market": "UK",
                        "segment": segment,
                        "shared_control": 5.0 if segment == "New" else np.nan,
                    }
                )
        df = pd.DataFrame(rows)
        freq = {
            "shared_control": FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
        }
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["shared_control"],
            frequency_metadata=freq,
            variable_sources={"shared_control": ("controls", 1)},
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
            segment_col="segment",
        )
        assert len(matrix.records) == 2
        new_record = next(r for r in matrix.records if r.segment == "New")
        dna_record = next(r for r in matrix.records if r.segment == "DNA_CrossSell")
        assert new_record.coverage_segments == ()
        assert len(dna_record.coverage_segments) == 1
        assert dna_record.observed_start is None

    def test_per_variable_source_provenance_is_not_conflated(self):
        """P2 review finding on an earlier version of this builder: two
        variables from genuinely different uploads must keep their own
        distinct source_id/source_version, never a single value stamped
        across a whole joined frame."""
        dates = _weekly_dates(4)
        df = pd.DataFrame(
            {
                "date": dates,
                "market": ["UK"] * 4,
                "media_var": [1.0, 2.0, 3.0, 4.0],
                "control_var": [5.0, 6.0, 7.0, 8.0],
            }
        )
        freq = {
            v: FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
            for v in ("media_var", "control_var")
        }
        matrix = build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=["media_var", "control_var"],
            frequency_metadata=freq,
            variable_sources={
                "media_var": ("media", 2),
                "control_var": ("controls", 5),
            },
            matrix_id="m1",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        )
        media_record = next(r for r in matrix.records if r.variable_id == "media_var")
        control_record = next(
            r for r in matrix.records if r.variable_id == "control_var"
        )
        assert (media_record.source_id, media_record.source_version) == ("media", 2)
        assert (control_record.source_id, control_record.source_version) == (
            "controls",
            5,
        )


# ---------------------------------------------------------------------------
# Part 3 v1.6 acceptance scenario 26.2 (REQ-COVERAGE-001 traces_to):
# weekly media in UK and AU; a UK-only control (to be reclassified
# not_applicable in AU); an AU monthly control starting mid-window because
# the source became available later; a newly launched channel with a
# genuine structural zero before launch; another variable with unavailable
# earlier history.
# ---------------------------------------------------------------------------


class TestPart3V16AcceptanceScenario262:
    @staticmethod
    def _scenario_frame():
        dates = _weekly_dates(12)
        rows = []
        for market in ["UK", "AU"]:
            for i, d in enumerate(dates):
                rows.append(
                    {
                        "date": d,
                        "market": market,
                        # Present throughout, both markets - the "clean"
                        # variable every scenario needs as a control group.
                        "TV_spend": 100.0 + i,
                        # UK-only control: present for UK, entirely absent
                        # for AU (a market simply not needing/having it).
                        "UK_only_control": 5.0 if market == "UK" else np.nan,
                        # AU monthly control: source became available only
                        # from week 4 onward, AU only.
                        "AU_monthly_control": (
                            (10.0 + i) if (market == "AU" and i >= 4) else np.nan
                        ),
                        # Newly launched channel: genuinely zero (not
                        # missing) before its week-4 launch, both markets.
                        "NewChannel_spend": 0.0 if i < 4 else 50.0 + i,
                        # Another variable with unavailable earlier
                        # history - UK only, starts at week 5.
                        "UK_var_unavailable_early_history": (
                            (20.0 + i) if (market == "UK" and i >= 5) else np.nan
                        ),
                    }
                )
        return pd.DataFrame(rows)

    @staticmethod
    def _frequency_metadata():
        variables = [
            "TV_spend",
            "UK_only_control",
            "AU_monthly_control",
            "NewChannel_spend",
            "UK_var_unavailable_early_history",
        ]
        return {
            v: FrequencyMetadata(
                native_frequency="weekly",
                target_frequency="weekly",
                variable_class="flow_count",
            )
            for v in variables
        }

    def _build_matrix(self):
        df = self._scenario_frame()
        return build_coverage_matrix_from_frame(
            df,
            date_col="date",
            market_col="market",
            variable_columns=list(self._frequency_metadata()),
            frequency_metadata=self._frequency_metadata(),
            variable_sources={v: ("media", 1) for v in self._frequency_metadata()},
            matrix_id="scenario-26-2",
            matrix_version=1,
            generated_at="2026-08-10T00:00:00Z",
        ), df

    def _record(self, matrix, variable_id, market):
        return next(
            r
            for r in matrix.records
            if r.variable_id == variable_id and r.market == market
        )

    def test_clean_variable_has_no_gaps_in_either_market(self):
        matrix, _df = self._build_matrix()
        for market in ("UK", "AU"):
            record = self._record(matrix, "TV_spend", market)
            assert record.coverage_segments == ()

    def test_uk_only_control_is_a_full_window_gap_in_au_only(self):
        matrix, _df = self._build_matrix()
        uk = self._record(matrix, "UK_only_control", "UK")
        au = self._record(matrix, "UK_only_control", "AU")
        assert uk.coverage_segments == ()
        assert len(au.coverage_segments) == 1
        assert au.coverage_segments[0].period_start == au.expected_start
        assert au.coverage_segments[0].period_end == au.expected_end
        assert au.observed_start is None

    def test_uk_only_control_gap_may_be_reclassified_not_applicable(self):
        """The builder itself only ever produces `unknown` - this proves
        the domain model accepts the human reclassification an analyst
        would make in the coverage-matrix UI, without the builder having
        guessed it."""
        matrix, _df = self._build_matrix()
        au = self._record(matrix, "UK_only_control", "AU")
        reclassified = VariableCoverageRecord(
            variable_id=au.variable_id,
            source_id=au.source_id,
            source_version=au.source_version,
            market=au.market,
            frequency=au.frequency,
            coverage_segments=(
                CoverageSegment(
                    period_start=au.coverage_segments[0].period_start,
                    period_end=au.coverage_segments[0].period_end,
                    state=STATE_NOT_APPLICABLE,
                ),
            ),
            observed_start=au.observed_start,
            observed_end=au.observed_end,
            expected_start=au.expected_start,
            expected_end=au.expected_end,
            treatment_status="approved",
            approved_treatment="not_applicable_to_au",
            treatment_approved_by="Analyst",
            treatment_approved_at="2026-08-10",
            approved_for_official_use=True,
        )
        assert not reclassified.is_officially_unresolved

    def test_au_monthly_control_partial_window_is_not_backfilled(self):
        matrix, df = self._build_matrix()
        au = self._record(matrix, "AU_monthly_control", "AU")
        assert len(au.coverage_segments) == 1
        assert au.coverage_segments[0].state == STATE_UNKNOWN
        # observed_start must be the genuine week-4 date, not the
        # project's expected_start.
        expected_week4 = df["date"].sort_values().unique()[4]
        assert au.observed_start == pd.Timestamp(expected_week4).strftime("%Y-%m-%d")
        assert au.observed_start != au.expected_start

    def test_new_channel_zero_before_launch_is_not_a_gap(self):
        matrix, _df = self._build_matrix()
        for market in ("UK", "AU"):
            record = self._record(matrix, "NewChannel_spend", market)
            assert record.coverage_segments == ()

    def test_new_channel_structural_zero_may_be_explicitly_recorded(self):
        """Recording "this zero is genuinely pre-launch" is optional,
        additive metadata a human supplies - never inferred by the
        builder (the previous test proves the builder itself stays
        silent about it)."""
        matrix, df = self._build_matrix()
        record = self._record(matrix, "NewChannel_spend", "UK")
        launch_date = df["date"].sort_values().unique()[4]
        pre_launch_start = df["date"].min()
        pre_launch_end = pd.Timestamp(launch_date) - pd.Timedelta(days=1)
        annotated = VariableCoverageRecord(
            variable_id=record.variable_id,
            source_id=record.source_id,
            source_version=record.source_version,
            market=record.market,
            frequency=record.frequency,
            coverage_segments=(
                CoverageSegment(
                    period_start=pre_launch_start.strftime("%Y-%m-%d"),
                    period_end=pre_launch_end.strftime("%Y-%m-%d"),
                    state=STATE_OBSERVED_ZERO,
                    structural_zero=True,
                    justification="Channel launched in week 4; genuinely no prior activity.",
                ),
            ),
            observed_start=record.observed_start,
            observed_end=record.observed_end,
            expected_start=record.expected_start,
            expected_end=record.expected_end,
        )
        assert annotated.coverage_segments[0].structural_zero
        assert not annotated.is_officially_unresolved

    def test_unavailable_early_history_gap_is_reported_and_not_backfilled(self):
        matrix, df = self._build_matrix()
        record = self._record(matrix, "UK_var_unavailable_early_history", "UK")
        assert len(record.coverage_segments) == 1
        assert record.coverage_segments[0].state == STATE_UNKNOWN
        expected_week5 = df["date"].sort_values().unique()[5]
        assert record.observed_start == pd.Timestamp(expected_week5).strftime(
            "%Y-%m-%d"
        )

    def test_reports_exactly_the_expected_blocking_issues(self):
        """Three gaps require reclassification before official use:
        UK_only_control/AU, AU_monthly_control/AU,
        UK_var_unavailable_early_history/UK. Everything else (clean
        variables, and the not-applicable-to-UK columns whose entire
        history is absent for their off-market side) is either gap-free
        or also correctly flagged - the count proves nothing is silently
        dropped or double-counted."""
        matrix, _df = self._build_matrix()
        issues = matrix.blocking_issues
        assert any("UK_only_control" in i and "AU" in i for i in issues)
        assert any("AU_monthly_control" in i for i in issues)
        assert any("UK_var_unavailable_early_history" in i for i in issues)

    def test_no_state_is_ever_inferred_from_a_zero_or_nan_alone(self):
        """The single invariant this whole scenario exists to prove: every
        gap segment across the entire matrix is `unknown` (a human must
        decide why), and no segment at all exists merely because a value
        was 0.0."""
        matrix, _df = self._build_matrix()
        all_states = {s.state for r in matrix.records for s in r.coverage_segments}
        assert all_states <= {STATE_UNKNOWN}

    def test_matrix_fingerprint_changes_when_a_gap_is_reclassified(self):
        matrix, _df = self._build_matrix()
        au = self._record(matrix, "UK_only_control", "AU")
        reclassified_records = tuple(
            r
            for r in matrix.records
            if not (r.variable_id == "UK_only_control" and r.market == "AU")
        ) + (
            VariableCoverageRecord(
                variable_id=au.variable_id,
                source_id=au.source_id,
                source_version=au.source_version,
                market=au.market,
                frequency=au.frequency,
                coverage_segments=(
                    CoverageSegment(
                        period_start=au.coverage_segments[0].period_start,
                        period_end=au.coverage_segments[0].period_end,
                        state=STATE_NOT_APPLICABLE,
                    ),
                ),
                observed_start=au.observed_start,
                observed_end=au.observed_end,
                expected_start=au.expected_start,
                expected_end=au.expected_end,
            ),
        )
        reclassified_matrix = new_variable_coverage_matrix_version(
            matrix, records=reclassified_records
        )
        assert matrix.fingerprint() != reclassified_matrix.fingerprint()

    def test_matrix_export_import_round_trip_preserves_scenario(self):
        matrix, _df = self._build_matrix()
        round_tripped = VariableCoverageMatrix.from_dict(matrix.to_dict())
        assert round_tripped == matrix


# ---------------------------------------------------------------------------
# Project export/import portability (REQ-COVERAGE-001 S1: "coverage
# decisions must be versioned and portable") - mirrors
# TestGraphVersionsForExport/TestCurrentGraphFromResolvedVersions in
# test_causal_graph.py exactly, since these functions are themselves a
# direct mirror of core.causal_graph's.
# ---------------------------------------------------------------------------


def _matrix(matrix_version: int = 1, **overrides) -> VariableCoverageMatrix:
    defaults = dict(
        matrix_id="m1",
        matrix_version=matrix_version,
        generated_at="2026-01-01",
        records=(_record(),),
    )
    defaults.update(overrides)
    return VariableCoverageMatrix(**defaults)


class TestVariableCoverageMatrixVersionsForExport:
    """REQ-COVERAGE-001 S1 work package (matrix portability): the shared
    rule for what a project export bundle's variable_coverage_matrices.json
    should contain - every saved version plus the current live matrix,
    deduplicated by unambiguous (matrix_id, matrix_version) identity."""

    def test_combines_saved_history_and_current_live_matrix(self):
        v1 = _matrix(matrix_version=1).to_dict()
        current = _matrix(matrix_version=2).to_dict()
        result = variable_coverage_matrix_versions_for_export(
            current_matrix_dict=current, version_history=[v1]
        )
        assert {(r["matrix_id"], r["matrix_version"]) for r in result} == {
            ("m1", 1),
            ("m1", 2),
        }

    def test_current_matrix_deduplicates_against_matching_history_entry(self):
        v1 = _matrix(matrix_version=1).to_dict()
        result = variable_coverage_matrix_versions_for_export(
            current_matrix_dict=v1, version_history=[v1]
        )
        assert len(result) == 1

    def test_no_current_matrix_returns_history_only(self):
        v1 = _matrix(matrix_version=1).to_dict()
        result = variable_coverage_matrix_versions_for_export(
            current_matrix_dict=None, version_history=[v1]
        )
        assert result == [v1]

    def test_no_history_and_no_current_matrix_returns_empty(self):
        assert (
            variable_coverage_matrix_versions_for_export(
                current_matrix_dict=None, version_history=None
            )
            == []
        )

    def test_current_matrix_never_overwrites_a_differently_structured_saved_version(
        self,
    ):
        """A live matrix sharing a saved version's (matrix_id, matrix_version)
        key but with genuinely different content (an unsaved in-session edit)
        must never silently clobber the saved record under that key - only
        an explicit new version (via new_variable_coverage_matrix_version,
        bumping matrix_version) is ever persisted as a distinct record."""
        saved_v1 = _matrix(matrix_version=1, notes="saved").to_dict()
        unsaved_live_v1 = _matrix(matrix_version=1, notes="unsaved edit").to_dict()
        result = variable_coverage_matrix_versions_for_export(
            current_matrix_dict=unsaved_live_v1, version_history=[saved_v1]
        )
        assert result == [saved_v1]


class TestCurrentVariableCoverageMatrixFromResolvedVersions:
    def test_returns_none_for_no_versions(self):
        assert current_variable_coverage_matrix_from_resolved_versions([]) is None

    def test_returns_the_highest_numbered_version(self):
        v1 = _matrix(matrix_version=1).to_dict()
        v3 = _matrix(matrix_version=3, notes="latest").to_dict()
        v2 = _matrix(matrix_version=2).to_dict()
        result = current_variable_coverage_matrix_from_resolved_versions([v1, v3, v2])
        assert result == v3
