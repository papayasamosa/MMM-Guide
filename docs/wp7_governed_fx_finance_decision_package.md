# Governed FX: Finance-owned decisions requiring approval

Work Package 7 (`Media-Mix-Lab Coding LLM Next Steps 2026-08-27`).

## Purpose

`REQ-FX-001` through `REQ-FX-006` (`docs/approved_requirements/`)
reconcile the *architecture* of `Ancestry_MMM_Governed_FX_Translation_
Requirements_Addendum.md` into repository authority — the data model,
governance mechanics, and structural rules for handling multi-currency
spend, historical conversion, provider adapters, future assumptions,
scenario/optimisation translation, and reporting. None of those six
records approves the concrete business/operational choices the addendum
itself explicitly names as unresolved (its own Section 20, "Decisions
requiring Finance approval") or the specific default-selection points
each `REQ-FX-*` record's own "Explicitly excluded" section defers. This
package collects every one of those open questions in one place so a
future implementation pass has a single document to work from rather
than six scattered "Explicitly excluded" lists, and so no coding agent
mistakes an approved architecture for an approved business policy.

**This package makes no decision.** It states the open questions,
the evidence already available (the addendum's own recommendations,
where it makes one), the viable options, and what would need to change
once each is decided. Every item below requires an explicit Finance (or,
where marked, Platform engineering) decision before any concrete default
is implemented.

## Open questions

### 1. Is `USD` definitely the Ancestry group reporting currency?

**Evidence available:** The addendum's own header states "Primary group
reporting currency: USD, subject to Finance confirmation" and Section 2.3
calls its USD proposal a "proposed initial value," not a settled one.

**Options:** (a) confirm USD; (b) a different group currency; (c) a
market-dependent group currency (not recommended by the addendum, which
frames group currency as one project-level governed setting).

**Affected:** `REQ-FX-001` §1 (group reporting currency field), every
downstream consolidated report, cross-market optimisation's typed
currency resource (`REQ-FX-005` §4).

### 2. What does `CSD` mean in the referenced documents?

**Evidence available:** The addendum's header explicitly flags this as
unresolved: "`CSD` is not the US-dollar code... may be a typo or an
internal term," and directs that any use be confirmed with Finance before
implementation.

**Options:** confirm the intended meaning, or confirm it was a typo for
`USD` and should never appear in implementation.

**Affected:** any place a currency code is hard-coded from an external
document referencing `CSD` — none currently exists in this repository.

### 3. The specific market-to-reporting-currency mapping

**Evidence available:** Section 2.2's suggested mapping (UK→GBP,
Germany/euro-area→EUR, Canada→CAD, Australia→AUD, US/group→USD) is
explicitly labelled "subject to approval," and itself notes a market may
contain transactions in more than one currency.

**Options:** approve the suggested mapping as-is; amend it; or defer
per-market mapping to a governed, editable table rather than a fixed
list.

**Affected:** `REQ-FX-001` §1, the eventual market-configuration UI
(`REQ-FX-004`'s "Add a governed FX workspace" scope).

### 4. Which source is authoritative for management reporting?

**Evidence available:** Section 7's source hierarchy is a *recommended*
precedence (Finance feed → official public source → manual upload), not
a selection; Section 20 item 3 asks this exact question directly.

**Options:** adopt the recommended hierarchy as governing policy; select
one single authoritative source; or a different precedence.

**Affected:** `REQ-FX-004` §2, `REQ-FX-002`'s rate-set provenance.

### 5. Should Finance corporate rates override market-reference rates?

**Evidence available:** Section 6.5 states Finance rates "must not
overwrite market-reference rates" as a *structural* rule (they are always
stored as separate governed rate sets), but Section 20 item 4 asks the
separate *policy* question of which is used by default for a given
purpose.

**Options:** market-reference rates remain default, with Finance rates
selectable per purpose (matches the structural rule as written); Finance
rates become default for specific purposes (e.g. financial
reconciliation); purpose-by-purpose Finance sign-off.

**Affected:** `REQ-FX-003` §6, `REQ-FX-002`'s rate-set selection at
report/scenario time.

### 6. Default historical conversion method for weekly spend

**Evidence available:** Section 6 describes three methods (arithmetic
weekly average, spend-weighted weekly, previous-business-day fallback)
without selecting a default; Section 20 item 5 poses the question
directly ("daily-spend-weighted, weekly average or month-end").

**Options:** the addendum's own stated preference order (spend-weighted
where daily data exists, otherwise arithmetic weekly average, per
Sections 6.2-6.3) as the default; a uniform single method regardless of
data availability; month-end rate as the default.

