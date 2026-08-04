"""Tests for the official curve artifact schema (PR 95A / REQ-CURVE-001).

Covers: schema versioning; JSON-safe metadata validation; the historical
evidence chain; deterministic fingerprints that bind key names and values;
unknown-field preservation; the migration hook; and the single-artifact
write/read round-trip that fails closed on missing, malformed, tampered, or
unknown-version input. Also verifies that the artifact status vocabulary is
disjoint from OUTCOME_APPROVAL_STATUSES (approved decision 4, Work package G).
"""

import dataclasses
import json

import pandas as pd
import pytest

from ancestry_mmm.core.curve_artifact import (
    CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS,
    CURVE_ARTIFACT_DRAW_VALUE_REQUIRED_COLUMNS,
    CURVE_ARTIFACT_DRAWS_FILENAME,
    CURVE_ARTIFACT_FORMAT_STATUSES,
    CURVE_ARTIFACT_GENERATOR_VERSION,
    CURVE_ARTIFACT_METADATA_FILENAME,
    CURVE_ARTIFACT_SCHEMA_VERSION,
    CURVE_ARTIFACT_SNAPSHOT_FIELDS,
    CURVE_ARTIFACT_SUMMARIES_FILENAME,
    CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS,
    CURVE_CURRENT_AUTHORIZATION_STATUSES,
    CURVE_HISTORICAL_INTEGRITY_STATUSES,
    CURVE_USE_ELIGIBILITY_STATUSES,
    CurveArtifact,
    CurveArtifactError,
    CurveArtifactMetadata,
    CurveArtifactMigrationResult,
    CurveArtifactStoreError,
    CurveArtifactStoreLoadResult,
    compute_curve_artifact_fingerprints,
    compute_legacy_curve_artifact_fingerprints,
    fingerprint_curve_artifact_payload,
    governed_context_fields,
    load_curve_artifact_store,
    migrate_curve_artifact_metadata,
    migrate_curve_artifact_store,
    read_curve_artifact,
    verify_curve_artifact_fingerprints,
    verify_curve_artifact_fingerprints_allow_legacy,
    write_curve_artifact,
)
from ancestry_mmm.core.fingerprint import fingerprint_dataframe
from ancestry_mmm.core.outcome_approval import OUTCOME_APPROVAL_STATUSES

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _base_metadata() -> CurveArtifactMetadata:
    return CurveArtifactMetadata(
        artifact_id="art-1",
        creation_timestamp="2026-07-31T00:00:00+00:00",
        model_identity_snapshot={
            "model_run_id": "run-1",
            "data_fingerprint": "d1",
            "model_spec_fingerprint": "s1",
            "posterior_fingerprint": "p1",
        },
        approval_snapshot={"approval_id": "apr-1", "status": "approved"},
        threshold_policy_snapshot={"policy_id": "pol-1", "version": "1.0"},
        readiness_snapshot={"readiness_id": "rd-1", "overall_ready": True},
        diagnostics_snapshot={"artefact_id": "diag-1", "schema_version": 2},
        outcome_definition_snapshot={
            "outcome_id": "fh_new_gsa",
            "definition_version": "1.0",
        },
        outcome_approval_snapshot={
            "approval_id": "apr-o1",
            "allowed_uses": ["curve_publication"],
        },
        activity_governance_snapshot={"activities": ["tv-paid"]},
        pathway_governance_snapshot={"pathways": ["direct"]},
        reference_context_snapshot={"market": "UK", "mode": "steady_state_reference"},
        support_snapshot={"observed_support_status": "available"},
        cost_currency_snapshot={"currency": "GBP", "fx_as_of_date": "2026-07-01"},
    )


def _metadata(**overrides: object) -> CurveArtifactMetadata:
    """Build a metadata object with consistent (verified) fingerprints."""
    values = dict(overrides)
    fingerprints = values.pop("fingerprints", None)
    base = dataclasses.replace(_base_metadata(), **values)
    if fingerprints is None:
        fingerprints = dict(compute_curve_artifact_fingerprints(base))
    return dataclasses.replace(base, fingerprints=fingerprints)


def _draws() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-1",
                "reference_context_id": "ctx-1",
                "market": "UK",
                "product": "fh",
                "segment": "New",
                "outcome_id": "fh_new_gsa",
                "metric_key": "fh_gsa",
                "channel": "TV",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "posterior_draw": 0,
                "incremental_response": 1.0,
            }
        ]
    )


def _summaries() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_run_id": "run-1",
                "reference_context_id": "ctx-1",
                "market": "UK",
                "product": "fh",
                "segment": "New",
                "outcome_id": "fh_new_gsa",
                "metric_key": "fh_gsa",
                "channel": "TV",
                "component_type": "direct",
                "pathway_role": "primary",
                "spend_point": 0,
                "incremental_response": 1.0,
            }
        ]
    )


