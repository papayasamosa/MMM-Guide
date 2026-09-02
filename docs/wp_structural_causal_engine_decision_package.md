# Structural causal engine decision package (Work Package 0 structural-causal authority reconciliation)

Status: decision support only. No code changes accompany this package; no
candidate approach below is enabled, selected, or implemented by it.

> **Work Package 4 (2026-08-19) follow-up:** the capability-matrix
> evaluation named by candidate D1-A below has now been performed and is
> recorded in
> `docs/wp4_structural_causal_engine_capability_evaluation.md` (current
> upstream evidence for PathMC, DoWhy, pgmpy, and the
> no-supplemental-engine baseline, classified per `AGENTS.md`'s six-way
> vocabulary). It supplies evidence only; it still does not decide D1,
> D2, or D3, and no engine is adopted by it.

## Why this package exists

Work Package 0's reconciliation of the local PRD suite's newer structural-
causal revisions (Part 3 v1.10, Part 4 v1.6 Final, Part 6 v1.8, Part 7
v1.7, Part 8 v1.5, Part 9 v1.6 Final, Part 10 v1.8 Final, Part 11 v1.7
Final) against repository authority produced five new records —
`REQ-ENGINE-001`, `REQ-SCENGINE-001`, `REQ-SCEFFECT-001`,
`REQ-CAUSALROBUST-001`, `REQ-SCCURVE-001`. Of these, `REQ-ENGINE-001` is
**not** a decision-support gap: Part 3 v1.10 explicitly resolves the
primary-production-engine question ("PyMC is the approved primary
production MMM engine... This is now a resolved production-architecture
decision... and must not remain represented as `decision_required`"), and
`REQ-ENGINE-001` simply reconciles that already-made decision into
repository authority. It is listed here only for cross-reference, not as
an open item.

The other four records each approve an engine-independent *invariant* for
the still-unresolved **supplemental** structural-causal adapter capability
while explicitly excluding a set of statistical, causal, business, and UX
choices the PRD itself leaves open. This package collects those excluded
items in one place, together with the PRD's own decision-register entries
that name them, so a future work package can review and resolve them
without re-deriving the same PRD passages from scratch.

This package does not choose among any candidate below. The governing
task-specific implementation brief's (§10.5) explicit "do not approve
from PRD prose" list —
PathMC as mandatory engine; exact structural-model DSL; exact mediation
engine formulation; exact DAG-falsification test; exact placebo/
permutation method; exact unmeasured-confounding sensitivity method;
thresholds; causal-proof-implying labels; isolated runtime topology where
not required; planning eligibility for structural curves; a replacement
for Candidate A; a replacement for sequential planning — is the authority
this package operationalises into concrete, PRD-cited decision items.

## The PRD's own decision registers already flag these as open

The local PRD parts, in their own numbered per-part decision registers,
already list these items as requiring separate human/statistical
approval, not as approved requirements:

- **Part 6 v1.8, §37, `MD-022` (structural causal adapter boundary):**
  "Approve the initial structural causal adapter implementation and
  eligibility matrix, including: which observed-variable mediation and
  causal-query classes are eligible; which likelihood, hierarchy,
  transformation and temporal structures are supported; which diagnostics
  may be used for official validation; the runtime-isolation approach
  where dependencies conflict; the requirement that engine-specific
  specifications remain generated from the approved causal graph; the
  fallback status when a requested structure is unsupported. PathMC is
  the current candidate implementation, but approval should attach to the
  verified capability and adapter contract rather than to the library
  name alone."
- **Part 7 v1.7, §48, `VL-028` (structural causal robustness policy):**
  "Approve which estimands and approval levels require empirical DAG
  falsification, placebo or permutation refutation, negative controls and
  unmeasured-confounding sensitivity; define interpretation, materiality
  and blocking consequences without collapsing them into one causal
  score."
- **Part 7 v1.7, §48, `VL-029` (structural causal engine validation):**
  "Approve the eligible structural causal model classes and causal-query
  types, graph-to-model equivalence requirements, recovery tolerances,
  engine/runtime provenance rules, isolated-runtime revalidation
  requirements and fallback status when the structural adapter is
  unsupported."
- **Part 10 v1.8, §47, `UX-031` (causal-robustness evidence
  presentation):** "Approve the technical and business labels, default
  summaries and drill-down patterns for: empirical graph challenge or DAG
  falsification; placebo or permutation refutation; unmeasured-
  confounding sensitivity; graph-to-model fidelity; structural
  intervention recovery. The design must preserve the distinction between
  supporting evidence and proof of causality."
- **Part 10 v1.8, §47, `UX-032` (structural causal engine visibility):**
  "Approve where engine and runtime details appear... no top-level
  navigation, workflow or product concept is named after the
  implementation library."
- **Part 10 v1.8, §47, `UX-033` (structural intervention planning
  eligibility):** "Approve the labels and warning pattern used when a
  structural intervention effect or curve is reportable but not eligible
  for sequential planning or optimisation."

These six items (`MD-022`, `VL-028`, `VL-029`, `UX-031`, `UX-032`,
`UX-033`) are the PRD's own complete decision surface for the structural-
causal overlay. Every "Explicitly excluded" bullet in `REQ-SCENGINE-001`,
`REQ-SCEFFECT-001`, `REQ-CAUSALROBUST-001`, and `REQ-SCCURVE-001` traces
to one of these six.

## Decision required

The exact decision required, once this package is reviewed, is composed
of several genuinely separable sub-decisions rather than one monolithic
choice:

### D1. Engine selection and eligibility matrix (`MD-022`)

Select and approve (or explicitly decline to select, and instead approve
a process for selecting) a concrete structural causal engine, or
determine that none is currently justified. If one is selected, approve:
which observed-variable mediation/causal-query classes it will be used
for; which likelihood/hierarchy/transformation/temporal-structure
combinations it must support to be usable at all for Ancestry's model
forms; which of its diagnostics may be used for official validation
evidence versus which remain informational only; and the explicit
fallback status (`unsupported`, `exploratory`, or remains on the primary
MMM path) when a requested structure exceeds engine capability.

**Candidate D1-A — PathMC as the evaluated candidate, no commitment
yet.** Treat PathMC as the PRD's own named candidate and run the
Work-Package-4-style capability-matrix evaluation (current upstream
documentation, supported likelihoods, temporal/hierarchical/mediation
semantics, dependency/runtime cost, licence) before any adoption
decision. Consistent with the PRD's own framing ("PathMC is the current
candidate implementation... approval should attach to the verified
capability and adapter contract rather than to the library name alone").
Requires the capability-matrix work itself, which is out of scope for a
documentation-only work package.

**Candidate D1-B — defer engine evaluation entirely until a concrete
Ancestry use case needs it.** Do not evaluate any engine now; wait for a
specific structural-mediation use case (beyond what Candidate A already
covers) to be proposed, and only then run the D1-A evaluation against
that concrete need. Avoids speculative evaluation cost; risks re-deriving
the same PRD requirements later without a driving use case to bound scope.

**Candidate D1-C — decline the structural-causal engine capability
altogether for the foreseeable roadmap.** Conclude that Candidate A plus
the existing graph-model-compiler's supported edge roles already cover
Ancestry's actual mediation needs, and that a second engine adds
dependency/runtime risk without a demonstrated gap. Requires an explicit
gap analysis against real upcoming use cases (e.g. a second capacity-
constrained pathway, DNA halo mediation) to justify, which this package
does not perform.

This package does not choose among D1-A/D1-B/D1-C.

### D2. Causal robustness policy (`VL-028`, `VL-029`)

Approve which estimands/approval levels require DAG falsification,
placebo/permutation refutation, negative controls, and unmeasured-
confounding sensitivity; define interpretation, materiality, and blocking
consequences for each, without collapsing them into one causal score
(`REQ-CAUSALROBUST-001` §1 already forbids the collapse; this decision is
about what threshold or requirement applies, not whether they stay
separate). Also approve the specific method for each: which
falsification-test statistic, which permutation/placebo construction, and
which confounding-sensitivity method (e.g. Rosenbaum-bounds-style,
E-value-style, or another approach) — `REQ-CAUSALROBUST-001` deliberately
approves none of these.

**Candidate D2-A — no blocking threshold; evidence-only disclosure.**
Compute and disclose all applicable robustness evidence for every
structural effect, with no automatic pass/fail gate — human review
decides materiality case by case, consistent with `REQ-CAP-001`'s and
`REQ-CALIB-001`'s established "disclose evidence, no invented verdict"
precedent in this repository. Simplest to implement once an engine
exists; provides no automatic protection against a genuinely non-credible
structural effect reaching a report.

**Candidate D2-B — approval-level-gated thresholds.** Define specific
estimand/approval-level combinations (e.g. "official curve publication
requires a non-rejected DAG falsification test and a documented
confounding-sensitivity bound") with concrete, approved thresholds.
Provides an automatic gate; requires committing to specific statistical
thresholds this package explicitly declines to invent, and risks a false
sense of certainty if the threshold is chosen without adequate
methodological review.

This package does not choose between D2-A/D2-B, nor any specific method
or threshold within either.

### D3. UX presentation for causal-robustness and engine visibility (`UX-031`, `UX-032`, `UX-033`)

Approve: the technical and business labels, default summaries, and
drill-down patterns for the three robustness evidence dimensions plus
graph-to-model fidelity and structural-intervention recovery (`UX-031`);
where engine/runtime technical detail is shown, consistent with "no
top-level navigation, workflow, or product concept named after the
implementation library" (`UX-032`); and the labels/warning pattern for a
reportable-but-planning-ineligible structural intervention curve
(`UX-033`).

This is a UX/design decision dependent on D1 and D2 above (there is
nothing concrete to label until an engine and a robustness policy exist),
so it is listed here for completeness but is not independently
actionable before D1/D2.

## What this package does not decide

- Whether PathMC, another named library, or no structural causal engine
  is adopted (D1).
- Any causal-robustness method, threshold, or blocking policy (D2).
- Any UX label, summary, or warning-pattern wording (D3).
- Whether the structural-causal engine capability is scheduled ahead of,
  or behind, any other open work-package item in the governing brief —
  this package only supplies the missing decision-support document.
- Any `core`, `application`, or `pages` code change — none accompanies
  this package. `core.graph_model_compiler` continues to reject every
  edge role beyond `direct`/`cross_product_halo`/`excluded_diagnostic_
  only`/Candidate A's authorised `mediated`/`capacity_constrained`
  structure, exactly as before.

## Owner and status

**Owner:** Modelling (engine capability matrix, causal-robustness
methods), Product (planning-eligibility labels, engine-visibility UX).

**Status:** Decision-support package only. `REQ-SCENGINE-001`,
`REQ-SCEFFECT-001`, `REQ-CAUSALROBUST-001`, and `REQ-SCCURVE-001` remain
target-state contracts with zero implementation, pending review of this
package.

## Update, 2026-08-30: D1 resolved as D1-B (deferred, not rejected)

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (Decision 19, "Defer PathMC") resolves D1.
Candidate D1-A's capability-matrix evaluation was already performed
(Work Package 4, `docs/wp4_structural_causal_engine_capability_
evaluation.md`, 2026-08-19) — PathMC 0.3.0, DoWhy 0.14, and pgmpy 1.1.2
were classified against the approved six-way capability vocabulary, with
no engine selected and no dependency added. This decision now resolves
the *post-evaluation posture* as **D1-B**: defer any engine adoption or
selection until a concrete Ancestry use case beyond what Candidate A
already covers is proposed — explicitly not D1-C (PathMC is not declined
permanently; the brief's own words are "mark it as deferred rather than
rejected forever"). PyMC/PyMC Marketing remains the sole production
modelling path, per `REQ-ENGINE-001`, unaffected by this update.

The brief's stated sequence for revisiting this decision: only after (1)
the core MMM, (2) Scenario Planner, and (3) Optimiser are fully working,
plus the validation/governance/reporting needed for those, should PathMC
be reconsidered. This is a business-priority ordering, not a technical
finding, and is recorded here as the condition under which D1 would be
reopened.

Confirmed (repository audit, 2026-08-30): no PathMC package appears in
`pyproject.toml`, any lockfile, or `requirements*.txt` — no new runtime
dependency has been, or is approved to be, added by this decision. No
PathMC UI work is approved. D2 (causal robustness policy) and D3 (UX
labels) remain fully open, unaffected by this update.
