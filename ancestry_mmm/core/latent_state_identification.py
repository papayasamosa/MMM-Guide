"""Latent-state scale and location identification (REQ-LATENT-001, Work
Package 3 - second record - of `Media-Mix-Lab: Coding LLM Next Steps
After PR #267 and Latest PRD Validation Updates`).

No module in this repository currently declares or validates a scale/
location identification strategy for a fitted latent state. Candidate
A's latent branded-search demand (`core.search_capacity`, the
`latent_branded_search_demand` deterministic) is the first concrete
integration target named by the reconciliation brief, but this record
does not itself approve Candidate A's actual identifying anchor -
`REQ-LATENT-001`'s own "Unresolved decisions" section reserves that
specific statistical choice (Part 6 `MD-021`) as a separate,
decision-required workstream. This module therefore ships a model-
agnostic identification-declaration contract and empirical stability
check; it does not modify `core.search_capacity` and does not assert
any specific anchor for Candidate A.

This module provides:

- `LatentStateIdentificationDeclaration`: the identifying strategy
  declared for one latent state (Requirement 1) - stored explicitly
  (kind, human-readable description, optional anchor reference), never
  left implicit in code (Requirement 2).
- `LatentStateIdentificationResult`: the assessed status for one latent
  state, plus whatever empirical sign/scale evidence chain-level
  posterior draws could establish. Never a bare boolean - always carries
  `LATENT_STATE_IDENTIFICATION_DISCLAIMER`.
- `assess_latent_state_identification`: assembles a result from a
  caller-supplied declaration (or its absence) and, optionally,
  caller-supplied per-chain posterior draws for the latent quantity's
  representative scalar (e.g. a loading or anchor-implied value per
  draw). Mirrors `core.structural_stability`'s "the caller supplies the
  fold-local computation, this module only assembles and compares the
  result" pattern from Work Package 2 part 2: this module does not
  itself fit a model or extract a posterior.
- `is_eligible_for_official_use`: the fail-closed use-eligibility gate
  (Requirement 5) - only an `identified` result is eligible for official
  causal reporting, curve publication, planning, or optimisation for the
  affected pathway. This mirrors the existing Search fail-closed pattern
  (`core.predict.predict_mu`/`core.attribution.compute_shapley_
  contributions` already fail closed for an unwired Candidate A pathway
  under `REQ-SEARCH-002`); this function extends the same fail-closed
  principle to identification specifically.

Sign-flip detection across chains is a well-established Bayesian
diagnostic for latent-scale label/sign switching (a structural
indeterminacy, not a graded threshold call): if one chain's posterior
for the representative scalar is reliably positive and another chain's
is reliably negative, the latent state's orientation is not identified
under sampling, independent of any materiality judgement. Scale drift
across chains is reported as a plain descriptive ratio - mirroring
`core.structural_stability.ParameterFoldComparison.point_range` - never
converted into a threshold-based pass/fail, since no specific
scale-drift materiality policy has been approved (see this record's own
"Explicitly excluded").

Deliberately out of scope for this module (see REQ-LATENT-001's own
"Explicitly excluded"/"Unresolved decisions"):

- Candidate A's actual identifying anchor/constraint for
  `latent_branded_search_demand`, or any other specific latent state's
  substantive anchor (Part 6 `MD-021`) - a statistical modelling
  decision, not resolvable by this reconciliation record.
- Compiler-level blocking (Requirement 3) - extending `core.graph_model_
  compiler`'s blocking-error contract is deferred as a separate
  integration follow-up, consistent with how `REQ-IDENT-001` deferred
  its own equivalent compiler-blocking requirement in Work Package 3's
  first record.
- Full synthetic-recovery validation for custom/advanced latent
  structures, and detection of "unexplained decision instability" from a
  changed identification choice over time (both part of Requirement 4) -
  both require a real fit/re-fit pipeline this module does not run,
  mirroring `core.structural_stability`'s own deferred "real re-fit
  integration" open item from Work Package 2 part 2.
- Wiring this evidence into `DiagnosticsArtefact`/the Diagnostics or
  Causal Graph pages - deferred alongside Work Package 1/2/3's own same
  open item.
- The accepted general-purpose identification-strategy taxonomy beyond
  the five kinds below, and business/technical status labels (Part 7
  §48 `VL-026`, Part 10 §47 `UX-028`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple

STRATEGY_FIXED_LOADING = "fixed_loading"
STRATEGY_ANCHORED_TO_OBSERVED = "anchored_to_observed"
STRATEGY_CONSTRAINED_REFERENCE_VARIANCE = "constrained_reference_variance"
STRATEGY_VALIDATED_MEASUREMENT_MODEL = "validated_measurement_model"
STRATEGY_OTHER_APPROVED_EQUIVALENT = "other_approved_equivalent"

IDENTIFICATION_STRATEGY_KINDS = (
    STRATEGY_FIXED_LOADING,
    STRATEGY_ANCHORED_TO_OBSERVED,
    STRATEGY_CONSTRAINED_REFERENCE_VARIANCE,
    STRATEGY_VALIDATED_MEASUREMENT_MODEL,
    STRATEGY_OTHER_APPROVED_EQUIVALENT,
)

LATENT_IDENTIFICATION_STATUS_IDENTIFIED = "identified"
LATENT_IDENTIFICATION_STATUS_REVIEW_REQUIRED = "review_required"
LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED = "not_identified"
LATENT_IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER = (
    "unsupported_by_current_checker"
)

LATENT_IDENTIFICATION_STATUSES = (
    LATENT_IDENTIFICATION_STATUS_IDENTIFIED,
    LATENT_IDENTIFICATION_STATUS_REVIEW_REQUIRED,
    LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED,
    LATENT_IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
)

LATENT_STATE_IDENTIFICATION_DISCLAIMER = (
    "This diagnostic checks whether an identifying strategy has been "
    "declared for this latent state and, where per-chain posterior draws "
    "are supplied, whether sampling reveals sign indeterminacy across "
    "chains. It does not prove the declared anchor or constraint is "
    "substantively correct, does not perform full synthetic-recovery "
    "validation for custom latent structures, and does not assess "
    "decision instability from a changed identification choice over "
    "time."
)


@dataclass(frozen=True)
class LatentStateIdentificationDeclaration:
    """The identifying strategy declared for one latent causal state
    (Requirement 1) - `strategy_kind` must be one of the five approved
    kinds, `description` records the substantive identifying choice in
    plain language (Requirement 2: "must be stored ... not left implicit
    in code"), and `anchor_reference` optionally names the specific
    measurement/structural loading/reference quantity the strategy
    anchors to (e.g. an observed channel's known conversion rate)."""

    latent_state_id: str
    strategy_kind: str
    description: str
    anchor_reference: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.latent_state_id:
            raise ValueError("latent_state_id is required")
        if self.strategy_kind not in IDENTIFICATION_STRATEGY_KINDS:
            raise ValueError(
                f"invalid strategy_kind {self.strategy_kind!r}; must be one "
                f"of {IDENTIFICATION_STRATEGY_KINDS}"
            )
        if not self.description:
            raise ValueError(
                "description is required - the identifying choice must be "
                "recorded explicitly, not left implicit (Requirement 2)"
            )

    def to_dict(self) -> dict:
        return {
            "latent_state_id": self.latent_state_id,
            "strategy_kind": self.strategy_kind,
            "description": self.description,
            "anchor_reference": self.anchor_reference,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "LatentStateIdentificationDeclaration":
        return cls(
            latent_state_id=values["latent_state_id"],
            strategy_kind=values["strategy_kind"],
            description=values["description"],
            anchor_reference=values.get("anchor_reference"),
            metadata=dict(values.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LatentStateIdentificationResult:
    """The assessed identification status for one latent state
    (Requirement 6: reported as a separate evidence dimension - never
    collapsed into `EstimandIdentificationResult` or
    `StructuralStabilityArtefact`). Never exposes a bare boolean; always
    carries `LATENT_STATE_IDENTIFICATION_DISCLAIMER`."""

    latent_state_id: str
    status: str
    declaration: Optional[LatentStateIdentificationDeclaration]
    sign_flip_detected: bool = False
    scale_drift_ratio: Optional[float] = None
    chains_checked: int = 0
    limitations: Tuple[str, ...] = ()
    disclaimer: str = LATENT_STATE_IDENTIFICATION_DISCLAIMER

    def __post_init__(self) -> None:
        if not self.latent_state_id:
            raise ValueError("latent_state_id is required")
        if self.status not in LATENT_IDENTIFICATION_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of "
                f"{LATENT_IDENTIFICATION_STATUSES}"
            )

    def to_dict(self) -> dict:
        return {
            "latent_state_id": self.latent_state_id,
            "status": self.status,
            "declaration": (
                self.declaration.to_dict() if self.declaration is not None else None
            ),
            "sign_flip_detected": self.sign_flip_detected,
            "scale_drift_ratio": self.scale_drift_ratio,
            "chains_checked": self.chains_checked,
            "limitations": list(self.limitations),
            "disclaimer": self.disclaimer,
        }

    @classmethod
    def from_dict(
        cls, values: Mapping[str, Any]
    ) -> "LatentStateIdentificationResult":
        declaration_values = values.get("declaration")
        return cls(
            latent_state_id=values["latent_state_id"],
            status=values["status"],
            declaration=(
                LatentStateIdentificationDeclaration.from_dict(declaration_values)
                if declaration_values is not None
                else None
            ),
            sign_flip_detected=bool(values.get("sign_flip_detected", False)),
            scale_drift_ratio=values.get("scale_drift_ratio"),
            chains_checked=int(values.get("chains_checked", 0)),
            limitations=tuple(values.get("limitations") or ()),
            disclaimer=values.get("disclaimer", LATENT_STATE_IDENTIFICATION_DISCLAIMER),
        )


def _median(values: Tuple[float, ...]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def assess_latent_state_identification(
    latent_state_id: str,
    declaration: Optional[LatentStateIdentificationDeclaration] = None,
    *,
    chain_draws: Optional[Tuple[Tuple[float, ...], ...]] = None,
) -> LatentStateIdentificationResult:
    """Assess the identification status of one latent state
    (REQ-LATENT-001).

    - `declaration=None` - no identifying strategy has been declared:
      `not_identified` (Requirement 1 is directly unmet), regardless of
      any supplied `chain_draws`.
    - `declaration` present, `chain_draws=None` - a strategy has been
      declared but not empirically checked under sampling:
      `review_required`.
    - `declaration` present, `chain_draws` with fewer than 2 chains -
      cross-chain sign/scale comparison is not possible:
      `unsupported_by_current_checker`.
    - `declaration` present, `chain_draws` with >= 2 chains - compares
      each chain's median of its representative scalar. Disagreement in
      sign across chains (a structural indeterminacy, not a graded
      threshold) is `not_identified` with `sign_flip_detected=True`.
      Otherwise `identified`, with `scale_drift_ratio` (max/min of the
      per-chain median absolute values) reported as descriptive evidence
      only - never turned into a threshold-based verdict.
    """
    if not latent_state_id:
        raise ValueError("latent_state_id is required")
    if declaration is not None and declaration.latent_state_id != latent_state_id:
        raise ValueError(
            f"declaration.latent_state_id {declaration.latent_state_id!r} does "
            f"not match latent_state_id {latent_state_id!r}"
        )
    if chain_draws is not None:
        if any(len(chain) == 0 for chain in chain_draws):
            raise ValueError("every supplied chain must have at least one draw")

    if declaration is None:
        return LatentStateIdentificationResult(
            latent_state_id=latent_state_id,
            status=LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED,
            declaration=None,
            limitations=(
                "No identifying strategy has been declared for this latent "
                "state (Requirement 1) - its scale and orientation are "
                "unresolved.",
            ),
        )

    if chain_draws is None:
        return LatentStateIdentificationResult(
            latent_state_id=latent_state_id,
            status=LATENT_IDENTIFICATION_STATUS_REVIEW_REQUIRED,
            declaration=declaration,
            limitations=(
                "An identifying strategy has been declared but not "
                "empirically checked under sampling (Requirement 4) - no "
                "per-chain posterior draws were supplied.",
            ),
        )

    chains_checked = len(chain_draws)
    if chains_checked < 2:
        return LatentStateIdentificationResult(
            latent_state_id=latent_state_id,
            status=LATENT_IDENTIFICATION_STATUS_UNSUPPORTED_BY_CURRENT_CHECKER,
            declaration=declaration,
            chains_checked=chains_checked,
            limitations=(
                "At least two chains are required to assess sign/scale "
                "stability across chains; fewer were supplied.",
            ),
        )

    medians = tuple(_median(chain) for chain in chain_draws)
    signs = {(1 if m > 0 else (-1 if m < 0 else 0)) for m in medians}
    sign_flip_detected = len(signs) > 1

    abs_medians = [abs(m) for m in medians if m != 0]
    scale_drift_ratio: Optional[float]
    if abs_medians:
        scale_drift_ratio = float(max(abs_medians) / min(abs_medians))
    else:
        scale_drift_ratio = None

    limitations = [
        "Sign comparison uses each chain's median of the supplied "
        "representative-scalar draws; a latent quantity legitimately "
        "close to zero may trigger a false sign-flip signal - this is a "
        "known limitation of the median-sign check, not a materiality "
        "judgement.",
        "scale_drift_ratio is descriptive evidence only - no scale-drift "
        "materiality threshold has been approved (see this record's "
        "Explicitly excluded section); it is never converted into a "
        "pass/fail verdict by this module.",
        "This module does not perform full synthetic-recovery validation "
        "for custom/advanced latent structures and does not assess "
        "decision instability from a changed identification choice over "
        "time (both part of Requirement 4).",
    ]

    status = (
        LATENT_IDENTIFICATION_STATUS_NOT_IDENTIFIED
        if sign_flip_detected
        else LATENT_IDENTIFICATION_STATUS_IDENTIFIED
    )

    return LatentStateIdentificationResult(
        latent_state_id=latent_state_id,
        status=status,
        declaration=declaration,
        sign_flip_detected=sign_flip_detected,
        scale_drift_ratio=scale_drift_ratio,
        chains_checked=chains_checked,
        limitations=tuple(limitations),
    )


def is_eligible_for_official_use(result: LatentStateIdentificationResult) -> bool:
    """Fail-closed use-eligibility gate (Requirement 5): a latent state
    without an `identified` result must remain visibly unsuitable for
    official causal reporting, curve publication, planning, or
    optimisation for its pathway. Every status other than `identified` -
    including `review_required` - fails closed."""
    return result.status == LATENT_IDENTIFICATION_STATUS_IDENTIFIED