**Affected:** `REQ-FX-003` §§2-4, the eventual FX conversion executor.

### 7. Which rate is used for budget planning?

**Evidence available:** Section 20 item 6 poses this directly; Section
10.2's `finance_budget_rate` method exists in the vocabulary but is not
selected as the budget-planning default.

**Options:** `finance_budget_rate` as the default for all budget-planning
future assumptions; a different method; purpose-specific selection left
to the analyst per scenario.

**Affected:** `REQ-FX-005` §1, the future-FX-assumption default method.

### 8. Constant-currency basis: prior-year, current-year, or budget rate?

**Evidence available:** Section 14.3 describes the constant-currency view
generically ("one approved reference-rate set, normally the comparison
period or budget rate") without selecting one; Section 20 item 7 poses
the question directly.

**Options:** prior-year rate; current-year rate; budget rate; analyst-
selectable per report.

**Affected:** `REQ-FX-006` §3, the year-on-year decomposition's
constant-currency view.

### 9. Required rounding/display precision

**Evidence available:** Section 20 item 8 poses this directly; the
addendum requires `Decimal` arithmetic for persisted calculation
(`REQ-FX-001` §4) but does not specify a rounding rule or display
precision for any reported figure.

**Options:** a fixed number of decimal places per currency (matching ISO
4217 minor-unit conventions); a Finance-specified precision table;
full-precision persistence with display-only rounding (no persisted
rounding at all).

**Affected:** `REQ-FX-001` §4, `REQ-FX-006` §2 (currency-labelled CPA/
ROI display).

### 10. How are hedged contracts handled?

**Evidence available:** Section 6.5 lists "hedged contract rates" among
Finance-override rate types without specifying handling rules beyond
"stored as separate governed rate sets"; Section 20 item 9 poses the
question directly.

**Options:** treat a hedged rate exactly like any other `finance_
accounting_rate`-tagged rate set (no special handling beyond `REQ-FX-002`/
`REQ-FX-003`'s existing governance); a dedicated `hedged_contract_rate`
method added to the closed vocabulary; hedged spend excluded from FX
translation entirely (booked at the hedged rate with no further
conversion).

**Affected:** `REQ-FX-003` §1 (method vocabulary), `REQ-FX-002` (rate-set
provenance).

### 11. Which currencies and markets are in initial scope?

**Evidence available:** Section 20 item 10 poses this directly; the
addendum's examples throughout (GBP, EUR, CAD, AUD, USD; UK, Germany/
euro-area, Canada, Australia, US) are illustrative, not a scope
commitment.

**Options:** the addendum's illustrative set as the actual initial scope;
a narrower initial scope (e.g. UK GBP↔USD only, matching this
repository's current UK-focused delivery); a broader scope.

**Affected:** every `REQ-FX-*` record's eventual implementation surface;
directly relevant to `docs/specification_authority.md`'s existing UK
historical-test scope.

### 12. Provider adapter selection

**Evidence available:** Section 7 names the European Central Bank Data
API and Federal Reserve H.10/FRED data as "potential official adapters"
without selecting either; `REQ-FX-004` §2 approves only the adapter
*pattern*.

**Options:** ECB Data API (covers EUR cross-rates directly, per Section
8's own worked example); Federal Reserve H.10/FRED; both, with the
source-hierarchy question (item 4 above) governing precedence; a
Finance-supplied feed as primary with either as backfill/validation only
(the addendum's own recommended pattern).

**Affected:** `REQ-FX-004` (the module that would be built once a
provider is chosen).

## What is NOT open (already resolved by the `REQ-FX-*` records)

To avoid a future pass re-litigating settled architecture: the four-
currency-role separation (`REQ-FX-001`), the immutable-versioned-rate-set
pattern and cross-rate derivation requirement (`REQ-FX-002`), the closed
conversion-method vocabulary's *existence* (though not its default,
`REQ-FX-003`), the provider-adapter *pattern* (though not the provider,
`REQ-FX-004`), the future-assumption-object pattern and typed cross-
market currency resource *pattern* (`REQ-FX-005`), and the four-view
reporting/year-on-year-decomposition contract (`REQ-FX-006`) are all
approved. A future implementation pass should build against these
contracts, not re-propose them.

## Owner

Finance (business/policy questions 1, 3, 4, 5, 6, 7, 8, 10, 11) and
Platform engineering (technical questions 2, 9, 12, in consultation with
Finance where the choice has a cost or compliance implication).

## Status

Decision package recorded; no decision made. This workstream stops here
pending explicit Finance sign-off on the items above.
