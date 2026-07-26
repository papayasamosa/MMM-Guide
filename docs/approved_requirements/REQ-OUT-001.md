# REQ-OUT-001: Distinct outcome definitions

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

Sign-up, GSA, Gross Bill Through, Bill Through, Net Bill Through, revenue, contribution and lifetime value are distinct outcomes or value measures.

They must not be aliases and must not inherit a universal conversion sequence. No implicit ordering or conversion between them is assumed.

Every official analytical artefact (fit, curve, attribution, report, scenario, optimisation) must reference a versioned `OutcomeDefinition`.

## Scope

- `ancestry_mmm/core/outcomes.py` — `OutcomeDefinition`, `METRIC_REGISTRY`, `normalize_metric_key`
- All named totals: `fh_gsa_outcome_ids`, `fh_signup_outcome_ids`, `dna_kit_sale_outcome_ids`, `fh_net_billthrough_outcome_ids`
- All attribution, curve, scenario, and optimisation code that reads outcome identity

## Required tests

- Distinct metric keys (`fh_gsa`, `fh_signup`, `fh_net_billthrough_count`, `dna_kit_sale`) remain distinct
- No code path treats `fh_gsa` and `fh_signup` as interchangeable
- `normalize_metric_key` maps recognised variants to the correct stable key but never maps one stable key to another

## Owner

Product / Analytics

## Affected modules

- `ancestry_mmm/core/outcomes.py`
- `ancestry_mmm/core/optimization.py`
- `ancestry_mmm/core/attribution.py`
- `ancestry_mmm/core/curve_bank.py`

## Human traceability

Derived from PRD section: Outcome Definitions; G2A.7 implementation brief section 2.4
