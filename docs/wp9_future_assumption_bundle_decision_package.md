# Future-assumption bundle decision package (Work Package 9)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Decision required

`docs/specification_authority.md` already lists "Future-assumption
bundles" as "No approved requirement/decision yet" and, separately,
`REQ-FORECAST-001` names "Work Package 9's broader 'governed future
assumptions' scope" without authorising it. `REQ-FUTURE-001` (this work
package) reconciles that gap into a formal target-state requirement
record but does not resolve it. This package is the missing decision-
support document.

The exact decision required after this package is reviewed is:

> Select and approve one production design for a governed future-
> assumption bundle (or explicitly reject all candidates below and
> request another package), covering: what a bundle is as a data
> structure and how it relates to `core.planning.future_context`'s
> existing per-control contract; how forecast materiality is quantified
> or graded, and when forecast-consequence review becomes blocking
> (`VL-027`/`RP-024`); and whether, and how, an external forecasting
> method (Chronos-2 or another) may supply a bundle's future path for an
> exogenous control or cost/translation assumption.

This is intentionally not chosen by the coding agent. No future-
assumption-bundle module exists; `core.planning.future_context` continues
to serve one plan window's controls and promotions exactly as it already
does, with no bundle-level object wrapping it, pending review of this
package.

## Why this is a modelling and governance question, not an engineering one

