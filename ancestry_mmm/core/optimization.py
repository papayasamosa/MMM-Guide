"""
Scenario planning and budget optimisation for the joint hierarchical FH model.

Three modes, matching how Ancestry actually plans budgets rather than just
producing a mathematically optimal split:

- Manual: edit spend directly, see predicted outcomes update (evaluate_scenario).
- Constrained: optimise subject to locked cells, fixed channel/month totals,
  bounded movement from the current plan, and minimum-spend floors
  (optimize_scenario with constraints).
- Unconstrained benchmark: optimise the same total budget with none of the
  above constraints - a theoretical-optimum comparison point, not a plan.

All three evaluate expected outcomes with the steady-state response
approximation in core.predict (see that module's docstring): spend held
constant within a month is treated as having reached its adstock
steady-state, so a month's expected outcome is a closed-form function of
that month's channel spend - no MCMC in the optimisation loop.

Works against either model type (Phase 3c) via `model_type`: `"shared"`
(Model A, the default - `steady_state_outcome_response`, `params` an
`FHPosteriorParams`) or `"market_specific"` (Model C -
`steady_state_outcome_response_market_specific`, `params` an
`FHMarketSpecificPosteriorParams`). Both functions have the identical
`(market, spend_by_channel, meta, params, reference_context) -> {outcome_id:
rate}` contract - `market` already selects the right market-specific
baseline/K/beta for Model C the same way it already selected the right
market baseline for Model A - so nothing else in this module's planning
math (constraints, bounds, the optimiser objective) needs to know which
model type it's driving.

evaluate_scenario and optimize_scenario are the core planning entry points,
and both require a ModelApproval that matches the exact model run supplying
`meta`/`params` (model_run_id plus data/spec/posterior fingerprints - see
core.fingerprint and core.approval). This is enforced here, not only by the
Streamlit Scenario Planner page's own checks, so a direct call to either
function - bypassing the page - still requires a valid, matching approval.

Kept from the original single-KPI implementation for reuse:
calculate_marginal_roi_loglog, optimize_budget_marginal_roi, calculate_expected_lift.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import warnings
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Tuple,
    Union,
    cast,
)

if TYPE_CHECKING:
    from .validation_policy import ApprovalReadiness, ThresholdPolicy
    from .optimization_constraint_vocabulary import GovernedSpendConstraint
    from .capacity import CapacityLimitDefinition
    from .sequential_optimisation_tractability import SequentialOptimisationContext

import numpy as np
import pandas as pd
from scipy.optimize import minimize, LinearConstraint

from .approval import ModelApproval, require_matching_approval
from .activities import (
    ActivityDefinition,
    activity_by_model_input,
    activity_definitions_fingerprint,
)
from .hierarchical_model import FHModelMeta
from .media_costs import CostMappingRegistry
from .outcomes import (
    fh_gsa_outcome_ids,
    fh_signup_outcome_ids,
    fh_net_billthrough_outcome_ids,
    dna_kit_sale_outcome_ids,
    select_outcome_ids,
    outcome_catalogue_at_fit_by_id,
    eligible_outcome_ids,
    METRIC_KEY_FH_GSA,
    METRIC_KEY_FH_SIGNUP,
    METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    METRIC_KEY_DNA_KIT_SALE,
)
from .outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    PlanningGovernanceError,
)
from .predict import FHPosteriorParams, steady_state_outcome_response
from .market_specific_predict import (
    FHMarketSpecificPosteriorParams,
    steady_state_outcome_response_market_specific,
)
from .scenario_governance import (
    CounterfactualPolicy,
    ScenarioPlan,
    classify_activity_plan,
    resolve_counterfactual,
    resolve_scenario_plan,
)

# PR 5: Pure value objects moved to core/planning/value.py
# Re-exported here for backward compatibility.
# Note: ObjectiveMissingError is defined locally in this file for
# backward compatibility (it references PlanningGovernanceError).
from .planning import (
    AdstockState,  # noqa: F401 — re-exported for scenario governance callers
    CurrencyContext,
    CURRENT_PLANNING_EVALUATION_SEMANTICS,
    SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS,
    OutcomeValueMapping,
    PlanningEvaluationSemantics,  # noqa: F401 — re-exported for scenario governance callers
    PlanningObjective,
    ResolvedOutcomeAuthorisation,  # noqa: F401 — re-exported for planning_governance.py
    ResolvedPlanningGovernance,
    ScenarioDependencyIssue,
    ScenarioEvaluationResult,
    ScenarioGovernanceDependencies,
    ScenarioValidationContext,
    planning_objective_from_legacy,
    validation_context_from_legacy_args,  # noqa: F401 — re-exported for persistence.py
    zero_carry_in_adstock_state,  # noqa: F401 — re-exported for scenario governance callers
)

WEEKS_PER_MONTH = 365.25 / 12 / 7  # ~4.348

AnyPosteriorParams = Union[FHPosteriorParams, FHMarketSpecificPosteriorParams]

# WP5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): every currently-
# approved evaluation engine's PlanningEvaluationSemantics fingerprint - see
# validate_scenario_dependencies's planning_semantics_fingerprint check
# below. Add a new engine's constant here (never remove an existing one
# without a migration) when a further evaluation engine is approved.
_CURRENT_PLANNING_SEMANTICS_FINGERPRINTS = frozenset(
    {
        CURRENT_PLANNING_EVALUATION_SEMANTICS.fingerprint(),
        SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS.fingerprint(),
    }
)


def _is_nbt_outcome(outcome_id: str, meta: object) -> bool:
    """Check if an outcome ID is a Net Bill-Through outcome in the given model meta."""
    try:
        catalogue = outcome_catalogue_at_fit_by_id(meta)
        if outcome_id in catalogue:
            from .outcomes import METRIC_KEY_FH_NET_BILLTHROUGH_COUNT

            return (
                getattr(catalogue[outcome_id], "metric_key", None)
                == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
            )
    except (AttributeError, KeyError, TypeError):
        pass
    return outcome_id.startswith("fh_nbt")


def _resolve_nbt_completeness_fingerprint(
    nbt_completeness_metadata: dict | None,
    *,
    fail_closed: bool = False,
) -> str | None:
    """Resolve the real NBT completeness-record fingerprint from metadata.

    Uses ``NetBillthroughCompletenessMetadata.from_dict`` to normalise the
    payload and ``completeness_fingerprint()`` to fingerprint the complete
    canonical metadata — not the outcome-definition fingerprint, which is
    a separate object (REQ-NBT-001).

    When ``fail_closed=True``, raises ``PlanningGovernanceError`` if
    metadata is absent or cannot be parsed (official mode). When
    ``fail_closed=False`` (exploratory mode), returns None."""
    if nbt_completeness_metadata is None:
        if fail_closed:
            from .outcome_approval import PlanningGovernanceError

            raise PlanningGovernanceError(
                "NBT completeness metadata is required for official "
                "planning or optimisation but was not provided."
            )
        return None
    try:
        from .net_billthrough import NetBillthroughCompletenessMetadata

        metadata = NetBillthroughCompletenessMetadata.from_dict(
            nbt_completeness_metadata
        )
        return metadata.completeness_fingerprint()
    except (TypeError, ValueError) as exc:
        if fail_closed:
            from .outcome_approval import PlanningGovernanceError

            raise PlanningGovernanceError(
                f"NBT completeness metadata is malformed: {exc}"
            )
        return None


# Import PLANNING_ESTIMANDS from the canonical planning package.


# ---------------------------------------------------------------------------
# ObjectiveMissingError — kept locally because it references
# PlanningGovernanceError, which would create a circular import if moved.
# ---------------------------------------------------------------------------


class ObjectiveMissingError(PlanningGovernanceError):
    """Official planning/optimisation requires an explicit objective."""

    # Not a subclass of OutcomeApprovalBlockedError because it is raised
    # before any approval check runs — the objective is missing regardless
    # of whether approvals exist.


class GovernedConstraintInfeasibleError(PlanningGovernanceError):
    """`optimize_scenario(governed_constraints=...)` (`REQ-OPT-001`
    Requirement 5, Decision 16): one or more governed constraint cells
    resolved to a lower bound exceeding the upper bound. Raised before the
    (potentially slow) SLSQP call runs — an infeasible cell is reported
    explicitly, never silently clamped, dropped, or left to produce a
    confusing/wrong optimiser result."""


class CapacityLimitInfeasibleError(PlanningGovernanceError):
    """`optimize_scenario(capacity_limits=...)` (`REQ-CAP-001`/`REQ-OPT-001`
    Requirement 4, Decision 18): applying one or more `CapacityLimitDefinition`
    bounds-tightenings on top of whatever the constraint vocabulary (legacy
    or governed) already produced resulted in a lower bound exceeding the
    upper bound for at least one cell. Raised before the SLSQP call runs -
    `core.capacity_plan_application.apply_capacity_limits_to_bounds` itself
    performs no feasibility check (it composes with whatever bounds it is
    given), so the composing caller (this function) is responsible for it."""


# ---------------------------------------------------------------------------
# G2A.7a.4: artefact kind — explicit scenario type, never inferred from
# constraints, names, or notes.
# ---------------------------------------------------------------------------

ARTEFACT_KINDS = frozenset(
    {
        "manual_scenario",
        "constrained_optimisation",
        "unconstrained_benchmark",
    }
)

# Required use per artefact kind — enforced by governance validation.
ARTEFACT_KIND_REQUIRED_USE: dict[str, str] = {
    "manual_scenario": "planning",
    "constrained_optimisation": "optimisation",
    "unconstrained_benchmark": "optimisation",
}


def classify_artefact_kind(
    constraints: list | None,
    *,
    explicit_kind: str | None = None,
) -> str:
    """Classify a scenario's artefact kind for a NEW official artefact.

    When ``explicit_kind`` is provided it is authoritative — never infer
    from constraints, names, or notes. If absent, raises: a new official
    artefact must state its kind explicitly (G2A.7a.10, brief section 13).
    ``scenario_from_dict``'s legacy-import path has its own separate
    inference that pairs with ``_migrated_from_schema``/``legacy_unverified``
    marking — this function is not used there."""
    if explicit_kind is not None:
        if explicit_kind not in ARTEFACT_KINDS:
            raise ValueError(
                f"Unknown artefact kind {explicit_kind!r}. "
                f"Must be one of {sorted(ARTEFACT_KINDS)}."
            )
        return explicit_kind
    # Legacy fallback: no explicit kind recorded.
    raise ValueError("artefact_kind must be explicitly provided; cannot infer.")


# ScenarioGovernanceDependencies imported from .planning.value
# (defined in ancestry_mmm/core/planning/value.py)


# ScenarioEvaluationResult imported from .planning.value


# OutcomeValueMapping imported from .planning.value
# (defined in ancestry_mmm/core/planning/value.py)


# CurrencyContext imported from .planning.value

# ScenarioValidationContext imported from .planning.value


# PlanningObjective imported from .planning.value
# planning_objective_from_legacy imported from .planning.value


def fingerprint_planning_objective(objective: PlanningObjective) -> str:
    """Deterministic SHA-256 fingerprint of a PlanningObjective.

    Uses canonical JSON (sorted keys, compact separators) — never
    ``repr()``, which is implementation-defined and unstable. This is
    the single fingerprint function used everywhere, including resolved
    governance and saved scenario dependencies."""
    payload = objective.to_dict()
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# ---------------------------------------------------------------------------
# G2A.7a.4: expected-value objective resolution
# ---------------------------------------------------------------------------


def resolve_planning_objective(
    *,
    objective_kind: str,
    meta: FHModelMeta,
    operation: Literal["planning", "optimisation"],
    ltv: Optional[Mapping[str, float]] = None,
    value_currency: Optional[str] = None,
    counterfactual_policy_fingerprint: Optional[str] = None,
    value_weights_by_outcome_id: Optional[Mapping[str, float]] = None,
) -> PlanningObjective:
    """Resolve a typed PlanningObjective from an objective kind string.

    For expected-value optimisation, every target must have:
    - value eligibility (include_in_value = True)
    - optimisation eligibility (include_in_optimisation = True)
    - fitted-model membership
    - a value weight in ``ltv``
    - compatible governed currency
    - optimisation approval

    Raises ``ValueError`` if targets cannot be resolved."""
    _objective_metric_keys = {
        "fh_net_billthrough": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        "fh_gsa": METRIC_KEY_FH_GSA,
        "fh_signups": METRIC_KEY_FH_SIGNUP,
        "dna_kits": METRIC_KEY_DNA_KIT_SALE,
    }
    _objective_target_resolvers: dict = {
        "fh_gsa": lambda m: tuple(fh_gsa_outcome_ids(m)),
        "fh_signups": lambda m: tuple(fh_signup_outcome_ids(m)),
        "fh_net_billthrough": lambda m: tuple(fh_net_billthrough_outcome_ids(m)),
        "dna_kits": lambda m: tuple(dna_kit_sale_outcome_ids(m)),
    }

    if objective_kind in _objective_metric_keys:
        return PlanningObjective(
            estimand="incremental_outcome",
            metric_key=_objective_metric_keys[objective_kind],
            target_outcome_ids=_objective_target_resolvers[objective_kind](meta),
            counterfactual_policy_fingerprint=counterfactual_policy_fingerprint,
        )
    elif objective_kind in ("expected_value", "value"):
        # Use outcome-level weights as primary source, fall back to legacy segment LTV
        weights = (
            value_weights_by_outcome_id
            if value_weights_by_outcome_id is not None
            else ltv
        )
        if not weights:
            raise ValueError(
                "Expected-value objective requires value weights. "
                "Set a value weight for at least one outcome, "
                "or provide segment LTV as a fallback."
            )
        # Resolve value-eligible outcomes
        value_eligible = set(
            eligible_outcome_ids(
                meta,
                list(meta.outcome_ids),
                "include_in_value",
            )
        )
        # For optimisation, also require optimisation eligibility
        if operation == "optimisation":
            optim_eligible = set(
                eligible_outcome_ids(
                    meta,
                    list(meta.outcome_ids),
                    "include_in_optimisation",
                )
            )
            targets = tuple(sorted(value_eligible & optim_eligible))
        else:
            targets = tuple(sorted(value_eligible))

        if not targets:
            raise ValueError(
                f"No value-eligible{' and optimisation-eligible' if operation == 'optimisation' else ''} "
                "outcomes found in the fitted model."
            )
        # Verify every target has a value weight in the selected mapping
        missing_weights = [oid for oid in targets if oid not in weights]
        if missing_weights:
            raise ValueError(
                f"Expected-value objective: target outcomes {missing_weights} "
                "have no value weight. Set a value weight for every target outcome "
                "via the outcome catalogue or a legacy LTV migration."
            )
        # Verify currency compatibility
        # G2A.7a.6: accept a single real currency (e.g. "GBP"),
        # reject mixed currencies, reject missing for expected_value
        if not value_currency:
            raise ValueError(
                "Expected-value objective requires a governed currency. "
                "All target outcomes must share one currency."
            )
        # Single currency is valid; multiple currencies block
        # (handled by the caller ensuring all outcomes share one currency)
        return PlanningObjective(
            estimand="incremental_value",
            metric_key="expected_value",
            target_outcome_ids=targets,
            value_currency=value_currency,
            counterfactual_policy_fingerprint=counterfactual_policy_fingerprint,
        )
    else:
        raise ValueError(
            f"Unknown objective kind {objective_kind!r}. "
            f"Must be one of {sorted(_objective_metric_keys)} or 'expected_value'."
        )


# ---------------------------------------------------------------------------
# ScenarioDependencyIssue imported from .planning.value


def validate_scenario_dependencies(
    scenario: dict,
    *,
    context: Optional[ScenarioValidationContext] = None,
    current_model_run_id: Optional[str] = None,
    current_data_fingerprint: Optional[str] = None,
    current_model_spec_fingerprint: Optional[str] = None,
    current_posterior_fingerprint: Optional[str] = None,
    current_planning_objective: Optional[PlanningObjective] = None,
    current_activity_fingerprint: Optional[str] = None,
    current_cost_fingerprint: Optional[str] = None,
    current_counterfactual_fingerprint: Optional[str] = None,
    current_nbt_completeness_fingerprint: Optional[str] = None,
    current_model_identity: Optional[dict] = None,
    current_model_approval: Optional[dict] = None,
    current_outcome_definitions: Optional[list] = None,
    current_outcome_approvals: Optional[list] = None,
) -> List[ScenarioDependencyIssue]:
    """Validate a saved scenario's governance dependencies against the
    current project state.

    Returns a list of `ScenarioDependencyIssue` objects — one per
    detected staleness or invalidity. An empty list means the scenario
    is ``current``.

    Required states:
    - ``current``: all dependencies match the current state.
    - ``stale``: at least one calculation-relevant dependency (objective,
      model identity, posterior, outcome definition, approval) has changed.
    - ``legacy_unverified``: old schema version with no validation
      metadata (migrated by adding null fields).
    - ``exploratory``: scenario was created in exploratory mode; no
      governance dependency checking applies.
    - ``invalid``: a required dependency is missing or malformed.

    G2A.7a.4: validates ``_migrated_from_schema`` for legacy detection,
    checks ``model_approval_fingerprint``, and validates saved approval
    IDs, status, expiry, use, and scope against current definitions.
    """
    issues: List[ScenarioDependencyIssue] = []
    current_model_approval_fingerprint: Optional[str] = None

    # G2A.7a.9: ScenarioValidationContext is authoritative for official
    # validation. When context is provided, it supplies ALL current values
    # and the individual legacy params are ignored — no ambiguous merging.
    # When context is None and governance_mode is "official", the validation
    # still works from individual params for backward compatibility, but
    # callers are expected to migrate to the context-based API.
    if context is not None:
        current_model_run_id = context.model_run_id
        current_model_approval_fingerprint = context.model_approval_fingerprint
        current_data_fingerprint = context.data_fingerprint
        current_model_spec_fingerprint = context.model_spec_fingerprint
        current_posterior_fingerprint = context.posterior_fingerprint
        current_planning_objective = context.planning_objective
        current_outcome_definitions = context.outcome_definitions
        current_outcome_approvals = (
            list(context.outcome_approvals) if context.outcome_approvals else None
        )
        current_activity_fingerprint = context.activity_fingerprint
        current_cost_fingerprint = context.cost_fingerprint
        current_counterfactual_fingerprint = context.counterfactual_fingerprint
        current_nbt_completeness_fingerprint = (
            _resolve_nbt_completeness_fingerprint(
                context.nbt_completeness_metadata,
                fail_closed=True,
            )
            if context.nbt_completeness_metadata
            else None
        )

    schema_ver = scenario.get("schema_version", 1)
    deps = scenario.get("governance_dependencies") or {}
    governance_mode = scenario.get("governance_mode", "exploratory")
    artefact_kind = scenario.get("artefact_kind")
    migrated_from = scenario.get("_migrated_from_schema")

    if governance_mode != "official":
        # Exploratory scenarios don't need governance dependency validation
        return issues

    # G2A.7a.4: check _migrated_from_schema — a migrated record with
    # null fields is legacy_unverified, never current. PR 88B: threshold
    # bumped from 3 to 4 — schema 4 added planning_semantics_fingerprint.
    if migrated_from is not None and migrated_from < 4:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="legacy_unverified",
                detail=(
                    f"Scenario was migrated from schema version {migrated_from}. "
                    "Migration by adding null fields does not produce 'current' "
                    "status — re-save with explicit governance dependencies."
                ),
            )
        )
        return issues

    if schema_ver < 3:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="legacy_unverified",
                detail=(
                    f"Scenario schema version {schema_ver} predates governance "
                    "dependency tracking. Migration by adding null fields does "
                    "not produce 'current' status — re-save with explicit "
                    "governance dependencies."
                ),
            )
        )
        return issues

    # PR 88B: schema 3 scenarios have governance dependency tracking but
    # predate planning-semantics disclosure entirely (at most PR 82E's
    # adstock_state_fingerprint, which mischaracterised a steady-state
    # calculation as having a carry-in concept it does not model) - loadable,
    # but never officially current.
    if schema_ver < 4:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="legacy_unverified",
                detail=(
                    f"Scenario schema version {schema_ver} predates truthful "
                    "planning-evaluation-semantics disclosure (PR 88B). "
                    "Re-save to record the current planning semantics."
                ),
            )
        )
        return issues

    if not deps:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="invalid",
                detail="Governance dependencies block is empty or missing.",
            )
        )
        return issues

    # G2A.7a.4: validate artefact kind
    if artefact_kind not in ARTEFACT_KINDS:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="invalid",
                detail=f"Unknown or missing artefact kind: {artefact_kind!r}.",
            )
        )

    # G2A.7a.4: validate required use from artefact kind
    required_use = ARTEFACT_KIND_REQUIRED_USE.get(artefact_kind, "planning")
    saved_authorisations = deps.get("outcome_authorisations") or []
    for auth in saved_authorisations:
        if isinstance(auth, dict) and auth.get("requested_use") != required_use:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="invalid",
                    detail=(
                        f"Authorisation for outcome '{auth.get('outcome_id')}' "
                        f"has requested_use='{auth.get('requested_use')}' but "
                        f"artefact kind '{artefact_kind}' requires '{required_use}'."
                    ),
                )
            )

    # Model identity
    saved_run_id = deps.get("model_run_id")
    if saved_run_id is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'model_run_id' is missing.",
            )
        )
    elif current_model_run_id is not None and saved_run_id != current_model_run_id:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail=(
                    f"Model run changed from {saved_run_id} to {current_model_run_id}."
                ),
            )
        )

    # G2A.7a.4: validate model approval fingerprint
    saved_approval_fp = deps.get("model_approval_fingerprint")
    if saved_approval_fp is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'model_approval_fingerprint' is missing.",
            )
        )
    elif current_model_approval_fingerprint or current_model_approval:
        if not current_model_approval_fingerprint and current_model_approval:
            from .approval import ModelApproval, fingerprint_model_approval

            try:
                current_model_approval_fingerprint = fingerprint_model_approval(
                    ModelApproval.from_dict(current_model_approval)
                )
            except (TypeError, ValueError):
                pass
        if (
            current_model_approval_fingerprint
            and saved_approval_fp != current_model_approval_fingerprint
        ):
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="stale",
                    detail="Model approval fingerprint has changed.",
                )
            )

    saved_data_fp = deps.get("data_fingerprint")
    if saved_data_fp is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'data_fingerprint' is missing.",
            )
        )
    elif (
        current_data_fingerprint is not None
        and saved_data_fp != current_data_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Data fingerprint has changed.",
            )
        )

    saved_spec_fp = deps.get("model_spec_fingerprint")
    if saved_spec_fp is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'model_spec_fingerprint' is missing.",
            )
        )
    elif (
        current_model_spec_fingerprint is not None
        and saved_spec_fp != current_model_spec_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Model spec fingerprint has changed.",
            )
        )

    saved_post_fp = deps.get("posterior_fingerprint")
    if saved_post_fp is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'posterior_fingerprint' is missing.",
            )
        )
    elif (
        current_posterior_fingerprint is not None
        and saved_post_fp != current_posterior_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Posterior fingerprint has changed.",
            )
        )

    # Objective fingerprint
    saved_obj_fp = deps.get("planning_objective_fingerprint")
    if saved_obj_fp is None:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="missing",
                detail="Governance dependency 'planning_objective_fingerprint' is missing.",
            )
        )
    elif current_planning_objective is not None:
        current_obj_fp = fingerprint_planning_objective(current_planning_objective)
        if saved_obj_fp != current_obj_fp:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="stale",
                    detail="Planning objective fingerprint has changed.",
                )
            )

    # PR 88B: planning-evaluation-semantics fingerprint. Unlike the
    # (deprecated for steady-state) adstock_state_fingerprint, this IS an
    # actively validated dependency. A schema >= 4 scenario missing it is
    # legacy_unverified (it predates truthful semantics disclosure just as
    # much as a schema < 4 one would, e.g. one built through the legacy
    # inline-dict path in scenario_to_dict) rather than "invalid" - a
    # missing disclosure is a provenance gap, not malformed data. A
    # mismatched fingerprint (an unrecognised engine, or a changed
    # prediction_function_version for a recognised one) is stale.
    #
    # WP5 (`Media-Mix-Lab: Coding LLM Next Steps Post PR262`): this must
    # recognise EVERY currently-approved evaluation engine's semantics as
    # "current", not only the steady-state one - a sequential-weekly
    # scenario stamped with SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS
    # would otherwise appear permanently stale the moment it was saved, even
    # though nothing about it had actually changed. This was anticipated in
    # the comment above before the sequential engine existed ("a future
    # sequential engine... is stale") but never actually implemented as
    # engine-aware.
    saved_semantics_fp = deps.get("planning_semantics_fingerprint")
    if not saved_semantics_fp:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="legacy_unverified",
                detail=(
                    "Governance dependency 'planning_semantics_fingerprint' is "
                    "missing - scenario predates truthful planning-evaluation-"
                    "semantics disclosure (PR 88B)."
                ),
            )
        )
    elif saved_semantics_fp not in _CURRENT_PLANNING_SEMANTICS_FINGERPRINTS:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Planning evaluation semantics have changed since this scenario was created.",
            )
        )

    # Activity and cost fingerprints (only relevant for specific uses)
    saved_act_fp = deps.get("activity_definitions_fingerprint")
    if (
        current_activity_fingerprint is not None
        and saved_act_fp is not None
        and saved_act_fp != current_activity_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Activity definitions fingerprint has changed.",
            )
        )

    saved_cost_fp = deps.get("cost_mapping_fingerprint")
    if (
        current_cost_fingerprint is not None
        and saved_cost_fp is not None
        and saved_cost_fp != current_cost_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Cost mapping fingerprint has changed.",
            )
        )

    saved_cf_fp = deps.get("counterfactual_policy_fingerprint")
    if (
        current_counterfactual_fingerprint is not None
        and saved_cf_fp is not None
        and saved_cf_fp != current_counterfactual_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="Counterfactual policy fingerprint has changed.",
            )
        )

    saved_nbt_fp = deps.get("nbt_completeness_fingerprint")
    if (
        current_nbt_completeness_fingerprint is not None
        and saved_nbt_fp is not None
        and saved_nbt_fp != current_nbt_completeness_fingerprint
    ):
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="stale",
                detail="NBT completeness fingerprint has changed.",
            )
        )

    # Outcome authorisations — G2A.7a.9: complete validation with
    # canonical deserialisation, missing/duplicate detection, and
    # malformed-record rejection (never silently continue).
    if not saved_authorisations:
        issues.append(
            ScenarioDependencyIssue(
                artefact_id=scenario.get("name", "<unknown>"),
                issue_type="invalid",
                detail="No outcome authorisations recorded for this official scenario.",
            )
        )
    else:
        _artefact_id = scenario.get("name", "<unknown>")
        seen_outcome_ids: set = set()
        seen_approval_ids: set = set()
        for auth_idx, auth in enumerate(saved_authorisations):
            if not isinstance(auth, dict):
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="invalid",
                        detail=(
                            f"Saved authorisation at index {auth_idx} is not a "
                            f"valid dictionary (type={type(auth).__name__})."
                        ),
                        dependency_type="outcome_authorisation",
                        reason_code="malformed_authorisation",
                    )
                )
                continue
            auth_id = auth.get("approval_id", "<unknown>")
            auth_outcome = auth.get("outcome_id", "<unknown>")
            auth_use = auth.get("requested_use", required_use)

            # Reject duplicate IDs
            if auth_id in seen_approval_ids:
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="invalid",
                        detail=f"Duplicate approval ID '{auth_id}' in saved authorisations.",
                        dependency_type="outcome_authorisation",
                        reason_code="duplicate_approval_id",
                    )
                )
            seen_approval_ids.add(auth_id)

            if auth_outcome and auth_outcome in seen_outcome_ids:
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="invalid",
                        detail=f"Duplicate outcome ID '{auth_outcome}' in saved authorisations.",
                        dependency_type="outcome_authorisation",
                        reason_code="duplicate_outcome_id",
                    )
                )
            seen_outcome_ids.add(auth_outcome)

            if current_outcome_approvals is None:
                continue

            # Find matching current approval by ID
            from .outcome_approval import OutcomeApproval

            matching_current = [
                a
                for a in current_outcome_approvals
                if isinstance(a, dict) and a.get("approval_id") == auth_id
            ]
            if not matching_current:
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=(
                            f"Saved approval '{auth_id}' for outcome "
                            f"'{auth_outcome}' no longer exists in current approvals."
                        ),
                        dependency_type="outcome_approval",
                        reason_code="approval_not_found",
                    )
                )
                continue

            try:
                current_approval = OutcomeApproval.from_dict(matching_current[0])
            except (TypeError, ValueError, KeyError, AttributeError) as exc:
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="invalid",
                        detail=f"Approval '{auth_id}' record is malformed: {exc}.",
                        dependency_type="outcome_approval",
                        reason_code="approval_malformed",
                    )
                )
                continue

            # Verify status
            if current_approval.status != "approved":
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=(
                            f"Approval '{auth_id}' status is "
                            f"'{current_approval.status}', not 'approved'."
                        ),
                        dependency_type="outcome_approval",
                        reason_code="approval_not_approved",
                    )
                )

            # Verify active
            if not current_approval.is_active():
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=f"Approval '{auth_id}' is not active (expired or future-dated).",
                        dependency_type="outcome_approval",
                        reason_code="approval_not_active",
                    )
                )

            # Verify requested use
            if auth_use and not current_approval.allows_use(auth_use):
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=(
                            f"Approval '{auth_id}' does not allow "
                            f"required use '{auth_use}'."
                        ),
                        dependency_type="outcome_approval",
                        reason_code="approval_use_not_allowed",
                    )
                )

            # Verify scope (market, product, segment)
            auth_market = auth.get("market")
            auth_product = auth.get("product")
            auth_segment = auth.get("segment")
            if not current_approval.matches_scope(
                market=auth_market,
                product=auth_product,
                segment=auth_segment,
            ):
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=(
                            f"Approval '{auth_id}' scope does not cover "
                            f"market={auth_market}, product={auth_product}, "
                            f"segment={auth_segment}."
                        ),
                        dependency_type="outcome_approval",
                        reason_code="approval_scope_mismatch",
                    )
                )

            # G2A.7a.9: canonical outcome definition deserialisation before
            # fingerprinting. Raw dicts are deserialised to OutcomeDefinition;
            # missing current definitions block rather than skipping silently.
            if current_outcome_definitions is not None and auth_outcome:
                from .outcome_approval import (
                    OutcomeDefinition,
                    fingerprint_outcome_definition,
                )

                matching_defns = [
                    d
                    for d in current_outcome_definitions
                    if isinstance(d, dict) and d.get("outcome_id") == auth_outcome
                ]
                if not matching_defns:
                    issues.append(
                        ScenarioDependencyIssue(
                            artefact_id=_artefact_id,
                            issue_type="invalid",
                            detail=(
                                f"Current outcome definition for '{auth_outcome}' "
                                "not found — cannot verify saved authorisation."
                            ),
                            dependency_type="outcome_definition",
                            reason_code="current_definition_not_found",
                        )
                    )
                elif len(matching_defns) > 1:
                    issues.append(
                        ScenarioDependencyIssue(
                            artefact_id=_artefact_id,
                            issue_type="invalid",
                            detail=(
                                f"Duplicate current definitions for outcome "
                                f"'{auth_outcome}' — expected exactly one."
                            ),
                            dependency_type="outcome_definition",
                            reason_code="duplicate_current_definitions",
                        )
                    )
                else:
                    try:
                        current_definition = OutcomeDefinition.from_dict(
                            matching_defns[0]
                        )
                        current_def_fp = fingerprint_outcome_definition(
                            current_definition
                        )
                    except (TypeError, ValueError, KeyError, AttributeError) as exc:
                        issues.append(
                            ScenarioDependencyIssue(
                                artefact_id=_artefact_id,
                                issue_type="invalid",
                                detail=(
                                    f"Current outcome definition for "
                                    f"'{auth_outcome}' is malformed and cannot "
                                    f"be deserialised: {exc}."
                                ),
                                dependency_type="outcome_definition",
                                reason_code="definition_deserialisation_failed",
                            )
                        )
                        continue

                    saved_def_fp = auth.get("definition_fingerprint")
                    if saved_def_fp and saved_def_fp != current_def_fp:
                        issues.append(
                            ScenarioDependencyIssue(
                                artefact_id=_artefact_id,
                                issue_type="stale",
                                detail=(
                                    f"Outcome '{auth_outcome}' definition has changed "
                                    f"(saved fingerprint '{saved_def_fp[:16]}...', "
                                    f"current '{current_def_fp[:16]}...')."
                                ),
                                dependency_type="outcome_definition",
                                reason_code="definition_fingerprint_mismatch",
                            )
                        )

            # Verify approval definition fingerprint
            saved_fp = auth.get("definition_fingerprint")
            if saved_fp and saved_fp != current_approval.definition_fingerprint:
                issues.append(
                    ScenarioDependencyIssue(
                        artefact_id=_artefact_id,
                        issue_type="stale",
                        detail=(
                            f"Approval '{auth_id}' definition fingerprint has changed "
                            f"(saved '{saved_fp[:16]}...', current "
                            f"'{current_approval.definition_fingerprint[:16]}...')."
                        ),
                        dependency_type="outcome_approval",
                        reason_code="approval_fingerprint_mismatch",
                    )
                )

    # G2A.7a.10: validate value-mapping and currency-context identity
    # symmetrically. Whether a dependency is *required* is determined from
    # the saved scenario's own planning objective (an expected-value
    # objective always needs a value mapping and a currency) - never from
    # whether the current context happens to supply a value. The previous
    # `context is not None and context.X_fingerprint is not None` guard
    # silently skipped the whole check whenever the current side omitted
    # the field, even though the saved scenario had a real one on record -
    # a fail-open hole for exactly the dependency official value/currency
    # planning most needs to trust.
    saved_planning_objective = scenario.get("planning_objective") or {}
    requires_value_and_currency = (
        saved_planning_objective.get("estimand") == "incremental_value"
    )

    saved_value_mapping_fp = deps.get("value_mapping_fingerprint")
    if requires_value_and_currency or saved_value_mapping_fp:
        if not saved_value_mapping_fp:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="invalid",
                    detail=(
                        "This scenario's objective requires a value mapping, "
                        "but no 'value_mapping_fingerprint' governance "
                        "dependency was saved."
                    ),
                    dependency_type="value_mapping",
                    reason_code="missing_value_mapping_fingerprint",
                )
            )
        elif context is None or context.value_mapping_fingerprint is None:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="invalid",
                    detail=(
                        "Saved scenario has a value mapping on record, but the "
                        "current project supplies no current value mapping to "
                        "verify it against."
                    ),
                    dependency_type="value_mapping",
                    reason_code="missing_current_value_mapping",
                )
            )
        elif saved_value_mapping_fp != context.value_mapping_fingerprint:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="stale",
                    detail="Value mapping fingerprint has changed.",
                    dependency_type="value_mapping",
                    reason_code="value_mapping_stale",
                )
            )

    saved_currency_context_fp = deps.get("currency_context_fingerprint")
    if requires_value_and_currency or saved_currency_context_fp:
        if not saved_currency_context_fp:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="invalid",
                    detail=(
                        "This scenario's objective requires a currency context, "
                        "but no 'currency_context_fingerprint' governance "
                        "dependency was saved."
                    ),
                    dependency_type="currency_context",
                    reason_code="missing_currency_context_fingerprint",
                )
            )
        elif context is None or context.currency_context_fingerprint is None:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="invalid",
                    detail=(
                        "Saved scenario has a currency context on record, but "
                        "the current project supplies no current currency "
                        "context to verify it against."
                    ),
                    dependency_type="currency_context",
                    reason_code="missing_current_currency_context",
                )
            )
        elif saved_currency_context_fp != context.currency_context_fingerprint:
            issues.append(
                ScenarioDependencyIssue(
                    artefact_id=scenario.get("name", "<unknown>"),
                    issue_type="stale",
                    detail="Currency context fingerprint has changed.",
                    dependency_type="currency_context",
                    reason_code="currency_context_stale",
                )
            )

    return issues


def scenario_dependency_status(
    scenario: dict,
    context: Optional[ScenarioValidationContext] = None,
    **current_kwargs,
) -> str:
    """Convenience wrapper that returns a single status string for a
    scenario based on its governance dependencies.

    Returns one of: ``current``, ``stale``, ``legacy_unverified``,
    ``exploratory``, ``invalid``.

    G2A.7a.4: checks ``_migrated_from_schema`` before governance_mode,
    so legacy scenarios without explicit ``official`` mode still return
    ``legacy_unverified`` rather than ``exploratory``."""
    # Check for legacy migration first — a migrated record is never
    # exploratory even if governance_mode is missing. PR 88B: threshold
    # bumped from 3 to 4 alongside validate_scenario_dependencies above.
    migrated_from = scenario.get("_migrated_from_schema")
    if migrated_from is not None and migrated_from < 4:
        return "legacy_unverified"
    governance_mode = scenario.get("governance_mode", "exploratory")
    if governance_mode != "official":
        return "exploratory"
    issues = validate_scenario_dependencies(
        scenario,
        context=context,
        **current_kwargs,
    )
    if not issues:
        return "current"
    for issue in issues:
        if issue.issue_type == "legacy_unverified":
            return "legacy_unverified"
        if issue.issue_type == "invalid" or issue.issue_type == "missing":
            return "invalid"
    return "stale"


@dataclass(frozen=True)
class OptimizationResource:
    """A single conserved optimisation resource - the unit the solver is
    allowed to trade decision variables against. `eligible_activity_ids`
    scopes which activities may move as part of this resource; every other
    activity in the plan is held fixed for the duration of an optimisation
    run against this resource, regardless of its own `planning_eligibility`.
    Prevents the historical defect of summing GBP spend, impressions, GRPs
    and CRM sends into one flat vector and conserving their numerical total
    (docs/g2a5_scenario_governance.md's dimensional-correctness gap)."""

    resource_id: str
    unit: str
    currency: Optional[str] = None
    eligible_activity_ids: Tuple[str, ...] = ()
    total: Optional[float] = None
    schema_version: int = 1

    def to_dict(self) -> dict:
        values = asdict(self)
        values["eligible_activity_ids"] = list(self.eligible_activity_ids)
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, object]) -> "OptimizationResource":
        payload = dict(values)
        payload["eligible_activity_ids"] = tuple(
            payload.get("eligible_activity_ids") or ()
        )
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def _resolved_currency_by_activity(
    candidates: Mapping[str, ActivityDefinition],
    market: str,
    cost_mapping_registry: Optional[CostMappingRegistry],
    cost_context_id: str,
    cost_as_of_dates: Optional[List[Optional[str]]],
) -> Dict[str, str]:
    """Effective mapping currency for each candidate, required to resolve
    to the exact same currency at every date in `cost_as_of_dates` - e.g.
    every period a multi-month plan spans, not just the first. A plan can
    cross a mapping's effective-date boundary, so checking only one date
    would miss a channel that is GBP in month one and USD (or unmapped) in
    a later month while the solver still sums every month's decisions into
    one conserved total. An activity that is unresolvable, or resolves to
    more than one currency, at any checked date is absent from the result
    - callers treat that as "unresolvable", never as an implicit match."""
    if cost_mapping_registry is None:
        return {}
    dates = list(dict.fromkeys(cost_as_of_dates)) if cost_as_of_dates else [None]
    resolved: Dict[str, str] = {}
    for activity_id, definition in candidates.items():
        currencies_at_each_date = set()
        fully_resolvable = True
        for as_of in dates:
            mapping = cost_mapping_registry.resolve(
                market,
                definition.channel,
                cost_context_id,
                as_of=as_of,
            )
            if mapping is None:
                fully_resolvable = False
                break
            currencies_at_each_date.add(mapping.currency)
        if fully_resolvable and len(currencies_at_each_date) == 1:
            resolved[activity_id] = next(iter(currencies_at_each_date))
    return resolved


