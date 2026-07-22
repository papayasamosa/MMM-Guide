# Brand Search Treatment Modes (PR G1)

Design record for `core.brand_search` - four explicit, analyst-chosen treatment modes for Brand Search
spend, the notoriously ambiguous MMM channel where some of the measured response is genuinely
incremental and some is upper-funnel demand it just happens to capture last-click.

## Why this exists

Fitting the "true" causal split between Brand Search's incremental effect and the demand it captures
from other channels requires either an incrementality experiment (a geo holdout) or a full causal DAG -
both explicitly out of scope for PR G1 ("do not yet build ... causal DAG", per the reprioritised
roadmap). Rather than silently picking one treatment and calling it correct, `core.brand_search` makes
the choice explicit and gives each mode transparent, documented mechanics.

## The four modes

```text
direct_channel                   - an ordinary primary_direct media channel (core.pathways). Known
                                    bias: OVERSTATES Brand Search's true incremental value whenever
                                    upper-funnel channels genuinely drive some of its clicks.
excluded                         - spend excluded entirely (core.pathways excluded role - zero
                                    contribution, deterministically). Conservative: never overstates
                                    Brand Search, but understates total measured media impact if it
                                    actually has some genuinely incremental effect of its own.
demand_capture_mediator          - fit exactly like direct_channel (same primary_direct mechanics, same
                                    fitted beta), but REPORTED contribution is decomposed post-hoc:
                                    mediation_share of it is reallocated onto the declared mediator_of
                                    upstream channels.
experiment_calibrated_incremental - reported contribution is scaled by calibration_factor, supplied
                                    from an external incrementality test (a geo holdout, a platform-run
                                    conversion lift study).
```

`brand_search_pathway_role(mode)` is the only touchpoint into actual model fitting:
`direct_channel`/`demand_capture_mediator`/`experiment_calibrated_incremental` all map to
`core.pathways`' `primary_direct` role; `excluded` maps to `excluded`. Everything else in this module
operates on already-fitted contribution series at report/attribution time - `BrandSearchConfig` alone
does not change what gets fitted; a channel set to `excluded` mode still needs a matching
`role="excluded"` row on the Structure page's pathway catalogue to actually drop it from the likelihood.

## `BrandSearchConfig`

```python
BrandSearchConfig(
    channel="Brand_Search",
    mode="demand_capture_mediator",
    mediator_of=["TV", "YouTube"],   # analyst-approved edges only, never auto-detected
    mediation_share=0.4,             # required for demand_capture_mediator - no safe default
    calibration_factor=None,         # required for experiment_calibrated_incremental - no safe default
    notes="",
)
```

`validate_brand_search_configs` fails closed on anything with no safe default: `demand_capture_mediator`
requires `mediator_of` (non-empty, no self-reference) and `mediation_share` (a `[0, 1]` fraction);
`experiment_calibrated_incremental` requires `calibration_factor` (a `[0, 1]` ratio). Duplicate configs
for the same channel are rejected.

## Deterministic mediator reallocation

`mediator_reallocation(config, brand_search_contribution, upstream_contributions)` splits
`config.mediation_share` of Brand Search's own fitted contribution across `config.mediator_of` in
proportion to each upstream channel's OWN contribution that period - an explicit, documented rule, not
a fitted causal estimate. The rest stays with Brand Search as genuinely incremental.

Reconciles exactly: `direct + sum(mediated_by_*) == brand_search_contribution` for every row, since
every reallocated amount comes out of the same total (never an independent estimate that could over- or
under-shoot it). A period with zero upstream activity across every declared mediator has nothing to
allocate its mediated pool to - that share folds back onto `direct` for that period rather than being
silently discarded, so reconciliation holds even in that edge case.

`apply_experiment_calibration(config, raw_contribution)` scales a channel's raw fitted contribution by
`calibration_factor` for `experiment_calibrated_incremental` mode.

## UI

Model Configuration page's "Brand Search treatment mode" section (below the promo sensitivity prior) is
an `st.data_editor` table, one row per Brand Search channel, validated before the modelling frame can be
prepared. `mediator_of` is stored as a real `List[str]` on `BrandSearchConfig` but rendered/edited as a
comma-joined string in the editor - `st.column_config.TextColumn` cannot bind to a list-typed DataFrame
column directly (caught by an `AppTest` regression check, `test_model_config_brand_search_apptest.py`).

## Explicitly out of scope for PR G1

No causal DAG, no automated incrementality-experiment pipeline, no fitted mediation model - the
`mediation_share`/`calibration_factor` inputs remain explicit analyst judgement, not estimated
parameters. A future PR could replace `experiment_calibrated_incremental`'s manual `calibration_factor`
with a structured geo-test result import; that is not built here.

## Verification

See `test_brand_search.py` (mode-to-pathway-role mapping, config validation, mediator reallocation
reconciliation, experiment calibration scaling) and `test_simulation_recovery.py`'s
`TestMediatorCreditAllocationRecovery` (the reallocation recovers an exact known upstream contribution
ratio, not merely a reconciling-but-arbitrary split).
