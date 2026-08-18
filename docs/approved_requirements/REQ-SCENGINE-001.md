# REQ-SCENGINE-001: Structural Causal Engine Adapter, Capability Resolution and Runtime Isolation

## PRD source

Ancestry MMM PRD Part 3 v1.10 (retained v1.8 section, `Retained v1.8
update: bounded structural causal engine integration`; the file's own
v1.10 update separately resolves the primary-engine question — see
`REQ-ENGINE-001`), Part 4 v1.6 Final (`Retained v1.5 update: bounded
structural causal engine architecture`), Part 6 v1.8 (intro bullets on the
structural causal model adapter and engine capability), Part 7 v1.7 (intro
bullets on structural causal validation coherence), Part 8 v1.5 (`Focused
v1.5 update: structural intervention curves and bounded causal-engine
use`), Part 10 v1.8 Final (structural causal modelling, causal robustness
and intervention UX, retained from its own v1.7 update), and Part 11 v1.7
Final (bounded structural causal service and API contracts, retained from
its own v1.6 update) — reconciled by Work Package 0 of `Media-Mix-Lab:
Coding LLM Next Steps After PR #286`.

Part 4 v1.6, Part 6 v1.8, Part 7 v1.7, Part 10 v1.8, and Part 11 v1.7 each
reference a further **Part 5 v1.6** that was **not** supplied in the local
PRD traceability set reconciled by this work package (only Part 5 v1.4 is
present locally). This record is reconciled only against the PRD text
that actually exists locally; it does not assume, infer, or implement any
content of the missing Part 5 v1.6. See `docs/specification_authority.md`'s
"Version history: focused structural causal engine integration overlay"
section for the full version-mismatch record. (An earlier reconciliation
pass of this same work package additionally found Part 3 v1.9 and Part 11
v1.7 referenced-but-absent; a subsequent local PRD refresh supplied Part 3
v1.10 — cumulatively retaining its own v1.9 content — and Part 11 v1.7,
resolving both of those specific gaps. Only the Part 5 v1.6 gap remains.)

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-18). This record approves a target-state **contract**
only: the invariants a future structural causal engine adapter must
satisfy if and when one is built. It does not approve PathMC or any other
named library as a dependency, does not select an engine, and does not
authorise writing any adapter code. `docs/wp_structural_causal_engine_
decision_package.md` is the companion decision-support document covering
everything this record explicitly excludes (see below).

Depends on `REQ-GRAPH-001` (the approved causal graph remains the sole
authoritative structural input to any engine, including a future
structural causal adapter) and `AGENTS.md`'s "Engine-capability boundary"
section (every approved model specification must record, per capability,
whether it is native/extension/linked/planning-approximation/experimental/
unsupported).

## Capability status

Zero implementation. No structural causal engine adapter, capability
matrix, capability-resolution service, or isolated-runtime mechanism
exists anywhere in this repository. `core.graph_model_compiler` compiles
only the PyMC-hierarchical engine's supported edge roles (`REQ-GRAPH-001`'s
own table); it has no notion of a second engine at all. This record
reconciles the target-state contract into repository authority so that,
if and when a structural causal engine adapter is built, it is built
against an approved contract rather than directly from PRD prose. It does
not itself unblock or schedule that work.

## Requirement

### 1. The approved graph remains the sole structural authority

Any structural causal engine adapter must consume the same approved
`CausalGraph` (`REQ-GRAPH-001`) that the primary PyMC-hierarchical engine
consumes. An engine-specific formula, DSL, compiled graph, or structural
model object generated for that engine is derived state only — it must
never become a second, independently editable relationship configuration,
and no workflow may write to it directly instead of the graph.

### 2. Capability resolution occurs before execution

