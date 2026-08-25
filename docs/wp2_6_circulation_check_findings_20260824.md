# WP2.6 item 4: circulation raw-data check findings (2026-08-24)

Status: findings only. No source value is edited by this document or by
`scripts/run_uk_wp2_6_circulation_check.py`. Per the analyst's stopping
instruction, this document reports (does not silently fix) if a plain
data defect were found; the finding below does not meet that bar, so no
remediation report is triggered.

Evidence source: `scripts/run_uk_wp2_6_circulation_check.py`, run
against the real approved UK source pack's `model_input_media` frame
(2026-08-24). Raw output is at `D:\Ancestry-MMM\test-artifacts\
historical-model-a-wp2-6-circulation-check-20260824\circulation_check.
json` - D-drive only, never committed, no raw source rows reproduced in
this document beyond the single circulation column's already-aggregated
weekly values needed to explain the finding.

## What WP2.5 flagged

Circulation's positive max/median ratio was 105.97 - a genuine outlier
against every other sparse/weak-support channel reviewed in WP2.5 (all
in the 1.4-8.2 range). The analyst asked for the specific week and value
behind this ratio to be identified using the local approved source pack.

## What was found

The peak is a single week: **2023-05-07 (UK), value 4,475,284**, against
a positive-week median of 42,232 (58 positive weeks total, 39 distinct
positive values across the full window). The value appears **exactly
once** in the series (`value_appears_n_times: 1`) - not a duplicated-row
artefact.

The surrounding six weeks:

| Date | Value |
|---|---|
| 2023-04-16 | 28,110 |
| 2023-04-23 | 0 |
| 2023-04-30 | 0 |
| **2023-05-07** | **4,475,284 (peak)** |
| 2023-05-14 | 283,289 |
| 2023-05-21 | 76,001 |
| 2023-05-28 | 0 |

Source evidence for this pack: `activity_data_approved_metadata_and_
structural_zeros.xlsx` (checksum `e0f7b68e...`, version 1) - the
governed, approved UK activity source, not an ad hoc file.

## Assessment

The pattern - two preceding zero weeks, then a single very large spike,
then a declining tail (283K -> 76K -> 0) over the following three weeks
- is consistent with a genuine one-off circulation/mailer distribution
event (e.g. a large print run or partner mailing sent in a single week,
with response/re-activity tapering over subsequent weeks) rather than a
simple duplicate-row or unit-conversion bug: a duplicate-row defect
would not produce this kind of decay shape, and the value appearing
exactly once rules out a repeated/duplicated observation.

**This is not ruled out as a batching/aggregation artefact** - e.g. a
quarter's or campaign's worth of circulation volume being recorded
against a single send-date rather than spread across its actual
distribution weeks would produce an identical-looking spike-then-decay
pattern in this weekly series, and this check cannot distinguish that
from a genuine single-week event without business-context confirmation
from the data owner (e.g. campaign planning records, print/distribution
logs).

**Conclusion: this is not "plainly a data defect"** per the analyst's
stopping criterion for this check - it is an unusual but structurally
plausible value with a source-consistent decay pattern, not an
arithmetic or duplication error visible in the data itself. No
remediation report is triggered by this pass. If independent business
confirmation is available (or obtainable) that a single 2023-05-07
circulation event of this magnitude did or did not occur, that would
resolve the remaining ambiguity; this diagnostic pass cannot obtain
that confirmation on its own.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.6 investigation, and the UK activity data owner (for
independent confirmation, if pursued). Status: check complete, finding
supplied for review; circulation's sparse-channel review classification
from WP2.5 (weak support, retained, no change) is unaffected. No WP3
full-fit sampling is authorised by this document.
