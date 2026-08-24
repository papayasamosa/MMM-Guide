# REQ-PREFIT-001: Mandatory pre-fit gate for official production submission

**Status:** approved for implementation
**Decision date:** 2026-08-22
**Scope:** official production-fit submission; the current bounded historical test may remain explicitly non-production while this capability is reconciled

## Decision

The latest PRD pre-fit workflow is a mandatory gate for official production
submission. It is separate from posterior validation and must not be represented
by relabelling ordinary prior-predictive or post-fit diagnostics.

The governed workflow is:

```text
candidate specification
-> static readiness checks
-> deterministic pre-fit diagnostics
-> analyst review
-> prior predictive checks
-> optional short/approximate probabilistic screening
-> full production PyMC posterior
-> post-fit validation
```

The states are exactly `ready`, `review_recommended` and `blocked`:

- `ready` permits production submission subject to later gates;
- `review_recommended` permits submission only with retained analyst review and rationale;
- `blocked` disables submission until corrected and rerun.

## Required evidence contract

Each pre-fit run must bind:

- exact candidate-specification, prepared-frame, causal-graph and transformation fingerprints;
- leakage-safe folds;
- baseline/context-only and baseline/context-plus-media surrogates;
- Ridge, Elastic Net or another approved equivalent;
- transformation-aware media screening;
- bounded coarse adstock/saturation screening;
- feature/channel and transformation stability;
- residual/autocorrelation screening;
- future-to-past timing refutation where applicable;
- retained analyst review/rationale;
- staleness after a fit-relevant change;
- same-sample-prior safeguards.

Pre-fit results are preparation evidence only. They are not official
attribution, CPA/ROI, response curves, planning or optimisation approval, and
passing them does not imply posterior validation.

## Historical-test exception

The 2023-01-01 through 2025-04-06 common-window exercise is explicitly
`historical_test` / `non_production`. It may continue using the existing static
readiness checks, prior predictive checks, identification diagnostics and short
MCMC convergence screening. That continuation must not be labelled as
satisfying the full official pre-fit workflow or promoted to official
production use.

## Affected modules

- `ancestry_mmm/core/`
- `ancestry_mmm/application/`
- `ancestry_mmm/pages/`
- persistence, model-submission and diagnostics contracts

## Required tests

- All required fingerprints are present and staleness invalidates submission.
- Leakage-safe folds and both surrogate baselines are recorded.
- The three-state gate is fail-closed.
- `review_recommended` requires retained analyst rationale.
- Pre-fit evidence cannot create official attribution/CPA/ROI/curve/planning approval.
- The historical-test exception is visibly non-production.

## Human traceability

Derived from `Ancestry_MMM_Analyst_Decisions_Response_2026-08-22.md`, section 3,
and PRD Parts 3 v1.12, 7 v1.9, 10 v1.7 and 11 v1.7.
