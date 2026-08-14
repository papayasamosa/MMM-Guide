# Decision required: official mixed-frequency methods

Status: decision required. No concrete frequency-conversion method is approved
for official use as of 2026-08-13.

This record implements the governance boundary requested by Work Package 6 of
`Ancestry_MMM_Coding_LLM_Next_Steps.md`. It is subordinate to
`docs/approved_requirements/REQ-COVERAGE-001.md`, which approves the typed
frequency-transformation contract but does not select a statistical method.
The candidate survey in `docs/frequency_conversion_method_options.md` is
decision support only and is not an approval.

## Decisions required before official preparation

For each variable class used by a project, Data Science / Platform engineering
must choose one approved method, or explicitly approve keeping the variable at
its native cadence. The decision must identify the method version, parameters,
market scope, effective period, publication/release timing, reconciliation
rule, support boundary, definition-break treatment, leakage-safe backtest
behaviour, validation evidence, and official-use owner/approval.

| Variable class | Exact unresolved choices |
| --- | --- |
| `flow_count` | Select a conversion or native-cadence treatment; define aggregation/reconciliation, publication lag, support boundary, parameters, definition-break handling, leakage controls, and validation evidence. |
| `stock_level` | Select a conversion or native-cadence treatment; define level preservation/reconciliation, boundary behaviour, publication lag, definition-break handling, leakage controls, and validation evidence. |
| `rate_index` | Select a conversion or native-cadence treatment; define weighting/aggregation, support boundary, publication lag, definition-break handling, leakage controls, and validation evidence. |
| `survey_measurement` | Select native cadence, step repetition, or another governed treatment; define release timing, uncertainty, support boundary, methodology-break handling, leakage controls, and validation evidence. |
| `event_flag` | Select full-period overlap, exact-date sub-period, native cadence, or another governed treatment; define event-boundary semantics, publication timing, definition-break handling, and validation evidence. |

## Current product behaviour

- The conversion-method registry remains empty. No interpolation, allocation,
  forward-fill, or other method is registered or defaulted for official use.
- `core.frequency_alignment.assess_official_preparation` evaluates the
  versioned coverage and canonical-calendar contracts without modifying a
  DataFrame. Already-weekly native sources may use the explicit canonical
  weekly preparation path; mixed-frequency records return
  `unsupported_no_approved_method` (or a more specific leakage or
  definition-break blocker), and missing governance returns
  `decision_required`.
- Native source frequency and canonical missingness are preserved.
- The Transform Pipeline's generic fill operations remain available as
  explicitly exploratory operations. They are not an official alignment
  mechanism.
- A future mixed-frequency approval must add the corresponding registry entry,
  an executor, reconciliation/leakage/support/definition-break tests, and
  explicit analyst review before the official button can produce a converted
  frame. It does not change the native-weekly path or authorize imputation.

## Owner and status

Owner: Data Science / Platform engineering.

Status: open; no implementation may resolve these choices by inference from
the external PRD, source dates, an inner join, or a fill operation.
