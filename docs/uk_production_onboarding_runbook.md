# UK production onboarding runbook

This runbook records the implementation boundary from `REQ-NBT-004` and the
UK production decisions brief. It is a checklist for a real analyst with the
approved external source packs; it does not contain production data or claim
that a production fit has been run.

## Required source and outcome boundary

1. Load the supplied UK source pack and its versioned metadata, including the
   production definition, maturity/completeness evidence, exclusions,
   reconciliation source, `data_as_of_date`, and source fingerprint.
2. Configure the three separate Family History NBT outcomes:
   `fh_net_billthrough_count_new`,
   `fh_net_billthrough_count_dna_cross_sell`, and
   `fh_net_billthrough_count_winback`.
3. Keep GSA as a distinct secondary/context measure. Do not reconstruct NBT
   from GSA, apply a universal conversion, or apply the historical-test
   14-day rule as a production default.
4. Run source preparation, coverage, pre-fit support, and the mandatory
   official-fit gates. Missing or immature evidence blocks official fitting.

## Optional pathways and boundaries

- Google Trends Candidate A preserves the exact approved query expression and
  extraction provenance. It is a Brand Demand anchor, not a Family History
  category-demand measure. Candidate A remains unavailable for UK production
  until governed historical cap evidence and its cap-hit rule are supplied;
  no cap is derived from spend or fabricated.
- SEO is an optional, separate observed organic-search input. Select Brand and
  Non-Brand (or explicitly governed deeper children) individually. Uploads may
  be raw GSC rows or already-aggregated market/week/group rows. Missing weeks
  remain inactive, never zero-filled, and SEO has no spend CPA/ROI.
- Deeper Non-Brand Search children start as draft. Parent and child cannot be
  fitted at the same model grain; child planning/economics stay unavailable
  without child-level observed and governed cost support. Google/Bing remains
  a separate platform axis.
- FX uses the UK convention `USD = GBP × approved GBP-to-USD rate`, by calendar
  year January–December. No live-rate fallback exists; pending/unapproved
  rates cannot drive official reporting. Count fitting is unaffected.
- Experiments/lift-test calibration are not configured for the initial UK
  scope. Their absence does not block the ordinary NBT fit. Profit optimisation
  is fail-closed without governed margin/COGS/value evidence and is not an
  onboarding blocker.

## Durable fit workflow

1. Build the proposal on Model Training. The page snapshots the frame,
   specification, pathways, Search/SEO inputs, sampler settings, random seed,
   and fingerprints before submission.
2. Submit the fit. Sampling runs in a separate local worker process and writes
   durable JSON state/progress, logs, and an atomically promoted ArviZ NetCDF
   artifact. Refreshing the browser does not cancel or restart it.
3. Reattach to the project-scoped job list. A worker that disappears without a
   valid terminal artifact becomes `orphaned`; cancellation is explicit and
   persisted.
4. Adopt only a `succeeded` job whose data, model-spec, and fit-input
   fingerprints still match the current project. Adoption clears prior
   approval and preserves the prior model when any check fails.
5. Run Diagnostics and the approval workflow. Technical approval belongs to
   the analyst/model technical approver; wider review may be recorded as
   optional metadata. No validation bypass is waivable.

## Current readiness statement

The code path and governance boundaries are implemented and tested with
synthetic fixtures. External UK source data, approved production metadata,
and any required cap/cost evidence remain deliberately required before an
official production fit can be performed.
