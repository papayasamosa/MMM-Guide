"""Tests for outcome approval governance (G2A.7).

REQ-OUT-002: Composable outcome approval
REQ-NBT-001: Conditional supplied-NBT use
REQ-PLAN-001: Explicit planning outcome
REQ-USE-001: Official versus exploratory outcome use
REQ-STALE-001: Definition-bound invalidation
"""

import json
from pathlib import Path

import pytest

from ancestry_mmm.core.outcome_approval import (
    OUTCOME_APPROVAL_STATUSES,
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    approved_outcome_ids_for_use,
    fingerprint_outcome_definition,
    legacy_unapproved_approval,
    normalise_datetime,
    outcome_is_approved_for_use,
    require_outcome_approval,
    resolve_approvals_by_outcome_id,
    validate_outcome_definition_for_approval,
)
from ancestry_mmm.core.outcomes import (
    FAMILY_HISTORY,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    OutcomeDefinition,
)
from ancestry_mmm.core.optimization import PlanningObjective


# ---------------------------------------------------------------------------
# REQ-STALE-001: Definition fingerprinting
# ---------------------------------------------------------------------------


class TestDefinitionFingerprint:
    """REQ-STALE-001: definition fingerprint is deterministic and includes
    all calculation-relevant fields."""

    @staticmethod
    def _base_outcome() -> OutcomeDefinition:
        return OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber completing sign-up",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Fully mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance weekly GSA report",
            business_owner="Analytics",
            definition_version="1.0",
        )

    def test_fingerprint_is_deterministic(self):
        """REQ-STALE-001: same fields → same fingerprint."""
        o1 = self._base_outcome()
        o2 = self._base_outcome()
        assert fingerprint_outcome_definition(o1) == fingerprint_outcome_definition(o2)

    def test_event_definition_change_changes_fingerprint(self):
        """REQ-STALE-001: changing event definition changes the fingerprint."""
        o1 = self._base_outcome()
        o2 = OutcomeDefinition(
            **{**o1.__dict__, "event_definition": "A different event definition"}
        )
        assert fingerprint_outcome_definition(o1) != fingerprint_outcome_definition(o2)

    def test_date_basis_change_changes_fingerprint(self):
        """REQ-STALE-001: changing date basis changes the fingerprint."""
        o1 = self._base_outcome()
        o2 = OutcomeDefinition(**{**o1.__dict__, "date_basis": "billing_date"})
        assert fingerprint_outcome_definition(o1) != fingerprint_outcome_definition(o2)

    def test_exclusions_change_changes_fingerprint(self):
        """REQ-STALE-001: changing exclusions changes the fingerprint."""
        o1 = self._base_outcome()
        o2 = OutcomeDefinition(
            **{**o1.__dict__, "exclusions": "Different exclusion list"}
        )
        assert fingerprint_outcome_definition(o1) != fingerprint_outcome_definition(o2)

    def test_definition_version_change_changes_fingerprint(self):
        """REQ-STALE-001: changing definition_version changes fingerprint."""
        o1 = self._base_outcome()
        o2 = OutcomeDefinition(**{**o1.__dict__, "definition_version": "2.0"})
        assert fingerprint_outcome_definition(o1) != fingerprint_outcome_definition(o2)

    def test_review_notes_do_not_change_definition_fingerprint(self):
        """REQ-STALE-001: role/inclusion/review fields do NOT affect the
        outcome-definition fingerprint used for approval matching."""
        o1 = self._base_outcome()
        o2 = OutcomeDefinition(**{**o1.__dict__, "role": "secondary"})
        # role is NOT a fingerprint field for outcome-definition fingerprinting
        # (it is for model-spec fingerprinting, but this test is about the
        #  outcome_approval fingerprint, which only covers business-definition
        #  fields)
        assert fingerprint_outcome_definition(o1) == fingerprint_outcome_definition(o2)


# ---------------------------------------------------------------------------
# REQ-OUT-002: Outcome approval matching
# ---------------------------------------------------------------------------


