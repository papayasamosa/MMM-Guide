# REQ-IDENT-001: Estimand-Specific Graphical Identification

## PRD source

Ancestry MMM PRD Part 6 v1.6 (intro bullets 1–2, §4.1 including
`REQ-4.1-04`/`REQ-4.1-05`, §30.1, §38 AC-07), Part 7 v1.5 (§0.15 intro bullet
4, §9, §9.1, §20.6, §39 blocking condition #7, §48 `VL-026`), and Part 10
v1.6 (`FCH-01`, §17.6, §17.7 including the mandated disclaimer, §23.4, §23.8,
§47 `UX-028`) — reconciled by Work Package 0 of `Media-Mix-Lab: Coding LLM
Next Steps Post PR #267`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief cited
above (2026-08-17). Depends on `REQ-GRAPH-001` (the approved causal graph
remains the authoritative structural input; this record adds an
estimand-specific diagnostic layered on top of it, not a replacement for
graph structural validation).

`core.causal_graph.validate_causal_graph` (implemented under `REQ-GRAPH-001`)
checks graph structure, roles, bad controls, cycles, and edge directions.
`core.identification_diagnostics` checks correlation, condition number,
posterior coefficient variation, and sensitivity on a fitted model. Neither
performs backdoor-path analysis, proposes or validates an adjustment set for
a *requested estimand*, or reports treatment descendants/colliders relative
to that estimand. This record's contract is a distinct, additional
diagnostic layer; it does not replace either existing check.

## Capability status

Core diagnostic implemented (Work Package 3, 2026-08-17):
`ancestry_mmm/core/estimand_identification.py`'s `assess_backdoor_
identification` implements Pearl's back-door criterion for an
adjustment-based total-effect estimand, composing `networkx`'s own
`is_d_separator`/`find_minimal_d_separator` (Context7 `/networkx/
networkx`; pinned `>=3.5,<4.0`, the version that introduced these current
names) rather than a hand-derived d-separation implementation — no
Ancestry-specific graph-theory algorithm is written from scratch.
`EstimandIdentificationResult` reports, per Requirement 2: whether
backdoor paths remain open (`status`); the proposed adjustment set;
treatment descendants incorrectly included in it (Pearl's second
back-door condition, checked separately in the original graph); a
constructive minimal adjustment set (excluding treatment's descendants)
when the proposed one fails; and members of the proposed set whose
removal would improve separation, flagged as likely colliders/collider
descendants (verified against a constructed collider scenario, not only
the simple-confounder case). `EstimandIdentificationResult` never exposes
a bare boolean; every result carries `GRAPHICAL_IDENTIFICATION_
DISCLAIMER` (Requirement 1) and an explicit limitation that this checker
cannot determine whether a graph node is actually observed data
(Requirement 2's "unavailable or unmeasured" item — `core.causal_graph.
CausalNode` has no observability field, so this is disclosed as a
limitation, never assumed either way).

Requesting `effect_type="direct"` returns `unsupported_by_current_
checker` rather than silently applying the total-effect criterion to a
direct-effect request (Requirement 3's closed status vocabulary, all five
values implemented) — direct/natural-direct effect identification
requires a different criterion this module does not implement.
Structural/linked-model estimands (Requirement 4) are correspondingly out
of this module's scope by construction: it only ever answers an
adjustment-based question.

`DiagnosticsArtefact`/Diagnostics-page wiring (Requirement 6's reporting
separation) now complete (Work Package 2 of `Media-Mix-Lab: Coding LLM
Next Steps After PR #286`, canonical Diagnostics evidence integration,
2026-08-18): schema v8 adds the `graphical_identification` section,
computed inline in `DiagnosticsService.evaluate()` when the caller
supplies a `causal_graph` and one or more `identification_requests` (no
PyMC required) — every result carries `GRAPHICAL_IDENTIFICATION_
DISCLAIMER` unchanged, and a `direct` effect-type request correctly
resolves to `unsupported_by_current_checker` rather than being silently
treated as identified (verified by an explicit test). `pages/06_
Diagnostics.py` exposes an interactive treatment/outcome/effect-type/
adjustment-set assessment, reported separately from every other evidence
dimension, always showing the disclaimer text.