`core.planning.future_context.build_future_context` (`REQ-SCEN-002`)
already implements a careful, fail-closed per-control contract: official
mode requires an explicit future value for every required period;
exploratory mode may opt a specific, eligible control into
`hold_last_observed`, and `FutureContextResult.is_decision_ready` is
`False` whenever any control did. This is deliberately narrow — one
scenario/plan window, one market, the controls and promotions that
window's model needs. It does not decide, and was never asked to decide
(`ancestry_mmm/core/planning/future_context.py`'s own module docstring:
"Deliberately out of scope... Chronos-2 or any other external
forecaster"), three separate open questions that only surface once
multiple future-role assignments, potential forecast provenance, and
downstream consequence evidence must be reasoned about *together*:

1. **What identity does a bundle have, and what does it wrap?**
   `FutureContextResult` already has a `fingerprint()`. A "bundle" could
   be nothing more than a name for one `FutureContextResult` plus its
   provenance, or a genuinely new object spanning several (e.g. one per
   market, or one covering a full multi-scenario comparison). This is
   not a modelling question in isolation, but it is entangled with
   question 3 below (where forecast-consequence evidence attaches),
   which is.
2. **Materiality.** `REQ-FORECAST-001` item 1 already states "the system
   must not assume a high-error forecast is automatically decision-
   material, nor that a statistically accurate forecast is low-risk" —
   but supplies no method for turning forecast uncertainty and model
   sensitivity into a graded materiality judgement, or a threshold for
   when review becomes blocking rather than advisory. This is a
   statistical/business judgement (how much predicted-outcome change is
   "material" to a decision), not a code gap.
3. **External-forecaster integration.** `AGENTS.md`'s future-variable-
   role #2 permits Chronos-2 "or another method" for exogenous controls
   and cost/translation series — a permission, not a selection. Which
   method (if any) is approved for production, and what provenance
   disclosure a bundle must carry when a control's future path came from
   one, is an unresolved governance choice, not an engineering one:
   `build_future_context`'s `explicit_future` parameter already accepts
   any caller-supplied series today, forecast-derived or not, so no code
   change is required merely to plumb a number through — the open
   question is which method is trusted enough to produce that number
   for official use, and how that trust is disclosed and audited.

## Candidate approaches to the bundle schema

### Candidate B1 - Thin named wrapper around existing `FutureContextResult`s

A bundle is a new, small dataclass holding a name, a version, and a
mapping of market (or market+outcome) to the `FutureContextResult`
already built for it, with a bundle-level `is_decision_ready` computed as
the logical AND of every wrapped result's own property. Minimal new
surface area; reuses `core.planning.future_context` entirely unchanged.
Tradeoff: does not by itself solve where `REQ-FORECAST-001` consequence
evidence attaches (question 3's identity sub-problem) — that would need
its own follow-on decision about whether evidence keys off the bundle,
the wrapped result's fingerprint, or a control name within it.

### Candidate B2 - Extend `FutureContextResult` itself with a bundle identity field

Add bundle name/version fields directly onto `FutureContextResult` rather
than wrapping it. Fewer new types; but couples a single-market/single-
window build function's return type to a cross-window bundling concept
it was never designed to know about, and every existing caller
(`core.sequential_scenario_evaluation`, `pages/08_Scenario_Planner.py`)
would need to supply bundle identity even when no genuine multi-context
bundle is in play - the "None decision-required" pattern
`FutureControlAssumption` already uses would need to grow a bundle-scoped
counterpart. Statistically identical intent to B1; structurally more
invasive for a narrower benefit.

### Candidate B3 - A separate registry keyed by fingerprint, no wrapper object at all

Rather than a bundle object, maintain a governed registry mapping a
`FutureContextResult.fingerprint()` (and, once implemented,
`REQ-FORECAST-001` consequence-evidence records) to a human-readable
name and approval status - closer to how `core.causal_graph`/`core.
experiments` already separate an object's own identity from a registry
of its approved uses. Avoids inventing a new wrapper type; raises its
own sub-question of where such a registry would live and whether it
needs its own persistence/export contract (`core.persistence`), not
addressed by this package.

## Candidate approaches to materiality quantification and grading

### Candidate M1 - Effect-size threshold on the already-approved consequence axis

Once `REQ-FORECAST-001`'s consequence-assessment method (posterior
scenario replay, local sensitivity, or counterfactual replay) produces a
distribution of plausible outcome changes, grade materiality by a fixed
or configurable effect-size threshold (e.g. a percentage change in
predicted incremental outcome or a decision-ranking flip). Simplest to
reason about; requires approving a specific threshold and its business
justification - an explicit business/statistical judgement call this
package does not make, and risks the same "one frozen number" brittleness
`AGENTS.md` cautions against elsewhere in this repository (e.g. "do not
prescribe one exact probability distribution... beyond what an approved
model specification requires").

### Candidate M2 - Decision-ranking-change detection (no absolute threshold)

Grade materiality by whether plausible alternative forecast paths change
which scenario/plan is recommended (a ranking flip) rather than by any
absolute effect-size number - closer to `REQ-FORECAST-001` item 4's own
"whether recommendation status changes as a result" language. Avoids
picking one arbitrary threshold; requires the consequence-assessment
method to be run against every candidate under comparison, not just one,
which may not always be available (e.g. a single scenario evaluated in
isolation, with no comparison set).

### Candidate M3 - Disclosed, ungraded consequence evidence only (no materiality score)

Report the two-axis evidence `REQ-FORECAST-001` already requires (forecast
accuracy; downstream consequence magnitude and uncertainty) without ever
reducing it to a single materiality grade or blocking/non-blocking
verdict - consistent with this program's own established pattern
(`core.calibration_comparison`'s explicit ban on a verdict/recommendation
field, `REQ-CALIB-001` Requirement 3) of presenting evidence rather than a
fabricated judgement. Cheapest and most consistent with precedent;
defers `VL-027`/`RP-024`'s own "when does this become blocking" question
entirely to human review every time, which may not satisfy the PRD's
intent that *some* threshold eventually gates official use.

## Candidate approaches to external-forecaster integration

### Candidate F1 - No production integration; explicit-future-path only

Do not integrate Chronos-2 or any other external forecaster now. A
bundle's future path for any control remains either an explicit,
analyst-supplied series or an exploratory `hold_last_observed`
assumption, exactly as `core.planning.future_context` already supports
unchanged. Zero new dependency, zero new risk surface; leaves
`AGENTS.md`'s permitted-but-unselected Chronos-2 option unused
indefinitely, and does not progress the PRD's own named forecasting
integration (`FCH-09`).

### Candidate F2 - Chronos-2 integration behind an explicit, disclosed provenance flag

Integrate Chronos-2 (or another approved method) as one more way to
produce the same `explicit_future` series `build_future_context` already
accepts, with every bundle recording which controls' future paths were
forecaster-derived versus analyst-supplied versus held-last-observed -
three visible provenance states instead of today's two
(`EXPLICIT_ASSUMPTION`/`HOLD_LAST_OBSERVED_ASSUMPTION`). Directly answers
the PRD's forecasting intent; introduces a new dependency (subject to
this repository's PyMC Labs/upstream-reference policy and `AGENTS.md`'s
role rules 1 and 3: only for exogenous controls and cost/translation
series, never an endogenous mediator or latent baseline) and requires its
own backtest-accuracy/benchmark-comparison contract
(`REQ-FORECAST-001` item 1) before any forecaster output could be trusted
for official use - not a mechanical library call.

### Candidate F3 - Method-agnostic forecaster interface, Chronos-2 as one registered implementation

Define a governed forecaster-interface contract (input: historical
series and horizon; output: a point/interval forecast plus a required
backtest-accuracy summary) that any approved method, including but not
limited to Chronos-2, can implement and register against - similar in
spirit to how `core.frequency_conversion.ensure_approved_frequency_
methods` registers a narrow, explicit catalogue of approved methods
rather than hard-coding one. Most extensible; the largest new surface
area of the three, and still requires the same backtest/provenance
decisions as F2 before any registered method's output is trustworthy.

## What this package does not decide

- Which bundle schema (B1/B2/B3) is approved.
- Which materiality-grading approach (M1/M2/M3), or combination, is
  approved, or any specific threshold M1 or M2 would need.
- Whether Chronos-2 or any other external forecaster is approved for
  production use, under which of F1/F2/F3, or what backtest-accuracy
  evidence a forecaster would need to produce before its output is
  trusted.
- Any specific persistence (`core.persistence`), UI (`pages/08_Scenario_
  Planner.py`), or diagnostics-page wiring for a bundle, beyond noting
  where it would eventually attach.
- Whether resolving this gap is scheduled ahead of or behind any other
  open work-package item — this package only supplies the missing
  decision-support document; it does not reprioritise the program.

## Owner and status

**Owner:** Data Science / Platform engineering (bundle schema, forecaster
integration), Modelling (materiality grading, forecast-consequence
review policy).

**Status:** Decision-support package only. `core.planning.future_context`
continues to serve one plan window's per-control contract exactly as
before, with no bundle-level object, pending review of this package.


## Update, 2026-08-30: bundle-schema, materiality, and forecaster-integration selection delegated by later approved instructions; resolved

The user's "Post-UI/UX Implementation Instructions: Approved Business
Decisions" brief (2026-08-29), a later human instruction, explicitly
established a source-of-truth order placing the brief's own approved
decisions and instructions above an older decision package such as this
one, and explicitly authorised (2026-08-30, in-session confirmation)
proceeding on this package's B1-B3/M1-M3/F1-F3 candidates: "The
business semantics are in the instructions. Users should provide things
they actually control, especially planned activity and promotions,
while demand, seasonality and similar model-derived assumptions should
come from governed system/model forecasts rather than manual guesses.
The exact internal bundle/module architecture is an implementation
choice. Reconcile it with the work already in the repo and document the
resulting contract." This supersedes this package's original "not
chosen by the coding agent" reservation.

The resulting resolution - B1 (a thin named wrapper around existing
`FutureContextResult`s, reusing `core.planning.future_context`
unchanged), M3 (disclosed, ungraded consequence evidence only, no
verdict field, matching this program's own already-established
`REQ-CALIB-001` precedent), and F1 (no production external-forecaster
integration now, since the demand/seasonality "model-derived forecast"
need is already satisfied by the existing trend/Fourier continuation,
and Chronos-2/F2/F3 both require a substantial separate backtest-
validation workstream this record's narrower scope should not rush) -
is recorded in full, with every rejected alternative, in
`docs/future_assumption_bundle_architecture_decision_record.md`. This
package's original text above is preserved as history and remains an
accurate record of the state of the decision before 2026-08-30 - it is
not rewritten, only superseded for the specific choices this update
describes.