class TestOutcomeApprovalMatching:
    """REQ-OUT-002: approval is fingerprint-bound."""

    @staticmethod
    def _make_outcome(outcome_id: str = "fh_new_gsa") -> OutcomeDefinition:
        return OutcomeDefinition(
            outcome_id=outcome_id,
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Fully mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )

    def test_matching_approved_passes_for_allowed_use(self):
        """REQ-OUT-002: matching approval + allowed use = True."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning", "optimisation"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        assert outcome_is_approved_for_use(outcome, approval, "planning")

    def test_approval_for_reporting_does_not_permit_optimisation(self):
        """REQ-OUT-002: a reporting approval doesn't grant optimisation."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("headline_reporting",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        assert not outcome_is_approved_for_use(outcome, approval, "planning")
        assert not outcome_is_approved_for_use(outcome, approval, "optimisation")

    def test_stale_fingerprint_blocks_use(self):
        """REQ-OUT-002, REQ-STALE-001: changed definition blocks approval."""
        outcome_v1 = self._make_outcome()
        fp_v1 = fingerprint_outcome_definition(outcome_v1)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp_v1,
            status="approved",
            allowed_uses=("planning",),
        )
        # Change the definition
        outcome_v2 = OutcomeDefinition(
            **{**outcome_v1.__dict__, "event_definition": "Completely different event"}
        )
        assert not outcome_is_approved_for_use(outcome_v2, approval, "planning")

    def test_expired_approval_blocks_use(self):
        """REQ-OUT-002: expired approval blocks use."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning",),
            expires_at="2020-01-01",
        )
        assert not outcome_is_approved_for_use(
            outcome, approval, "planning", as_of="2026-07-26"
        )

    def test_rejected_approval_blocks_use(self):
        """REQ-OUT-002: rejected approval blocks use."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="rejected",
            allowed_uses=("planning",),
        )
        assert not outcome_is_approved_for_use(outcome, approval, "planning")

    def test_legacy_unapproved_blocks_use(self):
        """REQ-OUT-002: legacy_unapproved status blocks all official use."""
        approval = legacy_unapproved_approval("fh_new_gsa")
        assert not approval.is_active()
        assert approval.status == "legacy_unapproved"

    def test_wrong_market_scope_blocks_use(self):
        """REQ-OUT-002: approval scoped to UK doesn't cover Australia."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning",),
            market_scope=("UK",),
        )
        assert not outcome_is_approved_for_use(
            outcome, approval, "planning", market="Australia"
        )

    def test_role_eligibility_alone_never_grants_approval(self):
        """REQ-OUT-002: being primary/included doesn't mean approved."""
        outcome = self._make_outcome()
        # No approval object at all
        assert not outcome_is_approved_for_use(outcome, None, "planning")


# ---------------------------------------------------------------------------
# REQ-PLAN-001: PlanningObjective defaults
# ---------------------------------------------------------------------------


class TestPlanningObjectiveDefaults:
    """REQ-PLAN-001: no business metric may be the dataclass default."""

    def test_planning_objective_no_default_metric_key(self):
        """REQ-PLAN-001: constructing without metric_key leaves it empty."""
        obj = PlanningObjective()
        assert obj.metric_key == ""
        assert obj.target_outcome_ids == ()

    def test_empty_metric_key_not_valid_for_official(self):
        """REQ-PLAN-001: empty metric_key blocks official planning."""
        obj = PlanningObjective()
        assert not obj.is_valid_for_official_planning

    def test_explicit_target_is_valid_for_official(self):
        """REQ-PLAN-001: explicit metric_key + target_outcome_ids is valid."""
        obj = PlanningObjective(
            metric_key=METRIC_KEY_FH_GSA,
            target_outcome_ids=("fh_new_gsa",),
        )
        assert obj.is_valid_for_official_planning

    def test_from_dict_strips_old_nbt_default(self):
        """REQ-PLAN-001: loading old schema version doesn't backfill NBT."""
        old_dict = {
            "estimand": "incremental_outcome",
            "metric_key": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
            "schema_version": 2,
        }
        obj = PlanningObjective.from_dict(old_dict)
        # The explicit value from the old dict is accepted (it was set
        # explicitly by the user, not a silent default)
        assert obj.metric_key == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
        # But target_outcome_ids are still empty — approval is still needed
        assert not obj.is_valid_for_official_planning

    def test_rate_outcomes_invalid_target(self):
        """REQ-PLAN-001: rate outcomes are not valid optimisation targets."""
        # The metric registry already marks rate metrics with
        # allowed_in_optimiser=False — this test confirms the planning
        # layer doesn't override that.
        from ancestry_mmm.core.outcomes import METRIC_KEY_FH_NET_BILLTHROUGH_RATE

        obj = PlanningObjective(
            metric_key=METRIC_KEY_FH_NET_BILLTHROUGH_RATE,
            target_outcome_ids=("fh_nbt_rate",),
        )
        # The PlanningObjective itself is structurally valid (it has
        # target_outcome_ids) — the rate check happens at the metric
        # registry level in validate_outcome_definitions
        assert obj.is_valid_for_official_planning


