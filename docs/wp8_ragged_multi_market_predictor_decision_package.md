# Ragged multi-market predictor decision package (Work Package 8)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`REQ-COVERAGE-001` §6 already names this gap and explicitly declines to
resolve it ("Model-engine mathematics — explicitly not approved by this
record"): `FR-MOD-015` (market-specific/ragged predictor sets inside the
hierarchical model equations) has never had its own decision-support
document laying out candidates with tradeoffs - only a fixed, deliberately
unspecific report string (`core.market_data_capability.
FR_MOD_015_DECISION_REPORT`) naming the shape of the decision needed. This
package is that document.

The exact decision required after this package is reviewed is:

> Select and approve one production strategy for how the fitting engine's
> likelihood should treat a (market, channel) cell with no genuine
> observed coverage (or explicitly reject all candidates below and
> request another package), covering: whether missing coverage is
> masked, restructured, or governed-zero-filled; whether that choice is
> uniform across every missing cell or depends on a recorded reason for
> the missingness; and how a channel's coefficient is estimated for a
> market that contributes no evidence for it under a pooled/hierarchical
> prior.

This is intentionally not chosen by the coding agent. `REQ-COVERAGE-001`
§6 keeps this out of the current production contract, and `core.
market_data_capability.check_engine_capability` continues to report an
unsupported request rather than attempting any of the candidates below.

## Why this is a modelling question, not an engineering one

`core.hierarchical_model.build_fh_hierarchical_model` and `core.
market_specific_model.build_fh_market_specific_model` both consume a
single `X_media` matrix where `spec.channels` supplies one shared column
set applied to every market's rows - `market_bounds` only slices which
*rows* belong to which market, never which *columns* apply. The engine
therefore only validly supports the rectangular case: every requested
channel genuinely observed, for every requested market. This is not a
missing runtime guard (there is no `RaggedPredictorNotSupportedError`
comparable to `CandidateAReplayNotSupportedError`) - the rectangular
assumption is baked into the array shape the model-building code
consumes, one layer below where a guard could even be inserted.

Resolving it requires answering a genuinely statistical question first,
not just an engineering one: **does "no coverage" mean the channel truly
had zero effect/spend in that market (a fact about the world), or does
it mean the channel's exposure there is unobserved but possibly non-zero
(a fact about the data)?** These have different correct treatments, and
the correct interpretation may not even be uniform across every missing
cell - a channel a market's activity plan never included is a different
real situation from a channel that plausibly ran there but was never
instrumented for reporting. `REQ-COVERAGE-001` S1's own governing
principle ("missing is not zero") already forbids assuming the former by
default anywhere else in this repository's data-coverage machinery; this
gap is exactly the one place that principle currently has no approved
mechanical enforcement.

## Candidate approaches

`REQ-COVERAGE-001` §6 names three candidate shapes without choosing among
them; each is elaborated with its tradeoffs below.

### Candidate R1 - Masked/marginalised likelihood term

For each (market, channel) cell with no genuine coverage, exclude that
specific predictor's contribution from that market's likelihood term
entirely, rather than supplying any value (zero or otherwise) for it.
Under a hierarchical/partially-pooled channel coefficient, a market
contributing no likelihood evidence for a parameter still receives a
posterior for it, fully determined by the pooling prior and the other
markets' evidence - the standard, coherent Bayesian treatment of "this
market has no information about this parameter," not a missing-data
workaround bolted on afterward. Tradeoff: requires re-deriving how `eta`/
the linear predictor is assembled per market inside `build_fh_
hierarchical_model`/`build_fh_market_specific_model` to support a
per-market predictor subset rather than one shared column matrix for
every market's rows - a non-trivial rewrite of both model-construction
functions, not a masking flag layered on top of the existing rectangular
array.

### Candidate R2 - Restructure `X_media`/`market_bounds` for genuinely ragged per-market columns

Rebuild the data-preparation and model-construction pipeline
(`data.preprocessor`, `core.hierarchical_model`, `core.market_specific_
model`) so each market supplies only its own supported channel subset -
a genuinely ragged/jagged predictor structure, not a rectangular matrix
with masked cells layered on top. Similar statistical intent to R1 for a
pooled coefficient, but a different, larger implementation shape:
touches the data-preparation layer as well as model construction, and
raises its own sub-question of whether a market's *unpooled* coefficient
for a channel it never had should even exist as a modelled quantity, or
be structurally absent for that market - a hierarchy/pooling-design
question this package does not resolve either.

### Candidate R3 - Explicit, governed zero-fill convention

Treat a market's missing channel as an explicit, approved "zero
exposure" convention, with the assumption recorded and disclosed exactly
where it is invoked - a deliberate, narrow, named exception to `REQ-
COVERAGE-001` S1's "missing is not zero" principle, never a silent
default. Cheapest to implement (the current rectangular engine already
accepts a zero-filled column without any change); statistically weakest
of the three, since it fabricates a specific value for something that
may not mean "no exposure" at all, and - unlike R1's pooling-consistent
treatment - actively competes with the pooling prior with a specific
(possibly wrong) signal rather than contributing no signal.

## A cross-cutting question none of the three candidates alone resolves

`core.coverage`'s own governed missingness-state vocabulary already
distinguishes reasons a (market, channel) cell might lack coverage (e.g.
a channel never active in that market vs. a data-collection gap for a
channel that was active) - REQ-COVERAGE-001 S1's "missing is not zero"
principle was written precisely because these reasons are not
interchangeable. Whether the *same* candidate (R1, R2, or R3) applies
uniformly to every missing cell, or whether the approved answer is
itself a *function of* the recorded missingness reason (e.g. R3 only
where the channel is recorded as genuinely inactive, R1 or R2 everywhere
else), is an additional dimension this package raises rather than
answers - a single "pick R1, R2, or R3" decision may be under-specified
without also deciding this.

## What this package does not decide

- Which candidate (R1/R2/R3), or which missingness-reason-dependent
  combination of them, is approved.
- Whether a channel's coefficient should be pooled/hierarchical or
  market-specific/unpooled for markets with ragged coverage - a
  hierarchy-design question this package surfaces (under Candidate R2)
  but does not resolve.
- Any specific implementation of the governed missingness-reason
  taxonomy this package's cross-cutting question raises, beyond noting
  that `core.coverage` already has one for a different purpose.
- Whether resolving `FR-MOD-015` is scheduled ahead of or behind any
  other open work-package item - this package only supplies the missing
  decision-support document; it does not reprioritise the program.

## Owner and status

**Owner:** Data Science / Platform engineering (decision), Modelling
(missingness-reason taxonomy and hierarchy/pooling review).

**Status:** Decision-support package only. `core.market_data_capability.
check_engine_capability` continues to report an unsupported request for
any (market, channel) cell lacking governed coverage, exactly as before,
pending review of this package.
