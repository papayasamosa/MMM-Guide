# Governed FX contract implementation decision record (Decision 13 build-out)

## Why this record exists, and its explicit scope boundary

`REQ-FX-001` through `REQ-FX-006` approve the *architecture* of governed
multi-currency FX handling (currency-concept separation, rate records/
sets, historical conversion methods, provider-adapter pattern, future
assumptions, and reporting/decomposition), each explicitly "target-state
contract only... zero implementation," with every concrete
business/operational choice reserved to Finance via
`docs/wp7_governed_fx_finance_decision_package.md`. The user's
2026-08-29 business-decision brief, confirmed in-session 2026-08-30, is
explicit and unambiguous about the boundary this record must respect:

> "Proceed with the FX contract, validation, upload/input mechanism,
> versioning, Finance constant-dollar mode, optional market-rate
> architecture, and all code/tests that do not require the real rates.
> However, do not invent the Finance exchange-rate values or claim
> official Finance sign-off. The actual annual currency-to-USD rate
> table remains an external business input that I will need to
> provide."

This record and its implementation build the approved ARCHITECTURE in
code - data structures, validation, a manual-upload provider adapter,
conversion computations, and reporting contracts - for all six REQ-FX
records. It invents **zero** actual exchange rates, currency mappings,
or provider selections, and claims **no** Finance sign-off anywhere. It
also does not resolve any item on `docs/wp7_governed_fx_finance_
decision_package.md`'s own "Open questions" list beyond what Decision
13's existing 2026-08-30 addenda (to `REQ-FX-002`/`REQ-FX-003`) already
resolved in Phase A - those business questions remain genuinely
Finance-owned, unchanged by this record.

## What is implemented, per REQ-FX record

### REQ-FX-001 (currency-concept separation and canonical monetary record)

