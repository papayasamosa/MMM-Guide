"""Production-integration glue: wires the governed named-event registry
(`core.named_events`) and the approved S3 regularised-spline-basis
statistical method (`core.named_event_response`, Decision 12) into a real
model-fitting call (`core.hierarchical_model.build_fh_hierarchical_model`'s
optional `named_event_fit_inputs` parameter).

`core.named_event_response`'s own decision record
(`docs/named_event_response_method_decision_record.md`) explicitly scopes
itself to "the deterministic basis-construction and window-policy contract
only," naming the actual model-fitting wiring as "a separate, materially
statistical follow-up requiring its own synthetic-recovery validation on
the ACTUAL family windows chosen [t]here" as the next reasonable step, not
performed there. This module is that follow-up's *construction* half; the
*validation* half is `ancestry_mmm/tests/test_named_event_response_
recovery_posterior.py` (real `pm.sample` NUTS recovery against a planted
synthetic event effect, mirroring `core.search_candidate_a_recovery`'s own
precedent for exactly this kind of production-integration evidence).

Nothing here invents a new statistical mechanism: `build_named_event_fit_
inputs` only calls `core.named_event_response`'s own
`build_event_relative_design_matrix`/`build_spline_basis` functions, over
the registry's own factual occurrence dates
(`core.named_events.NamedEventOccurrence.start_date`/`end_date`, never
shifted) and each family's own approved
`EventResponseDefinition.max_lead`/`max_lag` window - never a new kernel,
a different window, or a business date invented here.

**Explicit per-family opt-in gate** (mirrors Decision 11's identical guard
on `core.experiment_lift_test_mapping` - "registering an event/experiment
must never silently calibrate a model"): a family is consumed at fit time
only when its current `EventResponseDefinition.transformation_method_
reference` exactly equals `NAMED_EVENT_RESPONSE_STRUCTURE`
(`"S3_regularised_spline_basis"`). A response definition with any other
(or blank) reference - which is every response definition registered
before this module existed, and remains the default for any new one -
stays registered metadata only, exactly as before: `build_named_event_
fit_inputs` returns `None` (not an empty-but-present object) whenever
nothing in the registry opts in, so a caller can treat "no named events
configured" and "no named events opted in yet" identically to "no fit
inputs supplied at all" - `core.hierarchical_model.build_fh_hierarchical_
model(..., named_event_fit_inputs=None)` (the default) reproduces exactly
today's behaviour, byte-for-byte, for every project that does not
explicitly opt a family in.

**Pooling default** (Decision 12, dimension 4 - "unpooled per market/
family by default; partial pooling ... permitted only when repeated-event
support and validation justify it", and `core.named_event_response.
assess_family_pooling_eligibility` fails closed with no approved
threshold): each `(market, family)` combination present in the data gets
its own independent spline-coefficient block (`NamedEventFamilyFitBlock`),
never a coefficient shared across markets. Coefficients within one family
DO share one family-level shrinkage scale (`tau`) across every market that
family occurs in - a disclosed, reasonable default this module makes
(no existing record specifies whether `tau` is per-family or global; the
per-family choice keeps one family's window/amplitude from being
regularised by an unrelated family's evidence, which a single global
`tau` would do).

**Outcome scope**: an empty `EventResponseDefinition.outcome_scope` is
treated as "applies to every fitted outcome" - a disclosed choice this
module makes (no existing consumer of any `*_scope` field in this
repository establishes an empty-means-what convention to follow instead),
chosen as the least-surprising default (an analyst who does not restrict
scope should not have their event silently excluded from every outcome).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .named_event_response import (
    EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE,
    NAMED_EVENT_RESPONSE_STRUCTURE,
    build_event_relative_design_matrix,
    build_spline_basis,
)
from .named_events import (
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
    current_family_versions,
    current_occurrence_versions,
    current_response_definition_versions,
)

NAMED_EVENT_FIT_INPUTS_VERSION = "named-event-fit-inputs-v1"


@dataclass(frozen=True)
class NamedEventFamilyFitBlock:
    """One `(market, family)`'s spline-basis design matrix, already
    embedded into this fit's full `(n_obs, n_basis)` row range (zero
    outside that market's own rows - `core.hierarchical_model`'s
    `market_bounds` convention) - ready to `pm.math.dot` with a
    `pm.Normal` coefficient vector of width `design.shape[1]`. `n_basis`
    matches `core.named_event_response.build_spline_basis`'s own output
    width for this family's governed window."""

    family_id: str
    market: str
    design: np.ndarray
    response_definition_id: str
    response_definition_version: int
    outcome_scope: Tuple[str, ...]