# ---------------------------------------------------------------------------
# REQ-OUT-002: require_outcome_approval gate
# ---------------------------------------------------------------------------


class TestRequireOutcomeApproval:
    """REQ-OUT-002, REQ-USE-001: require_outcome_approval raises clearly."""

    @staticmethod
    def _make_outcome() -> OutcomeDefinition:
        return OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Fully mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )

    def test_no_approval_raises(self):
        """REQ-USE-001: no approval → OutcomeApprovalBlockedError."""
        outcome = self._make_outcome()
        with pytest.raises(OutcomeApprovalBlockedError, match="no approval record"):
            require_outcome_approval(outcome, None, "planning")

    def test_rejected_approval_raises(self):
        """REQ-USE-001: rejected approval → error."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="rejected",
            allowed_uses=("planning",),
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="rejected"):
            require_outcome_approval(outcome, approval, "planning")

    def test_stale_approval_raises(self):
        """REQ-USE-001: stale fingerprint → error."""
        outcome = self._make_outcome()
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint="wrong-fingerprint",
            status="approved",
            allowed_uses=("planning",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="stale"):
            require_outcome_approval(outcome, approval, "planning")

    def test_wrong_use_raises(self):
        """REQ-USE-001: approval doesn't include requested use → error."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("headline_reporting",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        with pytest.raises(OutcomeApprovalBlockedError, match="not for"):
            require_outcome_approval(outcome, approval, "planning")

    def test_valid_approval_succeeds(self):
        """REQ-USE-001: valid approval → no error."""
        outcome = self._make_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        # Should not raise
        require_outcome_approval(outcome, approval, "planning")


# ---------------------------------------------------------------------------
# REQ-NBT-001: Conditional NBT use
# ---------------------------------------------------------------------------


