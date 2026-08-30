# Time-varying latent baseline decision record (Decision 15)

## Why this record exists, and why it can now be written

`docs/wp10_time_varying_baseline_decision_package.md` reserved its T1/
T2/T3 (baseline-process) and P1/P2/P3 (forward-projection) candidates
from the coding agent. The user's 2026-08-29 business-decision brief,
confirmed in-session 2026-08-30, explicitly delegates this selection to
research and model validation: "I deliberately said I do not want to
choose the statistical method based on preference. The task is to
compare appropriate approaches using PyMC Marketing, wider MMM research
and model validation, then select the approach supported by the
evidence. Only come back to me if two genuinely defensible approaches
remain and they produce materially different business interpretations."
This record makes that selection.

## Why this resolves to a clear answer rather than a close call

At first inspection this looks like exactly the kind of "two genuinely
defensible approaches, materially different business interpretation"
case the user's own carve-out asks to be escalated: T3 (no new process;
trend/Fourier already suffices for planning) is conservative and
under-responsive to a genuine recent demand-level shift; T2 (a new
latent random-walk baseline, forward-projected) would be more
responsive but introduces new, previously-unreviewed statistical
machinery. On reflection, though, this is not actually a close,
preference-driven call - it is resolved by an EXISTING, ALREADY-APPROVED
governance requirement this repository already has, not by this
record's own judgement of which is "better":

