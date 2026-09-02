# SEO positional-visibility metric formula decision record

## Why this record exists

`REQ-SEO-001`'s 2026-08-30 addendum (Decision 5 of the "Post-UI/UX
Implementation Instructions: Approved Business Decisions" brief) approved
the **type** of the primary SEO exposure metric — an organic search
position / positional-visibility measure, not raw clicks — but explicitly
deferred the **exact formula** (aggregation across queries/pages,
impression weighting, and the transformation of raw average position into
a usable metric) as a named research-first item, requiring: "review of
the real GSC fields available, official Google Search Console
definitions, and relevant SEO/MMM research, with a decision record of the
options considered before implementation."

This record is that decision. It resolves the formula only. It does not
resolve, and explicitly defers:

- the functional form/transformation this index takes if and when it
  enters an actual MMM regression as a treatment variable (`REQ-SEO-001`'s
  still-open "transformation of a non-linear ranking metric... for use as
  a linear treatment" item — a statistical/causal design question for
  Phase B/C's Search causal-contribution work, Decision 6);
- full partial-window SEO handling policy (Decision 3) — e.g. whether a
  week with materially incomplete source coverage should be flagged,
  down-weighted, or excluded from a fit. This record's formula correctly
  *computes* from whatever rows a caller supplies (including an
  incomplete set — see the partial-window test in
  `ancestry_mmm/tests/test_seo_visibility.py`), but the policy for
  deciding when a window is *too* incomplete to trust is separate,
  later work.

## Sources consulted

This decision was made after directly querying live Google documentation
via the Context7 MCP tool (not from general training-data recall alone),
specifically:

1. **Google Search Console API reference** (`developers.google.com/webmaster-tools/v1/searchanalytics/query`,
   fetched via Context7 library `/websites/developers_google_webmaster-tools_v1`):
   confirmed the exact `rows[]` response schema (`clicks`, `impressions`,
   `ctr`, `position` — each a `double`), and that `position` is
   "Average position in search results" at whatever grain the query was
   made (i.e. already an average *within* that row, not a raw single
   rank).
2. **Google Search Console Help Center** (`support.google.com/webmasters`,
   fetched via Context7 library `/websites/support_google_webmasters`):
   two directly load-bearing findings —
   - The official BigQuery bulk-export documentation's own SQL formula
     for combining rows into a daily average position:
     `((sum(sum_top_position) / sum(impressions)) + 1.0) AS avg_position`
     (`sum_top_position` is 0-indexed; the API's `position` field is the
     1-indexed equivalent). This is Google's own authoritative
     confirmation that combining multiple rows correctly requires
     **impression-weighting**, not a naive mean of already-averaged
     `position` values.
   - The Help Center's "Average position" explainer: "A position is only
     recorded if the result receives an impression" — the authoritative
     source for this record's "missing is not zero" requirement: a
     zero-impression period has no position at all, not a position of 0
     or some placeholder.

No further external web search was used; the two sources above directly
answered every open question this decision required (the exact response
fields, the official aggregation method, and the documented missingness
behaviour), so a broader search was unnecessary. General SEO-industry
knowledge (e.g. that `1/position`-style indices are a common, simple
positional-visibility proxy) informed the transformation choice below but
was not treated as authoritative on its own — the two sources above are
what this decision is actually anchored to.

## Design requirements this record must satisfy (from the governing brief)

1. Unambiguous direction ("better ranking" must read as unambiguous).
2. A defined aggregation (not a naive unweighted mean).
3. Reproducible and deterministic.
4. Missing data must never become zero.
5. The metric's meaning must be visible/documented for the analyst.
6. Organic clicks/impressions retained as diagnostics, not the primary
   exposure metric.

## Decision required

### F1. Which raw GSC fields feed the metric

**Candidate F1-A — `position` and `impressions` only, `clicks` as
diagnostic.** Matches Decision 5's own framing exactly: ranking, not
clicks, is the causal question ("does better organic search ranking lead
to more sales or sign-ups?" cannot be answered by a clicks-based exposure,
since clicks are themselves a downstream consequence of both ranking and
independent demand). `impressions` is required as the weighting variable
(see F2) even though it is not the primary exposure itself.

**Candidate F1-B — `ctr` as an additional input.** Rejected as a metric
*input* (kept as a diagnostic output instead): CTR conflates ranking with
independent factors (title/meta-description quality, brand recognition,
SERP feature competition) that are not "ranking" in the sense Decision 5
asks about, and mixing it into the exposure metric would make the causal
story harder to isolate, not easier.

**Decision: F1-A.** `position` is the substantive signal;
`impressions` is the aggregation weight; `clicks` (and the derived `ctr`)
are retained as supporting diagnostics only, per requirement 6 above and
`REQ-SEO-001` §3's existing "distinct from organic capture" boundary.

### F2. Aggregation method across queries/pages

**Candidate F2-A — naive unweighted mean of per-row `position` values.**
Rejected outright: a query/page mix shift (e.g. a new, deep-ranked
long-tail query entering the result set) would move the metric even
though the site's *actual* visibility for its real search volume did not
change — exactly the distortion the governing brief warns against.

**Candidate F2-B — impression-weighted average.** `weighted_avg_position
= sum(position_i * impressions_i) / sum(impressions_i)`. This is not
merely a plausible choice — it is mathematically what Google's own
official BigQuery-export formula computes when combining multiple rows
(`(sum(sum_top_position) / sum(impressions)) + 1.0`, confirmed above),
generalised to whatever grain of rows the caller supplies (queries,
pages, days, or any combination) since the standard Search Analytics API
does not expose raw `sum_top_position`, only the already-averaged
`position` per row — impression-weighting the API's `position` field is
the correct way to recombine those row-level averages without needing
Google's internal 0-indexed sum directly.

**Decision: F2-B**, implemented in
`ancestry_mmm.core.seo_visibility.compute_weekly_positional_visibility`.

### F3. Transformation into a usable, directionally-unambiguous metric

**Candidate F3-A — use raw impression-weighted average position
directly (lower is better).** Rejected: GSC's native convention is
lower-is-better (position 1 is best), which is the *opposite* sign
convention from every other media variable in this MMM (spend up →
outcome up is the intuitive reading everywhere else). Requiring an
analyst to remember that a *negative* regression coefficient on this one
variable is the "good" result, while every other variable's positive
coefficient is "good," is exactly the ambiguity requirement 1 above
prohibits.

**Candidate F3-B — `1 / weighted_avg_position` ("positional visibility
index").** Higher is better (position 1 → 1.0; position 10 → 0.1),
bounded in `(0, 1]`, deterministic, monotonic, and directly reflects
diminishing returns of rank without assuming any external empirical
curve (a move from position 20 to 10 changes the index by 0.05; a move
from position 2 to 1 changes it by 0.5 — a materially larger, and
intuitively correct, jump for reaching the very top of results).

**Candidate F3-C — a CTR-curve-weighted "visibility share"**, using an
assumed empirical industry CTR-by-rank curve as weights (e.g. summing
`assumed_ctr(position) * impressions`). Rejected for this metric
definition: it requires importing and maintaining a third-party,
non-Ancestry-specific CTR-by-rank assumption that would itself need
separate governance and could silently go stale; it also conflates a
*positional-visibility* measurement with an assumed *click-propensity*
model, when this repository already keeps observed clicks/impressions/CTR
as separate, real diagnostics (requirement 6). This candidate remains a
plausible future *pathway variable* for causal work (Decision 6's own
scope) but is not adopted as the primary metric definition here.

**Candidate F3-D — `-ln(weighted_avg_position)`** (higher is better,
unbounded). Considered as an alternative curvature to F3-B: it compresses
differences at low (good) positions more and expands them at high
(poor) positions, which is the *opposite* of what a "how much does
improving from position 20 to 10 matter compared to 2 to 1" intuition
usually wants for this business. Noted as a viable alternative should a
future statistical/functional-form decision (the still-open
"transformation... for use as a linear treatment" item) want a different
curvature; not adopted as the primary metric definition here since
`1/position`'s bounded, more immediately interpretable scale is preferred
for the metric's own disclosed meaning.

**Decision: F3-B.** `visibility_index = 1.0 / weighted_avg_position`,
`directionality = "higher_is_better"`, `unit = "index_0_to_1"`.

### F4. Missingness representation

**Candidate F4-A — treat a zero-impression period as `visibility_index =
0`.** Rejected: this would fabricate a real number for an undefined
ratio (division by zero), and directly contradicts Google's own
documented behaviour that a position is only recorded when there is at
least one impression — a "no data" week and a "site fell to the very
bottom of results" week are not the same fact and must not share a value.

**Candidate F4-B — `None`/undefined for `weighted_avg_position` and
`visibility_index` whenever total impressions are zero, while
`total_impressions`/`total_clicks` remain real numbers (including a
genuine `0.0`) whenever the caller actually supplied source rows for the
period.** Matches Google's documented behaviour exactly and this
repository's existing "missing is not zero" doctrine
(`REQ-COVERAGE-001`).

**Decision: F4-B.**

One further, narrower design choice made during implementation: this
repository's existing `core.coverage` eight-state missingness vocabulary
(`observed_zero`/`missing_expected`/`not_applicable`/
`unavailable_source`/`suppressed`/`estimated`/`modelled`/`unknown`) has
no state for "a plain, directly observed, non-zero source fact" — every
existing consumer of that vocabulary (`core.outcome_valuation`'s FH
LTR/DNA revenue records) is inherently a modelled/projected quantity with
no raw-observation case, so this gap never mattered there. GSC
impressions/position, by contrast, **are** raw, directly observed source
facts. Forcing an ordinary, fully-observed, non-zero SEO week into
`estimated` or `modelled` would misrepresent it — exactly the mislabelling
`REQ-COVERAGE-001` §2 warns against in the opposite direction ("a
latent/modelled value must never be stored or displayed as though it
were an observed source fact" — the reverse is equally wrong). This
record's `SeoPositionalVisibilityObservation.coverage_state` is therefore
`None` for an ordinary fully-observed week and populated with an existing
`COVERAGE_STATES` value only for the one recognised exception this record
defines (`observed_zero`, a confirmed zero-impression week). This is an
implementation-level judgement call within this record's own delegated
scope, not a new business decision.

## What this record does not decide

- The functional form/curve this index takes inside an actual MMM
  regression (Decision 6/Phase C's causal-wiring scope).
- Full partial-window coverage policy (Decision 3).
- Any Search-taxonomy dimension the visibility metric should be broken
  out by (query/page/intent-group) beyond what a caller chooses to supply
  as rows — this record's formula is agnostic to that grain.
- Any ingestion/scheduling mechanism for actually pulling GSC data into
  this application (out of scope; this record only defines the
  computation given already-available rows).

## Implementation

`ancestry_mmm/core/seo_visibility.py`:

- `GscPositionRow` — one raw GSC Search Analytics row (`position`,
  `impressions`, `clicks`).
- `compute_weekly_positional_visibility` — the formula (F2-B + F3-B +
  F4-B) for one `market x week` cell.
- `compute_weekly_positional_visibility_series` — the same, over a
  supplied set of `(market, week)` cells.
- `SeoPositionalVisibilityObservation` — the governed
  `fact_seo_visibility_observation` record (`REQ-SEO-001` §2).
- `SeoVisibilityMetricDefinition` / `SEO_POSITIONAL_VISIBILITY_METRIC` —
  the governed `dim_seo_visibility_metric_definition` record
  (`REQ-SEO-001` §1), carrying Decision 6's already-approved
  `causal_role = "mediator_or_capture_efficiency_state"` and this
  record's `directionality = "higher_is_better"` /
  `aggregation_rule = "impression_weighted_average_position_then_inverse"`.

Tests: `ancestry_mmm/tests/test_seo_visibility.py`, including a dedicated
regression test that the aggregation is impression-weighted (not a naive
mean), a cross-check against Google's own documented BigQuery-export
formula shape, missingness tests (zero-impression and empty-rows cases),
determinism/round-trip tests, and a partially-observed-window test.

## Owner and status

Owner: Modelling / Platform engineering (metric computation);
Product-Marketing / SEO (methodology sign-off, not yet sought — this
record proposes the formula for Modelling's own implementation purposes,
consistent with the brief's delegation of "the exact formula" to this
implementation pass).

Status: implemented and tested, 2026-08-30. `REQ-SEO-001` addendum
(below) records this resolution at the requirement level.
