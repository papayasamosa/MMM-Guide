"""Candidate A Search mediation/capacity contracts and linked PyMC engine.

This module is deliberately separate from the ordinary rectangular MMM
builder.  Candidate A is an explicitly selected linked engine capability;
the ordinary PyMC-hierarchical engine must not silently reinterpret a Search
object as a generic ``brand_search`` channel.

The NumPy functions are the authoritative replay/counterfactual contract.
The optional PyMC builder uses the existing count outcome likelihood and log
link, while adding the Search state as a linked latent stage.  Planning and
optimisation are intentionally not enabled by this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, List, Mapping, Optional, Sequence

import numpy as np

if TYPE_CHECKING:
    import pymc as pm
    import pytensor.tensor as pt

from .search_objects import (
    SEARCH_ROLE_DEMAND,
    SEARCH_ROLE_DIRECT_NAV_CAPTURE,
    SEARCH_ROLE_ORGANIC_CAPTURE,
    SEARCH_ROLE_PAID_CAP,
    SEARCH_ROLE_PAID_DELIVERY,
    SEARCH_ROLE_PAID_SPEND,
    UNIT_EXPOSURE_COUNT,
    UNIT_MONETARY,
    SearchObjectDefinition,
    current_search_object_versions,
)


SEARCH_CANDIDATE_A_ENGINE = "pymc_search_candidate_a"
SEARCH_CANDIDATE_A_FORMULATION_ID = "candidate_a_v1"
SEARCH_CAP_PROVENANCE_VALUES = frozenset({"observed_platform", "analyst_declared"})


class SearchCapacityValidationError(ValueError):
    """Raised when a Candidate A invariant would otherwise be bypassed."""


def _as_float_vector(value: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=float)
    if array.ndim != 1:
        raise SearchCapacityValidationError(f"{name} must be one-dimensional.")
    if not np.all(np.isfinite(array)):
        raise SearchCapacityValidationError(f"{name} contains non-finite values.")
    return array


def _same_shape(*arrays: np.ndarray) -> None:
    if not arrays:
        return
    first = arrays[0].shape
    if any(array.shape != first for array in arrays[1:]):
        raise SearchCapacityValidationError(
            "Candidate A arrays must have the same period shape."
        )


@dataclass(frozen=True)
class SearchCandidateASpec:
    """Governed identity and engine settings for one Candidate A path."""

    outcome_definition_id: str
    outcome_definition_version: str
    outcome_definition_fingerprint: str
    market_scope: str
    demand_object_id: str
    paid_spend_object_id: str
    paid_delivery_object_id: str
    paid_cap_object_id: str
    organic_capture_object_id: str
    direct_navigation_object_id: str
    cap_unit: str = UNIT_EXPOSURE_COUNT
    cap_to_delivery_scale: float = 1.0
    cap_provenance: str = ""
    cap_provenance_status: str = "unresolved"
    pooling_mode: str = "partial"
    demand_prior_sigma: float = 0.5
    capture_prior_sigma: float = 0.5
    pooling_prior_sigma: float = 0.3
    prior_evidence_status: str = "pending"
    prior_evidence_reference: str = ""
    evidence_grade: str = "exploratory"
    planning_eligible: bool = False
    optimisation_eligible: bool = False
    explicit_model_approval: bool = False
    schema_version: int = 1

    @property
    def formulation_id(self) -> str:
        return SEARCH_CANDIDATE_A_FORMULATION_ID

    @property
    def search_object_ids(self) -> Mapping[str, str]:
        return {
            SEARCH_ROLE_DEMAND: self.demand_object_id,
            SEARCH_ROLE_PAID_SPEND: self.paid_spend_object_id,
            SEARCH_ROLE_PAID_DELIVERY: self.paid_delivery_object_id,
            SEARCH_ROLE_PAID_CAP: self.paid_cap_object_id,
            SEARCH_ROLE_ORGANIC_CAPTURE: self.organic_capture_object_id,
            SEARCH_ROLE_DIRECT_NAV_CAPTURE: self.direct_navigation_object_id,
        }

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["formulation_id"] = self.formulation_id
        values["search_object_ids"] = dict(self.search_object_ids)
        return values

    @classmethod
    def from_dict(cls, values: Mapping[str, Any]) -> "SearchCandidateASpec":
        payload = dict(values)
        raw_schema = payload.get("schema_version", 1)
        if (
            isinstance(raw_schema, bool)
            or type(raw_schema) is not int
            or raw_schema != 1
        ):
            raise ValueError(
                f"Unsupported Candidate A schema_version {raw_schema!r}; expected 1"
            )
        formulation_id = payload.get(
            "formulation_id", SEARCH_CANDIDATE_A_FORMULATION_ID
        )
        if formulation_id != SEARCH_CANDIDATE_A_FORMULATION_ID:
            raise ValueError(f"Unsupported Search formulation {formulation_id!r}")
        object_ids = payload.get("search_object_ids") or {}
        for field_name, role in (
            ("demand_object_id", SEARCH_ROLE_DEMAND),
            ("paid_spend_object_id", SEARCH_ROLE_PAID_SPEND),
            ("paid_delivery_object_id", SEARCH_ROLE_PAID_DELIVERY),
            ("paid_cap_object_id", SEARCH_ROLE_PAID_CAP),
            ("organic_capture_object_id", SEARCH_ROLE_ORGANIC_CAPTURE),
            ("direct_navigation_object_id", SEARCH_ROLE_DIRECT_NAV_CAPTURE),
        ):
            payload.setdefault(field_name, object_ids.get(role, ""))
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value for key, value in payload.items() if key in known})


def validate_candidate_a_spec(
    spec: SearchCandidateASpec,
    search_objects: Iterable[SearchObjectDefinition | Mapping[str, Any]] = (),
) -> tuple[str, ...]:
    """Return blocking specification/mapping issues in deterministic order."""

    issues: list[str] = []
    if not spec.outcome_definition_id:
        issues.append("an approved outcome_definition_id is required")
    if not spec.outcome_definition_version:
        issues.append("an approved outcome_definition_version is required")
    if not spec.outcome_definition_fingerprint:
        issues.append("an approved outcome definition fingerprint is required")
    if spec.cap_unit not in {UNIT_MONETARY, UNIT_EXPOSURE_COUNT}:
        issues.append(
            "paid_search_cap must be monetary or exposure_count; it cannot "
            "be treated as a response count"
        )
    if not np.isfinite(spec.cap_to_delivery_scale) or spec.cap_to_delivery_scale <= 0:
        issues.append("cap_to_delivery_scale must be finite and strictly positive")
    if spec.cap_provenance not in SEARCH_CAP_PROVENANCE_VALUES:
        issues.append("paid_search_cap provenance is unresolved")
    if spec.cap_provenance_status != "resolved":
        issues.append("paid_search_cap provenance status must be resolved")
    if spec.pooling_mode not in {"pooled", "partial", "market_specific", "unpooled"}:
        issues.append(f"unsupported Candidate A pooling_mode {spec.pooling_mode!r}")
    if spec.prior_evidence_status == "passed" and not spec.prior_evidence_reference:
        issues.append("passed prior evidence must reference its artefact")
    if not spec.market_scope:
        issues.append("Candidate A market_scope is required")
    for name, value in (
        ("demand_prior_sigma", spec.demand_prior_sigma),
        ("capture_prior_sigma", spec.capture_prior_sigma),
        ("pooling_prior_sigma", spec.pooling_prior_sigma),
    ):
        if not np.isfinite(value) or value <= 0:
            issues.append(f"{name} must be finite and strictly positive")
    if spec.planning_eligible or spec.optimisation_eligible:
        issues.append(
            "Candidate A planning and optimisation remain disabled until "
            "the evidence and explicit approval gates pass"
        )

    ids = list(spec.search_object_ids.items())
    non_empty = [(role, object_id) for role, object_id in ids if object_id]
    if len({object_id for _, object_id in non_empty}) != len(non_empty):
        issues.append("each governed Search object must have a distinct object id")

    current = current_search_object_versions(search_objects)
    by_id: dict[str, SearchObjectDefinition] = {}
    expected_roles = dict(spec.search_object_ids)
    if expected_roles and not current:
        issues.append("governed Search object mappings are unresolved")
    for role, object_id in expected_roles.items():
        if not object_id:
            issues.append(f"mapping for {role} is unresolved")
            continue
        candidates = [
            item
            for item in current
            if item.search_object_id == object_id
            and (spec.market_scope == "*" or item.market in {spec.market_scope, "*"})
        ]
        if len(candidates) > 1:
            issues.append(
                f"Search object {object_id!r} for {role} is ambiguous in market "
                f"scope {spec.market_scope!r}"
            )
            continue
        definition = candidates[0] if candidates else None
        if definition is None:
            issues.append(f"Search object {object_id!r} for {role} is not governed")
        elif definition.search_role != role:
            issues.append(
                f"Search object {object_id!r} is governed as "
                f"{definition.search_role!r}, not {role!r}"
            )
        else:
            by_id[object_id] = definition
    cap = by_id.get(spec.paid_cap_object_id)
    delivery = by_id.get(spec.paid_delivery_object_id)
    spend = by_id.get(spec.paid_spend_object_id)
    if cap is not None and cap.unit != spec.cap_unit:
        issues.append("Candidate A cap_unit does not match the governed cap object")
    if cap is not None and cap.channel:
        counterpart = spend if cap.unit == UNIT_MONETARY else delivery
        if counterpart is None or counterpart.channel != cap.channel:
            issues.append(
                "Paid Search cap and its governed counterpart do not share a channel"
            )
    return tuple(issues)


@dataclass(frozen=True)
class CandidateAForwardState:
    """One forward path, with all demand components in the same units."""

    latent_branded_search_demand: np.ndarray
    unconstrained_paid_search_opportunity: np.ndarray
    realised_paid_search_delivery: np.ndarray
    organic_capture: np.ndarray
    direct_navigation_capture: np.ndarray
    total_captured_demand: np.ndarray
    unmet_demand: np.ndarray
    cap_binding: np.ndarray
    unused_capacity: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value.tolist() if isinstance(value, np.ndarray) else value
            for key, value in asdict(self).items()
        }


def candidate_a_forward(
    latent_branded_search_demand: Sequence[float] | np.ndarray,
    paid_capture_share: float | np.ndarray,
    organic_capture_share: float | np.ndarray,
    direct_navigation_capture_share: float | np.ndarray,
    paid_search_cap: Sequence[float] | np.ndarray,
) -> CandidateAForwardState:
    """Replay Candidate A and enforce reconciliation structurally.

    ``paid_search_cap`` is already translated into delivery/capture units by
    the governed cost/translation mapping. It is not spend and it is never
    returned as realised delivery.
    """

    demand = _as_float_vector(latent_branded_search_demand, "latent demand")
    cap = _as_float_vector(paid_search_cap, "paid_search_cap")
    _same_shape(demand, cap)
    if np.any(demand < 0) or np.any(cap < 0):
        raise SearchCapacityValidationError("latent demand and cap cannot be negative")
    shares = [
        np.broadcast_to(np.asarray(value, dtype=float), demand.shape)
        for value in (
            paid_capture_share,
            organic_capture_share,
            direct_navigation_capture_share,
        )
    ]
    if any(not np.all(np.isfinite(value)) for value in shares):
        raise SearchCapacityValidationError("capture shares must be finite")
    if any(np.any(value < 0) for value in shares):
        raise SearchCapacityValidationError("capture shares cannot be negative")
    if np.any(sum(shares) > 1.0 + 1e-12):
        raise SearchCapacityValidationError(
            "paid, organic, and direct capture shares cannot exceed latent demand"
        )
    paid_opportunity = demand * shares[0]
    organic = demand * shares[1]
    direct = demand * shares[2]
    paid = np.minimum(paid_opportunity, cap)
    captured = organic + direct + paid
    unmet = demand - captured
    if np.any(captured > demand + 1e-9) or np.any(unmet < -1e-9):
        raise SearchCapacityValidationError("Candidate A demand reconciliation failed")
    if not np.allclose(captured + unmet, demand, rtol=1e-10, atol=1e-10):
        raise SearchCapacityValidationError(
            "captured demand plus unmet demand must equal latent demand"
        )
    return CandidateAForwardState(
        latent_branded_search_demand=demand,
        unconstrained_paid_search_opportunity=paid_opportunity,
        realised_paid_search_delivery=paid,
        organic_capture=organic,
        direct_navigation_capture=direct,
        total_captured_demand=captured,
        unmet_demand=unmet,
        cap_binding=np.isclose(paid, cap, rtol=1e-8, atol=1e-8),
        unused_capacity=np.maximum(cap - paid, 0.0),
    )


@dataclass(frozen=True)
class SearchIdentificationReport:
    """Fail-closed evidence about latent demand/capture/cap separation."""

    cap_unique_values: int
    cap_coefficient_of_variation: float
    binding_periods: int
    nonbinding_periods: int
    market_support: Mapping[str, int]
    official_eligible: bool
    blocking_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["market_support"] = dict(self.market_support)
        values["blocking_reasons"] = list(self.blocking_reasons)
        return values


def identify_candidate_a_search(
    paid_search_cap: Sequence[float] | np.ndarray,
    paid_search_delivery: Sequence[float] | np.ndarray,
    *,
    market_labels: Optional[Sequence[str]] = None,
    cap_provenance: str = "",
    cap_mapping_resolved: bool = True,
    capture_mappings_resolved: bool = True,
    min_nonbinding_periods: int = 4,
    min_binding_periods: int = 2,
    min_periods_per_market: int = 8,
) -> SearchIdentificationReport:
    """Diagnose whether Candidate A can be used officially.

    The thresholds are an explicit conservative gate, not a claim that a
    particular threshold proves causal identification. They prevent a prior
    or saturation parameter from manufacturing cap information absent in the
    data.
    """

    cap = _as_float_vector(paid_search_cap, "paid_search_cap")
    delivery = _as_float_vector(paid_search_delivery, "paid_search_delivery")
    _same_shape(cap, delivery)
    if np.any(cap < 0) or np.any(delivery < 0):
        raise SearchCapacityValidationError("cap and delivery cannot be negative")
    if np.any(delivery > cap + 1e-8):
        raise SearchCapacityValidationError(
            "observed Paid Search delivery exceeds its cap"
        )
    labels = np.asarray(
        market_labels if market_labels is not None else ["*" for _ in cap], dtype=str
    )
    if labels.shape != cap.shape:
        raise SearchCapacityValidationError("market_labels must match cap periods")
    binding = np.isclose(delivery, cap, rtol=1e-8, atol=1e-8)
    nonbinding = ~binding
    mean_cap = float(np.mean(cap)) if cap.size else 0.0
    cv = float(np.std(cap) / mean_cap) if mean_cap > 0 else float("inf")
    market_support = {
        str(market): int(np.sum(labels == market))
        for market in sorted(set(labels.tolist()))
    }
    reasons: list[str] = []
    if cap_provenance not in SEARCH_CAP_PROVENANCE_VALUES:
        reasons.append("cap provenance is unresolved")
    if not cap_mapping_resolved:
        reasons.append("cap-to-delivery mapping is unresolved")
    if not capture_mappings_resolved:
        reasons.append("organic/direct/Paid Search capture mappings are unresolved")
    if np.unique(cap).size < 3 or cv <= 0.05:
        reasons.append("cap variation is insufficient to identify capacity effects")
    if int(np.sum(binding)) < min_binding_periods:
        reasons.append("binding-cap support is insufficient")
    if int(np.sum(nonbinding)) < min_nonbinding_periods:
        reasons.append("non-binding cap support is insufficient")
    sparse = [
        market
        for market, count in market_support.items()
        if count < min_periods_per_market
    ]
    if sparse:
        reasons.append("market support is sparse for " + ", ".join(sparse))
    return SearchIdentificationReport(
        cap_unique_values=int(np.unique(cap).size),
        cap_coefficient_of_variation=cv,
        binding_periods=int(np.sum(binding)),
        nonbinding_periods=int(np.sum(nonbinding)),
        market_support=market_support,
        official_eligible=not reasons,
        blocking_reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class SearchPosteriorEffects:
    direct_media_effect: np.ndarray
    realised_mediated_search_effect: np.ndarray
    total_realised_media_effect: np.ndarray
    unrealised_potential: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {key: value.tolist() for key, value in asdict(self).items()}


def counterfactual_search_effects(
    mu_with_realised_search: Sequence[float] | np.ndarray,
    mu_with_direct_media_only: Sequence[float] | np.ndarray,
    mu_without_upstream_media: Sequence[float] | np.ndarray,
    mu_with_unconstrained_search: Sequence[float] | np.ndarray,
) -> SearchPosteriorEffects:
    """Calculate direct/mediated/total effects on the outcome scale.

    All four inputs must be posterior draws evaluated under the same context;
    only the named intervention differs. This prevents eta-scale additions
    and keeps unrealised potential outside realised contribution.
    """

    arrays = [
        np.asarray(value, dtype=float)
        for value in (
            mu_with_realised_search,
            mu_with_direct_media_only,
            mu_without_upstream_media,
            mu_with_unconstrained_search,
        )
    ]
    if any(not np.all(np.isfinite(value)) for value in arrays):
        raise SearchCapacityValidationError("counterfactual predictions must be finite")
    _same_shape(*arrays)
    direct = arrays[1] - arrays[2]
    mediated = arrays[0] - arrays[1]
    total = arrays[0] - arrays[2]
    potential = arrays[3] - arrays[0]
    if not np.allclose(total, direct + mediated, rtol=1e-8, atol=1e-8):
        raise SearchCapacityValidationError(
            "direct plus realised mediated effect does not reconcile"
        )
    return SearchPosteriorEffects(
        direct_media_effect=direct,
        realised_mediated_search_effect=mediated,
        total_realised_media_effect=total,
        unrealised_potential=potential,
    )


@dataclass(frozen=True)
class CandidateAPosteriorOutputs:
    """Required Search posterior outputs, retained separately by meaning."""

    latent_branded_search_demand: np.ndarray
    unconstrained_paid_search_opportunity: np.ndarray
    realised_paid_search_delivery: np.ndarray
    organic_capture: np.ndarray
    direct_navigation_capture: np.ndarray
    total_captured_demand: np.ndarray
    unmet_demand: np.ndarray
    probability_cap_binding: np.ndarray
    unused_capacity: np.ndarray
    direct_media_effect: np.ndarray
    realised_mediated_search_effect: np.ndarray
    total_realised_media_effect: np.ndarray
    unrealised_potential: np.ndarray

    def to_dict(self) -> dict[str, Any]:
        return {key: value.tolist() for key, value in asdict(self).items()}


def posterior_outputs_from_forward_draws(
    states: Sequence[CandidateAForwardState],
    effects: SearchPosteriorEffects,
) -> CandidateAPosteriorOutputs:
    """Aggregate draw-level states only after enforcing each draw's contract."""

    if not states:
        raise SearchCapacityValidationError(
            "at least one posterior forward draw is required"
        )
    arrays = {
        field_name: np.stack([getattr(state, field_name) for state in states])
        for field_name in (
            "latent_branded_search_demand",
            "unconstrained_paid_search_opportunity",
            "realised_paid_search_delivery",
            "organic_capture",
            "direct_navigation_capture",
            "total_captured_demand",
            "unmet_demand",
            "unused_capacity",
        )
    }
    binding = np.stack([state.cap_binding for state in states]).astype(float)
    if not np.allclose(
        arrays["total_captured_demand"] + arrays["unmet_demand"],
        arrays["latent_branded_search_demand"],
        rtol=1e-8,
        atol=1e-8,
    ):
        raise SearchCapacityValidationError("posterior draw reconciliation failed")
    if (
        effects.direct_media_effect.shape
        != arrays["latent_branded_search_demand"].shape
    ):
        raise SearchCapacityValidationError(
            "counterfactual effect draws must match forward draw shape"
        )
    return CandidateAPosteriorOutputs(
        **arrays,
        probability_cap_binding=np.mean(binding, axis=0),
        direct_media_effect=effects.direct_media_effect,
        realised_mediated_search_effect=effects.realised_mediated_search_effect,
        total_realised_media_effect=effects.total_realised_media_effect,
        unrealised_potential=effects.unrealised_potential,
    )