def monetary_optimization_resource(
    activity_definitions: List[ActivityDefinition],
    market: str,
    *,
    resource_id: str = "monetary_budget",
    currency: Optional[str] = None,
    total: Optional[float] = None,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: str = "default",
    cost_as_of_dates: Optional[List[Optional[str]]] = None,
    channels: Optional[List[str]] = None,
) -> OptimizationResource:
    """Default resource: every cost-bearing, optimisable activity for this
    market that is denominated in one governed currency - the monetary
    budget a spend optimisation is allowed to move. Response-only
    quantities, controls, events, mediators and fixed/scenario-only
    activity are never included, whatever `planning_eligibility` they
    carry - they are not denominated in this resource's unit.

    `channels`, when given, restricts candidates to activities resolved
    from exactly those model-input channels - the specific decision
    variables of the optimisation this resource will drive - rather than
    every activity registered for this market in the wider governance
    system (which may include activities from other models or channels
    entirely). Omit only when building a resource independently of any
    particular `optimize_scenario` call.

    A resource must never silently pool decisions from more than one
    currency into one conserved total (the same currency-purity rule as
    `_validate_no_mixed_currency_value_weights`) - one USD must not be
    conserved as interchangeable with one GBP. When `cost_mapping_registry`
    is given, each candidate's effective mapping currency is resolved via
    `cost_context_id` at every date in `cost_as_of_dates` (e.g. every
    period a multi-month plan spans, not just the first - a plan can cross
    a mapping's effective-date boundary); a candidate with no resolvable
    mapping at any of those dates, or whose currency disagrees with the
    resource's currency or varies across them, is excluded rather than
    pooled in. If resolvable candidates span more than one currency and
    `currency` wasn't given explicitly, raises - the caller must state
    which currency this resource optimises. Without a
    `cost_mapping_registry`, currency cannot be checked and every
    cost-bearing optimisable activity is included as before (only safe when
    the caller has already validated currency purity itself)."""

    by_input = activity_by_model_input(activity_definitions, market)
    pool = (
        {channel: by_input[channel] for channel in channels if channel in by_input}
        if channels is not None
        else by_input
    )
    candidates = {
        definition.activity_id: definition
        for definition in pool.values()
        if definition.is_cost_bearing
        and definition.planning_eligibility == "optimisable"
    }
    if cost_mapping_registry is None:
        return OptimizationResource(
            resource_id=resource_id,
            unit="currency",
            currency=currency,
            eligible_activity_ids=tuple(sorted(candidates)),
            total=total,
        )

    currency_by_activity = _resolved_currency_by_activity(
        candidates,
        market,
        cost_mapping_registry,
        cost_context_id,
        cost_as_of_dates,
    )
    resolved_currencies = set(currency_by_activity.values())
    if currency is None:
        if len(resolved_currencies) > 1:
            raise ValueError(
                "cost-bearing activities resolve to more than one currency "
                f"({sorted(resolved_currencies)}) - pass an explicit "
                "currency= to select which one this resource optimises; a "
                "monetary resource must never pool decisions across "
                "currencies into one conserved total."
            )
        currency = next(iter(resolved_currencies), None)

    eligible = tuple(
        sorted(
            activity_id
            for activity_id, resolved in currency_by_activity.items()
            if resolved == currency
        )
    )
    return OptimizationResource(
        resource_id=resource_id,
        unit="currency",
        currency=currency,
        eligible_activity_ids=eligible,
        total=total,
    )


