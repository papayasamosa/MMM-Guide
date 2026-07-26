# REQ-USE-001: Official versus exploratory outcome use

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

Official use is blocked when outcome approval is absent, stale, rejected, expired or does not include the requested use.

Exploratory use may continue only when:

- the workflow explicitly selects exploratory mode
- the result remains visibly non-official
- no approval is inferred or persisted
- downstream official artefacts cannot be created from it without revalidation

## Scope

- `ancestry_mmm/core/outcome_approval.py` — `require_outcome_approval` gate
- All UI pages that produce official artefacts: Diagnostics, Results/Curve Bank, Scenario Planner
- Scenario governance: `governance_mode` must be `"official"` or `"exploratory"`, never `"not_applicable"` for a manual scenario

## Required tests

- Official curve save blocked without outcome approval for `curve_publication`
- Official scenario evaluation blocked without outcome approval for `planning`
- Official optimisation blocked without outcome approval for `optimisation`
- Exploratory mode shows result but with visible non-official labelling
- Exploratory result cannot create an official downstream artefact

## Owner

Product / Analytics

## Affected modules

- `ancestry_mmm/core/outcome_approval.py` (new)
- `ancestry_mmm/core/scenario_governance.py`
- `ancestry_mmm/core/curve_bank.py`
- `ancestry_mmm/pages/06_Diagnostics.py`
- `ancestry_mmm/pages/07_Results_Curve_Bank.py`
- `ancestry_mmm/pages/08_Scenario_Planner.py`

## Human traceability

Derived from PRD section: Governance; G2A.7 implementation brief section 5.4