Not yet implemented: Requirement 5 (extending `core.graph_model_
compiler`'s blocking-error contract to fail official compilation on an
incompatible adjustment-based estimand) — deferred as a separate
integration follow-up; this record's own diagnostic evidence production
does not depend on it.

## Requirement

### 1. A diagnostic, not a proof

A graph-compatible adjustment set is necessary evidence for an
adjustment-based estimand; it is not sufficient evidence that the causal
effect is valid. Passing a backdoor/d-separation/adjustment-set check
validates the requested adjustment logic *under the assumed graph*. Every
surface (technical or business) that displays this result must not state or
imply that it proves: the graph itself is correct; there is no unobserved
confounding; timing or measurement is correct; the functional form is valid;
or the effect is empirically well identified. This disclaimer is a
functional requirement of the diagnostic's presentation, not optional
UX copy.

### 2. Diagnostic scope, where adjustment-set logic applies

Where the requested effect can be assessed using graphical adjustment logic
against the approved causal graph, before treating the resulting effect as
identified the diagnostic must assess and record, per requested estimand:

- open backdoor paths;
- the proposed adjustment set and whether a minimal valid adjustment set
  exists;
- treatment descendants included (incorrectly) as controls;
- colliders or collider descendants opened by the proposed conditioning;
- whether the requested effect type (direct vs. total) is compatible with
  the proposed conditioning set;
- whether a required confounder is unavailable or unmeasured under the
  graph.

### 3. Explicit status vocabulary

The diagnostic must resolve to one of an explicit, closed status vocabulary
per requested estimand — at minimum: `graph_compatible`; `review_required`;
`not_identified_under_graph`; `unsupported_by_current_checker`; `not_
applicable`. A status must never be inferred from the presence of an edge
alone; it is tied to the specific requested treatment, outcome, and effect
type.

### 4. Structural/linked-model estimands use a different identification path

Where the requested estimand is identified through a full structural or
linked model rather than ordinary covariate adjustment (e.g. a
capacity-constrained or mediated pathway compiled through
`core.graph_model_compiler`), this record's diagnostic does not apply as the
sole identification evidence. The identification plan must instead state the
structural equations, observed measurements, identifying constraints, and
assumptions that replace an adjustment-set argument. A structural model must
not be labelled "graph-identified" merely because an adjustment set exists
for a different estimand, and a failed adjustment-set test does not
automatically invalidate a correctly specified structural system targeting a
different estimand with its own approved identification strategy.

### 5. Compiler-level blocking

Official model compilation must fail when a requested adjustment-based
estimand uses a conditioning set incompatible with the approved graph and no
approved alternative identification strategy exists — extending
`core.graph_model_compiler`'s existing blocking-error contract
(`REQ-GRAPH-001` §7), not superseding it.

### 6. Reporting separation

Graphical-identification status must be reported as a separate evidence
dimension from predictive validation, structural stability (`REQ-STAB-001`),
and latent-state identification (`REQ-LATENT-001`) — never collapsed into
one undifferentiated "identified"/"not identified" flag.

## Explicitly excluded (decision-required, not approved by this record)

- the full set of graphical-identification statuses, when graph checks are
  required versus optional, and the accepted identification strategies for
  structural/linked estimands (Part 7 §48 `VL-026`);
- the business and technical labels used for each status (Part 10 §47
  `UX-028`).

## Affected modules

- `ancestry_mmm/core/estimand_identification.py` (new —
  `EstimandIdentificationResult`, `assess_backdoor_identification`)
- `pyproject.toml` / `uv.lock` (new dependency: `networkx>=3.5,<4.0`)
- `ancestry_mmm/core/causal_graph.py` (read-only consumer of the approved
  graph via `_build_digraph`; this record does not add a second,
  divergent structural validator — `excluded_diagnostic_only` edges are
  excluded from the identification graph, matching `REQ-GRAPH-001`'s own
  "compiles to nothing" rule)