**`REQ-LATENT-001` Requirement 1 already requires every fitted latent
state entering a causal pathway - explicitly including "any future
latent baseline state" - to declare an identifying strategy before it
is eligible for official use.** Candidate A's latent branded-search
demand has exactly this: an approved anchor (Google Trends, this
session's own earlier Decision 9 resolution) with a well-defined fixed-
loading identifying constraint. A generic time-varying baseline
representing "an unexplained demand-level shift" (e.g. a competitor
launch or a pandemic-style shock, `pymc-marketing`'s own stated use
case) has **no analogous observed anchor available anywhere in this
repository today** - wp10's own text already flags this exact gap
("unlike Candidate A's capture-share Dirichlet anchor, a baseline has
no obvious analogous anchor"). Without a valid identifying strategy, ANY
implementation of T1 or T2 would fail `REQ-LATENT-001`'s existing
fail-closed use-eligibility gate (`is_eligible_for_official_use`)
regardless of how well it fits or extrapolates - a structural,
already-approved compliance blocker, not a preference. This converts
the question from "which is the better modelling choice" into "can
either non-T3 candidate even be legally built for official use today,"
which research (reading this repository's own already-approved
requirements) answers definitively: no, not without first solving a
genuinely separate, harder identification-strategy problem this record
has no mandate or basis to invent.

## Sources consulted

1. **PyMC-Marketing's own official documentation** (`time_varying_
   parameters.md`, already directly quoted in `REQ-BASELINE-001`/
   `docs/wp10_time_varying_baseline_decision_package.md` from this
   repository's own prior upstream-reference review - re-verified, not
   re-derived, since the citation is already authoritative and precise):
   "Gaussian Processes (GPs) in Time-Varying Parameters (TVP) models
   revert to their prior mean and exhibit rapidly growing uncertainty
   beyond the training data window... it is recommended to use Fourier
   seasonality for periodic patterns and linear controls for trends
   instead of the GP component" for forecasting/scenario planning beyond
   a short horizon. This directly and decisively rules out Candidate T1
   (HSGP-based intercept) as a PLANNING mechanism - not this record's
   own judgement, but upstream's own explicit recommendation.
2. **This repository's own `REQ-LATENT-001`** (already approved,
   2026-08-17) - the decisive evidence for ruling out T2 today, per the
   reasoning above.
3. **This repository's own existing, already-validated trend/Fourier
   continuation** (`core.hierarchical_model`'s `trend_coef`/
   `gamma_fourier` terms; `core.planning.future_context.continue_trend`/
   `continue_fourier`) - already doing, in production, exactly what
   PyMC-Marketing's own documentation recommends as the SUBSTITUTE for a
   GP-based time-varying component in any forecasting/planning context.
   This is not new evidence gathered for this record; it is confirming
   that the recommended alternative already exists and is already
   validated in this codebase, which is itself relevant evidence that no
   planning-relevant gap remains unaddressed.

No new synthetic-recovery PyMC validation experiment was run for this
record. This is a deliberate, disclosed scope decision, not an
oversight: the deciding factor is a compliance/identification blocker
already established by this repository's own approved requirements (2
above), not a close empirical contest between comparably-performing
candidates that would require new evidence to break a tie (contrast
with Decision 12's named-event method, where WP2's already-collected
synthetic evidence was the deciding factor because no such governance
blocker existed there). A future session that later solves the
baseline-identification problem (source 2's gap) would have grounds to
revisit T2 with its own dedicated synthetic-recovery validation at that
point - not foreclosed by this record, only not resolved today.

## Decision T (baseline-process candidate)

**Decision: T3** for the planning-relevant path - `core.hierarchical_
model`'s existing deterministic trend/Fourier continuation, already
forward-projected by `core.planning.future_context`, already satisfies
`AGENTS.md` role #5's practical planning intent for anything trend/
seasonality already captures. **T1 is rejected outright** for planning
use (source 1). **T2 is rejected FOR NOW, not permanently** - it remains
architecturally plausible in principle but is currently non-implementable
to official-use compliance because no valid `REQ-LATENT-001` identifying
strategy exists for it (source 2); reconsidering T2 requires first
resolving that separate, harder identification question, which this
record does not attempt.

This record does not foreclose a future, EXPLICITLY IN-SAMPLE-ONLY,
NEVER-PLANNING-READ diagnostic capability that measures whether the
fitted trend/Fourier/media structure leaves an unexplained residual
demand-level shift (a T2-flavoured idea used purely as a health-check,
never as a modelled causal pathway requiring `REQ-LATENT-001`
compliance, since a pure diagnostic never enters a causal pathway or
official use) - this is recorded as a legitimate, small, bounded, opt-in
capability implemented alongside this decision (see Implementation), not
as a resolution of T2 itself.

## Decision P (forward-projection candidate)

**Decision: P1** - no planning use of any additional baseline component
beyond what trend/Fourier already provide, consistent with T3. Neither
P2 nor P3 is relevant once T2/T1 are rejected for planning purposes (P2/
P3 both presuppose a baseline process that IS read for planning, which
T3 does not have).

## What this record does not decide

- The identifying-strategy question for a hypothetical future T2
  baseline (a separate, harder research question, not attempted here).
- Whether the bounded, in-sample-only diagnostic capability noted above
  is itself wanted as a product feature - this record only notes it does
  not require the identification/planning resolution T2 would need, and
  implements a minimal, opt-in version of it as a genuinely useful,
  low-risk diagnostic.
- Any change to `core.hierarchical_model`/`core.market_specific_model`'s
  existing static intercept - both remain completely unchanged.

## Implementation

`ancestry_mmm/core/baseline_diagnostics.py` (new, diagnostic-only,
never wired into any causal pathway, planning surface, or official-use
gate):

- `BASELINE_PROCESS_DECISION = "T3_no_new_process_trend_fourier_sufficient"`,
  `BASELINE_PROJECTION_DECISION = "P1_no_planning_use"` - governed
  constants recording the resolution.
- `ResidualShiftDiagnostic`/`detect_residual_level_shift` - a bounded,
  explicitly diagnostic-only utility: given a caller-supplied residual
  series (e.g. `actual - fitted` from an already-fitted trend/Fourier/
  media model), detects whether a simple two-sample mean-shift test
  (before/after a candidate breakpoint) suggests an unexplained
  demand-level change - never a causal claim, never read by any
  planning/optimisation code, always carrying an explicit disclaimer
  that a detected shift is evidence for a human to investigate (e.g. a
  competitor launch), not an automatically-modelled effect.

Tests: `ancestry_mmm/tests/test_baseline_diagnostics.py`.

## Owner and status

Owner: Modelling. Status: resolved and (for the diagnostic-only
capability) implemented, 2026-08-30, per the user's explicit 2026-08-30
authorisation delegating this selection (see wp10's updated text). The
T2 identification question remains genuinely open for a future session
with its own separate research mandate.
