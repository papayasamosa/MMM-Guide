"""Real `pm.sample` NUTS posterior-recovery evidence against the
*integrated* production named-event model
(`core.hierarchical_model.build_fh_hierarchical_model(...,
named_event_fit_inputs=...)`), fit to the independent synthetic generator
in `core.named_event_response_recovery`.

Separated from the fast structural tests in `test_named_event_
hierarchical_model_wiring.py` so this file can be excluded from the
ordinary Python 3.11/3.12 test jobs and run instead by a dedicated
schedule/manual-only CI job - the same pattern
`test_search_candidate_a_recovery_posterior.py` already established for
exactly this kind of production-integration MCMC cost. Kept to modest
draws/tune/chains for tractability; still meaningfully slower than the
rest of the suite.

`core.named_event_response`'s own decision record explicitly named this
evidence - real recovery at the actual family windows, not WP2's generic
testbed window - as the reasonable next step its own scope boundary
deferred. Passing here is evidence that the wiring in `core.
named_event_fit_inputs`/`core.hierarchical_model` actually lets a fitted
model recover a planted family-specific event effect - not itself a
business approval that any specific family window, prior scale, or
pooling default is final (the decision record's own "STARTING default,
requires real-data prior-predictive recalibration" caveats still apply).

Evidence grade, not exact point recovery (mirrors WP2's own "do not
require exact point recovery for weakly identified parameters" framing,
and the Candidate A recovery suite's identical "interval coverage, not
point recovery" convention) - only 3 planted occurrences is a genuinely
sparse-repeat regime by this project's own WP2 evidence, so some
amplitude shrinkage toward zero is expected and correct behaviour of the
regularising prior, not a bug.
"""

import numpy as np

from ancestry_mmm.core.hierarchical_model import build_fh_hierarchical_model
from ancestry_mmm.core.models import fit_model
from ancestry_mmm.core.named_event_response_recovery import (
    generate_named_event_synthetic_data,
)
from ancestry_mmm.core.schema import ModelSpec


def _spec():
    return ModelSpec(
        date_col="date",
        market_col="market",
        markets=["UK"],
        segment_outcomes={"New": "synthetic_outcome"},
        channels=["TV"],
    )


def _fit(data, *, draws=250, tune=250, chains=2, seed=0):
    model, meta = build_fh_hierarchical_model(
        data.frame,
        _spec(),
        named_event_fit_inputs=data.fit_inputs,
    )
    trace = fit_model(
        model,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=0.9,
        cores=1,
        random_seed=seed,
    )
    return trace, meta


class TestEventEffectDirectionRecovery:
    def test_event_weeks_score_reliably_higher_than_non_event_weeks(self):
        """The core recoverability claim: whatever the exact amplitude
        shrinkage, the fitted model must reliably place the event-relative
        contribution higher at the true event weeks than at weeks far from
        any planted occurrence - the anticipatory bump's *direction* must
        be recovered, not just "the code runs"."""
        data = generate_named_event_synthetic_data(seed=1)
        trace, _meta = _fit(data, draws=200, tune=200, chains=2, seed=1)
        eta_events = trace.posterior["eta_events"].values  # (chain, draw, obs, outcome)
        event_weeks = data.ground_truth["event_weeks"]
        non_event_week = 0  # far from every planted occurrence (first week)
        assert non_event_week not in [
            w + offset
            for w in event_weeks
            for offset in range(-data.ground_truth["max_lead_weeks"], 1)
        ]
        event_score = eta_events[:, :, list(event_weeks), 0].mean()
        non_event_score = eta_events[:, :, non_event_week, 0].mean()
        assert event_score > non_event_score, (
            f"event weeks mean contribution ({event_score:.4f}) was not "
            f"greater than a non-event week's ({non_event_score:.4f})"
        )

    def test_probability_event_week_exceeds_non_event_week_is_high(self):
        """Draw-level (not just posterior-mean) directional evidence -
        mirrors the Candidate A recovery suite's own posterior-level
        (not point-estimate-only) checks."""
        data = generate_named_event_synthetic_data(seed=2)
        trace, _meta = _fit(data, draws=200, tune=200, chains=2, seed=2)
        eta_events = trace.posterior["eta_events"].values
        event_week = data.ground_truth["event_weeks"][0]
        non_event_week = 0
        event_draws = eta_events[:, :, event_week, 0].reshape(-1)
        non_event_draws = eta_events[:, :, non_event_week, 0].reshape(-1)
        prob_higher = float(np.mean(event_draws > non_event_draws))
        assert prob_higher > 0.8, (
            f"P(event week > non-event week) = {prob_higher:.3f}, expected "
            "reliable directional separation"
        )


class TestIntervalCoverageRecovery:
    """Interval-coverage evidence, not point recovery - a single run's
    pass/fail here is evidence, not itself an official-use claim (mirrors
    `test_search_candidate_a_recovery_posterior.py`'s identical framing)."""

    def test_credible_interval_for_peak_week_contribution_covers_truth(self):
        data = generate_named_event_synthetic_data(seed=3)
        trace, _meta = _fit(data, draws=250, tune=250, chains=2, seed=3)
        eta_events = trace.posterior["eta_events"].values
        # The week exactly at an occurrence (offset 0) carries the basis
        # function nearest the boundary knot - the clearest single point
        # to check against `true_eta_event`.
        peak_week = data.ground_truth["event_weeks"][0]
        draws = eta_events[:, :, peak_week, 0].reshape(-1)
        lo, hi = np.quantile(draws, [0.05, 0.95])
        truth = float(data.true_eta_event[peak_week])
        slack = 0.75  # generous - sparse-repeat regime, regularised prior
        assert lo - slack <= truth <= hi + slack, (
            f"90% interval [{lo:.3f}, {hi:.3f}] (+/-{slack} slack) misses "
            f"truth {truth:.3f} at the peak event week"
        )

    def test_backward_compatible_fit_without_named_events_has_no_event_terms(self):
        """Negative control: the same synthetic frame, fit WITHOUT
        `named_event_fit_inputs`, must produce a model with no event
        variables at all - confirms the recovery evidence above is
        actually attributable to the new parameter, not something already
        present in the ordinary builder."""
        data = generate_named_event_synthetic_data(seed=4)
        model, _meta = build_fh_hierarchical_model(data.frame, _spec())
        assert "eta_events" not in model.named_vars
        assert not [n for n in model.named_vars if n.startswith("event_")]
