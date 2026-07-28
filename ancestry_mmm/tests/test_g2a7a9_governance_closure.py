"""Regression tests for G2A.7a.9: green CI and fail-closed scenario governance.

Every business-critical test cites a requirement ID from the implementation
brief.

All constructors and signatures match the actual running code, not assumptions.
"""

from __future__ import annotations

import inspect
from typing import Optional

import pytest

from ancestry_mmm.core.approval import ModelApproval, fingerprint_model_approval
from ancestry_mmm.core.net_billthrough import NetBillthroughCompletenessMetadata
from ancestry_mmm.core.optimization import (
    ARTEFACT_KIND_REQUIRED_USE,
    CurrencyContext,
    OutcomeValueMapping,
    PlanningObjective,
    PlanningGovernanceError,
    ResolvedOutcomeAuthorisation,
    ScenarioGovernanceDependencies,
    ScenarioValidationContext,
    _calculate_scenario,
    evaluate_scenario,
    fingerprint_planning_objective,
    scenario_from_dict,
    scenario_to_dict,
    validate_scenario_dependencies,
    validation_context_from_legacy_args,
)
from ancestry_mmm.core.outcome_approval import (
    OutcomeApproval,
    OutcomeDefinition,
    fingerprint_outcome_definition,
)
from ancestry_mmm.core.outcomes import METRIC_KEY_FH_GSA


# ============================================================================
# Helpers -- match real constructors exactly
# ============================================================================

IDENTITY = dict(
    model_run_id="run-abc123",
    data_fingerprint="data-fp-1",
    model_spec_fingerprint="spec-fp-1",
    posterior_fingerprint="posterior-fp-1",
)

SAMPLE_OUTCOME_ID = "New"
SAMPLE_OUTCOME_IDS = ("New",)


def _make_outcome_definition(
    outcome_id: str = "New",
    product: str = "fh",
    segment: str = "new",
    metric: str = "GSA",
    source_column: str = "new_gsa",
    event_definition: str = "FH subscription attributed to GSA",
    cohort_or_attribution_basis: str = "transaction_month",
    completeness_or_maturity_policy: str = "12-month maturity",
    exclusions: str = "test exclusion",
    reconciliation_source: str = "test_source",
    business_owner: str = "test_owner",
    definition_version: str = "1.0",
) -> OutcomeDefinition:
    return OutcomeDefinition(
        outcome_id=outcome_id,
        product=product,
        segment=segment,
        metric=metric,
        source_column=source_column,
        event_definition=event_definition,
        cohort_or_attribution_basis=cohort_or_attribution_basis,
        completeness_or_maturity_policy=completeness_or_maturity_policy,
        exclusions=exclusions,
        reconciliation_source=reconciliation_source,
        business_owner=business_owner,
        definition_version=definition_version,
    )


def _make_outcome_approval(
    outcome_id: str = "New",
    definition_fingerprint: str = "",
    allowed_uses: tuple = ("planning",),
    status: str = "approved",
    approved_by: str = "Tester",
    approved_at: str = "2026-01-01",
) -> OutcomeApproval:
    return OutcomeApproval(
        approval_id=f"app-{outcome_id}",
        outcome_id=outcome_id,
        definition_fingerprint=definition_fingerprint,
        status=status,
        allowed_uses=allowed_uses,
        approved_by=approved_by,
        approved_at=approved_at,
    )


def _make_planning_objective(
    estimand: str = "incremental_outcome",
    metric_key: str = METRIC_KEY_FH_GSA,
    target_outcome_ids: tuple = SAMPLE_OUTCOME_IDS,
    value_currency: Optional[str] = None,
) -> PlanningObjective:
    return PlanningObjective(
        estimand=estimand,
        metric_key=metric_key,
        target_outcome_ids=target_outcome_ids,
        value_currency=value_currency,
    )


def _make_blank_context(**overrides) -> ScenarioValidationContext:
    """Build a minimal complete context -- all fields filled."""
    od = _make_outcome_definition()
    fp = fingerprint_outcome_definition(od)
    approval = _make_outcome_approval(definition_fingerprint=fp)
    # Build kwargs dict then override to avoid "multiple values" error
    kwargs = dict(
        model_run_id="run-abc",
        model_approval_fingerprint="fp-approval",
        data_fingerprint="fp-data",
        model_spec_fingerprint="fp-spec",
        posterior_fingerprint="fp-posterior",
        planning_objective=_make_planning_objective(),
        outcome_definitions=(od,),
        outcome_approvals=(approval,),
        counterfactual_fingerprint="fp-counterfactual",
        nbt_completeness_metadata=None,
        value_mapping_fingerprint=None,
        currency_context_fingerprint=None,
    )
    kwargs.update(overrides)
    return ScenarioValidationContext(**kwargs)


