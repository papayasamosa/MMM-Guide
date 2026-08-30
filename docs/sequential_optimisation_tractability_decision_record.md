# Sequential-weekly optimisation tractability decision record (Decision 16)

## Why this record exists, and why it can now be written

`docs/wp6_sequential_optimisation_decision_package.md` reserved its
tractability (T1-T4), objective-horizon (O1-O4), and posterior-awareness
candidates from the coding agent, explicitly noting that Candidate T1
"would need a real timing measurement against representative multi-
channel, multi-month plans before being trusted for production UI
latency - this package does not supply that measurement." The user's
2026-08-29 business-decision brief, confirmed in-session 2026-08-30,
explicitly delegates this to benchmarking: "The business requirement is
already decided: the optimiser should use the same sequential response
logic as Scenario Planning and support the objectives and monthly
constraints in the instructions. How you make that computationally
tractable is an engineering/statistical implementation choice. Benchmark
reasonable approaches and choose one that preserves the required
semantics." This record supplies that missing measurement and makes the
resulting selection.

## Benchmark performed

A one-off timing script (not part of the repository) exercised
`core.sequential_simulation.simulate_sequential_outcomes` directly -
the exact per-call kernel wp6 identifies as the tractability bottleneck
- reusing this repository's own existing test fixtures
(`ancestry_mmm/tests/test_sequential_simulation.py`'s `_meta`/`_params`/
`_plan_from_media` helper patterns) rather than a bespoke, unvalidated
harness. Point-estimate parameters (`n_posterior_draws=0`, matching
Candidate T1's own description), single market, 30 repeated calls per
configuration after a warm-up call, on the development machine actually
used for this session (numbers are illustrative of relative cost and
order of magnitude, not a certified production SLA benchmark - see
"Limitations"):

| Configuration | Mean time/call | p95 time/call |
|---|---|---|
| 6 channels, 12-week plan window | 0.337 ms | 0.515 ms |
| 6 channels, 52-week plan window | 0.398 ms | 0.478 ms |
| 10 channels, 52-week plan window | 0.494 ms | 0.521 ms |

Extrapolated total search cost, using SciPy SLSQP's own documented
finite-difference behaviour (calls the objective roughly
`n_decision_variables + 1` times per iteration, `n_decision_variables =
n_months x n_channels` for a monthly-granularity plan, matching wp6's
own framing) - a genuine extrapolation from measured per-call cost, not
a live end-to-end SLSQP run (see "Limitations"):

| Configuration | 20 iterations | 50 iterations | 100 iterations |
|---|---|---|---|
| 6ch / 12-week window (3 months) | 0.13 s | 0.32 s | 0.64 s |
| 6ch / 52-week window (13 months) | 0.63-1.60 s | 1.57-4.00 s | 3.14-7.99 s |
| 10ch / 52-week window (13 months) | 1.29-1.60 s | 3.24-4.00 s | 6.47-7.99 s |

(Two overlapping figures per cell above reflect two separate benchmark
runs during this session; both land in the same range, supporting the
extrapolation's stability.)

**This directly contradicts wp6's own stated hypothesis** ("may be too
slow for interactive use") for realistic plan sizes: even a demanding
100-iteration SLSQP run at 10 channels across a full 52-week/13-month
plan window extrapolates to under 8 seconds total, well within
tolerable interactive UI latency for an optimisation action (not an
instantaneous UI update, but a bounded "run optimisation" action a user
already expects to wait briefly for).

A second check addressed wp6's separate hypothesis that "finite-
difference gradients of a full recursive simulation may be numerically
noisy (adstock recursion amplifies small perturbations non-uniformly
across weeks)": a central finite-difference gradient of the total
incremental outcome with respect to one channel's one-week spend was
computed at five step sizes spanning four orders of magnitude
(`h` from `1e-2` to `1e-6`). The estimated gradient was stable to 7
significant figures across all five step sizes (`0.00045602` for
`h in [1e-2, 1e-5]`, drifting only in the 8th digit at `h=1e-6` -
expected floating-point round-off, not numerical noise). **This
contradicts wp6's second hypothesis too**: geometric adstock and Hill
saturation are smooth, continuously differentiable functions of spend,
so there is no inherent source of gradient noise for SciPy's
finite-difference SLSQP to contend with.

## Decision T (tractability candidate)

**Decision: T1 - direct replay of the exact sequential kernel, at
point-estimate parameters, inside the search loop.** The benchmark
evidence above directly refutes both of wp6's own hypothesized risks
for T1 (interactive-latency cost and gradient noise) at realistic plan
sizes. This makes T2 (reduced-evaluation-budget search, trading solution
quality for speed that is not actually needed) and T4 (a validated fast
surrogate, introducing new unreviewed mathematics to solve a
tractability problem that does not actually exist at these scales)
both unnecessary complexity relative to the evidence. T3 (steady-state
search, sequential report only) is rejected because it would produce a
plan that is steady-state-optimal, not sequential-optimal - failing
"preserve the required semantics" (the user's own explicit design goal
for this decision), which the evidence shows is not necessary to
sacrifice.

Refinement, informed by the benchmark's own methodology: the object
actually called inside the tight search loop should be the raw
numerical kernel (`simulate_sequential_outcomes` +
`compute_incremental_outcome`, what this benchmark measured), not
`core.sequential_scenario_evaluation.evaluate_manual_scenario_
sequential`'s full top-level orchestration (governance/audit-trail
construction, fingerprinting, etc., which the search loop does not need
per-iteration and was not what this benchmark measured). The full
governed evaluation should run exactly once, on the final chosen plan,
for reporting - this preserves T1's principle (the EXACT kernel, not an
approximation, drives the search) while not needlessly paying
governance-wrapper overhead on every SLSQP iteration. This is a
refinement of T1's own description, not a different candidate; it does
not require its own separate benchmark since the wrapper overhead is
governance/audit construction, not additional numerical work on the
simulation itself.

