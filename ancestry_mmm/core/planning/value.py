"""
Pure value objects and dataclasses for planning and optimisation.

Extracted from ``core/optimization.py`` as part of PR 5 (planning package
refactor). No numerical behaviour is changed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# G2A.7a.3 exception model
# ---------------------------------------------------------------------------


class ObjectiveMissingError(RuntimeError):
    """Official planning/optimisation requires an explicit objective."""
    # Imported from .outcome_approval.PlanningGovernanceError hierarchy.
    # Defined here so the value layer has its own importable exception
    # without requiring a circular dependency.


# ---------------------------------------------------------------------------
# G2A.7a.2 resolved governance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedOutcomeAuthorisation:
    """Proof that one outcome has been authorised for a specific use.

    Carried through the optimiser into nested calculations so they never
    need to re-validate or downgrade to exploratory.

    G2A.7a.3: ``scope_fingerprint`` was removed — it duplicated the
    definition fingerprint. Explicit scope values (market, product,
    segment) are persisted instead, so the authorisation's scope is
    auditable without re-deriving it from the definition."""
    outcome_id: str
    requested_use: str  # "planning" or "optimisation"
    approval_id: str
    definition_fingerprint: str
    market: Optional[str] = None
    product: Optional[str] = None
    segment: Optional[str] = None
    nbt_completeness_fingerprint: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ResolvedOutcomeAuthorisation":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass(frozen=True)
class ResolvedPlanningGovernance:
    """Immutable governance proof created once by the resolver, then passed
    into the solver, point evaluation, and posterior evaluation.

    G2A.7a.6: includes ``model_approval_fingerprint`` so the proof carries
    the exact approval-record identity the resolver confirmed."""
    governance_mode: str  # "official" or "exploratory"
    operation: str  # "planning" or "optimisation"
    objective_fingerprint: str
    model_run_id: str
    data_fingerprint: str
    model_spec_fingerprint: str
    posterior_fingerprint: str
    market: str
    authorisations: Tuple[ResolvedOutcomeAuthorisation, ...]
    model_approval_fingerprint: str = ""
    target_outcome_ids: Tuple[str, ...] = ()

    @property
    def is_official(self) -> bool:
        return self.governance_mode == "official"

    def to_dict(self) -> dict:
        return {
            "governance_mode": self.governance_mode,
            "operation": self.operation,
            "objective_fingerprint": self.objective_fingerprint,
            "model_run_id": self.model_run_id,
            "model_approval_fingerprint": self.model_approval_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "model_spec_fingerprint": self.model_spec_fingerprint,
            "posterior_fingerprint": self.posterior_fingerprint,
            "market": self.market,
            "authorisations": [a.to_dict() for a in self.authorisations],
            "target_outcome_ids": list(self.target_outcome_ids),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ResolvedPlanningGovernance":
        raw_targets = d.get("target_outcome_ids", ())
        return cls(
            governance_mode=d.get("governance_mode", "exploratory"),
            operation=d.get("operation", "planning"),
            objective_fingerprint=d.get("objective_fingerprint", ""),
            model_run_id=d.get("model_run_id", ""),
            data_fingerprint=d.get("data_fingerprint", ""),
            model_spec_fingerprint=d.get("model_spec_fingerprint", ""),
            posterior_fingerprint=d.get("posterior_fingerprint", ""),
            market=d.get("market", ""),
            authorisations=tuple(
                ResolvedOutcomeAuthorisation.from_dict(a)
                for a in d.get("authorisations", [])
            ),
            model_approval_fingerprint=d.get("model_approval_fingerprint", ""),
            target_outcome_ids=(
                tuple(raw_targets) if isinstance(raw_targets, list) else raw_targets
            ),
        )

    def validate_against(
        self,
        *,
        operation: str,
        objective_fingerprint: str,
        model_run_id: str,
        model_approval_fingerprint: str = "",
        data_fingerprint: str,
        model_spec_fingerprint: str,
        posterior_fingerprint: str,
        market: str,
        expected_operation: str | None = None,
    ) -> None:
        """Raises ``OutcomeApprovalBlockedError`` if any field does not
        match the current calculation context.

        When ``expected_operation`` is provided (preferred), validates
        against that value — do not call with ``operation=resolved.operation``
        as that compares the field with itself."""
        # Lazy import to avoid circular dependency at module level
        from ..outcome_approval import OutcomeApprovalBlockedError

        if self.governance_mode != "official":
            raise OutcomeApprovalBlockedError(
                "Resolved governance is not official."
            )
        # Use expected_operation when provided — not self.operation
        check_operation = expected_operation if expected_operation is not None else operation
        if self.operation != check_operation:
            raise OutcomeApprovalBlockedError(
                f"Resolved governance operation is '{self.operation}' "
                f"but the expected operation is '{check_operation}'."
            )
        if not self.objective_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance has an empty objective fingerprint."
            )
        if self.objective_fingerprint != objective_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance objective fingerprint does not match "
                "the current objective."
            )
        if not self.model_run_id:
            raise OutcomeApprovalBlockedError(
                "Resolved governance has an empty model_run_id."
            )
        if self.model_run_id != model_run_id:
            raise OutcomeApprovalBlockedError(
                "Resolved governance model_run_id does not match."
            )
        if not self.model_approval_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance has a blank model_approval_fingerprint — "
                "cannot authorise an official calculation."
            )
        if not model_approval_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Current model approval fingerprint is absent — "
                "cannot verify resolved governance."
            )
        if self.model_approval_fingerprint != model_approval_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance model_approval_fingerprint does not match "
                "the current model approval."
            )
        if self.data_fingerprint != data_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance data_fingerprint does not match."
            )
        if self.model_spec_fingerprint != model_spec_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance model_spec_fingerprint does not match."
            )
        if self.posterior_fingerprint != posterior_fingerprint:
            raise OutcomeApprovalBlockedError(
                "Resolved governance posterior_fingerprint does not match."
            )
        if self.market != market:
            raise OutcomeApprovalBlockedError(
                f"Resolved governance market is '{self.market}' but the "
                f"current market is '{market}'."
            )
        if not self.authorisations:
            raise OutcomeApprovalBlockedError(
                "Resolved governance has zero authorisations — cannot "
                "authorise an official calculation."
            )
        target_list = list(self.target_outcome_ids)
        if not target_list:
            raise OutcomeApprovalBlockedError(
                "Resolved governance has no target outcome IDs — cannot "
                "authorise an official calculation."
            )
        if len(target_list) != len(set(target_list)):
            duplicates = [oid for oid in target_list if target_list.count(oid) > 1]
            raise OutcomeApprovalBlockedError(
                f"Resolved governance has duplicate target outcome IDs: "
                f"{sorted(set(duplicates))}."
            )
        auth_id_list = [a.outcome_id for a in self.authorisations]
        if len(auth_id_list) != len(set(auth_id_list)):
            duplicates = [oid for oid in auth_id_list if auth_id_list.count(oid) > 1]
            raise OutcomeApprovalBlockedError(
                f"Resolved governance has duplicate authorisations for: "
                f"{sorted(set(duplicates))}."
            )
        approval_ids = [a.approval_id for a in self.authorisations]
        if len(approval_ids) != len(set(approval_ids)):
            duplicates = [aid for aid in approval_ids if approval_ids.count(aid) > 1]
            raise OutcomeApprovalBlockedError(
                f"Resolved governance has duplicate approval IDs: "
                f"{sorted(set(duplicates))}."
            )
        if len(self.authorisations) != len(target_list):
            raise OutcomeApprovalBlockedError(
                f"Resolved governance has {len(self.authorisations)} "
                f"authorisations for {len(target_list)} targets — "
                "counts must match."
            )
        authorised_ids = {a.outcome_id for a in self.authorisations}
        target_set = set(target_list)
        if authorised_ids != target_set:
            missing = target_set - authorised_ids
            extra = authorised_ids - target_set
            parts = []
            if missing:
                parts.append(f"missing authorisations for: {sorted(missing)}")
            if extra:
                parts.append(f"extra authorisations for: {sorted(extra)}")
            raise OutcomeApprovalBlockedError(
                "Resolved governance target mismatch: " + "; ".join(parts)
            )
        for auth in self.authorisations:
            if auth.requested_use != check_operation:
                raise OutcomeApprovalBlockedError(
                    f"Authorisation for outcome '{auth.outcome_id}' has "
                    f"requested_use='{auth.requested_use}' but expected "
                    f"'{check_operation}'."
                )


# ---------------------------------------------------------------------------
# Scenario governance dependencies
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioGovernanceDependencies:
    """Typed governance dependency contract for scenario persistence.

    Every field must be populated for an official save. Missing mandatory
    fields must block the save, not silently default to None."""
    model_run_id: str
    model_approval_fingerprint: str
    data_fingerprint: str
    model_spec_fingerprint: str
    posterior_fingerprint: str
    planning_objective_fingerprint: str
    outcome_authorisations: tuple[ResolvedOutcomeAuthorisation, ...]
    value_mapping_id: str | None = None
    value_mapping_fingerprint: str | None = None
    currency_context_fingerprint: str | None = None
    historical_fx_rate_set_id: str | None = None
    historical_fx_rate_set_fingerprint: str | None = None
    future_fx_assumption_id: str | None = None
    future_fx_assumption_fingerprint: str | None = None
    activity_definitions_fingerprint: str | None = None
    cost_mapping_fingerprint: str | None = None
    counterfactual_policy_fingerprint: str = ""
    nbt_completeness_fingerprint: str | None = None

    def to_dict(self) -> dict:
        return {
            "model_run_id": self.model_run_id,
            "model_approval_fingerprint": self.model_approval_fingerprint,
            "data_fingerprint": self.data_fingerprint,
            "model_spec_fingerprint": self.model_spec_fingerprint,
            "posterior_fingerprint": self.posterior_fingerprint,
            "planning_objective_fingerprint": self.planning_objective_fingerprint,
            "outcome_authorisations": [
                a.to_dict() for a in self.outcome_authorisations
            ],
            "value_mapping_id": self.value_mapping_id,
            "value_mapping_fingerprint": self.value_mapping_fingerprint,
            "currency_context_fingerprint": self.currency_context_fingerprint,
            "historical_fx_rate_set_id": self.historical_fx_rate_set_id,
            "historical_fx_rate_set_fingerprint": self.historical_fx_rate_set_fingerprint,
            "future_fx_assumption_id": self.future_fx_assumption_id,
            "future_fx_assumption_fingerprint": self.future_fx_assumption_fingerprint,
            "activity_definitions_fingerprint": self.activity_definitions_fingerprint,
            "cost_mapping_fingerprint": self.cost_mapping_fingerprint,
            "counterfactual_policy_fingerprint": self.counterfactual_policy_fingerprint,
            "nbt_completeness_fingerprint": self.nbt_completeness_fingerprint,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioGovernanceDependencies":
        return cls(
            model_run_id=d.get("model_run_id", ""),
            model_approval_fingerprint=d.get("model_approval_fingerprint", ""),
            data_fingerprint=d.get("data_fingerprint", ""),
            model_spec_fingerprint=d.get("model_spec_fingerprint", ""),
            posterior_fingerprint=d.get("posterior_fingerprint", ""),
            planning_objective_fingerprint=d.get("planning_objective_fingerprint", ""),
            outcome_authorisations=tuple(
                ResolvedOutcomeAuthorisation.from_dict(a)
                for a in d.get("outcome_authorisations", [])
            ),
            value_mapping_id=d.get("value_mapping_id"),
            value_mapping_fingerprint=d.get("value_mapping_fingerprint"),
            currency_context_fingerprint=d.get("currency_context_fingerprint"),
            historical_fx_rate_set_id=d.get("historical_fx_rate_set_id"),
            historical_fx_rate_set_fingerprint=d.get("historical_fx_rate_set_fingerprint"),
            future_fx_assumption_id=d.get("future_fx_assumption_id"),
            future_fx_assumption_fingerprint=d.get("future_fx_assumption_fingerprint"),
            activity_definitions_fingerprint=d.get("activity_definitions_fingerprint"),
            cost_mapping_fingerprint=d.get("cost_mapping_fingerprint"),
            counterfactual_policy_fingerprint=d.get("counterfactual_policy_fingerprint", ""),
            nbt_completeness_fingerprint=d.get("nbt_completeness_fingerprint"),
        )


# ---------------------------------------------------------------------------
# Scenario evaluation result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioEvaluationResult:
    """Structured manual evaluation result with full governance provenance.

    G2A.7a.6: includes ``governance_dependencies`` for persistence."""
    predicted: pd.DataFrame
    planning_objective: "PlanningObjective | None"
    governance_mode: str
    artefact_kind: str
    resolved_governance: ResolvedPlanningGovernance | None = None
    governance_dependencies: ScenarioGovernanceDependencies | None = None
    activity_definitions_fingerprint: str | None = None
    cost_mapping_fingerprint: str | None = None
    counterfactual_policy_fingerprint: str = ""
    economics_coverage: dict | None = None

    def to_dict(self) -> dict:
        return {
            "predicted": self.predicted,
            "planning_objective": self.planning_objective.to_dict() if self.planning_objective else None,
            "governance_mode": self.governance_mode,
            "artefact_kind": self.artefact_kind,
            "resolved_governance": self.resolved_governance.to_dict() if self.resolved_governance else None,
            "governance_dependencies": self.governance_dependencies.to_dict() if self.governance_dependencies else None,
            "activity_definitions_fingerprint": self.activity_definitions_fingerprint,
            "cost_mapping_fingerprint": self.cost_mapping_fingerprint,
            "counterfactual_policy_fingerprint": self.counterfactual_policy_fingerprint,
            "economics_coverage": self.economics_coverage,
        }


# ---------------------------------------------------------------------------
# Outcome-value mapping
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OutcomeValueMapping:
    """Canonical outcome-level value mapping for expected-value calculations.

    Outcome-ID weights are authoritative. Legacy segment LTV is converted
    through an explicit migration adapter before reaching this type.

    G2A.7a.9: ``mapping_fingerprint`` is a deterministic fingerprint of the
    mapping's identity and content. A caller-supplied ``mapping_fingerprint``
    may disagree with the calculated fingerprint — in that case the
    calculated fingerprint is authoritative (``mapping_fingerprint`` property
    recalculates it)."""
    value_by_outcome_id: Mapping[str, float]
    currency_by_outcome_id: Mapping[str, str]
    mapping_id: str = "default"
    mapping_fingerprint: str = ""
    source: str = "outcome_catalogue"

    def __post_init__(self) -> None:
        """Validate that every value and currency field is populated,
        and that the fingerprint is consistent with the content."""
        for oid, val in self.value_by_outcome_id.items():
            if val is None or (isinstance(val, float) and np.isnan(val)):
                raise ValueError(f"OutcomeValueMapping.value_by_outcome_id[{oid!r}] is None or NaN")
        for oid, cur in self.currency_by_outcome_id.items():
            if not cur:
                raise ValueError(f"OutcomeValueMapping.currency_by_outcome_id[{oid!r}] is empty")
        # Recalculate the authoritative fingerprint
        computed = self._compute_fingerprint()
        object.__setattr__(self, "mapping_fingerprint", computed)

    def _compute_fingerprint(self) -> str:
        payload = {
            "mapping_id": self.mapping_id,
            "value_by_outcome_id": dict(sorted(self.value_by_outcome_id.items())),
            "currency_by_outcome_id": dict(sorted(self.currency_by_outcome_id.items())),
            "source": self.source,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return {
            "mapping_id": self.mapping_id,
            "mapping_fingerprint": self.mapping_fingerprint,
            "value_by_outcome_id": dict(self.value_by_outcome_id),
            "currency_by_outcome_id": dict(self.currency_by_outcome_id),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeValueMapping":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)


def legacy_segment_ltv_to_value_mapping(
    segment_ltv: dict[str, float],
    currency: str = "GBP",
) -> OutcomeValueMapping:
    """Convert a legacy ``{segment_name: LTV}`` dict to an
    ``OutcomeValueMapping`` keyed by outcome ID.

    The mapping is:
    - ``New`` → ``segment_ltv["New"]``
    - ``DNA_CrossSell`` → ``segment_ltv.get("DNA_CrossSell", segment_ltv.get("FH DNA", 0.0))``
    - ``Winback`` → ``segment_ltv.get("Winback", segment_ltv.get("Winback", 0.0))``

    If the legacy dict uses "FH DNA" as the key (common in old project
    exports), it is mapped to DNA_CrossSell. Unrecognised keys are ignored.
    """
    legacy_map = {
        "New": segment_ltv.get("New", 0.0),
        "DNA_CrossSell": segment_ltv.get("DNA_CrossSell", segment_ltv.get("FH DNA", 0.0)),
        "Winback": segment_ltv.get("Winback", 0.0),
    }
    value_by_outcome_id = {k: float(v) for k, v in legacy_map.items()}
    currency_by_outcome_id = {k: currency for k in value_by_outcome_id}
    return OutcomeValueMapping(
        value_by_outcome_id=value_by_outcome_id,
        currency_by_outcome_id=currency_by_outcome_id,
        mapping_id="legacy_segment_ltv_migration",
        source="legacy_segment_ltv_migration",
    )


# ---------------------------------------------------------------------------
# Currency context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrencyContext:
    """Currency context for scenario planning and reporting.

    For single-market planning: local monetary decisions remain in the
    market reporting currency. No conversion is performed without a
    governed rate set or assumption.

    G2A.7a.9: validates ISO-style three-letter uppercase codes for
    populated currency fields. No hard-coded defaults for GBP, USD, or
    group reporting currency. ``fingerprint`` is deterministic."""

    market_reporting_currency: str = ""
    value_currency: str | None = None
    group_reporting_currency: str | None = None
    model_currency: str | None = None
    historical_fx_rate_set_id: str | None = None
    historical_fx_rate_set_fingerprint: str | None = None
    future_fx_assumption_id: str | None = None
    future_fx_assumption_fingerprint: str | None = None

    def __post_init__(self) -> None:
        _ISO_CODE_RE = __import__('re').compile(r'^[A-Z]{3}$')
        for field_name in ('market_reporting_currency', 'value_currency',
                           'group_reporting_currency', 'model_currency'):
            value = getattr(self, field_name)
            if value and (not isinstance(value, str) or not _ISO_CODE_RE.match(value)):
                raise ValueError(
                    f"CurrencyContext.{field_name} must be a three-letter "
                    f"uppercase ISO code, got {value!r}."
                )

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of the currency context's
        identity-relevant fields."""
        payload = {
            "market_reporting_currency": self.market_reporting_currency,
            "value_currency": self.value_currency,
            "group_reporting_currency": self.group_reporting_currency,
            "model_currency": self.model_currency,
            "historical_fx_rate_set_id": self.historical_fx_rate_set_id,
            "historical_fx_rate_set_fingerprint": self.historical_fx_rate_set_fingerprint,
            "future_fx_assumption_id": self.future_fx_assumption_id,
            "future_fx_assumption_fingerprint": self.future_fx_assumption_fingerprint,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        result = asdict(self)
        result["fingerprint"] = self.fingerprint()
        return result

    @classmethod
    def from_dict(cls, d: dict) -> "CurrencyContext":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)


