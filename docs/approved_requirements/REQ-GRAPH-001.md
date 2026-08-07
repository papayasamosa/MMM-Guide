# REQ-GRAPH-001: Graph-Authoritative Causal Configuration

## PRD source

Current product-context implementation brief: first-release causal
configuration must be graph-first, and the approved graph must become the
authoritative structural input to model compilation. Identified as the
largest missing first-release product capability.

## Capability status

Not yet implemented. No graph domain object exists anywhere in this
repository today (core, application, tests, or docs — confirmed by search
for `CausalGraph`, `GraphNode`, `GraphEdge`, `networkx`, `DAG`, `acyclic`).
The current relationship-configuration mechanism is the `MediaOutcomePathway`
catalogue (`ancestry_mmm/core/pathways.py`, edited via a `st.data_editor` in
`ancestry_mmm/pages/03_Structure_Segments_Markets.py`) plus the
diagnostics-only `FunnelLink` list (`ancestry_mmm/core/funnel.py`). Both are
form-driven and neither is a general graph: `MediaOutcomePathway` is a flat
channel→outcome edge list with no cycle detection (cycles are not
structurally possible in a bipartite list), and `FunnelLink` is an unordered
pair list used only for coherence diagnostics.

Root `AGENTS.md` already names a target pathway taxonomy (direct, mediated,
capacity-constrained/censored, cross-product halo, moderated,
residual-interaction, excluded/diagnostic-only) broader than today's four
`PATHWAY_ROLES` (`primary_direct`, `active_cross_product`,
`exploratory_cross_product`, `excluded`), and both PR E.2 and PR G1 decision
log entries explicitly listed a causal DAG as out of scope, reserved for a
dedicated future PR. This record is that reservation being exercised.

This record is design/specification only. It does not implement the graph
editor UI, the graph domain model, or the model compiler — those are
delivered by separate, dependent requirements/PRs (causal graph domain and
persistence; graph-authoritative model compilation; graph-first Streamlit
editor), each re-validated against this record's contract rather than
re-deriving it.

## Requirement

### 1. Graph-first relationship configuration

- The approved causal graph is the single authoritative source of
  variable-level causal structure for model compilation.
- A fully drag-and-drop canvas is the primary editing surface for nodes and
  edges.
- A synchronised structured property panel (form fields for the selected
  node or edge) always reads and writes the same underlying graph state as
  the canvas — never a separate or divergent store.
- A keyboard-accessible alternative exists for every graph edit the canvas
  supports (add/remove/rewire a node or edge, change role, change lag):
  both a keyboard-navigable canvas (focus via Tab, move via arrow keys,
  remove via Delete, deselect via Escape, with ARIA roles on nodes and
  edges) and a structured, non-drag data-editor view that edits the same
  graph records — so a keyboard-only or assistive-technology user is never
  blocked from a capability the canvas offers.

### 2. Governed node/edge records and graph versions

- `CausalNode`: id, label, role, product/segment/market scope, metadata.
- `CausalEdge`: id, source node id, target node id, edge/pathway role, lag
  direction, lag configuration, metadata.
- `GraphLayout`: per-node canvas position and visual metadata only — never
  contributes to structural/causal meaning.
- `CausalGraph`: a versioned aggregate of nodes, edges and layout, carrying
  `graph_version`, `status`, a schema version, and audit fields (created/
  approved by, timestamp).
- Every saved graph is a new immutable `graph_version`; approving a version
  never mutates an earlier one — historical versions remain auditable,
  mirroring the existing immutability pattern in `core/model_identity.py`
  and `core/fingerprint.py`.

### 3. Structural fingerprint and layout fingerprint are independent

- `CausalGraph` carries two independently and deterministically computed
  fingerprints:
  - a **structural fingerprint**, derived only from node roles/scopes, edge
    endpoints, edge roles, and lag configuration — anything that changes
    what compiles;
  - a **layout fingerprint**, derived only from `GraphLayout` — anything
    that changes only how the graph is drawn.
