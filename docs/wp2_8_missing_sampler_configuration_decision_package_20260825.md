# WP2.8 decision package: 4-chain geometry screen / medium-run sampler configuration is undefined (2026-08-25)

Status: decision package. **No stage of WP2.8 was executed.** This
document reports a governance gap found while attempting to begin
WP2.8 item 1 and stops there, per the analyst's own explicit
instruction: "Do not invent a new sampler configuration. If the
repository does not define the intended 4-chain geometry-screen
configuration sufficiently to reproduce it, produce a small decision
package describing the missing setting and stop rather than silently
selecting one."

## What was searched

An exhaustive search was run across:

- Every `docs/**/*.md` file, including all of `docs/approved_requirements/`
  and `docs/decision_log.md`
- Every `scripts/**/*.py` file for `draws=`/`tune=`/`chains=`/
  `target_accept=` (and their `--draws`/`--tune`/`--chains`/
  `--target-accept` CLI equivalents)
- `AGENTS.md`
- The full git history (`--all`) of `docs/model_a_convergence_
  remediation_20260822.md` and of `scripts/run_uk_transform_
  identifiability_experiment.py`, and a repository-wide commit-message
  search for "geometry", "medium run", and "4-chain"

## What was found

**The phrases "4-chain geometry screen" and "medium run" appear in
exactly one place in the entire repository**, `docs/model_a_
convergence_remediation_20260822.md` lines 73-76:

> "The 4-chain geometry screen, medium run, full convergence run,
> posterior validation, attribution, and Search mediation Model B were
> not started because the approved computational gate failed."

This sentence names the two stages but attaches **no draws/tune/chains/
target_accept numbers to either**, and no other part of that document,
any other document, any script, any REQ record, or any decision-log
entry defines them further. Checking the document's full git history
confirms this sentence has read identically, with zero numbers, in
every version since it was first written - no earlier draft ever had
concrete numbers that were later removed.

**The only two governed/documented sampler configurations that exist
anywhere in the repository** are:

| Stage | Draws | Tune | Chains | Target accept | Source |
|---|---|---|---|---|---|
| Short screen (2 chains) | 100 | 150 | 2 | 0.95 | `scripts/run_uk_transform_identifiability_experiment.py` CLI defaults; already used for WP2.7's short screen |
| Full production run | 2000 | 1000 | 4 | 0.9 | `scripts/run_uk_production_fit.py` CLI defaults |

Nothing in the repository defines a configuration sized between these
two, and nothing anywhere is labelled "geometry screen" or "medium
run" with numbers attached. `docs/approved_requirements/REQ-PREFIT-001.md`'s
own governed workflow explicitly jumps directly from "optional short/
approximate probabilistic screening" to "full production PyMC
posterior" - it does not define an intermediate stage either.

(Two superficially similar hits were checked and ruled out as
unrelated: `docs/decision_log.md` records several 2-chain, 150-400-draw
sampler configurations, but these are all for **Model C / DNA-halo
synthetic-panel recovery checks**, a different model entirely, not UK
Model A. `docs/pymc_marketing_alignment.md`'s "Transform/hierarchy
identifiability ladder" is a different ladder - the C0-C5 diagnostic
switches in `run_uk_transform_identifiability_experiment.py` - not the
sampler-stage ladder this document's remediation doc describes.)

## Why this blocks the rest of WP2.8

Item 1's own instruction is explicit: use an existing governed
configuration for the 4-chain geometry screen, or stop and report the
gap rather than inventing one. Since no such configuration exists, item
1 cannot proceed as specified. Items 2-7 are each conditional on item
1's output (item 2 requires "healthy geometry" from item 1's run before
proceeding to the medium run; items 3-6 analyse the medium-run
posterior; item 7 returns "the 4-chain geometry and medium-run
evidence"). None of them can be executed without first resolving this
gap. **No sampling was run for this work package.**

## Candidate configurations (not selected)

For the analyst's reference only - **none of these is chosen or
recommended over the others**, and none should be treated as approved
without an explicit decision:

**4-chain geometry screen** - a plausible next rung would keep draws/
tune close to the already-run short screen (its purpose being to check
whether 4 independent chains show consistent geometry, not to gather
more posterior mass) while moving from 2 to 4 chains:
- 4 chains x 100 draws x 150 tune x 0.95 target_accept (identical to
  the short screen's per-chain draws/tune, chain count only)
- 4 chains x 200 draws x 250 tune x 0.9 (a modest step up in both
  draws and chains simultaneously)

**Medium run** - a plausible intermediate point between the short
screen and the 2000/1000/4/0.9 full production configuration:
- 4 chains x 500 draws x 500 tune x 0.9
- 4 chains x 1000 draws x 500 tune x 0.9

These are illustrative bracketing examples only, to give the analyst a
concrete sense of the range - not a shortlist to choose from
necessarily, and not this document's recommendation.

## What this document does not do

- Does not select a sampler configuration for either stage.
- Does not run any sampling.
- Does not change any statistical specification (control priors,
  seasonality, trend, adstock, Hill K/S, pooling, channel selection,
  causal structure, sparse-channel treatment all remain exactly as
  frozen at the WP2.7 state, per the analyst's instruction).
- Does not authorise WP3.

## Requested analyst decision

Either (a) confirm one of the illustrative configurations above (or a
different one) as the governed 4-chain-geometry-screen configuration,
recorded in a `docs/approved_requirements/REQ-*` record or a
`docs/decision_log.md` entry so it is reproducible and citable for
future stages of this same ladder, or (b) direct a different resolution
(e.g. treating the short screen itself, already run at 2 chains, as
sufficient evidence to skip directly to a specifically-approved medium
or full run). Once a configuration is approved, WP2.8's items 1-7 can
proceed against real evidence in a follow-up pass.

## Owner and status

Owner: Modelling / Platform engineering, with the human analyst who
directed this WP2.8 investigation. Status: blocked on a governance gap,
reported for decision. No WP2.8 evidence produced; no WP3 authorised.
