# Time-varying latent baseline decision package (Work Package 10)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`docs/specification_authority.md` already lists "Time-varying baseline"
as "No approved requirement/decision yet", pointing to `AGENTS.md`'s
future-variable-role #5 ("latent baseline state — the time-varying
intercept, projected from its own fitted statistical process, never
treated as an ordinary external control") as the standing invariant any
future approval must satisfy. No `REQ-BASELINE-*` (or equivalently named)
record exists, and no time-varying-intercept code path exists anywhere in
`ancestry_mmm/core/` today (`core.hierarchical_model.build_fh_
hierarchical_model` and `core.market_specific_model.build_fh_market_
specific_model` both define `intercept` as a single static `pm.Normal`
per market/outcome, never a function of time). This package is the
missing decision-support document.

The exact decision required after this package is reviewed is:

> Select and approve one production strategy for a time-varying latent
> baseline (or explicitly reject all candidates below and request
> another package), covering: which statistical process generates it;
> how its scale/location are identified under `REQ-LATENT-001`'s existing
> identification contract; and — the genuinely hard question this
> package's own upstream research surfaces — how, if at all, it is
> projected forward for scenario/optimisation planning, given that this
> repository's primary upstream reference for this exact feature
> documents that its own default implementation is unsuitable for that
> purpose.

This is intentionally not chosen by the coding agent. No time-varying
baseline exists anywhere in this repository's fitting engine today;
`core.hierarchical_model`/`core.market_specific_model` continue to use a
single static intercept per market/outcome exactly as before, pending
review of this package.

## Why this is a modelling question, not an engineering one

Per this repository's "Required upstream-reference workflow"
(`AGENTS.md`), the closest relevant upstream implementation was
inspected before writing this package: `pymc-labs/pymc-marketing`'s `MMM`
class supports `time_varying_intercept=True`, implemented as a Hilbert
Space Gaussian Process (HSGP) modelling the intercept's percentage
deviation from a fitted baseline over time. This is directly relevant —
it is the named upstream pattern for exactly the capability
`AGENTS.md`'s role #5 describes — but adopting it surfaces a genuine,
upstream-documented tension with what role #5 also requires:

> "Gaussian Processes (GPs) in Time-Varying Parameters (TVP) models
> revert to their prior mean and exhibit rapidly growing uncertainty
> beyond the training data window... For forecasting beyond a few months
> or for scenario planning, it is recommended to use Fourier seasonality
> for periodic patterns and linear controls for trends instead of the GP
> component." (`pymc-marketing` docs, `time_varying_parameters.md`)

In other words: the standard upstream tool for a time-varying baseline is
explicitly documented as an *in-sample decomposition* device, not a
forward-projectable one — while `AGENTS.md` role #5 requires the latent
baseline to be "projected from its own fitted statistical process" for
planning use. These are not automatically compatible, and reconciling
them is a statistical judgement call, not an implementation detail:

1. **Is the gap this package addresses already filled by existing
   deterministic trend/seasonality, or is it a distinct residual
   component?** `core.hierarchical_model`'s `trend_coef`/`gamma_fourier`
   terms (lines 813-827) and `core.planning.future_context.continue_
   trend`/`continue_fourier` already deterministically continue a
   fitted trend and calendar-anchored Fourier seasonality forward for
   planning — exactly the upstream-recommended alternative to a GP
   intercept for forecasting. A genuinely new "time-varying baseline"
   capability would need to represent something trend and seasonality do
   not already capture (e.g. an unexplained demand-level shift from a
   competitor launch or a pandemic — pymc-marketing's own stated use
   case) - and whether that residual concept is even identifiable
   separately from trend/seasonality/controls in this repository's
   existing model structure is itself unresolved.
2. **How is it identified?** `REQ-LATENT-001`'s Requirement 1 already
   requires "every fitted latent... state that enters a causal pathway
   (including... any future latent baseline state)" to declare an
   identifying strategy via `core.latent_state_identification`. This
   package does not decide which strategy applies to a baseline process
   specifically (fixing a loading, anchoring to an observed quantity, or
   another approved constraint) - a baseline has no obvious analogue to
   Candidate A's capture-share Dirichlet anchor.
