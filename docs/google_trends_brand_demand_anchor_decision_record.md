# Google Trends brand-demand identifying-anchor decision record

## Why this record exists

`REQ-LATENT-001`'s 2026-08-30 addendum (Decision 9 of the "Post-UI/UX
Implementation Instructions: Approved Business Decisions" brief) approved
**Google Trends for Ancestry branded search terms** as the identifying
anchor *source* for Candidate A's latent `latent_branded_search_demand`
state (`MD-021`'s single most concrete open item) — but explicitly left
open "the exact identifying constraint/measurement-model mathematics
that ties the Google Trends series to `latent_branded_search_demand`'s
scale... and the business interpretation of one unit of the resulting
latent state," naming this as Phase B implementation and identification
work.

This record is that resolution. It resolves:

- the governed query-set/series-observation data contract;
- the deterministic normalisation applied to the raw Google Trends
  series before it can serve as an anchor;
- the specific identifying constraint (which of `REQ-LATENT-001`
  Requirement 1's five listed strategies, and its exact mathematical
  form);
- the business interpretation of one unit of the resulting latent
  state.

It explicitly does **not** resolve, and does not implement:

- an actual Google Trends ingestion/API-client mechanism (out of scope —
  mirrors `core.seo_visibility`'s equivalent boundary: this record only
  defines the computation given an already-available extraction);
- wiring the fixed-loading constraint into `core.search_capacity`'s
  actual linked-PyMC construction of `latent_branded_search_demand` —
  imposing this constraint inside a real fit is itself a materially
  statistical model change requiring its own prior-predictive checks and
  synthetic-recovery validation (`REQ-LATENT-001` Requirement 4), and
  stays a separate, explicitly deferred follow-up, exactly as
  `REQ-LATENT-001`'s own Requirement 3 (compiler-level blocking) and the
  remaining Requirement 4 sub-items are already deferred;
- Decision 10's separate capacity-cap question (already addressed by
  `REQ-LATENT-001`'s own 2026-08-30 Decision 10 addendum).

## Sources consulted

This decision was made after directly querying Google's own official
Trends documentation (not from general training-data recall alone):

1. **Google Trends Help Center FAQ**
   (`support.google.com/trends/answer/4365533`, fetched directly): the
   authoritative source for how Google Trends normalises its own
   numbers — "each data point is divided by the total searches of the
   geography and time range it represents to compare relative
   popularity[;] the resulting numbers are then scaled on a range of 0
   to 100 based on a topic's proportion to all searches on all topics."
   The same FAQ states plainly: "Trends only shows data for popular
   terms, so search terms with low volume appear as '0.'" — the
   authoritative source for this record's missingness treatment below.
2. Secondary, non-authoritative corroboration (search-aggregator/blog
   commentary, e.g. SerpApi's and Medium's explainers of Trends
   behaviour) was used only to sanity-check the general shape of the
   renormalise-on-every-request behaviour widely reported by
   Trends-tooling practitioners (e.g. `pytrends` users' well-documented
   experience that stitching two separately-requested time windows
   without a shared overlap-rescaling step silently produces an
   inconsistent series) — this is NOT treated as an authoritative
   Google statement, and this record's actual constraints below rely
   only on source 1's plain text, treating the stitching risk as a
   reason to prohibit multi-extraction combination rather than to adopt
   any specific third-party rebasing formula.

No further external web search was used; source 1 directly answered
every open normalisation/missingness question this decision required.

## Design requirements this record must satisfy (from `REQ-LATENT-001`'s
2026-08-30 addendum)

1. The branded query set must be a governed definition, not an ad-hoc
   keyword list assembled at extraction time.
2. Geography, time range, category/filter settings, and extraction date
   must be recorded alongside the series.
3. The raw Google Trends series must be kept as evidence, never
   discarded after use.
4. Any normalisation/rescaling applied before using the series as an
   anchor must be deterministic and documented.
5. The latent state must never be presented as an absolute count of
   searches — Google Trends is a relative index, not an absolute volume.
6. The branded-demand trend must be shown in diagnostics in a form
   comparable to the observed Google Trends series.

## Decisions required

### G1. Query-set governance shape

**Candidate G1-A — an ad-hoc keyword string per extraction.** Rejected
outright by Decision 9's own text (design requirement 1 above).

