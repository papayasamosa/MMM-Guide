# REQ-PLAN-001: Explicit planning outcome

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

A planning objective (`PlanningObjective`) must explicitly identify its target outcome or outcomes.

No planning objective may silently default to NBT, GSA, sign-ups, DNA kits, value or a blended volume.

Official planning and optimisation require the target outcome definitions to be approved for the requested use.

## Scope

- `ancestry_mmm/core/optimization.py` — `PlanningObjective` dataclass
- `ancestry_mmm/pages/08_Scenario_Planner.py` — objective selector
- Legacy migration: `planning_objective_from_legacy` maps explicit old strings but does not grant approval

## Required tests

- Constructing/deserialising an objective without explicit target intent does not default to NBT
- Explicit legacy `fh_net_billthrough` intent maps to NBT but remains subject to approval
- Official planning with an unapproved target is blocked
- Exploratory planning remains explicitly labelled
- Target outcome IDs must be present in the fitted model
- Rate outcomes remain invalid CPA denominators and optimisation targets

## Owner

Product / Analytics

## Affected modules

- `ancestry_mmm/core/optimization.py`
- `ancestry_mmm/core/outcome_approval.py` (new)
- `ancestry_mmm/pages/08_Scenario_Planner.py`

## Human traceability

Derived from PRD section: Scenario Planning; G2A.7 implementation brief section 6