class TestConditionalNBTUse:
    """REQ-NBT-001: NBT requires both definition approval and completeness."""

    @staticmethod
    def _make_nbt_outcome() -> OutcomeDefinition:
        return OutcomeDefinition(
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

    def test_no_approval_blocks_nbt(self):
        """REQ-NBT-001: complete definition + no approval = blocked."""
        outcome = self._make_nbt_outcome()
        assert not outcome_is_approved_for_use(outcome, None, "planning")

    def test_approved_nbt_allowed_for_approved_use(self):
        """REQ-NBT-001: approved NBT definition + valid approval = allowed."""
        outcome = self._make_nbt_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-nbt",
            outcome_id="fh_new_nbt",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("model_fit", "planning"),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        assert outcome_is_approved_for_use(outcome, approval, "model_fit")
        assert outcome_is_approved_for_use(outcome, approval, "planning")

    def test_nbt_fit_approval_not_optimisation(self):
        """REQ-NBT-001: approval for model_fit doesn't imply optimisation."""
        outcome = self._make_nbt_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-nbt",
            outcome_id="fh_new_nbt",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("model_fit",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        assert outcome_is_approved_for_use(outcome, approval, "model_fit")
        assert not outcome_is_approved_for_use(outcome, approval, "optimisation")

    def test_nbt_definition_change_stales_approval(self):
        """REQ-NBT-001: changing NBT definition stales approval."""
        outcome = self._make_nbt_outcome()
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-nbt",
            outcome_id="fh_new_nbt",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning",),
        )
        # Change the reconciliation source
        changed = OutcomeDefinition(
            **{**outcome.__dict__, "reconciliation_source": "Different source"}
        )
        assert not outcome_is_approved_for_use(changed, approval, "planning")

    def test_legacy_nbt_imports_unapproved(self):
        """REQ-NBT-001: legacy NBT import → legacy_unapproved."""
        approval = legacy_unapproved_approval("fh_new_nbt")
        assert approval.status == "legacy_unapproved"
        assert not approval.is_active()
        assert approval.allowed_uses == ()


# ---------------------------------------------------------------------------
# Definition validation
# ---------------------------------------------------------------------------


class TestDefinitionValidation:
    """validate_outcome_definition_for_approval checks required fields."""

    def test_complete_definition_passes_validation(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="A new subscriber",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )
        issues = validate_outcome_definition_for_approval(outcome)
        assert len(issues) == 0

    def test_missing_event_definition_fails_validation(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            reconciliation_source="Finance report",
            business_owner="Analytics",
        )
        issues = validate_outcome_definition_for_approval(outcome)
        assert any("event_definition" in i for i in issues)

    def test_missing_business_owner_fails_validation(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="An event",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            reconciliation_source="Finance report",
            business_owner="",
        )
        issues = validate_outcome_definition_for_approval(outcome)
        assert any("business_owner" in i for i in issues)


# ---------------------------------------------------------------------------
# Bulk resolution
# ---------------------------------------------------------------------------


class TestBulkResolution:
    def test_resolve_approvals_by_outcome_id_last_wins(self):
        a1 = OutcomeApproval(
            approval_id="a1",
            outcome_id="o1",
            definition_fingerprint="fp1",
            status="approved",
            allowed_uses=("planning",),
            approved_at="2020-01-01",
        )
        a2 = OutcomeApproval(
            approval_id="a2",
            outcome_id="o1",
            definition_fingerprint="fp2",
            status="approved",
            allowed_uses=("planning",),
            approved_at="2021-01-01",
        )
        by_id = resolve_approvals_by_outcome_id([a1, a2])
        assert by_id["o1"].approval_id == "a2"

    def test_approved_outcome_ids_for_use_filters_unapproved(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="An event",
            date_basis="event_date",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            exclusions="Excludes internal/test accounts",
            reconciliation_source="Finance report",
            business_owner="Analytics",
            definition_version="1.0",
        )
        fp = fingerprint_outcome_definition(outcome)
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint=fp,
            status="approved",
            allowed_uses=("planning",),
            approved_by="Jane Analyst",
            approved_at="2026-01-01",
        )
        ids = approved_outcome_ids_for_use(
            [outcome],
            [approval],
            "planning",
        )
        assert "fh_new_gsa" in ids

    def test_no_approval_excluded(self):
        outcome = OutcomeDefinition(
            outcome_id="fh_new_gsa",
            product=FAMILY_HISTORY,
            segment="New",
            metric="GSA",
            metric_key=METRIC_KEY_FH_GSA,
            source_column="GSA_New",
            unit="GSA",
            aggregation_type="count",
            event_definition="An event",
            cohort_or_attribution_basis="signup_cohort",
            completeness_or_maturity_policy="Mature after 12 weeks",
            reconciliation_source="Finance report",
            business_owner="Analytics",
        )
        ids = approved_outcome_ids_for_use(
            [outcome],
            [],
            "planning",
        )
        assert "fh_new_gsa" not in ids


# ---------------------------------------------------------------------------
# REQ-AUTH-001: Authority consistency
# ---------------------------------------------------------------------------


