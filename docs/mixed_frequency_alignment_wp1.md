# Mixed-frequency alignment: WP1 implementation record

This record is scoped to the approved implementation brief “Media-Mix-Lab:
Coding LLM Next Steps”, WP1. It does not amend the external MMM PRD or the
approved requirement authority.

## Scope and estimand

No MMM estimand, likelihood, link function, prior, posterior, or outcome
definition changes in WP1. The executor produces a governed weekly
model-input series in the source variable's own units:

| Variable class | Method | Output semantics |
| --- | --- | --- |
| `flow_count` | `calendar_overlap_allocation` v1 | Allocate a source total by inclusive calendar-day overlap; non-missing source periods reconcile exactly. |
| `stock_level` | `release_aware_locf` v1 | Carry the latest released level forward; pre-first-release weeks remain missing. |
| `rate_index` | `release_aware_locf` v1 | Carry the latest released rate/index forward; no interpolation. |
| `survey_measurement` | `release_aware_locf` v1 | Carry released measurements forward and retain observation age evidence. |
| `survey_measurement` | `native_cadence_only` v1 | Retain the native series without conversion; target and native cadence must match. |
| `event_flag` | `calendar_event_alignment` v1 | Place point events on their containing week; allocate duration events by inclusive active-day fraction. |

Method ID, method version, parameters, publication timing, support, effective
period, definition breaks, and reconciliation rule are explicit persisted
metadata. A class or source frequency never selects a default method.

## Governance and failure behaviour

The Coverage page is the review surface. Official preparation blocks on an
unknown method, method-version mismatch, missing governed parameters,
publication leakage, unresolved definition breaks, invalid source values, or
reconciliation failure. The exploratory Transform Pipeline remains separate.
Native source data is not overwritten; official conversion evidence is stored
with the preparation result and participates in the model identity path.

The current executor targets the explicitly governed weekly calendar. It is a
planning/data-preparation transformation, not a causal mediation model and
not an endorsement of any Search, capacity, censoring, or future-variable
role.

## Upstream references and compatibility

Context7 was unavailable in the coding environment. The locked dependency is
`pandas==3.0.3` (from `pyproject.toml`/`uv.lock`). The implementation used the
official pandas API documentation for period/calendar operations:

- [`pandas.PeriodIndex.start_time`](https://pandas.pydata.org/docs/reference/api/pandas.PeriodIndex.start_time.html)
- [`pandas.PeriodIndex.end_time`](https://pandas.pydata.org/docs/reference/api/pandas.PeriodIndex.end_time.html)
- [`pandas.Period`](https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.Period.html)
- [`pandas.date_range`](https://pandas.pydata.org/pandas-docs/stable/reference/api/pandas.date_range.html)

No PyMC, PyTensor, ArviZ, or PyMC-Marketing modelling API is changed or
reimplemented by this package.

## Known limitations

The methods are intentionally deterministic and narrow. They do not solve
ragged market-specific predictor mathematics, survival/maturity likelihoods,
generic interpolation, production mediation, lower-funnel censoring, or
future endogenous mediator forecasting. Those remain subject to their own
approved implementation briefs and engine-capability decisions.