- `ancestry_mmm/core/identification_diagnostics.py` (unchanged — this
  record's diagnostic is additional, not a replacement)
- `ancestry_mmm/core/graph_model_compiler.py` (not yet touched — Requirement
  5's compiler-blocking extension is deferred)
- `ancestry_mmm/pages/14_Causal_Graph.py` (not yet wired — deferred)
- `ancestry_mmm/application/diagnostics_service.py` (Work Package 2 —
  `DiagnosticsArtefact` schema v8 `graphical_identification` section,
  computed inline in `evaluate()`)
- `ancestry_mmm/pages/06_Diagnostics.py` (Work Package 2 — wired,
  interactive treatment/outcome/effect-type/adjustment-set assessment)
- `docs/approved_requirements/REQ-IDENT-001.md` (this record)
- `docs/approved_requirements/index.json` (updated)

## Required tests

- `ancestry_mmm/tests/test_estimand_identification.py` (18 tests: a
  simple-confounder scenario proving the empty set leaves a backdoor path
  open and adjusting for the confounder is graph-compatible; a mediator/
  treatment-descendant scenario proving it is flagged and excluded from
  the constructive minimal adjustment set; a constructed collider
  scenario proving conditioning on a collider that was already blocking
  a path by default correctly reopens it and is flagged as the
  problematic member, never the genuine confounder in the same proposed
  set; `effect_type="direct"` returning `unsupported_by_current_checker`;
  treatment/outcome absent from the graph returning `not_applicable`; a
  cyclic graph returning `unsupported_by_current_checker` rather than a
  silently wrong answer; `excluded_diagnostic_only` edges excluded from
  the identification graph; and result validation/round-trip)
- `ancestry_mmm/tests/test_diagnostics_artefact.py::TestEvaluateGraphicalIdentification`
  (Work Package 2 — not_computed with no graph/requests; graph-compatible
  total-effect request computed; `direct` effect-type request rejected,
  not silently allowed; round trip/fingerprint)
- `ancestry_mmm/tests/test_diagnostics_wp2_evidence_apptest.py::test_graphical_identification_assesses_a_graph_compatible_total_effect`
- `ancestry_mmm/tests/test_diagnostics_wp2_evidence_apptest.py::test_graphical_identification_rejects_unsupported_direct_effect_request`
- `ancestry_mmm/tests/test_official_lifecycle_browser.py::test_diagnostics_wp2_evidence_sections_render_in_browser`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

Resolved (Work Package 2): `DiagnosticsArtefact` schema v7 → v8. An
artefact computed before schema v8 upgrades this section to `not_computed`
with an explicit "added in schema v8" message. New dependency
`networkx>=3.5,<4.0` added to `pyproject.toml`/`uv.lock` (pure-Python,
MIT-licensed, no known vulnerabilities per `pip-audit` against the updated
lock file) remains unchanged by this wiring.

## Unresolved decisions

- Graph-library/algorithm choice for backdoor-path and adjustment-set
  computation — **resolved**: `networkx>=3.5,<4.0` (`is_d_separator`,
  `find_minimal_d_separator`), verified via Context7 against
  `/networkx/networkx` current documentation before selection, per root
  `AGENTS.md`'s required upstream-reference workflow.
- `DiagnosticsArtefact`/Diagnostics-page wiring — **resolved** (Work
  Package 2, see Capability status above).
- Whether this diagnostic is computed synchronously at graph-approval
  time, at model-compile time, or both — deferred to the Requirement 5
  compiler-integration follow-up (Diagnostics-page evaluation, resolved
  above, is one such point; graph-approval-time and compile-time remain
  undecided).
- The full set of graphical-identification statuses, when graph checks
  are required versus optional, and the accepted identification
  strategies for structural/linked estimands (Part 7 §48 `VL-026`) —
  this implementation provides the five-value status vocabulary Part 10
  §17.7 suggested; which statuses are officially *required* for a given
  use remains that separate decision.
- The business and technical labels used for each status (Part 10 §47
  `UX-028`).

## Owner

Modelling

## Approval date

2026-08-17
