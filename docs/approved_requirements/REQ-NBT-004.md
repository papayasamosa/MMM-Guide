# REQ-NBT-004: Current UK production Family History KPI authority

**Status:** approved for implementation
**Decision date:** 2026-09-04
**Scope:** current UK production onboarding and fitting

## Decision

For the current UK production scope, the official Family History KPI is the
supplied canonical Net Bill Through (NBT) source pack, represented by these
separate versioned outcome IDs:

```text
fh_net_billthrough_count_new
fh_net_billthrough_count_dna_cross_sell
fh_net_billthrough_count_winback
```

The three outcomes remain separate fits and separate reporting units. Totals,
where needed, are derived from draw-level segment outcomes. GSA is a distinct
secondary/context measure and must not be relabelled, reconstructed, or
converted into NBT (or vice versa).

## Production evidence boundary

Production completeness, maturity, exclusions, reconciliation source, and
data-as-of status must come from the supplied source metadata and its approved
definition version. The historical-test 14-day completeness rule in
`REQ-NBT-002` must not be silently applied as a production assumption.

No production fit is authorised until the supplied NBT source pack and its
versioned evidence are present. This decision does not make NBT a global
default for unrelated projects or outcome registries; each fit still selects
explicit approved outcome definitions.

## Affected modules

- `ancestry_mmm/core/outcomes.py`
- `ancestry_mmm/core/net_billthrough.py`
- `ancestry_mmm/pages/03_Structure_Segments_Markets.py`
- `ancestry_mmm/pages/05_Model_Training.py`
- `ancestry_mmm/pages/08_Scenario_Planner.py`
- `docs/decision_log.md`

## Required tests

- The three canonical NBT IDs remain distinct and are not aliases for GSA.
- The current UK UI identifies supplied NBT as the production authority while
  keeping GSA separate.
- The historical 14-day rule is not presented as a production default.

## Human traceability

Derived from `Coding_LLM_Instructions_UK_Production_Decisions_and_Durable_Fit.md`,
Work Package 2, and reconciled with `REQ-NBT-002` (historical test only).
