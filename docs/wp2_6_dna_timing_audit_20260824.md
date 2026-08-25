# DNA media/outcome timing audit (Work Package 2.6, item 5)

Status: audit findings only. This is not a presumption that DNA timing
leakage exists - WP2.5's mature-fold incremental-future-media evidence
was already largely reassuring; this audit checks for a specific class
of defect (one-week offsets, differing campaign/payment/bill-through date
conventions) that would not necessarily show up in that surrogate
evidence alone. No production code, data, or fit-relevant configuration
is changed by this document.

## What was checked

1. **The existing governed calendar-alignment/leakage assessment.**
   Every real-data pre-fit run in this programme already routes through
   `core.frequency_alignment.assess_official_preparation` (called from
   `scripts/run_uk_production_fit.py`'s official-preparation gate before
   any frame is built) - the same governed check that would fail closed
   (`FitGateError`) on a detected publication-timing leak or a definition
   break between DNA's media and outcome date bases. For the DNA kit
   model, this gate resolved `status: "pass"`, `decisions_required: []`,
   and an empty `alignment_results` list (no flagged rows) against the
   real approved UK source pack. This is the repository's own dedicated,
   already-tested mechanism for exactly this class of problem, not a new
   check invented for this audit.
2. **Direct weekday-convention spot-check.** `pack.activity_bundle.
   model_input_media`'s `period_start` column (which both the DNA media
   and, via the same canonical-calendar resolution, the DNA outcome data
   are aligned to) is Sunday-dated for all 235 rows spanning 2022-01-02
   through 2026-06-28 - a single, consistent weekly-start convention
   with no mixed Monday/Sunday rows that would silently produce a
   one-week-equivalent misalignment between two "weekly" series using
   different week-start conventions.
3. **`REQ-NBT-002`'s recorded DNA/Family History date basis.** The
   approved historical-test outcome authority records signup-date/
   signup-cohort attribution with a 14-day completeness horizon for the
   Family History NBT outcomes; the same record's "Affected modules"
   list includes `core.net_billthrough.py` for the shared completeness
   contract. No separate DNA-specific date-basis override (e.g. a
   distinct payment-date or bill-through-date convention for DNA
   specifically) is recorded in `docs/approved_requirements/` or
   `docs/decision_log.md` - DNA is expected to follow the same governed
   signup/cohort-date convention as Family History unless a future
   record states otherwise.

## Finding

No positive evidence of a systematic one-week offset or a differing
campaign-date/payment-date/bill-through convention was found for DNA in
this pass. This is not an exhaustive manual date-by-date reconciliation
of every DNA source row (which would require inspecting raw values this
programme's diagnostics deliberately avoid surfacing beyond aggregate
statistics) - it combines the repository's own dedicated, already-
enforced alignment gate (which every real-data run already passes
through and which is designed to catch exactly this defect class) with
a direct calendar-convention spot-check and a documentation cross-check.
Combined with WP2.5's mature-fold finding that the raw future-media R2
signal is largely explained by shared baseline/seasonality on the same
fold, the residual open question from WP2.5 (whether DNA's future-media
timing signal reflects a real defect) is not supported by this audit
either.

## What remains open

- This audit did not reconstruct DNA media/outcome timing from raw
  source rows directly (e.g. verifying individual campaign start/end
  dates against individual outcome cohort dates) - only the governed
  alignment gate's own pass/fail result, a calendar-convention spot-
  check, and the recorded date-basis documentation were reviewed.
- If the analyst or a data owner has independent knowledge of a DNA-
  specific reporting convention not captured in `REQ-NBT-002` or the
  supplied source pack's own metadata, that would not be caught by this
  audit and should be raised separately.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.6 investigation. Status: audit complete, no defect
found; residual open items above recorded, not resolved.