3. **How, if at all, is it projected forward?** `AGENTS.md`'s own rule
   ("A latent baseline must not be configured as a Chronos or any
   ordinary external forecast target") already forecloses one path.
   Upstream's own guidance forecloses naive GP extrapolation for anything
   beyond a short horizon. What remains - hold-the-fitted-process-at-its-
   prior-mean (in effect, no genuine future signal), a different
   validated statistical process better suited to extrapolation, or
   restricting the capability to in-sample measurement/diagnostics only
   with no planning use at all - is not decided by this package.

## Candidate approaches to what the baseline represents and how it is fit

### Candidate T1 - HSGP-based time-varying intercept (direct upstream adoption)

Adopt `pymc-marketing`'s `time_varying_intercept=True`/`HSGPKwargs`
pattern directly: the intercept becomes a GP-modelled percentage
deviation from a fitted baseline scalar, added alongside the existing
`trend_coef`/`gamma_fourier` terms in `core.hierarchical_model`/`core.
market_specific_model`. Most directly aligned with the named upstream
reference and least invented machinery; inherits upstream's own
documented weakness for anything beyond in-sample decomposition and
short-horizon forecasting, which conflicts with role #5's planning-
projection requirement unless paired with a restrictive Candidate P
below.

### Candidate T2 - Latent random-walk baseline with explicit process choice

Model the baseline as a discrete-time stochastic process (e.g. a
Gaussian random walk or AR(1)-style process on the log scale) rather
than a GP - a different mathematical family with different
extrapolation behaviour (a random walk's forecast is its last value
plus growing but centred uncertainty, not a reversion to a fixed prior
mean). Potentially better suited to genuine forward projection than
Candidate T1's GP; introduces a new, unreviewed statistical process this
repository has not used before and does not have an upstream `pymc-
marketing` reference for (this exact pattern is not part of `MMM`'s
built-in time-varying-parameters API), so its own priors/behaviour would
need independent statistical review, not just an implementation choice.

### Candidate T3 - No new baseline process; treat the gap as already addressed by trend + Fourier

Conclude that `core.hierarchical_model`'s existing per-market linear
trend and calendar-anchored Fourier seasonality, already deterministically
continued forward by `core.planning.future_context`, already fulfil
role #5's intent for planning purposes, and that a separate "time-varying
baseline" capability is only warranted for retrospective, in-sample
measurement/diagnostics (e.g. explaining a past demand shift), never for
forward projection. Requires no new model-fitting code for the planning
path; leaves the in-sample measurement use case (competitor launch,
pandemic-style shift detection) unaddressed, and does not resolve whether
that measurement-only use case is itself wanted.

## Candidate approaches to forward projection for planning

(Independent of which of T1/T2/T3 is chosen, if a baseline process exists
and any planning use is contemplated at all.)

### Candidate P1 - No planning use; measurement/diagnostics only

The baseline process (if any) is fit and reported for retrospective
explanation only, exactly as `pymc-marketing`'s own documentation
recommends its GP-based TVP be used - never read by
`core.planning.future_context`, `core.sequential_simulation`, or
`core.optimization`. Cleanly avoids the extrapolation problem entirely by
declining to solve it; leaves role #5's word "projected" only partially
satisfied (the *fitting* process is a valid time-varying statistical
process; there is no forward *projection* of it for decisions).

### Candidate P2 - Hold at fitted-process's own steady-state/prior mean

For planning periods, hold the baseline at whatever value its own fitted
process reverts to when extrapolated (a GP's fitted prior mean; a mean-
reverting process's stationary mean) - mirroring `core.planning.
future_context`'s existing `hold_last_observed` pattern in spirit
(explicit, disclosed, exploratory-only), but holding at the process's own
implied long-run value rather than literally the last observed data
point. Reuses this repository's already-approved disclosure pattern;
still requires deciding whether "the GP's own prior mean" is an
acceptable planning assumption to disclose, given upstream's own caution
about growing uncertainty even under that assumption.

### Candidate P3 - Validated continuation via a process actually suited to extrapolation

Restrict Candidate T choice to whichever process (per the T-candidates
above) has genuine, validated extrapolation behaviour appropriate to the
planning horizons `REQ-SCEN-002`/`REQ-SCEN-003` already define, with
recovery/backtest validation analogous to this repository's existing
`pymc-labs/mmm-param-recovery`-informed identifiability checks, before
any planning surface reads it. Most rigorous; requires the T-candidate
decision to be made jointly with this one, since not every T candidate
has a validated extrapolation behaviour to select here.

## What this package does not decide

- Which baseline-process candidate (T1/T2/T3) is approved, or whether a
  genuinely new baseline capability is warranted at all versus concluding
  the existing trend/Fourier continuation already satisfies role #5's
  intent (T3).
- Which forward-projection candidate (P1/P2/P3), or combination, is
  approved.
- The specific identifying strategy (`REQ-LATENT-001`) a baseline process
  would use, beyond noting that record's existing requirement that one be
  declared.
- Any specific `core.hierarchical_model`/`core.market_specific_model`/
  `core.planning.future_context` code change - `core.latent_state_
  identification`'s existing five-strategy contract and `core.planning.
  future_context`'s existing trend/Fourier continuation are both
  untouched by this package.
- Whether resolving this gap is scheduled ahead of or behind any other
  open work-package item - this package only supplies the missing
  decision-support document; it does not reprioritise the program.

## Owner and status

**Owner:** Modelling (baseline-process selection, identification strategy,
extrapolation validation), Data Science / Platform engineering
(implementation once a strategy is approved).

**Status:** Decision-support package only. No time-varying baseline
exists in `core.hierarchical_model`/`core.market_specific_model`; both
continue to use a single static per-market/outcome intercept exactly as
before, pending review of this package.