# ---------------------------------------------------------------------------
# Schema basics
# ---------------------------------------------------------------------------


class TestSchemaBasics:
    def test_schema_version_is_defined(self):
        assert CURVE_ARTIFACT_SCHEMA_VERSION == 1
        assert CURVE_ARTIFACT_GENERATOR_VERSION

    def test_metadata_rejects_blank_artifact_id(self):
        with pytest.raises(ValueError, match="artifact_id"):
            _metadata(artifact_id="")

    def test_metadata_rejects_bad_creation_timestamp(self):
        with pytest.raises(ValueError, match="ISO-8601"):
            _metadata(creation_timestamp="not-a-date")

    def test_metadata_rejects_unknown_schema_version(self):
        with pytest.raises(ValueError, match="schema_version"):
            _metadata(schema_version=99)

    def test_metadata_rejects_non_json_safe_snapshot(self):
        with pytest.raises(ValueError, match="JSON-safe"):
            _metadata(approval_snapshot={"approval": object()})

    def test_metadata_rejects_invalid_status(self):
        with pytest.raises(ValueError, match="format_status"):
            _metadata(format_status="not_a_status")

    def test_metadata_rejects_bad_fingerprint_values(self):
        with pytest.raises(ValueError, match="fingerprints"):
            _metadata(fingerprints={"chain_fingerprint": 123})

    def test_metadata_rejects_empty_outcome_definition_snapshot(self):
        # Review-debt finding 1 (PR #97): an artifact with no outcome
        # definition binding must never be constructible, even though the
        # single production caller (CurveService) already populates this.
        with pytest.raises(ValueError, match="outcome_definition_snapshot"):
            _metadata(outcome_definition_snapshot={})

    def test_metadata_rejects_empty_outcome_approval_snapshot(self):
        with pytest.raises(ValueError, match="outcome_approval_snapshot"):
            _metadata(outcome_approval_snapshot={})


class TestMetadataRoundTrip:
    def test_to_dict_from_dict_roundtrip_preserves_unknown_keys(self):
        original = _metadata()
        payload = original.to_dict()
        payload["future_schema_field"] = {"nested": [1, 2, 3]}
        loaded = CurveArtifactMetadata.from_dict(payload)
        # unknown key is preserved, not silently dropped
        assert loaded.extra["future_schema_field"] == {"nested": [1, 2, 3]}
        # and re-emitted on serialisation
        assert loaded.to_dict()["future_schema_field"] == {"nested": [1, 2, 3]}
        # known fields round-trip unchanged
        assert loaded.artifact_id == original.artifact_id
        assert (
            loaded.outcome_definition_snapshot == original.outcome_definition_snapshot
        )

    def test_to_dict_is_json_serialisable(self):
        payload = _metadata().to_dict()
        json.dumps(payload)  # must not raise


# ---------------------------------------------------------------------------
# Corrective PR D4/D5: governed-context fields for display/export rows
# ---------------------------------------------------------------------------