def validate_optimization_resource(
    resource: OptimizationResource,
    activity_definitions: List[ActivityDefinition],
    market: str,
    channels: List[str],
    *,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: str = "default",
    cost_as_of_dates: Optional[List[Optional[str]]] = None,
    governance_mode: str = "official",
) -> None:
    """Reject an `OptimizationResource` before it drives the solver.

    `monetary_optimization_resource`'s default output is already safe by
    construction; this exists because a caller may supply
    `optimize_scenario(optimization_resource=...)` directly, and that
    custom resource cannot be trusted to already respect the same rules
    (PR G2A.6b workstream 1). Raises ValueError, naming the resource and
    the offending activity ID(s), on:

    - a blank `unit`
    - duplicate activity IDs
    - no eligible activities at all (nothing for the solver to move)
    - an activity ID not registered anywhere in `activity_definitions`
    - an activity ID not among this optimisation's `channels`
    - an activity not applicable to `market`
    - an activity whose `planning_eligibility` is not `"optimisable"`
    - a non-cost-bearing activity in a `unit="currency"` resource
    - a cost-bearing activity in a resource whose `unit` is not
      `"currency"` - `optimize_scenario` always resolves a cost-bearing
      activity's plan cell as monetary regardless of the resource's
      declared unit, so this would silently mislabel and mis-conserve a
      currency decision as if it were denominated in something else
    - (when `cost_mapping_registry` is given) an activity with no
      resolvable effective mapping at every date in `cost_as_of_dates`
      (e.g. every period a multi-month plan spans, not just the first),
      or whose resolved currency varies across them or spans more than
      one currency overall
    - a non-finite or negative `total`
    - (PR G2A.6c workstream F, `governance_mode="official"` only) any
      activity resolved for this plan's `channels` - not only this
      resource's own eligible members - whose `approval_status` is not
      `"approved"`. A fixed or `scenario_only` activity is still part of
      the plan being predicted against (pinned to its current value, not
      removed), so a draft or rejected activity must not drive an official
      optimisation even when it never moves. Pass
      `governance_mode="exploratory"` for a clearly non-official run that
      skips this one check only; every other rule above still applies
      regardless of mode.
    """
    if governance_mode not in {"official", "exploratory"}:
        raise ValueError(
            f"governance_mode must be 'official' or 'exploratory', got {governance_mode!r}"
        )
    if not resource.unit:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} has a blank unit"
        )
    if len(set(resource.eligible_activity_ids)) != len(resource.eligible_activity_ids):
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} lists duplicate "
            f"activity IDs: {resource.eligible_activity_ids}"
        )
    if not resource.eligible_activity_ids:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} has no eligible "
            "activities - there is nothing for the solver to move under this "
            "resource. Check activity economic_treatment, planning_eligibility, "
            "and approved cost-mapping coverage."
        )
    if resource.total is not None and (
        not np.isfinite(resource.total) or resource.total < 0
    ):
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r}.total must be "
            "finite and non-negative"
        )

    by_input = activity_by_model_input(activity_definitions, market)
    # Built from the *unfiltered* `activity_definitions`, not `by_input`
    # (which `activity_by_model_input` already restricts to definitions
    # applicable to `market`) - otherwise an activity registered only for
    # a different market is invisible here, and the "not applicable to
    # market" check below can never fire; it would instead misreport as
    # "unknown activity ID". Prefers a definition that actually applies to
    # `market` when the same activity_id is somehow registered more than
    # once, falling back to any match so an activity with no
    # market-applicable definition still resolves to something (for a
    # clear "not applicable" error) rather than looking unknown.
    by_id: Dict[str, ActivityDefinition] = {}
    for definition in activity_definitions:
        by_id.setdefault(definition.activity_id, definition)
    for specificity in ("*", market):
        for definition in activity_definitions:
            if definition.market == specificity:
                by_id[definition.activity_id] = definition
    plan_activity_ids = {
        by_input[channel].activity_id for channel in channels if channel in by_input
    }

    unknown = [
        activity_id
        for activity_id in resource.eligible_activity_ids
        if activity_id not in by_id
    ]
    if unknown:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} references "
            f"unknown activity ID(s): {sorted(unknown)}"
        )

    # Checked before "not in plan channels": an activity registered only
    # for a different market is structurally invisible to
    # `activity_by_model_input(..., market)` (it can never resolve for any
    # of this market's channels), so it would always also fail the
    # plan-membership check below - naming the market mismatch first is
    # the more specific, more useful diagnosis.
    not_in_market = [
        activity_id
        for activity_id in resource.eligible_activity_ids
        if not by_id[activity_id].applies_to_market(market)
    ]
    if not_in_market:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} references "
            f"activity ID(s) not applicable to market {market!r}: "
            f"{sorted(not_in_market)}"
        )

    not_in_plan = [
        activity_id
        for activity_id in resource.eligible_activity_ids
        if activity_id not in plan_activity_ids
    ]
    if not_in_plan:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} references "
            "activity ID(s) not present among this optimisation's channels: "
            f"{sorted(not_in_plan)}"
        )

    not_optimisable = [
        activity_id
        for activity_id in resource.eligible_activity_ids
        if by_id[activity_id].planning_eligibility != "optimisable"
    ]
    if not_optimisable:
        raise ValueError(
            f"OptimizationResource {resource.resource_id!r} references "
            f"activity ID(s) that are not planning_eligibility='optimisable': "
            f"{sorted(not_optimisable)}"
        )

    if governance_mode == "official":
        # Every activity resolved for this plan's `channels`, not just this
        # resource's own eligible members - a fixed, scenario_only, or
        # otherwise non-eligible activity is still part of the plan
        # `optimize_scenario` predicts against (it's pinned to its current
        # value, not removed), so its model role, quantity assumption, and
        # response still influence an official optimisation even though it
        # never moves. Checking only `resource.eligible_activity_ids` would
        # let a draft or rejected fixed activity drive an official result
        # undetected.
        plan_activities_by_id = {
            by_input[channel].activity_id: by_input[channel]
            for channel in channels
            if channel in by_input
        }
        not_approved = sorted(
            activity_id
            for activity_id, definition in plan_activities_by_id.items()
            if definition.approval_status != "approved"
        )
        if not_approved:
            raise ValueError(
                f"OptimizationResource {resource.resource_id!r} is blocked in "
                "official mode - this optimisation's plan includes activity "
                f"ID(s) without approved governance: {not_approved} (every "
                "activity in the plan, not only this resource's own eligible "
                "members). Pass governance_mode='exploratory' for a clearly "
                "labelled non-official optimisation."
            )

    if resource.unit == "currency":
        not_cost_bearing = [
            activity_id
            for activity_id in resource.eligible_activity_ids
            if not by_id[activity_id].is_cost_bearing
        ]
        if not_cost_bearing:
            raise ValueError(
                f"OptimizationResource {resource.resource_id!r} is a "
                "currency resource but references non-cost-bearing "
                f"activity ID(s): {sorted(not_cost_bearing)}"
            )

        if cost_mapping_registry is not None:
            candidates = {
                activity_id: by_id[activity_id]
                for activity_id in resource.eligible_activity_ids
            }
            currency_by_activity = _resolved_currency_by_activity(
                candidates,
                market,
                cost_mapping_registry,
                cost_context_id,
                cost_as_of_dates,
            )
            unresolved = [
                activity_id
                for activity_id in resource.eligible_activity_ids
                if activity_id not in currency_by_activity
            ]
            if unresolved:
                raise ValueError(
                    f"OptimizationResource {resource.resource_id!r} "
                    "references activity ID(s) with no approved, effective "
                    f"cost mapping: {sorted(unresolved)}"
                )
            currencies = set(currency_by_activity.values())
            if resource.currency is not None:
                currencies.add(resource.currency)
            if len(currencies) > 1:
                raise ValueError(
                    f"OptimizationResource {resource.resource_id!r} spans "
                    f"more than one currency: {sorted(currencies)} - a "
                    "monetary resource must never pool decisions across "
                    "currencies into one conserved total."
                )
    else:
        # optimize_scenario resolves a cost-bearing activity's plan cell as
        # monetary purely from ActivityDefinition.is_cost_bearing, never
        # from a resource's declared unit - a non-currency resource
        # (e.g. unit="impressions") containing a cost-bearing activity
        # would have its `total` labelled and conserved as that unit while
        # the solver actually treats and converts it as currency.
        cost_bearing_in_non_currency = [
            activity_id
            for activity_id in resource.eligible_activity_ids
            if by_id[activity_id].is_cost_bearing
        ]
        if cost_bearing_in_non_currency:
            raise ValueError(
                f"OptimizationResource {resource.resource_id!r} has unit "
                f"{resource.unit!r} but references cost-bearing activity "
                f"ID(s): {sorted(cost_bearing_in_non_currency)} - "
                "optimize_scenario always resolves a cost-bearing "
                "activity's decisions as monetary regardless of the "
                "resource's declared unit, so a non-currency resource must "
                "never include one."
            )


def seed_monetary_and_quantity_defaults(
    *,
    avg_weekly_media_input: Mapping[str, float],
    activity_definitions: List[ActivityDefinition],
    market: str,
    cost_mapping_registry: Optional[CostMappingRegistry],
    cost_context_id: str = "default",
    as_of: Optional[str] = None,
    weeks_per_month: float = WEEKS_PER_MONTH,
) -> Tuple[Dict[str, float], List[str]]:
    """Seed a default monthly scenario plan from historical weekly model
    input, without reinterpreting a non-monetary model input as currency.

    Cost-bearing activities are converted through the governed cost
    mapping's `media_input_to_spend` (never assumed to already be spend);
    an activity with no resolvable effective mapping defaults to 0 rather
    than silently presenting a media-input quantity as a currency amount.
    Non-cost-bearing activities (response-only, not-applicable) are seeded
    directly from their historical model-input quantity, which is the
    correct unit for `activity_quantity_assumptions_by_period`.

    Returns `(defaults_by_channel, unmapped_cost_bearing_channels)` - the
    second list flags cost-bearing channels that were zero-defaulted for
    lack of an effective mapping, so a caller can surface that explicitly
    rather than let a silent zero look like a deliberate planning choice.
    """
    by_input = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions
        else {}
    )
    defaults: Dict[str, float] = {}
    unmapped: List[str] = []
    for channel, weekly_value in avg_weekly_media_input.items():
        definition = by_input.get(channel)
        if definition is None or not definition.is_cost_bearing:
            defaults[channel] = float(weekly_value) * weeks_per_month
            continue
        mapping = (
            cost_mapping_registry.resolve(
                market,
                definition.channel,
                cost_context_id,
                as_of=as_of,
            )
            if cost_mapping_registry is not None
            else None
        )
        if mapping is None:
            defaults[channel] = 0.0
            unmapped.append(channel)
            continue
        # Scale to the monthly media-input quantity *before* converting
        # through the mapping - a nonlinear mapping (e.g. piecewise-linear
        # marginal cost) does not commute with scaling, so
        # media_input_to_spend(weekly) * weeks_per_month is only correct
        # for a linear mapping and silently seeds the wrong monthly spend
        # for anything else.
        defaults[channel] = float(
            mapping.media_input_to_spend(float(weekly_value) * weeks_per_month)
        )
    return defaults, unmapped


def monetary_plan_to_media_input(
    spend_plan: Dict[str, Dict[str, float]],
    *,
    market: str,
    registry: CostMappingRegistry,
    cost_context_id: str,
    as_of_by_period: Dict[str, str],
) -> Dict[str, Dict[str, float]]:
    """Convert local-currency decisions through effective governed mappings."""

    converted: Dict[str, Dict[str, float]] = {}
    for period, channel_spend in spend_plan.items():
        if period not in as_of_by_period:
            raise ValueError(f"Missing cost-mapping date for period {period}")
        converted[period] = {}
        for channel, spend in channel_spend.items():
            mapping = registry.resolve(
                market,
                channel,
                cost_context_id,
                as_of=as_of_by_period[period],
            )
            if mapping is None:
                raise ValueError(
                    "Monetary planning blocked without an approved effective "
                    f"mapping for {market}/{channel}/{period}"
                )
            converted[period][channel] = float(mapping.spend_to_media_input(spend))
    return converted


def _steady_state_response_fn(model_type: str):
    if model_type not in ("shared", "market_specific"):
        raise ValueError(
            f"model_type must be 'shared' or 'market_specific', got {model_type!r}"
        )
    return (
        steady_state_outcome_response_market_specific
        if model_type == "market_specific"
        else steady_state_outcome_response
    )


def _require_planning_outcome_approvals(
    *,
    planning_objective: PlanningObjective,
    meta: FHModelMeta,
    outcome_approvals: Optional[List[OutcomeApproval]],
    requested_use: str = "planning",
    market: Optional[str] = None,
    nbt_completeness_metadata: Optional[dict] = None,
) -> None:
    """G2A.7a/.7a.1 gate (REQ-PLAN-001, REQ-USE-001, REQ-OUT-002, REQ-NBT-001):
    validate that every target outcome in a planning objective has a
    matching, active OutcomeApproval for the requested use, within the given
    market and the outcome's own product/segment scope. This is the single
    resolver both `evaluate_scenario` and `optimize_scenario` call - neither
    duplicates this logic, and both must pass the `requested_use` that
    actually matches what they are about to do ('planning' vs
    'optimisation') so a planning-only approval never authorises
    optimisation and vice versa.

    Called unconditionally in official mode — the objective must be complete
    (metric_key + target_outcome_ids non-empty) or this raises immediately.
    Uses `find_matching_outcome_approval` for multi-approval resolution.

    G2A.7a.1 (REQ-NBT-001, section 10): when a target's metric is Net
    Bill-Through, official use additionally requires `nbt_completeness_metadata`
    to reference the *same* outcome and pass its own internal-consistency
    checks - an approved definition alone is not sufficient for NBT."""
    if not planning_objective.metric_key:
        raise OutcomeApprovalBlockedError(
            "Official planning blocked: PlanningObjective has no metric_key. "
            "Select an explicit objective before official planning."
        )
    if not planning_objective.target_outcome_ids:
        raise OutcomeApprovalBlockedError(
            "Official planning blocked: PlanningObjective has no "
            "target_outcome_ids. Select at least one approved outcome "
            "explicitly before using this model for official planning."
        )
    catalogue_by_id = outcome_catalogue_at_fit_by_id(meta)
    if not catalogue_by_id:
        raise OutcomeApprovalBlockedError(
            "Official planning blocked: no outcome catalogue metadata "
            "available from the fitted model."
        )
    from .outcome_approval import find_matching_outcome_approval

    for target_id in planning_objective.target_outcome_ids:
        if target_id not in catalogue_by_id:
            raise OutcomeApprovalBlockedError(
                f"Official planning blocked: target outcome "
                f"'{target_id}' was not present in the fitted model."
            )
        outcome = catalogue_by_id[target_id]
        # G2A.7a: pass outcome's own product and segment for scope checking
        matching = find_matching_outcome_approval(
            outcome,
            outcome_approvals or [],
            requested_use,
            market=market,
            product=outcome.product,
            segment=outcome.segment,
        )
        if matching is None:
            raise OutcomeApprovalBlockedError(
                f"Official planning blocked: outcome '{target_id}' has no "
                f"active approval for '{requested_use}' "
                f"(market={market or 'any'}, product={outcome.product}, "
                f"segment={outcome.segment})."
            )
        if outcome.metric_key == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT:
            from .net_billthrough import validate_nbt_completeness_metadata_for_outcome

            nbt_issues = validate_nbt_completeness_metadata_for_outcome(
                outcome,
                nbt_completeness_metadata,
            )
            if nbt_issues:
                raise OutcomeApprovalBlockedError(
                    f"Official planning blocked: outcome '{target_id}' is "
                    "Net Bill-Through and requires both an approved "
                    "definition AND valid completeness metadata for "
                    f"'{requested_use}': {'; '.join(nbt_issues)}"
                )


# ---------------------------------------------------------------------------
# Scenario evaluation (manual mode)
# ---------------------------------------------------------------------------


