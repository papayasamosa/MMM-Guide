# Net Bill-Through Transformation (PR G1)

Design record for `core.net_billthrough` - the deterministic transformation PR F's schema
(`METRIC_KEY_FH_NET_BILLTHROUGH_COUNT`, `date_basis="signup_date_attributed"`, `maturity_required`) was
built ahead of. PR F explicitly deferred this ("no bill-through cohort is actually computed" - see
`docs/media_outcome_pathways.md`'s "Explicitly out of scope"); PR G1 builds it.

## Why signup-date attribution, not event-date

`fh_gsa_finance_date` (`core.outcomes.METRIC_KEY_FH_GSA_FINANCE_DATE`) is booked on the date the
billing/finance event itself happened - a normal source-column outcome, entirely unaffected by this
module. `fh_net_billthrough_count` is booked BACK to `signup_date` instead, so it lines up on the same
axis media spend does: a signup driven by a given week's media should have its eventual bill-through
outcome attributed to that week, not to whichever later week the customer's trial happened to convert
or lapse. **These are two structurally separate metrics, never merged or treated as synonyms** - the
module never imports `core.outcomes` at all (a structural, not just documented, guarantee - see
`TestFinanceDateGsaStaysSeparate` in `test_net_billthrough.py`).

## Deterministic, not fitted or inferred

`NetBillthroughOfferRule(offer_id, market, maturity_days, description)` is analyst-configured, matching
`core.pathways.MediaOutcomePathway`'s convention of explicit config over fitted heuristics elsewhere in
this codebase. `maturity_days` is how many days after `signup_date` a cohort's eventual net bill-through
outcome (did the customer stick around past their trial/refund window) is considered determined - a
cohort younger than that has a genuinely unknown outcome, not merely an unobserved one.

```python
cohorts = compute_net_billthrough_cohorts(signups, cancellations, offer_rules, as_of_date)
# one row per (market, signup_date, offer_id): gross_signups, cancellations,
# net_billthroughs = gross_signups - cancellations (clipped at 0), maturity_days, matures_on, is_mature

series = net_billthrough_weekly_series(cohorts)
# weekly (market, week_start) -> fh_net_billthrough_count, MATURE COHORTS ONLY by default
```

`cohort_maturity_status` raises if any `(market, offer_id)` pair in the data has no matching rule -
fails closed rather than silently assuming a maturity window, since there is no safe default. A
cancellation count exceeding its own cohort's gross signups (a data/join error upstream) is clipped to
zero net bill-throughs, never a fabricated negative value.

## Immature cohorts are excluded, never zero-filled

`net_billthrough_weekly_series` drops any cohort with `is_mature=False` from the reported series by
default - not zero-filled, not extrapolated. Reporting an immature cohort as `0` (or any guessed value)
would be a fabricated number, not a deterministic transformation: the cohort's true net bill-through
outcome genuinely isn't known yet. `include_immature=True` surfaces an explicitly-labelled
provisional view (e.g. a diagnostics page visualising the still-maturing tail); it must never feed the
model or a headline report. `immature_cohort_summary` is the transparency counterpart - exactly which
cohorts got excluded and how many signups they represent, so the exclusion is visible rather than silent.

## UI

Structure page's "Net bill-through offer rules" section (below the pathway catalogue) is an
`st.data_editor` table, one row per `(market, offer_id)`, validated and persisted through the page's
existing Save handler alongside the pathway catalogue and funnel links.

## Explicitly out of scope for PR G1

No wiring into `prepare_fh_modeling_frame` or the model builders yet - `fh_net_billthrough_count` can
already be captured as an ordinary `OutcomeDefinition` (with `date_basis="signup_date_attributed"`) and
fitted like any other outcome once a caller computes its weekly series via this module and joins it into
the transformed data; this PR does not add that join step to the UI pipeline. The DNA activation
classifier, the constrained funnel model, and 0-3/3-12/full-horizon reporting windows remain future
roadmap items - this module's job is producing one correct, deterministic weekly series a future PR can
report those windows from.

## Verification

See `test_net_billthrough.py`: offer rule validation, per-market maturity windows, the required test
cases "net bill-through -> signup-date mapping" (each cohort's net bill-through lands in its own signup
week, not a later cancellation-event week) and "immature-cohort exclusion" (excluded, not zero-filled;
`include_immature=True` surfaces it explicitly; an all-immature series is empty, not an error), and
"finance-date GSA stays separate" (structural - the module has no import of `core.outcomes` at all).