@dataclass(frozen=True)
class NamedEventFitInputs:
    """Production-integration inputs for `core.hierarchical_model.
    build_fh_hierarchical_model`'s optional `named_event_fit_inputs`
    parameter - everything the additive event-response `eta` term needs
    beyond what the ordinary builder already computes from `frame`/
    `spec`, mirroring `core.search_capacity.CandidateASearchFitInputs`'s
    own "production-integration inputs" naming and role."""

    blocks: Tuple[NamedEventFamilyFitBlock, ...]
    shrinkage_prior_scale_by_family: Mapping[str, float]
    version: str = NAMED_EVENT_FIT_INPUTS_VERSION

    @property
    def family_ids(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for block in self.blocks:
            if block.family_id not in seen:
                seen.append(block.family_id)
        return tuple(seen)

    def blocks_for_family(self, family_id: str) -> Tuple[NamedEventFamilyFitBlock, ...]:
        return tuple(b for b in self.blocks if b.family_id == family_id)

    def consumed_response_definitions(self) -> Tuple[Tuple[str, int], ...]:
        """`(response_definition_id, response_definition_version)` pairs
        actually consumed at fit time, in first-seen order - for
        `FHModelMeta`'s fit-time provenance record (mirrors
        `causal_graph_id`/`causal_graph_version`'s own "which governed
        identity was actually authoritative for this fit" pattern)."""
        seen: List[Tuple[str, int]] = []
        for block in self.blocks:
            pair = (block.response_definition_id, block.response_definition_version)
            if pair not in seen:
                seen.append(pair)
        return tuple(seen)


def build_named_event_fit_inputs(
    frame: Mapping[str, Any],
    *,
    families: Sequence[NamedEventFamily],
    occurrences: Sequence[NamedEventOccurrence],
    response_definitions: Sequence[EventResponseDefinition],
) -> Optional[NamedEventFitInputs]:
    """Build `NamedEventFitInputs` for this fit's actual `(market, week)`
    grid (`frame["markets"]`/`frame["dates"]`/`frame["market_bounds"]` -
    `data.preprocessor.prepare_fh_modeling_frame`'s own contiguous-
    per-market-block layout) from the governed registry.

    Returns `None` (never an empty-but-present object) when nothing in
    the registry opts in to production fitting (see module docstring for
    the opt-in gate) - so a caller can treat "no named events configured"
    and "no named events opted in yet" identically to "no fit inputs
    supplied at all".
    """
    markets: List[str] = list(frame["markets"])
    dates = np.asarray(frame["dates"])
    market_bounds: List[Tuple[int, int]] = list(frame["market_bounds"])
    n_obs = len(dates)

    current_families = {f.family_id: f for f in current_family_versions(families)}
    opted_in_definitions = [
        d
        for d in current_response_definition_versions(response_definitions)
        if d.transformation_method_reference == NAMED_EVENT_RESPONSE_STRUCTURE
    ]
    if not opted_in_definitions:
        return None
    current_occurrences = current_occurrence_versions(occurrences)

    blocks: List[NamedEventFamilyFitBlock] = []
    shrinkage_scale_by_family: Dict[str, float] = {}

    for definition in opted_in_definitions:
        family = current_families.get(definition.family_id)
        if family is None:
            # core.named_events.validate_registry_references already
            # reports an orphan family link as a registry problem
            # elsewhere - this function never fabricates a family here.
            continue
        family_occurrences = [
            occ for occ in current_occurrences if occ.family_id == family.family_id
        ]
        if not family_occurrences:
            continue
        max_lead = definition.max_lead
        max_lag = definition.max_lag
        if max_lead == 0 and max_lag == 0:
            # build_spline_basis requires a non-degenerate window; a
            # response definition recorded with no support at all simply
            # contributes nothing, never an error at fit time.
            continue

        for market_i, market in enumerate(markets):
            start, end = market_bounds[market_i]
            n_weeks = end - start
            market_dates = pd.to_datetime(dates[start:end])

            event_week_set: set[int] = set()
            for occ in family_occurrences:
                if market not in occ.market_scope:
                    continue
                occ_start = pd.Timestamp(occ.start_date)
                occ_end = pd.Timestamp(occ.end_date)
                mask = (market_dates >= occ_start) & (market_dates <= occ_end)
                event_week_set.update(int(i) for i in np.where(mask)[0])
            if not event_week_set:
                continue

            design_matrix = build_event_relative_design_matrix(
                sorted(event_week_set),
                n_weeks,
                max_lead_weeks=max_lead,
                max_lag_weeks=max_lag,
            )
            basis = build_spline_basis(max_lead_weeks=max_lead, max_lag_weeks=max_lag)
            local_design = design_matrix @ basis  # (n_weeks, n_basis)

            full_design = np.zeros((n_obs, local_design.shape[1]))
            full_design[start:end, :] = local_design

            blocks.append(
                NamedEventFamilyFitBlock(
                    family_id=family.family_id,
                    market=market,
                    design=full_design,
                    response_definition_id=definition.response_definition_id,
                    response_definition_version=definition.response_definition_version,
                    outcome_scope=tuple(definition.outcome_scope),
                )
            )
            shrinkage_scale_by_family.setdefault(
                family.family_id, EVENT_RESPONSE_SHRINKAGE_PRIOR_DEFAULT_SCALE
            )

    if not blocks:
        return None

    return NamedEventFitInputs(
        blocks=tuple(blocks),
        shrinkage_prior_scale_by_family=shrinkage_scale_by_family,
    )
