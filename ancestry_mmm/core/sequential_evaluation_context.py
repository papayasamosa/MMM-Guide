"""
Shared sequential evaluation context (`REQ-STATE-001`/`REQ-SCEN-001`, Work
Package 3 of `Media-Mix-Lab: Coding LLM Next Steps Post PR262`).

`core.sequential_simulation.compute_incremental_outcome` can only check
market/period/outcome identity between a candidate and reference
`SequentialSimulationResult` - it cannot prove the two were evaluated with
the same model/posterior, historical state, phasing policy, future
controls, seasonality, promotions/events, cost assumptions, or evaluation
semantics (brief §5.6/§9.5: "Candidate/reference context equality remains
caller responsibility"). This module adds a typed, fingerprintable context
object that names every one of those identities explicitly, plus a guard a
caller uses before treating an incremental result as headline - "a normal
incremental result must not be constructible from mismatched contexts
without an explicit governed intervention."

This module is framework-independent and has no dependency on the
not-yet-built application-layer phasing/future-context/cost-mapping
services (`REQ-SCEN-002`'s own "Not yet covered" boundary) - every field
here is a caller-supplied identity/fingerprint string, not a deep object;
each of those services is responsible for producing its own stable
identity for the caller to pass in here once it exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping

import numpy as np

from .sequential_simulation import (
    SequentialSimulationResult,
    compute_incremental_outcome,
)

SEQUENTIAL_EVALUATION_CONTEXT_SCHEMA_VERSION = 1

_CONTEXT_FIELDS = (
    "model_identity",
    "posterior_identity",
    "market",
    "canonical_calendar_identity",
    "historical_state_source_identity",
    "evaluation_semantics_identity",
    "phasing_policy_identity",
    "future_assumption_identity",
    "cost_context_identity",
    "counterfactual_policy_identity",
)


class MismatchedSequentialEvaluationContextError(ValueError):
    """Raised when a candidate and reference `SequentialEvaluationContext`
    differ in a field that is not explicitly named as allowed to differ."""


@dataclass(frozen=True)
class SequentialEvaluationContext:
    """Identifies every non-decision input a candidate/reference sequential
    evaluation pair must share, unless a named field is an explicit,
    governed intervention (e.g. a deliberately varied cost assumption -
    `REQ-SCEN-001`: "Candidate/reference plans share the same phasing
    policy... unless a difference in phasing itself is an explicit,
    recorded scenario decision").

    Every field is required and non-empty (`__post_init__`) - a context
    cannot be built with part of its identity silently omitted.
    """

    model_identity: str
    posterior_identity: str
    market: str
    canonical_calendar_identity: str
    historical_state_source_identity: str
    evaluation_semantics_identity: str
    phasing_policy_identity: str
    future_assumption_identity: str
    cost_context_identity: str
    counterfactual_policy_identity: str
    schema_version: int = SEQUENTIAL_EVALUATION_CONTEXT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in _CONTEXT_FIELDS:
            if not getattr(self, name):
                raise ValueError(
                    f"SequentialEvaluationContext.{name} must be a non-empty "
                    "identity/fingerprint string - every context field is "
                    "required so a caller cannot silently omit part of the "
                    "identity a candidate/reference pair must share."
                )

    def to_dict(self) -> dict[str, Any]:
        payload = {name: getattr(self, name) for name in _CONTEXT_FIELDS}
        payload["schema_version"] = self.schema_version
        return payload

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "SequentialEvaluationContext":
        schema_version = d.get("schema_version", 1)
        if schema_version > SEQUENTIAL_EVALUATION_CONTEXT_SCHEMA_VERSION:
            raise ValueError(
                "SequentialEvaluationContext payload declares "
                f"schema_version={schema_version}, newer than the "
                f"{SEQUENTIAL_EVALUATION_CONTEXT_SCHEMA_VERSION} this code "
                "supports. Refusing to load an unsupported future payload "
                "rather than guessing at its shape."
            )
        kwargs = {name: d[name] for name in _CONTEXT_FIELDS}
        return cls(schema_version=schema_version, **kwargs)

    def fingerprint(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(raw).hexdigest()


def require_matching_context(
    candidate_context: SequentialEvaluationContext,
    reference_context: SequentialEvaluationContext,
    *,
    allowed_to_differ: FrozenSet[str] = frozenset(),
) -> None:
    """Raise `MismatchedSequentialEvaluationContextError` if candidate and
    reference contexts differ in any field not explicitly named in
    `allowed_to_differ` (e.g. `allowed_to_differ={"cost_context_identity"}`
    for a deliberately-varied-cost scenario). Raises `ValueError` if
    `allowed_to_differ` names a field that does not exist, to catch a typo
    rather than silently ignoring it."""
    unknown = allowed_to_differ - set(_CONTEXT_FIELDS)
    if unknown:
        raise ValueError(
            f"allowed_to_differ names unknown context field(s): {sorted(unknown)}."
        )
    mismatched = [
        name
        for name in _CONTEXT_FIELDS
        if name not in allowed_to_differ
        and getattr(candidate_context, name) != getattr(reference_context, name)
    ]
    if mismatched:
        raise MismatchedSequentialEvaluationContextError(
            "Candidate and reference sequential evaluation contexts differ "
            f"in field(s) not explicitly allowed to differ: {mismatched}. "
            "A headline incremental result must not be produced by "
            "subtracting unrelated non-decision contexts unless that "
            "difference is itself an explicit governed intervention - pass "
            "the differing field name(s) in allowed_to_differ if this "
            "difference is intentional."
        )


def compute_incremental_outcome_with_context(
    candidate: SequentialSimulationResult,
    candidate_context: SequentialEvaluationContext,
    reference: SequentialSimulationResult,
    reference_context: SequentialEvaluationContext,
    *,
    allowed_to_differ: FrozenSet[str] = frozenset(),
) -> np.ndarray:
    """`core.sequential_simulation.compute_incremental_outcome`, guarded by
    `require_matching_context` first - the context-identity check
    `compute_incremental_outcome` alone cannot perform (see module
    docstring). Prefer this over calling `compute_incremental_outcome`
    directly once candidate/reference contexts exist."""
    require_matching_context(
        candidate_context, reference_context, allowed_to_differ=allowed_to_differ
    )
    return compute_incremental_outcome(candidate, reference)


__all__ = [
    "MismatchedSequentialEvaluationContextError",
    "SequentialEvaluationContext",
    "compute_incremental_outcome_with_context",
    "require_matching_context",
]
