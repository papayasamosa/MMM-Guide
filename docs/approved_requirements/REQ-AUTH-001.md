# REQ-AUTH-001: Implementation requirements authority

**Status:** approved for implementation  
**Decision date:** 2026-07-26  

## Decision

Coding agents implement from:

1. task-specific approved implementation briefs
2. repository-controlled approved requirement records (this directory)
3. applicable `AGENTS.md` invariants
4. existing schemas, tests, migrations and documented code contracts

The external Ancestry MMM PRD is human traceability material, not a document a coding agent independently reconciles, interprets, amends or supersedes.

## Scope

- Root `AGENTS.md` requirements-authority section
- `docs/approved_requirements/README.md`
- All coding agent workflows in this repository

## Required tests

- A repository test confirms root `AGENTS.md` and `docs/approved_requirements/README.md` authority wording is consistent
- No source says that applicable `AGENTS.md` invariants are forbidden while also ranking them as authoritative

## Owner

Platform engineering / repo governance

## Affected modules

- `AGENTS.md` (root)
- `docs/approved_requirements/README.md`

## Human traceability

Derived from PRD section: Implementation Governance; G2A.7 implementation brief section 2.1
