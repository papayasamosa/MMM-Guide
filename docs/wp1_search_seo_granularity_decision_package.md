# Search granularity and SEO visibility decision package (Work Package 1)

Status: decision support only. No code changes accompany this package;
no candidate approach below is enabled, selected, or implemented by it.

## Why this package exists

Work Package 0 (2026-08-24) reconciled the local PRD suite's newer
"Optional Search Granularity, Paid Search Intent and SEO Visibility"
overlay (Parts 2-11) into `docs/specification_authority.md`'s
per-part version map only — a traceability pass, not an approval or
implementation pass. That record's own text is explicit: "No
`docs/approved_requirements/` record reconciles any part of this
overlay's Search-granularity or SEO-visibility content... This map does
not itself approve, reject, or implement any requirement."

Work Package 1 completes the second half of that deferred process for
the invariants that are already implementation-ready and unambiguous:
`REQ-SEARCH-004` (governed intent taxonomy, term/query mapping,
parent-child lineage), `REQ-SEARCH-005` (multi-axis granularity
eligibility), and `REQ-SEO-001` (SEO visibility metric-definition/
observation data shape). Each of those records explicitly excludes a set
of statistical, causal, business, and threshold choices the PRD itself
leaves open in its own per-part decision registers. This package
collects those excluded items in one place, together with the PRD's own
decision-register entries that name them, so a future work package can
review and resolve them without re-deriving the same PRD passages from
scratch.

This package does not choose among any candidate below.

## The PRD's own decision registers already flag these as open

The local PRD parts, in their own numbered per-part decision registers,
already list these items as requiring separate human/statistical
approval, not as approved requirements:

- **Part 2 v1.5, §26.3, item 14 (SEO visibility approval scope):**
  "Approve the SEO visibility or ranking metric, source, interpretation,
  causal role and any estimand permitted for official reporting."
- **Part 3 v1.13, `FR-CAU-015` (Epic H):** a governed causal-role
  decision is required before any SEO effect is estimated — the
  requirement to decide is approved; the decision itself is not.
- **Part 3 v1.13, §29, item 27 (initial taxonomy):** "Approve the
  initial governed Search intent taxonomy and its ownership."
- **Part 3 v1.13, §29, item 28 (identification thresholds):** "Approve
  the minimum support, collinearity, stability and posterior-separation
  criteria for approving an intent-group's own contribution rather than
  falling back to its parent."
- **Part 3 v1.13, §29, item 29 (SEO definitions):** "Approve the SEO
  visibility/ranking metric definitions, source methodology, and
  causal-role policy."
- **Part 3 v1.13, §29, item 30 (cost allocation):** "Approve whether any
  parent-to-child Search cost allocation is ever approved; the default
  is no mechanical allocation."
- **Part 5 v1.6, §39, `DD-020` (optional Search granularity and SEO
  visibility contract):** an 11-sub-bullet register covering minimum
  grain, taxonomy ownership, cross-route comparability, unmapped-term
  handling, parent-child rules, child-cost-allocation permission, SEO
  metric/methodology/causal-role/reporting permission, and default
  non-optimisable status for SEO.
- **Part 6 v1.11, §37, `MD-008A` (optional Search granularity policy):**
  taxonomy, parent-child semantics, maximum grain, market fallback, and
  raw-term-mapping-only status.
- **Part 6 v1.11, §37, `MD-008B` (Search child economics):** whether an
  actual-only or an estimated-allocation cost treatment is ever
  permitted for a child intent group.
- **Part 6 v1.11, §37, `MD-008C` (SEO visibility effect):** metric,
  methodology, causal role, transformation, counterfactual, demand
  controls, and identification standard.
- **Part 7 v1.10, §49, `VL-032` (optional Search granularity policy):**
  minimum support, sibling correlation, fold stability, posterior
  separation, mapping coverage, hierarchy recovery, and
  aggregation-sensitivity thresholds.
- **Part 7 v1.10, §49, `VL-033` (Search child economic-grain policy):**
  allocation-method approval conditions.
- **Part 7 v1.10, §49, `VL-034` (SEO visibility-effect validation
  policy):** metric definitions, methodology checks, transformations,
  causal-role requirements, identification requirements, stability
  evidence, and permitted reporting uses.
