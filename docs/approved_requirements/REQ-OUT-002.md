# REQ-OUT-002: Composable outcome approval

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

Outcome definition, analytical eligibility and approval for use are separate concepts.

An outcome may be:

- defined but unapproved
- approved for fitting but not reporting
- approved for reporting but not planning
- approved for planning but not optimisation
- approved for one market, product, segment or period only

Approval is bound to the definition fingerprint and becomes stale when the definition changes.

## Scope

- `ancestry_mmm/core/outcome_approval.py` — `OutcomeApproval`, approval helpers
- `ancestry_mmm/core/outcomes.py` — `OutcomeDefinition` business-metadata fields
- `ancestry_mmm/core/optimization.py` — planning/optimisation gates
- `ancestry_mmm/core/persistence.py` — export/import of outcome approvals
- UI pages: Structure, Diagnostics, Results/Curve Bank, Scenario Planner

## Required tests

- Matching approved record passes for an allowed use
- Approval for reporting does not permit optimisation
- Stale fingerprint blocks use
- Expired approval blocks use
- Rejected approval blocks use
- Wrong market/segment scope blocks use
- Role/eligibility alone never grants approval

## Owner

Product / Analytics

## Affected modules

- `ancestry_mmm/core/outcome_approval.py` (new)
- `ancestry_mmm/core/outcomes.py`
- `ancestry_mmm/core/optimization.py`
- `ancestry_mmm/core/persistence.py`
- `ancestry_mmm/core/fingerprint.py`
- `ancestry_mmm/pages/03_Structure_Segments_Markets.py`
- `ancestry_mmm/pages/06_Diagnostics.py`
- `ancestry_mmm/pages/07_Results_Curve_Bank.py`
- `ancestry_mmm/pages/08_Scenario_Planner.py`

## Human traceability

Derived from PRD section: Outcome Governance; G2A.7 implementation brief section 5.1-5.4
