# Standard source-pack parity matrix

This document records the WP3 implementation boundary for the four logical
source domains. A workbook is physical source evidence; adoption creates only
the canonical objects named below. It does not infer approvals, calibration,
cost mappings, or model roles.

| Logical domain | Download | Upload/parser | Canonical mapping and adoption | Coverage / official preparation | Export / re-import | Explicit unsupported state |
| --- | --- | --- | --- | --- | --- | --- |
| Outcomes | `build_standard_template` produces the governed Outcomes v2 workbook | Sheet-level validation and immutable workbook/source version | Existing Outcomes v2 catalogue draft/adoption path; adopted canonical outcome frame is retained separately | Outcome definitions remain approval-gated; canonical outcome rows can enter the official native-frame path when the model proposal consumes them | `standard_outcome_data` and existing outcome catalogue/governance records are portable | Unapproved or incomplete outcome definitions remain review/blocking evidence; no default outcome is inferred |
| Activity and Media | Download includes activity identity, ownership, model-input, spend/response-unit, currency, and effective-period fields | Sheet-level validation; multiple workbooks/tables are retained under one logical domain | Existing `ActivityDefinition` is adopted at market × activity identity. Explicit source semantics are retained as evidence; `pooling_group_id` remains identity-only | Adopted wide model-input frame can feed official preparation after the normal capability and coverage gates. Existing market/channel media-unit and cost mappings remain a separate review step | `standard_activity_model_input`, `activity_definitions`, and semantic statuses are portable | Missing physical mapping fields are `adopted_with_physical_mapping_review`; no `ChannelMediaUnitConfig` or cost mapping is auto-created |
| Context and External Factors | Download includes native frequency, role, source, scope, unit, and effective-period metadata | Native-frequency tidy observations are accepted without row fabrication or conversion | Tidy native evidence is preserved in raw sources; lossless wide model-input reshape and variable metadata are adopted | Weekly native variables can enter the current official path. Mixed/non-weekly native context fails closed until an approved conversion method exists | `standard_context_data`, `context_variable_metadata`, and semantic statuses are portable | Metadata gaps are reviewable; non-weekly native frequency is `unsupported_no_approved_method` for the current official path |
| Experiment Evidence | Separate optional evidence workbook | Sheet-level validation and provenance retention | Evidence is recorded as `source_evidence_only`; no calibration registry object is created | Not consumed by standard official preparation or model fit | Raw workbook tables and semantic status are portable | No approved experiment-evidence ingestion registry exists, so no `CalibrationRecord` or fit alteration is inferred |

## Shared workflow contract

Market is a row dimension. Multiple physical workbooks can be uploaded per
domain and are merged only when their canonical period × market keys and
overlapping values are compatible; duplicate or conflicting keys fail closed.
The standard adoption state is separate from the existing physical media-unit
and cost mapping registry. The standard path therefore exposes source evidence
and a next action instead of silently translating spend, delivery, or currency
into planning economics.

The current standard path provides an exploratory outer-join frame for Model
Structure and Data Coverage. Official preparation uses the adopted canonical
frames through the WP2 native-frequency and consumed-variable gates. It does
not use dictionary/event tables as model rows, fill missingness, repeat native
observations, or convert a non-weekly source.
