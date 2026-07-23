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

## Completeness contract

The upload retains `data_as_of_date`, `model_start_week`, `model_end_week`,
`latest_complete_net_billthrough_week`, `maturity_rule_description`, and
`source_owner`. Training is blocked unless the latest complete week is at
least the model end week. Validation also rejects missing or duplicate
market/segment/week records, negative or non-integer-like counts, absent
configured markets or segments, finance-date GSA mapping, and rows after the
stated model end week.
