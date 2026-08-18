# REQ-SCCURVE-001: Structural Intervention Curve Provenance and Planning-Eligibility Boundary

## PRD source

Ancestry MMM PRD Part 8 v1.5 (`Focused v1.5 update: structural intervention
curves and bounded causal-engine use`), Part 9 v1.6 Final (structural
intervention response curves "must be distinguishable from ordinary MMM
response curves and must retain graph, estimand, effect-computation,
engine, runtime, support and approval provenance"), and Part 10 v1.8 Final
(§47 `UX-033` structural intervention planning eligibility) — reconciled
by Work Package 0 of `Media-Mix-Lab: Coding LLM Next Steps After PR #286`.

## Approval and traceability

Approved for implementation by the task-specific implementation brief
cited above (2026-08-18). Target-state contract only. Extends
`REQ-CURVE-001` (official response-curve authority and evidence contract)
to a structural-intervention-engine-produced curve; it does not
supersede or weaken `REQ-CURVE-001` for an ordinary MMM response curve.
Depends on `REQ-SCENGINE-001`/`REQ-SCEFFECT-001` (a structural intervention
curve can only exist once a structural causal engine adapter produces a
posterior intervention effect under those contracts).

## Capability status

Zero implementation. No structural intervention curve type exists in
`core.canonical_curves`/`core.curve_bank`/`core.curve_artifact`. The
existing curve bank supports only ordinary MMM response curves (including
Candidate A's own curves once wired, per `REQ-SEARCH-002`'s remaining
scope).

## Requirement

### 1. Curve bank distinguishes structural intervention curves from ordinary curves

If and when a structural intervention curve is produced, the curve bank
must represent it as a distinct curve kind from an ordinary MMM response
curve, never silently merged into the same type or listing without a
distinguishing label.

### 2. Provenance retained on the curve

A structural intervention curve must retain: the approved causal graph
version and structural fingerprint it was generated from; the estimand
(direct/mediated/total, and which downstream endogenous variables were
allowed to respond, per `REQ-SCEFFECT-001` §3); the calculation method
(posterior intervention, per `REQ-SCEFFECT-001` §2); engine identifier,
engine version, and runtime identity (per `REQ-SCENGINE-001` §5); and
observed-support/extrapolation status, mirroring `REQ-CURVE-001`'s
existing "support provenance" and "extrapolation status" fields for an
ordinary curve.

### 3. Reportable does not imply planning-eligible

A structural intervention curve or effect being reportable (i.e. produced
and validated as evidence) does not by itself grant sequential-planning or
optimisation eligibility. `AGENTS.md`'s existing "Governance" section
("fitted in model" / "visible in analyst attribution" / "approved for
headline reporting" / "eligible for planning" / "eligible for
optimisation" are kept separate) applies unchanged to a structural
intervention curve — planning/optimisation eligibility is a further,
separately approved step this record does not grant.

### 4. The sequential simulator remains authoritative unless separately proven equivalent

The existing weekly sequential simulator (`core.sequential_simulation`,
`REQ-STATE-001`/`REQ-SCEN-001`–`004`) remains the authoritative mechanism
for carry-in state, weekly carryover, terminal response, cross-product lag
context, and capacity-constrained planning. A structural-causal-engine-
specific simulator may be adopted for these purposes only if it is
separately proposed and proves numerical and semantic equivalence to the
existing simulator on a governed validation grid, and is separately
approved — this record does not itself approve or predetermine that
comparison's outcome.

### 5. Candidate A is not replaced

Producing a structural intervention curve for some other pathway does not
authorise replacing Candidate A's Search mediation/capacity model
(`REQ-SEARCH-002`) with a generic structural intervention curve for
Search. This restates `REQ-SCEFFECT-001` §5's boundary in curve terms.

### 6. Same validation, support, and approval gates as any other curve

A structural intervention curve remains subject to the same `REQ-CURVE-001`
support/stability/economics/approval gates as any other curve, plus the
causal-robustness evidence dimensions from `REQ-CAUSALROBUST-001` where
applicable. It does not receive a lighter approval path because it was
computed through posterior intervention rather than the ordinary
counterfactual-prediction path.

### 7. Explicit unsupported status, never silent fallback

If a structural causal engine is unavailable, unsupported for the
requested pathway, or its capability check (`REQ-SCENGINE-001` §2) fails,
the platform must return an explicit unsupported/exploratory status for
that curve request rather than silently reverting to a different causal
interpretation (e.g. treating the pathway as an ordinary direct effect).

## Explicitly excluded (decision-required, not approved by this record)

See `docs/wp_structural_causal_engine_decision_package.md`. In summary,
this record does not approve:

- planning or optimisation eligibility for any structural intervention
  curve (Part 10 §47 `UX-033`);
- a replacement simulator for sequential planning (Part 8 v1.5's own
  "unless a future engine-specific simulator proves ... equivalence"
  clause — the proof and the approval are both future, separate steps);
- the specific validation grid or numerical-equivalence tolerance a
  replacement simulator would need to satisfy;
- warning-label wording for a reportable-but-planning-ineligible curve
  (Part 10 §47 `UX-033`).

## Affected modules

None yet — target-state contract only. Anticipated future affected
modules (not created by this record): `core.canonical_curves`,
`core.curve_bank`, `core.curve_artifact` (new curve kind and provenance
fields), `application.curve_service`, and `pages/13_Official_Curve_
Generation.py` / `pages/07_Results_Curve_Bank.py` (UI distinction between
ordinary and structural intervention curves).

## Required tests

- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_approved_requirements_readme_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_exists`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_index_json_is_valid`
- `ancestry_mmm/tests/test_outcome_approval.py::TestAuthorityConsistency::test_indexed_records_exist`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_requirement_ids_are_unique`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_record_path_exists`
- `ancestry_mmm/tests/test_requirements_index_conformance.py::test_every_indexed_test_node_is_collectable`
- `ancestry_mmm/tests/test_structural_causal_authority_reconciliation.py::TestStructuralCausalEngineOverlayReconciled::test_req_sccurve_001_indexed_and_classified_incomplete`

## Migration impact

None. No schema, persisted artefact, or application code changes as a
result of this record.

## Unresolved decisions

All items under "Explicitly excluded" above, tracked by
`docs/wp_structural_causal_engine_decision_package.md`.

## Owner

Modelling / Product

## Approval date

2026-08-18