**Candidate G1-B — a versioned `GoogleTrendsQuerySetDefinition` record**
(branded terms tuple, geography, category, time-range bounds, extraction
date, methodology version), mirroring this repository's established
governed-definition pattern (`SeoVisibilityMetricDefinition`,
`ActivityDefinition`).

**Decision: G1-B.**

### G2. Whether multiple extractions may be combined into one series

**Candidate G2-A — allow stitching multiple extraction calls freely.**
Rejected: Google's own FAQ confirms normalisation is "based on a topic's
proportion to all searches" **for the geography and time range
requested** — i.e. each request's 0–100 scale is internally consistent
only *within that request*. Two separate extractions (even for the same
query set, geography, and terms) each re-peak their own 0–100 scale to
their own request window; naively concatenating them would silently
produce a series where "100" means two different things in two
different segments — exactly the kind of silent corruption this
project's fail-closed discipline exists to prevent.

**Candidate G2-B — require one single extraction call per query set,
covering the model's entire estimation window; reject any attempt to
combine rows carrying different `query_set_id`s into one series.**
Matches design requirement 4 (deterministic, documented normalisation)
and avoids inventing an unapproved rebasing formula. A future session
that genuinely needs to extend a series beyond one extraction's window
must define and approve a specific overlap-rescaling method first — not
guessed here.

**Decision: G2-B**, implemented as a hard validation error in
`compute_anchor_series` when supplied raw rows do not all share the
same `query_set_id`.

### G3. Missingness representation for a raw-zero week

**Candidate G3-A — treat a raw `0` exactly like GSC's zero-impression
case (`STATE_OBSERVED_ZERO`, with the derived value forced to `None`).**
Rejected: this conflates two different facts. GSC's zero-impression case
is a genuinely undefined ratio (division by zero — no meaningful
position exists that week). Google Trends' documented `0` behaviour is
different in kind: the FAQ states the *term* itself is too low-volume
for Trends to report precisely, not that the ratio is undefined. A `0`
returned by Google Trends is a real, transcribed number from the
source — treating it as "missing" would discard real evidence design
requirement 3 requires be kept.

**Candidate G3-B — keep the raw `0` and its linear rescaling
(`anchor_value = 0.0`) as a real, computed number, but flag the week
with `coverage_state = STATE_SUPPRESSED`** (this repository's existing
`core.coverage` vocabulary state for "a value withheld/floored by the
source itself," `REQ-COVERAGE-001` §2) rather than `STATE_OBSERVED_ZERO`
or `None`. An ordinary, non-zero, non-suppressed week gets
`coverage_state = None` (an ordinary observed source fact), mirroring
the same implementation judgement `core.seo_visibility` already made for
GSC's raw, non-modelled fields.

**Decision: G3-B.**

### G4. Normalisation for use as an anchor

**Candidate G4-A — use the raw 0–100 index directly as the anchor
value.** Rejected only as a matter of unit hygiene: leaving the anchor
on a 0–100 basis rather than a documented, chosen scale makes it easy
for a future reader to mistake "100" for something meaningful in
absolute terms (e.g. a percentage of some real quantity), which Google's
own scale is not.

**Candidate G4-B — `anchor_value = raw_index / 100.0`.** A purely linear
rescaling onto `[0, 1]` that preserves every relative relationship in
Google's already internally-consistent 0–100 basis (deterministic,
documented, trivially reversible, no information gained or lost).

**Decision: G4-B**, implemented in
`ancestry_mmm.core.google_trends_anchor.compute_anchor_series`.

### G5. The identifying constraint itself and the business interpretation
of one unit

**Candidate G5-A — a free multiplicative scale parameter between the
anchor and the latent state (`latent_demand_t = scale * anchor_t`, with
`scale` estimated).** Rejected: this reintroduces exactly the
scale-indeterminacy `REQ-LATENT-001` exists to resolve — a free scale
parameter on the one and only anchor input provides no identifying
information at all; it merely relabels the indeterminacy without fixing
it.