class TestAuthorityConsistency:
    """REQ-AUTH-001: repository authority wording is consistent."""

    def test_approved_requirements_readme_exists(self):
        """REQ-AUTH-001: approved_requirements/README.md is present."""
        readme_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "README.md"
        )
        assert readme_path.exists()

    def test_index_json_exists(self):
        """REQ-AUTH-001: approved_requirements/index.json is present."""
        index_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "index.json"
        )
        assert index_path.exists()

    def test_index_json_is_valid(self):
        """REQ-AUTH-001: index.json is valid JSON with required fields."""
        index_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "index.json"
        )
        data = json.loads(index_path.read_text())
        assert "schema_version" in data
        assert "requirements" in data
        assert isinstance(data["requirements"], list)
        assert len(data["requirements"]) >= 7  # 7 REQ-* records minimum

    def test_index_metadata_and_datain_status_match_current_main(self):
        """WP1: machine-readable requirement metadata must describe the
        current post-WP8 repository state rather than the pre-template-pack
        baseline."""
        index_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "index.json"
        )
        data = json.loads(index_path.read_text())
        assert data["generated_at"] == "2026-08-17"

        datain = next(
            req
            for req in data["requirements"]
            if req["requirement_id"] == "REQ-DATAIN-001"
        )
        assert datain["status"] == "approved_for_implementation"

        record = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "REQ-DATAIN-001.md"
        ).read_text()
        assert "PRs #229" in record and "#237" in record
        assert (
            "remaining outcome\nworkbook/template-pack and end-to-end source-contract work is not\nimplemented"
            not in record
        )

    def test_indexed_records_exist(self):
        """REQ-AUTH-001: every indexed record path exists."""
        index_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "index.json"
        )
        data = json.loads(index_path.read_text())
        docs_root = Path(__file__).parent.parent.parent
        for req in data["requirements"]:
            record_path = docs_root / req["record_path"]
            assert record_path.exists(), f"Missing: {record_path}"

    def test_root_agents_md_mentions_approved_requirements_not_forbids(self):
        """REQ-AUTH-001: root AGENTS.md doesn't forbid AGENTS.md invariants
        while also ranking them as authoritative."""
        agents_path = Path(__file__).parent.parent.parent / "AGENTS.md"
        content = agents_path.read_text()
        # AGENTS.md invariants are listed as authority source #3
        assert "applicable stable `AGENTS.md` invariant" in content
        assert "applicable `AGENTS.md`" in content

    @staticmethod
    def _markdown_table_rows(section_text: str) -> list[list[str]]:
        """Parse `| a | b | c |` rows from a Markdown section, skipping the
        header and `---` separator rows."""
        rows = []
        for line in section_text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("|") and stripped.endswith("|")):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if all(set(c) <= {"-", ":"} for c in cells):
                continue  # separator row
            rows.append(cells)
        return rows[1:]  # drop the header row

    def test_specification_authority_current_suite_table_states_v1_5(self):
        """REQ-AUTH-001: the "Current PRD suite" table's Version row (not
        merely some text elsewhere in the document) names v1.5 - guards
        against the current-version table regressing to v1.4 while
        surrounding prose still mentions v1.5."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        suite_section = content.split("## Current PRD suite", 1)[1].split("##", 1)[0]
        rows = {
            cells[0]: cells[1] for cells in self._markdown_table_rows(suite_section)
        }
        assert "Cross-Document Coherent v1.5" in rows["Version"]

    def test_specification_authority_classifies_graph_and_search_correctly(self):
        """REQ-AUTH-001: `REQ-GRAPH-001`'s and `REQ-SEARCH-001`'s own
        capability rows in the implementation-gaps table must be classified
        "requirement exists but capability incomplete", never "no approved
        requirement/decision yet" - and both records must be named in the
        "already implemented" section. This asserts each row's actual State
        column, not merely that the requirement ID string appears somewhere
        in the document (which a table regression could still satisfy)."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()

        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = self._markdown_table_rows(gaps_section)
        assert gap_rows, "no rows parsed from the implementation-gaps table"

        no_requirement_state = "No approved requirement/decision yet"
        incomplete_state = "Requirement exists but capability incomplete"

        # REQ-GRAPH-001's and REQ-SEARCH-001's OWN capability (identified by
        # the requirement ID appearing in that row's Capability column, not
        # merely referenced in another row's Notes) must never be
        # classified as if no requirement record exists.
        for requirement_id in ("REQ-GRAPH-001", "REQ-SEARCH-001"):
            own_rows = [row for row in gap_rows if requirement_id in row[0]]
            for row in own_rows:
                assert row[1] == incomplete_state, (
                    f"{requirement_id}'s own capability row is classified "
                    f"{row[1]!r}, expected {incomplete_state!r}: {row}"
                )

        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        for requirement_id in ("REQ-GRAPH-001", "REQ-SEARCH-001"):
            assert requirement_id in implemented_section
            assert "implemented" in implemented_section.lower()
            # Must not simultaneously read as an unclassified gap in that
            # same section.
            assert no_requirement_state not in implemented_section

        # REQ-COVERAGE-001's own capability row must likewise read as
        # "requirement exists but capability incomplete", not "no approved
        # requirement/decision yet" - it is an approved authority record
        # with no implementation yet, the same status as REQ-VAL-001's
        # remaining scope.
        coverage_rows = [row for row in gap_rows if "REQ-COVERAGE-001" in row[0]]
        assert coverage_rows, "no implementation-gaps row references REQ-COVERAGE-001"
        for row in coverage_rows:
            assert row[1] == incomplete_state, (
                f"REQ-COVERAGE-001's own capability row is classified "
                f"{row[1]!r}, expected {incomplete_state!r}: {row}"
            )

        # FR-MOD-015 (ragged/market-specific predictor sets) must remain an
        # explicit, unresolved gap - never silently folded into
        # REQ-COVERAGE-001's "incomplete but approved" status, since no
        # model-engine mathematics is approved by that record (see its §6).
        mod015_rows = [row for row in gap_rows if "FR-MOD-015" in row[0]]
        assert mod015_rows, "no implementation-gaps row references FR-MOD-015"
        for row in mod015_rows:
            assert row[1] == no_requirement_state, (
                f"FR-MOD-015's row is classified {row[1]!r}, expected "
                f"{no_requirement_state!r} (no model-engine mathematics is "
                f"approved for ragged predictor sets): {row}"
            )

    def test_part3_v16_overlay_table_scopes_only_part_three(self):
        """REQ-COVERAGE-001: the Part 3 v1.6 overlay version table names
        Part 3 as v1.6 and every other part as retained (not v1.6) - a
        structured, per-row check rather than a substring search, so a
        regression that bumped an unrelated part's row to v1.6 (or failed to
        record Part 3's overlay at all) is caught even if the surrounding
        prose still reads correctly."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        overlay_section = content.split(
            "## Version history: focused Part 3 v1.6 overlay", 1
        )[1].split("## Operating model", 1)[0]
        rows = self._markdown_table_rows(overlay_section)
        assert rows, "no rows parsed from the Part 3 v1.6 overlay table"

        by_part = {cells[0]: cells[1] for cells in rows}
        assert set(by_part) == {f"Part {n}" for n in range(1, 12)}, sorted(by_part)

        assert "v1.6" in by_part["Part 3"], by_part["Part 3"]
        for part, version in by_part.items():
            if part == "Part 3":
                continue
            assert "v1.6" not in version, (
                f"{part}'s row claims v1.6 ({version!r}); only Part 3 is "
                "overlaid by this brief"
            )

    def test_req_coverage_001_gap_row_reflects_delivered_capability(self):
        """REQ-COVERAGE-001's own gap-table row must name the PR range that
        delivered its implemented capability and must not still claim no
        domain objects/join diagnostics exist (Work Package A reconciliation,
        2026-08-11) - a structured check on the row's own Notes column, not a
        substring search of the whole document."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = self._markdown_table_rows(gaps_section)
        coverage_rows = [row for row in gap_rows if "REQ-COVERAGE-001" in row[0]]
        assert coverage_rows, "no implementation-gaps row references REQ-COVERAGE-001"
        for row in coverage_rows:
            notes = row[2]
            assert "#151" in notes and "#161" in notes, (
                f"REQ-COVERAGE-001's gap-table Notes must cite the delivering "
                f"PR range: {notes}"
            )
            assert "No source/coverage-matrix domain objects" not in notes, (
                "REQ-COVERAGE-001's gap-table Notes still claims no domain "
                "objects are implemented, contradicting core.coverage"
            )

    def test_req_coverage_001_named_in_implemented_section(self):
        """REQ-COVERAGE-001 must appear in the 'already implemented' section
        alongside REQ-GRAPH-001/REQ-SEARCH-001 - the established pattern for
        an approved record with substantive but bounded implementation."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        implemented_section = content.split(
            "## Approved requirement records already implemented", 1
        )[1]
        assert "REQ-COVERAGE-001" in implemented_section
        assert "core.coverage" in implemented_section

    def test_req_coverage_001_record_states_dated_implementation_history(self):
        """REQ-COVERAGE-001.md's own Capability status section must record
        both its approval-time status and a dated update reflecting what was
        actually delivered - never silently rewritten as though the
        capability existed at approval time."""
        record_path = (
            Path(__file__).parent.parent.parent
            / "docs"
            / "approved_requirements"
            / "REQ-COVERAGE-001.md"
        )
        content = record_path.read_text()
        status_section = content.split("## Capability status", 1)[1].split(
            "### What already exists today", 1
        )[0]
        assert "2026-08-09" in status_section
        assert "2026-08-11" in status_section
        assert "#151" in status_section and "#159" in status_section

    def test_validation_overlay_table_scopes_only_the_five_named_parts(self):
        """Work Package 0: the focused Bayesian-validation/causal-
        identification/calibration/forecast-risk overlay table names exactly
        Parts 3, 6, 7, 9 and 10 with their new versions (v1.7/v1.6/v1.5/
        v1.5/v1.6 respectively) and every other part as retained - a
        structured, per-row check rather than a substring search, so a
        regression that bumped an unrelated part's row (or missed one of the
        five) is caught even if the surrounding prose still reads
        correctly."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        overlay_section = content.split(
            "## Version history: focused Bayesian validation, causal "
            "identification, calibration and forecast-risk overlay",
            1,
        )[1].split("## Version history: focused Part 3 v1.6 overlay", 1)[0]
        rows = self._markdown_table_rows(overlay_section)
        assert rows, "no rows parsed from the validation-overlay table"

        by_part = {cells[0]: cells[1] for cells in rows}
        assert set(by_part) == {f"Part {n}" for n in range(1, 12)}, sorted(by_part)

        expected_overlay_version = {
            "Part 3": "v1.7",
            "Part 6": "v1.6",
            "Part 7": "v1.5",
            "Part 9": "v1.5",
            "Part 10": "v1.6",
        }
        for part, expected_version in expected_overlay_version.items():
            assert expected_version in by_part[part], (
                f"{part}'s row is {by_part[part]!r}, expected to contain "
                f"{expected_version!r}"
            )
        for part, version in by_part.items():
            if part in expected_overlay_version:
                continue
            assert "focused overlay" not in version, (
                f"{part}'s row claims a focused overlay ({version!r}); only "
                "Parts 3, 6, 7, 9 and 10 are overlaid by this brief"
            )

    def test_validation_overlay_requirement_records_classified_incomplete(self):
        """The eight REQ-* records this overlay produced (REQ-LEAK-001,
        REQ-STAB-001, REQ-PPD-001, REQ-IDENT-001, REQ-LATENT-001,
        REQ-EXPMODE-001, REQ-CALIB-001, REQ-FORECAST-001) must each appear in
        the implementation-gaps table classified "Requirement exists but
        capability incomplete" - never "no approved requirement/decision
        yet", since each is an approved, indexed record even though none has
        any implementation yet."""
        authority_path = (
            Path(__file__).parent.parent.parent / "docs" / "specification_authority.md"
        )
        content = authority_path.read_text()
        gaps_section = content.split(
            "## Current implementation gaps requiring decision records", 1
        )[1].split("## Approved requirement records already implemented", 1)[0]
        gap_rows = self._markdown_table_rows(gaps_section)
        assert gap_rows, "no rows parsed from the implementation-gaps table"

        incomplete_state = "Requirement exists but capability incomplete"
        for requirement_id in (
            "REQ-LEAK-001",
            "REQ-STAB-001",
            "REQ-PPD-001",
            "REQ-IDENT-001",
            "REQ-LATENT-001",
            "REQ-EXPMODE-001",
            "REQ-CALIB-001",
            "REQ-FORECAST-001",
        ):
            own_rows = [row for row in gap_rows if requirement_id in row[0]]
            assert own_rows, f"no implementation-gaps row references {requirement_id}"
            for row in own_rows:
                assert row[1] == incomplete_state, (
                    f"{requirement_id}'s own capability row is classified "
                    f"{row[1]!r}, expected {incomplete_state!r}: {row}"
                )


