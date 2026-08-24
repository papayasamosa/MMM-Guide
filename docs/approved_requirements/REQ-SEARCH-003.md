# REQ-SEARCH-003: Product-specific historical Search preparation

## Approval and traceability

This scoped record implements the approved sequential historical MMM brief
`Ancestry_MMM_Sequential_Next_Steps_Search_Brand_State_and_GitHub_PRs.md`,
section 1 through section 4, supplied for the UK production-readiness
sequence on 2026-08-21.

It does not supersede `REQ-SEARCH-001`'s object-separation invariants or
`REQ-SEARCH-002`'s separately approved latent-demand/capacity formulation.
It adds the product-specific observed Search preparation boundary required for
the staged historical Model B comparison. The analyst decision dated
2026-08-22 additionally approves the bounded observed-mediator historical test
after Model A passes its convergence gate.

## Approved scope

For the UK historical sequence, Family History and DNA have separate paid
Search account identities:

| Product | Spend object | Delivery/mediator object |
|---|---|---|
| Family History | `fh_paid_brand_search_spend` | `fh_paid_brand_search_clicks` |
| DNA | `dna_paid_brand_search_spend` | `dna_paid_brand_search_clicks` |

The source workbook's shared physical `spend` and `clicks` names do not merge
these objects: product scope is part of the governed source identity.

Missing spend is unresolved unless an explicit, source-supported structural-zero
evidence set names the period. Zero clicks are not evidence of zero spend.
No interpolation, generic zero-fill, or spend/delivery substitution is
permitted.

The staged observed Search graph permits spend to explain the corresponding
click mediator and permits clicks to mediate into the product's approved
outcomes. It prohibits a direct spend-to-outcome edge and prohibits treating
the same clicks as an ordinary direct media predictor for the same effect.
Mediator-path adstock uses a separate parameter namespace from outcome-path
adstock. VIF, Pearson/Spearman correlation, condition number, rank,
near-zero variance, temporal/flight overlap, and coverage remain diagnostics;
they do not automatically delete variables.

For the bounded historical test, the approved observed mediation structure is:

```text
FH paid brand-search spend -> FH paid brand-search clicks -> FH NBT outcomes
DNA paid brand-search spend -> DNA paid brand-search clicks -> DNA kit outcomes
```

Eligible upstream media may also explain the product-specific Search click
mediator and retain their direct outcome paths. Paid Brand Search spend does
not receive a second ordinary direct outcome coefficient, and clicks are not
also fitted as a duplicate ordinary direct media channel. Search-path
transformations may use a separate adstock namespace from final-outcome paths.

## Out of scope and gates

This record does not approve official production contribution, planning,
optimisation, or a latent branded-demand/capacity model. The bounded
historical observed-mediator test may run after Model A convergence, valid
common-window FH/DNA spend/click coverage, graph approval, Search prior
predictive checks, equation-level identification diagnostics and synthetic
mediation recovery. Unresolved real source coverage must stop the affected
fit and retain the exact unresolved periods.

## Affected modules and tests

- `ancestry_mmm/core/search_preparation.py`
- `ancestry_mmm/core/search_objects.py`
- `ancestry_mmm/core/graph_model_compiler.py`
- `ancestry_mmm/core/observed_mediation.py`
- `ancestry_mmm/tests/test_search_preparation.py`
- `scripts/resolve_search_spend_coverage.py`

Required tests include separate FH/DNA identities, no spend zero-fill from
zero clicks, explicit structural-zero resolution, mediator-specific adstock
timing, equation diagnostics, and prohibited direct Search-spend paths.

## Engine boundary

The preparation and graph contracts are repository code. The observed
mediator likelihood remains custom PyMC code and is not claimed as native
PyMC-Marketing functionality. No sampler or production engine is changed by
this record.

## Status

Approved for this staged implementation boundary. Real-UK coverage and graph
approval remain separate evidence gates.