# ---------------------------------------------------------------------------
# Scenario validation context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioValidationContext:
    """Complete current project state for scenario dependency validation.

    A scenario may be ``current`` only when every required saved dependency
    was compared with this context. Omitted fields prevent ``current``
    status.

    Required (non-optional) fields are mandatory for every official check.
    Optional fields are use-specific (activity, cost, NBT).

    G2A.7a.9: ``__post_init__`` rejects blank required fields and empty
    collections. Use ``validation_context_from_legacy_args()`` for the
    compatibility adapter path."""

    model_run_id: str
    model_approval_fingerprint: str
    data_fingerprint: str
    model_spec_fingerprint: str
    posterior_fingerprint: str
    planning_objective: "PlanningObjective"
    outcome_definitions: tuple
    outcome_approvals: tuple
    counterfactual_fingerprint: str
    value_mapping_fingerprint: str | None = None
    currency_context_fingerprint: str | None = None
    activity_fingerprint: Optional[str] = None
    cost_fingerprint: Optional[str] = None
    nbt_completeness_metadata: Optional[dict] = None

    def __post_init__(self) -> None:
        """Reject blank required fields and empty collections.

        Use-specific fields (value_mapping_fingerprint,
        currency_context_fingerprint, activity_fingerprint, cost_fingerprint,
        nbt_completeness_metadata) may remain None when the saved scenario
        does not depend on them - only the scenario's own saved dependencies
        determine which fields are mandatory, not the context alone."""
        if not self.model_run_id or not self.model_run_id.strip():
            raise ValueError("ScenarioValidationContext.model_run_id must be non-blank")
        if not self.model_approval_fingerprint or not self.model_approval_fingerprint.strip():
            raise ValueError("ScenarioValidationContext.model_approval_fingerprint must be non-blank")
        if not self.data_fingerprint or not self.data_fingerprint.strip():
            raise ValueError("ScenarioValidationContext.data_fingerprint must be non-blank")
        if not self.model_spec_fingerprint or not self.model_spec_fingerprint.strip():
            raise ValueError("ScenarioValidationContext.model_spec_fingerprint must be non-blank")
        if not self.posterior_fingerprint or not self.posterior_fingerprint.strip():
            raise ValueError("ScenarioValidationContext.posterior_fingerprint must be non-blank")
        if self.planning_objective is None:
            raise ValueError("ScenarioValidationContext.planning_objective must not be None")
        if not self.planning_objective.is_valid_for_official_planning:
            raise ValueError(
                "ScenarioValidationContext.planning_objective must be valid for official planning"
            )
        if not self.outcome_definitions:
            raise ValueError("ScenarioValidationContext.outcome_definitions must not be empty")
        if not self.outcome_approvals:
            raise ValueError("ScenarioValidationContext.outcome_approvals must not be empty")
        if not self.counterfactual_fingerprint or not self.counterfactual_fingerprint.strip():
            raise ValueError("ScenarioValidationContext.counterfactual_fingerprint must be non-blank")