Before a structural causal job is accepted, the platform must resolve
whether the requested likelihood, hierarchy, temporal structure, ragged-
coverage pattern, transformation set, and causal mechanism are supported
by the selected engine. An unsupported combination must fail explicitly
with an attributable reason (mirroring `REQ-GRAPH-001` §7's "rejected
before approval, never silently dropped or approximated" pattern) or
remain on the existing primary MMM / Candidate A path — it must never be
silently simplified to fit the engine.

### 3. Engine-independent contracts

Public and internal application services, APIs, and persisted artefacts
that expose a structural causal capability (identification, structural
model compilation, posterior intervention, causal validation, response
generation) must describe Ancestry domain actions, not an implementation
library. No public or internal service, job, or artefact type may be
named after a specific engine (e.g. no "PathMC service"), consistent with
Part 11 v1.6's explicit instruction.

### 4. Runtime isolation only where required, never assumed by default

Where a candidate engine's dependency stack is incompatible with the
primary application/MMM runtime, it may execute in an isolated,
reproducible worker, process, environment, or container behind the same
application-service and artefact boundary. Runtime isolation must not be
introduced as a default architecture; it is justified only by an actual
demonstrated dependency or fault-isolation need for the specific engine
under evaluation (see `AGENTS.md`'s "Prefer a reusable Python analytical
core plus a modular monolith... over splitting into microservices without
an operational reason").

### 5. Provenance

Any structural causal artefact must retain: engine identifier, engine
version, runtime identity, the approved causal-graph structural
fingerprint it was generated from, and a fingerprint of the generated
engine-specific specification itself. These fields exist so that a graph
or engine change can be traced to every dependent structural causal
artefact through the same staleness/fingerprint mechanism `REQ-GRAPH-001`
already establishes for the primary engine.

### 6. Previously approved results remain readable without the optional runtime

An optional structural causal runtime being unavailable, removed, or
incompatible at a later date must never make a previously approved
structural causal result unreadable. A persisted structural causal
artefact must be a portable, engine-independent representation (per
Requirement 3), not an opaque engine-native object requiring the
originating runtime to load.

### 7. The primary production path is unaffected by default

Adding this contract must not change: the approved PyMC/PyMC-Marketing-
informed hierarchical MMM, ragged multi-market handling, Search Candidate
A, approved adstock/Hill transformation semantics, the sequential planning
kernel, economics, curve-bank governance, or optimisation. These remain
separate platform capabilities unless a future, separately approved
decision explicitly changes that boundary.

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp_structural_causal_engine_decision_package.md` for the full
decision-support treatment. In summary, this record does not approve:

- PathMC, or any other named library, as a required or default engine
  (Part 6 §37 `MD-022`);
- which observed-variable mediation and causal-query classes are eligible,
  which likelihood/hierarchy/transformation/temporal structures are
  supported, or which diagnostics may be used for official validation
  (Part 6 §37 `MD-022`);
- the specific runtime-isolation topology (process vs. container vs.
  separate service) for any actual candidate engine (Part 4 v1.6, Part 11
  v1.6);
- where engine/runtime technical-provenance detail is surfaced in the UI
  (Part 10 §47 `UX-032`) — the business-mode-vs-technical-mode distinction
  is a UX decision, not settled by this record;
- any exact structural-model DSL, generated-specification schema, or
  compiled-model representation.

## Affected modules

None yet. This record adds no code. It exists so that a future
capability-resolution service, engine-adapter module, or isolated-runtime
mechanism has an approved contract to implement against, rather than being
written directly from PRD prose. Anticipated future affected modules
(not created by this record): a new `core`/`application` engine-
capability-resolution module, `core.graph_model_compiler` (capability-
matrix extension), `core.persistence` (structural-causal artefact
provenance fields), and `docs/pymc_marketing_alignment.md` or an
equivalent structural-causal alignment document.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py::TestStructuralCausalEngineOverlayReconciled::test_req_scengine_001_indexed_and_classified_incomplete`
- `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py::TestStructuralCausalEngineOverlayReconciled::test_decision_package_referenced_by_req_scengine_001`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp_structural_causal_engine_decision_package.md`.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-18
