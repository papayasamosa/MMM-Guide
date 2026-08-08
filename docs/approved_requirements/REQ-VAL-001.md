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

PR 82D: the governance evidence chain (``validation_policy``,
``diagnostics_artefact``, ``validation_results``, ``approval_readiness``)
now round-trips through the project export/import bundle
(``core/persistence.py``, ``application/project_service.py``,
``pages/09_Project_Export.py``). The policy and diagnostics artefact are
restored as-is on import (they remain valid evidence on their own); the
readiness proof binding them to a specific model identity is only restored
if ``application.project_service.verify_imported_readiness`` confirms it
still matches the imported policy, diagnostics artefact, and reconstructed
model identity fingerprints - never trusted blindly, mirroring how
``core.persistence.verify_imported_approval`` already treats an imported
``model_approval``.

UK-pilot evidence expansion (schema v3): ``DiagnosticsArtefact`` gained two
additive evidence sections, computed once by ``DiagnosticsService.evaluate``
alongside the existing seven and rendered by the Diagnostics page from the
canonical artefact only (never a separate recomputation) -

- ``error_metrics`` (``core.diagnostics.error_metrics_by_outcome`` /
  ``core.market_specific_diagnostics.error_metrics_by_outcome_market_specific``):
  MAE, RMSE, sMAPE, WAPE and bias per outcome_id, alongside the existing
  R-squared/MAPE in ``in_sample_fit`` - sMAPE/WAPE close MAPE's
  divide-by-zero and volume-weighting blind spots respectively; bias
  surfaces systematic over/under-prediction that MAE/RMSE (which fold
  errors to magnitude) cannot.
- ``residual_diagnostics`` (``core.diagnostics.residual_temporal_diagnostics``
  / the market-specific equivalent): lag-1 autocorrelation coefficient and
  the Durbin-Watson statistic on the fit's residuals per outcome_id -
  evidence of unexplained temporal structure (under-fit carryover/trend/
  seasonality). No blocking threshold is introduced by either section -
  REQ-VAL-001's "evidence computation and approval policy are separate" is
  unchanged; an approved policy decides thresholds later.

Schema v2 artefacts upgrade to v3 with both new sections ``not_computed``
(the evidence did not exist yet when they were computed) - this is
deliberately *not* the same as ``legacy_incomplete`` (reserved for schema
v1, which silently dropped evidence it claimed to have): a v2 artefact
remains fully valid ``official_canonical`` evidence for the seven sections
it always had, since ``ValidationService`` gates on ``schema_version >= 2``,
not ``== 2``.

Work Package 2 corrective fix: `residual_diagnostics`'s underlying
calculation (`core.diagnostics.residual_temporal_diagnostics` / the
market-specific equivalent) originally computed lag-1 autocorrelation/
Durbin-Watson on the full, multi-market-concatenated residual vector per
outcome_id - since the model frame stacks every market's rows together,
this formed an invalid lag pair between one market's last observation and a
different market's first observation. It now computes within each market's
own chronological slice (`frame["market_bounds"]`) and reports one row per
market x outcome_id, never across a market boundary. `DiagnosticsArtefact.
schema_version` is unchanged (still 3 - the section's serialized shape is
still a list of JSON-safe records); `DiagnosticsService.evaluate()` now
stamps newly-computed artefacts with `diagnostics_version "3.1.0"` (bumped
from `"3.0.0"`) to record the calculation change - an already-persisted
`"3.0.0"` artefact remains loadable exactly as computed, its outcome-only
residual rows never silently reinterpreted as market-safe evidence. Also
closed in the same corrective PR: `DiagnosticsArtefact.from_dict`'s
`schema_version` dispatch used plain `==`/`in` equality, which let a `bool`
(`True == 1`) or a numerically-equal `float` (`2.0 in (2, 3)`) silently
masquerade as a genuine integer schema version - now validated strictly.

Not yet implemented (explicitly deferred, not silently dropped): prior
predictive checks, prior-versus-posterior comparison summaries, and
predictive log-density. Each requires building and sampling from the actual
PyMC model specification independently of an already-fitted trace (prior
predictive: ``pm.sample_prior_predictive`` against
``core.hierarchical_model``/``core.market_specific_model``'s model-building
functions; predictive log-density: ArviZ ``psis-loo``/``waic`` against the
posterior's log-likelihood) - a materially larger integration than the
purely-deterministic (actual, predicted)/residual-array evidence above, and
one this record's audit judged should not be bundled into the same PR as
that evidence without its own scoped review (sampling cost/determinism in
CI, and the PyMC model-builder surface these would touch is large and
sensitive). A dependent PR should close this gap as its own scoped package.

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
- ``ancestry_mmm/core/persistence.py`` (export/import the evidence chain)
- ``ancestry_mmm/application/project_service.py`` (verify imported readiness)
- ``ancestry_mmm/pages/09_Project_Export.py`` (wire export/import restoration)

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
- A project bundle's governance evidence chain round-trips through export
  and import; an imported readiness is restored only when it still matches
  the imported policy, diagnostics artefact, and reconstructed model
  identity (PR 82D).

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