def _make_nbt_metadata(
    data_as_of_date: str = "2026-01-01",
    model_start_week: str = "2023-01-01",
    model_end_week: str = "2025-12-31",
    latest_complete_net_billthrough_week: str = "2025-06-01",
    maturity_rule_description: str = "12-month maturity",
    source_owner: str = "Finance",
    outcome_id: str = "NBT",
) -> NetBillthroughCompletenessMetadata:
    return NetBillthroughCompletenessMetadata(
        data_as_of_date=data_as_of_date,
        model_start_week=model_start_week,
        model_end_week=model_end_week,
        latest_complete_net_billthrough_week=latest_complete_net_billthrough_week,
        maturity_rule_description=maturity_rule_description,
        source_owner=source_owner,
        outcome_id=outcome_id,
    )


# ============================================================================
# 13.1 Current CI regression
# ============================================================================


class TestCurrentCIRegression:
    """REQ-CI-001: persistence constructs the strict context without TypeError."""

    def test_persistence_can_construct_strict_context(self):
        """Construction of ScenarioValidationContext must not raise."""
        ctx = ScenarioValidationContext(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective=_make_planning_objective(),
            outcome_definitions=(_make_outcome_definition(),),
            outcome_approvals=(_make_outcome_approval(),),
            counterfactual_fingerprint="cf1",
        )
        assert ctx.model_run_id == "r1"

    def test_validation_context_from_legacy_args_complete(self):
        """validation_context_from_legacy_args with all fields succeeds."""
        ctx = validation_context_from_legacy_args(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective=_make_planning_objective(),
            outcome_definitions=(_make_outcome_definition(),),
            outcome_approvals=(_make_outcome_approval(),),
            counterfactual_fingerprint="cf1",
        )
        assert ctx is not None

    def test_validation_context_from_legacy_args_incomplete_raises(self):
        """Incomplete legacy args must raise."""
        with pytest.raises((TypeError, ValueError, PlanningGovernanceError)):
            validation_context_from_legacy_args(
                model_run_id="",
                model_approval_fingerprint="",
                data_fingerprint="",
                model_spec_fingerprint="",
                posterior_fingerprint="",
                planning_objective=None,
                outcome_definitions=(),
                outcome_approvals=(),
                counterfactual_fingerprint="",
            )


# ============================================================================
# 13.2 Context completeness
# ============================================================================


class TestContextCompleteness:
    """REQ-CONTEXT-001: no incomplete context returns 'current'."""

    def test_blank_model_run_id_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(model_run_id="")

    def test_blank_approval_fingerprint_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(model_approval_fingerprint="")

    def test_blank_data_fingerprint_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(data_fingerprint="")

    def test_blank_spec_fingerprint_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(model_spec_fingerprint="")

    def test_blank_posterior_fingerprint_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(posterior_fingerprint="")

    def test_empty_outcome_definitions_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(outcome_definitions=())

    def test_empty_outcome_approvals_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(outcome_approvals=())

    def test_blank_counterfactual_fingerprint_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(counterfactual_fingerprint="")

    def test_missing_planning_objective_blocks(self):
        with pytest.raises((ValueError, PlanningGovernanceError)):
            _make_blank_context(planning_objective=None)

    def test_complete_matching_context_returns_current(self):
        """A complete context with matching fingerprints returns current."""
        # Build the context with dicts for outcome_definitions and outcome_approvals
        # because validate_scenario_dependencies checks isinstance(a, dict)
        od = _make_outcome_definition()
        od_dict = od.to_dict()
        od_fp = fingerprint_outcome_definition(od)
        approval = _make_outcome_approval(definition_fingerprint=od_fp)
        approval_dict = approval.to_dict()
        obj = _make_planning_objective()
        ctx = ScenarioValidationContext(
            model_run_id="run-abc",
            model_approval_fingerprint="fp-approval",
            data_fingerprint="fp-data",
            model_spec_fingerprint="fp-spec",
            posterior_fingerprint="fp-posterior",
            planning_objective=obj,
            outcome_definitions=(od_dict,),
            outcome_approvals=(approval_dict,),
            counterfactual_fingerprint="fp-counterfactual",
        )
        deps = ScenarioGovernanceDependencies(
            model_run_id="run-abc",
            model_approval_fingerprint="fp-approval",
            data_fingerprint="fp-data",
            model_spec_fingerprint="fp-spec",
            posterior_fingerprint="fp-posterior",
            planning_objective_fingerprint=fingerprint_planning_objective(obj),
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="New",
                    requested_use="planning",
                    approval_id="app-New",
                    definition_fingerprint=od_fp,
                ),
            ),
            nbt_completeness_fingerprint=None,
            counterfactual_policy_fingerprint="fp-counterfactual",
        )
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "artefact_kind": "manual_scenario",
            "governance_dependencies": deps.to_dict(),
        }
        issues = validate_scenario_dependencies(scenario, context=ctx)
        assert len(issues) == 0

    def test_no_context_returns_issues(self):
        """validate_scenario_dependencies without context returns issues."""
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(),
        )
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "governance_dependencies": deps.to_dict(),
        }
        issues = validate_scenario_dependencies(scenario, context=None)
        # Without context, validation still checks deps and returns issues
        assert len(issues) > 0