def validation_context_from_legacy_args(
    *,
    model_run_id: str = "",
    model_approval_fingerprint: str = "",
    data_fingerprint: str = "",
    model_spec_fingerprint: str = "",
    posterior_fingerprint: str = "",
    planning_objective: Any = None,
    outcome_definitions: Any = None,
    outcome_approvals: Any = None,
    counterfactual_fingerprint: str = "",
    **kwargs: Any,
) -> ScenarioValidationContext:
    """Build a ``ScenarioValidationContext`` from legacy (keyword-only or
    positional) arguments.

    This is the compatibility adapter: it requires every mandatory field to
    be non-blank/non-None and constructs the context. Partial contexts
    (missing a required field) raise ``ValueError`` rather than producing a
    malfunctioning context.

    Note: ``planning_objective`` must be a ``PlanningObjective`` instance
    whose ``is_valid_for_official_planning`` is True.
    """
    if not model_run_id:
        raise ValueError("model_run_id is required for ScenarioValidationContext")
    if not model_approval_fingerprint:
        raise ValueError("model_approval_fingerprint is required for ScenarioValidationContext")
    if not data_fingerprint:
        raise ValueError("data_fingerprint is required for ScenarioValidationContext")
    if not model_spec_fingerprint:
        raise ValueError("model_spec_fingerprint is required for ScenarioValidationContext")
    if not posterior_fingerprint:
        raise ValueError("posterior_fingerprint is required for ScenarioValidationContext")
    if planning_objective is None:
        raise ValueError("planning_objective is required for ScenarioValidationContext")
    if not outcome_definitions:
        raise ValueError("outcome_definitions are required for ScenarioValidationContext")
    if not outcome_approvals:
        raise ValueError("outcome_approvals are required for ScenarioValidationContext")
    if not counterfactual_fingerprint:
        raise ValueError("counterfactual_fingerprint is required for ScenarioValidationContext")

    return ScenarioValidationContext(
        model_run_id=model_run_id,
        model_approval_fingerprint=model_approval_fingerprint,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
        planning_objective=planning_objective,
        outcome_definitions=tuple(outcome_definitions) if outcome_definitions else (),
        outcome_approvals=tuple(outcome_approvals) if outcome_approvals else (),
        counterfactual_fingerprint=counterfactual_fingerprint,
        value_mapping_fingerprint=kwargs.get("value_mapping_fingerprint"),
        currency_context_fingerprint=kwargs.get("currency_context_fingerprint"),
        activity_fingerprint=kwargs.get("activity_fingerprint"),
        cost_fingerprint=kwargs.get("cost_fingerprint"),
        nbt_completeness_metadata=kwargs.get("nbt_completeness_metadata"),
    )