@dataclass(frozen=True)
class SearchUseGate:
    """Separate implementation availability from official-use eligibility."""

    engine_available: bool
    official_use_eligible: bool
    planning_eligible: bool
    optimisation_eligible: bool
    blocking_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        values["blocking_reasons"] = list(self.blocking_reasons)
        return values


def candidate_a_use_gate(
    spec: SearchCandidateASpec,
    identification: SearchIdentificationReport,
    *,
    noisy_recovery_passed: bool = False,
    prior_predictive_passed: bool = False,
    posterior_predictive_passed: bool = False,
    counterfactual_contract_passed: bool = False,
) -> SearchUseGate:
    reasons = list(identification.blocking_reasons)
    if spec.prior_evidence_status != "passed":
        reasons.append("prior-predictive and prior-scale evidence has not passed")
    if not noisy_recovery_passed:
        reasons.append("noisy simulation parameter recovery has not passed")
    if not prior_predictive_passed:
        reasons.append("prior-predictive validation has not passed")
    if not posterior_predictive_passed:
        reasons.append("posterior-predictive validation has not passed")
    if not counterfactual_contract_passed:
        reasons.append("scenario/counterfactual contract validation has not passed")
    if not spec.explicit_model_approval:
        reasons.append("explicit Candidate A model approval is missing")
    official = not reasons
    return SearchUseGate(
        engine_available=True,
        official_use_eligible=official,
        planning_eligible=False,
        optimisation_eligible=False,
        blocking_reasons=tuple(reasons),
    )


