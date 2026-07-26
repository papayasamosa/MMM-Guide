"""Tests for authoritative uploaded net bill-through validation.

REQ-NBT-001: official NBT use requires both an approved outcome definition
AND valid completeness metadata for that same definition - approval alone
is not sufficient (see `validate_nbt_completeness_metadata_for_outcome`,
G2A.7a.1 section 10).
"""

from ancestry_mmm.core.net_billthrough import (
    NetBillthroughCompletenessMetadata,
    validate_nbt_completeness_metadata_for_outcome,
)
from ancestry_mmm.core.outcome_approval import fingerprint_outcome_definition
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    OutcomeDefinition,
)


def _nbt_outcome(**overrides) -> OutcomeDefinition:
    values = dict(
        outcome_id="fh_new_nbt",
        product=FAMILY_HISTORY,
        segment="New",
        metric="Net bill-through count",
        metric_key=METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        source_column="fh_net_billthrough_count",
        unit="bill-through subscriber",
        aggregation_type="count",
        event_definition="Net bill-through subscriber count",
        date_basis="signup_date_attributed",
        cohort_or_attribution_basis="signup_cohort",
        completeness_or_maturity_policy="Mature after 26 weeks",
        exclusions="Excludes cancelled within 30 days",
        reconciliation_source="Finance NBT report",
        business_owner="Analytics",
        definition_version="1.0",
    )
    values.update(overrides)
    return OutcomeDefinition(**values)


def _complete_metadata(outcome: OutcomeDefinition, **overrides) -> NetBillthroughCompletenessMetadata:
    values = dict(
        data_as_of_date="2026-07-20",
        model_start_week="2026-01-05",
        model_end_week="2026-07-13",
        latest_complete_net_billthrough_week="2026-07-13",
        maturity_rule_description="Mature after 26 weeks",
        source_owner="Finance",
        outcome_id=outcome.outcome_id,
        definition_version=outcome.definition_version,
        definition_fingerprint=fingerprint_outcome_definition(outcome),
    )
    values.update(overrides)
    return NetBillthroughCompletenessMetadata(**values)


class TestNBTCompletenessGate:
    """REQ-NBT-001: planning-time NBT completeness gate."""

    def test_missing_metadata_blocks(self):
        outcome = _nbt_outcome()
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, None)
        assert issues
        assert any("required" in i for i in issues)

    def test_complete_metadata_matching_outcome_passes(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome)
        assert validate_nbt_completeness_metadata_for_outcome(outcome, metadata) == []

    def test_complete_metadata_accepted_as_dict(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome)
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata.to_dict())
        assert issues == []

    def test_metadata_for_a_different_outcome_id_blocks(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome, outcome_id="some_other_outcome")
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("does not" in i or "not the requested" in i for i in issues)

    def test_stale_definition_fingerprint_blocks(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome, definition_fingerprint="stale-fingerprint")
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("stale" in i for i in issues)
        # Changing the definition (e.g. reconciliation_source) after
        # metadata was recorded must be caught the same way.
        changed = _nbt_outcome(reconciliation_source="A different source")
        metadata_for_original = _complete_metadata(outcome)
        issues_after_change = validate_nbt_completeness_metadata_for_outcome(
            changed, metadata_for_original,
        )
        assert any("stale" in i for i in issues_after_change)

    def test_latest_complete_week_before_model_end_blocks(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(
            outcome, latest_complete_net_billthrough_week="2026-06-01",
        )
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("earlier than model end week" in i for i in issues)

    def test_latest_complete_week_after_as_of_blocks(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(
            outcome, latest_complete_net_billthrough_week="2026-08-01",
        )
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("cannot be after data_as_of_date" in i for i in issues)

    def test_missing_maturity_rule_or_owner_blocks(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome, maturity_rule_description="", source_owner="")
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("maturity rule and source owner" in i for i in issues)

    def test_invalid_dates_block(self):
        outcome = _nbt_outcome()
        metadata = _complete_metadata(outcome, data_as_of_date="not-a-date")
        issues = validate_nbt_completeness_metadata_for_outcome(outcome, metadata)
        assert any("invalid dates" in i for i in issues)