`ancestry_mmm/core/fx_currency.py`: `MonetaryObservation` - the four
distinct currency roles (transaction/market/group/model), original
amount never overwritten (each conversion is a separately named,
nullable field), Python `Decimal` for persisted amounts (Requirement 4 -
"exact decimal arithmetic, not binary floating point... a float
conversion may occur only at the numerical-model boundary"), and the
three FX-rate-identifier fields (`market_fx_rate_id`/`group_fx_rate_id`/
`model_fx_rate_id`) resolving against `REQ-FX-002`'s rate-set contract.
No currency list, default group currency (beyond Decision 13's own
already-approved USD-when-using-the-default-method note), or rounding
policy is invented - `MonetaryObservation` accepts any ISO-4217-shaped
currency string and any `Decimal` precision the caller supplies.

### REQ-FX-002 (FX-rate record and immutable rate-set governance)

`ancestry_mmm/core/fx_rates.py`: `FXRateRecord` (stable `rate_id`, rate
date, source/target currency, the rate with the fixed `target = source x
rate` direction convention, frequency including Decision 13's
2026-08-30 `annual` addition, method, provider identity, retrieval
timestamp, `is_derived_cross_rate`/`derivation_path`); `FXRateSet`
(immutable identity, `records_fingerprint`, approval metadata, "new
version on any change" mirroring `core.coverage.SourceVersion`'s
already-established pattern exactly); `derive_cross_rate` (the
`B per A = (B per EUR) / (A per EUR)` reference-currency derivation,
with deterministic round-trip identity as a regression test - "verified
by deterministic direction/round-trip identity tests," per this
record's own Requirement 3, never assumed correct from a provider's raw
shape). No provider or authoritative-rate-set selection is made.

### REQ-FX-003 (historical conversion-method vocabulary)

`ancestry_mmm/core/fx_conversion.py`: the closed, versioned eight-value
method vocabulary (`observed_daily`, `daily_spend_weighted_weekly_
average`, `business_day_weekly_average`, `previous_business_day`,
`finance_budget_rate`, `finance_accounting_rate`, `manual_approved_
rate`, and Decision 13's own 2026-08-30 `finance_constant_dollar_
annual` addition) - an unrecognised method fails closed by construction
(a `ValueError`, never a silent fallback). Conversion functions:
`convert_daily_spend` (Requirement 2, per-day conversion before
weekly summation); `convert_weekly_average` (Requirement 3, arithmetic
mean of available business-day rates, retaining observation count and
missing-day status - fails closed against a caller-supplied minimum-
observation threshold, never inventing that threshold, mirroring `core.
seo_partial_window_policy`'s established "approve the framework, defer
the number" discipline); `convert_spend_weighted_weekly` (Requirement 4,
`sum(daily spend x daily rate)`, with the implied effective weekly rate
always derivable/auditable); `apply_previous_business_day_fallback`
(Requirement 5); and `apply_finance_constant_dollar_annual` (Decision
13's own default method - applies one Finance-supplied annual rate
uniformly across its financial year, carrying no observation-count/
business-day logic, per this record's own 2026-08-30 addendum). No
default-method selection for weekly-spend conversion beyond Decision
13's own already-resolved default, and no minimum-observation threshold,
is invented.

### REQ-FX-004 (provider-adapter architecture and ingestion governance)

`ancestry_mmm/core/fx_provider.py`: the `FXProvider` Protocol
(`fetch_rates(currencies, start_date, end_date) -> list[FXRateRecord]`),
never a hard-coded call to a specific API. `ManualUploadFXProvider` - a
genuine, working reference implementation of the source hierarchy's own
third tier ("manual approved upload... when an API cannot supply a
required historical pair") that validates and normalises caller-
supplied rate rows into governed `FXRateRecord`s without any network
dependency - the one adapter this record can safely and honestly
implement without fabricating a live integration to a provider this
project has not selected or been given credentials for. The governed
ingestion-pipeline validation stages that do not require network I/O
are implemented: currency/date/direction validation, duplicate-date
detection, missing-period detection, and impossible-rate checks
(non-positive or absurd-magnitude rates) - `validate_rate_records`.
Credential-security is enforced structurally: `assert_no_embedded_
credentials` scans a serialised payload for common secret-shaped
patterns (API key/token/bearer/password-like strings) and raises if
found, a genuinely testable safeguard for Requirement 5's "never
persisted inside a project bundle... log output... or a Streamlit
session export" rule. **No ECB, FRED, or any other live network
provider adapter is implemented or selected** - this record does not
choose a provider, exactly as `REQ-FX-004`'s own text requires.

### REQ-FX-005 (future FX assumptions and scenario/optimisation translation)

`ancestry_mmm/core/fx_future_assumption.py`: `FutureFXAssumption` (the
closed five-value method vocabulary `finance_budget_rate`/`latest_
observed`/`trailing_average`/`manual_fixed`/`forward_curve`, currency
pair, date range, rate value, provenance, approval metadata - never a
silently substituted live spot rate). `CurrencyResource` (Requirement 4's
typed cross-market resource: `unit="currency"`, an explicit `currency`
field, local decision-variable amounts each carrying their own required
FX translation). `validate_cross_market_currency_translation` -
Requirement 4's "the optimiser must validate every conversion before
solving, never silently coercing mismatched currencies" as a standalone,
testable pre-solve check (not wired into `core.optimization` itself -
see "What this record does not implement"). No future-rate method
default or typed-resource naming convention beyond what this record
itself introduces is claimed as Finance-approved.

### REQ-FX-006 (reporting, currency-labelled economics, year-on-year decomposition)

`ancestry_mmm/core/fx_reporting.py`: the four-value currency-view
vocabulary (`transaction`/`market_reporting`/`group_reporting`/
`constant_currency`, Requirement 1); `label_currency_figure` (Requirement
2's "every CPA/ROI figure must display its currency explicitly," fails
closed - raises rather than returning an unlabelled string - when more
than one currency is in play and no explicit label is supplied);
`FxTranslationDecompositionComponent` (Requirement 4's "FX translation
as its own explicit component, distinct from... media-price inflation");
`FxDependencySnapshot` and `assess_fx_staleness_triggers` (Requirement
5's persisted-dependency/staleness contract: a changed historical rate
set or future assumption stales dependent artefacts; a changed
reporting-currency *selection* alone never does).

**Explicitly NOT implemented for REQ-FX-006**: the full eight-component
year-on-year decomposition framework this record's Requirement 4 lists
alongside FX (underlying response/effectiveness, spend/saturation,
channel/product/segment mix, timing/carryover, promotions/price,
capacity, external conditions, definition change) - a repo-wide grep
confirms none of those seven other components exist anywhere in this
codebase yet (no `core.report`/`core.reporting_rollups` decomposition
module implements this vocabulary today). Building the FX component in
isolation without the framework it plugs into would either invent that
framework unreviewed or produce an orphaned component with nothing to
attach to. `FxTranslationDecompositionComponent` is deliberately
self-contained (computable and testable on its own, from a pair of
period-level FX-rate-set fingerprints and translated values) so it can
be adopted by that framework once/if it is built, without this record
guessing that framework's own shape.

## What this record does not implement (deliberate scope boundaries)

- Any actual currency list, default group/model currency (beyond
  Decision 13's own already-approved USD note), or rounding/precision
  policy (`REQ-FX-001`).
- Any specific rate-provider selection, or a live network adapter to
  ECB/FRED/a corporate feed (`REQ-FX-004`) - only the protocol and the
  network-free manual-upload tier.
- Any specific historical-conversion default beyond Decision 13's own
  already-resolved `finance_constant_dollar_annual` default, or the
  minimum-business-day-observation threshold (`REQ-FX-003`).
- Any future-FX method default, typed-resource naming convention beyond
  this record's own introduced shape, or actual forward-curve/budget-
  rate value (`REQ-FX-005`).
- Any reference-rate-set default for the constant-currency view, or
  display/rounding precision (`REQ-FX-006`).
- Wiring any of the above into `core.media_costs`, `core.market_config`,
  `core.canonical_curves`, `core.optimization`, `core.planning.
  future_context`, `core.report`, `core.reporting_rollups`, or any
  `pages/*.py` UI - every module here is additive and standalone,
  consistent with every other Phase B/C/D step's "declare the contract,
  defer production wiring" scope boundary already established
  throughout this session.
- **Any actual exchange-rate value.** Every example, test fixture, and
  docstring in this record's implementation uses clearly synthetic
  numbers (e.g. `Decimal("1.27")` for a GBP/USD test) - never presented
  as, or resembling, a real historical or current rate.

## Implementation

Five new modules (`ancestry_mmm/core/fx_currency.py`,
`fx_rates.py`, `fx_conversion.py`, `fx_provider.py`,
`fx_future_assumption.py`, `fx_reporting.py`) - six files, one per
REQ-FX record's primary contract, per the per-record detail above.

Tests: `ancestry_mmm/tests/test_fx_currency.py`,
`test_fx_rates.py`, `test_fx_conversion.py`, `test_fx_provider.py`,
`test_fx_future_assumption.py`, `test_fx_reporting.py`.

## Owner and status

Owner: Finance / Platform engineering (architecture implemented per
approved contract); Finance retains ownership of every concrete
operational choice this record does not make. Status: implemented and
tested, 2026-08-30, per the user's explicit 2026-08-30 authorisation
and its explicit rate-value carve-out.