# ---------------------------------------------------------------------------
# Planning objective
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanningObjective:
    """Typed objective and estimand stored with every scenario.

    G2A.7 (REQ-PLAN-001): no business metric may be the dataclass default.
    `metric_key` and `target_outcome_ids` must be set explicitly by the
    caller. An empty or missing `metric_key` fails official planning
    validation; it does not silently default to NBT, GSA, or any other KPI."""

    estimand: str = "incremental_outcome"
    metric_key: str = ""
    target_outcome_ids: Tuple[str, ...] = ()
    weight_by_outcome_id: Optional[Mapping[str, float]] = None

    def __post_init__(self) -> None:
        valid_estimands = {"total_outcome", "incremental_outcome", "incremental_value", "weighted_mix"}
        if self.estimand not in valid_estimands:
            raise ValueError(f"Unknown estimand: {self.estimand!r}; must be one of {valid_estimands}")

    @property
    def is_valid_for_official_planning(self) -> bool:
        return bool(self.metric_key and self.target_outcome_ids)

    def fingerprint(self) -> str:
        payload = {
            "estimand": self.estimand,
            "metric_key": self.metric_key,
            "target_outcome_ids": sorted(self.target_outcome_ids) if self.target_outcome_ids else [],
            "weight_by_outcome_id": dict(sorted(self.weight_by_outcome_id.items())) if self.weight_by_outcome_id else {},
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return {
            "estimand": self.estimand,
            "metric_key": self.metric_key,
            "target_outcome_ids": list(self.target_outcome_ids),
            "weight_by_outcome_id": dict(self.weight_by_outcome_id) if self.weight_by_outcome_id else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlanningObjective":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        weights = payload.get("weight_by_outcome_id")
        if weights is not None and not isinstance(weights, dict):
            weights = dict(weights)
            payload = {**payload, "weight_by_outcome_id": weights}
        return cls(**payload)


# ---------------------------------------------------------------------------
# Scenario dependency issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioDependencyIssue:
    """Describes a single dependency mismatch found during scenario
    validation."""
    category: str
    field: str
    message: str
    severity: str = "error"  # "error" or "warning"
