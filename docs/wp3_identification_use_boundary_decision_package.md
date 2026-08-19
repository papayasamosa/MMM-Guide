# WP3 Decision Package: Identification and Latent-State Use-Boundary

Work Package 3 of `Media-Mix-Lab: Coding LLM Next Steps After PR #291`
(2026-08-19). Companion to `REQ-IDENT-001` and `REQ-LATENT-001`
(`docs/approved_requirements/`). This package records the mechanical
determination of what could be wired at the official-use boundary, the
unresolved decisions that block the rest, and the candidate integration
points for when those decisions land. **No candidate in this package is
selected.**

## 1. The question WP3 was asked to close

`REQ-IDENT-001` Requirement 5: "Official model compilation must fail when a
requested adjustment-based estimand uses a conditioning set incompatible
with the approved graph and no approved alternative identification strategy
exists - extending `core.graph_model_compiler`'s existing blocking-error
contract (`REQ-GRAPH-001` §7)."

`REQ-LATENT-001` Requirement 3: "The model compiler must reject a latent
structure that remains invariant under an arbitrary rescaling or sign
reversal that could be offset by another free parameter ... a fitted latent
mediator or latent demand state with no valid scale-identification strategy
is a compiler-level blocking error, not a warning."

## 2. Mechanical determination (verified against the current code)

### 2.1 The compiler has no adjustment-set surface

`core.graph_model_compiler.GraphModelCompiler.compile(self, graph:
CausalGraph)` accepts a graph and returns structural compilation
(`GraphCompilationPlan`, `ResolvedPathwayMasks`,
`causal_graph_structural_fingerprint`, optional
`SearchCandidateAGraphPlan`). No official artefact anywhere requests an
adjustment-based estimand *with a conditioning set* at compile or use time:

- `core.estimand_identification.assess_backdoor_identification` is consumed
  only by `application.diagnostics_service` (the Diagnostics evidence
  section). It is never an input to compilation, fitting, approval,
  curves, planning, or optimisation.
- Therefore there is currently **no mechanical surface** on which
  Requirement 5's blocking error could fire: compilation never receives a
  conditioning set to reject.

Requirement 5 cannot be wired without first deciding *which official
requests carry an adjustment-based estimand* - i.e. VL-026's "when graph
checks are required versus optional", explicitly decision-required and
excluded from the record's approval. That decision does not exist.

### 2.2 The only fitted latent state is Candidate A, whose anchor is unresolved

The only fitted latent causal state in production is Candidate A's
`latent_branded_search_demand` (`core.search_capacity`,
`REQ-SEARCH-002`). Its scale/location identifying anchor is `MD-021`
(Part 6 §37), explicitly decision-required and excluded from both
`REQ-LATENT-001` and `REQ-SEARCH-002`. `cap_to_delivery_scale` is a prior-
scale parameter, not an identifying anchor - prior regularisation does not
resolve structural non-identification (`REQ-LATENT-001` Requirement 2).

Applying Requirement 3's compiler rejection to Candidate A today would
block `compile_candidate_a_search_graph` outright - including the
implementation-and-validation scope `REQ-SEARCH-002` actually approved.
That is a contradiction, not an implementation: the rejection can only be
applied once `MD-021` supplies the anchor the rejection checks for.

### 2.3 What is already fail-closed today (and must not be weakened)

- Candidate A's official downstream use is already blocked by the
  fail-closed replay boundary (`core.predict.predict_mu` /
  `core.attribution.compute_shapley_contributions` raise for an unwired
  Candidate A pathway) - official planning/optimisation cannot consume an
  unanchored latent state by another route.
- `core.latent_state_identification.is_eligible_for_official_use` is the
  approved fail-closed use-eligibility gate (only `identified` is
  eligible). It has no production caller today, because the only latent
  state's official use is blocked earlier - the gate exists as the
  contract a future caller must use.
- The Diagnostics page renders graphical identification and latent-state
  identification as separate evidence dimensions with mandatory disclaimers
  and explicit limitations (`REQ-IDENT-001` Requirement 6,
  `REQ-LATENT-001` Requirement 6) - never collapsed into one "identified"
  flag.

## 3. Blocked work (decision-required, not implemented here)

| Item | Record | Blocking decision | Consequence |
|---|---|---|---|
| Compiler-level rejection of incompatible adjustment sets | `REQ-IDENT-001` R5 | VL-026: when graph checks are mandatory vs optional; which official requests carry adjustment-based estimands | No surface exists to wire; cannot invent which official artefacts request adjustment-based estimands |
| Compiler-level rejection of unanchored latent states | `REQ-LATENT-001` R3 | MD-021: Candidate A's actual scale/location anchor | Would block the approved Candidate A implementation/validation scope; rejection needs the anchor it would check |

## 4. Candidate integration points (for when the decisions land - none selected)

A. **Adjustment-set use boundary** (`REQ-IDENT-001` R5): a new
   fail-closed check in `core.estimand_identification` (e.g.
   `require_graph_compatible_adjustment(estimand_request, graph,
   identification_strategy)`) that official artefact builders (curve
   generation, planning, reporting) must call when - and only when - the
   VL-026 decision makes the check mandatory for their estimand class.
   The check must: reject direct-effect requests as unsupported (never
   apply the total-effect criterion to them); never treat a Candidate A
   structural estimand as ordinary covariate adjustment; treat a
   graph-compatible result as necessary evidence, never proof; and keep
   the existing disclaimer verbatim.

B. **Latent-state compiler gate** (`REQ-LATENT-001` R3): once MD-021
   defines Candidate A's anchor, `compile_candidate_a_search_graph` (or
   its caller in `GraphModelCompiler.compile`) verifies the compiled
   structure actually contains the approved anchor/constraint - mirroring
   Requirement 4's "the anchor or constraint is present in the compiled
   model" - and `is_eligible_for_official_use` becomes the single
   official-use gate every latent-pathway artefact must consult.

C. **No new vocabulary**: statuses stay the closed vocabularies already
   approved (`REQ-IDENT-001` R3's five values; `REQ-LATENT-001` R1's
   four values). Business labels remain VL-026/UX-028 decision-required.

## 5. What this workstream changed (independently valid authority work)

- This decision package (the determination + blocked items + candidates).
- A conformance test (`ancestry_mmm/tests/
  test_identification_use_boundary_package.py`) guarding the package's
  central mechanical facts: the compiler takes no adjustment-set input;
  the back-door assessor is diagnostics-only; the records still mark
  Requirement 5 / Requirement 3 as not implemented; this package records
  VL-026 and MD-021 as open.
- A decision-log entry (see `docs/decision_log.md`).

## 6. Unresolved human decisions (unchanged, restated for the record)

- VL-026: when graphical-identification checks are mandatory versus
  optional, and the accepted identification strategies for
  structural/linked estimands.
- MD-021: Candidate A's actual substantive scale/location anchor,
  measurement model or identifying constraint, and the business
  interpretation of one unit of its latent branded-search demand.
- UX-028: business and technical labels for identification statuses.

Until these land: the diagnostics evidence continues to be produced and
displayed (separate dimensions, disclaimers, explicit limitations), the
fail-closed downstream boundaries stay exactly as they are, and no
compiler-gating is added that a human decision has not authorised.
