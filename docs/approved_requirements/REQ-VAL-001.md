# REQ-VAL-001: Validation Policy and Approval Readiness

## PRD source

PRD v1.4, Validation and Approval sections. Model approval must be gated by
a governed, policy-driven validation gate — not a manual acknowledgement.

## Capability status

Not yet implemented.

## Requirement

### 1. Policy objects

Introduce versioned validation-policy domain objects:

- ``ThresholdPolicy``: a named, versioned set of validation gates.
- ``ValidationGate``: a single gate with a name, scope, acceptable range/status,
  blocking flag, and optional waiver reference.
- ``ValidationResult``: the outcome of evaluating a gate against a fitted model.
- ``ApprovalReadiness``: an aggregate of all gate results under a policy,
  identifying blockers, review items, and passes.
- ``ValidationWaiverReference``: an approved exception to a gate.

### 2. Policy must support

- ``scope``: what the policy applies to (e.g. model type, market).
- ``version``: semantic version string.
- ``pass``, ``review``, ``fail`` bands with thresholds.
- ``blocking`` flag: a failing blocking gate blocks official approval.
- ``owner``: who owns/maintains the policy.
- ``approval_date``: when the policy was approved.
- ``expiry``: optional expiry date.
- ``supersession``: optional reference to a newer policy that replaces this one.

### 3. Readiness evaluator

A pure function ``evaluate_approval_readiness(validation_results, policy)``
that:

- consumes a list of ``ValidationResult`` objects and a ``ThresholdPolicy``;
- returns an ``ApprovalReadiness`` with lists of blockers, review items, and
  passes;
- does **not** choose thresholds itself — it applies the policy it is given;
- does **not** mutate approvals.

### 4. Integration

- Diagnostics UI displays readiness separately from raw metrics.
- Official planning approval is blocked when a configured blocking gate fails
  or is missing.
- Not every warning is made blocking.
- A free-text note cannot override a non-waivable gate.

### 5. Exploratory mode

Exploratory model review remains available and visibly labelled. Exploratory
use is not blocked by validation-policy gates (but is still subject to
existing governance rules such as outcome approval).

## Affected modules

- ``ancestry_mmm/core/validation_policy.py`` (new)
- ``ancestry_mmm/core/approval.py`` (extend)
- ``ancestry_mmm/core/diagnostics.py`` (extend)
- ``ancestry_mmm/core/optimization.py`` (import readiness check)
- ``ancestry_mmm/pages/06_Diagnostics.py`` (display readiness)
- ``ancestry_mmm/pages/07_Results_Curve_Bank.py`` (approval gate update)

## Required tests

- Missing required gate blocks official approval.
- Failed blocking gate blocks official approval.
- Review-only gate does not block but is reported.
- Expired policy blocks.
- Stale validation artefact blocks.
- Approved waiver unblocks.
- Non-waivable failure still blocks after waiver attempt.
- Matching successful readiness passes.

## Migration impact

None. Existing approvals remain valid (they were created without policy
binding). Forward: new approvals should optionally reference a policy ID.

## Unresolved decisions

- Whether to require policy binding for all new approvals immediately or only
  when explicitly configured.
- Default policy thresholds: these will be suggested but must be approved by
  the modelling lead before becoming authoritative.

## Owner

Modelling

## Approval date

2026-07-28