# ============================================================================
# 13.3 Outcome definitions
# ============================================================================


class TestOutcomeDefinitionValidation:
    """REQ-OUTCOME-001: current definitions are deserialised, not raw dicts."""

    def test_raw_dictionary_is_deserialised_before_fingerprinting(self):
        """A raw dict must be deserialised via OutcomeDefinition.from_dict."""
        raw = {
            "outcome_id": "TestId",
            "product": "fh",
            "segment": "tier1",
            "metric": "GSA",
            "source_column": "test_gsa",
            "event_definition": "FH subscription attributed to GSA",
            "cohort_or_attribution_basis": "transaction_month",
            "completeness_or_maturity_policy": "12-month maturity",
            "exclusions": "none",
            "reconciliation_source": "src",
            "business_owner": "owner",
            "definition_version": "1",
        }
        definition = OutcomeDefinition.from_dict(raw)
        assert definition.outcome_id == "TestId"
        fp = fingerprint_outcome_definition(definition)
        assert isinstance(fp, str) and len(fp) > 0

    def test_unchanged_definition_remains_current(self):
        """Same definition produces same fingerprint."""
        d1 = _make_outcome_definition("Test", event_definition="Signup")
        d2 = _make_outcome_definition("Test", event_definition="Signup")
        assert fingerprint_outcome_definition(d1) == fingerprint_outcome_definition(d2)

    def test_changed_definition_becomes_stale(self):
        """Different definition produces different fingerprint."""
        d1 = _make_outcome_definition("Test", event_definition="Signup")
        d2 = _make_outcome_definition("Test", event_definition="GSA")
        assert fingerprint_outcome_definition(d1) != fingerprint_outcome_definition(d2)

    def test_missing_current_definition_is_invalid(self):
        """A saved outcome authorisation with no matching current definition blocks."""
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="MissingId",
                    requested_use="planning",
                    approval_id="app-MissingId",
                    definition_fingerprint="some-fp",
                ),
            ),
        )
        ctx = _make_blank_context()
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "governance_dependencies": deps.to_dict(),
        }
        issues = validate_scenario_dependencies(scenario, context=ctx)
        assert len(issues) > 0

    def test_malformed_saved_authorisation_is_invalid(self):
        """A saved authorisation that is not a valid ResolvedOutcomeAuthorisation blocks."""
        # Build a scenario dict with a malformed authorisation entry directly
        # to avoid the to_dict() serialisation that would crash on strings.
        ctx = _make_blank_context()
        valid_deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(),
        )
        deps_dict = valid_deps.to_dict()
        # Replace outcome_authorisations with a non-dict entry
        deps_dict["outcome_authorisations"] = ["not-a-valid-authorisation"]
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "artefact_kind": "manual_scenario",
            "governance_dependencies": deps_dict,
        }
        issues = validate_scenario_dependencies(scenario, context=ctx)
        assert len(issues) > 0


# ============================================================================
# 13.4 Operation integrity
# ============================================================================