- A layout-only edit changes the layout fingerprint and leaves the
  structural fingerprint untouched; it must not stale any dependent model
  specification, fitted model, official curve, or scenario.
- A structural edit changes the structural fingerprint; it must stale the
  dependent model specification, fitted model, official curves, and
  scenarios — mirroring the existing invalidation pattern already applied to
  outcome and pathway definition fingerprints (`core/outcome_approval.py`,
  `core/fingerprint.py`).
- No code may derive a third, undocumented notion of "did the graph
  change" — these two fingerprints are the only ones.

### 4. Variable roles (node roles)

Minimum required vocabulary, chosen as a strict variable-level
generalisation of the AGENTS.md-approved pathway taxonomy rather than a
competing one:

- `outcome`
- `intervention`
- `mediator`
- `demand_capture`
- `capacity_or_cap`
- `moderator`
- `control_or_confounder`
- `diagnostic`
- `excluded`

### 5. Edge/pathway roles and lag

- Edge roles extend today's narrower `PATHWAY_ROLES` up to the full
  AGENTS.md pathway taxonomy: direct, mediated, capacity-constrained/
  censored, cross-product halo, moderated, residual-interaction, excluded/
  diagnostic-only.
- Every edge has an explicit lag direction (upstream → downstream) and lag
  configuration (type and weeks), consistent with the existing `LAG_TYPES`
  in `core/pathways.py`.
- `MediaOutcomePathway` and `FunnelLink` become graph-derived views once the
  compiler requirement lands. Neither may remain an independently editable
  second source of relationship truth capable of disagreeing with the
  graph — no second hidden relationship configuration.

### 6. Deterministic graph validation

Every save/approve runs the same deterministic validator, producing a
`GraphValidationResult` (blocking errors plus non-blocking warnings),
covering at minimum:

- duplicate node or edge ids;
- edge endpoints referencing unknown nodes;
- unknown or invalid node/edge role;
- prohibited edge direction for a role pair (e.g. an edge terminating in
  `intervention`, or an edge originating in `outcome` without an explicit
  diagnostic/excluded role);
- **bad-control checks**: rejects a `control_or_confounder` node positioned
  as a descendant of an `intervention` on a causal path to the target
  `outcome` (a mediator or collider misclassified as a control);
- **incompatible-role checks**: e.g. a node cannot be both `outcome` and
  `capacity_or_cap` in the same graph version; an excluded edge cannot carry
  planning-eligible metadata;
- acyclicity among `intervention`/`mediator`/`moderator`/`outcome` nodes,
  with any relaxation for capacity/diagnostic-only edges gated by an
  explicit engine-capability declaration, never permissive by default;
- a missing required `outcome` node;
- invalid or missing lag configuration for an edge role that requires one.

### 7. Model-plan preview and engine capability checks

- Before approval, the graph produces a `GraphCompilationPlan` preview: the
  modelling columns, outcome ordering, pathway masks, and lag structure the
  graph would compile to, without requiring a fit.
- The preview is checked against the target engine's declared capability
  (initially PyMC/PyMC Marketing, per the first production path). A graph
  structure the engine cannot express is rejected before approval with an
  explicit, attributable message — never silently dropped or approximated.

### 8. Draft and approved states

- `status`: `draft` (editable, not authoritative), `approved` (authoritative
  structural input to compilation), `superseded` (a newer approved version
  exists), `deprecated` — reusing the status vocabulary already defined in
  `docs/approved_requirements/README.md`.
- Only an `approved` graph version may be bound into a model specification's
  structural fingerprint.
- Approving a graph requires a `GraphValidationResult` with zero blocking
  errors.

### 9. Authoritative structural input to compilation

- Once the compiler requirement lands, the graph-to-model boundary accepts
  only an approved `CausalGraph`, revalidates it, and produces the compiled
  model inputs. The graph is the sole structural input; no parallel manual
  Python edit path may alter compiled structure without going through the
  graph.
