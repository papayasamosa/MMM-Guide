# REQ-ACTIVITY-001: Governed Activity Taxonomy

## PRD source

Task-specific implementation brief, `Ancestry_MMM_Coding_LLM_Next_Steps.md`,
Work Package 1 (2026-08-13).

This record translates the approved Work Package 1 taxonomy scope into
repository authority. It does not reinterpret the external Ancestry MMM PRD
or change the model equations.

## Capability status

Approved for implementation. Work Package 1 adds explicit activity
classification and backward-compatible persistence to the existing
`core.activities.ActivityDefinition` domain.

## Requirement

### 1. Canonical identity and reporting dimensions

- `activity_id` remains the canonical business identity at market x activity
  grain; it is not a source-column name.
- `pooling_group_id` remains an optional cross-market identity only. Its
  presence must not force, imply, or default to statistical parameter pooling.
- `channel` remains a reporting-family roll-up. It is not the fitted predictor
  identity, and several governed activities may share one channel.
- `platform`, `campaign_type`, `product_advertised`, and `message_type` remain
  separate descriptive dimensions.
- `marketing_objective` is an optional normalized string describing intended
  business purpose. It is separate from campaign type and message type and is
  never inferred from names, platform, or source columns.

### 2. Funnel classification

`funnel_stage` is a governed, descriptive reporting field with this closed
stored vocabulary:

- `brand_upper`
- `mid_funnel`
- `performance_lower`
- `cross_funnel`
- `not_applicable`
- `unclassified`

The value `unclassified` is the explicit migration/default state for legacy
payloads and draft records. Funnel stage is never inferred from channel,
platform, campaign type, message type, metric, or column name.

Funnel stage does not create causal graph edges, mediators, priors,
coefficients, model roles, planning eligibility, or optimisation permission.
An activity must be explicitly classified before it is used in an official
funnel-layer report.

### 3. Migration and persistence

- The activity schema version increments for the new fields.
- A legacy payload missing `funnel_stage` receives `unclassified`.
- A legacy payload missing `marketing_objective` receives the empty string.
- Existing values are preserved; no classification is guessed.
- Both fields survive `to_dict`/`from_dict` and project export/import.

### 4. Fingerprinting and invalidation

`activity_fit_fingerprint` remains limited to fit-relevant identity, role,
physical model input, and pathway structure. Funnel stage, marketing
objective, channel, platform, campaign type, message type, and other reporting
taxonomy fields do not become fit-relevant merely because they are displayed
or grouped.

Where grouped reporting needs reproducibility, it uses a separate
`activity_reporting_fingerprint` rather than expanding the hard
fit/curve/scenario fingerprint. Editing only funnel stage or marketing
objective therefore does not force a model refit.

## Out of scope

- Model equation changes, causal inference, mediation, graph-edge creation,
  adstock or saturation selection.
- Replacing `ModelSpec.channels` or changing model-structure selection (Work
  Package 2).
- Funnel-aware attribution aggregation (Work Package 4).
- Automatic classification or a globally closed marketing-objective enum.

## Affected modules

- `ancestry_mmm/core/activities.py`
- `ancestry_mmm/pages/10_Channel_Media_Units.py`
- `ancestry_mmm/utils/display.py`
- `ancestry_mmm/tests/test_activities.py`
- `ancestry_mmm/tests/test_channel_media_units_pooling_group_id_apptest.py`

## Required tests

- Legacy payload migration defaults to `unclassified` and empty objective
  without guessing.
- Funnel vocabulary validation rejects unknown values.
- Taxonomy fields round-trip through the activity record.
- Reporting fingerprint changes when taxonomy changes, while fit and hard
  curve/scenario fingerprints do not.
- Meta activities can share `channel="Paid Social"` and `platform="Meta"`
  while retaining distinct activity IDs and funnel stages.
- CRM activities can share `channel="CRM"` while retaining distinct campaign,
  message, objective, and funnel classifications.
- The Media Mapping editor exposes editable funnel stage, objective, and
  `pooling_group_id` without losing existing values.

## Migration impact

Existing activity bundles remain readable. Missing taxonomy fields receive
only the explicit defaults above. No fitted model, causal graph, or planning
permission is changed by migration.

## Owner

Data Science / Platform engineering.

## Approval date

2026-08-13