## Decision on posterior-awareness

**Decision: the search itself is NOT posterior-aware** (point-estimate
parameters only, `n_posterior_draws=0`, exactly as this record's
benchmark used). Posterior uncertainty for the final chosen plan is
computed once, as a separate, explicit, opt-in step - mirroring the
existing manual Scenario Planner tab's own already-established UX
pattern, where posterior-uncertainty evaluation is already separate
from and opt-in relative to the point-estimate evaluation (this pattern
is not invented by this record - it is wp6's own already-approved text,
re-applied here consistently rather than re-decided).

## Decision O (objective-horizon candidate)

**Decision: O1 - plan-window total** (sum of weekly incremental outcome
across the full plan window). This is "the direct sequential analogue
of steady-state's per-month sum" (wp6's own description of O1) and
requires no new business input to define - unlike O4 (an explicit
weighting between short- and long-horizon incremental outcome, which
wp6's own text states "requires a specific, approved weight - itself a
business decision, not supplied here") or O2/O3 (which arbitrarily
privilege one horizon over the other with no stated business
justification). O1 most directly "preserves the required semantics" -
the user's own explicit design goal for this whole decision - since it
generalises steady-state's existing total-outcome objective without
introducing an unapproved horizon-weighting assumption. Terminal
carryover remains excluded from the objective, unchanged from wp6's own
already-settled position (`REQ-SCEN-003`'s existing prohibition).

## What this record does not decide

- Any actual rewiring of `core.optimization.py`'s SLSQP call sites to
  use the sequential kernel in place of the steady-state objective - a
  separate, substantial engineering integration (bounds/constraints
  translation, `REQ-OPT-001`'s objective-kind vocabulary wiring,
  existing steady-state code paths must remain available and correct)
  requiring its own dedicated implementation pass and end-to-end
  validation, not attempted here.
- `REQ-OPT-001`'s own objective-KIND vocabulary (max_outcome/max_revenue/
  max_profit/max_roi/min_cpa, already approved in Phase A) - this
  record resolves the objective-HORIZON question (O1-O4), an orthogonal,
  compatible axis: any of `REQ-OPT-001`'s objective kinds can be
  computed over O1's plan-window-total horizon.
- Monthly spend constraints' exact translation into the sequential
  kernel's weekly grid - a separate implementation detail for the actual
  integration pass.

## Limitations of this record's evidence

- The benchmark measured the raw simulation kernel's per-call cost and
  extrapolated total search cost from SciPy's own documented
  finite-difference call-count behaviour - it did NOT run a live,
  end-to-end SLSQP optimisation loop with real bounds/constraints to
  measure actual wall-clock convergence time or genuine convergence
  quality. A future integration pass should re-verify with a real
  end-to-end run before treating this as a certified production
  benchmark, though the extrapolation's inputs (real measured per-call
  cost, SciPy's own documented call-count formula) are themselves
  genuine, not guessed.
- Measured on the development machine used for this session, not a
  production server - relative costs and orders of magnitude should
  transfer, but absolute production latency should be re-measured in
  the actual deployment environment before being quoted as an SLA.
- The gradient-smoothness check used one representative perturbation
  (one channel, one week) at one synthetic parameter set - not an
  exhaustive sweep over every channel/week/parameter combination.

## Implementation

`ancestry_mmm/core/sequential_optimisation_tractability.py` (new):

- `SEQUENTIAL_OPTIMISATION_TRACTABILITY_STRATEGY = "T1_direct_replay_
  point_estimate"`, `SEQUENTIAL_OPTIMISATION_OBJECTIVE_HORIZON =
  "O1_plan_window_total"`, `SEQUENTIAL_OPTIMISATION_SEARCH_IS_POSTERIOR_
  AWARE = False` - governed constants recording the resolution.
- `SequentialKernelBenchmarkEvidence` - the measured benchmark figures
  above, preserved as a structured, versioned record (not only narrative
  prose in this document) so a future session can see exactly what was
  measured and when, and re-run/update it.
- `compute_sequential_plan_objective_value` - the O1 objective helper:
  given a candidate plan, reference plan, shared carry-in, `meta`, and
  point-estimate `params`, returns the scalar plan-window-total
  incremental outcome, using the exact kernel
  (`simulate_sequential_outcomes` + `compute_incremental_outcome`) at
  point-estimate parameters - the function a future `core.optimization`
  integration would call as its SLSQP objective, not implemented here.

This module does not modify `core.optimization.py`, `core.sequential_
simulation.py`, or `core.sequential_scenario_evaluation.py` - it is a
standalone decision-record-plus-helper module, mirroring every other
Phase B/C step's "declare the contract, defer the full fit-time/search-
loop integration" scope boundary already established in this
repository.

Tests: `ancestry_mmm/tests/test_sequential_optimisation_tractability.py`.

## Owner and status

Owner: Data Science / Platform engineering (tractability selection,
benchmarked); Modelling (objective/statistical review, not yet sought
for the full integration). Status: resolved and the objective-helper
function implemented, 2026-08-30, per the user's explicit 2026-08-30
authorisation delegating this benchmarking task (see wp6's updated
text). The full `core.optimization` integration remains a separate,
substantial follow-up.
