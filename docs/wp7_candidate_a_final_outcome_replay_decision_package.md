# Candidate A final-outcome replay decision package (Work Package 7)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`REQ-SEARCH-002` approved Candidate A (structural latent demand with hard
censoring) as the production Search mediation/capacity formulation
(2026-08-15) - that formulation choice is settled and is **not** reopened
here. What remains genuinely unresolved, identified as far back as this
formulation's own Work Package 3 (`docs/decision_log.md`, "Full replay
integration" entry) and still open after every subsequent work package
that has touched Candidate A since, is narrower and different: **how a
hypothetical scenario/curve/plan spend point maps to a counterfactual
Search demand/capture/cap state**, so that `core.predict.predict_mu` and
`core.sequential_simulation.simulate_sequential_outcomes` can eventually
stop raising `CandidateAReplayNotSupportedError` for a Candidate A fit.

The exact decision required after this package is reviewed is:

> Select and approve one production strategy for counterfactual Candidate
> A replay (or explicitly reject all candidates below and request another
> package), covering: how upstream media is supplied at a hypothetical
> spend point; how the paid-search cap is specified for a period with no
> observed cap; how far outside the historically observed spend/cap range
> a replay may extrapolate before being treated as unsupported; and how
> posterior uncertainty is propagated through the cap's non-linearity.

This is intentionally not chosen by the coding agent. `core.predict.
predict_mu` and `core.sequential_simulation.simulate_sequential_
outcomes` keep raising `CandidateAReplayNotSupportedError` for a
Candidate A fit until this is decided.

## Why this is a modelling question, not an engineering one

Candidate A's demand/capture/cap chain (`core.search_capacity`,
`add_search_candidate_a_to_model`) is:

```text
latent_branded_search_demand_t = exp(demand_intercept + demand_market_offset
                                      + demand_media_beta * x_media_t)
capture_shares ~ Dirichlet(4)                      # [paid, organic, direct, implicit]
paid_opportunity_t  = latent_t * capture_shares[0]
realised_paid_t     = min(paid_opportunity_t, cap_t)
organic_expected_t  = latent_t * capture_shares[1]
direct_expected_t   = latent_t * capture_shares[2]
search_eta_contribution_t = beta_paid * (realised_paid_t / scale)
                          + beta_organic * (organic_expected_t / scale)
                          + beta_direct * (direct_expected_t / scale)
```

Every quantity above is a **fit-time deterministic** computed once, over
the historical `x_media` (upstream media after the approved adstock/
saturation transform) and the historical, *observed* `cap` array
(`fit_inputs.paid_search_cap` - not a latent parameter, not inferred, a
fixed input array covering only the fitted historical periods). Nothing
in the current model defines this chain as a *function* callable at an
arbitrary candidate `x_media`/`cap` pair the way `core.predict.predict_mu`
re-evaluates the ordinary media/baseline/trend/season/promo/controls
terms at any candidate plan. Making it one raises four genuinely
open questions, not one.

## Candidate approaches to upstream-media input

### Candidate M1 - Direct re-evaluation from the candidate/reference plan's own media

Recompute `latent_branded_search_demand` at the candidate/reference
plan's post-adstock-saturation media exactly the way the fit-time formula
does, substituting the plan's `x_media` for the historical one, using the
same posterior `demand_intercept`/`demand_market_offset`/`demand_media_
beta` draws. Mechanically the most direct option once the remaining
three questions below are resolved; carries the extrapolation risk
discussed under Candidate E below regardless of which cap/uncertainty
candidate accompanies it.

### Candidate M2 - Restrict replay to plans within the fitted media range

As M1, but only for plans whose implied `x_media` stays within (or within
an approved tolerance of) the historically observed range per channel;
outside that range, continue raising `CandidateAReplayNotSupportedError`
(or a more specific successor exception) rather than extrapolating.
Requires approving a specific tolerance/range-check policy - not decided
here.

## Candidate approaches to the paid-search cap at a hypothetical period

The fitted cap is a fixed, observed historical input - a scenario/curve
period has no corresponding observed cap by construction. Candidates,
listed independently of each other:

### Candidate C1 - Reuse the existing future-assumption pattern

