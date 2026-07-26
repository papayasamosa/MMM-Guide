# Approved implementation requirements

This directory stores concise, repository-controlled implementation decisions derived from approved human product requirements. Each record captures a *business* requirement approved upstream of implementation, before any code is written against it.

This directory is separate from `docs/decision_log.md`, which records engineering decisions made *during* implementation (design trade-offs, phasing, rejected alternatives).

## Authority

Coding agents must implement from:

1. the current task-specific implementation brief
2. approved requirement records in this directory (see `index.json`)
3. applicable `AGENTS.md` invariants
4. existing schemas, tests, migrations and documented code contracts

Coding agents must not independently interpret or reconcile the external Ancestry MMM PRD.

## How to use

- `index.json` is the machine-readable registry of all current approved requirements
- Each `REQ-*.md` file contains the full decision, scope, affected modules, required tests, and human traceability reference
- A record may approve a *blocking invariant* (e.g. "NBT must not be a default") without yet approving the underlying business value (the final NBT event definition)
- Tests that enforce business-critical invariants must cite one or more requirement IDs in their docstring

## Status vocabulary

| Status | Meaning |
|---|---|
| `draft` | Under review, not yet approved for implementation |
| `approved_for_implementation` | Approved and ready for coding work |
| `superseded` | Replaced by a newer requirement record |
| `deprecated` | No longer applicable |

## Requirement ID convention

`REQ-{CATEGORY}-{NUMBER}`, e.g.:

- `REQ-AUTH-*` — requirements authority and governance
- `REQ-OUT-*` — outcome definitions and governance
- `REQ-NBT-*` — net bill-through
- `REQ-PLAN-*` — scenario planning and optimisation
- `REQ-USE-*` — official versus exploratory use
- `REQ-STALE-*` — staleness and invalidation
