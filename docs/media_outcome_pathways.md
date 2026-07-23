# Media–outcome pathway contract

`core.pathways` is the single calculation and governance contract for media
pathways. Both PyMC builders, NumPy replay, attribution, curves, and planning
consume the same `ResolvedPathwayComponent` collection.

## Components

A `(channel, target_outcome_id)` pair may contain more than one component:

- `direct`: an undelayed primary effect using the model's hierarchical
  `beta[outcome, channel]` prior.
- `cross_product`: an active or exploratory delayed effect. `prior_scale`
  is operational here only: it is the sigma of the component's HalfNormal
  pathway-strength prior.
- `mediated`: diagnostic governance metadata only. It does not enter the
  standard MMM likelihood and cannot be used for planning or headlines.
- `excluded`: an explicit zero-effect governance record.

The natural key is `(channel, target_outcome_id, component_type)`, so direct
and delayed components can coexist without overwriting each other.

Each fitted component has its own lag, prior semantics, attribution
eligibility, planning eligibility, evidence status, and headline decision.
Cross-product lags are applied independently after ordinary channel adstock;
they are not one shared global delay.

## Reporting governance

Evidence and approval are deliberately separate:

```text
evidence_status
include_in_attribution
include_in_planning
include_in_headline
headline_approval_status
headline_approval_note
approved_by
approved_at
```

`model_supported` or `experiment_supported` does not automatically make a
component suitable for executive reporting. Headline output requires
`include_in_headline=True`, `headline_approval_status="approved"`, and an
auditable reviewer and timestamp/reference. A headline component must also
be attribution-visible.

Mediated and excluded components are never planning- or headline-eligible.
Exploratory cross-product planning requires the existing explicit planning
confirmation.

## Resolution and compatibility

`resolve_pathway_masks` materialises explicit catalogue rows and legacy
defaults into an authoritative component collection. The older fields

```text
primary_channels_by_outcome
active_channels_by_outcome
exploratory_channels_by_outcome
lag_weeks_by_cell
prior_scale_by_cell
planning_by_cell
```

remain in persisted metadata only as deterministic compatibility caches.
They are regenerated from components, exposed as read-only compatibility
views, and cannot be reassigned independently. Bundle import rejects a
component collection whose supplied caches disagree with it.

All operational lag and prior lookups use the stable component key
`(outcome_id, channel, component_type)`. Index-based lookup remains only as
a compatibility wrapper and requires the caller's explicit model
`outcome_ids` and `channels`; component-list order is never treated as model
coordinate order.

Bundles written before component/headline fields existed are migrated:
component type is inferred from role, unused direct/excluded prior scales are
removed, and the old evidence-derived headline result is captured as an
explicit legacy-migration approval rather than continuing to infer it.

Older mask-only model metadata is stricter. Its masks are materialised as
explicit fitted components and analyst attribution is preserved, but the
project is marked `legacy_governance_mode`. Headline and planning output are
blocked until an analyst reviews and re-saves an explicit pathway catalogue.
The resolved metadata and resumability audit both retain a migration report.

## Validation sequence

Pathways are validated twice:

1. during frame preparation, before NBT long-to-wide reshaping or other
   aggregation, with channel ownership, outcome ownership, fitted outcomes,
   and diagnostic-only outcomes;
2. immediately before either PyMC model is constructed, with the same full
   context.

The resolved-component preview on the Structure page shows the exact
equation term and fit/attribution/headline/planning decisions that downstream
calculations will use.

The pathway grid keeps component-specific fields read-only and exposes them
through a row selector. `prior_scale` is enabled only for `cross_product`
components and controls the HalfNormal sigma for that component's
`pathway_strength` multiplier. Planning and headline controls are disabled
for mediated and excluded components; mediated rows are labelled
diagnostic-only.

## Scope boundary

Diagnostic Brand Search reallocation and the OLS mediation prototype are not
production causal mediation. A genuine mediation likelihood is future work.
Until it exists, `mediated` pathway records remain outside fitting, planning,
and headline reporting.