def _calculate_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
) -> pd.DataFrame:
    """Private numerical scenario evaluation. Contains NO governance checks,
    NO approval resolution, NO operation parameter, and NO proof object.

    This is the single numerical core shared by all trusted service paths
    (``evaluate_manual_scenario``, ``optimize_scenario``, posterior
    evaluation). Callers must have resolved governance before invoking this.

    G2A.7a.9: extracted from ``evaluate_scenario`` to enforce the private
    numerical boundary."""
    response_fn = _steady_state_response_fn(model_type)
    ltv = ltv or {}
    gsa_ids = set(fh_gsa_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    nbt_ids = set(fh_net_billthrough_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    catalogue_by_id = outcome_catalogue_at_fit_by_id(meta)
    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )
    if activity_definitions is not None:
        missing_activity = set(meta.channels) - set(activity_map)
        if missing_activity:
            raise ValueError(
                f"Missing activity definitions for model inputs "
                f"{sorted(missing_activity)}"
            )
    activity_fingerprint = (
        activity_definitions_fingerprint(activity_definitions)
        if activity_definitions is not None
        else None
    )
    policy = counterfactual_policy or CounterfactualPolicy()
    if planning_objective is not None:
        if (
            planning_objective.counterfactual_policy_fingerprint
            and planning_objective.counterfactual_policy_fingerprint
            != policy.fingerprint()
        ):
            raise ValueError(
                "PlanningObjective counterfactual fingerprint does not match "
                "the supplied CounterfactualPolicy"
            )
    rows = []
    if scenario_plan is None and activity_definitions is not None:
        scenario_plan = classify_activity_plan(
            spend_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
    if scenario_plan is not None:
        model_input_plan, _, coverage = resolve_scenario_plan(
            scenario_plan,
            market=market,
            activity_definitions=activity_definitions,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id or "default",
            cost_as_of_by_period=cost_as_of_by_month,
        )
        monetary_plan = scenario_plan.monetary_decisions_by_period
        quantity_plan = scenario_plan.activity_quantity_assumptions_by_period
    else:
        model_input_plan = (
            monetary_plan_to_media_input(
                spend_plan,
                market=market,
                registry=cost_mapping_registry,
                cost_context_id=cost_context_id or "default",
                as_of_by_period=cost_as_of_by_month or {},
            )
            if cost_mapping_registry is not None
            else spend_plan
        )
        monetary_plan = spend_plan
        quantity_plan = {}
        coverage = {
            "economics_status": "legacy_monetary_assumption",
            "covered_activity_ids": [],
            "uncovered_activity_ids": [],
            "excluded_response_only_activity_ids": [],
            "mapping_ids": [],
            "mapping_effective_dates": [],
            "value_coverage": "evaluated_separately",
            "currency_coverage": "legacy_unspecified",
            "counterfactual_scope": policy.policy_id,
        }
        if activity_map:
            active_definitions = [
                activity_map[column]
                for values in spend_plan.values()
                for column, amount in values.items()
                if float(amount) != 0 and column in activity_map
            ]
            costed = sorted(
                {
                    item.activity_id
                    for item in active_definitions
                    if item.is_cost_bearing
                }
            )
            response_only = sorted(
                {
                    item.activity_id
                    for item in active_definitions
                    if item.economic_treatment == "response_only"
                }
            )
            coverage.update(
                {
                    "economics_status": (
                        "mixed_cost_and_response_only"
                        if costed and response_only
                        else "response_only"
                        if response_only
                        else "monetary_economics_available"
                    ),
                    "covered_activity_ids": costed,
                    "excluded_response_only_activity_ids": response_only,
                }
            )

    resolved_counterfactual = (
        counterfactual_media_input_by_month
        if counterfactual_media_input_by_month is not None
        else resolve_counterfactual(
            model_input_plan,
            market=market,
            activity_definitions=activity_definitions,
            policy=policy,
        )
    )

    def _scoped_counterfactual(
        month: str,
        treatment: str,
    ) -> dict[str, float]:
        values = dict(model_input_plan[month])
        for column, value in values.items():
            definition = activity_map.get(column)
            if (
                definition is not None
                and definition.economic_treatment == treatment
                and definition.model_role == "intervention"
                and definition.planning_eligibility == "optimisable"
            ):
                values[column] = 0.0
        return values

    def _period_costs(month: str) -> dict[str, float]:
        result = {
            "paid_media_cost": 0.0,
            "fully_loaded_cost": 0.0,
            "campaign_cost": 0.0,
        }
        for key, amount in monetary_plan.get(month, {}).items():
            definition = next(
                (
                    item
                    for item in activity_map.values()
                    if key
                    in {
                        item.activity_id,
                        item.resolved_model_input_column,
                        item.channel,
                    }
                ),
                None,
            )
            treatment = (
                definition.economic_treatment
                if definition is not None
                else "paid_media_cost"
            )
            if treatment in result:
                result[treatment] += float(amount)
        return result

    for month, media_input_by_activity in model_input_plan.items():
        ref = reference_context_by_month.get(month, {})
        weekly_rate = response_fn(
            market,
            media_input_by_activity,
            meta,
            params,
            ref,
            planning_only=True,
        )
        counterfactual_input = resolved_counterfactual[month]
        counterfactual_weekly_rate = response_fn(
            market,
            counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        paid_counterfactual_input = _scoped_counterfactual(month, "paid_media_cost")
        response_only_counterfactual_input = _scoped_counterfactual(
            month, "response_only"
        )
        paid_counterfactual_rates = response_fn(
            market,
            paid_counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        response_only_counterfactual_rates = response_fn(
            market,
            response_only_counterfactual_input,
            meta,
            params,
            ref,
            planning_only=True,
        )
        costs = _period_costs(month)
        paid_spend = costs["paid_media_cost"]
        fully_loaded_owned_spend = costs["fully_loaded_cost"]
        campaign_cost_spend = costs["campaign_cost"]
        total_spend = sum(costs.values())
        non_costed_ids = sorted(
            {
                definition.activity_id
                for key, value in quantity_plan.get(month, {}).items()
                if float(value) != 0
                for definition in activity_map.values()
                if key
                in {
                    definition.activity_id,
                    definition.resolved_model_input_column,
                    definition.channel,
                }
            }
        )
        monthly_outcome_by_id = {
            oid: rate * WEEKS_PER_MONTH for oid, rate in weekly_rate.items()
        }
        counterfactual_outcome_by_id = {
            oid: rate * WEEKS_PER_MONTH
            for oid, rate in counterfactual_weekly_rate.items()
        }
        incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid] - counterfactual_outcome_by_id[oid]
            for oid in monthly_outcome_by_id
        }
        paid_incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid]
            - paid_counterfactual_rates[oid] * WEEKS_PER_MONTH
            for oid in monthly_outcome_by_id
        }
        response_only_incremental_outcome_by_id = {
            oid: monthly_outcome_by_id[oid]
            - response_only_counterfactual_rates[oid] * WEEKS_PER_MONTH
            for oid in monthly_outcome_by_id
        }
        fh_gsa = sum(v for oid, v in monthly_outcome_by_id.items() if oid in gsa_ids)
        fh_signups = sum(
            v for oid, v in monthly_outcome_by_id.items() if oid in signup_ids
        )
        fh_net_billthrough = sum(
            v for oid, v in monthly_outcome_by_id.items() if oid in nbt_ids
        )
        dna_kits = sum(v for oid, v in monthly_outcome_by_id.items() if oid in dna_ids)
        incremental_fh_gsa = sum(
            v for oid, v in incremental_outcome_by_id.items() if oid in gsa_ids
        )
        incremental_fh_signups = sum(
            v for oid, v in incremental_outcome_by_id.items() if oid in signup_ids
        )
        incremental_fh_nbt = sum(
            v for oid, v in incremental_outcome_by_id.items() if oid in nbt_ids
        )
        incremental_dna_kits = sum(
            v for oid, v in incremental_outcome_by_id.items() if oid in dna_ids
        )
        paid_incremental_fh_gsa = sum(
            value
            for oid, value in paid_incremental_outcome_by_id.items()
            if oid in gsa_ids
        )
        paid_incremental_fh_nbt = sum(
            value
            for oid, value in paid_incremental_outcome_by_id.items()
            if oid in nbt_ids
        )
        avg_cpa = (
            (total_spend / incremental_fh_gsa)
            if incremental_fh_gsa > 0 and total_spend > 0
            else None
        )
        fh_signup_avg_cpa = (
            (total_spend / incremental_fh_signups)
            if incremental_fh_signups > 0
            else None
        )
        nbt_avg_cpa = (
            (total_spend / incremental_fh_nbt) if incremental_fh_nbt > 0 else None
        )
        dna_avg_cpa = (
            (total_spend / incremental_dna_kits) if incremental_dna_kits > 0 else None
        )
        paid_media_incremental_cpa = (
            paid_spend / paid_incremental_fh_gsa
            if paid_spend > 0 and paid_incremental_fh_gsa > 0
            else None
        )
        paid_media_incremental_nbt_cpa = (
            paid_spend / paid_incremental_fh_nbt
            if paid_spend > 0 and paid_incremental_fh_nbt > 0
            else None
        )

        priced_ids = sorted(oid for oid in monthly_outcome_by_id if oid in ltv)
        unpriced_ids = sorted(oid for oid in monthly_outcome_by_id if oid not in ltv)
        _validate_no_mixed_currency_value_weights(priced_ids, ltv, catalogue_by_id)
        if not priced_ids:
            # Either ltv is entirely omitted, or none of this month's
            # outcome_ids happen to be in it - either way there is nothing
            # priced to report as "value" this month.
            value_status = "not configured"
            total_value = None
            total_value_is_complete = False
        elif unpriced_ids:
            value_status = "partial"
            total_value = sum(
                monthly_outcome_by_id[oid] * ltv[oid] for oid in priced_ids
            )
            total_value_is_complete = False
        else:
            value_status = "complete"
            total_value = sum(
                monthly_outcome_by_id[oid] * ltv[oid] for oid in priced_ids
            )
            total_value_is_complete = True
        incremental_total_value = (
            sum(
                incremental_outcome_by_id[oid] * ltv[oid]
                for oid in incremental_outcome_by_id
            )
            if total_value_is_complete
            else None
        )
        paid_incremental_total_value = (
            sum(
                paid_incremental_outcome_by_id[oid] * ltv[oid]
                for oid in paid_incremental_outcome_by_id
            )
            if total_value_is_complete
            else None
        )
        whole_plan_incremental_roi = (
            incremental_total_value / total_spend
            if incremental_total_value is not None and total_spend > 0
            else None
        )
        paid_media_incremental_roi = (
            paid_incremental_total_value / paid_spend
            if paid_incremental_total_value is not None and paid_spend > 0
            else None
        )
        period_coverage = dict(coverage)
        period_coverage.update(
            {
                "counterfactual_scope": policy.policy_id,
                "non_costed_activity_ids": non_costed_ids,
                "whole_plan_scope_compatible": not any(
                    abs(value) > 1e-12
                    for value in response_only_incremental_outcome_by_id.values()
                ),
            }
        )
        if not period_coverage["whole_plan_scope_compatible"]:
            avg_cpa = None
            fh_signup_avg_cpa = None
            nbt_avg_cpa = None
            dna_avg_cpa = None
            whole_plan_incremental_roi = None

        for oid, monthly_outcome in monthly_outcome_by_id.items():
            value = monthly_outcome * ltv[oid] if oid in ltv else None
            rows.append(
                {
                    "month": month,
                    "outcome_id": oid,
                    "predicted_outcome": monthly_outcome,
                    "predicted_total_outcome": monthly_outcome,
                    "predicted_counterfactual_outcome": counterfactual_outcome_by_id[
                        oid
                    ],
                    "incremental_outcome": incremental_outcome_by_id[oid],
                    "incremental_outcome_all_activities": (
                        incremental_outcome_by_id[oid]
                    ),
                    "incremental_outcome_paid_decisions": (
                        paid_incremental_outcome_by_id[oid]
                    ),
                    "incremental_outcome_response_only_activities": (
                        response_only_incremental_outcome_by_id[oid]
                    ),
                    "counterfactual_media_input": dict(counterfactual_input),
                    "resolved_counterfactual_vector": dict(counterfactual_input),
                    "counterfactual_policy": policy.to_dict(),
                    "counterfactual_policy_fingerprint": policy.fingerprint(),
                    "value": value,
                    "value_status": value_status,
                    "unpriced_outcome_ids": unpriced_ids,
                    "total_spend": total_spend,
                    "paid_spend": paid_spend,
                    "fully_loaded_owned_spend": fully_loaded_owned_spend,
                    "campaign_cost_spend": campaign_cost_spend,
                    "non_costed_activity_present": bool(non_costed_ids),
                    "fh_gsa": fh_gsa,
                    "fh_signups": fh_signups,
                    "fh_net_billthrough": fh_net_billthrough,
                    "incremental_fh_gsa": incremental_fh_gsa,
                    "incremental_fh_signups": incremental_fh_signups,
                    "incremental_fh_net_billthrough": incremental_fh_nbt,
                    "incremental_dna_kits": incremental_dna_kits,
                    "dna_kits": dna_kits,
                    "avg_cpa": avg_cpa,
                    "cost_per_fh_gsa": avg_cpa,
                    # `whole_plan_*` (PR E.2 #8) - the explicit-spend-scope name:
                    # this divides *total scenario spend across every channel* by
                    # a KPI total, so it is a whole-plan efficiency number, never
                    # a channel-specific one (see core.media_units.CPA_SPEND_SCOPES/
                    # cpa_scope_metadata). The bare avg_cpa/cost_per_fh_gsa names
                    # are kept as legacy aliases.
                    "whole_plan_cost_per_fh_gsa": avg_cpa,
                    "fh_signup_avg_cpa": fh_signup_avg_cpa,
                    "cost_per_fh_signup": fh_signup_avg_cpa,
                    "whole_plan_cost_per_fh_signup": fh_signup_avg_cpa,
                    "whole_plan_cost_per_fh_net_billthrough": nbt_avg_cpa,
                    "whole_plan_incremental_nbt_cpa": nbt_avg_cpa,
                    "paid_media_incremental_cpa": paid_media_incremental_cpa,
                    "paid_media_incremental_nbt_cpa": (paid_media_incremental_nbt_cpa),
                    "dna_avg_cpa": dna_avg_cpa,
                    "cost_per_dna_kit": dna_avg_cpa,
                    "whole_plan_cost_per_dna_kit": dna_avg_cpa,
                    "total_value": total_value,
                    "incremental_total_value": incremental_total_value,
                    "whole_plan_incremental_roi": whole_plan_incremental_roi,
                    "paid_media_incremental_roi": paid_media_incremental_roi,
                    "economics_availability_status": period_coverage[
                        "economics_status"
                    ],
                    "economics_coverage": period_coverage,
                    "activity_definitions_fingerprint": activity_fingerprint,
                    "scenario_plan_fingerprint": (
                        scenario_plan.fingerprint()
                        if scenario_plan is not None
                        else None
                    ),
                    "planning_objective": (
                        planning_objective.to_dict()
                        if planning_objective is not None
                        else None
                    ),
                    "total_value_is_complete": total_value_is_complete,
                }
            )
    return pd.DataFrame(rows)


def evaluate_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    outcome_approvals: Optional[List[OutcomeApproval]] = None,
    governance_mode: str = "official",
    nbt_completeness_metadata: Optional[dict] = None,
    approval_readiness: Optional["ApprovalReadiness"] = None,
    current_policy: Optional["ThresholdPolicy"] = None,
) -> pd.DataFrame:
    """Evaluate total and incremental outcomes under governed activity scopes.

    G2A.7a.10 (brief section 12.2): this is the exploratory/compatibility
    numerical API, not the official planning gate. Official callers must use
    ``evaluate_manual_scenario()``, the trusted service that resolves
    governance exactly once via ``resolve_planning_governance()`` and returns
    the exact resolved proof for persistence. This function still performs
    ``require_matching_approval``/outcome-approval checks when
    ``governance_mode="official"`` is passed explicitly (so a direct call
    never silently bypasses model-identity or outcome-approval enforcement),
    but it is not the authoritative planning gate and does not produce a
    persistable governance proof - pass ``governance_mode="exploratory"`` for
    ordinary non-official use, which is what every in-repo caller does.

    G2A.7a.9: this is a public calculation API. It performs governance checks
    (model identity, outcome approvals) then delegates to the private
    ``_calculate_scenario`` for numerical evaluation. The ``_trusted_operation``
    parameter has been removed — callers must pass the correct
    ``governance_mode`` and let the API determine the required operation.

    Raises:
        ApprovalMismatchError: if the model approval does not match.
        OutcomeApprovalBlockedError: if outcome-approval checks fail.
        ObjectiveMissingError: if no objective is provided in official mode.
    """
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
        approval_readiness=approval_readiness,
        current_policy=current_policy,
    )
    # --- Outcome-approval gate ---
    if governance_mode == "official":
        if outcome_approvals is None or len(outcome_approvals) == 0:
            raise OutcomeApprovalBlockedError(
                "Official scenario evaluation blocked: no outcome approvals "
                "are configured. Official use requires at least one active "
                "OutcomeApproval. Pass governance_mode='exploratory' for "
                "non-official evaluation."
            )
        if planning_objective is None:
            raise ObjectiveMissingError(
                "Official scenario evaluation blocked: no PlanningObjective "
                "provided. Official planning requires an explicit objective "
                "with metric_key and target_outcome_ids. Pass "
                "governance_mode='exploratory' for non-official evaluation, "
                "or provide a complete PlanningObjective."
            )
        _require_planning_outcome_approvals(
            planning_objective=planning_objective,
            meta=meta,
            outcome_approvals=outcome_approvals,
            requested_use="planning",
            market=market,
            nbt_completeness_metadata=nbt_completeness_metadata,
        )
    # --- end outcome-approval gate ---
    return _calculate_scenario(
        spend_plan,
        market,
        meta,
        params,
        reference_context_by_month,
        ltv,
        model_type=model_type,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        planning_objective=planning_objective,
        activity_definitions=activity_definitions,
        scenario_plan=scenario_plan,
        counterfactual_policy=counterfactual_policy,
    )


def _validate_no_mixed_currency_value_weights(
    priced_outcome_ids: List[str],
    ltv: Dict[str, float],
    catalogue_by_id: Dict[str, object],
) -> None:
    """Raise ValueError if `priced_outcome_ids`' value weights would combine
    two different explicit currencies into one `total_value` (PR E.2 - "stop
    calling raw units value" also means never silently blending currencies).
    Outcome_ids with no recorded `value_currency` (blank/legacy catalogue)
    are treated as "no currency asserted" and never trigger this - there is
    nothing to conflict with. No FX conversion is applied or offered here;
    the caller must give `ltv` entries in one common currency."""
    currencies = {
        catalogue_by_id[oid].value_currency
        for oid in priced_outcome_ids
        if oid in catalogue_by_id and catalogue_by_id[oid].value_currency
    }
    if len(currencies) > 1:
        raise ValueError(
            f"Cannot combine value weights (ltv) across different currencies {sorted(currencies)} into "
            "one total_value without an explicit FX conversion - convert value_weight to one common "
            "currency before calling evaluate_scenario, or restrict to outcome_ids sharing a currency."
        )


# ---------------------------------------------------------------------------
# G2A.7a.5: trusted manual evaluation service
# ---------------------------------------------------------------------------


def evaluate_manual_scenario(
    spend_plan: Dict[str, Dict[str, float]],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    *,
    model_type: str = "shared",
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    outcome_approvals: Optional[List[OutcomeApproval]] = None,
    governance_mode: str = "official",
    nbt_completeness_metadata: Optional[dict] = None,
    artefact_kind: str = "manual_scenario",
    value_mapping: Optional["OutcomeValueMapping"] = None,
    currency_context: Optional["CurrencyContext"] = None,
    approval_readiness: Optional["ApprovalReadiness"] = None,
    current_policy: Optional["ThresholdPolicy"] = None,
) -> ScenarioEvaluationResult:
    """Trusted manual scenario evaluation service (G2A.7a.5).

    Resolves planning governance, evaluates the scenario, and returns a
    ``ScenarioEvaluationResult`` containing the exact resolved governance
    proof used to authorise the calculation. The page must persist this
    result's ``governance_dependencies`` unchanged.

    This is the public planning API. It does NOT accept ``_resolved_governance``
    — the service resolves governance itself, so there is no forged-proof
    surface.

    G2A.7a.10: when ``value_mapping`` is given, it is the single
    authoritative source of value weights for this calculation - its
    ``value_by_outcome_id`` is used in place of ``ltv`` and its identity is
    persisted into the saved governance dependencies. Legacy callers may
    still pass ``ltv`` directly; ``value_mapping`` takes precedence when
    both are given."""
    from .planning_governance import resolve_planning_governance

    effective_ltv = (
        dict(value_mapping.value_by_outcome_id) if value_mapping is not None else ltv
    )

    # Resolve governance for official mode
    resolved_gov = None
    governance_deps = None
    planning_semantics = None

    if governance_mode == "official":
        if planning_objective is None:
            raise ObjectiveMissingError(
                "Official manual evaluation requires a PlanningObjective."
            )
        # PR 88B: discloses the actual planning-engine semantics this
        # scenario was evaluated under (steady-state monthly, no carry-in/
        # terminal adstock state) as an explicit, fingerprinted governance
        # record - replaces PR 82E's zero_carry_in_adstock_state disclosure,
        # which implied a carry-in concept steady-state evaluation does not
        # actually model. See PlanningEvaluationSemantics.
        planning_semantics = CURRENT_PLANNING_EVALUATION_SEMANTICS
        resolved_gov = resolve_planning_governance(
            operation="planning",
            planning_objective=planning_objective,
            model_approval=approval,
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            market=market,
            meta=meta,
            outcome_approvals=outcome_approvals or [],
            nbt_completeness_metadata=nbt_completeness_metadata,
            approval_readiness=approval_readiness,
            current_policy=current_policy,
        )
        # Build governance dependencies from resolved proof
        governance_deps = ScenarioGovernanceDependencies(
            model_run_id=model_run_id,
            model_approval_fingerprint=resolved_gov.model_approval_fingerprint,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            planning_objective_fingerprint=resolved_gov.objective_fingerprint,
            outcome_authorisations=resolved_gov.authorisations,
            value_mapping_id=value_mapping.mapping_id
            if value_mapping is not None
            else None,
            value_mapping_fingerprint=value_mapping.fingerprint
            if value_mapping is not None
            else None,
            currency_context_fingerprint=(
                currency_context.fingerprint() if currency_context is not None else None
            ),
            activity_definitions_fingerprint=(
                activity_definitions_fingerprint(activity_definitions)
                if activity_definitions is not None
                else None
            ),
            cost_mapping_fingerprint=(
                cost_mapping_registry.fingerprint()
                if cost_mapping_registry is not None
                else None
            ),
            counterfactual_policy_fingerprint=(
                counterfactual_policy.fingerprint()
                if counterfactual_policy is not None
                else ""
            ),
            nbt_completeness_fingerprint=_resolve_nbt_completeness_fingerprint(
                nbt_completeness_metadata,
                fail_closed=(
                    governance_mode == "official"
                    and planning_objective is not None
                    and any(
                        _is_nbt_outcome(tid, meta)
                        for tid in planning_objective.target_outcome_ids
                    )
                ),
            ),
            # PR 56D: readiness artefact binding
            validation_policy_id=approval_readiness.policy_id
            if approval_readiness is not None
            else "",
            validation_policy_version=approval_readiness.policy_version
            if approval_readiness is not None
            else "",
            validation_policy_fingerprint=approval_readiness.policy_fingerprint
            if approval_readiness is not None
            else "",
            readiness_artefact_id=approval_readiness.readiness_artefact_id
            if approval_readiness is not None
            else "",
            readiness_fingerprint=approval_readiness.fingerprint()
            if approval_readiness is not None
            else "",
            diagnostic_artefact_fingerprint=approval_readiness.diagnostic_artefact_fingerprint
            if approval_readiness is not None
            else "",
            model_identity_fingerprint=approval_readiness.model_identity_fingerprint
            if approval_readiness is not None
            else "",
            planning_semantics_fingerprint=planning_semantics.fingerprint()
            if planning_semantics is not None
            else "",
        )

    # Call the private numerical function directly.
    # In official mode, governance has already been resolved once above and the
    # exact proof (resolved_gov) is returned to the caller. The numerical
    # calculation does NOT re-validate governance.
    predicted = _calculate_scenario(
        spend_plan,
        market,
        meta,
        params,
        reference_context_by_month,
        effective_ltv,
        model_type=model_type,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        planning_objective=planning_objective,
        activity_definitions=activity_definitions,
        scenario_plan=scenario_plan,
        counterfactual_policy=counterfactual_policy,
    )

    # Extract economics coverage from the predicted DataFrame
    economics_cov = None
    if "economics_coverage" in predicted.columns and len(predicted) > 0:
        economics_cov = predicted["economics_coverage"].iloc[0]

    return ScenarioEvaluationResult(
        predicted=predicted,
        planning_objective=planning_objective,
        governance_mode=governance_mode,
        artefact_kind=artefact_kind,
        resolved_governance=resolved_gov,
        governance_dependencies=governance_deps,
        activity_definitions_fingerprint=(
            activity_definitions_fingerprint(activity_definitions)
            if activity_definitions is not None
            else None
        ),
        cost_mapping_fingerprint=(
            cost_mapping_registry.fingerprint()
            if cost_mapping_registry is not None
            else None
        ),
        counterfactual_policy_fingerprint=(
            counterfactual_policy.fingerprint()
            if counterfactual_policy is not None
            else ""
        ),
        economics_coverage=dict(economics_cov)
        if isinstance(economics_cov, dict)
        else None,
        planning_semantics=planning_semantics,
    )


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