# ---------------------------------------------------------------------------
# OutcomeApproval vocabulary
# ---------------------------------------------------------------------------


class TestOutcomeApprovalVocabulary:
    def test_valid_statuses_accepted(self):
        for status in OUTCOME_APPROVAL_STATUSES:
            approval = OutcomeApproval(
                approval_id="test",
                outcome_id="test",
                definition_fingerprint="fp",
                status=status,
            )
            assert approval.status == status

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Unknown outcome approval status"):
            OutcomeApproval(
                approval_id="test",
                outcome_id="test",
                definition_fingerprint="fp",
                status="not_a_real_status",
            )

    def test_invalid_use_raises(self):
        with pytest.raises(ValueError, match="Unknown outcome use"):
            OutcomeApproval(
                approval_id="test",
                outcome_id="test",
                definition_fingerprint="fp",
                allowed_uses=("not_a_real_use",),
            )

    def test_round_trip_through_dict(self):
        approval = OutcomeApproval(
            approval_id="apr-1",
            outcome_id="fh_new_gsa",
            definition_fingerprint="abc123",
            status="approved",
            allowed_uses=("planning", "optimisation"),
            market_scope=("UK", "Australia"),
            approved_by="Jane Analyst",
            approved_at="2026-07-26",
            conditions=("Must review quarterly",),
            notes="Initial approval",
        )
        restored = OutcomeApproval.from_dict(approval.to_dict())
        assert restored.approval_id == approval.approval_id
        assert restored.outcome_id == approval.outcome_id
        assert restored.definition_fingerprint == approval.definition_fingerprint
        assert restored.status == approval.status
        assert set(restored.allowed_uses) == set(approval.allowed_uses)
        assert restored.market_scope == approval.market_scope