Treat the cap exactly as `core.planning.future_context` already treats
exogenous controls: an explicit future value where available, or an
exploratory "hold at last observed value" assumption with the same
not-decision-ready disclosure already required for controls
(`core.planning.future_context`'s `hold_last_observed`/`eligible_for_
hold_last_observed` contract). Reuses an existing, already-approved
disclosure pattern rather than inventing a new one; still requires
approving that this specific assumption (a capacity ceiling, not an
ordinary covariate) is an appropriate use of that pattern.

### Candidate C2 - Require an explicit planning input for the cap

Never hold the cap at a historical value implicitly; require the
analyst (or a governed capacity-planning input elsewhere in the
repository, if one is later approved) to supply an explicit future cap
for every replayed period, failing closed if none is supplied. Removes
the implicit-assumption risk of C1 at the cost of a new required input
this repository does not yet collect anywhere.

### Candidate C3 - Treat the cap as unconstraining for replay purposes

Replay only the *uncapped* opportunity/demand chain (drop the `min(...,
cap)` censoring for scenario/curve purposes), on the reasoning that
planning decisions are about media spend, not capacity operations, and
report the capped/uncapped divergence as a limitation rather than a
resolved number. Simplest to implement; changes what the replayed number
actually represents (an opportunity ceiling-free figure, not the
capacity-constrained delivery the fitted model estimates) - a
interpretation change that itself needs approval, not merely an
implementation shortcut.

## Candidate approaches to extrapolation policy

### Candidate E1 - No explicit bound (trust the fitted functional form)

Allow M1-style replay at any candidate spend level, relying on the
fitted `exp(...)` demand curve's own shape to extrapolate. Simplest;
inherits the general MMM risk of extrapolating a fitted response curve
outside the range the data can identify, with no additional safeguard
specific to Candidate A.

### Candidate E2 - Bounded/flagged extrapolation (pairs naturally with Candidate M2)

Replay is permitted outside the observed range but the result carries an
explicit, structured limitation (mirroring this program's own established
"never silently extrapolate" precedent in `core.curve_artifact`'s
extrapolation-status contract) rather than being indistinguishable from
an in-range result.

### Candidate E3 - Hard block outside the observed range

Raise a specific exception (a Candidate-A-replay analogue of `core.
curve_artifact`'s existing extrapolation blocking) for any candidate
spend level outside an approved tolerance of the historical range,
rather than returning a number with a caveat attached.

## Candidate approaches to posterior uncertainty through the cap non-linearity

`min(paid_opportunity, cap)` is concave in `paid_opportunity` - by
Jensen's inequality, `E[min(X, cap)] <= min(E[X], cap)` whenever `X` is
stochastic near the cap. Candidate A's `capture_shares` (and therefore
`paid_opportunity`) are posterior-drawn, so this is not a hypothetical
edge case near the cap-binding region.

### Candidate U1 - Point-estimate replay only

Replay using posterior-mean (or a single representative draw's)
parameters, matching a non-uncertainty-aware point evaluation. Simplest;
does not represent the cap's non-linear effect on the *distribution* of
outcomes at all - silently understates or overstates expected delivery
near the cap-binding region depending on which point estimate is used.

### Candidate U2 - Draw-consistent replay, mirroring the sequential kernel's own pattern

Evaluate the full chain (including the `min(...)` censoring) once per
posterior draw, exactly mirroring `core.sequential_scenario_evaluation`'s
existing `n_posterior_draws`/draw-consistency contract for the rest of
the sequential-weekly path (REQ-SCEN-003's "Posterior aggregation"
section: aggregate only after the complete path has been evaluated per
draw). Correctly represents the cap's non-linear effect on the outcome
distribution; carries the same per-draw computational cost this
program's own Work Package 6 decision package already flagged as
untested at realistic plan sizes for the rest of the sequential kernel -
compounding that cost, not introducing a new one.

## What this package does not decide

- Which upstream-media candidate (M1/M2), cap candidate (C1/C2/C3),
  extrapolation candidate (E1/E2/E3), or uncertainty candidate (U1/U2) is
  approved, or which combination.
- Any specific extrapolation tolerance, range-check policy, or exception
  taxonomy.
- Whether an approved combination also requires new governed inputs
  (e.g. a future-cap planning input, if Candidate C2 is selected) that do
  not exist anywhere in the repository yet.
- Candidate A-specific Shapley/attribution decomposition
  (`core.attribution`) and the official curve artefact contract
  (`REQ-CURVE-001`) for Candidate A - both already identified in
  `docs/decision_log.md` as blocked by this same replay prerequisite, and
  remain blocked pending the same review, not separately re-litigated
  here.

## Owner and status

**Owner:** Data Science / Platform engineering (decision), Modelling
(counterfactual specification and extrapolation-policy review).

**Status:** the decision-support package remains the authority for the
replay choices. The approved implementation addendum below records the
production integration; it does not change the selected statistical options.

## Implementation addendum, 2026-09-01

Candidate A final-outcome replay is now implemented through the existing
posterior parameter extraction and NumPy replay boundary. The replay uses
the fitted demand/capture/outcome-link variables, applies an explicit
non-negative Paid Search cap before the captured-demand terms, and evaluates
the full final-outcome link once per posterior draw. Historical attribution
uses the fit-pinned historical cap. Curves require one explicit future cap
per market; sequential Scenario Planner and Optimiser paths require one
explicit weekly cap in the `WeeklyPlan`. No historical last value is silently
carried into a future plan.

The same replay is now available to official model-input/monetary curves,
period attribution, sequential planning, sequential optimisation, and the
Results contribution waterfall. Draw-level replay is retained through the
existing posterior sampling loops, so cap non-linearity and parameter
uncertainty are not replaced by posterior summaries added after the fact.
Missing replay variables, invalid caps, missing fit-time cap provenance, and
unsupported named-event combinations fail closed.

The implementation does not grant planning or optimisation approval by
itself. Candidate A still carries its existing evidence/use gates and needs
real governed Google Trends, Search delivery/cap observations, and any
required approval before official use. The long named-event NUTS recovery
run is recorded separately in the durable handoff.
