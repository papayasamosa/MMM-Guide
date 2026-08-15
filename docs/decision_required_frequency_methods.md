# Decision required: official mixed-frequency methods

Status: **partially resolved.** As of 2026-08-15 (PR #250), the narrow WP1
method catalogue below is approved and registered for official use
(`METHOD_APPROVED_BY`/`METHOD_APPROVED_AT` in
`ancestry_mmm/core/frequency_conversion.py`; full contract in
`docs/mixed_frequency_alignment_wp1.md`). A variable class or scenario outside
that narrow catalogue — a different method family, a broader ragged-window
treatment, or a policy-backed alternative — still has no approved method and
remains decision-required exactly as before.

This record implements the governance boundary requested by Work Package 6 of
`Ancestry_MMM_Coding_LLM_Next_Steps.md`. It is subordinate to
`docs/approved_requirements/REQ-COVERAGE-001.md`, which approves the typed
frequency-transformation contract but does not select a statistical method.
The candidate survey in `docs/frequency_conversion_method_options.md` is
decision support only and is not an approval.

## What is now approved (WP1 catalogue, v1)

| Variable class | Approved method | Version |
| --- | --- | --- |
| `flow_count` | `calendar_overlap_allocation` | v1 |
| `stock_level` | `release_aware_locf` | v1 |
| `rate_index` | `release_aware_locf` | v1 |
| `survey_measurement` | `release_aware_locf` | v1 |
| `survey_measurement` | `native_cadence_only` | v1 |
| `event_flag` | `calendar_event_alignment` | v1 |

Each method's parameters, publication timing, support boundary,
definition-break treatment, and leakage controls are fixed by its
implementation (`docs/mixed_frequency_alignment_wp1.md`) and are not
per-project decisions. A project still selects which approved method applies
to which variable on the Coverage review; the method is never inferred from
source frequency or column names, and official preparation still fails
closed on an unknown method, version mismatch, or unresolved definition
break.

## Decisions still required beyond the WP1 catalogue

The table below is now satisfied for the five rows in the WP1 catalogue above
by the corresponding approved method. It remains open for any variable class
usage the WP1 catalogue does not cover (a different method family for the
same class, or a class/scenario the catalogue does not address). For each
such case, Data Science / Platform engineering must choose one approved
method, or explicitly approve keeping the variable at its native cadence. The
decision must identify the method version, parameters,
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

- The conversion-method registry is no longer empty: the WP1 catalogue (six
  method/variable-class registrations) is registered and approved by default
  (`ensure_approved_frequency_methods` in
  `ancestry_mmm/core/frequency_conversion.py`).
- `core.frequency_alignment.assess_official_preparation` evaluates the
  versioned coverage and canonical-calendar contracts and, for a variable
  whose governed method is in the WP1 catalogue, executes it. Already-weekly
  native sources may use the explicit canonical weekly preparation path;
  records with a registered, approved method reach `method_available`/
  executed conversion; records outside the catalogue still return
  `unsupported_no_approved_method` (or a more specific leakage or
  definition-break blocker); missing governance still returns
  `decision_required`.
- Native source frequency and canonical missingness are preserved.
- The Transform Pipeline's generic fill operations remain available as
  explicitly exploratory operations. They are not an official alignment
  mechanism.
- A future mixed-frequency approval beyond the WP1 catalogue must add the
  corresponding registry entry, an executor, reconciliation/leakage/support/
  definition-break tests, and explicit analyst review before the official
  button can produce a converted frame for that case. It does not change the
  native-weekly path or authorize imputation.

## Owner and status

Owner: Data Science / Platform engineering.

Status: the WP1 catalogue is approved and executable; every other variable
class/method combination remains open, and no implementation may resolve
those remaining choices by inference from the external PRD, source dates, an
inner join, or a fill operation.
