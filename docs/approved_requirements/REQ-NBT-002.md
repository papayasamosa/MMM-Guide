# REQ-NBT-002: Initial UK supplied NBT historical-test authority

**Status:** approved for implementation
**Decision date:** 2026-08-22
**Scope:** bounded UK historical test only; not a production-programme window approval

## Decision

The current bounded UK historical test is an NBT model, not a GSA model. GSA
and Net Bill Through remain separate governed outcomes. The supplied weekly
Net Bill Through source pack is the authoritative fact source for this test.

The fitted Family History outcomes are:

```text
fh_net_billthrough_count_new
fh_net_billthrough_count_dna_cross_sell
fh_net_billthrough_count_winback
```

The source grain is week × market × Family History segment. The outcome date
basis is the original signup date / signup-cohort attribution and the unit is
qualifying bill-through subscribers.

## Approved completeness and offer treatment

The current test uses a 14-day cohort completeness horizon. This is a
completeness rule, not an assertion that every qualifying event occurs exactly
14 days after signup. For a supplied weekly feed, the latest complete NBT week
must be at or after the model end week; the MMM does not reconstruct
customer-level maturity when the authoritative feed satisfies this contract.

Free trials count only when they subsequently reach the qualifying bill-through
event, attributed back to the original signup date. Hard or immediate paid
offers qualify from signup when the qualifying condition is met immediately.
Non-bill-through trials, failed qualifying payments and source-defined
reversed/non-qualifying records are excluded. Refunds/chargebacks remain
excluded where the supplied source definition excludes them. Modelling code
must not invent customer-level exclusion logic.

## Source, ownership and provenance

The source owner/reconciliation authority for this historical exercise is
**Ancestry Marketing Data Science / Marketing Measurement**. The exact physical
source version, checksum, `data_as_of_date`, `latest_complete_net_billthrough_week`,
`model_end_week`, `definition_version` and `definition_fingerprint` must be
persisted with each run. The current supplied source pack, rather than an
invented source-system name, is the source lineage authority.

## Identity and compatibility

The canonical semantic identities are the three `fh_net_billthrough_count_*`
IDs above. Historical `fh_gsa_*` IDs may survive only as explicit migration
aliases for backwards compatibility. They must not surface as current NBT
labels, reporting semantics or business identities. A genuine GSA definition
with a legacy identifier must fail closed rather than be relabelled.

## Boundaries

This record does not approve the wider PRD production-programme window of
2023-07-03 through 2026-06-28, any production reporting/planning/optimisation
use, or a universal NBT-to-GSA conversion. It complements `REQ-NBT-001` and
`REQ-OUT-001`/`REQ-OUT-002`; completeness and use-specific approval remain
separate gates.

## Affected modules

- `ancestry_mmm/core/outcomes.py`
- `ancestry_mmm/core/net_billthrough.py`
- `ancestry_mmm/core/outcome_approval.py`
- `scripts/run_uk_production_fit.py`
- `docs/decision_log.md`

## Required tests

- Canonical NBT IDs are used in the current historical-fit report.
- Legacy `fh_gsa_*` aliases migrate only when semantic NBT metadata matches.
- A genuine GSA definition with a legacy ID is rejected.
- The 14-day completeness record binds to the run’s model end week.
- Raw source columns remain unchanged.

## Human traceability

Derived from `Ancestry_MMM_Analyst_Decisions_Response_2026-08-22.md`, sections
1 and 4, and the approved UK source dictionary.
