"""
Pure value objects and dataclasses for planning and optimisation.

PR 51A: Canonical source of planning value objects. These implementations
match the active ``core.optimization`` classes exactly. ``core.optimization``
imports from this module and re-exports for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

PLANNING_ESTIMANDS = frozenset(
    {
        "total_outcome",
        "incremental_outcome",
        "incremental_value",
    }
)


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
            raise OutcomeApprovalBlockedError("Resolved governance is not official.")
        # Use expected_operation when provided — not self.operation
        check_operation = (
            expected_operation if expected_operation is not None else operation
        )
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
    # PR 56D: validation-policy and readiness artefact binding
    validation_policy_id: str = ""
    validation_policy_version: str = ""
    validation_policy_fingerprint: str = ""
    readiness_artefact_id: str = ""
    readiness_fingerprint: str = ""
    diagnostic_artefact_fingerprint: str = ""
    model_identity_fingerprint: str = ""
    # PR 82E: adstock carry-in state this scenario was evaluated under.
    # PR 88B: deprecated for steady-state evaluation - the steady-state
    # engine has no carry-in/terminal-state concept at all (no sequential
    # simulation), so disclosing "zero carry-in" as evidence mischaracterised
    # the calculation as having a carry-in concept it does not model. Kept
    # only so pre-88B official scenarios (schema_version < 4) still
    # deserialize; no longer populated by evaluate_manual_scenario/
    # optimize_scenario. See ``planning_semantics_fingerprint`` below, which
    # replaces it as the truthful, actively-validated disclosure.
    adstock_state_fingerprint: str = ""
    # PR 88B: fingerprint of the PlanningEvaluationSemantics this scenario
    # was evaluated under - truthfully states the engine, temporal
    # resolution, within-period media assumption, and whether carry-in/
    # terminal adstock state apply at all. Unlike adstock_state_fingerprint,
    # this IS an actively validated dependency (see
    # validate_scenario_dependencies) - a scenario missing it, or whose
    # value no longer matches the current semantics, is not officially
    # current.
    planning_semantics_fingerprint: str = ""

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
            "validation_policy_id": self.validation_policy_id,
            "validation_policy_version": self.validation_policy_version,
            "validation_policy_fingerprint": self.validation_policy_fingerprint,
            "readiness_artefact_id": self.readiness_artefact_id,
            "readiness_fingerprint": self.readiness_fingerprint,
            "diagnostic_artefact_fingerprint": self.diagnostic_artefact_fingerprint,
            "model_identity_fingerprint": self.model_identity_fingerprint,
            "adstock_state_fingerprint": self.adstock_state_fingerprint,
            "planning_semantics_fingerprint": self.planning_semantics_fingerprint,
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
            historical_fx_rate_set_fingerprint=d.get(
                "historical_fx_rate_set_fingerprint"
            ),
            future_fx_assumption_id=d.get("future_fx_assumption_id"),
            future_fx_assumption_fingerprint=d.get("future_fx_assumption_fingerprint"),
            activity_definitions_fingerprint=d.get("activity_definitions_fingerprint"),
            cost_mapping_fingerprint=d.get("cost_mapping_fingerprint"),
            counterfactual_policy_fingerprint=d.get(
                "counterfactual_policy_fingerprint", ""
            ),
            nbt_completeness_fingerprint=d.get("nbt_completeness_fingerprint"),
            validation_policy_id=d.get("validation_policy_id", ""),
            validation_policy_version=d.get("validation_policy_version", ""),
            validation_policy_fingerprint=d.get("validation_policy_fingerprint", ""),
            readiness_artefact_id=d.get("readiness_artefact_id", ""),
            readiness_fingerprint=d.get("readiness_fingerprint", ""),
            diagnostic_artefact_fingerprint=d.get(
                "diagnostic_artefact_fingerprint", ""
            ),
            model_identity_fingerprint=d.get("model_identity_fingerprint", ""),
            adstock_state_fingerprint=d.get("adstock_state_fingerprint", ""),
            planning_semantics_fingerprint=d.get("planning_semantics_fingerprint", ""),
        )


# ---------------------------------------------------------------------------
# Adstock state (starting and terminal)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdstockState:
    """Starting and terminal adstock states for scenario planning.

    PR 72F: The starting adstock is the media stock carried into the
    planning window from prior spend. The terminal adstock is the stock
    remaining at the end, which can be passed to the next planning period.
    """

    channel_adstock_start: tuple[tuple[str, float], ...] = ()
    channel_adstock_terminal: tuple[tuple[str, float], ...] = ()
    as_of_date: str = ""

    def fingerprint(self) -> str:
        raw = json.dumps(
            {
                "channel_adstock_start": tuple(sorted(self.channel_adstock_start)),
                "channel_adstock_terminal": tuple(
                    sorted(self.channel_adstock_terminal)
                ),
                "as_of_date": self.as_of_date,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict:
        return {
            "channel_adstock_start": list(self.channel_adstock_start),
            "channel_adstock_terminal": list(self.channel_adstock_terminal),
            "as_of_date": self.as_of_date,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AdstockState":
        return cls(
            channel_adstock_start=tuple(
                tuple(x) for x in d.get("channel_adstock_start", [])
            ),
            channel_adstock_terminal=tuple(
                tuple(x) for x in d.get("channel_adstock_terminal", [])
            ),
            as_of_date=d.get("as_of_date", ""),
        )


def zero_carry_in_adstock_state(
    channels: Iterable[str], as_of_date: str
) -> AdstockState:
    """The adstock carry-in every scenario actually starts from today.

    PR 82E: ``geometric_adstock_matrix`` (core.transformations) has no
    initial-state parameter - every scenario evaluation implicitly starts
    each channel's adstock at zero, regardless of real recent spend. That
    was previously an undisclosed fact of the prediction code; this makes
    it an explicit, fingerprinted governance record instead. It does not
    change prediction behaviour - carrying in nonzero adstock would be an
    MMM math change requiring its own approved requirement, not this one.

    PR 88B: no longer called by ``evaluate_manual_scenario``/
    ``optimize_scenario`` for steady-state official governance evidence -
    see ``PlanningEvaluationSemantics`` below. The steady-state engine has
    no sequential simulation at all, so "the carry-in is zero" is not a
    fact about the calculation; it's a fact about a concept (carry-in) the
    calculation does not model. Kept, with ``AdstockState``, for a future
    sequential planning engine that actually has starting/terminal stock.
    """
    return AdstockState(
        channel_adstock_start=tuple((c, 0.0) for c in sorted(channels)),
        channel_adstock_terminal=(),
        as_of_date=as_of_date,
    )


# ---------------------------------------------------------------------------
# Planning evaluation semantics
# ---------------------------------------------------------------------------

# PR 91A: schema version of PlanningEvaluationSemantics's own serialized
# payload (its to_dict()/from_dict() shape) - distinct from both
# ``prediction_function_version`` (which describes the calculation the
# semantics disclose, e.g. steady_state_outcome_response's behaviour) and
# a saved scenario's own governance-dependencies schema version (bumped
# 3 -> 4 in core.scenario_governance when planning_semantics_fingerprint
# was added). Bump this only when to_dict()/from_dict()'s field shape
# changes, not when the disclosed calculation changes.
PLANNING_SEMANTICS_SCHEMA_VERSION = 1

# PR 92A: the set of schema_version values from_dict()/__post_init__ accept.
# Distinct from PLANNING_SEMANTICS_SCHEMA_VERSION (the version this code
# writes) so a future version can be added here as "readable but not the
# current write version" without conflating the two.
_SUPPORTED_PLANNING_SEMANTICS_SCHEMA_VERSIONS = frozenset({1})


def _validate_planning_semantics_schema_version(value: Any) -> int:
    """Strictly validate a ``PlanningEvaluationSemantics.schema_version``.

    PR 92A: ``int(raw_version)`` silently coerced floats, bools, and numeric
    strings, and accepted zero/negative integers. ``type(value) is not int``
    (rather than ``isinstance``) is required to reject ``bool``, which is a
    subclass of ``int`` in Python and would otherwise pass an ``isinstance``
    check."""
    if type(value) is not int:
        raise ValueError(
            "PlanningEvaluationSemantics schema_version must be an actual "
            f"int, got {value!r} ({type(value).__name__})."
        )
    if value > PLANNING_SEMANTICS_SCHEMA_VERSION:
        raise ValueError(
            "PlanningEvaluationSemantics payload declares "
            f"schema_version={value}, which is newer than the "
            f"{PLANNING_SEMANTICS_SCHEMA_VERSION} this code supports. "
            "Refusing to load an unsupported future payload rather than "
            "guessing at its shape."
        )
    if value not in _SUPPORTED_PLANNING_SEMANTICS_SCHEMA_VERSIONS:
        raise ValueError(
            f"PlanningEvaluationSemantics schema_version={value} is not a "
            "supported schema version "
            f"({sorted(_SUPPORTED_PLANNING_SEMANTICS_SCHEMA_VERSIONS)})."
        )
    return value


@dataclass(frozen=True)
class PlanningEvaluationSemantics:
    """Truthful, machine-checkable disclosure of what the planning engine
    that produced a scenario actually calculates.

    PR 88B: replaces ``AdstockState``/``zero_carry_in_adstock_state`` as the
    steady-state engine's official governance disclosure. Those disclosed a
    "zero carry-in", which implies a carry-in concept the steady-state
    engine does not model at all (no time-stepped simulation - see
    ``core.predict.steady_state_outcome_response``): spend held constant at
    a level is assumed to have already converged to its steady-state
    response, for every month independently. This object states that
    directly instead of reporting a fabricated value for an inapplicable
    concept.

    PR 91A: added ``schema_version`` (see ``PLANNING_SEMANTICS_SCHEMA_
    VERSION`` above) so the serialized payload shape is itself versioned,
    separately from ``prediction_function_version``. ``from_dict()``
    migrates a legacy payload with no ``schema_version`` key (every payload
    written before this PR) to schema version 1 - the field shape is
    unchanged, so no value migration is needed, only the version stamp.
    A payload declaring a schema version newer than this code supports is
    rejected fail-closed rather than guessed at.

    PR 92A: ``from_dict`` now requires an actual mapping, distinguishes a
    genuinely absent ``schema_version`` key (legacy migration) from an
    explicitly present ``null`` (malformed, rejected), and validates the
    field strictly (real ``int``, not ``bool``/``float``/numeric-string,
    positive, and a supported version) instead of coercing it with
    ``int(...)``. ``__post_init__`` enforces the same invariant on direct
    construction, so a ``PlanningEvaluationSemantics`` cannot be built, let
    alone serialized, with an invalid ``schema_version``.

    Parameters
    ----------
    engine : str
        Which prediction engine evaluated this scenario, e.g.
        ``"steady_state_monthly"``.
    temporal_resolution : str
        The time granularity the engine operates at, e.g. ``"monthly"``.
    within_period_media_assumption : str
        What the engine assumes media has done within one period, e.g.
        ``"constant_to_steady_state"`` (spend held constant long enough to
        reach the converged response - see root AGENTS.md's steady-state-
        versus-sequential rule: this must never be read as a 0-3 month or
        3-12 month response).
    carry_in_state_applicable : bool
        Whether a starting adstock/carry-in state is part of this engine's
        calculation at all. ``False`` for steady state - there is nothing
        to disclose a value for, so no value (zero or otherwise) is
        reported as if it were meaningful.
    terminal_state_applicable : bool
        Whether a terminal (end-of-window) adstock state is produced by
        this engine. ``False`` for steady state, for the same reason.
    prediction_function_version : str
        Version marker for the prediction function these semantics
        describe, so a future change to steady_state_outcome_response's
        calculation (even one that keeps the same engine/resolution/
        assumption labels) can still be distinguished.
    schema_version : int
        Version of this object's own serialized payload shape - see
        ``PLANNING_SEMANTICS_SCHEMA_VERSION``.
    """

    engine: str = ""
    temporal_resolution: str = ""
    within_period_media_assumption: str = ""
    carry_in_state_applicable: bool = False
    terminal_state_applicable: bool = False
    prediction_function_version: str = ""
    schema_version: int = PLANNING_SEMANTICS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _validate_planning_semantics_schema_version(self.schema_version)

    def fingerprint(self) -> str:
        """Fingerprint of the disclosed calculation semantics only.

        PR 91A: deliberately excludes ``schema_version`` - the fingerprint
        identifies what the engine calculates (engine, resolution,
        within-period assumption, carry-in/terminal applicability,
        prediction function version), not how this object happens to be
        serialized. Migrating a legacy unversioned payload to
        ``schema_version=1`` must not, by itself, stale a scenario that
        was evaluated under an otherwise-unchanged calculation.
        """
        raw = json.dumps(
            {
                "engine": self.engine,
                "temporal_resolution": self.temporal_resolution,
                "within_period_media_assumption": self.within_period_media_assumption,
                "carry_in_state_applicable": self.carry_in_state_applicable,
                "terminal_state_applicable": self.terminal_state_applicable,
                "prediction_function_version": self.prediction_function_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "engine": self.engine,
            "temporal_resolution": self.temporal_resolution,
            "within_period_media_assumption": self.within_period_media_assumption,
            "carry_in_state_applicable": self.carry_in_state_applicable,
            "terminal_state_applicable": self.terminal_state_applicable,
            "prediction_function_version": self.prediction_function_version,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "PlanningEvaluationSemantics":
        if not isinstance(d, Mapping):
            raise TypeError(
                "PlanningEvaluationSemantics.from_dict requires a mapping, "
                f"got {type(d).__name__}."
            )
        if "schema_version" not in d:
            # Legacy payload written before PR 91A never had a
            # schema_version key at all - the field shape is otherwise
            # identical, so this migrates cleanly to schema_version=1.
            # An explicitly present `null` is NOT this case - it falls
            # through to strict validation below and is rejected.
            schema_version = 1
        else:
            schema_version = _validate_planning_semantics_schema_version(
                d["schema_version"]
            )
        return cls(
            engine=d.get("engine", ""),
            temporal_resolution=d.get("temporal_resolution", ""),
            within_period_media_assumption=d.get("within_period_media_assumption", ""),
            carry_in_state_applicable=bool(d.get("carry_in_state_applicable", False)),
            terminal_state_applicable=bool(d.get("terminal_state_applicable", False)),
            prediction_function_version=d.get("prediction_function_version", ""),
            schema_version=schema_version,
        )


# The current (and, until a sequential engine exists, only) planning engine's
# truthful semantics - the single source every official evaluation stamps
# onto its governance dependencies, and the single value
# validate_scenario_dependencies compares a saved scenario's recorded
# fingerprint against. Bump prediction_function_version (which changes the
# fingerprint) when steady_state_outcome_response's calculation changes in a
# way that should stale previously-saved official scenarios even though the
# engine/resolution/assumption labels stay the same.
CURRENT_PLANNING_EVALUATION_SEMANTICS = PlanningEvaluationSemantics(
    engine="steady_state_monthly",
    temporal_resolution="monthly",
    within_period_media_assumption="constant_to_steady_state",
    carry_in_state_applicable=False,
    terminal_state_applicable=False,
    prediction_function_version="1.0.0",
)

# WP5 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): the sequential
# weekly simulation kernel's own truthful semantics - a second, explicitly-
# labelled evaluation path alongside CURRENT_PLANNING_EVALUATION_SEMANTICS
# above, never a silent replacement of it (see core/AGENTS.md's "Steady-
# state versus sequential" section). Unlike the steady-state engine, this
# one genuinely reconstructs a starting adstock state from real historical
# media (`core.sequential_simulation.reconstruct_starting_state`) and
# produces a terminal carryover state
# (`core.sequential_simulation.simulate_terminal_carryover`), so both
# applicability flags are True. `within_period_media_assumption` is
# `"explicit_weekly_plan"` because - unlike the steady-state engine, which
# assumes spend held constant within a period until it converges - this
# engine takes an explicit weekly plan as input and never infers within-
# period spread from a coarser (e.g. monthly) figure; that spread decision
# is WP6's scope, not this engine's.
SEQUENTIAL_WEEKLY_PLANNING_EVALUATION_SEMANTICS = PlanningEvaluationSemantics(
    engine="sequential_weekly",
    temporal_resolution="weekly",
    within_period_media_assumption="explicit_weekly_plan",
    carry_in_state_applicable=True,
    terminal_state_applicable=True,
    prediction_function_version="1.0.0",
)


# ---------------------------------------------------------------------------
# Future assumptions (cost, FX, external controls)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FutureAssumptions:
    """Versioned future assumptions for scenario planning.

    PR 72F: Captures cost-per-unit, FX rates, and external control
    forecasts that a scenario depends on. When these change, the
    scenario becomes stale.
    """

    cost_assumptions: tuple[tuple[str, str, float], ...] = ()
    fx_assumptions: tuple[tuple[str, str, float], ...] = ()
    external_forecasts: tuple[tuple[str, str, float], ...] = ()
    version: str = ""
    label: str = ""

    def fingerprint(self) -> str:
        raw = json.dumps(
            {
                "cost_assumptions": tuple(sorted(self.cost_assumptions)),
                "fx_assumptions": tuple(sorted(self.fx_assumptions)),
                "external_forecasts": tuple(sorted(self.external_forecasts)),
                "version": self.version,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def to_dict(self) -> dict:
        return {
            "cost_assumptions": list(self.cost_assumptions),
            "fx_assumptions": list(self.fx_assumptions),
            "external_forecasts": list(self.external_forecasts),
            "version": self.version,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FutureAssumptions":
        return cls(
            cost_assumptions=tuple(tuple(x) for x in d.get("cost_assumptions", [])),
            fx_assumptions=tuple(tuple(x) for x in d.get("fx_assumptions", [])),
            external_forecasts=tuple(tuple(x) for x in d.get("external_forecasts", [])),
            version=d.get("version", ""),
            label=d.get("label", ""),
        )


# ---------------------------------------------------------------------------
# Scenario staleness
# ---------------------------------------------------------------------------


def check_scenario_staleness(
    scenario_fingerprint: str,
    current_assumptions_fingerprint: str,
) -> tuple[bool, str]:
    """Check whether a scenario is stale relative to current assumptions.

    Returns ``(is_stale, reason)``. A scenario is stale when the
    assumptions fingerprint used at scenario creation differs from the
    current assumptions fingerprint.
    """
    if not scenario_fingerprint:
        return True, "No scenario fingerprint recorded."
    if not current_assumptions_fingerprint:
        return True, "No current assumptions fingerprint for comparison."
    if scenario_fingerprint != current_assumptions_fingerprint:
        return True, "Assumptions have changed since this scenario was created."
    return False, "Scenario is current."


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
    # PR 88B: deprecated for steady-state evaluation - no longer populated
    # by evaluate_manual_scenario (see PlanningEvaluationSemantics below).
    # Kept for a future sequential engine and for reading pre-88B results.
    adstock_state: AdstockState | None = None
    assumptions_fingerprint: str = ""
    future_assumptions: FutureAssumptions | None = None
    # PR 88B: the actual planning-engine semantics this scenario was
    # evaluated under - see PlanningEvaluationSemantics.
    planning_semantics: "PlanningEvaluationSemantics | None" = None

    def to_dict(self) -> dict:
        return {
            "predicted": self.predicted,
            "planning_objective": self.planning_objective.to_dict()
            if self.planning_objective
            else None,
            "governance_mode": self.governance_mode,
            "artefact_kind": self.artefact_kind,
            "resolved_governance": self.resolved_governance.to_dict()
            if self.resolved_governance
            else None,
            "governance_dependencies": self.governance_dependencies.to_dict()
            if self.governance_dependencies
            else None,
            "activity_definitions_fingerprint": self.activity_definitions_fingerprint,
            "cost_mapping_fingerprint": self.cost_mapping_fingerprint,
            "counterfactual_policy_fingerprint": self.counterfactual_policy_fingerprint,
            "economics_coverage": self.economics_coverage,
            "adstock_state": self.adstock_state.to_dict()
            if self.adstock_state
            else None,
            "future_assumptions": self.future_assumptions.to_dict()
            if self.future_assumptions
            else None,
            "assumptions_fingerprint": self.assumptions_fingerprint,
            "planning_semantics": self.planning_semantics.to_dict()
            if self.planning_semantics
            else None,
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
    calculated fingerprint is authoritative and a ``ValueError`` is raised.
    """

    value_by_outcome_id: Mapping[str, float]
    currency_by_outcome_id: Mapping[str, str]
    mapping_id: str = "default"
    mapping_fingerprint: str = ""
    source: str = "outcome_catalogue"

    def __post_init__(self) -> None:
        """Validate that every value and currency field is populated,
        and that the fingerprint is consistent with the content."""
        for oid, val in self.value_by_outcome_id.items():
            if val is None or (isinstance(val, float) and not np.isfinite(val)):
                raise ValueError(
                    f"OutcomeValueMapping: outcome '{oid}' has a non-finite or "
                    f"None value ({val}). Every target must have a finite value."
                )
            # Until Finance approves negative value semantics, reject negative values.
            if val < 0:
                raise ValueError(
                    f"OutcomeValueMapping: outcome '{oid}' has a negative value "
                    f"({val}). Negative outcome values are not a governed "
                    "policy - Finance has not approved negative value "
                    "semantics."
                )
        for oid, curr in self.currency_by_outcome_id.items():
            if (
                not curr
                or not isinstance(curr, str)
                or len(curr) != 3
                or not curr.isupper()
            ):
                raise ValueError(
                    f"OutcomeValueMapping: outcome '{oid}' has an invalid currency "
                    f"'{curr}'. Must be a three-letter uppercase ISO code."
                )
        calculated = self._calculate_fingerprint()
        # G2A.7a.10: a caller-supplied fingerprint that disagrees with the
        # calculated one must raise, not silently overwrite.
        if self.mapping_fingerprint and self.mapping_fingerprint != calculated:
            raise ValueError(
                f"OutcomeValueMapping.mapping_fingerprint "
                f"({self.mapping_fingerprint[:16]}...) disagrees with the "
                f"calculated fingerprint ({calculated[:16]}...) of the "
                "supplied content. A caller-supplied fingerprint must match "
                "the content exactly, or be omitted."
            )

    def _calculate_fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of the mapping content."""
        payload = {
            "mapping_id": self.mapping_id,
            "source": self.source,
            "value_by_outcome_id": {
                k: v for k, v in sorted(self.value_by_outcome_id.items())
            },
            "currency_by_outcome_id": {
                k: v for k, v in sorted(self.currency_by_outcome_id.items())
            },
        }
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @property
    def fingerprint(self) -> str:
        """The authoritative mapping fingerprint, always recalculated."""
        return self._calculate_fingerprint()

    def to_dict(self) -> dict:
        return {
            "value_by_outcome_id": dict(self.value_by_outcome_id),
            "currency_by_outcome_id": dict(self.currency_by_outcome_id),
            "mapping_id": self.mapping_id,
            "mapping_fingerprint": self.fingerprint,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OutcomeValueMapping":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)

    @classmethod
    def from_legacy_segment_ltv(
        cls,
        segment_by_outcome_id: Mapping[str, str],
        segment_ltv: Mapping[str, float],
        currency: str,
        *,
        outcome_ids: tuple[str, ...],
    ) -> "OutcomeValueMapping":
        """Strict adapter: convert legacy segment-level LTV to outcome-ID
        value mapping. Every target outcome must map to one existing segment
        value. Missing values block rather than defaulting to 0.0.

        G2A.7a.9: requires explicit ``segment_by_outcome_id`` mapping and
        ``currency``. No hard-coded GBP. Missing segment-value entries raise.
        """
        if not currency or len(currency) != 3 or not currency.isupper():
            raise ValueError(
                f"from_legacy_segment_ltv requires a valid three-letter "
                f"uppercase ISO currency, got {currency!r}."
            )
        value_by_outcome_id: dict[str, float] = {}
        currency_by_outcome_id: dict[str, str] = {}
        for oid in outcome_ids:
            segment = segment_by_outcome_id.get(oid)
            if segment is None:
                raise ValueError(
                    f"Outcome '{oid}' has no segment mapping in "
                    "segment_by_outcome_id. Every target outcome must "
                    "map to exactly one segment."
                )
            if segment not in segment_ltv:
                raise ValueError(
                    f"Segment '{segment}' (for outcome '{oid}') has no "
                    "value in segment_ltv. Missing values block; they "
                    "do not become zero."
                )
            value = segment_ltv[segment]
            if value is None or not np.isfinite(value):
                raise ValueError(
                    f"Segment '{segment}' (for outcome '{oid}') has a "
                    f"non-finite value ({value})."
                )
            value_by_outcome_id[oid] = float(value)
            currency_by_outcome_id[oid] = currency

        return cls(
            value_by_outcome_id=value_by_outcome_id,
            currency_by_outcome_id=currency_by_outcome_id,
            mapping_id="legacy_segment_ltv_migration",
            source="legacy_segment_ltv_migration",
        )


# ---------------------------------------------------------------------------
# Scenario forward-value assumptions (REQ-ECON-003 Requirement 5, WP2G)
# ---------------------------------------------------------------------------

DNA_VALUE_MODE_OVERALL = "overall"
DNA_VALUE_MODE_SEGMENT_SPECIFIC = "segment_specific"
DNA_VALUE_MODES = (DNA_VALUE_MODE_OVERALL, DNA_VALUE_MODE_SEGMENT_SPECIFIC)


@dataclass(frozen=True)
class ScenarioValueAssumptions:
    """Explicit forward economic-value assumption for Scenario Planner
    (REQ-ECON-003 Requirement 5). Never extrapolated from historical
    valuation - every field here is an analyst-declared number for a
    FUTURE plan, clearly distinct from REQ-ECON-002's historical
    valuation catalogue (`core.outcome_valuation`).

    `fh_value_by_outcome_id` is an explicit LTR value per relevant FH
    outcome_id ("preferably by segment", restricted to whichever
    subscription/GSA/bill-through relationship the fit's outcome
    catalogue makes valid - callers choose which outcome_ids are
    eligible; this dataclass does not).

    `dna_mode` explicitly states whether `dna_value_by_outcome_id` holds
    one shared value under every DNA outcome_id it contains
    (`"overall"`) or a genuinely distinct value per outcome_id
    (`"segment_specific"`) - both representations are required to be
    supported, and which one was used is disclosed, never inferred
    after the fact from whether the values happen to be equal.

    `currency` is a single ISO-3 currency shared by every value here -
    FX conversion across currencies remains Finance-blocked
    (`REQ-ECON-002` Requirement 7 / `docs/wp2_outcome_valuation_
    decision_package.md` D7); this dataclass never invents an FX
    default, so it deliberately does not support mixed currencies.
    """

    fh_value_by_outcome_id: Mapping[str, float]
    dna_value_by_outcome_id: Mapping[str, float]
    dna_mode: str
    currency: str
    assumptions_id: str = "default"
    source: str = "scenario_forward_assumption"

    def __post_init__(self) -> None:
        if self.dna_mode not in DNA_VALUE_MODES:
            raise ValueError(
                f"ScenarioValueAssumptions: unknown dna_mode "
                f"'{self.dna_mode}' (expected one of {DNA_VALUE_MODES})."
            )
        if not self.currency or len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError(
                "ScenarioValueAssumptions requires a valid three-letter "
                f"uppercase ISO currency, got {self.currency!r}."
            )
        combined = {**self.fh_value_by_outcome_id, **self.dna_value_by_outcome_id}
        for oid, val in combined.items():
            if val is None or (isinstance(val, float) and not np.isfinite(val)):
                raise ValueError(
                    f"ScenarioValueAssumptions: outcome '{oid}' has a "
                    f"non-finite or None value ({val})."
                )
            if val < 0:
                raise ValueError(
                    f"ScenarioValueAssumptions: outcome '{oid}' has a "
                    f"negative value ({val}) - Finance has not approved "
                    "negative value semantics."
                )
        overlap = set(self.fh_value_by_outcome_id) & set(self.dna_value_by_outcome_id)
        if overlap:
            raise ValueError(
                f"ScenarioValueAssumptions: outcome_id(s) {sorted(overlap)} "
                "appear in both fh_value_by_outcome_id and "
                "dna_value_by_outcome_id - each outcome must belong to "
                "exactly one product's assumption."
            )

    def to_dict(self) -> dict:
        return {
            "fh_value_by_outcome_id": dict(self.fh_value_by_outcome_id),
            "dna_value_by_outcome_id": dict(self.dna_value_by_outcome_id),
            "dna_mode": self.dna_mode,
            "currency": self.currency,
            "assumptions_id": self.assumptions_id,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioValueAssumptions":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        return cls(**payload)

    def missing_outcome_ids(self, required_outcome_ids: Sequence[str]) -> List[str]:
        """Which of `required_outcome_ids` have no explicit value yet -
        used to fail closed before evaluation/save, never silently
        proceeding with an incomplete assumption set."""
        covered = set(self.fh_value_by_outcome_id) | set(self.dna_value_by_outcome_id)
        return [oid for oid in required_outcome_ids if oid not in covered]

    def to_outcome_value_mapping(
        self, *, mapping_id: str = "scenario_forward_assumption"
    ) -> "OutcomeValueMapping":
        """Flatten into the existing, governed `OutcomeValueMapping` -
        Requirement 5 extends, rather than replaces, this mechanism.
        The `dna_mode="overall"` expansion (one value applied to every
        `dna_value_by_outcome_id` key) already happened when this object
        was built (`build_scenario_value_assumptions`) - this method
        never performs an implicit expansion of its own."""
        value_by_outcome_id = {
            **self.fh_value_by_outcome_id,
            **self.dna_value_by_outcome_id,
        }
        currency_by_outcome_id = {oid: self.currency for oid in value_by_outcome_id}
        return OutcomeValueMapping(
            value_by_outcome_id=value_by_outcome_id,
            currency_by_outcome_id=currency_by_outcome_id,
            mapping_id=mapping_id,
            source=self.source,
        )


def build_scenario_value_assumptions(
    *,
    fh_value_by_outcome_id: Mapping[str, float],
    dna_mode: str,
    currency: str,
    dna_outcome_ids: Sequence[str] = (),
    dna_overall_value: Optional[float] = None,
    dna_value_by_outcome_id: Optional[Mapping[str, float]] = None,
    assumptions_id: str = "default",
) -> ScenarioValueAssumptions:
    """The one place `dna_mode="overall"` is expanded into a per-
    outcome_id dict - explicit and testable, never performed silently
    inside `ScenarioValueAssumptions` itself.

    `dna_mode="overall"` requires `dna_overall_value` and applies it to
    every id in `dna_outcome_ids`. `dna_mode="segment_specific"`
    requires `dna_value_by_outcome_id` to already cover every id in
    `dna_outcome_ids` - missing entries block rather than defaulting to
    0.0 or being silently omitted. When `dna_outcome_ids` is empty (no
    DNA outcome is in scope at all), no DNA assumption is required
    regardless of `dna_mode` - there is nothing to expand or validate.
    """
    if dna_mode not in DNA_VALUE_MODES:
        raise ValueError(
            f"Unknown dna_mode '{dna_mode}' (expected one of {DNA_VALUE_MODES})."
        )
    if not dna_outcome_ids:
        expanded_dna: dict = {}
    elif dna_mode == DNA_VALUE_MODE_OVERALL:
        if dna_overall_value is None:
            raise ValueError(
                "dna_mode='overall' requires an explicit dna_overall_value."
            )
        if dna_overall_value < 0 or not np.isfinite(dna_overall_value):
            raise ValueError(
                f"dna_overall_value must be a finite, non-negative number, "
                f"got {dna_overall_value!r}."
            )
        expanded_dna = {oid: float(dna_overall_value) for oid in dna_outcome_ids}
    elif dna_mode == DNA_VALUE_MODE_SEGMENT_SPECIFIC:
        expanded_dna = dict(dna_value_by_outcome_id or {})
        missing = [oid for oid in dna_outcome_ids if oid not in expanded_dna]
        if missing:
            raise ValueError(
                "dna_mode='segment_specific' requires an explicit value "
                f"for every DNA outcome_id; missing: {missing}."
            )
    return ScenarioValueAssumptions(
        fh_value_by_outcome_id=dict(fh_value_by_outcome_id),
        dna_value_by_outcome_id=expanded_dna,
        dna_mode=dna_mode,
        currency=currency,
        assumptions_id=assumptions_id,
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
        _ISO_CODE_RE = __import__("re").compile(r"^[A-Z]{3}$")
        for field_name in (
            "market_reporting_currency",
            "value_currency",
            "group_reporting_currency",
            "model_currency",
        ):
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
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
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
        if (
            not self.model_approval_fingerprint
            or not self.model_approval_fingerprint.strip()
        ):
            raise ValueError(
                "ScenarioValidationContext.model_approval_fingerprint must be non-blank"
            )
        if not self.data_fingerprint or not self.data_fingerprint.strip():
            raise ValueError(
                "ScenarioValidationContext.data_fingerprint must be non-blank"
            )
        if not self.model_spec_fingerprint or not self.model_spec_fingerprint.strip():
            raise ValueError(
                "ScenarioValidationContext.model_spec_fingerprint must be non-blank"
            )
        if not self.posterior_fingerprint or not self.posterior_fingerprint.strip():
            raise ValueError(
                "ScenarioValidationContext.posterior_fingerprint must be non-blank"
            )
        if self.planning_objective is None:
            raise ValueError(
                "ScenarioValidationContext.planning_objective must not be None"
            )
        if not self.planning_objective.is_valid_for_official_planning:
            raise ValueError(
                "ScenarioValidationContext.planning_objective must be valid for official planning"
            )
        if not self.outcome_definitions:
            raise ValueError(
                "ScenarioValidationContext.outcome_definitions must not be empty"
            )
        if not self.outcome_approvals:
            raise ValueError(
                "ScenarioValidationContext.outcome_approvals must not be empty"
            )
        if (
            not self.counterfactual_fingerprint
            or not self.counterfactual_fingerprint.strip()
        ):
            raise ValueError(
                "ScenarioValidationContext.counterfactual_fingerprint must be non-blank"
            )


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
        raise ValueError(
            "model_approval_fingerprint is required for ScenarioValidationContext"
        )
    if not data_fingerprint:
        raise ValueError("data_fingerprint is required for ScenarioValidationContext")
    if not model_spec_fingerprint:
        raise ValueError(
            "model_spec_fingerprint is required for ScenarioValidationContext"
        )
    if not posterior_fingerprint:
        raise ValueError(
            "posterior_fingerprint is required for ScenarioValidationContext"
        )
    if planning_objective is None:
        raise ValueError("planning_objective is required for ScenarioValidationContext")
    if not outcome_definitions:
        raise ValueError(
            "outcome_definitions are required for ScenarioValidationContext"
        )
    if not outcome_approvals:
        raise ValueError("outcome_approvals are required for ScenarioValidationContext")
    if not counterfactual_fingerprint:
        raise ValueError(
            "counterfactual_fingerprint is required for ScenarioValidationContext"
        )

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
    value_currency: Optional[str] = None
    spend_scope: str = "cost_bearing_decisions"
    activity_scope: str = "optimisable_interventions"
    counterfactual_policy_fingerprint: Optional[str] = None
    schema_version: int = 3

    def __post_init__(self) -> None:
        if self.estimand not in PLANNING_ESTIMANDS:
            raise ValueError(f"Unsupported planning estimand: {self.estimand}")
        if self.estimand == "incremental_value" and not self.value_currency:
            raise ValueError("value objectives require value_currency")
        # G2A.7a.7: reject duplicate target_outcome_ids
        if len(self.target_outcome_ids) != len(set(self.target_outcome_ids)):
            dupes = [
                oid
                for oid in self.target_outcome_ids
                if list(self.target_outcome_ids).count(oid) > 1
            ]
            raise ValueError(
                f"PlanningObjective target_outcome_ids contains duplicates: "
                f"{sorted(set(dupes))}."
            )

    @property
    def is_valid_for_official_planning(self) -> bool:
        """True if this objective has enough explicit information to be
        validated against outcome approvals. Does not check whether approvals
        actually exist — that's the caller's responsibility via
        outcome_approval.require_outcome_approval."""
        return bool(self.metric_key and self.target_outcome_ids)

    def to_dict(self) -> dict:
        values = asdict(self)
        values["target_outcome_ids"] = list(self.target_outcome_ids)
        return values

    @classmethod
    def from_dict(cls, d: dict) -> "PlanningObjective":
        known = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in d.items() if k in known}
        if "target_outcome_ids" in payload and isinstance(
            payload["target_outcome_ids"], list
        ):
            payload["target_outcome_ids"] = tuple(payload["target_outcome_ids"])
        return cls(**payload)


def planning_objective_from_legacy(
    objective: str,
    *,
    value_currency: str | None = None,
    counterfactual_policy_fingerprint: str | None = None,
) -> PlanningObjective:
    """Migrate a saved legacy objective string to the typed contract.

    The mapping only identifies intent. It does NOT grant outcome approval.
    """
    # Lazy import to avoid circular dependency on .outcomes at module level
    from ..outcomes import (
        METRIC_KEY_FH_GSA,
        METRIC_KEY_FH_SIGNUP,
        METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        METRIC_KEY_DNA_KIT_SALE,
    )

    metric_keys = {
        "fh_gsa": METRIC_KEY_FH_GSA,
        "fh_signups": METRIC_KEY_FH_SIGNUP,
        "fh_net_billthrough": METRIC_KEY_FH_NET_BILLTHROUGH_COUNT,
        "dna_kits": METRIC_KEY_DNA_KIT_SALE,
        "weighted_mix": "weighted_mix",
    }
    if objective in {"expected_value", "value"}:
        if not value_currency:
            raise ValueError(
                "Legacy 'expected_value' objective migration requires an "
                "explicit value_currency."
            )
        return PlanningObjective(
            estimand="incremental_value",
            metric_key="expected_value",
            value_currency=value_currency,
            counterfactual_policy_fingerprint=counterfactual_policy_fingerprint,
        )
    if objective not in metric_keys:
        raise ValueError(f"cannot migrate unknown legacy objective {objective!r}")
    return PlanningObjective(
        estimand="incremental_outcome",
        metric_key=metric_keys[objective],
        counterfactual_policy_fingerprint=counterfactual_policy_fingerprint,
    )


# ---------------------------------------------------------------------------
# Scenario dependency issue
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioDependencyIssue:
    """One detected staleness or invalidity issue in a saved scenario's
    governance dependencies."""

    artefact_id: str
    issue_type: str  # "stale", "legacy_unverified", "invalid", "missing"
    detail: str
    dependency_type: str = "unknown"
    reason_code: str = ""
