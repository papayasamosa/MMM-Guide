# WP2.6 item 3: transformation/collinearity diagnostic findings (2026-08-24)

Status: diagnostic findings only. No adstock prior, transform default, or
production model configuration is changed by this document. This
completes the collinearity hypothesis test that WP2.5's transformation-
sensitivity finding left open (`docs/wp2_5_diagnostic_investigation_
findings_20260824.md`, item 2): whether T1/T2 (lighter adstock)
outperforming heavier-adstock variants on the mature fold is
substantially explained by heavier variants overlapping more with
baseline/context and with each other, as opposed to a genuinely weak or
short-lived response.

Evidence source: `scripts/run_uk_wp2_6_transform_collinearity.py`, run
against the real approved UK source pack, mature fold only
(`prefit-fold-3`, 82 training weeks - the same fold WP2.5's
transformation-sensitivity finding used). Raw output (aggregate
statistics only) is at `D:\Ancestry-MMM\test-artifacts\
historical-model-a-wp2-6-collinearity-20260824\`.

## Family History: condition number grows with adstock weight, and so
does baseline/cross-channel overlap

| Transform | Condition number | Mean \|corr\| with baseline (trend/season/context) | Mean \|corr\| with other channels |
|---|---|---|---|
| T1 (lightest) | 10.9 | 0.424 | 0.490 |
| T2 | 10.5 | - | - |
| T3 | 40.9 | - | - |
| T4 | 28.9 | - | - |
| T5 | 87.0 | - | - |
| T6 (heaviest) | 61.1 | 0.642 | 0.714 |

(Base-overlap correlations were computed for T1 and T6 only, as the
bounding endpoints of the transform grid; condition number is reported
for all six.)

Both signals point the same direction: as adstock weight increases from
T1 to T6, Family History's condition number rises roughly six-fold (not
perfectly monotonically - T4 < T3 and T6 < T5, consistent with the grid
not being a single ordered decay parameter but a joint decay/Hill-slope
grid), and every channel's average overlap with baseline and with other
channels rises substantially (mean baseline correlation 0.424 -> 0.642;
mean cross-channel correlation 0.490 -> 0.714). This is consistent with
the hypothesis that heavier adstock's poorer mature-fold surrogate
performance for Family History is substantially explained by increasing
collinearity with baseline/context and other channels, not solely (or
necessarily at all) by a genuinely weaker underlying response at longer
carryover lengths.

## DNA: collinearity diagnostics are dominated by one structurally
zero-variance channel, independent of adstock choice

DNA's condition numbers are astronomically large for every transform
variant (T1=1.43e17, T2=7.48e16, T3=3.16e16, T4=4.61e17, T5=2.99e17,
T6=5.42e16) - orders of magnitude beyond anything a real adstock-driven
collinearity effect would produce, and not ordered by adstock weight the
way Family History's are. Per-channel VIF inspection (T1) identifies the
cause directly: `uk_dna_content_marketing` has `VIF = NaN` while every
other DNA channel's VIF is modest and comparable to Family History's
range (1.44-9.56). A VIF of NaN in this diagnostic's own definition
means the target column has zero variance in the regression it was
computed on (see `_vif` in `scripts/run_uk_wp2_6_transform_
collinearity.py` - guarded explicitly, not a computation error).

Direct verification confirms `uk_dna_content_marketing` has exactly
**zero nonzero observations within the 82-row mature-fold training
window** - its only two active weeks across the entire 119-week
governed window both fall in the held-out test portion of fold 3, not
the training portion (consistent with WP2.5's sparse-channel finding
that this channel has only 2 active weeks in total). A constant
(all-zero) column is trivially collinear with the intercept, which
inflates the whole design matrix's condition number to near-numerical-
limit values regardless of any other channel's adstock transform - this
is a fold/coverage artefact of DNA Content Marketing's extreme sparsity,
not evidence about DNA's adstock transform choice generally.

**This means DNA's mature-fold transformation-sensitivity result from
WP2.5 (T1 RMSE 0.532 vs T6 RMSE 0.842, monotonically worsening) cannot
currently be cleanly attributed to genuine adstock-driven collinearity**
- the diagnostic that would show this is swamped by the DNA Content
Marketing artefact. Re-running this specific diagnostic with DNA Content
Marketing excluded (or with a fold that has training-window coverage for
it) would be needed to see DNA's transform-driven collinearity signal on
its own; not done in this pass, since removing a channel from a
diagnostic's design matrix is different from removing it from the model
and does not require the "no channel removal" governance boundary to be
crossed, but was out of scope for this bounded pass.

## What this does and does not settle

- **Settled for Family History**: the collinearity hypothesis is
  materially supported by real evidence - heavier adstock variants are
  more collinear with baseline and with each other, consistent with
  (though not proof of) the mature-fold RMSE pattern being partly a
  surrogate-model identification limit rather than solely a true
  short-response finding.
- **Not settled for DNA**: the diagnostic as run is uninformative on
  this specific question, dominated by a single sparse channel's
  fold-coverage artefact. DNA's own transformation-sensitivity finding
  from WP2.5 remains open.
- **No transform default, adstock prior, or channel treatment is changed
  by this finding.** If a production transformation change is proposed
  in a future decision package, this evidence should be cited as
  supporting (for Family History) or inconclusive (for DNA), not as a
  final determination either way.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.6 investigation. Status: findings supplied for
review, collinearity hypothesis test complete for Family History,
inconclusive for DNA. No WP3 full-fit sampling is authorised by this
document.