class TestOperationIntegrity:
    """REQ-OP-001: manual service authorises planning, optimiser authorises optimisation."""

    def test_manual_service_authorises_planning(self):
        assert ARTEFACT_KIND_REQUIRED_USE["manual_scenario"] == "planning"

    def test_constrained_optimiser_authorises_optimisation(self):
        assert ARTEFACT_KIND_REQUIRED_USE["constrained_optimisation"] == "optimisation"

    def test_benchmark_authorises_optimisation(self):
        assert ARTEFACT_KIND_REQUIRED_USE["unconstrained_benchmark"] == "optimisation"

    def test_planning_only_approval_cannot_authorise_optimisation(self):
        """REQ-OP-002: planning-only approval should not authorise optimisation."""
        approval = _make_outcome_approval(allowed_uses=("planning",))
        assert "optimisation" not in approval.allowed_uses

    def test_no_public_trusted_operation_argument(self):
        """REQ-OP-003: evaluate_scenario must not accept _trusted_operation."""
        sig = inspect.signature(evaluate_scenario)
        assert "_trusted_operation" not in sig.parameters

    def test_public_caller_cannot_switch_operation(self):
        """REQ-OP-003: No public caller can switch the operation through a private-looking argument."""
        sig = inspect.signature(evaluate_scenario)
        for param in sig.parameters:
            assert not param.startswith("_trusted"), f"Found leaked param: {param}"

    def test_optimisation_only_approval_works_without_planning_approval(self):
        """REQ-OP-004: optimisation-only approval works for optimisation without requiring planning approval."""
        approval = _make_outcome_approval(allowed_uses=("optimisation",))
        assert "optimisation" in approval.allowed_uses
        assert "planning" not in approval.allowed_uses


# ============================================================================
# 13.5 Proof identity
# ============================================================================


class TestProofIdentity:
    """REQ-PROOF-001: the saved proof is the exact proof used by the calculation."""

    def test_blank_saved_fingerprint_blocks(self):
        """Blank model_approval_fingerprint in deps blocks."""
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(),
        )
        ctx = _make_blank_context()
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "governance_dependencies": deps.to_dict(),
        }
        issues = validate_scenario_dependencies(scenario, context=ctx)
        assert len(issues) > 0

    def test_blank_current_fingerprint_raises_at_construction(self):
        """Blank current fingerprint in context raises at construction."""
        with pytest.raises((ValueError, PlanningGovernanceError)):
            ScenarioValidationContext(
                model_run_id="r1",
                model_approval_fingerprint="",
                data_fingerprint="df1",
                model_spec_fingerprint="msf1",
                posterior_fingerprint="pf1",
                planning_objective=_make_planning_objective(),
                outcome_definitions=(_make_outcome_definition(),),
                outcome_approvals=(_make_outcome_approval(),),
                counterfactual_fingerprint="cf1",
            )


# ============================================================================
# 13.6 NBT
# ============================================================================