- A supported graph edit (adding/removing/re-rolling a node or edge,
  changing lag) changes compilation the next time the graph is approved and
  a model is prepared from it, without any manual Python code change.

### 10. Project export/import and schema migration

- `CausalGraph` versions referenced by any surviving model specification,
  plus the current draft, round-trip through project export/import,
  following the governance-evidence-chain pattern already established for
  validation policy, diagnostics artefacts, and official curve artefacts.
- A malformed or unknown-schema imported graph fails closed — rejected with
  a clear reason, never partially imported or silently coerced — consistent
  with the existing "malformed imported governance evidence must fail
  closed" invariant.
- `CausalGraph` carries its own schema version; a schema change requires an
  explicit migration function, and an unrecognised future schema version is
  rejected explicitly rather than guessed at.

### 11. Unsupported-state behaviour

- A project with no causal graph yet (every current and pre-existing
  project) is a valid, clearly labelled unsupported-for-graph-compilation
  state, not an error. Until the compiler requirement ships, the existing
  `MediaOutcomePathway`/`FunnelLink` path remains the only compilation
  input, and the two must not be silently blended with graph output.
- Once the compiler requirement ships, a project with only a `draft`
  (never-approved) graph is blocked from official compilation with an
  explicit message, distinct from a project whose approved graph has since
  been structurally staled.

### 12. Acceptance evidence

Domain round-trip, fingerprint, validation, migration, invalidation-
propagation, AppTest, and Playwright acceptance evidence are specified and
delivered by the dependent domain, compiler, and editor requirements against
this record's contract. This record adds no executable tests beyond the
general requirements-authority conformance suite (see Required tests).

## Candidate graph-editing component (research note, not a selection)

Researched via Context7 and the GitHub API for a maintained,
Streamlit-compatible, drag-and-drop node/edge editor that operates locally
(no graph data sent to a third-party hosted service):

| Candidate | Basis | License | Maintenance | Notes |
|---|---|---|---|---|
| `streamlit-flow-component` (`dkapur17/streamlit-flow`) | Wraps React Flow | MIT | Active-ish; last push 2025-06-24, 14 open issues | Inherits React Flow's built-in ARIA roles and keyboard navigation (focus via Tab, move via arrow keys, remove via Delete, deselect via Escape) — the strongest fit for the keyboard-accessible canvas requirement in §1 |
| `streamlit-agraph` | vis.js | MIT | Stale — last PyPI release 2023-01-28 | Visualization-oriented, not an edit-in-place drag/drop editor; not selected |
| `streamlit-elements` (`okld/streamlit-elements`) | Material UI dashboard grid | MIT | General dashboard component, not node/edge graph editing | Not a fit for this use case |

None of these send graph data to a third-party hosted service — each
renders through a locally-served Streamlit custom component.
`streamlit-flow-component` is the leading candidate for the editor
requirement; its freshness and maintenance must be re-verified at that
requirement's implementation time rather than assumed from this record.

## Affected modules

- `docs/approved_requirements/REQ-GRAPH-001.md` (new)
- `docs/approved_requirements/index.json` (new entry)

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`

## Migration impact

None. No existing schema, model, or persisted artefact changes as a result
of this record. `MediaOutcomePathway` and `FunnelLink` remain the sole
compilation input until the dependent compiler requirement ships and
explicitly supersedes them.

## Unresolved decisions

- Final graph-editing component selection (candidate:
  `streamlit-flow-component`) — deferred to the editor requirement, subject
  to a freshness re-check at that time.
- Whether acyclicity is ever relaxable for a declared capacity/diagnostic-
  only edge, and under what engine-capability declaration — deferred to the
  domain requirement's validator design; must not default to permissive.
- Exact `GraphCompilationPlan` preview schema — deferred to the compiler
  requirement.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-07