# ---------------------------------------------------------------------------
# PlanningObjective migration (legacy)
# ---------------------------------------------------------------------------


class TestPlanningObjectiveLegacy:
    """REQ-PLAN-001: legacy objectives map correctly but remain subject to approval."""

    def test_legacy_fh_net_billthrough_maps_but_no_target(self):
        """Legacy NBT objective maps metric_key but has empty target_outcome_ids."""
        from ancestry_mmm.core.optimization import planning_objective_from_legacy

        obj = planning_objective_from_legacy("fh_net_billthrough")
        assert obj.metric_key == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
        assert obj.target_outcome_ids == ()
        assert not obj.is_valid_for_official_planning

    def test_legacy_fh_gsa_maps_correctly(self):
        from ancestry_mmm.core.optimization import planning_objective_from_legacy

        obj = planning_objective_from_legacy("fh_gsa")
        assert obj.metric_key == METRIC_KEY_FH_GSA

    def test_unknown_legacy_raises(self):
        from ancestry_mmm.core.optimization import planning_objective_from_legacy

        with pytest.raises(ValueError, match="unknown legacy objective"):
            planning_objective_from_legacy("unknown_objective")


class TestNormaliseDatetimePublicWrapper:
    """normalise_datetime is the public wrapper for _normalise_datetime,
    reused by CurveService.authorize_use's staleness-cutoff comparison
    (Corrective PR B7) so a naive/aware timestamp mismatch never raises an
    uncaught TypeError."""

    def test_naive_and_aware_timestamps_compare_without_raising(self):
        naive = normalise_datetime("2026-07-01T00:00:00")
        aware = normalise_datetime("2026-07-01T00:00:00+00:00")
        assert naive == aware  # must not raise TypeError

    def test_returns_timezone_aware_utc(self):
        result = normalise_datetime("2026-07-01")
        assert result.tzinfo is not None