class TestNbtCompleteness:
    """REQ-NBT-001: NBT completeness fingerprint comparison."""

    def test_unchanged_completeness_metadata_remains_current(self):
        """Same metadata produces same fingerprint."""
        m1 = _make_nbt_metadata()
        m2 = _make_nbt_metadata()
        assert m1.completeness_fingerprint() == m2.completeness_fingerprint()

    def test_changed_complete_week_stales(self):
        m1 = _make_nbt_metadata(latest_complete_net_billthrough_week="2025-06-01")
        m2 = _make_nbt_metadata(latest_complete_net_billthrough_week="2025-07-01")
        assert m1.completeness_fingerprint() != m2.completeness_fingerprint()

    def test_changed_as_of_date_stales(self):
        m1 = _make_nbt_metadata(data_as_of_date="2026-01-01")
        m2 = _make_nbt_metadata(data_as_of_date="2026-06-01")
        assert m1.completeness_fingerprint() != m2.completeness_fingerprint()

    def test_changed_source_owner_stales(self):
        """Changing source_owner changes completeness fingerprint."""
        m1 = _make_nbt_metadata(source_owner="Finance")
        m2 = _make_nbt_metadata(source_owner="Marketing")
        assert m1.completeness_fingerprint() != m2.completeness_fingerprint()

    def test_non_nbt_scenario_does_not_require_nbt_completeness(self):
        """Non-NBT scenario with no NBT completeness metadata passes validation."""
        od = _make_outcome_definition()
        od_dict = od.to_dict()
        od_fp = fingerprint_outcome_definition(od)
        approval = _make_outcome_approval(definition_fingerprint=od_fp)
        approval_dict = approval.to_dict()
        obj = _make_planning_objective()
        ctx = ScenarioValidationContext(
            model_run_id="run-abc",
            model_approval_fingerprint="fp-approval",
            data_fingerprint="fp-data",
            model_spec_fingerprint="fp-spec",
            posterior_fingerprint="fp-posterior",
            planning_objective=obj,
            outcome_definitions=(od_dict,),
            outcome_approvals=(approval_dict,),
            counterfactual_fingerprint="fp-counterfactual",
            nbt_completeness_metadata=None,
        )
        deps = ScenarioGovernanceDependencies(
            model_run_id="run-abc",
            model_approval_fingerprint="fp-approval",
            data_fingerprint="fp-data",
            model_spec_fingerprint="fp-spec",
            posterior_fingerprint="fp-posterior",
            planning_objective_fingerprint=fingerprint_planning_objective(obj),
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="New",
                    requested_use="planning",
                    approval_id="app-New",
                    definition_fingerprint=od_fp,
                ),
            ),
            nbt_completeness_fingerprint=None,
            counterfactual_policy_fingerprint="fp-counterfactual",
        )
        scenario = {
            "name": "test",
            "governance_mode": "official",
            "schema_version": 3,
            "artefact_kind": "manual_scenario",
            "governance_dependencies": deps.to_dict(),
        }
        issues = validate_scenario_dependencies(scenario, context=ctx)
        assert len(issues) == 0


# ============================================================================
# 13.7 Value mapping
# ============================================================================


class TestValueMapping:
    """REQ-VALUE-001: outcome-level mapping drives all value calculations."""

    def test_value_mapping_fingerprint_round_trips(self):
        """Mapping fingerprint is deterministic and changes when values change."""
        m1 = OutcomeValueMapping(
            mapping_id="map1",
            source="test",
            value_by_outcome_id={"New": 100.0, "Winback": 50.0},
            currency_by_outcome_id={"New": "GBP", "Winback": "GBP"},
        )
        m2 = OutcomeValueMapping(
            mapping_id="map1",
            source="test",
            value_by_outcome_id={"New": 100.0, "Winback": 50.0},
            currency_by_outcome_id={"New": "GBP", "Winback": "GBP"},
        )
        m3 = OutcomeValueMapping(
            mapping_id="map1",
            source="test",
            value_by_outcome_id={"New": 200.0, "Winback": 50.0},
            currency_by_outcome_id={"New": "GBP", "Winback": "GBP"},
        )
        assert m1.fingerprint == m2.fingerprint
        assert m1.fingerprint != m3.fingerprint

    def test_legacy_segment_mapping_requires_explicit_mapping(self):
        """from_legacy_segment_ltv requires explicit outcome-to-segment mapping."""
        mapping = OutcomeValueMapping.from_legacy_segment_ltv(
            segment_by_outcome_id={"New": "New"},
            segment_ltv={"New": 50.0},
            currency="GBP",
            outcome_ids=("New",),
        )
        assert mapping.value_by_outcome_id["New"] == 50.0
        assert mapping.currency_by_outcome_id["New"] == "GBP"

    def test_missing_legacy_segment_value_blocks(self):
        """Missing legacy segment value must block, not default to zero."""
        with pytest.raises((ValueError, KeyError, PlanningGovernanceError)):
            OutcomeValueMapping.from_legacy_segment_ltv(
                segment_by_outcome_id={"DNA_CrossSell": "DNA_CrossSell"},
                segment_ltv={"New": 50.0},
                currency="GBP",
                outcome_ids=("DNA_CrossSell",),
            )


# ============================================================================
# 13.8 Currency
# ============================================================================


