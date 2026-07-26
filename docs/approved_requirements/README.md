# Approved implementation requirements

This directory stores concise, repository-controlled implementation decisions derived from approved human product requirements.

Coding agents must implement from:
- the current task brief
- approved requirement records in this directory
- applicable `AGENTS.md` invariants
- existing schemas, tests, and migrations

Coding agents must not independently interpret or reconcile the external Ancestry MMM PRD.

Each requirement record should include:
- requirement ID
- status
- approved decision
- implementation scope
- owner
- approval date
- supersedes/superseded-by
- affected schemas and modules
- required tests
- human traceability reference

This directory is separate from `docs/decision_log.md`, which records engineering decisions made *during* implementation (design trade-offs, phasing, rejected alternatives). A record here captures a *business* requirement approved upstream of implementation, before any code is written against it.
