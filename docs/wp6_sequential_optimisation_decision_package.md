# Sequential-weekly optimisation decision package (Work Package 6)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`REQ-SCEN-001`/`002`/`003` already implement sequential-weekly *manual*
evaluation end to end (`pages/08_Scenario_Planner.py`'s "Sequential
weekly" method on the manual tab: weekly/monthly incremental tables,
short/long response-horizon metrics, terminal carryover, opt-in
posterior uncertainty, and save/export - Work Packages 5 parts 2-4).
Both optimiser tabs (constrained and unconstrained-benchmark) and
`core.optimization`'s objective remain steady-state-monthly-only, and no
approved requirement exists for changing that.

The exact decision required after this package is reviewed is:

> Select and approve one production strategy for sequential-weekly
> optimisation (or explicitly reject all candidates below and request
> another package), covering: which incremental-outcome quantity becomes
> the optimised scalar; how the sequential kernel's per-call cost is made
> tractable inside a numerical search loop (or replaced by an approved
> approximation strategy); and whether the search itself must be
> posterior-aware.

This is intentionally not chosen by the coding agent. `REQ-SCEN-004`
keeps sequential-weekly optimisation out of the current production
contract until this is decided.

## Why this cannot be a mechanical rewiring

`core.optimization.optimize_scenario`'s search
(`ancestry_mmm/core/optimization.py`, `scipy.optimize.minimize`, method
`SLSQP`) calls an analytic, per-month, state-independent objective
(`_objective_factory` → `_steady_state_response_fn` →
`steady_state_outcome_response`/`_market_specific`) potentially hundreds
to low thousands of times per optimisation run - SLSQP is not supplied an
analytic Jacobian, so SciPy finite-differences the objective, calling it
roughly `(n_months × n_channels + 1)` times *per iteration*.

`core.sequential_scenario_evaluation.evaluate_manual_scenario_
sequential` performs a full week-by-week state-transition (adstock
carry-in) simulation per call - each week's state depends on the
previous week's, so no partial or incremental re-evaluation is possible
- and optionally loops that entire simulation once per requested
posterior draw (`n_posterior_draws`). Calling it directly inside SLSQP's
finite-difference inner loop replaces today's cheap analytic objective
with a materially more expensive computational problem per candidate
plan, potentially past interactive UI latency for a realistic multi-
channel, multi-month plan - not a drop-in swap of one function reference
for another.

Separately, the sequential contract natively produces at least three
distinct incremental-outcome quantities per candidate plan
(short-horizon, long-horizon, and terminal carryover - the last kept
reporting-only by `REQ-SCEN-003` unless a later, separately approved
requirement authorises otherwise). Steady-state optimisation has one
unambiguous per-month objective value to sum; sequential optimisation
does not, until one of these (or a defined combination) is chosen as
the target.

## Candidate approaches to search tractability

Presented as distinct, not mutually exclusive with every objective
candidate below - a reviewer may combine one tractability candidate with
one objective candidate.

### Candidate T1 - Direct replay in the search loop

Call `evaluate_manual_scenario_sequential` (posterior-mean parameters,
`n_posterior_draws=0`) as the SLSQP objective directly, unchanged.
Simplest to implement; correctness is automatic since it is the exact
kernel. Risk: untested at realistic plan sizes - may be too slow for
interactive use, and finite-difference gradients of a full recursive
simulation may be numerically noisy (adstock recursion amplifies small
perturbations non-uniformly across weeks). Would need a real timing
measurement against representative multi-channel, multi-month plans
before being trusted for production UI latency - this package does not
supply that measurement.

### Candidate T2 - Reduced-evaluation-budget search

Keep direct replay (T1) but switch to a derivative-free method with an
explicit evaluation cap (e.g. a bounded number of candidate plans, rather
than finite-difference-gradient SLSQP). Reduces total kernel calls at
the cost of solution quality/convergence guarantees; still pays the full
per-call cost of T1, just fewer times. Requires choosing and validating
a specific algorithm and evaluation budget - not decided here.

### Candidate T3 - Two-stage: steady-state search, sequential report

Run today's existing fast steady-state optimiser unchanged to find a
candidate plan, then evaluate that *same* plan once through the exact
sequential kernel afterward - purely for reporting, never inside the
search loop. Avoids the tractability problem entirely (the search never
calls the sequential kernel). Trade-off: the plan chosen is not actually
sequential-optimal - it is steady-state-optimal, sequential-*reported*.
Whether this satisfies what "sequential-weekly optimisation" is supposed
to mean, or under-delivers on it, is precisely the kind of business
question this package raises rather than answers.

### Candidate T4 - Validated fast surrogate inside the search loop

Derive a closed-form or otherwise fast approximation of the sequential
kernel's short/long/terminal outputs for a piecewise-constant weekly
spend path (e.g. exploiting the known closed-form of a geometric-adstock
recursion's steady/transient decomposition), use it only inside the
search loop, and re-evaluate the optimiser's final chosen plan through
the exact kernel for reporting. Could recover most of sequential
optimisation's intent at steady-state-like speed. Requires new
mathematical derivation, and a validation contract proving the surrogate
tracks the exact kernel closely enough to trust the search's chosen
plan - a genuine modelling workstream, not a mechanical implementation
task, and not attempted by this package.

## Candidate approaches to the objective definition

### Candidate O1 - Plan-window total (sum of weekly incremental)

Sum `weekly_incremental` across the full plan window - the direct
sequential analogue of steady-state's per-month sum. Simple, consistent
with how the manual tab already reports "Weekly incremental outcome" and
"Monthly incremental outcome (summed from weekly)."

### Candidate O2 - Short-horizon only

Optimise `short_horizon_incremental` alone (the configured near-term
window, default weeks 0-4). Matches a "fast payback" business framing;
under-weights or ignores value realised later in the plan window.

### Candidate O3 - Long-horizon only

Optimise `long_horizon_incremental` alone (default weeks 5-52).
Matches a "build for sustained response" framing; under-weights near-
term value.

### Candidate O4 - Weighted combination of short- and long-horizon

Optimise an explicit, approved weighting of short- and long-horizon
incremental outcome. Most flexible; requires a specific, approved weight
- itself a business decision, not supplied here.

Terminal carryover is not offered as an objective candidate in any of
the above: `REQ-SCEN-003` already forbids folding it into the
optimisation objective without a separately approved requirement, and
this package does not propose reopening that.

## What this package does not decide

- Which tractability candidate (T1-T4), which objective candidate
  (O1-O4), or which combination is approved.
- Any specific evaluation budget, surrogate-validation tolerance,
  short/long-horizon weighting, or performance benchmark threshold.
- Whether optimisation search itself must be posterior-aware (evaluating
  every candidate plan across sampled draws) or only the final chosen
  plan's reported uncertainty needs to be posterior-aware, mirroring how
  the manual tab's own posterior-uncertainty panel is already a
  separate, opt-in step from the point-estimate evaluation.

## Owner and status

**Owner:** Data Science / Platform engineering (decision), Modelling
(objective/statistical review).

**Status:** Decision-support package only. `REQ-SCEN-004` records the
target-state requirement and keeps this capability explicitly out of
the current production contract pending review of this package.
