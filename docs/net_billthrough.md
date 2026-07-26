# Family History net bill-through

`fh_net_billthrough_count` is an **authoritative supplied weekly outcome** at
`week_start × market × segment`. The MMM does not reconstruct it from signup,
billing, cancellation, refund, payment-event, or offer-level records and does
not estimate maturity or right-censoring.

The canonical definition is:

- `metric_key`: `fh_net_billthrough_count`
- `aggregation_type`: `count`
- `date_basis`: `signup_date_attributed`
- `unit`: `bill-through subscriber`

## Conditional use (G2A.7, REQ-NBT-001)

NBT may be used officially only when **both** conditions are met:

1. **Definition approval**: the NBT `OutcomeDefinition` has a matching, active
   `OutcomeApproval` (`core.outcome_approval`) for the requested use; and
2. **Completeness validation**: `validate_supplied_net_billthrough` passes
   (data coverage, week anchor, market/segment completeness, non-negative
   integer-like counts).

Data completeness is a data-integrity gate, not business approval. Both are
required. Complete NBT data without an approved definition is blocked.
Approved NBT with incomplete data is blocked.

## Completeness contract

The upload retains `data_as_of_date`, `model_start_week`, `model_end_week`,
`latest_complete_net_billthrough_week`, `maturity_rule_description`,
`source_owner`, `outcome_id`, `definition_version`, and `definition_fingerprint`.
Training is blocked unless the latest complete week is at least the model
end week. Validation also rejects missing or duplicate market/segment/week
records, negative or non-integer-like counts, absent configured markets or
segments, finance-date GSA mapping, and rows after the stated model end week.

## Legacy migration

Legacy bundles without outcome approvals import with `legacy_unapproved`
status. No implicit approval is generated during migration. Old NBT metadata
records remain inspectable; official NBT use is blocked until an approved
definition and completeness validation are both present.