class TestGovernedContextFields:
    def test_extracts_definition_version_segment_product_and_approval_status(self):
        metadata = _metadata(
            outcome_definition_snapshot={
                "outcome_id": "fh_new_gsa",
                "definition_version": "2.0",
                "segment": "New",
                "product": "Family History",
            },
            outcome_approval_snapshot={
                "approval_id": "apr-o1",
                "status": "approved",
                "allowed_uses": ["curve_publication"],
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["outcome_definition_version"] == "2.0"
        assert fields["segment"] == "New"
        assert fields["product"] == "Family History"
        assert fields["outcome_approval_status"] == "approved"

    def test_extracts_currency_fx_and_component_scope_from_snapshot_rows(self):
        metadata = _metadata(
            cost_currency_snapshot={
                "rows": [
                    {
                        "market": "UK",
                        "local_currency": "GBP",
                        "reporting_currency": "GBP",
                        "fx_source": "test-fx-provider",
                        "fx_as_of_date": "2026-07-01",
                    },
                    {
                        "market": "AU",
                        "local_currency": "AUD",
                        "reporting_currency": "GBP",
                        "fx_source": "test-fx-provider",
                        "fx_as_of_date": "2026-07-01",
                    },
                ]
            },
            support_snapshot={
                "rows": [
                    {"market": "UK", "channel": "TV", "is_extrapolated": False},
                    {"market": "AU", "channel": "TV", "is_extrapolated": True},
                ]
            },
            pathway_governance_snapshot={
                "rows": [
                    {"channel": "TV", "component_type": "direct"},
                    {"channel": "DNA", "component_type": "cross_product"},
                ]
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["local_currency"] == "AUD, GBP"
        assert fields["reporting_currency"] == "GBP"
        assert fields["fx_source"] == "test-fx-provider"
        assert fields["fx_as_of_date"] == "2026-07-01"
        assert fields["component_scope"] == "cross_product, direct"
        # Any extrapolated row anywhere in the artifact is surfaced, not
        # silently averaged away or hidden behind a per-row-only flag.
        assert fields["extrapolation_status"] == "extrapolated"

    def test_reports_within_observed_range_when_no_row_is_extrapolated(self):
        metadata = _metadata(
            support_snapshot={
                "rows": [{"market": "UK", "channel": "TV", "is_extrapolated": False}]
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["extrapolation_status"] == "within observed range"

    def test_handles_missing_or_empty_snapshots_gracefully(self):
        # outcome_definition_snapshot/outcome_approval_snapshot must be
        # non-empty (CURVE_ARTIFACT_REQUIRED_NON_EMPTY_SNAPSHOT_FIELDS), but
        # the specific fields governed_context_fields reads from them are
        # not - and cost_currency/support/pathway snapshots have no such
        # requirement at all.
        metadata = _metadata(
            outcome_definition_snapshot={"outcome_id": "fh_new_gsa"},
            outcome_approval_snapshot={"approval_id": "apr-o1"},
            cost_currency_snapshot={},
            support_snapshot={},
            pathway_governance_snapshot={},
        )
        fields = governed_context_fields(metadata)
        assert fields["outcome_definition_version"] is None
        assert fields["segment"] is None
        assert fields["outcome_approval_status"] is None
        assert fields["local_currency"] is None
        assert fields["component_scope"] is None
        # Corrective PR E2.5: no support evidence at all must never be
        # asserted as "within observed range" - that claims evidence that
        # does not exist.
        assert fields["extrapolation_status"] == "support unavailable or unknown"

    def test_reports_unavailable_when_every_row_has_unknown_support(self):
        """is_extrapolated is None precisely when observed_support_status
        is not SUPPORT_AVAILABLE (canonical missing-support representation,
        core.canonical_curves.generate_canonical_curve_draws) - this must
        never be treated as "within observed range" evidence."""
        metadata = _metadata(
            support_snapshot={
                "rows": [
                    {"market": "UK", "channel": "TV", "is_extrapolated": None},
                    {"market": "UK", "channel": "DNA", "is_extrapolated": None},
                ]
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["extrapolation_status"] == "support unavailable or unknown"

    def test_reports_unavailable_when_some_rows_have_unknown_support_and_none_extrapolated(
        self,
    ):
        """A mix of known-non-extrapolated and unknown-support rows must
        not be rounded up to "within observed range" - only every relevant
        row being explicitly known non-extrapolated earns that label."""
        metadata = _metadata(
            support_snapshot={
                "rows": [
                    {"market": "UK", "channel": "TV", "is_extrapolated": False},
                    {"market": "UK", "channel": "DNA", "is_extrapolated": None},
                ]
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["extrapolation_status"] == "support unavailable or unknown"

    def test_reports_extrapolated_even_when_mixed_with_unknown_support_rows(self):
        """An extrapolated row is still the most actionable signal even
        alongside an unrelated unknown-support row - it must not be
        diluted into "unavailable or unknown"."""
        metadata = _metadata(
            support_snapshot={
                "rows": [
                    {"market": "UK", "channel": "TV", "is_extrapolated": True},
                    {"market": "UK", "channel": "DNA", "is_extrapolated": None},
                ]
            },
        )
        fields = governed_context_fields(metadata)
        assert fields["extrapolation_status"] == "extrapolated"


# ---------------------------------------------------------------------------
# PR 96A: unknown metadata is bound into integrity, not just preserved
# ---------------------------------------------------------------------------


class TestUnknownMetadataIntegrity:
    @staticmethod
    def _metadata_with_unknown_field(value: object = 1) -> CurveArtifactMetadata:
        payload = _metadata().to_dict()
        payload["future_schema_field"] = {"nested": value}
        loaded = CurveArtifactMetadata.from_dict(payload)
        return dataclasses.replace(
            loaded, fingerprints=dict(compute_curve_artifact_fingerprints(loaded))
        )

    def test_current_schema_round_trip_preserves_unknown_metadata(self, tmp_path):
        metadata = self._metadata_with_unknown_field()
        write_curve_artifact(
            tmp_path, metadata=metadata, draws=_draws(), summaries=_summaries()
        )
        artifact = read_curve_artifact(tmp_path)
        assert artifact.metadata.extra["future_schema_field"] == {"nested": 1}
        verify_curve_artifact_fingerprints(artifact.metadata)  # must not raise

    def test_unknown_metadata_key_tampering_is_detected(self, tmp_path):
        metadata = self._metadata_with_unknown_field()
        write_curve_artifact(
            tmp_path, metadata=metadata, draws=_draws(), summaries=_summaries()
        )
        envelope = json.loads(
            (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).read_text(encoding="utf-8")
        )
        # Add a brand new unknown key directly to the persisted JSON, without
        # recomputing fingerprints - simulates a file edited outside the
        # write_curve_artifact boundary.
        envelope["metadata"]["another_future_field"] = "sneaky"
        (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            read_curve_artifact(tmp_path)

    def test_unknown_metadata_value_tampering_is_detected(self, tmp_path):
        metadata = self._metadata_with_unknown_field(value=1)
        write_curve_artifact(
            tmp_path, metadata=metadata, draws=_draws(), summaries=_summaries()
        )
        envelope = json.loads(
            (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).read_text(encoding="utf-8")
        )
        envelope["metadata"]["future_schema_field"] = {"nested": 999}
        (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            read_curve_artifact(tmp_path)


# ---------------------------------------------------------------------------
# Fingerprints (bind key names and values)
# ---------------------------------------------------------------------------


class TestFingerprints:
    def test_fingerprint_is_deterministic(self):
        payload = {"a": 1, "b": [1, 2]}
        assert fingerprint_curve_artifact_payload(payload) == (
            fingerprint_curve_artifact_payload(payload)
        )

    def test_fingerprint_binds_values(self):
        assert fingerprint_curve_artifact_payload({"a": 1}) != (
            fingerprint_curve_artifact_payload({"a": 2})
        )

    def test_fingerprint_binds_key_names(self):
        # same values, different keys -> different fingerprint
        assert fingerprint_curve_artifact_payload({"a": 1, "b": 2}) != (
            fingerprint_curve_artifact_payload({"b": 1, "a": 2})
        )

    def test_compute_fingerprints_covers_every_snapshot(self):
        fingerprints = compute_curve_artifact_fingerprints(_base_metadata())
        assert set(fingerprints) == {
            "chain_fingerprint",
            "extra_fingerprint",
            *CURVE_ARTIFACT_SNAPSHOT_FIELDS,
        }

    def test_verify_passes_when_intact(self):
        verify_curve_artifact_fingerprints(_metadata())  # must not raise

    def test_verify_fails_when_snapshot_tampered(self):
        metadata = _metadata()
        tampered = dataclasses.replace(
            metadata,
            approval_snapshot={**metadata.approval_snapshot, "status": "rejected"},
        )
        # Tampering changes the chain fingerprint (raised first) and the
        # per-snapshot approval_snapshot fingerprint; either way it fails closed.
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            verify_curve_artifact_fingerprints(tampered)

    def test_verify_fails_when_fingerprints_missing(self):
        with pytest.raises(CurveArtifactError, match="chain_fingerprint"):
            verify_curve_artifact_fingerprints(_base_metadata())


# ---------------------------------------------------------------------------
# Migration hook
# ---------------------------------------------------------------------------


class TestMigrationHook:
    def test_current_version_passes_through(self):
        payload = _metadata().to_dict()
        migrated = migrate_curve_artifact_metadata(payload)
        assert migrated["schema_version"] == CURVE_ARTIFACT_SCHEMA_VERSION

    def test_unknown_version_fails_closed(self):
        with pytest.raises(CurveArtifactError, match="Unsupported"):
            migrate_curve_artifact_metadata({"schema_version": 99})


# ---------------------------------------------------------------------------
# Round-trip IO (fail closed)
# ---------------------------------------------------------------------------


class TestRoundTripIO:
    def test_write_read_roundtrip(self, tmp_path):
        metadata = _metadata()
        draws = _draws()
        summaries = _summaries()
        write_curve_artifact(
            tmp_path, metadata=metadata, draws=draws, summaries=summaries
        )
        artifact = read_curve_artifact(tmp_path)
        assert artifact.metadata == metadata
        pd.testing.assert_frame_equal(artifact.draws, draws)
        pd.testing.assert_frame_equal(artifact.summaries, summaries)

    def test_read_returns_curve_artifact_container(self, tmp_path):
        write_curve_artifact(
            tmp_path, metadata=_metadata(), draws=_draws(), summaries=_summaries()
        )
        artifact = read_curve_artifact(tmp_path)
        assert isinstance(artifact, CurveArtifact)

    def test_write_rejects_table_missing_identity_columns(self, tmp_path):
        with pytest.raises(CurveArtifactError, match="required column"):
            write_curve_artifact(
                tmp_path,
                metadata=_metadata(),
                draws=_draws().drop(columns=["channel"]),
                summaries=_summaries(),
            )

    def test_write_rejects_draws_table_missing_value_columns(self, tmp_path):
        # Review-debt finding 2 (PR #97): a summary-shaped frame (identity
        # columns only, no posterior_draw/incremental_response) must not be
        # accepted as a draws table.
        summary_shaped = _draws().drop(
            columns=list(CURVE_ARTIFACT_DRAW_VALUE_REQUIRED_COLUMNS)
        )
        with pytest.raises(CurveArtifactError, match="required column"):
            write_curve_artifact(
                tmp_path,
                metadata=_metadata(),
                draws=summary_shaped,
                summaries=_summaries(),
            )

    def test_write_rejects_metadata_with_unpopulated_fingerprints(self, tmp_path):
        # Review-debt finding 3 (PR #97): a write with empty/unpopulated
        # fingerprints must fail before anything touches disk, rather than
        # succeeding and only failing on the next read.
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            write_curve_artifact(
                tmp_path,
                metadata=_base_metadata(),
                draws=_draws(),
                summaries=_summaries(),
            )
        assert not (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).exists()
        assert not (tmp_path / CURVE_ARTIFACT_DRAWS_FILENAME).exists()
        assert not (tmp_path / CURVE_ARTIFACT_SUMMARIES_FILENAME).exists()

    def test_write_rejects_empty_table(self, tmp_path):
        with pytest.raises(CurveArtifactError, match="empty"):
            write_curve_artifact(
                tmp_path,
                metadata=_metadata(),
                draws=_draws().iloc[0:0],
                summaries=_summaries(),
            )

    def test_read_fails_closed_on_missing_metadata(self, tmp_path):
        with pytest.raises(CurveArtifactError, match="Missing curve artifact metadata"):
            read_curve_artifact(tmp_path)

    def test_read_fails_closed_on_malformed_metadata_json(self, tmp_path):
        (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            "{not valid json", encoding="utf-8"
        )
        _draws().to_parquet(tmp_path / "curve_artifact_draws.parquet", index=False)
        _summaries().to_parquet(
            tmp_path / "curve_artifact_summaries.parquet", index=False
        )
        with pytest.raises(
            CurveArtifactError, match="Malformed curve artifact metadata"
        ):
            read_curve_artifact(tmp_path)

    def test_read_fails_closed_on_missing_table_fingerprint(self, tmp_path):
        payload = _metadata().to_dict()
        envelope = {
            "schema_version": CURVE_ARTIFACT_SCHEMA_VERSION,
            "metadata": payload,
        }
        (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        _draws().to_parquet(tmp_path / "curve_artifact_draws.parquet", index=False)
        _summaries().to_parquet(
            tmp_path / "curve_artifact_summaries.parquet", index=False
        )
        with pytest.raises(CurveArtifactError, match="draws fingerprint missing"):
            read_curve_artifact(tmp_path)

    def test_read_fails_closed_on_tampered_draws(self, tmp_path):
        write_curve_artifact(
            tmp_path, metadata=_metadata(), draws=_draws(), summaries=_summaries()
        )
        tampered = _draws().copy()
        tampered["incremental_response"] = tampered["incremental_response"] + 999.0
        tampered.to_parquet(tmp_path / "curve_artifact_draws.parquet", index=False)
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            read_curve_artifact(tmp_path)

    def test_read_fails_closed_on_unknown_schema_version(self, tmp_path):
        payload = _metadata().to_dict()
        payload["schema_version"] = 99
        envelope = {
            "schema_version": 99,
            "metadata": payload,
            "draws_fingerprint": "x",
            "summaries_fingerprint": "y",
        }
        (tmp_path / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        _draws().to_parquet(tmp_path / "curve_artifact_draws.parquet", index=False)
        _summaries().to_parquet(
            tmp_path / "curve_artifact_summaries.parquet", index=False
        )
        with pytest.raises(
            CurveArtifactError, match="Unsupported curve artifact schema"
        ):
            read_curve_artifact(tmp_path)

    def test_required_columns_are_non_empty(self):
        assert CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS
        assert CURVE_ARTIFACT_SUMMARY_REQUIRED_COLUMNS
        assert "model_run_id" in CURVE_ARTIFACT_DRAW_REQUIRED_COLUMNS


# ---------------------------------------------------------------------------
# Corrective PR A2: pre-96A legacy fingerprint migration.
#
# Review-debt finding 7 (PR #103, highest risk in the persistence bucket):
# PR 96A added "extra" into the fingerprint chain without bumping
# CURVE_ARTIFACT_SCHEMA_VERSION, so every schema-v1 artifact written before
# that change has fingerprints computed under the pre-96A formula (no
# "extra" key in chain_payload, no "extra_fingerprint" entry at all) and was
# becoming permanently unreadable *and* unmigratable.
# ---------------------------------------------------------------------------


def _write_artifact_bypassing_write_time_fingerprint_check(
    directory, metadata, draws, summaries
):
    """Write an artifact directly to disk exactly like write_curve_artifact
    does, but WITHOUT its write-time verify_curve_artifact_fingerprints
    call - used to simulate a pre-96A artifact already on disk, which
    write_curve_artifact itself would now correctly refuse to create."""
    directory.mkdir(parents=True, exist_ok=True)
    draws.to_parquet(directory / CURVE_ARTIFACT_DRAWS_FILENAME, index=False)
    summaries.to_parquet(directory / CURVE_ARTIFACT_SUMMARIES_FILENAME, index=False)
    envelope = {
        "schema_version": metadata.schema_version,
        "metadata": metadata.to_dict(),
        "draws_fingerprint": fingerprint_dataframe(draws),
        "summaries_fingerprint": fingerprint_dataframe(summaries),
    }
    (directory / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
        json.dumps(envelope, indent=2, sort_keys=True), encoding="utf-8"
    )


def _legacy_metadata(**overrides: object) -> CurveArtifactMetadata:
    """A metadata object whose fingerprints are computed under the pre-96A
    formula - exactly what a real schema-v1 artifact written before PR 96A
    has on disk."""
    base = dataclasses.replace(_base_metadata(), **overrides)
    legacy_fingerprints = dict(compute_legacy_curve_artifact_fingerprints(base))
    return dataclasses.replace(base, fingerprints=legacy_fingerprints)


class TestLegacyFingerprintMigration:
    def test_legacy_fingerprints_have_no_extra_fingerprint_key(self):
        legacy = compute_legacy_curve_artifact_fingerprints(_base_metadata())
        assert "extra_fingerprint" not in legacy
        current = compute_curve_artifact_fingerprints(_base_metadata())
        assert "extra_fingerprint" in current

    def test_pre_96a_artifact_is_still_readable(self, tmp_path):
        metadata = _legacy_metadata()
        _write_artifact_bypassing_write_time_fingerprint_check(
            tmp_path, metadata, _draws(), _summaries()
        )
        artifact = read_curve_artifact(tmp_path)  # must not raise
        assert artifact.metadata.format_status == "legacy"
        # the original (legacy) fingerprints are preserved, not silently
        # rewritten by a read
        assert "extra_fingerprint" not in artifact.metadata.fingerprints

    def test_verify_allow_legacy_reports_legacy(self):
        metadata = _legacy_metadata()
        assert verify_curve_artifact_fingerprints_allow_legacy(metadata) == "legacy"

    def test_verify_allow_legacy_reports_current(self):
        assert verify_curve_artifact_fingerprints_allow_legacy(_metadata()) == "current"

    def test_pre_96a_artifact_can_be_migrated_via_store_migration(self, tmp_path):
        # The store-level migration rescue path must actually be able to
        # reach and migrate a legacy artifact, not fail identically to a
        # direct read (the original bug: migrate_curve_artifact_store's
        # first step was read_curve_artifact, which used to raise).
        artifact_dir = tmp_path / "art-pre-96a"
        # A real pre-96A artifact was written before the "legacy"/"migrated"
        # format_status distinction existed for fingerprints, so its stored
        # format_status is "current" (the field's own default) even though
        # its fingerprints predate the extra-inclusion change - read must
        # detect this from fingerprint shape alone, not from format_status.
        metadata = _legacy_metadata(artifact_id="art-pre-96a")
        assert metadata.format_status == "current"
        _write_artifact_bypassing_write_time_fingerprint_check(
            artifact_dir, metadata, _draws(), _summaries()
        )
        result = migrate_curve_artifact_store(tmp_path)
        assert result.failed == ()
        assert result.migrated_count == 1
        migrated = read_curve_artifact(artifact_dir)
        assert migrated.metadata.format_status == "migrated"
        # After migration, the artifact verifies under the CURRENT formula.
        verify_curve_artifact_fingerprints(migrated.metadata)

    def test_malformed_current_artifact_is_not_reinterpreted_as_legacy(self, tmp_path):
        # A genuinely current-format artifact (has an extra_fingerprint key)
        # whose value is wrong must fail as tampered/corrupted, never be
        # silently treated as a legacy layout.
        metadata = _metadata()
        tampered = dataclasses.replace(
            metadata,
            fingerprints={**metadata.fingerprints, "extra_fingerprint": "wrong"},
        )
        with pytest.raises(CurveArtifactError, match="extra_fingerprint"):
            verify_curve_artifact_fingerprints_allow_legacy(tampered)

    def test_legacy_artifact_with_wrong_fingerprint_still_fails_closed(self):
        metadata = _legacy_metadata()
        tampered = dataclasses.replace(
            metadata,
            fingerprints={**metadata.fingerprints, "chain_fingerprint": "wrong"},
        )
        with pytest.raises(CurveArtifactError, match="fingerprint mismatch"):
            verify_curve_artifact_fingerprints_allow_legacy(tampered)


# ---------------------------------------------------------------------------
# Artifact status vocabulary (approved decision 4, Work package G)
# ---------------------------------------------------------------------------


class TestArtifactStatusSeparation:
    def test_artifact_status_vocabularies_are_disjoint_from_outcome_approval_statuses(
        self,
    ):
        artifact_statuses = (
            set(CURVE_ARTIFACT_FORMAT_STATUSES)
            | set(CURVE_HISTORICAL_INTEGRITY_STATUSES)
            | set(CURVE_CURRENT_AUTHORIZATION_STATUSES)
            | set(CURVE_USE_ELIGIBILITY_STATUSES)
        )
        # An outcome-approval status must never be reused as an artifact status.
        assert artifact_statuses.isdisjoint(set(OUTCOME_APPROVAL_STATUSES))

    def test_vocabulary_constants_are_exposed(self):
        # Guards against accidental re-introduction of outcome-approval values.
        assert "legacy_unapproved" not in CURVE_ARTIFACT_FORMAT_STATUSES
        assert "expired" not in CURVE_CURRENT_AUTHORIZATION_STATUSES
        assert "stale" not in CURVE_CURRENT_AUTHORIZATION_STATUSES


# ---------------------------------------------------------------------------
# PR 95D: store-level import, migration, and malformed-file audit
# ---------------------------------------------------------------------------


class TestStoreImportMigrationAudit:
    @staticmethod
    def _write_artifact(directory, artifact_id, **metadata_overrides):
        target = directory / artifact_id
        target.mkdir(parents=True, exist_ok=True)
        metadata = _metadata(artifact_id=artifact_id, **metadata_overrides)
        write_curve_artifact(
            target, metadata=metadata, draws=_draws(), summaries=_summaries()
        )
        return target

    @staticmethod
    def _write_corrupted_metadata(directory, artifact_id):
        target = directory / artifact_id
        target.mkdir(parents=True, exist_ok=True)
        (target / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            "{not valid json", encoding="utf-8"
        )
        _draws().to_parquet(target / "curve_artifact_draws.parquet", index=False)
        _summaries().to_parquet(
            target / "curve_artifact_summaries.parquet", index=False
        )
        return target

    @staticmethod
    def _write_unsupported_schema(directory, artifact_id):
        target = directory / artifact_id
        target.mkdir(parents=True, exist_ok=True)
        payload = _metadata().to_dict()
        payload["schema_version"] = 99
        envelope = {
            "schema_version": 99,
            "metadata": payload,
            "draws_fingerprint": "x",
            "summaries_fingerprint": "y",
        }
        (target / CURVE_ARTIFACT_METADATA_FILENAME).write_text(
            json.dumps(envelope), encoding="utf-8"
        )
        _draws().to_parquet(target / "curve_artifact_draws.parquet", index=False)
        _summaries().to_parquet(
            target / "curve_artifact_summaries.parquet", index=False
        )
        return target

    def test_missing_store_is_empty(self, tmp_path):
        result = load_curve_artifact_store(tmp_path / "does-not-exist")
        assert isinstance(result, CurveArtifactStoreLoadResult)
        assert result.loaded == ()
        assert result.audit == ()

    def test_loads_multiple_artifacts_with_audit(self, tmp_path):
        self._write_artifact(tmp_path, "art-a")
        self._write_artifact(tmp_path, "art-b")
        result = load_curve_artifact_store(tmp_path)
        assert len(result.loaded) == 2
        assert len(result.audit) == 2
        assert all(entry.status == "loaded" for entry in result.audit)
        assert {entry.artifact_dir.name for entry in result.audit} == {"art-a", "art-b"}

    def test_store_roundtrip_preserves_artifacts(self, tmp_path):
        self._write_artifact(tmp_path, "art-a")
        result = load_curve_artifact_store(tmp_path)
        assert result.loaded[0].metadata.artifact_id == "art-a"
        assert not result.loaded[0].draws.empty

    def test_single_artifact_directory_is_a_store(self, tmp_path):
        self._write_artifact(tmp_path, "art-a")  # artifact dir itself is the store
        result = load_curve_artifact_store(tmp_path / "art-a")
        assert len(result.loaded) == 1
        assert result.loaded[0].metadata.artifact_id == "art-a"

    def test_malformed_artifact_is_audited_and_fails_closed(self, tmp_path):
        self._write_artifact(tmp_path, "art-good")
        self._write_corrupted_metadata(tmp_path, "art-bad")
        with pytest.raises(CurveArtifactStoreError, match="failed to load"):
            load_curve_artifact_store(tmp_path)

    def test_malformed_artifact_audit_inspectable_without_raising(self, tmp_path):
        self._write_artifact(tmp_path, "art-good")
        self._write_corrupted_metadata(tmp_path, "art-bad")
        result = load_curve_artifact_store(tmp_path, raise_on_malformed=False)
        assert len(result.loaded) == 1
        malformed = result.malformed
        assert len(malformed) == 1
        assert malformed[0].artifact_dir.name == "art-bad"
        assert malformed[0].status == "malformed"
        assert malformed[0].error  # the reason is never hidden

    def test_unsupported_schema_is_audited_as_unsupported(self, tmp_path):
        self._write_unsupported_schema(tmp_path, "art-future")
        result = load_curve_artifact_store(tmp_path, raise_on_malformed=False)
        assert result.malformed[0].status == "unsupported_schema"
        assert "schema_version" in result.malformed[0].error

    def test_migration_dry_run_reports_legacy_stamp_without_writing(self, tmp_path):
        target = self._write_artifact(tmp_path, "art-legacy", format_status="legacy")
        result = migrate_curve_artifact_store(tmp_path, dry_run=True)
        assert isinstance(result, CurveArtifactMigrationResult)
        assert result.migrated_count == 1
        assert result.failed == ()
        # dry run must not rewrite the persisted metadata
        assert read_curve_artifact(target).metadata.format_status == "legacy"

    def test_migration_rewrites_legacy_format_and_reloads(self, tmp_path):
        target = self._write_artifact(tmp_path, "art-legacy", format_status="legacy")
        result = migrate_curve_artifact_store(tmp_path)
        assert result.migrated_count == 1
        migrated = read_curve_artifact(target)
        assert migrated.metadata.format_status == "migrated"
        # fingerprints were recomputed and verify on reload (fail closed)
        assert migrated.draws.equals(_draws())

    def test_migration_fails_closed_on_unsupported_schema(self, tmp_path):
        self._write_unsupported_schema(tmp_path, "art-future")
        with pytest.raises(CurveArtifactStoreError, match="failed to migrate"):
            migrate_curve_artifact_store(tmp_path)

    def test_migration_identity_for_current_format(self, tmp_path):
        self._write_artifact(tmp_path, "art-current")
        result = migrate_curve_artifact_store(tmp_path)
        assert result.migrated_count == 0
        assert result.failed == ()

    # -----------------------------------------------------------------
    # Corrective PR A3: partial-artifact audit, schema-version
    # preservation, directory-identified fail-closed errors.
    # -----------------------------------------------------------------

    def test_partial_artifact_missing_metadata_is_audited_as_malformed(self, tmp_path):
        # Review-debt finding 4 (PR #100): metadata deleted (or an
        # interrupted write) leaves only the Parquet tables - this must
        # still surface as a malformed audit entry, not be silently skipped.
        target = self._write_artifact(tmp_path, "art-partial")
        (target / CURVE_ARTIFACT_METADATA_FILENAME).unlink()
        result = load_curve_artifact_store(tmp_path, raise_on_malformed=False)
        assert result.loaded == ()
        assert len(result.malformed) == 1
        assert result.malformed[0].artifact_dir.name == "art-partial"
        assert result.malformed[0].status == "malformed"
        assert "metadata" in result.malformed[0].error.lower()

    def test_partial_artifact_raises_when_raise_on_malformed(self, tmp_path):
        target = self._write_artifact(tmp_path, "art-partial")
        (target / CURVE_ARTIFACT_METADATA_FILENAME).unlink()
        with pytest.raises(CurveArtifactStoreError, match="failed to load"):
            load_curve_artifact_store(tmp_path)

    def test_migration_failure_preserves_parsed_schema_version(self, tmp_path):
        # Review-debt finding 5 (PR #100): a failed migration entry must
        # report the artifact's actual (unsupported) schema version, not
        # always 0 - otherwise it's indistinguishable from a v1 artifact
        # whose fingerprint chain failed for an unrelated reason.
        self._write_unsupported_schema(tmp_path, "art-future")
        result = migrate_curve_artifact_store(tmp_path, raise_on_error=False)
        assert len(result.failed) == 1
        assert result.failed[0].schema_version == 99

    def test_migration_failure_schema_version_falls_back_to_zero_when_unparseable(
        self, tmp_path
    ):
        target = self._write_corrupted_metadata(tmp_path, "art-corrupt")
        result = migrate_curve_artifact_store(tmp_path, raise_on_error=False)
        assert len(result.failed) == 1
        assert result.failed[0].schema_version == 0
        assert result.failed[0].artifact_dir == target

    def test_load_failure_message_identifies_artifact_directory(self, tmp_path):
        # Review-debt finding 6 (PR #100): an operator with multiple
        # artifacts must be able to tell which directory failed from the
        # exception message alone.
        self._write_corrupted_metadata(tmp_path, "art-bad-1")
        self._write_corrupted_metadata(tmp_path, "art-bad-2")
        with pytest.raises(CurveArtifactStoreError) as excinfo:
            load_curve_artifact_store(tmp_path)
        assert "art-bad-1" in str(excinfo.value)
        assert "art-bad-2" in str(excinfo.value)

    def test_migration_failure_message_identifies_artifact_directory(self, tmp_path):
        self._write_corrupted_metadata(tmp_path, "art-bad-1")
        with pytest.raises(CurveArtifactStoreError) as excinfo:
            migrate_curve_artifact_store(tmp_path)
        assert "art-bad-1" in str(excinfo.value)
