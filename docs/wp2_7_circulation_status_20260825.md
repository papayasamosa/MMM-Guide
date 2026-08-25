# WP2.7 item 5: circulation observation status (2026-08-25)

Status: no change. This document formalises the analyst's explicit
instruction and does not alter any data.

## Decision

The 2023-05-07 UK circulation observation (value 4,475,284, ~106x the
positive-week median; see `docs/wp2_6_circulation_check_findings_
20260824.md` for the original investigation) is **preserved unchanged**.
It is not winsorised, capped, or replaced. No governed source evidence
gathered so far establishes that this value is erroneous - WP2.6's
investigation found a plausible genuine-event decay pattern in the
surrounding weeks, and could not rule out a batching/aggregation
artefact, but found no arithmetic or duplication defect in the data
itself.

## Recorded data-quality caveat

**This observation is a data-quality caveat requiring data-owner
confirmation before final production certification of the current UK
Model A candidate.** The circulation channel is retained in the model
with `weak` support classification (per WP2.5's sparse-channel review)
and this single observation materially affects that channel's own
positive-value scale; any ROI/attribution evidence for circulation
specifically should be treated as provisional until the data owner
either confirms the value or provides a corrected one through the
governed source-pack update process. No other channel or observation is
affected by this caveat.

## Owner and status

Owner: UK activity data owner (confirmation), Modelling / Platform
engineering (tracking). Status: open caveat, gating circulation-specific
production certification only - not gating this work package's other
deliverables, and not itself a blocker for the short sampler screen or
governed pre-fit evidence already produced under WP2.7.