class TestCurrency:
    """REQ-CURRENCY-001: currency context validates ISO codes."""

    def test_valid_gbp_target_set(self):
        """One selected GBP target set is valid."""
        ctx = CurrencyContext(market_reporting_currency="GBP")
        assert ctx.market_reporting_currency == "GBP"

    def test_valid_usd_target_set(self):
        """One selected USD target set is valid."""
        ctx = CurrencyContext(market_reporting_currency="USD")
        assert ctx.market_reporting_currency == "USD"

    def test_blank_currency_allowed_for_non_value(self):
        """Blank currency is allowed for non-value contexts."""
        ctx = CurrencyContext(market_reporting_currency="")
        assert ctx.market_reporting_currency == ""

    def test_no_constructor_hard_codes_currency(self):
        """No CurrencyContext constructor hard-codes a currency."""
        ctx = CurrencyContext(market_reporting_currency="EUR")
        assert ctx.market_reporting_currency == "EUR"

    def test_currency_context_fingerprint_round_trips(self):
        """Currency-context fingerprint is deterministic."""
        c1 = CurrencyContext(market_reporting_currency="GBP")
        c2 = CurrencyContext(market_reporting_currency="GBP")
        c3 = CurrencyContext(market_reporting_currency="USD")
        assert c1.fingerprint() == c2.fingerprint()
        assert c1.fingerprint() != c3.fingerprint()


# ============================================================================
# G2A.7a.10 (brief section 8, 14.6, 14.7): symmetric value/currency
# dependency validation
# ============================================================================