@dataclass(frozen=True)
class CandidateASearchFitInputs:
    """The production-integration inputs for
    `attach_candidate_a_demand_capture_chain`: everything the linked Search
    chain needs beyond what the ordinary MMM builder (`core.hierarchical_model.
    build_fh_hierarchical_model`) already computes from `frame`/`spec`.

    `demand_channel_names` must be a subset of the fit's own `channels`
    (validated by the caller against the approved `SearchCandidateAGraphPlan.
    upstream_intervention_node_ids` - REQ-GRAPH-001/`core.graph_model_compiler`)
    so each demand-driving channel keeps its own identity, adstock, and Hill
    saturation exactly like every other channel (AGENTS.md: "Do not create a
    second incompatible adstock or Hill implementation"). `paid_search_cap`
    must already be translated into delivery units by the governed cap
    mapping (`application.model_fit_service`/`core.media_costs`) - this
    dataclass never performs that translation itself.
    """

    spec: SearchCandidateASpec
    demand_channel_names: List[str]
    paid_search_delivery: np.ndarray
    paid_search_cap: np.ndarray
    organic_search_capture: np.ndarray
    direct_navigation_capture: np.ndarray
    search_objects: List[SearchObjectDefinition | Mapping[str, Any]] = field(
        default_factory=list
    )

    def __post_init__(self) -> None:
        if not self.demand_channel_names:
            raise SearchCapacityValidationError(
                "Candidate A requires at least one demand-driving upstream channel"
            )
        arrays = [
            _as_float_vector(value, name)
            for value, name in (
                (self.paid_search_delivery, "paid_search_delivery"),
                (self.paid_search_cap, "paid_search_cap"),
                (self.organic_search_capture, "organic_search_capture"),
                (self.direct_navigation_capture, "direct_navigation_capture"),
            )
        ]
        _same_shape(*arrays)
        if any(np.any(value < 0) for value in arrays):
            raise SearchCapacityValidationError(
                "observed Candidate A capture/delivery/cap values cannot be negative"
            )
        delivery, cap = arrays[0], arrays[1]
        if np.any(delivery > cap + 1e-8):
            raise SearchCapacityValidationError(
                "observed Paid Search delivery exceeds its cap"
            )