**Candidate G5-B — fix the loading between the anchor and the latent
state's scale at exactly `1.0` (never estimated)** — the standard
single-indicator scale-identification device in Bayesian/econometric
latent-variable models (`REQ-LATENT-001` Requirement 1's second listed
strategy, "anchoring the latent state to an observed quantity with a
defined unit"): the anchor's own rescaled value *is*, by construction,
the latent state's scale for the corresponding period. This is a valid,
minimal, fully documented identifying constraint that requires no new
free parameters and directly satisfies design requirement 5: because the
anchor itself is a relative index (never an absolute count), fixing the
latent state's scale to it means one unit of `latent_branded_search_demand`
is, by construction, **one point of this governed, rescaled, relative
Google Trends index for the approved branded query set** — explicitly
NOT one search, one click, or any absolute search volume.

**Decision: G5-B.** Implemented as
`GOOGLE_TRENDS_ANCHOR_FIXED_LOADING = 1.0` and carried through
`build_google_trends_identification_declaration`'s
`LatentStateIdentificationDeclaration` (`strategy_kind =
STRATEGY_ANCHORED_TO_OBSERVED`), whose `description` states the fixed
loading and the resulting business interpretation of one unit
explicitly, satisfying `REQ-LATENT-001` Requirement 2 ("must be stored
in the model specification and effect metadata, not left implicit in
code").

Actually imposing this fixed-loading constraint inside `core.
search_capacity`'s real linked-PyMC construction of
`latent_branded_search_demand` is **not** done by this record (see "Why
this record exists" above) — this record only assembles the governed
declaration a future fit-time integration would consume, mirroring
`core.latent_state_identification`'s own "the caller supplies the
declaration" scope boundary.

### G6. Diagnostic comparability (design requirement 6)

**Decision:** `compare_anchor_to_fitted_latent_series` pairs the
governed anchor series with a caller-supplied fitted-latent-value-by-week
mapping (e.g. a posterior median per week), producing one
`GoogleTrendsAnchorComparisonPoint` per anchor week. This function
performs no fitting itself — mirrors `core.structural_stability`'s "the
caller supplies the fold-local computation" pattern already reused by
`core.latent_state_identification`.

## What this record does not decide

- Any actual Google Trends extraction/ingestion mechanism.
- Whether/how the fixed-loading constraint is imposed inside a real
  PyMC fit (a separate, materially statistical follow-up requiring its
  own validation).
- A rebasing method for combining more than one extraction into a
  single series (explicitly prohibited without one — G2 above).
- Candidate A's overall eligibility for official use — that remains
  gated by `core.latent_state_identification.is_eligible_for_official_use`
  and `REQ-LATENT-001`'s existing fail-closed Requirement 5, unaffected
  by this record.

## Implementation

`ancestry_mmm/core/google_trends_anchor.py`:

- `GoogleTrendsQuerySetDefinition` — the governed query-set record (G1).
- `GoogleTrendsRawObservation` — one raw weekly Trends row (0–100 scale)
  for one query set.
- `GoogleTrendsAnchorObservation` — the governed anchor-series record
  after this record's rescaling and suppressed-zero treatment (G3, G4).
- `compute_anchor_series` — the deterministic computation (G2, G3, G4).
- `GOOGLE_TRENDS_ANCHOR_FIXED_LOADING`,
  `build_google_trends_identification_declaration` — the identifying
  constraint and its `LatentStateIdentificationDeclaration` (G5),
  reusing `core.latent_state_identification.STRATEGY_ANCHORED_TO_OBSERVED`
  without modifying that module.
- `GoogleTrendsAnchorComparisonPoint`,
  `compare_anchor_to_fitted_latent_series` — the diagnostic comparison
  (G6).

Tests: `ancestry_mmm/tests/test_google_trends_anchor.py`, including
query-set validation/round-trip, the single-query-set enforcement (G2),
the suppressed-zero missingness treatment (G3) versus an ordinary
observed week, the 0–1 rescaling (G4), the identification declaration's
fixed loading and one-unit interpretation text (G5), and the diagnostic
comparison pairing (G6).

## Owner and status

Owner: Modelling / Platform engineering (anchor definition and
computation); Product-Marketing / SEO-SEM (query-set term list
sign-off, not yet sought — this record proposes the query-set governance
shape and formula for Modelling's own implementation purposes, mirroring
`docs/seo_positional_visibility_metric_decision_record.md`'s own
delegation).

Status: implemented and tested, 2026-08-30. `REQ-LATENT-001` addendum
(below) records this resolution at the requirement level. `MD-021`
remains not fully resolved until the fixed-loading constraint is
actually imposed inside a real Candidate A fit and validated per
Requirement 4 — that fit-time integration is explicitly out of this
record's scope.