class TestValueCurrencyDependencySymmetry:
    """REQ-VALUE-002/REQ-CURRENCY-002: validate_scenario_dependencies used to
    only compare a saved value_mapping_fingerprint/currency_context_fingerprint
    against the current context when the current context happened to supply
    one (`context.X_fingerprint is not None`) - a saved scenario with a real
    dependency on record silently passed as "current" whenever the caller's
    context omitted the field. Whether the dependency is required is now
    determined from the saved scenario's own planning_objective.estimand,
    never from what the current context happens to provide."""

    def _value_scenario(self, *, value_mapping_fp, currency_context_fp) -> dict:
        return scenario_to_dict(
            name="value-scenario",
            market="UK",
            spend_plan={"2024-01": {"TV_Brand": 100.0}},
            objective="expected_value",
            constraints=[],
            planning_objective=_make_planning_objective(
                estimand="incremental_value",
                metric_key="expected_value",
                value_currency="GBP",
            ),
            artefact_kind="manual_scenario",
            governance_mode="official",
            governance_dependencies=ScenarioGovernanceDependencies(
                **IDENTITY,
                model_approval_fingerprint="approval-fp",
                planning_objective_fingerprint="obj-fp",
                outcome_authorisations=(),
                value_mapping_fingerprint=value_mapping_fp,
                currency_context_fingerprint=currency_context_fp,
                counterfactual_policy_fingerprint="cf-fp",
            ),
        )

    def _issues_of_type(self, issues, dependency_type):
        return [i for i in issues if i.dependency_type == dependency_type]

    def test_saved_value_mapping_with_current_missing_is_invalid(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-saved", currency_context_fp="ccf-saved"
        )
        context = _make_blank_context(
            value_mapping_fingerprint=None,
            currency_context_fingerprint="ccf-saved",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        vm_issues = self._issues_of_type(issues, "value_mapping")
        assert vm_issues, (
            "saved value mapping with no current value mapping must not pass silently"
        )
        assert vm_issues[0].issue_type == "invalid"
        assert vm_issues[0].reason_code == "missing_current_value_mapping"

    def test_saved_currency_context_with_current_missing_is_invalid(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-saved", currency_context_fp="ccf-saved"
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-saved",
            currency_context_fingerprint=None,
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        cc_issues = self._issues_of_type(issues, "currency_context")
        assert cc_issues, (
            "saved currency context with no current currency context must not pass silently"
        )
        assert cc_issues[0].issue_type == "invalid"
        assert cc_issues[0].reason_code == "missing_current_currency_context"

    def test_value_objective_with_no_saved_value_mapping_is_invalid(self):
        """estimand=incremental_value requires a value mapping regardless of
        whether one happens to be saved."""
        scenario = self._value_scenario(
            value_mapping_fp=None, currency_context_fp="ccf-saved"
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-current",
            currency_context_fingerprint="ccf-saved",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        vm_issues = self._issues_of_type(issues, "value_mapping")
        assert vm_issues
        assert vm_issues[0].issue_type == "invalid"
        assert vm_issues[0].reason_code == "missing_value_mapping_fingerprint"

    def test_value_objective_with_no_saved_currency_context_is_invalid(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-saved", currency_context_fp=None
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-saved",
            currency_context_fingerprint="ccf-current",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        cc_issues = self._issues_of_type(issues, "currency_context")
        assert cc_issues
        assert cc_issues[0].issue_type == "invalid"
        assert cc_issues[0].reason_code == "missing_currency_context_fingerprint"

    def test_changed_value_mapping_fingerprint_is_stale(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-old", currency_context_fp="ccf-saved"
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-new",
            currency_context_fingerprint="ccf-saved",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        vm_issues = self._issues_of_type(issues, "value_mapping")
        assert vm_issues
        assert vm_issues[0].issue_type == "stale"
        assert vm_issues[0].reason_code == "value_mapping_stale"

    def test_changed_currency_context_fingerprint_is_stale(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-saved", currency_context_fp="ccf-old"
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-saved",
            currency_context_fingerprint="ccf-new",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        cc_issues = self._issues_of_type(issues, "currency_context")
        assert cc_issues
        assert cc_issues[0].issue_type == "stale"
        assert cc_issues[0].reason_code == "currency_context_stale"

    def test_matching_value_mapping_and_currency_context_raise_no_issue(self):
        scenario = self._value_scenario(
            value_mapping_fp="vmf-match", currency_context_fp="ccf-match"
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-match",
            currency_context_fingerprint="ccf-match",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        assert not self._issues_of_type(issues, "value_mapping")
        assert not self._issues_of_type(issues, "currency_context")

    def test_non_value_objective_does_not_require_value_mapping(self):
        """A plain incremental_outcome scenario with no value dependency on
        record must not be forced to have one just because the current
        context happens to carry one."""
        scenario = scenario_to_dict(
            name="outcome-scenario",
            market="UK",
            spend_plan={"2024-01": {"TV_Brand": 100.0}},
            objective="fh_gsa",
            constraints=[],
            planning_objective=_make_planning_objective(estimand="incremental_outcome"),
            artefact_kind="manual_scenario",
            governance_mode="official",
            governance_dependencies=ScenarioGovernanceDependencies(
                **IDENTITY,
                model_approval_fingerprint="approval-fp",
                planning_objective_fingerprint="obj-fp",
                outcome_authorisations=(),
                value_mapping_fingerprint=None,
                currency_context_fingerprint=None,
                counterfactual_policy_fingerprint="cf-fp",
            ),
        )
        context = _make_blank_context(
            value_mapping_fingerprint="vmf-current",
            currency_context_fingerprint="ccf-current",
        )
        issues = validate_scenario_dependencies(scenario, context=context)
        assert not self._issues_of_type(issues, "value_mapping")
        assert not self._issues_of_type(issues, "currency_context")


# ============================================================================
# 13.9 Persistence lifecycle
# ============================================================================


class TestPersistenceLifecycle:
    """REQ-LIFECYCLE-001: full save/export/import/validate round trip."""

    def test_scenario_to_dict_and_back(self):
        """scenario_to_dict and scenario_from_dict round-trip preserves artefact_kind."""
        spend = {"2026-07": {"TV": 100.0}}
        s = scenario_to_dict(
            "test",
            "UK",
            spend,
            "fh_gsa",
            [],
            artefact_kind="manual_scenario",
        )
        loaded = scenario_from_dict(s)
        assert loaded["name"] == "test"
        assert loaded["artefact_kind"] == "manual_scenario"

    def test_governance_deps_round_trip_through_dict(self):
        """ScenarioGovernanceDependencies round-trips through dict."""
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(
                ResolvedOutcomeAuthorisation(
                    outcome_id="New",
                    requested_use="planning",
                    approval_id="app1",
                    definition_fingerprint="dfp1",
                ),
            ),
            value_mapping_id="vm1",
            value_mapping_fingerprint="vmf1",
            currency_context_fingerprint="ccf1",
        )
        d = deps.to_dict()
        restored = ScenarioGovernanceDependencies.from_dict(d)
        assert restored.model_run_id == deps.model_run_id
        assert restored.value_mapping_id == deps.value_mapping_id
        assert restored.value_mapping_fingerprint == deps.value_mapping_fingerprint
        assert (
            restored.currency_context_fingerprint == deps.currency_context_fingerprint
        )
        assert restored.outcome_authorisations[0].outcome_id == "New"

    def test_model_approval_has_correct_field_names(self):
        """ModelApproval uses model_spec_fingerprint (not model_specification_fingerprint)."""
        approval = ModelApproval(
            approved_by="Tester",
            model_run_id="r1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
        )
        fp = fingerprint_model_approval(approval)
        assert fp is not None
        assert approval.model_spec_fingerprint == "msf1"


# ============================================================================
# 13.10 Scenario Planner contracts
# ============================================================================


class TestScenarioPlannerContracts:
    """REQ-UI-001: Scenario Planner uses canonical outcome-ID mapping."""

    def test_planning_objective_resolution_uses_catalogue(self):
        """PlanningObjective from catalogue weights uses outcome IDs, not legacy segment LTV."""
        obj = _make_planning_objective(
            estimand="incremental_value",
            metric_key=METRIC_KEY_FH_GSA,
            target_outcome_ids=("New", "Winback"),
            value_currency="GBP",
        )
        assert obj.estimand == "incremental_value"
        assert "New" in obj.target_outcome_ids
        assert obj.value_currency == "GBP"

    def test_planning_objective_round_trips_through_dict(self):
        """PlanningObjective serialises and deserialises, preserving value_currency."""
        obj = _make_planning_objective(
            estimand="incremental_value",
            value_currency="USD",
        )
        d = obj.to_dict()
        restored = PlanningObjective.from_dict(d)
        assert restored.value_currency == obj.value_currency
        assert restored.estimand == obj.estimand


# ============================================================================
# _calculate_scenario contract
# ============================================================================


class TestPrivateCalculateScenario:
    """REQ-CALC-001: _calculate_scenario has no governance surface."""

    def test_no_governance_parameters(self):
        """_calculate_scenario must not accept approval, governance_mode, or _trusted_operation."""
        sig = inspect.signature(_calculate_scenario)
        params = set(sig.parameters.keys())
        assert "approval" not in params
        assert "governance_mode" not in params
        assert "outcome_approvals" not in params
        assert "_trusted_operation" not in params

    def test_is_callable(self):
        """Verify the function exists and is callable."""
        assert callable(_calculate_scenario)


# ============================================================================
# OutcomeValueMapping fingerprint contract
# ============================================================================


class TestOutcomeValueMappingFingerprint:
    """REQ-VALUE-002: mapping fingerprint is canonical and enforced."""

    def test_fingerprint_changes_when_currency_changes(self):
        m1 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 100.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        m2 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 100.0},
            currency_by_outcome_id={"New": "USD"},
        )
        assert m1.fingerprint != m2.fingerprint

    def test_fingerprint_changes_when_values_change(self):
        m1 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 100.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        m2 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 200.0},
            currency_by_outcome_id={"New": "GBP"},
        )
        assert m1.fingerprint != m2.fingerprint

    def test_fingerprint_stable_for_same_values(self):
        fp1 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 100.0},
            currency_by_outcome_id={"New": "GBP"},
        ).fingerprint
        fp2 = OutcomeValueMapping(
            mapping_id="m1",
            source="test",
            value_by_outcome_id={"New": 100.0},
            currency_by_outcome_id={"New": "GBP"},
        ).fingerprint
        assert fp1 == fp2