- **Part 8 v1.6, §41, `PL-027` (optional Search intent planning/
  economics):** which parents expose child curves, reporting/scenario/
  optimisation eligibility by market, minimum evidence, the cost-
  allocation contract, and the reconciliation/fallback rule.
- **Part 8 v1.6, §41, `PL-028` (SEO visibility planning boundary):**
  reporting-only vs. sensitivity use; definition of any controllable SEO
  intervention distinct from the observed metric; units/bounds/timing/
  mechanism; cost/value contract; whether ever optimisation-eligible.
- **Part 9 v1.7, §48, `RP-030` (optional Search-intent reporting
  grain):** drill hierarchy, labels, taxonomy, grouped-fallback, and
  market disclosure.
- **Part 9 v1.7, §48, `RP-031` (child Search economics reporting):**
  compatible cost requirement, parent-only-spend markets, allocation
  method, and prohibition on undocumented allocation.
- **Part 9 v1.7, §48, `RP-032` (SEO visibility/ranking effect
  reporting):** official labels, approved metric/transformation,
  causal/uncertainty language, contextual-vs-decision rule, and cost
  contract before any SEO CPA/ROI.
- **Part 11 v1.8, §60, `API-029` (optional Search granularity and SEO
  visibility service contracts):** taxonomy schema/ownership, cross-route
  reuse policy, mapping governance, grain enum, parent-child
  reconciliation, eligibility rules, allocation-method approval, SEO
  metric-definition schema/source systems, default causal/future roles,
  minimum evidence before SEO effect reporting, connector/event/
  staleness/portability requirements, and delivery-increment placement.

These items are the PRD's own complete decision surface for the
Search-granularity/SEO-visibility overlay. Every "Out of scope" bullet in
`REQ-SEARCH-004`, `REQ-SEARCH-005`, and `REQ-SEO-001` traces to one or
more of them.

Confirmed by this reconciliation: the overlay introduces **zero hard
numeric thresholds itself** — every register item above names a
threshold *category* (minimum support, sibling correlation, mapping
coverage, and so on) without supplying a number, consistent with Part
7 v1.10 §7.1's suite-wide "no universal production threshold" principle
(thresholds are a per-artefact `Threshold policy record`, `REQ-VAL-001`).
A future decision resolving any of D3-D7 below must therefore supply
both the qualitative policy and the concrete number(s) — neither is
approved by the PRD text alone.

## Decision required

The exact decision required, once this package is reviewed, is composed
of several genuinely separable sub-decisions rather than one monolithic
choice.

### D1. SEO visibility causal role and estimand (`MD-008C`, `VL-034`, Part 2 item 14, `FR-CAU-015`)

Select and approve SEO visibility's causal role for a given use, and (if
a role implying an effect estimate is chosen) the estimand,
transformation of any non-linear ranking metric, counterfactual
definition, and demand-control set.

