# G2A.5 scenario governance and mixed economics

Status: implemented and locally verified on 2026-07-24.

## Decision contract

Every official scenario answers an incremental question: what outcome or value
does the candidate plan add relative to its stored counterfactual? The
authoritative `PlanningObjective` records:

- the estimand (`incremental_outcome` or `incremental_value`);
- the metric and optional outcome scope;
- the spend and activity scopes;
- the currency for value objectives;
- the fingerprint of the counterfactual policy used to evaluate it.

Legacy objective strings are migrated when old project bundles are imported.
New planner flows always create the typed objective. The unimplemented
`marginal_incremental_value` label is rejected rather than presented as a
false analytical capability.

## Counterfactual policy

`CounterfactualPolicy` is resolved to a complete model-input vector for every
period and persisted with its fingerprint. The default policy:

- sets optimisable intervention activity to zero;
- holds fixed and scenario-only activity at the candidate-plan level;
- holds mediators, controls, and events;
- requires an explicit choice for demand-capture activity.

The planner exposes that demand-capture choice. A policy that requests an
explicit value fails closed if a value is absent.

## Scenario inputs

`ScenarioPlan` separates:

- `monetary_decisions_by_period` for cost-bearing activity; and
- `activity_quantity_assumptions_by_period` for response-only or
  non-applicable activity.

Only monetary decisions are converted through approved, effective cost
mappings. A missing mapping blocks the affected monetary activity, but never
blocks an unrelated response-only quantity. The resolved model-input plan,
mapping evidence, coverage status, and fingerprints are stored with the
scenario.

## Activity grain and approvals

The required activity register operates at market × activity grain. It records
channel, platform, campaign type, advertised product, message type, fitted
model-input column, pathway links, causal role, economic treatment, planning
eligibility, evidence, limitations, approval metadata, change history, and
supersession.

Multiple activities may share a reporting channel when their activity IDs and
model-input columns differ. Market-specific definitions override global
definitions. Model approval is blocked or invalidated when required activity
governance is incomplete.

Activity changes invalidate downstream state according to the stored matrix:

| Change | Refit | Curves | Economics | Scenarios |
|---|---:|---:|---:|---:|
| Model role, fitted input, or pathway link | yes | yes | yes | yes |
| Ownership | no | yes | yes | yes |
| Economic treatment | no | yes | yes | yes |
| Planning eligibility | no | no | no | yes |
| Descriptive or approval metadata | no | no | no | no |

## Mixed-plan economics

Evaluation reports incremental response separately for all activity,
cost-bearing activity, and response-only activity. Paid-media CPA, net
bill-through CPA, and ROI retain the paid spend numerator in a mixed plan;
response-only quantity is never added to spend.

Whole-plan economics are emitted only when the configured cost scope supports
them. Each result carries structured coverage including covered and excluded
activities, mapping IDs and effective dates, value/currency coverage, and
counterfactual scope.

## Posterior decision uncertainty

Scenario re-evaluation preserves draw identity (`chain_index`, `draw_index`)
and returns raw draw-level results plus mean, median, credible intervals, and
probability of positive incremental response. Candidate-versus-current
probability uses paired draws, so both plans are judged under the same
posterior state.

The optimizer's point search is still SLSQP-based. The candidate it produces
is therefore re-evaluated across posterior draws rather than described as a
fully Bayesian optimizer. Dynamic horizons, year-on-year reporting, and
time-varying optimization remain outside G2A.5.
