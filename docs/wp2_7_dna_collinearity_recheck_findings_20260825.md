# WP2.7 item 3: DNA transformation-collinearity recheck findings (2026-08-25)

Status: diagnostic findings only. No production adstock default,
transform, or channel treatment is changed by this document.
`uk_dna_content_marketing` remains in Model A unchanged - it is excluded
only from this diagnostic's own design matrix, per the analyst's
instruction, because WP2.6 found it constant-zero in the mature fold's
training sample (making its own collinearity numbers a fold-coverage
artefact rather than a real adstock-driven signal).

Evidence source: `scripts/run_uk_wp2_7_dna_collinearity_recheck.py`
(new; reuses `core.prefit_screening`'s transform/fold helpers, no
duplicate implementation), run against the real approved UK source
pack, mature fold only (`prefit-fold-3`, 82 training weeks). Raw output
is at `D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-dna-
collinearity-recheck-20260825\wp2_7_dna_collinearity_recheck.json`.

## Condition number, with the artefact channel excluded

| Transform | Condition number |
|---|---|
| T1 (lightest) | 11.4 |
| T2 | 11.8 |
| T3 | 22.2 |
| T4 | 22.0 |
| T5 | 48.0 |
| T6 (heaviest) | 37.1 |

This is now a clean, real signal - condition number grows roughly
three-to-four-fold from T1 to T6 (with the same non-monotonic T4<T3,
T6<T5 pattern already seen for Family History in WP2.6, consistent with
the grid varying decay and Hill-slope jointly rather than a single
ordered parameter), on the same order of magnitude as Family History's
own WP2.6 result (10.9 to 61.1). Every other DNA channel's VIF at T1 is
modest (1.44-9.56, confirmed unchanged from WP2.6), so this pattern is
not driven by any other single sparse channel.

## Base and cross-channel overlap grows with adstock weight

| Transform | Mean \|corr\| with baseline (trend/season/context) | Mean \|corr\| with other channels |
|---|---|---|
| T1 | 0.170 | 0.216 |
| T6 | 0.231 | 0.350 |

Both overlap measures increase from T1 to T6 - smaller in absolute
magnitude than Family History's equivalent WP2.6 result (0.424->0.642
baseline, 0.490->0.714 cross-channel) but the same direction and a
comparable relative increase (roughly 1.4x baseline, 1.6x cross-channel
for DNA; roughly 1.5x and 1.5x for Family History).

## Conclusion

**With the fold-coverage artefact removed, DNA shows the same
qualitative pattern as Family History**: condition number, baseline
overlap, and cross-channel overlap all increase with heavier adstock.
This supports (does not prove) WP2.5's collinearity hypothesis for
DNA's own transformation-sensitivity finding (T1 RMSE 0.532 vs. T6 RMSE
0.842, monotonically worsening) - heavier-adstock variants overlapping
more with baseline/context and with each other is a real, measurable
phenomenon for DNA once the sparse-channel artefact is excluded, not
solely (or necessarily at all) evidence of a genuinely weaker underlying
response at longer carryover lengths.

**This closes the open question WP2.6 left for DNA's collinearity
diagnostic.** No adstock, transform, or channel-treatment default is
changed by this finding, per the analyst's explicit instruction; if a
future decision package proposes a production transformation change,
this evidence should be cited as supporting for both products now, not
inconclusive for DNA as WP2.6 left it.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.7 investigation. Status: diagnostic complete, WP2.6's
open DNA collinearity question resolved. No production change made.