@dataclass
class SpendConstraint:
    kind: str  # "locked_cell" | "channel_total" | "month_total" | "bounded_movement" | "min_spend_floor"
    channel: Optional[str] = None
    month: Optional[str] = None
    months: Optional[List[str]] = None
    value: Optional[float] = None
    max_pct_move: Optional[float] = None
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "channel": self.channel,
            "month": self.month,
            "months": self.months,
            "value": self.value,
            "max_pct_move": self.max_pct_move,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SpendConstraint":
        return cls(**d)


def _flatten(
    spend_plan: Dict[str, Dict[str, float]], months: List[str], channels: List[str]
) -> np.ndarray:
    return np.array([spend_plan[m].get(c, 0.0) for m in months for c in channels])


def _unflatten(
    x: np.ndarray, months: List[str], channels: List[str]
) -> Dict[str, Dict[str, float]]:
    n_ch = len(channels)
    return {
        m: {c: float(x[mi * n_ch + ci]) for ci, c in enumerate(channels)}
        for mi, m in enumerate(months)
    }


def _cell_index(
    month: str, channel: str, months: List[str], channels: List[str]
) -> int:
    return months.index(month) * len(channels) + channels.index(channel)


def build_bounds_and_constraints(
    months: List[str],
    channels: List[str],
    current_spend: np.ndarray,
    constraints: List[SpendConstraint],
    default_max_pct_move: Optional[float] = None,
    resource_channels: Optional[List[str]] = None,
) -> Tuple[List[Tuple[float, float]], List[LinearConstraint]]:
    """Translate SpendConstraint objects into scipy bounds + LinearConstraints.

    `resource_channels`, when given, restricts a `month_total` constraint's
    row to only those channels - a `month_total` spans every channel in the
    plan by default, which mixes units (GBP spend, impressions, CRM sends)
    unless scoped to one optimisation resource's eligible channels. `None`
    preserves the legacy behaviour of summing every channel (only valid when
    the caller has no governed activity taxonomy to scope by)."""
    n = len(current_spend)
    lower = np.zeros(n)
    upper = np.full(n, np.inf)

    if default_max_pct_move is not None:
        lower = np.maximum(0, current_spend * (1 - default_max_pct_move))
        upper = current_spend * (1 + default_max_pct_move)

    linear_constraints: List[LinearConstraint] = []

    for c in constraints:
        if c.kind == "locked_cell":
            idx = _cell_index(c.month, c.channel, months, channels)
            val = c.value if c.value is not None else current_spend[idx]
            lower[idx] = upper[idx] = val

        elif c.kind == "bounded_movement":
            pct = c.max_pct_move if c.max_pct_move is not None else default_max_pct_move
            if pct is None:
                continue
            if c.channel and c.month:
                idx = _cell_index(c.month, c.channel, months, channels)
                lower[idx] = max(0, current_spend[idx] * (1 - pct))
                upper[idx] = current_spend[idx] * (1 + pct)
            elif c.channel:
                for m in months:
                    idx = _cell_index(m, c.channel, months, channels)
                    lower[idx] = max(0, current_spend[idx] * (1 - pct))
                    upper[idx] = current_spend[idx] * (1 + pct)
            else:
                lower = np.maximum(0, current_spend * (1 - pct))
                upper = current_spend * (1 + pct)

        elif c.kind == "min_spend_floor":
            months_set = c.months or ([c.month] if c.month else months)
            for m in months_set:
                idx = _cell_index(m, c.channel, months, channels)
                lower[idx] = max(lower[idx], c.value or 0.0)

        elif c.kind == "channel_total":
            row = np.zeros(n)
            for m in months:
                row[_cell_index(m, c.channel, months, channels)] = 1
            target = (
                c.value
                if c.value is not None
                else float(
                    sum(
                        current_spend[_cell_index(m, c.channel, months, channels)]
                        for m in months
                    )
                )
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        elif c.kind == "month_total":
            target_channels = (
                resource_channels if resource_channels is not None else channels
            )
            row = np.zeros(n)
            for ch in target_channels:
                row[_cell_index(c.month, ch, months, channels)] = 1
            target = (
                c.value
                if c.value is not None
                else float(
                    sum(
                        current_spend[_cell_index(c.month, ch, months, channels)]
                        for ch in target_channels
                    )
                )
            )
            linear_constraints.append(LinearConstraint(row, lb=target, ub=target))

        else:
            raise ValueError(f"Unknown constraint kind: {c.kind}")

    bounds = list(zip(lower, upper))
    return bounds, linear_constraints


# ---------------------------------------------------------------------------
# Optimiser
# ---------------------------------------------------------------------------

VALID_OBJECTIVES = (
    "fh_net_billthrough",
    "fh_gsa",
    "fh_signups",
    "dna_kits",
    "weighted_mix",
    "expected_value",
)

_OBJECTIVE_METRIC_KEY = {
    "fh_gsa": METRIC_KEY_FH_GSA,
    "fh_signups": METRIC_KEY_FH_SIGNUP,
    "fh_net_billthrough": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
    "dna_kits": METRIC_KEY_DNA_KIT_SALE,
}


def _validate_target_outcome_ids(
    target_outcome_ids: Optional[List[str]],
    meta: FHModelMeta,
    *,
    metric_key: Optional[str] = None,
) -> None:
    """PR E.2 requirement #9 (harden optimiser target validation): every
    `target_outcome_id` must (a) actually exist in this fit, (b) match the
    requested metric when `metric_key` is given - a caller must not be able
    to pass a sign-up outcome_id into `objective="fh_gsa"` and bypass
    metric-aware selection - and (c) be eligible for optimisation
    (`include_in_optimisation`, which defaults to `False` for a diagnostic-
    role outcome and for a `funnel_intermediate` outcome - PR E.2's
    eligibility defaults - so "reject diagnostic outcomes" and "reject
    outcomes excluded from planning" are both enforced by this one check).
    No-op if `target_outcome_ids` is empty/None - there is nothing to
    validate when a caller relies on the objective's own default selector.
    Legacy fallback: a `FHModelMeta` with no catalogue metadata at all
    (`outcome_id_to_product` empty - a fit that predates
    `outcome_catalogue_at_fit`, or a hand-built test fixture) skips the
    metric-match check, matching every other named selector's legacy
    fallback in `core.outcomes` - there is no metric metadata to check
    against.
    """
    if not target_outcome_ids:
        return
    unknown = sorted(set(target_outcome_ids) - set(meta.outcome_ids))
    if unknown:
        raise ValueError(
            f"target_outcome_ids contains outcome_id(s) not fitted in this model: {unknown}."
        )
    has_catalogue_metadata = bool(getattr(meta, "outcome_id_to_product", {}))
    if metric_key is not None and has_catalogue_metadata:
        matching = set(select_outcome_ids(meta, metric_key=metric_key))
        mismatched = sorted(oid for oid in target_outcome_ids if oid not in matching)
        if mismatched:
            raise ValueError(
                f"target_outcome_ids {mismatched} do not match this objective's metric "
                f"({metric_key!r}) - a sign-up outcome cannot be optimised under a mismatched-metric "
                "objective (e.g. 'fh_gsa'), or vice versa."
            )
    optimisable = set(
        eligible_outcome_ids(meta, list(target_outcome_ids), "include_in_optimisation")
    )
    excluded = sorted(set(target_outcome_ids) - optimisable)
    if excluded:
        raise ValueError(
            f"target_outcome_ids {excluded} are not eligible for optimisation (diagnostic role, "
            "funnel_intermediate role, or an explicit include_in_optimisation=False) - remove them, or "
            "opt them in explicitly via include_in_optimisation on the OutcomeDefinition."
        )


def _objective_weight(
    objective: str,
    meta: FHModelMeta,
    ltv: Optional[Dict[str, float]],
    target_outcome_ids: Optional[List[str]],
    weights: Optional[Dict[str, float]],
    *,
    assume_value_scaled_weights: bool = False,
) -> Dict[str, float]:
    """
    Per-outcome_id weight for the optimiser's scalar objective - the
    instruction document's "optimisation objectives must be explicit" /
    "block generic raw-volume optimisation when mixed metric types are
    present" requirement. `objective` must be one of VALID_OBJECTIVES:
    there is no "maximise everything, whatever unit it's in" option, and an
    outcome_id outside the objective's scope gets weight 0 (excluded), never
    an implicit 1 (silently counted as if it were the same unit as
    everything else - the confirmed defect this replaces: `"fh_gsa"` used to
    mean "every outcome_id that isn't a DNA-kit outcome", which would
    silently fold a Family History sign-up outcome into a GSA objective).

    Every branch validates any explicit `target_outcome_ids` via
    `_validate_target_outcome_ids` (PR E.2 #9) - unknown outcome_ids,
    metric mismatches, and outcomes excluded from optimisation (diagnostic
    role or `include_in_optimisation=False`) are all rejected before the
    (potentially slow) optimisation runs, not discovered afterwards.

    - `"fh_gsa"`: Family History GSA outcomes - `core.outcomes.fh_gsa_outcome_ids`
      (metric_key=fh_gsa), or just `target_outcome_ids` if given (e.g. a
      single FH outcome - "maximise FH New GSA").
    - `"fh_signups"`: Family History sign-up outcomes -
      `core.outcomes.fh_signup_outcome_ids` (metric_key=fh_signup), or just
      `target_outcome_ids` if given. Raises if the model has none - distinct
      from `"fh_gsa"` even when both share a segment.
    - `"dna_kits"`: DNA kit sales - `core.outcomes.dna_kit_sale_outcome_ids`,
      or just `target_outcome_ids` if given. Raises if the model has none.
    - `"weighted_mix"`: an analyst-supplied per-outcome_id `weights` dict -
      required explicitly; there is no default mix to fall back to. Every
      weight must be finite and non-negative. If the weighted outcome_ids
      span more than one raw `unit` (e.g. "GSA" and "sign-up"), this raises
      unless `assume_value_scaled_weights=True` is passed explicitly - the
      instruction document's "reject weighted mixes across different units
      unless weights explicitly convert to a common business-value scale"
      requirement; there is no way to infer that intent from the numbers
      alone, so it must be asserted explicitly by the caller.
    - `"expected_value"`: LTV-weighted total value across every eligible
      (`include_in_value` AND `include_in_optimisation`, or just
      `target_outcome_ids` if given) outcome_id - requires `ltv` to have a
      finite, non-negative entry for every one of them. Fails closed
      (raises) rather than silently treating a missing weight as 0 or 1 -
      the confirmed "missing value_weight defaults to 1.0" defect this
      replaces. Also raises if the priced outcome_ids don't share one
      explicit currency (`OutcomeDefinition.value_currency`) - see
      `evaluate_scenario`'s docstring for the same rule.
    """
    if objective not in VALID_OBJECTIVES:
        raise ValueError(
            f"objective must be one of {VALID_OBJECTIVES}, got {objective!r}. Generic unlabelled "
            "volume optimisation is not supported here - it would silently combine Family History "
            "GSAs, sign-ups and DNA kit sales into one meaningless total."
        )
    if objective in _OBJECTIVE_METRIC_KEY:
        metric_key = _OBJECTIVE_METRIC_KEY[objective]
        _validate_target_outcome_ids(target_outcome_ids, meta, metric_key=metric_key)
        default_selector = {
            "fh_gsa": fh_gsa_outcome_ids,
            "fh_signups": fh_signup_outcome_ids,
            "fh_net_billthrough": fh_net_billthrough_outcome_ids,
            "dna_kits": dna_kit_sale_outcome_ids,
        }[objective]
        eligible = (
            set(target_outcome_ids)
            if target_outcome_ids
            else set(default_selector(meta))
        )
        if objective != "fh_gsa" and not eligible:
            noun = {
                "fh_signups": "Family History sign-up",
                "fh_net_billthrough": "Family History net bill-through",
                "dna_kits": "DNA-kit",
            }[objective]
            raise ValueError(
                f"objective={objective!r} but this model has no {noun} outcomes."
            )
        return {s: 1.0 for s in eligible}
    if objective == "weighted_mix":
        if not weights:
            raise ValueError(
                "objective='weighted_mix' requires an explicit weights={outcome_id: weight} dict - there is no default mix."
            )
        _validate_target_outcome_ids(list(weights), meta)
        invalid = sorted(
            oid
            for oid, w in weights.items()
            if not (isinstance(w, (int, float)) and np.isfinite(w) and w >= 0)
        )
        if invalid:
            raise ValueError(
                f"weighted_mix weights must be finite and non-negative; invalid for: {invalid}."
            )
        units = {meta.outcome_id_to_unit.get(oid) for oid in weights}
        units.discard(None)
        if len(units) > 1 and not assume_value_scaled_weights:
            raise ValueError(
                f"weighted_mix combines outcome_ids with different units ({sorted(units)}) - raw counts "
                "in different units cannot be added together. Pass assume_value_scaled_weights=True only "
                "if these weights already convert every outcome_id onto one common business-value scale "
                "(e.g. LTV-weighted), not raw unit counts."
            )
        return weights
    # objective == "expected_value"
    if not ltv:
        raise ValueError(
            "objective='expected_value' requires ltv={outcome_id: value} - it is the LTV-weighted total across every outcome_id."
        )
    if target_outcome_ids:
        _validate_target_outcome_ids(target_outcome_ids, meta)
        eligible = set(target_outcome_ids)
    else:
        all_ids = list(meta.outcome_ids)
        value_eligible = set(eligible_outcome_ids(meta, all_ids, "include_in_value"))
        optimisation_eligible = set(
            eligible_outcome_ids(meta, all_ids, "include_in_optimisation")
        )
        eligible = value_eligible & optimisation_eligible
    missing = sorted(oid for oid in eligible if oid not in ltv)
    if missing:
        raise ValueError(
            f"objective='expected_value' requires a value weight for every eligible outcome_id, but "
            f"{missing} have none in ltv - a missing weight must never be silently treated as 0 or 1. "
            "Provide ltv entries for all of them, or pass target_outcome_ids to restrict the objective."
        )
    invalid = sorted(
        oid
        for oid in eligible
        if not (
            isinstance(ltv[oid], (int, float))
            and np.isfinite(ltv[oid])
            and ltv[oid] >= 0
        )
    )
    if invalid:
        raise ValueError(
            f"objective='expected_value' requires finite, non-negative value weights; invalid for: {invalid}."
        )
    catalogue_by_id = outcome_catalogue_at_fit_by_id(meta)
    _validate_no_mixed_currency_value_weights(sorted(eligible), ltv, catalogue_by_id)
    return {oid: ltv[oid] for oid in eligible}


def _objective_factory(
    months: List[str],
    channels: List[str],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]],
    objective: str,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
    assume_value_scaled_weights: bool = False,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    sequential_context: Optional[SequentialOptimisationContext] = None,
):
    if planning_objective is not None:
        metric_objectives = {
            METRIC_KEY_FH_GSA: "fh_gsa",
            METRIC_KEY_FH_SIGNUP: "fh_signups",
            METRIC_KEY_FH_NET_BILLTHROUGH_COUNT: "fh_net_billthrough",
            METRIC_KEY_DNA_KIT_SALE: "dna_kits",
        }
        objective = (
            "expected_value"
            if planning_objective.estimand == "incremental_value"
            else metric_objectives.get(
                planning_objective.metric_key,
                objective,
            )
        )
        target_outcome_ids = list(planning_objective.target_outcome_ids) or None
    weight = _objective_weight(
        objective,
        meta,
        ltv,
        target_outcome_ids,
        weights,
        assume_value_scaled_weights=assume_value_scaled_weights,
    )
    if sequential_context is not None:
        from .sequential_optimisation_tractability import (
            compute_sequential_plan_objective_value,
        )

        if sequential_context.model_type != model_type:
            raise ValueError(
                "SequentialOptimisationContext.model_type must match "
                f"optimize_scenario model_type ({model_type!r})."
            )
        if sequential_context.reference_plan.market != market:
            raise ValueError(
                "SequentialOptimisationContext.reference_plan.market must "
                f"match the optimisation market ({market!r})."
            )
    response_fn = _steady_state_response_fn(model_type)
    policy = counterfactual_policy or CounterfactualPolicy()
    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )

    def neg_total(x: np.ndarray) -> float:
        spend_plan = _unflatten(x, months, channels)
        if sequential_context is not None:
            candidate_plan = sequential_context.candidate_plan(spend_plan)
            if candidate_plan.market != market:
                raise ValueError(
                    "Sequential candidate plan market does not match the "
                    f"optimisation market ({market!r})."
                )
            if (
                candidate_plan.period_labels
                != sequential_context.reference_plan.period_labels
            ):
                raise ValueError(
                    "Sequential candidate and reference plans must cover "
                    "exactly the same canonical weeks."
                )
            return -compute_sequential_plan_objective_value(
                candidate_plan,
                sequential_context.reference_plan,
                sequential_context.carry_in,
                meta,
                cast(FHPosteriorParams, params),
                model_type=model_type,
                outcome_weights=weight,
                incremental=(
                    planning_objective is not None
                    and planning_objective.estimand != "total_outcome"
                ),
                named_event_fit_inputs=sequential_context.named_event_fit_inputs,
            )
        if cost_mapping_registry is not None and activity_definitions is not None:
            monetary: dict[str, dict[str, float]] = {}
            quantities: dict[str, dict[str, float]] = {}
            for period, values in spend_plan.items():
                monetary[period] = {}
                quantities[period] = {}
                for column, value in values.items():
                    definition = activity_map[column]
                    target = monetary if definition.is_cost_bearing else quantities
                    target[period][definition.activity_id] = value
            typed_plan = ScenarioPlan(monetary, quantities)
            model_input_plan, _, _ = resolve_scenario_plan(
                typed_plan,
                market=market,
                activity_definitions=activity_definitions,
                cost_mapping_registry=cost_mapping_registry,
                cost_context_id=cost_context_id or "default",
                cost_as_of_by_period=cost_as_of_by_month,
            )
        else:
            model_input_plan = (
                monetary_plan_to_media_input(
                    spend_plan,
                    market=market,
                    registry=cost_mapping_registry,
                    cost_context_id=cost_context_id or "default",
                    as_of_by_period=cost_as_of_by_month or {},
                )
                if cost_mapping_registry is not None
                else spend_plan
            )
        resolved_counterfactual = (
            counterfactual_media_input_by_month
            if counterfactual_media_input_by_month is not None
            else resolve_counterfactual(
                model_input_plan,
                market=market,
                activity_definitions=activity_definitions,
                policy=policy,
            )
        )
        total = 0.0
        for m in months:
            ref = reference_context_by_month.get(m, {})
            rates = response_fn(
                market,
                model_input_plan[m],
                meta,
                params,
                ref,
                planning_only=True,
            )
            if (
                planning_objective is not None
                and planning_objective.estimand != "total_outcome"
            ):
                counterfactual = resolved_counterfactual[m]
                counterfactual_rates = response_fn(
                    market,
                    counterfactual,
                    meta,
                    params,
                    ref,
                    planning_only=True,
                )
                rates = {
                    outcome_id: rate - counterfactual_rates[outcome_id]
                    for outcome_id, rate in rates.items()
                }
            for oid, rate in rates.items():
                total += rate * WEEKS_PER_MONTH * weight.get(oid, 0.0)
        return -total

    return neg_total