def attach_candidate_a_demand_capture_chain(
    *,
    model: "pm.Model",
    sat_media: "pt.TensorVariable",
    channels: Sequence[str],
    market_idx: np.ndarray,
    fit_inputs: CandidateASearchFitInputs,
    prior_config: Optional[Mapping[str, float]] = None,
):
    # No declared return type: pm.Deterministic is untyped (Any) in PyMC's
    # stubs, and every intermediate value in this chain is built from one -
    # an explicit "-> pt.TensorVariable" annotation here would just be an
    # unenforceable claim mypy correctly flags as no-any-return.
    """Add Candidate A's latent-demand/capture-share/cap chain to a model
    already under construction, and return the (n_obs, n_outcomes) outcome
    predictor contribution to add into `eta` alongside the ordinary
    direct/cross-product channel terms.

    Must be called from inside the same `with pm.Model() as model:` block
    that produced `sat_media` (`core.hierarchical_model._market_grouped_
    adstock_and_saturation`) - every demand-driving channel's contribution
    uses that *already adstocked and Hill-saturated* media, per Candidate
    A's approved formulation (`docs/search_mediation_capacity_decision_wp3.md`:
    "X_t is upstream media after the approved adstock/saturation
    transformation").

    Reconciliation (`captured + unmet = latent`) holds by construction: a
    single Dirichlet(4) simplex allocates latent demand into
    paid/organic/direct/unmet shares, so unmet demand can only be driven
    negative if a cap-hit consumes more than the paid share allows - which
    cannot happen, since realised paid delivery is `min(paid_opportunity,
    cap)` and can only ever be <= the paid share of latent demand.
    `core.graph_model_compiler.GraphModelCompiler` (`engine=
    SEARCH_CANDIDATE_A_ENGINE`) excludes the demand/organic/direct-nav
    "search_capture" edges from the ordinary `ResolvedPathwayMasks` it
    returns - organic and direct-navigation capture get their own
    coefficients here, never a second, competing pathway_masks cell.
    """

    import pymc as pm
    import pytensor.tensor as pt

    prior = dict(prior_config or {})
    spec = fit_inputs.spec
    demand_channel_idx = [
        channels.index(name) for name in fit_inputs.demand_channel_names
    ]

    cap = pt.as_tensor_variable(fit_inputs.paid_search_cap)
    delivery_obs = fit_inputs.paid_search_delivery
    organic_obs = fit_inputs.organic_search_capture
    direct_obs = fit_inputs.direct_navigation_capture
    capture_scale = max(float(np.mean(delivery_obs + organic_obs + direct_obs)), 1.0)

    model.add_coord("search_demand_channel", fit_inputs.demand_channel_names)

    demand_market_pool_sigma = pm.HalfNormal(
        "search_demand_market_pool_sigma",
        sigma=float(prior.get("pooling_prior_sigma", spec.pooling_prior_sigma)),
    )
    demand_market_raw = pm.Normal(
        "search_demand_market_raw", mu=0.0, sigma=1.0, dims="market"
    )
    demand_market_offset = pm.Deterministic(
        "search_demand_market_offset",
        demand_market_pool_sigma * demand_market_raw,
        dims="market",
    )
    default_demand_intercept_mu = float(
        np.log(max(float(np.mean(fit_inputs.paid_search_cap)), 1.0))
    )
    demand_intercept = pm.Normal(
        "search_demand_intercept",
        mu=float(prior.get("demand_intercept_mu", default_demand_intercept_mu)),
        sigma=float(prior.get("demand_intercept_sigma", 1.0)),
    )
    demand_media_beta = pm.HalfNormal(
        "search_demand_media_beta",
        sigma=float(prior.get("demand_prior_sigma", spec.demand_prior_sigma)),
        dims="search_demand_channel",
    )
    demand_media_term = pm.math.dot(sat_media[:, demand_channel_idx], demand_media_beta)
    demand = pm.Deterministic(
        "search_latent_branded_demand",
        pt.exp(demand_intercept + demand_market_offset[market_idx] + demand_media_term),
        dims="obs",
    )

    share_alpha = np.asarray(
        prior.get("capture_share_alpha", [2.0, 1.5, 1.5, 2.0]), dtype=float
    )
    if share_alpha.shape != (4,) or np.any(share_alpha <= 0):
        raise SearchCapacityValidationError(
            "capture_share_alpha must have four positive entries"
        )
    capture_shares = pm.Dirichlet("search_capture_shares", a=share_alpha, shape=4)

    paid_opportunity = pm.Deterministic(
        "search_unconstrained_paid_opportunity",
        demand * capture_shares[0],
        dims="obs",
    )
    realised_paid = pm.Deterministic(
        "search_realised_paid_delivery",
        pt.minimum(paid_opportunity, cap),
        dims="obs",
    )
    organic_expected = pm.Deterministic(
        "search_organic_capture_expected", demand * capture_shares[1], dims="obs"
    )
    direct_expected = pm.Deterministic(
        "search_direct_navigation_capture_expected",
        demand * capture_shares[2],
        dims="obs",
    )
    captured = pm.Deterministic(
        "search_total_captured_demand",
        organic_expected + direct_expected + realised_paid,
        dims="obs",
    )
    pm.Deterministic("search_unmet_demand", demand - captured, dims="obs")
    pm.Deterministic(
        "search_cap_binding_probability",
        pt.cast(pt.ge(paid_opportunity, cap), "float64"),
        dims="obs",
    )
    pm.Deterministic(
        "search_unused_capacity", pt.maximum(cap - realised_paid, 0.0), dims="obs"
    )

    delivery_sigma = pm.HalfNormal(
        "search_paid_delivery_observation_sigma",
        sigma=float(prior.get("delivery_observation_sigma", 5.0)),
    )
    capture_obs_sigma = pm.HalfNormal(
        "search_capture_observation_sigma",
        sigma=float(prior.get("capture_observation_sigma", 5.0)),
    )
    pm.Normal(
        "search_paid_delivery_obs",
        mu=realised_paid,
        sigma=delivery_sigma,
        observed=delivery_obs,
        dims="obs",
    )
    pm.Normal(
        "search_organic_capture_obs",
        mu=organic_expected,
        sigma=capture_obs_sigma,
        observed=organic_obs,
        dims="obs",
    )
    pm.Normal(
        "search_direct_navigation_capture_obs",
        mu=direct_expected,
        sigma=capture_obs_sigma,
        observed=direct_obs,
        dims="obs",
    )

    # Separate outcome coefficients for paid/organic/direct capture (REQ-
    # SEARCH-002: "organic and direct-navigation capture may not be pooled
    # with Paid Search capture or counted twice") - non-negative, since
    # captured demand cannot suppress the outcome.
    beta_paid = pm.HalfNormal(
        "search_paid_capture_outcome_beta",
        sigma=float(prior.get("capture_prior_sigma", spec.capture_prior_sigma)),
        dims="outcome",
    )
    beta_organic = pm.HalfNormal(
        "search_organic_capture_outcome_beta",
        sigma=float(prior.get("capture_prior_sigma", spec.capture_prior_sigma)),
        dims="outcome",
    )
    beta_direct = pm.HalfNormal(
        "search_direct_navigation_capture_outcome_beta",
        sigma=float(prior.get("capture_prior_sigma", spec.capture_prior_sigma)),
        dims="outcome",
    )
    eta_search = (
        beta_paid[None, :] * (realised_paid / capture_scale)[:, None]
        + beta_organic[None, :] * (organic_expected / capture_scale)[:, None]
        + beta_direct[None, :] * (direct_expected / capture_scale)[:, None]
    )
    return pm.Deterministic(
        "search_eta_contribution", eta_search, dims=("obs", "outcome")
    )


