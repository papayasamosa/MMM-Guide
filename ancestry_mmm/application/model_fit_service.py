"""
Model fit service — the one place that decides which model-builder engine
(ordinary shared MMM, ordinary market-specific MMM, or the Candidate A
linked Search MMM) a fit uses, and dispatches to it. WP1
(`Media-Mix-Lab: Coding LLM Next Steps After PR #253`): before this module
existed, `pages/05_Model_Training.py` selected between
`core.hierarchical_model.build_fh_hierarchical_model` and
`core.market_specific_model.build_fh_market_specific_model` with an inline
ternary on `model_type`, and had no path to the Candidate A engine at all.

Engine selection is governed, never a hidden UI toggle: it comes from
whether the project's approved causal graph requires the Candidate A engine
(`core.graph_model_compiler.check_engine_capability`), not from a flag an
analyst sets directly. A graph the ordinary engine already supports never
routes to Candidate A, even if governed Search objects happen to exist.

Framework-independent: importing this module does not import Streamlit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ancestry_mmm.core.causal_graph import CausalGraph
from ancestry_mmm.core.graph_model_compiler import (
    GRAPH_ENGINE_PYMC_HIERARCHICAL,
    check_engine_capability,
)
from ancestry_mmm.core.hierarchical_model import (
    FHModelMeta,
    build_fh_hierarchical_model,
)
from ancestry_mmm.core.market_specific_model import build_fh_market_specific_model
from ancestry_mmm.core.named_event_fit_inputs import NamedEventFitInputs
from ancestry_mmm.core.experiment_lift_test_mapping import ModelLiftTestCalibrationInput
from ancestry_mmm.core.schema import ModelSpec
from ancestry_mmm.core.search_capacity import (
    SEARCH_CANDIDATE_A_ENGINE,
    CandidateASearchFitInputs,
    SearchCandidateASpec,
    SearchIdentificationReport,
    identify_candidate_a_search,
    validate_candidate_a_spec,
)
from ancestry_mmm.core.seo_visibility import SeoModelFitInputs
from ancestry_mmm.core.search_objects import SearchObjectDefinition

MODEL_TYPE_SHARED = "shared"
MODEL_TYPE_MARKET_SPECIFIC = "market_specific"


class ModelFitServiceError(ValueError):
    """Raised when the requested fit configuration cannot be built - always
    with the specific, attributable reason(s), never a bare rejection."""


def resolve_engine(
    *,
    causal_graph: Optional[CausalGraph],
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
) -> str:
    """Decide which engine an approved graph requires - governed by the
    graph's own structure, never a caller-supplied flag.

    No graph configured: the legacy pathway-catalogue path
    (`GRAPH_ENGINE_PYMC_HIERARCHICAL`, exactly today's behaviour when
    `causal_graph` is None inside the ordinary builders).

    A graph the ordinary engine can already compile: `GRAPH_ENGINE_
    PYMC_HIERARCHICAL`, even if governed Search objects exist elsewhere in
    the project - registering a Search object never changes fitting
    behaviour by itself (REQ-SEARCH-001 S7).

    A graph the ordinary engine cannot compile: `SEARCH_CANDIDATE_A_ENGINE`
    only if the Candidate A engine *can* compile it - otherwise this raises,
    since a graph neither engine supports must fail closed here rather than
    reach a builder that will raise a less specific error.
    """
    if causal_graph is None:
        return GRAPH_ENGINE_PYMC_HIERARCHICAL
    ordinary_issues = check_engine_capability(
        causal_graph, engine=GRAPH_ENGINE_PYMC_HIERARCHICAL
    )
    if not ordinary_issues:
        return GRAPH_ENGINE_PYMC_HIERARCHICAL
    candidate_a_issues = check_engine_capability(
        causal_graph, engine=SEARCH_CANDIDATE_A_ENGINE, search_objects=search_objects
    )
    if not candidate_a_issues:
        return SEARCH_CANDIDATE_A_ENGINE
    raise ModelFitServiceError(
        "Approved graph is not supported by any known engine. Ordinary engine: "
        + "; ".join(ordinary_issues)
        + ". Candidate A engine: "
        + "; ".join(candidate_a_issues)
    )


@dataclass(frozen=True)
class CandidateAReadiness:
    """Fail-closed evidence gate for using Candidate A in this fit, separate
    from whether the graph merely requires the engine (`resolve_engine`).
    Engine-required does not imply official-use-eligible - see
    `core.search_capacity.candidate_a_use_gate`; this fit-time gate only
    blocks fitting itself (spec/mapping validity and basic identification),
    not the separate official/planning/optimisation gates."""

    is_ready: bool
    spec_issues: Tuple[str, ...] = ()
    identification: Optional[SearchIdentificationReport] = None

    @property
    def blocking_reasons(self) -> Tuple[str, ...]:
        reasons = list(self.spec_issues)
        if self.identification is not None:
            reasons.extend(self.identification.blocking_reasons)
        return tuple(reasons)


def check_candidate_a_fit_readiness(
    *,
    spec: SearchCandidateASpec,
    fit_inputs: CandidateASearchFitInputs,
    market_labels: Optional[Sequence[str]] = None,
) -> CandidateAReadiness:
    """Governed Search object mapping and basic cap-identification checks -
    run before a Candidate A fit is attempted, not only after it completes.
    Does not itself grant official/planning/optimisation eligibility
    (`core.search_capacity.candidate_a_use_gate` remains the single source
    of truth for that, and requires evidence this fit-time check cannot
    produce, e.g. noisy recovery)."""
    spec_issues = validate_candidate_a_spec(spec, fit_inputs.search_objects)
    identification = identify_candidate_a_search(
        fit_inputs.paid_search_cap,
        fit_inputs.paid_search_delivery,
        market_labels=market_labels,
        cap_to_delivery_scale=spec.cap_to_delivery_scale,
        cap_provenance=spec.cap_provenance,
        cap_mapping_resolved=spec.cap_provenance_status == "resolved",
        capture_mappings_resolved=not spec_issues,
    )
    return CandidateAReadiness(
        is_ready=not spec_issues and identification.official_eligible,
        spec_issues=spec_issues,
        identification=identification,
    )


@dataclass
class ModelFitResult:
    model: Any  # pm.Model - untyped to keep this module import-light
    meta: FHModelMeta
    engine: str
    model_type: str
    candidate_a_readiness: Optional[CandidateAReadiness] = None


def build_model_for_spec(
    *,
    frame: Dict[str, Any],
    model_spec: ModelSpec,
    model_type: str = MODEL_TYPE_SHARED,
    dna_lag_weeks: int = 4,
    dna_outcome_id: Optional[str] = None,
    prior_config: Optional[Dict] = None,
    direct_dna_outcome_ids: Optional[List[str]] = None,
    causal_graph: Optional[CausalGraph] = None,
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
    candidate_a_fit_inputs: Optional[CandidateASearchFitInputs] = None,
    named_event_fit_inputs: Optional[NamedEventFitInputs] = None,
    calibration_inputs: Optional[Sequence[ModelLiftTestCalibrationInput]] = None,
    seo_fit_inputs: Optional[SeoModelFitInputs] = None,
) -> ModelFitResult:
    """The one place `pages/05_Model_Training.py` (or any non-Streamlit
    caller - a future FastAPI service, a batch job) should build a proposed
    or fitted model from, instead of branching on `model_type` inline.

    `candidate_a_fit_inputs` is optional even when the resolved engine is
    Candidate A: a caller building only a truthful status preview (e.g. "is
    this project Candidate A-shaped?") does not need to have already
    assembled Search observation arrays. Actually fitting raises
    ModelFitServiceError if the engine requires it and it is missing.
    """
    engine = resolve_engine(causal_graph=causal_graph, search_objects=search_objects)

    if engine == SEARCH_CANDIDATE_A_ENGINE:
        if model_type != MODEL_TYPE_SHARED:
            raise ModelFitServiceError(
                "Candidate A is only integrated with the shared joint-hierarchical "
                "builder in this release; market-specific (Model C) integration is "
                "a documented follow-up, not yet available."
            )
        if candidate_a_fit_inputs is None:
            raise ModelFitServiceError(
                "The approved graph requires the Candidate A engine, but no "
                "Candidate A Search observations were supplied for this fit."
            )
        readiness = check_candidate_a_fit_readiness(
            spec=candidate_a_fit_inputs.spec,
            fit_inputs=candidate_a_fit_inputs,
            market_labels=frame.get("markets"),
        )
        if not readiness.is_ready:
            raise ModelFitServiceError(
                "Candidate A fit-readiness check failed: "
                + "; ".join(readiness.blocking_reasons)
            )
        model, meta = build_fh_hierarchical_model(
            frame,
            model_spec,
            dna_lag_weeks=dna_lag_weeks,
            dna_outcome_id=dna_outcome_id,
            prior_config=prior_config,
            direct_dna_outcome_ids=direct_dna_outcome_ids,
            causal_graph=causal_graph,
            search_candidate_a=candidate_a_fit_inputs,
            named_event_fit_inputs=named_event_fit_inputs,
            calibration_inputs=calibration_inputs,
            seo_fit_inputs=seo_fit_inputs,
        )
        return ModelFitResult(
            model=model,
            meta=meta,
            engine=engine,
            model_type=MODEL_TYPE_SHARED,
            candidate_a_readiness=readiness,
        )

    builder = (
        build_fh_market_specific_model
        if model_type == MODEL_TYPE_MARKET_SPECIFIC
        else build_fh_hierarchical_model
    )
    model, meta = builder(
        frame,
        model_spec,
        dna_lag_weeks=dna_lag_weeks,
        dna_outcome_id=dna_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=causal_graph,
        named_event_fit_inputs=named_event_fit_inputs,
        calibration_inputs=calibration_inputs,
        seo_fit_inputs=seo_fit_inputs,
    )
    return ModelFitResult(
        model=model,
        meta=meta,
        engine=engine,
        model_type=model_type,
    )


__all__ = [
    "MODEL_TYPE_MARKET_SPECIFIC",
    "MODEL_TYPE_SHARED",
    "CandidateAReadiness",
    "ModelFitResult",
    "ModelFitServiceError",
    "build_model_for_spec",
    "check_candidate_a_fit_readiness",
    "resolve_engine",
]
