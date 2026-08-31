"""Synthetic-data generator for real `pm.sample` NUTS posterior-recovery
evidence against the *integrated* production named-event pathway
(`core.hierarchical_model.build_fh_hierarchical_model(...,
named_event_fit_inputs=...)`), mirroring `core.search_candidate_a_
recovery`'s own role and naming for the Candidate A Search engine.

`core.named_event_response`'s own decision record names this exact kind
of evidence - "re-running recovery evidence at the real 6-week/2-week
windows before production use is a reasonable next step" - as the
validation the wiring in `core.named_event_fit_inputs`/`core.
hierarchical_model` still needed. This module builds the synthetic DGP;
`ancestry_mmm/tests/test_named_event_response_recovery_posterior.py`
(schedule/manual-only, mirroring `test_search_candidate_a_recovery_
posterior.py`) fits the real integrated model against it and checks
recovery.

The planted event contribution is built through the *same* deterministic
functions the real fit inputs use
(`core.named_event_response.build_event_relative_design_matrix`/
`build_spline_basis`) - this generator never uses a different kernel to
create ground truth than the one being tested, which would make any
"recovery" result meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Sequence

import numpy as np
import pandas as pd
import pymc as pm

from .named_event_fit_inputs import (
    NamedEventFitInputs,
    build_named_event_fit_inputs,
)
from .named_event_response import (
    NAMED_EVENT_RESPONSE_STRUCTURE,
)
from .named_events import (
    DEFAULT_EVENT_EVIDENCE_STATUS,
    EventResponseDefinition,
    NamedEventFamily,
    NamedEventOccurrence,
)


@dataclass(frozen=True)
class NamedEventRecoveryData:
    """Everything one recovery test needs: the real production `frame`
    dict (ready to pass straight into `core.hierarchical_model.
    build_fh_hierarchical_model`), the real `NamedEventFitInputs` built
    from the same registry the ground truth was planted from, and the
    ground-truth values a fitted model's posterior should recover."""

    frame: Dict[str, Any]
    fit_inputs: NamedEventFitInputs
    family_id: str
    market: str
    true_event_coefs: np.ndarray
    true_eta_event: np.ndarray  # (n_weeks,) - the planted per-week contribution
    ground_truth: Mapping[str, Any] = field(default_factory=dict)


def generate_named_event_synthetic_data(
    *,
    n_weeks: int = 104,
    event_weeks: Sequence[int] = (20, 55, 90),
    max_lead_weeks: int = 4,
    max_lag_weeks: int = 0,
    true_event_coefs: "np.ndarray | None" = None,
    intercept: float = 3.0,
    alpha: float = 50.0,
    market: str = "UK",
    family_id: str = "mothers_day",
    seed: int = 0,
) -> NamedEventRecoveryData:
    """Generate one synthetic weekly dataset with a planted, known
    family-specific event effect, using the real production construction
    path end to end: a real governed registry (family/occurrences/
    response definition) -> real `build_named_event_fit_inputs` -> the
    real spline-basis design matrix, which is also used (with a known
    coefficient vector) to build the ground-truth mean.

    `event_weeks` are 0-indexed week positions inside the `n_weeks`-long
    grid. `true_event_coefs`, if omitted, defaults to a smooth ramp-up
    shape (increasing toward the event, matching the anticipatory/gifting
    family's own real-world shape) scaled to a magnitude clearly above
    the NegativeBinomial observation noise for `alpha=50`.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-07", periods=n_weeks, freq="W")

    family = NamedEventFamily(
        family_id=family_id,
        family_version=1,
        display_name=family_id.replace("_", " ").title(),
        classification="gifting",
        classification_status=DEFAULT_EVENT_EVIDENCE_STATUS,
    )
    occurrences = [
        NamedEventOccurrence(
            event_id=f"{family_id}-occ-{i}",
            event_version=1,
            display_name=f"{family_id} occurrence {i}",
            start_date=str(dates[week].date()),
            end_date=str(dates[week].date()),
            market_scope=(market,),
            source_id="synthetic",
            family_id=family_id,
        )
        for i, week in enumerate(event_weeks)
    ]
    definition = EventResponseDefinition(
        response_definition_id=f"{family_id}-def",
        response_definition_version=1,
        family_id=family_id,
        treatment="anticipatory",
        max_lead=max_lead_weeks,
        max_lag=max_lag_weeks,
        transformation_method_reference=NAMED_EVENT_RESPONSE_STRUCTURE,
    )

    frame: Dict[str, Any] = {
        "markets": [market],
        "market_idx": np.zeros(n_weeks, dtype=int),
        "market_bounds": [(0, n_weeks)],
        "dates": dates.to_numpy(),
        "channels": ["TV"],
        "dna_channel_idx": [],
        "outcome_ids": ["synthetic_outcome"],
        "X_media": rng.uniform(50.0, 150.0, size=(n_weeks, 1)),
        "X_controls": np.zeros((n_weeks, 0)),
        "control_names": [],
        "fourier": np.zeros((n_weeks, 2)),
        "trend": np.zeros(n_weeks),
        "unpooled_markets": [],
    }

    fit_inputs = build_named_event_fit_inputs(
        frame,
        families=[family],
        occurrences=occurrences,
        response_definitions=[definition],
    )
    assert fit_inputs is not None, (
        "generate_named_event_synthetic_data: the planted registry did not "
        "produce any fit inputs - check event_weeks fall inside n_weeks."
    )
    block = fit_inputs.blocks_for_family(family_id)[0]
    n_basis = block.design.shape[1]

    if true_event_coefs is None:
        # A smooth ramp toward the event (largest weight on the
        # basis function nearest the event boundary), matching the
        # anticipatory/gifting family's own real-world shape - scaled
        # comfortably above NegativeBinomial(alpha=50) observation noise.
        true_event_coefs = np.linspace(0.1, 1.2, n_basis)
    true_event_coefs = np.asarray(true_event_coefs, dtype=float)
    assert true_event_coefs.shape == (n_basis,)

    true_eta_event = block.design @ true_event_coefs  # (n_weeks,)
    eta = intercept + true_eta_event
    mu = np.exp(np.clip(eta, -20, 20))

    y = pm.draw(
        pm.NegativeBinomial.dist(mu=mu, alpha=alpha),
        draws=1,
        random_seed=seed,
    )
    frame["Y"] = np.asarray(y, dtype=float).reshape(n_weeks, 1)
    frame["promo"] = np.zeros((n_weeks, 1))

    return NamedEventRecoveryData(
        frame=frame,
        fit_inputs=fit_inputs,
        family_id=family_id,
        market=market,
        true_event_coefs=true_event_coefs,
        true_eta_event=true_eta_event,
        ground_truth={
            "intercept": intercept,
            "alpha": alpha,
            "event_weeks": tuple(event_weeks),
            "max_lead_weeks": max_lead_weeks,
            "max_lag_weeks": max_lag_weeks,
        },
    )