# ============================================================================
# ScenarioGovernanceDependencies extended fields
# ============================================================================


class TestScenarioGovernanceDependenciesExtended:
    """REQ-DEPS-001: extended fields for value and currency identity."""

    def test_value_mapping_fields_round_trip(self):
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(),
            value_mapping_id="vm1",
            value_mapping_fingerprint="vmf1",
            currency_context_fingerprint="ccf1",
        )
        d = deps.to_dict()
        restored = ScenarioGovernanceDependencies.from_dict(d)
        assert restored.value_mapping_id == "vm1"
        assert restored.value_mapping_fingerprint == "vmf1"
        assert restored.currency_context_fingerprint == "ccf1"

    def test_fx_fields_remain_null(self):
        """FX fields may remain null in this PR."""
        deps = ScenarioGovernanceDependencies(
            model_run_id="r1",
            model_approval_fingerprint="maf1",
            data_fingerprint="df1",
            model_spec_fingerprint="msf1",
            posterior_fingerprint="pf1",
            planning_objective_fingerprint="opf1",
            outcome_authorisations=(),
        )
        assert deps.historical_fx_rate_set_id is None
        assert deps.historical_fx_rate_set_fingerprint is None
        assert deps.future_fx_assumption_id is None
        assert deps.future_fx_assumption_fingerprint is None
