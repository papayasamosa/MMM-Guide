# REQ-ENGINE-001: Approved Primary Production MMM Engine (PyMC)

## PRD source

Ancestry MMM PRD Part 3 v1.10 (`Focused v1.10 update: approved primary
production MMM engine`) — reconciled by Work Package 0 of `Media-Mix-Lab:
Coding LLM Next Steps After PR #286`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-18). This record translates an already-resolved PRD
governance decision into repository authority; it approves no new
statistical, causal, or engine-selection choice of its own. Distinct from,
and does not resolve, `REQ-SCENGINE-001`'s still-open supplemental
structural-causal-adapter decision (tracked by `docs/wp_structural_
causal_engine_decision_package.md`).

Part 3 v1.10 states: "This revision resolves the remaining governance
ambiguity around the primary production MMM engine. **PyMC is the
approved primary production MMM engine for the Ancestry MMM platform**,
using PyMC Marketing-informed or supported components where they fit the
approved model specification and approved custom PyMC extensions where
required. This is now a resolved production-architecture decision in Part
3 and must not remain represented as `decision_required`." Before this
revision, root `AGENTS.md`'s "Engine-capability boundary" section left the
choice between PyMC and Meridian as the primary engine open ("The platform
may launch with one engine behind a stable adapter boundary rather than
both at once" — describing a still-open choice, not a made one). This
record closes that specific ambiguity; it does not otherwise change
`AGENTS.md`'s engine-capability-classification requirement.

## Capability status

**Already the de facto implementation, now also the approved governance
fact.** Every production model builder in this repository
(`core.hierarchical_model.build_fh_hierarchical_model`,
`core.market_specific_model.build_fh_market_specific_model`,
`core.models.fit_model`, `core.search_capacity`'s Candidate A engine) is
already built directly on PyMC, using PyMC-Marketing-informed
transformations where they fit (see `docs/pymc_marketing_alignment.md`)
and approved custom PyMC extensions elsewhere (hierarchical hyperpriors,
the Search capacity/mediation model, sequential simulation). Meridian is
not imported anywhere in this repository (`ancestry_mmm/**` contains no
`meridian` import). This record therefore has **zero migration impact and
requires no code change** — it exists so that the engine choice is an
explicit, citable, approved requirement rather than an implicit fact of
how the code happens to be written, closing the ambiguity `AGENTS.md`
previously left open between PyMC and Meridian.

## Requirement

### 1. PyMC is the approved primary production MMM engine

PyMC is the default and approved production execution path for the
primary hierarchical MMM (Model A/Model C, and any future production
model sharing that path). This is an approved architecture decision, not
an open question requiring further evaluation before every PR.

### 2. PyMC Marketing and custom PyMC extensions

PyMC Marketing may supply supported transformations, model components,
utilities, or reference implementations where they satisfy the governed
Ancestry model contract (per `AGENTS.md`'s "PyMC and PyMC Labs reference
policy" and "Required upstream-reference workflow", unchanged by this
record). Approved custom PyMC components remain necessary, and continue to
be used, where a required hierarchy, likelihood, causal pathway, baseline,
transformation, or other model behaviour is not supplied directly by PyMC
Marketing (per `core/AGENTS.md`'s "Current custom-model reality").

### 3. Model specifications remain platform-native

PyMC code, PyMC Marketing objects, and other engine-native state do not
become a second source of product or causal truth. This restates, for the
now-confirmed primary engine, the same governed-model-specification
principle `REQ-GRAPH-001` already establishes for the causal graph and
`REQ-SCENGINE-001` establishes for a future structural-causal adapter.

### 4. Capability classification requirement is unchanged

Selecting PyMC as the primary engine does not exempt any capability from
`AGENTS.md`'s existing "Engine-capability boundary" classification (native
/ supported-extension / linked-model / planning-approximation /
experimental / not supported). If a required capability cannot be
represented faithfully within PyMC/PyMC-Marketing, the platform must use
an explicitly approved linked or specialist path, retain exploratory
status, or return `unsupported` — selecting PyMC does not itself approve
an unsupported analytical simplification.

### 5. Meridian is not adopted

Meridian remains a benchmark or possible future adapter, not the current
or planned production MMM path, unless a later, separately approved
decision explicitly changes the engine architecture. No code in this
repository may import or depend on Meridian without that separate
approval.

### 6. PathMC is not the primary engine

PathMC remains, at most, a candidate implementation behind the bounded
*supplemental* structural-causal adapter boundary (`REQ-SCENGINE-001`,
still decision-required per that record and
`docs/wp_structural_causal_engine_decision_package.md`'s D1). This record
does not change that boundary in either direction: PathMC is not approved
as a dependency by this record, and this record does not make PathMC any
more or less likely to be approved for the supplemental role.

### 7. Changing the primary engine is a new, separate decision

Changing the primary production MMM engine away from PyMC would itself be
a new material architecture decision requiring a new approved decision
record and corresponding updates across the dependent PRD parts (3, 4, 6,
7, 10, 11) and this record. Nothing in this record, or in any other
current requirement, authorises that change.

## Explicitly excluded (decision-required, not approved by this record)

- any change to the primary production MMM engine away from PyMC
  (Requirement 7);
- whether, when, and for which capability class a supplemental
  structural-causal adapter (PathMC or otherwise) is adopted
  (`REQ-SCENGINE-001`, tracked by `docs/wp_structural_causal_engine_
  decision_package.md` D1);
- any Meridian adoption for any capability.

## Affected modules

- `docs/approved_requirements/REQ-ENGINE-001.md` (new)
- `docs/approved_requirements/index.json` (new entry)
- `AGENTS.md` (root) — "Engine-capability boundary" section cross-
  references this record to resolve the ambiguity its own text previously
  left open between PyMC and Meridian as primary engine; the section's
  substantive capability-classification requirement is otherwise
  unchanged.

No `ancestry_mmm/core`, `ancestry_mmm/application`, or `ancestry_mmm/pages`
code changes — the implementation already conforms.

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py::TestStructuralCausalEngineOverlayReconciled::test_req_engine_001_indexed_and_no_meridian_import`

## Migration impact

None. This record documents an already-true implementation fact as
approved authority; it changes no schema, persisted artefact, or code
behaviour.

## Unresolved decisions

None introduced by this record. The still-open supplemental structural-
causal-adapter decision belongs to `REQ-SCENGINE-001` /
`docs/wp_structural_causal_engine_decision_package.md`, not this record.

## Owner

Modelling / Platform engineering

## Approval date

2026-08-18