def build_candidate_a_search_model(
    *,
    upstream_media: Sequence[float] | np.ndarray,
    paid_search_delivery: Sequence[float] | np.ndarray,
    paid_search_cap: Sequence[float] | np.ndarray,
    organic_search_capture: Sequence[float] | np.ndarray,
    direct_navigation_capture: Sequence[float] | np.ndarray,
    final_outcome: Sequence[float] | np.ndarray,
    outcome_definition_id: str,
    outcome_definition_version: str,
    outcome_definition_fingerprint: str,
    cap_unit: str = UNIT_EXPOSURE_COUNT,
    cap_to_delivery_scale: float = 1.0,
    market_idx: Optional[Sequence[int] | np.ndarray] = None,
    market_labels: Optional[Sequence[str]] = None,
    controls: Optional[Sequence[float] | np.ndarray] = None,
    prior_config: Optional[Mapping[str, float]] = None,
):
    """Build the Candidate A linked PyMC model using the existing outcome link.

    This builder is intentionally explicit about the outcome definition and
    consumes separate Search observations. It is an engine capability, not a
    grant of planning eligibility. The ordinary production fit adapter must
    supply governed object mappings and identification evidence before this
    function is used for official artefacts.
    """

    import pymc as pm
    import pytensor.tensor as pt

    prior = dict(prior_config or {})
    arrays = [
        _as_float_vector(value, name)
        for value, name in (
            (upstream_media, "upstream_media"),
            (paid_search_delivery, "paid_search_delivery"),
            (paid_search_cap, "paid_search_cap"),
            (organic_search_capture, "organic_search_capture"),
            (direct_navigation_capture, "direct_navigation_capture"),
            (final_outcome, "final_outcome"),
        )
    ]
    _same_shape(*arrays)
    upstream, delivery, cap, organic, direct, outcome = arrays
    if any(np.any(value < 0) for value in (delivery, cap, organic, direct, outcome)):
        raise SearchCapacityValidationError(
            "observed Candidate A counts cannot be negative"
        )
    if np.any(delivery > cap + 1e-8):
        raise SearchCapacityValidationError("observed Paid Search delivery exceeds cap")
    if (
        not outcome_definition_id
        or not outcome_definition_version
        or not outcome_definition_fingerprint
    ):
        raise SearchCapacityValidationError(
            "an approved versioned outcome definition is required"
        )
    if cap_unit not in {UNIT_MONETARY, UNIT_EXPOSURE_COUNT}:
        raise SearchCapacityValidationError("unsupported cap unit")
    if not np.isfinite(cap_to_delivery_scale) or cap_to_delivery_scale <= 0:
        raise SearchCapacityValidationError("cap_to_delivery_scale must be positive")

    n_obs = upstream.size
    if market_idx is None:
        market_index = np.zeros(n_obs, dtype=int)
    else:
        market_index = np.asarray(market_idx, dtype=int)
        if market_index.shape != upstream.shape or np.any(market_index < 0):
            raise SearchCapacityValidationError(
                "market_idx must match periods and be non-negative"
            )
    n_markets = int(np.max(market_index)) + 1 if market_index.size else 1
    if market_labels is None:
        labels = [str(index) for index in range(n_markets)]
    else:
        labels = list(market_labels)
        if len(labels) != n_markets:
            raise SearchCapacityValidationError(
                "market_labels must match the market index cardinality"
            )
    controls_array = (
        None if controls is None else _as_float_vector(controls, "controls")
    )
    if controls_array is not None and controls_array.shape != upstream.shape:
        raise SearchCapacityValidationError("controls must match periods")

    upstream_mean = float(np.mean(upstream))
    upstream_scale = float(np.std(upstream))
    upstream_scale = upstream_scale if upstream_scale > 0 else 1.0
    x_media = (upstream - upstream_mean) / upstream_scale
    capture_scale = max(float(np.mean(organic + direct + delivery)), 1.0)
    cap_model = cap * cap_to_delivery_scale
    y_mean = max(float(np.mean(outcome)), 1.0)
    share_alpha = np.asarray(
        prior.get("capture_share_alpha", [2.0, 1.5, 1.5, 2.0]), dtype=float
    )
    if share_alpha.shape != (4,) or np.any(share_alpha <= 0):
        raise SearchCapacityValidationError(
            "capture_share_alpha must have four positive entries"
        )

    with pm.Model() as model:
        model.add_coord("obs", np.arange(n_obs))
        model.add_coord("market", labels)
        demand_market_pool_sigma = pm.HalfNormal(
            "demand_market_pool_sigma",
            sigma=float(prior.get("pooling_prior_sigma", 0.3)),
        )
        demand_market_raw = pm.Normal("demand_market_raw", 0.0, 1.0, dims="market")
        demand_market_offset = pm.Deterministic(
            "demand_market_offset",
            demand_market_pool_sigma * demand_market_raw,
            dims="market",
        )
        demand_intercept = pm.Normal(
            "demand_intercept",
            mu=float(prior.get("demand_intercept_mu", np.log(max(np.mean(cap), 1.0)))),
            sigma=float(prior.get("demand_intercept_sigma", 1.0)),
        )
        demand_media_beta = pm.Normal(
            "demand_media_beta",
            mu=0.0,
            sigma=float(prior.get("demand_prior_sigma", 0.5)),
        )
        latent = pm.Deterministic(
            "latent_branded_search_demand",
            pt.exp(
                demand_intercept
                + demand_market_offset[market_index]
                + demand_media_beta * x_media
            ),
            dims="obs",
        )
        capture_shares = pm.Dirichlet("capture_shares", a=share_alpha, shape=4)
        paid_opportunity = pm.Deterministic(
            "unconstrained_paid_search_opportunity",
            latent * capture_shares[0],
            dims="obs",
        )
        realised_paid = pm.Deterministic(
            "realised_paid_search_delivery",
            pt.minimum(paid_opportunity, pt.as_tensor_variable(cap_model)),
            dims="obs",
        )
        organic_expected = pm.Deterministic(
            "organic_capture", latent * capture_shares[1], dims="obs"
        )
        direct_expected = pm.Deterministic(
            "direct_navigation_capture", latent * capture_shares[2], dims="obs"
        )
        captured = pm.Deterministic(
            "total_captured_demand",
            organic_expected + direct_expected + realised_paid,
            dims="obs",
        )
        pm.Deterministic("unmet_demand", latent - captured, dims="obs")
        pm.Deterministic(
            "probability_cap_binding",
            pt.cast(
                pt.ge(paid_opportunity, pt.as_tensor_variable(cap_model)), "float64"
            ),
            dims="obs",
        )
        pm.Deterministic(
            "unused_capacity",
            pt.maximum(pt.as_tensor_variable(cap_model) - realised_paid, 0.0),
            dims="obs",
        )

        delivery_sigma = pm.HalfNormal(
            "paid_delivery_observation_sigma",
            sigma=float(prior.get("delivery_observation_sigma", 5.0)),
        )
        organic_sigma = pm.HalfNormal(
            "organic_observation_sigma",
            sigma=float(prior.get("capture_observation_sigma", 5.0)),
        )
        direct_sigma = pm.HalfNormal(
            "direct_navigation_observation_sigma",
            sigma=float(prior.get("capture_observation_sigma", 5.0)),
        )
        pm.Normal(
            "paid_search_delivery_obs",
            mu=realised_paid,
            sigma=delivery_sigma,
            observed=delivery,
            dims="obs",
        )
        pm.Normal(
            "organic_search_capture_obs",
            mu=organic_expected,
            sigma=organic_sigma,
            observed=organic,
            dims="obs",
        )
        pm.Normal(
            "direct_navigation_capture_obs",
            mu=direct_expected,
            sigma=direct_sigma,
            observed=direct,
            dims="obs",
        )

        direct_beta = pm.Normal(
            "direct_media_beta",
            mu=0.0,
            sigma=float(prior.get("direct_media_sigma", 0.5)),
        )
        search_capture_beta = pm.Normal(
            "search_capture_beta",
            mu=0.0,
            sigma=float(prior.get("capture_prior_sigma", 0.5)),
        )
        outcome_intercept = pm.Normal(
            "outcome_intercept",
            mu=np.log(y_mean),
            sigma=float(prior.get("outcome_intercept_sigma", 1.0)),
        )
        control_effect = pt.zeros(n_obs)
        if controls_array is not None:
            control_beta = pm.Normal("control_beta", mu=0.0, sigma=0.5)
            control_effect = control_beta * controls_array
        eta = (
            outcome_intercept
            + direct_beta * x_media
            + search_capture_beta * (captured / capture_scale)
            + control_effect
        )
        mu = pm.Deterministic("mu", pt.clip(pt.exp(eta), 1e-6, 1e9), dims="obs")
        # Outcome-scale counterfactuals are deterministics in the linked
        # model, so extraction never adds eta terms or independently
        # summarised component medians. The direct pathway is held fixed
        # while the endogenous Search state is regenerated under each
        # counterfactual.
        latent_without_upstream = pm.Deterministic(
            "latent_demand_without_upstream_media",
            pt.exp(demand_intercept + demand_market_offset[market_index]),
            dims="obs",
        )
        paid_opportunity_without_upstream = latent_without_upstream * capture_shares[0]
        paid_realised_without_upstream = pt.minimum(
            paid_opportunity_without_upstream, pt.as_tensor_variable(cap_model)
        )
        captured_without_upstream = (
            latent_without_upstream * capture_shares[1]
            + latent_without_upstream * capture_shares[2]
            + paid_realised_without_upstream
        )
        captured_unconstrained = organic_expected + direct_expected + paid_opportunity
        mu_direct_only = pm.Deterministic(
            "mu_direct_media_only",
            pt.clip(
                pt.exp(outcome_intercept + direct_beta * x_media + control_effect),
                1e-6,
                1e9,
            ),
            dims="obs",
        )
        mu_without_upstream = pm.Deterministic(
            "mu_without_upstream_media",
            pt.clip(
                pt.exp(
                    outcome_intercept
                    + search_capture_beta * (captured_without_upstream / capture_scale)
                    + control_effect
                ),
                1e-6,
                1e9,
            ),
            dims="obs",
        )
        mu_unconstrained = pm.Deterministic(
            "mu_unconstrained_search",
            pt.clip(
                pt.exp(
                    outcome_intercept
                    + direct_beta * x_media
                    + search_capture_beta * (captured_unconstrained / capture_scale)
                    + control_effect
                ),
                1e-6,
                1e9,
            ),
            dims="obs",
        )
        pm.Deterministic(
            "direct_media_effect", mu_direct_only - mu_without_upstream, dims="obs"
        )
        pm.Deterministic(
            "realised_mediated_search_effect", mu - mu_direct_only, dims="obs"
        )
        pm.Deterministic(
            "total_realised_media_effect", mu - mu_without_upstream, dims="obs"
        )
        pm.Deterministic("unrealised_potential", mu_unconstrained - mu, dims="obs")
        alpha = pm.Gamma(
            "alpha",
            alpha=float(prior.get("alpha_shape", 2.0)),
            beta=float(prior.get("alpha_rate", 0.1)),
        )
        # The final outcome remains the existing approved count likelihood
        # and log link used by core.hierarchical_model.
        pm.NegativeBinomial("y_obs", mu=mu, alpha=alpha, observed=outcome, dims="obs")

    model._candidate_a_metadata = {
        "formulation_id": SEARCH_CANDIDATE_A_FORMULATION_ID,
        "outcome_definition_id": outcome_definition_id,
        "outcome_definition_version": outcome_definition_version,
        "outcome_definition_fingerprint": outcome_definition_fingerprint,
        "cap_unit": cap_unit,
        "cap_to_delivery_scale": float(cap_to_delivery_scale),
        "upstream_media_mean": upstream_mean,
        "upstream_media_scale": upstream_scale,
        "capture_scale": capture_scale,
        "pooling_mode": "partial",
        "planning_eligible": False,
        "optimisation_eligible": False,
    }
    return model


__all__ = [
    "CandidateAForwardState",
    "CandidateAPosteriorOutputs",
    "CandidateASearchFitInputs",
    "SEARCH_CANDIDATE_A_ENGINE",
    "SEARCH_CANDIDATE_A_FORMULATION_ID",
    "SearchCandidateASpec",
    "SearchCapacityValidationError",
    "SearchIdentificationReport",
    "SearchPosteriorEffects",
    "SearchUseGate",
    "attach_candidate_a_demand_capture_chain",
    "build_candidate_a_search_model",
    "candidate_a_forward",
    "candidate_a_use_gate",
    "counterfactual_search_effects",
    "identify_candidate_a_search",
    "posterior_outputs_from_forward_draws",
    "validate_candidate_a_spec",
]