def _sequential_pair_to_prediction_frame(
    *,
    candidate,
    reference,
    spend_plan: Mapping[str, Mapping[str, float]],
    meta: FHModelMeta,
    ltv: Optional[Mapping[str, float]],
    activity_definitions: Optional[List[ActivityDefinition]],
    market: str,
    planning_objective: Optional[PlanningObjective],
    scenario_plan: Optional[ScenarioPlan],
    counterfactual_policy: CounterfactualPolicy,
) -> pd.DataFrame:
    """Convert one exact sequential candidate/reference replay to the
    monthly-shaped table consumed by the existing scenario UI/export code.

    The weekly kernel remains authoritative: monthly values are aggregated
    from weekly outcome-scale ``mu`` only after both replays complete.  This
    adapter deliberately does not call ``_calculate_scenario`` because that
    would replace sequential carryover with the steady-state approximation.
    """
    if candidate.market != market or reference.market != market:
        raise ValueError("Sequential prediction markets do not match the request.")
    if candidate.period_labels != reference.period_labels:
        raise ValueError("Sequential prediction periods do not match.")

    ltv_values = dict(ltv or {})
    outcome_ids = tuple(candidate.outcome_ids)
    by_input = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )
    cost_bearing = {
        channel
        for channel, definition in by_input.items()
        if definition.is_cost_bearing
    }
    response_only_active = bool(
        activity_definitions
        and any(
            float(value) != 0.0
            and channel in by_input
            and not by_input[channel].is_cost_bearing
            for values in spend_plan.values()
            for channel, value in values.items()
        )
    )
    whole_plan_compatible = not response_only_active
    if activity_definitions is None:
        cost_bearing = set(spend_plan[next(iter(spend_plan))]) if spend_plan else set()

    month_indices: Dict[str, List[int]] = {}
    for index, label in enumerate(candidate.period_labels):
        month_indices.setdefault(str(label)[:7], []).append(index)

    gsa_ids = set(fh_gsa_outcome_ids(meta))
    signup_ids = set(fh_signup_outcome_ids(meta))
    nbt_ids = set(fh_net_billthrough_outcome_ids(meta))
    dna_ids = set(dna_kit_sale_outcome_ids(meta))
    rows: List[dict] = []
    for month, indices in month_indices.items():
        candidate_month = np.asarray(candidate.mu[indices], dtype=float).sum(axis=0)
        reference_month = np.asarray(reference.mu[indices], dtype=float).sum(axis=0)
        incremental_month = candidate_month - reference_month
        month_values = spend_plan.get(month, {})
        total_spend = float(
            sum(
                float(value)
                for channel, value in month_values.items()
                if channel in cost_bearing
            )
        )
        if activity_definitions is None:
            total_spend = float(sum(float(value) for value in month_values.values()))
        priced_ids = [oid for oid in outcome_ids if oid in ltv_values]
        total_value_is_complete = len(priced_ids) == len(outcome_ids)
        total_value = (
            float(
                sum(
                    candidate_month[i] * ltv_values[oid]
                    for i, oid in enumerate(outcome_ids)
                    if oid in ltv_values
                )
            )
            if priced_ids
            else None
        )
        incremental_total_value = (
            float(
                sum(
                    incremental_month[i] * ltv_values[oid]
                    for i, oid in enumerate(outcome_ids)
                )
            )
            if total_value_is_complete
            else None
        )
        incremental_gsa = float(
            sum(
                incremental_month[i]
                for i, oid in enumerate(outcome_ids)
                if oid in gsa_ids
            )
        )
        incremental_signup = float(
            sum(
                incremental_month[i]
                for i, oid in enumerate(outcome_ids)
                if oid in signup_ids
            )
        )
        incremental_nbt = float(
            sum(
                incremental_month[i]
                for i, oid in enumerate(outcome_ids)
                if oid in nbt_ids
            )
        )
        incremental_dna = float(
            sum(
                incremental_month[i]
                for i, oid in enumerate(outcome_ids)
                if oid in dna_ids
            )
        )
        whole_plan_cpa = (
            total_spend / incremental_gsa
            if whole_plan_compatible and total_spend > 0 and incremental_gsa > 0
            else None
        )
        whole_plan_nbt_cpa = (
            total_spend / incremental_nbt
            if whole_plan_compatible and total_spend > 0 and incremental_nbt > 0
            else None
        )
        whole_plan_signup_cpa = (
            total_spend / incremental_signup
            if whole_plan_compatible and total_spend > 0 and incremental_signup > 0
            else None
        )
        whole_plan_dna_cpa = (
            total_spend / incremental_dna
            if whole_plan_compatible and total_spend > 0 and incremental_dna > 0
            else None
        )
        whole_plan_roi = (
            incremental_total_value / total_spend
            if whole_plan_compatible
            and incremental_total_value is not None
            and total_spend > 0
            else None
        )
        coverage = {
            "economics_status": (
                "sequential_weekly_kernel"
                if activity_definitions is None or cost_bearing
                else "economics_not_applicable"
            ),
            "whole_plan_scope_compatible": whole_plan_compatible,
            "counterfactual_scope": counterfactual_policy.policy_id,
            "calculation_method": "sequential_weekly",
        }
        common = {
            "month": month,
            "calculation_method": "sequential_weekly",
            "predicted_total_outcome": float(candidate_month.sum()),
            "predicted_counterfactual_outcome_total": float(reference_month.sum()),
            "total_spend": total_spend,
            "paid_spend": total_spend,
            "fully_loaded_owned_spend": 0.0,
            "campaign_cost_spend": 0.0,
            "value_status": "complete"
            if total_value_is_complete
            else "partial"
            if priced_ids
            else "not configured",
            "total_value": total_value,
            "incremental_total_value": incremental_total_value,
            "whole_plan_incremental_roi": whole_plan_roi,
            "paid_media_incremental_roi": None,
            "whole_plan_scope_compatible": whole_plan_compatible,
            "economics_coverage": coverage,
            "scenario_plan_fingerprint": scenario_plan.fingerprint()
            if scenario_plan
            else None,
            "planning_objective": planning_objective.to_dict()
            if planning_objective
            else None,
        }
        for i, oid in enumerate(outcome_ids):
            rows.append(
                {
                    **common,
                    "outcome_id": oid,
                    "predicted_outcome": float(candidate_month[i]),
                    "predicted_counterfactual_outcome": float(reference_month[i]),
                    "incremental_outcome": float(incremental_month[i]),
                    "incremental_outcome_all_activities": float(incremental_month[i]),
                    "incremental_outcome_paid_decisions": float(incremental_month[i])
                    if whole_plan_compatible
                    else None,
                    "incremental_outcome_response_only_activities": 0.0,
                    "counterfactual_media_input": {},
                    "resolved_counterfactual_vector": {},
                    "counterfactual_policy": counterfactual_policy.to_dict(),
                    "counterfactual_policy_fingerprint": counterfactual_policy.fingerprint(),
                    "value": float(candidate_month[i] * ltv_values[oid])
                    if oid in ltv_values
                    else None,
                    "unpriced_outcome_ids": [
                        item for item in outcome_ids if item not in ltv_values
                    ],
                    "non_costed_activity_present": response_only_active,
                    "fh_gsa": float(
                        sum(
                            candidate_month[j]
                            for j, item in enumerate(outcome_ids)
                            if item in gsa_ids
                        )
                    ),
                    "fh_signups": float(
                        sum(
                            candidate_month[j]
                            for j, item in enumerate(outcome_ids)
                            if item in signup_ids
                        )
                    ),
                    "fh_net_billthrough": float(
                        sum(
                            candidate_month[j]
                            for j, item in enumerate(outcome_ids)
                            if item in nbt_ids
                        )
                    ),
                    "incremental_fh_gsa": incremental_gsa,
                    "incremental_fh_signups": incremental_signup,
                    "incremental_fh_net_billthrough": incremental_nbt,
                    "incremental_dna_kits": incremental_dna,
                    "dna_kits": float(
                        sum(
                            candidate_month[j]
                            for j, item in enumerate(outcome_ids)
                            if item in dna_ids
                        )
                    ),
                    "avg_cpa": whole_plan_cpa,
                    "cost_per_fh_gsa": whole_plan_cpa,
                    "whole_plan_cost_per_fh_gsa": whole_plan_cpa,
                    "fh_signup_avg_cpa": whole_plan_signup_cpa,
                    "cost_per_fh_signup": whole_plan_signup_cpa,
                    "whole_plan_cost_per_fh_signup": whole_plan_signup_cpa,
                    "whole_plan_cost_per_fh_net_billthrough": whole_plan_nbt_cpa,
                    "whole_plan_incremental_nbt_cpa": whole_plan_nbt_cpa,
                    "paid_media_incremental_cpa": None,
                    "paid_media_incremental_nbt_cpa": None,
                    "dna_avg_cpa": whole_plan_dna_cpa,
                    "cost_per_dna_kit": whole_plan_dna_cpa,
                    "whole_plan_cost_per_dna_kit": whole_plan_dna_cpa,
                    "total_value_is_complete": total_value_is_complete,
                }
            )
    return pd.DataFrame(rows)


