"""
Governance resolution, dependency validation, and fingerprinting for
scenario planning and optimisation (G2A.7a.5).

Extracted from core.optimization to separate governance from calculation.
This module adds NEW functionality (resolve_planning_governance,
require_nonblank_dependency) and imports existing types from
core.optimization for backward compatibility.
"""

from __future__ import annotations

from typing import Literal, Sequence

from .approval import ModelApproval, fingerprint_model_approval
from .hierarchical_model import FHModelMeta
from .net_billthrough import NetBillthroughCompletenessMetadata
from .outcome_approval import (
    OutcomeApproval,
    OutcomeApprovalBlockedError,
    find_matching_outcome_approval,
)
from .outcomes import METRIC_KEY_FH_NET_BILLTHROUGH_COUNT
from .optimization import (
    ObjectiveMissingError,
    PlanningObjective,
    ResolvedOutcomeAuthorisation,
    ResolvedPlanningGovernance,
    ScenarioDependencyIssue,
    fingerprint_planning_objective,
)


# ---------------------------------------------------------------------------
# G2A.7a.5: require_nonblank_dependency helper
# ---------------------------------------------------------------------------


def require_nonblank_dependency(
    value: object,
    name: str,
    artefact_id: str = "<unknown>",
    dependency_type: str = "governance_dependency",
) -> list[ScenarioDependencyIssue]:
    """Return a list with one ``invalid`` issue when ``value`` is blank
    (None or empty string), or an empty list when the value is present."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return [
            ScenarioDependencyIssue(
                artefact_id=artefact_id,
                issue_type="invalid",
                detail=f"Mandatory dependency '{name}' is missing or blank.",
                dependency_type=dependency_type,
                reason_code="blank_mandatory_field",
            )
        ]
    return []


# ---------------------------------------------------------------------------
# G2A.7a.5: single governance resolver
# ---------------------------------------------------------------------------


def resolve_planning_governance(
    *,
    operation: Literal["planning", "optimisation"],
    planning_objective: PlanningObjective,
    model_approval: ModelApproval,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
    market: str,
    meta: FHModelMeta,
    outcome_definitions: Sequence[object],
    outcome_approvals: Sequence[OutcomeApproval],
    nbt_completeness_metadata: dict | NetBillthroughCompletenessMetadata | None = None,
) -> ResolvedPlanningGovernance:
    """Resolve planning governance exactly once for a given operation.

    Validates:
    - complete objective with exact fitted target IDs
    - exactly one active approval per target
    - no extra approval records in the resolved proof
    - market, product and segment binding
    - current definition fingerprints
    - required use
    - model approval and identity
    - NBT completeness where required

    Returns an immutable, serialisable ``ResolvedPlanningGovernance`` proof.
    """
    from .outcomes import outcome_catalogue_at_fit_by_id as get_catalogue

    if not planning_objective.is_valid_for_official_planning:
        raise ObjectiveMissingError(
            "Official planning/optimisation requires a complete PlanningObjective "
            "with metric_key and target_outcome_ids."
        )

    catalogue_by_id = get_catalogue(meta)
    target_ids = planning_objective.target_outcome_ids

    auth_list: list[ResolvedOutcomeAuthorisation] = []
    for target_id in target_ids:
        if target_id not in catalogue_by_id:
            raise OutcomeApprovalBlockedError(
                f"Target outcome '{target_id}' is not in the fitted model's "
                "outcome catalogue."
            )
        outcome = catalogue_by_id[target_id]
        matching = find_matching_outcome_approval(
            outcome,
            list(outcome_approvals),
            operation,
            market=market,
            product=outcome.product,
            segment=outcome.segment,
        )
        if matching is None:
            raise OutcomeApprovalBlockedError(
                f"No active '{operation}' approval found for target outcome "
                f"'{target_id}' in market '{market}'."
            )
        nbt_fp = None
        if getattr(outcome, 'metric_key', None) == METRIC_KEY_FH_NET_BILLTHROUGH_COUNT:
            from .net_billthrough import validate_nbt_completeness_metadata_for_outcome
            nbt_issues = validate_nbt_completeness_metadata_for_outcome(
                outcome, nbt_completeness_metadata,
            )
            if nbt_issues:
                raise OutcomeApprovalBlockedError(
                    f"Net Bill-Through target '{target_id}' completeness "
                    f"validation failed: {'; '.join(nbt_issues)}"
                )
            # Use canonical fingerprint from valid metadata
            if isinstance(nbt_completeness_metadata, dict):
                nbt_meta_obj = NetBillthroughCompletenessMetadata.from_dict(
                    nbt_completeness_metadata
                )
            elif isinstance(nbt_completeness_metadata, NetBillthroughCompletenessMetadata):
                nbt_meta_obj = nbt_completeness_metadata
            else:
                raise OutcomeApprovalBlockedError(
                    f"Net Bill-Through target '{target_id}' has invalid "
                    "completeness metadata type."
                )
            nbt_fp = nbt_meta_obj.completeness_fingerprint()

        auth_list.append(ResolvedOutcomeAuthorisation(
            outcome_id=target_id,
            requested_use=operation,
            approval_id=matching.approval_id,
            definition_fingerprint=matching.definition_fingerprint,
            market=market,
            product=outcome.product,
            segment=outcome.segment,
            nbt_completeness_fingerprint=nbt_fp,
        ))

    return ResolvedPlanningGovernance(
        governance_mode="official",
        operation=operation,
        objective_fingerprint=fingerprint_planning_objective(planning_objective),
        model_run_id=model_run_id,
        model_approval_fingerprint=fingerprint_model_approval(model_approval),
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
        market=market,
        authorisations=tuple(auth_list),
        target_outcome_ids=target_ids,
    )
