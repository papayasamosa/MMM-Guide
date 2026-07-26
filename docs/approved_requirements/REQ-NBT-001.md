# REQ-NBT-001: Conditional supplied-NBT use

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

The supplied weekly NBT path remains supported as a data-readiness path.

NBT may be used officially only when:

1. its outcome definition (`OutcomeDefinition`) is approved for the requested use via a matching `OutcomeApproval`; and
2. supplied completeness validation (`validate_supplied_net_billthrough`) passes.

Do not reconstruct billing events or cohort maturity for an approved complete weekly NBT feed.

Do not use NBT merely because its metric key (`fh_net_billthrough_count`) exists in the catalogue.

Data completeness is not the same thing as business-definition approval. Both are required.

## Scope

- `ancestry_mmm/core/net_billthrough.py` — bind metadata to outcome definition
- `ancestry_mmm/core/outcome_approval.py` — NBT-specific approval gate
- Model training gate: official fitting of NBT requires approval for `model_fit`
- Scenario planner: NBT planning requires approval for `planning` or `optimisation`

## Required tests

- Complete NBT data + no outcome approval = blocked
- Approved NBT + incomplete data = blocked
- Approved NBT + complete data = allowed for the approved use
- Approval for `model_fit` does not imply approval for `optimisation`
- Changing the NBT definition stales its approval
- No NBT outcome means NBT metadata is not required
- Legacy NBT bundle imports as `legacy_unapproved`

## Owner

Product / Finance

## Affected modules

- `ancestry_mmm/core/net_billthrough.py`
- `ancestry_mmm/core/outcome_approval.py` (new)
- `ancestry_mmm/core/optimization.py`
- `ancestry_mmm/pages/04_Model_Config.py`
- `ancestry_mmm/pages/08_Scenario_Planner.py`

## Human traceability

Derived from PRD section: Net Bill-Through; G2A.7 implementation brief section 7