def optimize_scenario(
    current_spend_plan: Dict[str, Dict[str, float]],
    months: List[str],
    channels: List[str],
    market: str,
    meta: FHModelMeta,
    params: AnyPosteriorParams,
    reference_context_by_month: Dict[str, dict],
    ltv: Optional[Dict[str, float]] = None,
    objective: Optional[str] = None,
    constraints: Optional[List[SpendConstraint]] = None,
    conserve_total_budget: bool = True,
    max_iter: int = 200,
    *,
    model_type: str = "shared",
    target_outcome_ids: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
    assume_value_scaled_weights: bool = False,
    approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    cost_mapping_registry: Optional[CostMappingRegistry] = None,
    cost_context_id: Optional[str] = None,
    cost_as_of_by_month: Optional[Dict[str, str]] = None,
    planning_objective: Optional[PlanningObjective] = None,
    counterfactual_media_input_by_month: Optional[Dict[str, Dict[str, float]]] = None,
    activity_definitions: Optional[List[ActivityDefinition]] = None,
    counterfactual_policy: Optional[CounterfactualPolicy] = None,
    posterior_trace: Optional[Any] = None,
    posterior_evaluation_draws: int = 100,
    optimization_resource: Optional[OptimizationResource] = None,
    governance_mode: str = "official",
    outcome_approvals: Optional[List[OutcomeApproval]] = None,
    nbt_completeness_metadata: Optional[dict] = None,
    artefact_kind: Optional[str] = None,
    value_currency: Optional[str] = None,
    value_mapping: Optional["OutcomeValueMapping"] = None,
    currency_context: Optional["CurrencyContext"] = None,
    approval_readiness: Optional["ApprovalReadiness"] = None,
    current_policy: Optional["ThresholdPolicy"] = None,
    governed_constraints: Optional[List["GovernedSpendConstraint"]] = None,
    capacity_limits: Optional[List["CapacityLimitDefinition"]] = None,
    capacity_realised_by_limit_and_period: Optional[Dict[str, Dict[str, float]]] = None,
    capacity_unit_to_spend_rate_by_limit_id: Optional[Dict[str, float]] = None,
    evaluation_method: str = "steady_state_monthly",
    sequential_context: Optional[SequentialOptimisationContext] = None,
) -> Dict:
    """
    Optimise a spend plan. `constraints=None` (or empty) + conserve_total_budget=True
    is the "unconstrained benchmark" mode: reallocate the same total budget
    freely, ignoring locks/floors/bounded-movement - a theoretical-optimum
    comparison point, not a recommended plan. Pass `constraints` for the
    constrained-planning mode analysts will actually use.

    `objective` must be one of `VALID_OBJECTIVES` - see `_objective_weight`'s
    docstring for what each one maximises and what `target_outcome_ids`/
    `weights` do. There is deliberately no generic "maximise volume"
    objective (the instruction document's audit-confirmed defect this
    replaces): every objective states exactly what it sums, and an
    outcome_id outside its scope contributes 0, never an implicit 1.

    `model_type` selects which model's response function drives optimisation
    and evaluation - `"shared"` (Model A, default) or `"market_specific"`
    (Model C). ``evaluation_method="sequential_weekly"`` requires a
    ``SequentialOptimisationContext`` built by the caller and runs both the
    SLSQP objective and final predictions through the exact weekly replay
    kernel. The application-facing `ScenarioService` supplies that method by
    default; this lower-level function retains its explicit steady-state
    default for backwards-compatible direct callers, who must opt into the
    production method by passing the context.

    Raises ApprovalMismatchError unless `approval` matches the current model
    run identity - checked up front, before running the (potentially slow)
    SLSQP optimisation, not just when the final predicted outcomes are
    computed via evaluate_scenario below. Raises ValueError up front too if
    `objective` (plus `target_outcome_ids`/`weights`/`ltv`) isn't resolvable -
    same "fail before the slow optimisation runs" reasoning.

    `governed_constraints` (`REQ-OPT-001` Requirement 2, Decision 16): an
    optional list of `core.optimization_constraint_vocabulary.
    GovernedSpendConstraint` - the extended ten-kind constraint vocabulary
    (`maximum_spend`, `spend_range`, `absolute_change_from_reference`,
    `unavailable`, `required_minimum_activity`, plus the four kinds with a
    direct legacy equivalent). When supplied, it *replaces* `constraints`
    for bounds-building (never combined with `constraints` in the same
    call - a caller picks one vocabulary per optimisation run), resolved via
    `resolve_governed_constraints` - the real function this optimiser's
    SLSQP call receives its bounds/linear constraints from in that case, not
    a parallel vocabulary that sits beside the run unused. An infeasible
    cell (resolved lower bound > upper bound) raises
    `GovernedConstraintInfeasibleError` before SLSQP ever runs (Requirement
    5) - never silently clamped or dropped. The returned dict's
    `governed_constraint_disclosures` names every governed constraint's
    disposition plus whether it was actually binding at the optimised
    solution (Requirement 4 - binding-constraint reporting).

    `capacity_limits` (`REQ-CAP-001`/`REQ-OPT-001` Requirement 4, Decision
    18): an optional list of `core.capacity.CapacityLimitDefinition`,
    applied as a further bounds-tightening pass via `core.
    capacity_plan_application.apply_capacity_limits_to_bounds` on top of
    whichever `constraints`/`governed_constraints` bounds were already
    resolved - composable with either, never a separate/duplicate rule
    set (Decision 18's own "both must be usable together" instruction).
    A resulting infeasible cell raises `CapacityLimitInfeasibleError`
    before SLSQP runs, same discipline as governed constraints.
    `capacity_realised_by_limit_and_period`/`capacity_unit_to_spend_rate_
    by_limit_id` pass through unchanged to `apply_capacity_limits_to_
    bounds` - see that function's own docstring for what they control
    (report-only binding classification, and the explicit non-money-unit
    -> spend conversion a non-monetary limit requires to ever tighten a
    spend bound, respectively).
    """
    require_matching_approval(
        approval,
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
        approval_readiness=approval_readiness,
        current_policy=current_policy,
    )
    if evaluation_method not in {"steady_state_monthly", "sequential_weekly"}:
        raise ValueError(
            "evaluation_method must be 'steady_state_monthly' or "
            f"'sequential_weekly', got {evaluation_method!r}."
        )
    if evaluation_method == "sequential_weekly" and sequential_context is None:
        raise ValueError(
            "Sequential optimisation requires a SequentialOptimisationContext "
            "with governed weekly plans and carry-in state."
        )
    if evaluation_method == "steady_state_monthly" and sequential_context is not None:
        raise ValueError(
            "sequential_context cannot be supplied for steady-state optimisation."
        )
    if evaluation_method == "sequential_weekly" and posterior_trace is not None:
        raise ValueError(
            "Sequential optimisation search is point-estimate by decision. "
            "Posterior uncertainty must be evaluated separately through the "
            "sequential scenario-evaluation path; it is not silently replaced "
            "with steady-state uncertainty."
        )
    # G2A.7a.10: when value_mapping is given, it is the single authoritative
    # value source - used for objective resolution, the SLSQP objective
    # function, the current/optimised predicted-value calculations, and
    # posterior evaluation alike, replacing the previous split where target
    # resolution used catalogue weights but calculation used legacy ltv.
    effective_ltv = (
        dict(value_mapping.value_by_outcome_id) if value_mapping is not None else ltv
    )
    # --- Outcome-approval gate (G2A.7a.2, G2A.7a.3, REQ-PLAN-001, REQ-USE-001) ---
    # G2A.7a.10 (brief section 12.1): cheap, fast-fail presence checks only -
    # a friendlier error before the (possibly deprecated-string) objective is
    # even resolved. Per-target approval validation (status, expiry, scope,
    # use, NBT completeness) is no longer duplicated here - it happens
    # exactly once, in resolve_planning_governance() below, which is the
    # single authoritative approval decision for this optimisation.
    # Official mode: fail closed. Missing or empty approval collections block.
    # Track whether the caller gave ANY objective information at all
    # (a typed object, or a legacy string) *before* reconstruction below.
    _caller_gave_objective_info = (
        objective is not None or planning_objective is not None
    )
    if governance_mode == "official":
        if outcome_approvals is None or len(outcome_approvals) == 0:
            raise OutcomeApprovalBlockedError(
                "Official optimisation blocked: no outcome approvals are "
                "configured. Official use requires at least one active "
                "OutcomeApproval. Pass governance_mode='exploratory' for "
                "non-official optimisation."
            )
        if not _caller_gave_objective_info:
            raise ObjectiveMissingError(
                "Official optimisation blocked: no objective provided. "
                "Official optimisation requires an explicit objective. "
                "Pass governance_mode='exploratory' for non-official "
                "optimisation, or provide an objective."
            )
    # --- end outcome-approval gate ---
    constraints = constraints or []
    # G2A.7a.10 (brief section 13): a new official artefact must state its
    # kind explicitly - never inferred from whether constraints happen to be
    # present. Resolved after the outcome-approval gate (so a missing
    # approval/objective still raises its own specific error first) but
    # before the slow SLSQP optimisation runs. Exploratory results keep the
    # legacy inferred fallback (unofficial, never persisted as an official
    # artefact kind).
    resolved_artefact_kind = (
        classify_artefact_kind(constraints, explicit_kind=artefact_kind)
        if governance_mode == "official"
        else (
            artefact_kind
            if artefact_kind is not None
            else (
                "constrained_optimisation" if constraints else "unconstrained_benchmark"
            )
        )
    )
    policy = counterfactual_policy or CounterfactualPolicy()
    if objective is None and planning_objective is None:
        # G2A.7a (REQ-PLAN-001): no implicit default to NBT or any KPI.
        # Nothing to gate - see _caller_gave_objective_info above.
        planning_objective = PlanningObjective(
            counterfactual_policy_fingerprint=policy.fingerprint(),
        )
    elif objective is not None and planning_objective is None:
        warnings.warn(
            "String objectives are deprecated and are migrated to an "
            "incremental PlanningObjective; official workflows must persist "
            "the typed objective.",
            DeprecationWarning,
            stacklevel=2,
        )
        planning_objective = planning_objective_from_legacy(
            objective,
            value_currency=value_currency,
            counterfactual_policy_fingerprint=policy.fingerprint(),
        )
        if target_outcome_ids:
            planning_objective = replace(
                planning_objective,
                target_outcome_ids=tuple(target_outcome_ids),
            )
        elif not planning_objective.target_outcome_ids:
            # G2A.7a.1 (REQ-PLAN-001 section 5.2): a deprecated string
            # objective must resolve to the *exact* set of outcome_ids it
            # would actually optimise over - the same resolution
            # `_objective_weight` itself performs - before approval
            # validation runs, rather than leaving target_outcome_ids empty
            # (which would either block ambiguously on "no target_outcome_ids"
            # for a caller that legitimately meant "every fitted <metric>
            # outcome", or let the gate check a narrower objective than what
            # is actually optimised). Resolution failures (missing ltv,
            # unknown weights, an objective with no matching fitted outcomes)
            # are deliberately swallowed here and left to surface naturally,
            # with a more specific message, from `_objective_factory`'s own
            # call to `_objective_weight` later in this function.
            try:
                resolved_weight = _objective_weight(
                    objective,
                    meta,
                    effective_ltv,
                    None,
                    weights,
                    assume_value_scaled_weights=assume_value_scaled_weights,
                )
                resolved_ids = tuple(sorted(resolved_weight))
            except ValueError:
                resolved_ids = ()
            if resolved_ids:
                planning_objective = replace(
                    planning_objective,
                    target_outcome_ids=resolved_ids,
                )
    # G2A.7a (REQ-PLAN-001, DEFECT-9): no implicit NBT fallback.
    # legacy_objective is derived from the resolved objective, never from a
    # hard-coded default. It is used only for labelling/economics, not for
    # target selection (which comes from planning_objective.target_outcome_ids).
    legacy_objective = (
        planning_objective.metric_key
        if planning_objective and planning_objective.metric_key
        else (objective if objective else "")
    )
    # G2A.7a.10 (brief section 12.1): the deprecated objective= string path
    # resolves planning_objective above; whether it came from a typed
    # PlanningObjective or a legacy string, resolve_planning_governance below
    # is the one and only per-target approval resolution - no separate
    # re-gate for the string-objective path.
    # G2A.7a.6: resolve governance via shared resolver.
    # Fail before expensive work, never reconstruct after.
    _resolved_gov: Optional[ResolvedPlanningGovernance] = None
    if governance_mode == "official" and planning_objective is not None:
        from .planning_governance import resolve_planning_governance

        _resolved_gov = resolve_planning_governance(
            operation="optimisation",
            planning_objective=planning_objective,
            model_approval=approval,
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            market=market,
            meta=meta,
            outcome_approvals=outcome_approvals or [],
            nbt_completeness_metadata=nbt_completeness_metadata,
            approval_readiness=approval_readiness,
            current_policy=current_policy,
        )

    # PR 88B: discloses the actual planning-engine semantics this
    # optimisation was evaluated under - replaces PR 82E's
    # zero_carry_in_adstock_state disclosure (see PlanningEvaluationSemantics
    # and evaluate_manual_scenario's identical block above).
    _planning_semantics: Optional[PlanningEvaluationSemantics] = None
    if governance_mode == "official":
        _planning_semantics = (
            SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS
            if evaluation_method == "sequential_weekly"
            else CURRENT_PLANNING_EVALUATION_SEMANTICS
        )

    current_spend = _flatten(current_spend_plan, months, channels)

    activity_map = (
        activity_by_model_input(activity_definitions, market)
        if activity_definitions is not None
        else {}
    )
    resource: Optional[OptimizationResource] = None
    resource_channels: Optional[List[str]] = None
    reference_resource_total: Optional[float] = None
    optimisation_resource_total: Optional[float] = None
    if activity_definitions is not None:
        missing_activity = set(channels) - set(activity_map)
        if missing_activity:
            raise ValueError(
                f"Missing activity definitions for {sorted(missing_activity)}"
            )
        # Every period's date, not just the first - a multi-month plan can
        # cross a mapping's effective-date boundary, so resource
        # eligibility/currency must hold across the whole plan, not just
        # its first month (PR G2A.6b Codex follow-up).
        resource_cost_as_of_dates = [
            (cost_as_of_by_month or {}).get(month) for month in months
        ]
        resource = optimization_resource or monetary_optimization_resource(
            activity_definitions,
            market,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id or "default",
            cost_as_of_dates=resource_cost_as_of_dates,
            channels=channels,
        )
        # Validate unconditionally - a caller-supplied `optimization_resource`
        # cannot be trusted to already respect these rules, and the default
        # resource is cheap to re-check for defense in depth (PR G2A.6b
        # workstream 1). Raises before the (potentially slow) SLSQP call.
        validate_optimization_resource(
            resource,
            activity_definitions,
            market,
            channels,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id or "default",
            cost_as_of_dates=resource_cost_as_of_dates,
            governance_mode=governance_mode,
        )
        resource_channels = [
            channel
            for channel in channels
            if activity_map[channel].activity_id in resource.eligible_activity_ids
        ]

    _governed_constraint_resolution = None
    if governed_constraints:
        # REQ-OPT-001 Requirement 2/5: the extended constraint-kind
        # vocabulary replaces (never supplements) the legacy `constraints`
        # bounds-building for this call - resolved via the real,
        # already-tested function this vocabulary itself delegates to
        # (build_bounds_and_constraints), not a reimplementation.
        from .optimization_constraint_vocabulary import resolve_governed_constraints

        _governed_constraint_resolution = resolve_governed_constraints(
            governed_constraints,
            months=months,
            channels=channels,
            current_spend=[float(v) for v in current_spend],
            resource_channels=resource_channels,
        )
        if not _governed_constraint_resolution.is_feasible:
            cells_desc = "; ".join(
                f"{month}/{channel} (lower={lo}, upper={hi})"
                for month, channel, lo, hi in _governed_constraint_resolution.infeasible_cells
            )
            raise GovernedConstraintInfeasibleError(
                "Optimisation is infeasible under the supplied governed "
                f"constraints: {len(_governed_constraint_resolution.infeasible_cells)} "
                f"cell(s) have a lower bound exceeding the upper bound: "
                f"{cells_desc}. Relax or remove a conflicting constraint - "
                "results are never silently clamped or dropped."
            )
        bounds: List[Tuple[float, float]] = [
            (float(lo), float(hi)) for lo, hi in _governed_constraint_resolution.bounds
        ]
        linear_constraints: List[LinearConstraint] = list(
            _governed_constraint_resolution.legacy_constraints
        )
    else:
        bounds, linear_constraints = build_bounds_and_constraints(
            months,
            channels,
            current_spend,
            constraints,
            resource_channels=resource_channels,
        )

    _capacity_application_result = None
    if capacity_limits:
        # REQ-CAP-001/REQ-OPT-001 Requirement 4 (Decision 18): composable
        # with whichever constraint bounds were already resolved above -
        # apply_capacity_limits_to_bounds performs no feasibility check
        # itself (it composes with whatever bounds it is given), so this
        # function checks feasibility of the combined result.
        from .capacity_plan_application import apply_capacity_limits_to_bounds

        _capacity_application_result = apply_capacity_limits_to_bounds(
            bounds,
            months=months,
            channels=channels,
            limits=capacity_limits,
            realised_by_limit_and_period=capacity_realised_by_limit_and_period,
            unit_to_spend_rate_by_limit_id=capacity_unit_to_spend_rate_by_limit_id,
        )
        bounds = [
            (float(lo), float(hi)) for lo, hi in _capacity_application_result.bounds
        ]
        _capacity_infeasible_cells = [
            (months[i // len(channels)], channels[i % len(channels)], lo, hi)
            for i, (lo, hi) in enumerate(bounds)
            if lo > hi
        ]
        if _capacity_infeasible_cells:
            cells_desc = "; ".join(
                f"{month}/{channel} (lower={lo}, upper={hi})"
                for month, channel, lo, hi in _capacity_infeasible_cells
            )
            raise CapacityLimitInfeasibleError(
                "Optimisation is infeasible after applying the supplied capacity "
                f"limits: {len(_capacity_infeasible_cells)} cell(s) have a lower "
                f"bound exceeding the upper bound: {cells_desc}. Relax or remove a "
                "conflicting capacity limit or constraint - results are never "
                "silently clamped or dropped."
            )

    if activity_definitions is not None:
        # Every channel outside this optimisation resource - not just the
        # ones explicitly marked non-optimisable - is held fixed for this
        # run. A response-only/quantity activity marked "optimisable" for
        # scenario purposes is still not denominated in this resource's
        # unit, so it must never be traded against it (PR G2A.6 workstream A).
        # `resource.eligible_activity_ids` is already validated above, so
        # membership alone is sufficient here.
        for month in months:
            for channel in channels:
                definition = activity_map[channel]
                if definition.activity_id not in resource.eligible_activity_ids:
                    index = _cell_index(month, channel, months, channels)
                    value = float(current_spend[index])
                    bounds[index] = (value, value)

    if conserve_total_budget:
        if resource is not None:
            eligible_indices = [
                _cell_index(month, channel, months, channels)
                for month in months
                for channel in resource_channels
            ]
            # `resource_channels` is non-empty here: validate_optimization_resource
            # above already rejected an empty resource, and every eligible
            # activity ID was confirmed present among `channels`.
            reference_resource_total = float(current_spend[eligible_indices].sum())
            optimisation_resource_total = (
                float(resource.total)
                if resource.total is not None
                else reference_resource_total
            )
            total_row = np.zeros(len(current_spend))
            total_row[eligible_indices] = 1
            linear_constraints.append(
                LinearConstraint(
                    total_row,
                    lb=optimisation_resource_total,
                    ub=optimisation_resource_total,
                )
            )
        else:
            reference_resource_total = float(current_spend.sum())
            optimisation_resource_total = reference_resource_total
            total_row = np.ones(len(current_spend))
            linear_constraints.append(
                LinearConstraint(
                    total_row, lb=current_spend.sum(), ub=current_spend.sum()
                )
            )

    objective_fn = _objective_factory(
        months,
        channels,
        market,
        meta,
        params,
        reference_context_by_month,
        effective_ltv,
        legacy_objective,
        model_type,
        target_outcome_ids=target_outcome_ids,
        weights=weights,
        assume_value_scaled_weights=assume_value_scaled_weights,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        planning_objective=planning_objective,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        activity_definitions=activity_definitions,
        counterfactual_policy=policy,
        sequential_context=sequential_context,
    )

    result = minimize(
        objective_fn,
        current_spend,
        method="SLSQP",
        bounds=bounds,
        constraints=linear_constraints,
        options={"maxiter": max_iter, "ftol": 1e-8},
    )

    # REQ-OPT-001 Requirement 4: disclose which governed constraints were
    # actually binding at the SLSQP solution - never buried in raw bounds.
    # A disclosure is "binding" if the optimised cell landed at the final
    # (possibly multiply-tightened) lower or upper bound for at least one
    # of its covered (month, channel) cells.
    _governed_constraint_disclosures: List[dict] = []
    if _governed_constraint_resolution is not None:
        _clipped_x = np.clip(result.x, 0, None)
        _bind_tol = 1e-6
        for _d in _governed_constraint_resolution.disclosures:
            binding = False
            if _d.channel is not None:
                for _month in _d.months:
                    _idx = _cell_index(_month, _d.channel, months, channels)
                    _lo, _hi = bounds[_idx]
                    _x = float(_clipped_x[_idx])
                    if abs(_x - _lo) <= max(_bind_tol, _bind_tol * abs(_lo)) or abs(
                        _x - _hi
                    ) <= max(_bind_tol, _bind_tol * abs(_hi)):
                        binding = True
                        break
            _governed_constraint_disclosures.append(
                {**_d.to_dict(), "binding": binding}
            )

    optimized_plan = _unflatten(np.clip(result.x, 0, None), months, channels)

    optimized_scenario_plan = (
        classify_activity_plan(
            optimized_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
        if activity_definitions is not None
        else None
    )
    current_scenario_plan = (
        classify_activity_plan(
            current_spend_plan,
            market=market,
            activity_definitions=activity_definitions,
        )
        if activity_definitions is not None
        else None
    )
    # G2A.7a.9: use private numerical function directly — governance has
    # already been resolved and validated by the optimiser's own gate.
    _calculate_kwargs = dict(
        model_type=model_type,
        cost_mapping_registry=cost_mapping_registry,
        cost_context_id=cost_context_id,
        cost_as_of_by_month=cost_as_of_by_month,
        counterfactual_media_input_by_month=counterfactual_media_input_by_month,
        planning_objective=planning_objective,
        activity_definitions=activity_definitions,
        counterfactual_policy=policy,
    )
    if sequential_context is not None:
        from .sequential_optimisation_tractability import compute_sequential_plan_pair

        optimized_weekly_plan = sequential_context.candidate_plan(optimized_plan)
        current_weekly_plan = sequential_context.candidate_plan(current_spend_plan)
        optimized_weekly, optimized_reference, _ = compute_sequential_plan_pair(
            optimized_weekly_plan,
            sequential_context.reference_plan,
            sequential_context.carry_in,
            meta,
            cast(FHPosteriorParams, params),
            model_type=model_type,
            named_event_fit_inputs=sequential_context.named_event_fit_inputs,
        )
        current_weekly, current_reference, _ = compute_sequential_plan_pair(
            current_weekly_plan,
            sequential_context.reference_plan,
            sequential_context.carry_in,
            meta,
            cast(FHPosteriorParams, params),
            model_type=model_type,
            named_event_fit_inputs=sequential_context.named_event_fit_inputs,
        )
        predicted = _sequential_pair_to_prediction_frame(
            candidate=optimized_weekly,
            reference=optimized_reference,
            spend_plan=optimized_plan,
            meta=meta,
            ltv=effective_ltv,
            activity_definitions=activity_definitions,
            market=market,
            planning_objective=planning_objective,
            scenario_plan=optimized_scenario_plan,
            counterfactual_policy=policy,
        )
        current_predicted = _sequential_pair_to_prediction_frame(
            candidate=current_weekly,
            reference=current_reference,
            spend_plan=current_spend_plan,
            meta=meta,
            ltv=effective_ltv,
            activity_definitions=activity_definitions,
            market=market,
            planning_objective=planning_objective,
            scenario_plan=current_scenario_plan,
            counterfactual_policy=policy,
        )
    else:
        predicted = _calculate_scenario(
            optimized_plan,
            market,
            meta,
            params,
            reference_context_by_month,
            effective_ltv,
            scenario_plan=optimized_scenario_plan,
            **_calculate_kwargs,
        )
        current_predicted = _calculate_scenario(
            current_spend_plan,
            market,
            meta,
            params,
            reference_context_by_month,
            effective_ltv,
            scenario_plan=current_scenario_plan,
            **_calculate_kwargs,
        )

    # Evaluated via the same objective_fn used for optimisation (not
    # re-derived from the predicted DataFrames) so "current" and "optimised"
    # totals are guaranteed to use the identical weighting - no risk of the
    # two diverging from a second, hand-written copy of the eligibility logic.
    current_objective_value = -float(objective_fn(current_spend))
    posterior_evaluation = None
    if posterior_trace is not None and sequential_context is None:
        from .uncertainty import evaluate_scenario_with_uncertainty

        # G2A.7a.10: posterior evaluation uses the same approval/objective/
        # outcome_approvals the optimiser itself already resolved above, and
        # inherits the optimiser's own governance_mode/operation - it is not
        # a second, independent resolution against different inputs.
        posterior_evaluation = evaluate_scenario_with_uncertainty(
            optimized_plan,
            market,
            meta,
            posterior_trace,
            reference_context_by_month,
            effective_ltv,
            model_type=model_type,
            n_draws=posterior_evaluation_draws,
            approval=approval,
            model_run_id=model_run_id,
            data_fingerprint=data_fingerprint,
            model_spec_fingerprint=model_spec_fingerprint,
            posterior_fingerprint=posterior_fingerprint,
            baseline_spend_plan=current_spend_plan,
            scenario_plan=optimized_scenario_plan,
            baseline_scenario_plan=current_scenario_plan,
            activity_definitions=activity_definitions,
            counterfactual_policy=policy,
            planning_objective=planning_objective,
            cost_mapping_registry=cost_mapping_registry,
            cost_context_id=cost_context_id,
            cost_as_of_by_month=cost_as_of_by_month,
            outcome_approvals=outcome_approvals,
            governance_mode=governance_mode,
            operation="optimisation",
            nbt_completeness_metadata=nbt_completeness_metadata,
            value_mapping=value_mapping,
            approval_readiness=approval_readiness,
            current_policy=current_policy,
        )

    return {
        "success": bool(result.success),
        "message": str(result.message),
        "spend_plan": optimized_plan,
        "scenario_plan": (
            optimized_scenario_plan.to_dict()
            if optimized_scenario_plan is not None
            else ScenarioPlan.from_legacy_spend_plan(optimized_plan).to_dict()
        ),
        "predicted": predicted,
        "current_predicted": current_predicted,
        "objective_value": -float(result.fun),
        "current_objective_value": current_objective_value,
        "posterior_evaluation": posterior_evaluation,
        "cost_mapping_fingerprint": (
            cost_mapping_registry.fingerprint()
            if cost_mapping_registry is not None
            else None
        ),
        # G2A.7a.10: the exact value_mapping/currency_context used for this
        # calculation, for the caller to persist unchanged via
        # governance_deps_from_optimizer_result - never recomputed later.
        "value_mapping_id": (
            value_mapping.mapping_id if value_mapping is not None else None
        ),
        "value_mapping_fingerprint": (
            value_mapping.fingerprint if value_mapping is not None else None
        ),
        "currency_context_fingerprint": (
            currency_context.fingerprint() if currency_context is not None else None
        ),
        "planning_objective": (
            planning_objective.to_dict()
            if planning_objective is not None
            else {
                "estimand": "total_outcome",
                "legacy_objective": legacy_objective,
            }
        ),
        "counterfactual_policy": policy.to_dict(),
        "counterfactual_policy_fingerprint": policy.fingerprint(),
        "optimization_resource": resource.to_dict() if resource is not None else None,
        "reference_resource_total": reference_resource_total,
        "optimisation_resource_total": optimisation_resource_total,
        "governance_mode": governance_mode,
        "activity_definitions_fingerprint": (
            activity_definitions_fingerprint(activity_definitions)
            if activity_definitions is not None
            else None
        ),
        # G2A.7a.10: resolved once, up front (see resolved_artefact_kind
        # above) - required explicitly for official artefacts, never
        # inferred from constraints for those.
        "artefact_kind": resolved_artefact_kind,
        # G2A.7a.3: resolved governance context for persistence
        "_resolved_governance": (
            _resolved_gov.to_dict() if _resolved_gov is not None else None
        ),
        # PR 88B: planning-evaluation-semantics disclosure (see
        # PlanningEvaluationSemantics) - replaces PR 82E's adstock_state_
        # fingerprint disclosure for steady-state evaluation.
        "planning_semantics_fingerprint": (
            _planning_semantics.fingerprint()
            if _planning_semantics is not None
            else None
        ),
        "evaluation_method": evaluation_method,
        "sequential_optimisation_strategy": (
            "T1_direct_replay_point_estimate"
            if evaluation_method == "sequential_weekly"
            else None
        ),
        "sequential_optimisation_objective_horizon": (
            "O1_plan_window_total" if evaluation_method == "sequential_weekly" else None
        ),
        # REQ-OPT-001 Requirement 2/4: only populated when governed_constraints
        # was supplied - empty (never None) otherwise, so a caller can always
        # iterate without a None-check.
        "governed_constraint_disclosures": _governed_constraint_disclosures,
        "governed_constraint_vocabulary_version": (
            _governed_constraint_resolution.vocabulary_version
            if _governed_constraint_resolution is not None
            else None
        ),
        # REQ-CAP-001/REQ-OPT-001 Requirement 4: only populated when
        # capacity_limits was supplied - empty (never None) otherwise.
        "capacity_disclosures": (
            [d.to_dict() for d in _capacity_application_result.disclosures]
            if _capacity_application_result is not None
            else []
        ),
        "capacity_binding_reports": (
            [r.to_dict() for r in _capacity_application_result.binding_reports]
            if _capacity_application_result is not None
            else []
        ),
        "capacity_plan_application_version": (
            _capacity_application_result.version
            if _capacity_application_result is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Scenario save/reload
# ---------------------------------------------------------------------------


def scenario_to_dict(
    name: str,
    market: str,
    spend_plan: Dict[str, Dict[str, float]],
    objective: str,
    constraints: List[SpendConstraint],
    notes: str = "",
    cost_mapping_fingerprint: Optional[str] = None,
    planning_objective: Optional[PlanningObjective | Dict[str, object]] = None,
    activity_definitions_fingerprint: Optional[str] = None,
    scenario_plan: Optional[ScenarioPlan] = None,
    counterfactual_policy: Optional[CounterfactualPolicy | Dict[str, object]] = None,
    economics_coverage: Optional[Dict[str, object]] = None,
    governance_mode: Optional[str] = None,
    # G2A.7a.2: governance dependency identity
    model_run_id: Optional[str] = None,
    model_approval_fingerprint: Optional[str] = None,
    data_fingerprint: Optional[str] = None,
    model_spec_fingerprint: Optional[str] = None,
    posterior_fingerprint: Optional[str] = None,
    outcome_authorisations: Optional[List[dict]] = None,
    nbt_completeness_fingerprint: Optional[str] = None,
    # G2A.7a.4: explicit artefact kind and structured governance deps
    artefact_kind: Optional[str] = None,
    governance_dependencies: Optional[ScenarioGovernanceDependencies] = None,
    scenario_value_assumptions: Optional[Mapping[str, object]] = None,
) -> dict:
    objective_payload = (
        planning_objective.to_dict()
        if isinstance(planning_objective, PlanningObjective)
        else planning_objective
    )
    policy_payload = (
        counterfactual_policy.to_dict()
        if isinstance(counterfactual_policy, CounterfactualPolicy)
        else counterfactual_policy
    )
    typed_plan = scenario_plan or ScenarioPlan.from_legacy_spend_plan(spend_plan)

    # G2A.7a.4: use typed governance dependencies when provided.
    if governance_dependencies is not None:
        governance_deps = governance_dependencies.to_dict()
    else:
        # G2A.7a.2: versioned governance dependency block so a change to any
        # calculation-relevant dependency makes the saved official scenario stale.
        governance_deps: dict = {
            "model_run_id": model_run_id,
            "model_approval_fingerprint": model_approval_fingerprint,
            "data_fingerprint": data_fingerprint,
            "model_spec_fingerprint": model_spec_fingerprint,
            "posterior_fingerprint": posterior_fingerprint,
            "planning_objective_fingerprint": (
                fingerprint_planning_objective(planning_objective)
                if isinstance(planning_objective, PlanningObjective)
                else None
            ),
            "outcome_authorisations": outcome_authorisations or [],
            "activity_definitions_fingerprint": activity_definitions_fingerprint,
            "cost_mapping_fingerprint": cost_mapping_fingerprint,
            "counterfactual_policy_fingerprint": (
                CounterfactualPolicy.from_dict(policy_payload).fingerprint()
                if policy_payload
                else None
            ),
            "nbt_completeness_fingerprint": nbt_completeness_fingerprint,
            # PR 88B: this legacy inline-dict path has no way to know the
            # planning semantics a caller evaluated under - left unset
            # (never fabricated), so such a scenario correctly reads as
            # legacy_unverified rather than falsely "current".
            "planning_semantics_fingerprint": None,
        }

    # G2A.7a.10 (brief section 13): a new official artefact must state its
    # kind explicitly - never inferred from constraints. Non-official saves
    # (governance_mode != "official", including the historical None default)
    # keep the legacy inferred fallback for backward compatibility.
    if governance_mode == "official":
        resolved_kind = classify_artefact_kind(constraints, explicit_kind=artefact_kind)
    else:
        resolved_kind = artefact_kind
        if resolved_kind is None:
            resolved_kind = (
                "constrained_optimisation" if constraints else "manual_scenario"
            )
        elif resolved_kind not in ARTEFACT_KINDS:
            raise ValueError(
                f"Unknown artefact kind {resolved_kind!r}. "
                f"Must be one of {sorted(ARTEFACT_KINDS)}."
            )

    return {
        "name": name,
        "market": market,
        "spend_plan": spend_plan,
        "scenario_plan": typed_plan.to_dict(),
        "objective": objective,
        "constraints": [c.to_dict() for c in constraints],
        "notes": notes,
        "cost_mapping_fingerprint": cost_mapping_fingerprint,
        "planning_objective": objective_payload,
        "activity_definitions_fingerprint": activity_definitions_fingerprint,
        "counterfactual_policy": policy_payload,
        "counterfactual_policy_fingerprint": (
            CounterfactualPolicy.from_dict(policy_payload).fingerprint()
            if policy_payload
            else None
        ),
        "economics_coverage": economics_coverage,
        # WP2G: preserve the exact forward-assumption bundle used for this
        # scenario.  This is provenance, not a historical-value fallback.
        "scenario_value_assumptions": (
            dict(scenario_value_assumptions)
            if scenario_value_assumptions is not None
            else None
        ),
        "governance_mode": governance_mode,
        "governance_dependencies": governance_deps,
        "artefact_kind": resolved_kind,
        # PR 88B: bumped from 3 to 4 - schema 4 requires
        # governance_dependencies.planning_semantics_fingerprint for an
        # official scenario to be current (see validate_scenario_dependencies
        # and scenario_from_dict's migration below).
        "schema_version": 4,
    }


def scenario_from_dict(d: dict) -> dict:
    d = dict(d)
    # WP5 part 4: a sequential-weekly scenario (`core.sequential_scenario_
    # evaluation.sequential_scenario_to_dict`) has no `spend_plan`/
    # `objective`/`scenario_plan` in the steady-state shape this legacy-
    # migration logic below assumes - it is a new schema starting now, with
    # nothing to migrate from, so it passes through unchanged rather than
    # having steady-state-specific fields spuriously injected into it.
    if d.get("calculation_method") == "sequential_weekly":
        return d
    schema_ver = d.get("schema_version", 1)
    if "scenario_plan" not in d:
        d["scenario_plan"] = ScenarioPlan.from_legacy_spend_plan(
            d.get("spend_plan", {})
        ).to_dict()
        d["schema_version"] = max(schema_ver, 2)
    if not d.get("planning_objective") and d.get("objective"):
        try:
            d["planning_objective"] = planning_objective_from_legacy(
                d["objective"]
            ).to_dict()
        except ValueError:
            # G2A.7a.10: a legacy 'value'/'expected_value' objective with no
            # governed currency on record cannot be migrated to a typed
            # PlanningObjective without inventing a currency. Retain the
            # original objective string and predictions; leave
            # planning_objective unset so official use stays blocked via the
            # legacy_unverified path below (loadable does not mean
            # officially usable).
            d["planning_objective"] = None
            d["_legacy_unverified_reason"] = "missing_value_currency"
            d.setdefault("_migrated_from_schema", schema_ver)
    # G2A.7a.4: migrate older schema versions — add empty governance
    # dependencies block and mark as legacy_unverified.
    # G2A.7a.9: includes value_mapping_fingerprint, currency_context_fingerprint,
    # and FX fields.
    if "governance_dependencies" not in d:
        d["governance_dependencies"] = {
            "model_run_id": None,
            "model_approval_fingerprint": None,
            "data_fingerprint": None,
            "model_spec_fingerprint": None,
            "posterior_fingerprint": None,
            "planning_objective_fingerprint": None,
            "outcome_authorisations": [],
            "value_mapping_id": None,
            "value_mapping_fingerprint": None,
            "currency_context_fingerprint": None,
            "historical_fx_rate_set_id": None,
            "historical_fx_rate_set_fingerprint": None,
            "future_fx_assumption_id": None,
            "future_fx_assumption_fingerprint": None,
            "activity_definitions_fingerprint": d.get(
                "activity_definitions_fingerprint"
            ),
            "cost_mapping_fingerprint": d.get("cost_mapping_fingerprint"),
            "counterfactual_policy_fingerprint": d.get(
                "counterfactual_policy_fingerprint"
            ),
            "nbt_completeness_fingerprint": None,
        }
        d["schema_version"] = max(schema_ver, 3)
    # PR 88B: migrate schema < 4 — add a null planning_semantics_fingerprint
    # and bump the schema version. A schema-3 scenario (with only PR 82E's
    # adstock_state_fingerprint, if anything) is loadable here but must not
    # read as "current": it predates the truthful planning-semantics
    # disclosure entirely, so there is nothing to compare against the
    # current engine's semantics fingerprint. See
    # validate_scenario_dependencies.
    deps_block = d.get("governance_dependencies") or {}
    if "planning_semantics_fingerprint" not in deps_block:
        deps_block = dict(deps_block)
        deps_block["planning_semantics_fingerprint"] = None
        d["governance_dependencies"] = deps_block
        d["schema_version"] = max(schema_ver, d.get("schema_version", schema_ver), 4)
    # G2A.7a.4: migrate artefact_kind from legacy scenarios
    if "artefact_kind" not in d:
        # Legacy: infer from constraints — but then mark as migrated
        has_constraints = bool(d.get("constraints"))
        d["artefact_kind"] = (
            "constrained_optimisation" if has_constraints else "manual_scenario"
        )
        d["_migrated_from_schema"] = max(
            d.get("_migrated_from_schema", schema_ver),
            schema_ver,
        )
    # A migrated scenario retains its original schema version for staleness
    # detection — adding null fields does not make it "current". PR 88B:
    # bumped from 3 to 4 — every pre-88B official scenario (schema 1-3)
    # predates planning-semantics disclosure and must migrate to
    # legacy_unverified, not silently remain "current".
    if schema_ver < 4:
        d["_migrated_from_schema"] = schema_ver
    d["constraints"] = [SpendConstraint.from_dict(c) for c in d.get("constraints", [])]
    return d


def resolve_scenario_cost_mapping_fingerprint(
    artifact: Mapping[str, object],
) -> Optional[str]:
    """Resolve the cost-mapping dependency fingerprint an artifact
    (scenario or curve metadata dict) actually depends on (Corrective PR
    E2.1) - the one canonical resolution path every freshness check must
    use, rather than each reading a field directly.

    The current, governed contract is the nested
    ``governance_dependencies.cost_mapping_fingerprint``:
    ``scenario_to_dict`` always populates it (directly or via
    ``ScenarioGovernanceDependencies.to_dict()``) whenever a cost mapping
    was actually used to evaluate the scenario. The top-level
    ``cost_mapping_fingerprint`` field is supported only as an explicit
    legacy fallback for artifacts that predate the nested governance-
    dependencies block (or that never had one, e.g. some curve-metadata
    dicts). When both are present they must agree - a caller passing
    ``governance_dependencies=`` without also passing the matching
    top-level ``cost_mapping_fingerprint=`` kwarg previously left the
    top-level field ``None`` even though the real dependency existed
    (silently classifying a normal cost-dependent save as
    dependency-free); a genuine conflict between the two is a
    data-integrity problem, never silently resolved by preferring one.
    """
    governance_deps = artifact.get("governance_dependencies") or {}
    nested = (
        governance_deps.get("cost_mapping_fingerprint")
        if isinstance(governance_deps, Mapping)
        else None
    )
    legacy = artifact.get("cost_mapping_fingerprint")
    if nested and legacy and nested != legacy:
        raise ValueError(
            "Artifact has conflicting cost_mapping_fingerprint values between "
            f"the top-level field ({legacy!r}) and governance_dependencies "
            f"({nested!r}); cannot resolve a single cost-mapping dependency."
        )
    return nested or legacy


def require_current_cost_mapping(
    artifact: Dict, current_cost_mapping_fingerprint: str
) -> None:
    """Reject scenarios/curve metadata created under another cost mapping.

    Resolves the dependency via ``resolve_scenario_cost_mapping_fingerprint``
    (Corrective PR E2.1) rather than reading the top-level field directly,
    so a normal scenario save (nested ``governance_dependencies`` only) is
    correctly classified as cost-dependent instead of dependency-free.
    """
    saved = resolve_scenario_cost_mapping_fingerprint(artifact)
    if not saved or saved != current_cost_mapping_fingerprint:
        raise ValueError("Artifact is stale because its governed cost mapping changed")


def governance_deps_from_optimizer_result(result: dict) -> dict:
    """Extract governance dependency block from an ``optimize_scenario``
    result for passing to ``scenario_to_dict``. Returns a dict with all
    fields populated from the resolved governance context embedded in the
    result, or empty-string/None defaults when no resolved governance is
    available (exploratory mode or no planning objective).

    G2A.7a.4: the NBT completeness fingerprint is now sourced from the
    resolved governance's authorisations, not hard-coded to None."""
    resolved = result.get("_resolved_governance") or {}
    # Derive NBT completeness fingerprint from authorisations
    nbt_fingerprint = None
    for auth in resolved.get("authorisations") or []:
        if isinstance(auth, dict) and auth.get("nbt_completeness_fingerprint"):
            nbt_fingerprint = auth["nbt_completeness_fingerprint"]
            break
        elif (
            hasattr(auth, "nbt_completeness_fingerprint")
            and auth.nbt_completeness_fingerprint
        ):
            nbt_fingerprint = auth.nbt_completeness_fingerprint
            break
    return {
        "model_run_id": resolved.get("model_run_id") or "",
        "model_approval_fingerprint": resolved.get("model_approval_fingerprint") or "",
        "data_fingerprint": resolved.get("data_fingerprint") or "",
        "model_spec_fingerprint": resolved.get("model_spec_fingerprint") or "",
        "posterior_fingerprint": resolved.get("posterior_fingerprint") or "",
        "planning_objective_fingerprint": resolved.get("objective_fingerprint") or "",
        "outcome_authorisations": resolved.get("authorisations") or [],
        "value_mapping_id": result.get("value_mapping_id"),
        "value_mapping_fingerprint": result.get("value_mapping_fingerprint"),
        "currency_context_fingerprint": result.get("currency_context_fingerprint"),
        "historical_fx_rate_set_id": result.get("historical_fx_rate_set_id"),
        "historical_fx_rate_set_fingerprint": result.get(
            "historical_fx_rate_set_fingerprint"
        ),
        "future_fx_assumption_id": result.get("future_fx_assumption_id"),
        "future_fx_assumption_fingerprint": result.get(
            "future_fx_assumption_fingerprint"
        ),
        "activity_definitions_fingerprint": result.get(
            "activity_definitions_fingerprint"
        ),
        "cost_mapping_fingerprint": result.get("cost_mapping_fingerprint"),
        "counterfactual_policy_fingerprint": result.get(
            "counterfactual_policy_fingerprint"
        ),
        "nbt_completeness_fingerprint": nbt_fingerprint,
        # PR 88B: adstock_state_fingerprint is deprecated for steady-state -
        # a result dict from optimize_scenario no longer sets it (this key
        # only remains populated for reading a stale in-memory result built
        # before this PR). planning_semantics_fingerprint is the current,
        # actively-validated disclosure.
        "adstock_state_fingerprint": result.get("adstock_state_fingerprint") or "",
        "planning_semantics_fingerprint": (
            result.get("planning_semantics_fingerprint") or ""
        ),
    }


def compare_scenarios(
    scenarios: List[Dict], predicted_key: str = "predicted"
) -> pd.DataFrame:
    """
    Compare total predicted value/volume and spend across saved scenarios.

    `total_value` sums `pred["value"]` skipping any row with no value weight
    (`value is None` - see evaluate_scenario's docstring), `min_count=1` so
    a scenario with `value_status="not configured"` for every row (raw
    units, PR E.2) yields `NaN` here, never a misleading `0.0` -
    `total_value_is_complete` is `False` if any scenario-month had an
    incomplete-coverage row (including "not configured" entirely), so a
    caller can flag the total as a partial/absent sum rather than
    presenting it as exact. `total_gsa` would sum Family History outcomes,
    sign-ups and DNA
    kit sales into one meaningless count if combined - split into
    `total_fh_gsa`/`total_fh_signups`/`total_dna_kits` instead (never
    combined), same metric-aware discipline as
    core.optimization.evaluate_scenario. `fh_gsa`/`fh_signups`/`dna_kits` are
    month-level totals *duplicated* across every outcome_id row within a
    month (see evaluate_scenario's docstring), so they're deduplicated by
    month before summing across a scenario's months - directly summing them
    across every row would overcount by the number of outcome_ids in each
    month.
    """
    rows = []
    for s in scenarios:
        pred = s[predicted_key]
        total_spend = sum(sum(ch.values()) for ch in s["spend_plan"].values())
        has_product_split = "fh_gsa" in pred.columns and "dna_kits" in pred.columns
        if has_product_split:
            dedup_cols = ["fh_gsa", "dna_kits"] + (
                ["fh_signups"] if "fh_signups" in pred.columns else []
            )
            by_month = pred.groupby("month")[dedup_cols].first()
            total_fh_gsa = float(by_month["fh_gsa"].sum())
            total_fh_signups = (
                float(by_month["fh_signups"].sum())
                if "fh_signups" in dedup_cols
                else 0.0
            )
            total_dna_kits = float(by_month["dna_kits"].sum())
        else:
            total_fh_gsa = float(pred["predicted_outcome"].sum())
            total_fh_signups = 0.0
            total_dna_kits = 0.0
        total_value_is_complete = (
            bool(pred["total_value_is_complete"].all())
            if "total_value_is_complete" in pred
            else True
        )
        rows.append(
            {
                "scenario": s["name"],
                "market": s.get("market"),
                "governance_mode": s.get("governance_mode"),
                "total_spend": total_spend,
                "total_value": pred["value"].sum(min_count=1)
                if "value" in pred
                else np.nan,
                "total_value_is_complete": total_value_is_complete,
                "total_fh_gsa": total_fh_gsa,
                "total_fh_signups": total_fh_signups,
                "total_dna_kits": total_dna_kits,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# PR G2A.6c workstream C: there must be one authoritative economics
# implementation. `evaluate_scenario` already computes CPA/ROI correctly
# scoped per month, deliberately nulling whole-plan fields when
# response-only activity contributes to the incremental outcome without a
# corresponding spend (see its `whole_plan_scope_compatible` gate above). A
# caller (the Scenario Planner UI previously had its own
# `_scenario_cpa_summary`) that recomputed total_spend / incremental_outcome
# from raw columns could silently resurrect exactly the number the core
# suppressed. These two helpers only select and de-duplicate columns the
# core already computed - no CPA/ROI arithmetic happens outside
# evaluate_scenario.
# ---------------------------------------------------------------------------

GOVERNED_ECONOMICS_COLUMNS = [
    "whole_plan_incremental_nbt_cpa",
    "paid_media_incremental_nbt_cpa",
    "whole_plan_incremental_roi",
    "paid_media_incremental_roi",
    "whole_plan_cost_per_fh_gsa",
    "paid_media_incremental_cpa",
    "whole_plan_cost_per_dna_kit",
    "whole_plan_cost_per_fh_signup",
]


def monthly_economics_table(predicted_df: pd.DataFrame) -> pd.DataFrame:
    """Governed per-month economics, straight from evaluate_scenario's own
    output columns (`GOVERNED_ECONOMICS_COLUMNS`, whichever are present).
    Every `whole_plan_*` field is already `None` for a month the core
    marked scope-incompatible; `paid_media_*` fields are never suppressed
    this way. De-duplicated by month since every field here is repeated
    once per outcome_id row within a month."""
    cols = [c for c in GOVERNED_ECONOMICS_COLUMNS if c in predicted_df.columns]
    return predicted_df.groupby("month")[cols].first().reset_index()


def whole_plan_scope_compatible(predicted_df: pd.DataFrame) -> bool:
    """True only if every month in `predicted_df` was whole-plan
    scope-compatible (`economics_coverage["whole_plan_scope_compatible"]`) -
    the same condition evaluate_scenario itself checks before populating
    the `whole_plan_*` columns, exposed here so a caller can explain an
    unavailable metric instead of silently omitting it."""
    return bool(
        predicted_df["economics_coverage"]
        .apply(lambda coverage: bool(coverage.get("whole_plan_scope_compatible")))
        .all()
    )


# ---------------------------------------------------------------------------
# Generic single-KPI helpers, kept for reuse
# ---------------------------------------------------------------------------


def calculate_marginal_roi_loglog(
    current_spend: float,
    elasticity: float,
    avg_sales: float,
    avg_spend: float,
) -> float:
    if current_spend <= 0:
        return 0
    return elasticity * (avg_sales / current_spend)


def optimize_budget_marginal_roi(
    total_budget: float,
    channels: List[str],
    elasticities: Dict[str, float],
    current_spend: Dict[str, float],
    avg_sales: float,
    constraints: Optional[Dict[str, Tuple[float, float]]] = None,
) -> Dict[str, float]:
    n_channels = len(channels)
    constraints = constraints or {}
    default_min, default_max = 0.05, 0.80

    min_bounds, max_bounds = [], []
    for ch in channels:
        min_pct, max_pct = constraints.get(ch, (default_min, default_max))
        min_bounds.append(min_pct * total_budget)
        max_bounds.append(max_pct * total_budget)

    def objective(x):
        total_effect = 0
        for i, ch in enumerate(channels):
            if x[i] > 0:
                total_effect += elasticities[ch] * np.log(x[i])
        return -total_effect

    def gradient(x):
        grad = np.zeros(n_channels)
        for i, ch in enumerate(channels):
            if x[i] > 0:
                grad[i] = -elasticities[ch] / x[i]
        return grad

    bounds = list(zip(min_bounds, max_bounds))
    total_current = sum(current_spend.values())
    if total_current > 0:
        x0 = np.array(
            [
                current_spend.get(ch, total_budget / n_channels)
                / total_current
                * total_budget
                for ch in channels
            ]
        )
    else:
        x0 = np.full(n_channels, total_budget / n_channels)
    x0 = np.clip(x0, min_bounds, max_bounds)
    x0 = x0 / x0.sum() * total_budget

    result = minimize(
        objective,
        x0,
        method="SLSQP",
        jac=gradient,
        bounds=bounds,
        constraints={"type": "eq", "fun": lambda x: x.sum() - total_budget},
        options={"maxiter": 1000, "ftol": 1e-10},
    )

    optimal_spend = {ch: max(0, result.x[i]) for i, ch in enumerate(channels)}
    total_allocated = sum(optimal_spend.values())
    if total_allocated > 0:
        for ch in channels:
            optimal_spend[ch] = optimal_spend[ch] / total_allocated * total_budget
    return optimal_spend


def calculate_expected_lift(
    current_spend: Dict[str, float],
    optimal_spend: Dict[str, float],
    elasticities: Dict[str, float],
    current_sales: float,
) -> Dict[str, float]:
    total_pct_change = 0
    for channel in elasticities:
        curr = current_spend.get(channel, 0)
        opt = optimal_spend.get(channel, 0)
        if curr > 0:
            pct_change_spend = (opt - curr) / curr
            total_pct_change += elasticities[channel] * pct_change_spend

    expected_sales = current_sales * (1 + total_pct_change)
    return {
        "current_sales": current_sales,
        "expected_sales": expected_sales,
        "lift": expected_sales - current_sales,
        "lift_pct": total_pct_change * 100,
    }