**Candidate D1-A — diagnostic/context only, no effect estimate.** Treat
every SEO visibility metric as `diagnostic_only` or
`observed_context_variable` (Part 6 §15.8's first two candidates)
indefinitely. Never produces an SEO "effect" figure; avoids the
identification burden entirely; forecloses `BQ-I11` (Part 2, priority
`SHOULD`) without a further decision to revisit this choice.

**Candidate D1-B — mediator/capture-efficiency state, estimand-specific.**
Approve `mediator_or_capture_efficiency_state` or
`structural_exposure_intervention` (Part 6 §15.8's other two candidates)
for a specific, named estimand only, following Part 6 §15.10's
requirement that the graph state whether visibility is upstream,
downstream, or outside the effect being estimated *per use* — i.e. the
role may be use-specific rather than global. Requires the identification
and refutation evidence Part 7 §22.7/`VL-034` demand before any resulting
effect reaches reporting.

This package does not choose between D1-A/D1-B, nor any estimand,
transformation, or demand-control set within either.

### D2. Controllable SEO intervention definition (`PL-028`, Part 6 §15.8/§15.9)

Approve whether any controllable SEO intervention exists at all, and if
so its identity, unit, feasible range, cost, timing, and operational
implementation mechanism — distinct from the observed ranking/visibility
metric itself.

**Candidate D2-A — no controllable intervention; observed metric only.**
SEO visibility remains permanently outside planning/optimisation
(consistent with Part 8's default-exclusion rule). Simplest; forecloses
any future SEO-budget scenario.

**Candidate D2-B — name a specific controllable intervention (e.g. a
content or technical SEO work-stream) with its own unit, cost, and
timing.** Enables eventual planning/optimisation eligibility per
`REQ-SEARCH-005`, but requires D1 to be resolved first (an intervention
without an approved causal role has nothing to attach an effect to), and
requires Product/Marketing to name the actual controllable activity —
not something this package can supply.

This package does not choose between D2-A/D2-B, nor name any specific
intervention.

### D3. Initial governed Search intent taxonomy content and ownership (`DD-020`, Part 3 §29 item 27)

Approve which intent groups exist, their names, hierarchy, `brand_class`
assignments, and owning function. Part 5 §17.4 supplies only
non-mandated illustrative examples ("Family Tree, Genealogy, Census/
Records, Military Records") and explicitly states it "does not mandate
those specific labels."

**Candidate D3-A — adopt an existing internal keyword/campaign taxonomy
verbatim**, if one already exists in Ancestry's paid-media tooling.
Minimises new categorisation work; risks importing a taxonomy shaped for
media-buying rather than for causal/reporting comparability.

**Candidate D3-B — design a new MMM-specific taxonomy from the PRD's
illustrative categories**, reviewed and owned by Modelling/Marketing
jointly. More work up front; better shaped for the
`cross_route_comparable_flag` requirement (Part 5 §17.4) that a
media-buying taxonomy may not satisfy.

This package does not choose between D3-A/D3-B, nor name any actual
intent group.

### D4. Search intent-group identification/promotion thresholds (`MD-008A`, `VL-032`, Part 3 §29 item 28)

Approve the concrete minimum-support, sibling-correlation,
fold-stability, posterior-separation, mapping-coverage, and
hierarchy-recovery numbers that promote an intent group from "grouped
fallback" to "separately reportable" (`REQ-SEARCH-005`'s
`contribution_eligible` axis).

**Candidate D4-A — reuse an existing repository threshold-setting
process** (e.g. the `REQ-VAL-001` per-artefact `Threshold policy record`
mechanism) to host these new Search-specific thresholds, rather than
inventing a parallel mechanism.

**Candidate D4-B — a dedicated Search-granularity threshold record**,
justified if the evidence dimensions (sibling correlation, hierarchy
recovery) prove different enough from `REQ-VAL-001`'s existing gates to
warrant their own structure.

This package does not choose between D4-A/D4-B, nor any numeric value.

### D5. Search/SEO planning-eligibility promotion criteria (`PL-027`, Part 7 §22.13)

Approve the minimum evidence that promotes `planning_eligible` from
`false` to `true` for an intent group or (pending D1/D2) an SEO object.

**Candidate D5-A — planning eligibility requires curve + economics
eligibility first**, i.e. strictly sequential promotion through the five
Part 8 §25.6 states.

**Candidate D5-B — planning eligibility may be granted independent of
economics eligibility** for a non-monetary planning use (e.g. a
volume-only scenario), if such a use is ever approved.

This package does not choose between D5-A/D5-B.

### D6. Search/SEO optimisation-eligibility promotion criteria (`PL-027`, `PL-028`, `VL-032`, `VL-033`)

Approve the (necessarily stricter) evidence bar for
`optimisation_eligible`, on top of whatever D5 approves for planning.

**Candidate D6-A — optimisation eligibility is never granted to any
Search intent group or SEO object under the current evidence
programme**, deferring this entirely to a later, separately-scoped
decision once real usage data exists.

**Candidate D6-B — define a concrete, higher evidence bar now** (e.g.
requiring the same fold-refit/structural-stability evidence class
`REQ-STAB-001`/`REQ-LEAK-001` already require for the primary model).

This package does not choose between D6-A/D6-B.

### D7. Parent-child Search cost allocation method (`MD-008B`, `VL-033`, `RP-031`, Part 3 §29 item 30)

Approve whether, and how, spend recorded only at the parent level is
ever allocated to child intent groups for `economics_eligible` reporting.
The PRD's own default is explicit and is not itself a decision this
package leaves open: "no mechanical allocation... by click share,
impression share, platform-attributed conversions or modelled
contribution" (Part 3 §29 item 30). What remains open is only the
escape hatch.

**Candidate D7-A — never allocate; parent-only economics always.** Every
child intent group's economics stay `not_applicable` unless spend is
natively tracked at child grain. Simplest; consistent with the PRD's
stated default; may permanently block `economics_eligible` for markets
that never get child-level spend tracking.

**Candidate D7-B — permit a governed `estimated`-status cost mapping**
as an explicit, separately approved exception (the PRD's own named
escape hatch), with its own uncertainty disclosure and permitted-use
policy, analogous to `core.media_costs.GovernedCostMapping`'s existing
`approval_status` gate but extended to represent an allocation rather
than a spend-to-delivery conversion.

This package does not choose between D7-A/D7-B, nor approve any specific
allocation method, weighting scheme, or Finance sign-off process for
D7-B.

## What this package does not decide

- SEO visibility's causal role, estimand, or any transformation (D1).
- Whether any controllable SEO intervention exists, or its definition
  (D2).
- The content of the governed Search intent taxonomy, or its ownership
  (D3).
- Any numeric identification/promotion threshold for Search
  granularity, planning, or optimisation eligibility (D4, D5, D6).
- Any parent-to-child Search cost-allocation method (D7).
- Whether this capability is scheduled ahead of, or behind, any other
  open work-package item in the governing brief — this package only
  supplies the missing decision-support document.
- Any `core`, `application`, or `pages` code change — none accompanies
  this package. `core.search_objects`/`core.activities` continue to have
  no taxonomy, mapping, granularity-capability, or SEO-visibility
  representation, exactly as before.

## Owner and status

**Owner:** Modelling (identification thresholds, taxonomy design),
Product/Marketing (taxonomy content and ownership, SEO metric/
methodology, controllable-intervention definition), Finance (any
cost-allocation sign-off under D7-B).

**Status:** Decision-support package only. `REQ-SEARCH-004`,
`REQ-SEARCH-005`, and `REQ-SEO-001` remain target-state contracts with
zero implementation, pending review of this package.

## Update, 2026-08-30: D1, D2, and D3 resolved by business-decision brief

The business-decision brief "Post-UI/UX Implementation Instructions:
Approved Business Decisions" (decision date 2026-08-29) resolves three
of this package's seven sub-decisions. This update records the
resolutions without rewriting the original analysis above, which remains
valid as a record of what was open before this brief.

- **D1 (SEO visibility causal role and estimand): resolved in favour of
  D1-B.** Decision 6 ("SEO is a marketing activity with a causal
  contribution") approves a real, non-diagnostic causal role — SEO work
  -> better ranking/visibility -> more organic traffic ->
  more sign-ups/sales — rather than D1-A's permanent diagnostic-only
  treatment. The role is estimand-specific per use, per Part 6 §15.10, as
  D1-B's own candidate text requires. See `REQ-SEO-001`'s 2026-08-30
  addendum for the contract-level resolution. **Still open within D1:**
  the specific estimand, transformation of the (non-linear) positional
  metric, counterfactual definition, and demand-control set for any given
  use — these require the identification/refutation evidence Part 7
  §22.7/`VL-034` demands and are Phase B/C implementation work, not
  resolved by this brief.
- **D2 (controllable SEO intervention): resolved in favour of D2-A.**
  Decision 7 ("SEO should not have spend-based ROI") and Decision 6's
  "non-paid marketing activity" framing confirm no controllable,
  spend-based SEO intervention is approved — SEO visibility remains
  permanently outside planning/optimisation via the observed-metric-only
  path, consistent with Part 8's default-exclusion rule. This forecloses
  D2-B unless a future, separately-scoped decision names an actual
  controllable content/technical-SEO work-stream with its own unit,
  cost, and timing.
- **D3 (initial governed Search intent taxonomy content and ownership):
  resolved in favour of D3-B.** Decision 2 ("Minimum Paid Search detail")
  names Brand/Non-Brand as the two top-level governed intent groups. See
  `REQ-SEARCH-004`'s 2026-08-30 addendum for the full contract-level
  resolution, including the orthogonal platform (Google/Bing) axis and
  the reporting roll-up hierarchy.

**D4, D5, D6, and D7 remain open**, exactly as originally recorded above.
Decision 2 supplies D4's *gating principle* (evidence-based promotion,
no invented threshold) without a concrete number, which is not a
resolution of D4 itself — the numeric thresholds still require the
evidence-gathering work D4 always anticipated.
