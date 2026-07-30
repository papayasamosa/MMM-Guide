# REQ-VAL-001: Validation Policy and Approval Readiness

## PRD source

PRD v1.4, Validation and Approval sections. Model approval must be gated by
a governed, policy-driven validation gate — not a manual acknowledgement.

## Capability status

Foundation implemented. Domain objects (ThresholdPolicy, ValidationGate,
ValidationResult, ApprovalReadiness, ValidationWaiverReference) exist in
``core/validation_policy.py``. The evaluator (``evaluate_approval_readiness``)
implements explicit pass/review/fail bands with versioned policies. The
evaluator registry (PR 56E) uses a typed, pluggable pattern in
``core/validation_policy.py`` with registered evaluators for R-hat, ESS,
divergences, and PPC coverage. Fallback thresholds have been removed in favour
of policy-supplied thresholds. ``require_matching_approval`` (PR 56C) verifies
policy and readiness fingerprint binding. The DiagnosticsService (PR 56F,
extended PR 82B to also compute identification/coefficient-stability
evidence) produces a fingerprinted DiagnosticsArtefact. Validation and
readiness are displayed via the Diagnostics page.

PR 79A/PR 82B: new official (policy-backed) model approvals require active
policy binding - ``create_policy_backed_model_approval`` is the only
approval-creation path used by the Diagnostics page, and it rejects an
inactive policy, a readiness that is not ``overall_ready``, or any
fingerprint mismatch between the policy, the readiness, and the current
model identity. ``ValidationService``'s ``official_canonical`` evidence mode
(PR 82B) additionally guarantees that a policy-backed approval's readiness
was evaluated entirely from the canonical diagnostics artefact - it never
falls back to a live recomputation for a metric the artefact lacks. This
resolves the "optionally reference a policy" language below in favour of a
firm requirement for anything created going forward.

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
- Official (``official_canonical``) evidence mode fails a gate closed when
  its metric is missing from an otherwise-valid artefact, rather than
  recomputing it live (PR 82B).
- A policy, model-identity, or diagnostics-artefact fingerprint change
  invalidates a previously evaluated readiness and any approval bound to it
  (PR 82B).

## Migration impact

Legacy approvals created before policy binding was required (empty
``validation_policy_id``) remain loadable and are still matched against the
current model by ``require_matching_approval`` on identity alone - they are
not deleted or silently rejected. They are not, however, treated as
equivalent to a current policy-backed approval: they carry no policy or
readiness fingerprint proof, so nothing downstream can verify what evidence
(if any) they were granted against. Forward: every new official approval
must reference an active policy and a matching, ``overall_ready`` readiness
- there is no unbound approval path for newly created approvals.

## Unresolved decisions

- Default policy thresholds: these will be suggested but must be approved by
  the modelling lead before becoming authoritative.
- Whether/how a legacy unbound approval can be "upgraded" to policy-backed
  status without a full re-approval (currently: it cannot - re-approval
  through the policy-backed path is required to gain fingerprint proof).

## Owner

Modelling

## Approval date

2026-07-28
