# REQ-STALE-001: Definition-bound invalidation

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

Changing calculation-relevant outcome-definition fields changes the definition fingerprint and stales:

- outcome approval
- model approval where the outcome was fitted
- dependent effects
- curves
- scenarios
- optimisations
- reports

The implementation must use existing fingerprint propagation where possible.

Do not silently delete historical artefacts.

## Scope

- `ancestry_mmm/core/outcome_approval.py` — `fingerprint_outcome_definition`, `outcome_approval_matches_definition`
- `ancestry_mmm/core/fingerprint.py` — include new definition fields in model-spec fingerprint
- `ancestry_mmm/core/outcomes.py` — outcome catalogue fingerprint payload

## Required tests

- Changing event definition changes the fingerprint
- Changing date basis changes the fingerprint
- Changing exclusions changes the fingerprint
- Changing review notes does NOT change the definition fingerprint
- Definition fingerprint is deterministic
- Approval matching fails after a fingerprint-changing definition edit

## Owner

Platform engineering

## Affected modules

- `ancestry_mmm/core/outcome_approval.py` (new)
- `ancestry_mmm/core/fingerprint.py`
- `ancestry_mmm/core/outcomes.py`

## Human traceability

Derived from PRD section: Versioning and Staleness; G2A.7 implementation brief section 9
