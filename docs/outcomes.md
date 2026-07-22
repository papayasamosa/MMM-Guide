# Outcome Schema

Design record for `core.outcomes` - the generalised outcome catalogue that lets the tool describe
*what's being measured* (product, segment, metric, source column, value weight) as explicit
dimensions, rather than assuming every measurable outcome is a Family History segment.

**`outcome_id` is the model's canonical identity dimension (PR E, "make `OutcomeDefinition` the
canonical modelling schema" - see `docs/decision_log.md`), not `segment`.** Every fitted model, curve,
attribution, scenario, and persisted bundle keys on `outcome_id`, never on `segment` membership. This
is what makes it possible to fit two distinct KPIs on the *same* customer segment - e.g. a Family
History **sign-up** (`outcome_id="fh_new_signup"`) and a Family History **GSA**
(`outcome_id="fh_new_gsa"`), both `segment="New"` - as two independent outcome_ids with independent
fitted response curves, rather than conflating them because they happen to share a segment name.
`segment` remains a *descriptive* grouping field (which customer segment this outcome belongs to), not
a unique key.

## Why this exists

Before this schema, "outcome" meant exactly one thing: an entry in `ModelSpec.segment_outcomes`,
implicitly a Family History GSA column. That's correct for what the fitted model predicts today, but
it can't represent DNA kit purchases - a genuinely different business outcome (a product sale, not a
Family History signup) with its own economics - or two distinct KPIs (a sign-up funnel step and its
downstream GSA) on the same customer segment. `core.outcomes.OutcomeDefinition` adds an explicit
`product` dimension (`"Family History"` or `"DNA"`) alongside `segment`, `metric`, `source_column`, and
an optional `value_weight`, so the catalogue can describe all of these without forcing the data into a
shape built for one-outcome-per-segment.

## Scope boundary: captured always, modelled once mapped

`ModelSpec.segment_outcomes` is now purely a **migration source** - `core.outcomes.fh_outcomes_from_spec`
derives an equivalent outcome catalogue from it for any project that predates this schema. The actual
frame-preparation and model-building path (`data.preprocessor.prepare_fh_modeling_frame`,
`core.hierarchical_model.build_fh_hierarchical_model`, `core.market_specific_model.
build_fh_market_specific_model`) takes an explicit outcome catalogue (`outcomes=`, a
`List[OutcomeDefinition]`) as its structural input, not `spec.segment_outcomes` directly. DNA-product
outcomes are **opt-in**: mapping one on Structure: Segments & Markets does not, by itself,
retroactively change any existing fit, but the next time the modelling frame is prepared on Model
Configuration, `core.outcomes.dna_kit_outcome_columns` feeds the mapped DNA outcome_id(s) into
`prepare_fh_modeling_frame`'s `outcomes` parameter, and from there into the model builders'
`direct_dna_outcome_ids` - DNA-targeted media then gets full, direct response on that outcome_id, not
the shrunk-toward-zero halo pathway other outcomes get. See `docs/dna_fh_causal_structure.md` for the
full equation-level treatment and how double counting between DNA kit sales and FH cross-sell is
avoided.

`core.outcomes.outcome_requires_opt_in(outcome)` reflects the *automatic-vs-opt-in* distinction
specifically - `True` for any non-`"Family History"`-product outcome (today, any DNA outcome), since
FH is the only kind that's part of every fit with no extra step. It is a static, type-level question
("does this *kind* of outcome ever need a config step?") answerable from the outcome alone.

Whether a *specific* past run actually included a given outcome is a different, run-aware question -
answered by `core.outcomes.outcome_was_modelled(outcome, model_meta)` (`True` iff `outcome.outcome_id`
is in the given `FHModelMeta.outcome_ids` - `None` for `model_meta` always means `False`, never an
error - keyed on `outcome_id`, never `segment`, since two outcomes can share a segment and still need
to be distinguishable: a sign-up outcome must not read as "modelled" just because its sibling GSA
outcome on the same segment was) - and, more granularly, `core.outcomes.outcome_status(...)`, which
returns one of six states (`OUTCOME_STATUSES`): `Configured`, `Included in prepared frame`, `Included
in fitted run`, `Missing source column`, `Excluded`, `Stale after configuration changes`. A single
collapsed boolean can't distinguish "mapped but never fit" from "excluded from this fit on purpose"
from "fit before, but its source column has since disappeared" - `outcome_status` can, so every place
the outcome catalogue reaches the UI (Structure page, project report) shows this richer status rather
than a boolean, and a DNA row is never presented as if it's unconditionally influencing every fit's
outputs.

The Structure page also has a genuine "exclude this DNA outcome from the next fit" control (a
`st.multiselect`). As of PR E, exclusion is a **persisted property of the outcome itself** -
`OutcomeDefinition.included_in_fit` (plus an optional free-text `exclusion_reason`) - not session-only
state: the Structure page applies the multiselect's choice directly onto each outcome's
`included_in_fit` before saving the catalogue, `prepare_fh_modeling_frame` filters to
`included_outcomes(outcomes)` internally, and a reimported project now reconstructs the *exact* set of
outcomes that were included at fit time, closing the persistence gap the pre-PR-E
`excluded_outcome_ids` session-state mechanism left open.

## The schema

```python
OutcomeDefinition(
    outcome_id="fh_new_signup",
    product="Family History",
    segment="New",
    metric="Sign-up",
    source_column="Signup_New",
    unit="sign-up",
    value_weight=None,
    role="funnel_intermediate",
)

OutcomeDefinition(
    outcome_id="fh_new_gsa",
    product="Family History",
    segment="New",             # same segment as the sign-up above - a distinct outcome_id, not a conflict
    metric="GSA",
    source_column="GSA_New",
    unit="GSA",            # derived default - "GSA" for Family History, "kit" for DNA
    value_weight=180.0,    # LTV - optional
    role="primary",        # default
)

OutcomeDefinition(
    outcome_id="dna_new_kit",
    product="DNA",
    segment="New Customer",
    metric="Kit sale",
    source_column="DNA_Kit_New_Customer",
    unit="kit",
    value_weight=90.0,     # value per kit - optional
    role="primary",
    included_in_fit=True,  # persisted exclusion flag - see "Scope boundary" above
    exclusion_reason=None,
)
```

`outcome_id` is the stable identity every fitted model, curve, attribution, scenario, and persisted
bundle keys on - it is never re-derived from `segment`. `product` is one of
`core.outcomes.FAMILY_HISTORY` / `core.outcomes.DNA`. DNA `segment` is one of `DNA_SEGMENT_NEW` ("New
Customer"), `DNA_SEGMENT_EXISTING_FH` ("Existing FH Customer"), or `DNA_SEGMENT_COMBINED` ("Combined")
- see below. `unit`, `role`, `included_in_fit` and `exclusion_reason` are migration-safe additions: a
bundle saved before these fields existed just falls back to `unit`'s derived default, `role`'s
`"primary"` default, and `included_in_fit=True` (`OutcomeDefinition.from_dict` filters to known
dataclass fields and translates the legacy `column` key to `source_column`, so an older/missing key
never raises, it just uses the field default) - nothing to migrate explicitly. `unit` is what every
product-aware output downstream keeps separate (see "Product-aware outputs" below); `role` is one of
`OUTCOME_ROLES` (`"primary"`, `"secondary"`, `"funnel_intermediate"`, `"diagnostic"`) - validated and
always visible, but not yet a fitting-behaviour change in this PR.

A validation heuristic (`_implies_conflicting_metric_label`) string-matches `outcome_id`/`source_column`
against `metric` and flags an outcome whose id/column implies "signup" while its metric says "GSA" (or
the reverse) - a guard against exactly the mislabelling risk two distinct KPIs on one segment could
otherwise introduce. It is a heuristic (string patterns, not data semantics), documented as such.

## Backward compatibility: every project has a catalogue, not just ones that set one up

`core.outcomes.resolve_outcome_definitions(outcome_definitions, segment_outcomes, segment_ltv)` is
the single entry point every caller (Structure page, project report, persistence) uses to get "this
project's current outcome catalogue":

- If the project has an explicitly saved outcome set (any project that has been through the
  Structure page's outcome-catalogue save since this schema shipped), that wins.
- Otherwise - every project created before this schema existed, or that has never touched the DNA
  outcomes section - `core.outcomes.fh_outcomes_from_spec(segment_outcomes, segment_ltv)` derives an
  equivalent, correct FH-only set live from `ModelSpec`. A project is never left with "no outcome
  catalogue"; it just may not have any DNA outcomes mapped yet.

This is what makes the schema backward compatible with every existing FH-only project bundle without
a migration step: there is nothing to migrate, because the FH-only case is always derivable from data
that already exists.

## DNA kit outcomes: split vs. combined

The target shape is two separate DNA outcomes - kit purchases from new customers vs. from existing
Family History customers - because they have different economics (a new-customer kit purchase is an
acquisition event; an existing customer's is a cross-sell) and, once DNA response equations exist,
different causal links back to FH. `core.outcomes.dna_outcomes_from_columns` builds this from mapped
data columns.

Where source data can't support that split, a single combined column is an explicit, visible
fallback (`DNA_SEGMENT_COMBINED`) - not a silent approximation. `validate_outcome_definitions` rejects
mixing a combined outcome with split ones in the same catalogue, and every place the catalogue is
displayed shows `segment = "Combined"` plainly rather than pretending it's one of the two specific
segments.

## Data capture: Structure: Segments & Markets

The "DNA outcomes (optional)" section on the Structure page lets an analyst map either the split
columns or a combined column, with a per-outcome value weight. On save, the page builds the full
catalogue (`fh_outcomes_from_spec(...) + dna_outcomes_from_columns(...)`), validates it
(`validate_outcome_definitions`), and stores it in session state - then renders it back as an outcome
catalogue table (`outcomes_to_dataframe`) with the run-aware `status` column (see "Scope boundary"
above), so what's captured vs. what's actually driving the fitted model is never left for the analyst
to infer.

This is deliberately part of the existing Structure page, not a new workflow step - it's additional,
optional data capture alongside the FH segment mapping already there, not a new stage in the guided
workflow.

## Product-aware outputs

Every response/CPA/scenario/optimisation output that could combine Family History GSAs and DNA kit
sales keeps them separate instead - the instruction document's "do not expose a generic total volume
that adds kits and GSAs" / "CPA must identify its denominator" requirements, and the audit-confirmed
`volume_objective_mixes_units` defect this closed. `meta.kit_only_outcome_ids`
(`direct_dna_outcome_ids` minus `dna_outcome_id`) is, by construction, exactly the set of outcome_ids
with `OutcomeDefinition.product == DNA` - so `core.predict`/`core.market_specific_predict` can split
`fh_response`/`dna_response` on every curve using only `FHModelMeta`, without importing
`core.outcomes` (avoids a new coupling/import-cycle risk). From there:
`core.media_units.compute_cpa_by_product` (never `compute_cpa`'s bare `"overall_response"` default on
a curve that genuinely mixes both - it raises unless the caller passes `allow_mixed=True`),
`core.optimization.evaluate_scenario`'s `fh_gsa`/`dna_kits`/`avg_cpa`/`dna_avg_cpa`/`total_value`
columns, and `core.optimization.VALID_OBJECTIVES` (`"fh_gsa"`, `"dna_kits"`, `"weighted_mix"`,
`"expected_value"` - no generic "maximise volume") all follow the same discipline. See
`docs/dna_fh_causal_structure.md` and `docs/decision_log.md` for the full treatment.

## Persistence

`config/outcome_definitions.json` in the project bundle (`core.persistence.export_project` /
`import_project`), following the same "absent means legacy, not corrupt" convention as
`market_spec_config.json` and `model_type.json`: a bundle exported before this schema existed simply
has no such file, `import_project` reports `outcome_definitions: None`, and every downstream reader
calls `resolve_outcome_definitions` rather than assuming the key is populated.

`core.persistence.reconstruct_model_state` rebuilds a reimported project's modelling frame from the
*same* outcome catalogue the original fit used - `resolve_outcome_definitions(imported.get(
"outcome_definitions"), ...)`, filtered to outcomes whose `source_column` is still present in
`transformed_data`, passed as `prepare_fh_modeling_frame`'s `outcomes=` argument (which itself filters
to `included_in_fit=True` via `included_outcomes()`). Because `included_in_fit` is now persisted on
each `OutcomeDefinition` rather than being session-only state, a reimported project reconstructs the
*exact* set of outcomes that were included at fit time - both the pre-PR-E "reconstruction silently
drops DNA-kit segments" defect and the "excluded_outcome_ids isn't persisted" gap are closed by the
same change: exclusion is now data the bundle carries, not a preference the session held.
`outcome_catalogue_at_fit` on `FHModelMeta` (round-tripped through the bundle as part of `model_meta.json`,
restored to real `OutcomeDefinition` instances on import) additionally records the *exact* catalogue a
fit was built from, for future staleness-detection use.

**Which outcome_ids are included IS part of the model-specification fingerprint.** Once DNA response
equations shipped (the direct/halo pathway split, `docs/dna_fh_causal_structure.md`), which DNA-kit
outcomes are actually included in a fit became genuinely model-relevant: it changes
`FHModelMeta.outcome_ids`/`direct_dna_outcome_ids` without touching `model_spec`, prior config,
pipeline steps, or the raw data at all. `core.fingerprint.fingerprint_model_spec`'s
`direct_dna_outcome_ids` parameter (fed the fitted model's own `meta.direct_dna_outcome_ids`, sorted so
order never matters) covers this - an approval never stays "matching" across two fits that differed
only in which DNA-kit outcomes were included. Editing the outcome catalogue's *descriptive* fields
(metric label, value weight) without changing which outcome_ids actually get fit still does not touch
the fingerprint - only a change to what gets included in the next fit does, via
`direct_dna_outcome_ids`. Not yet fingerprinted: the exact source column mapped to each included
outcome_id (only *which outcome_ids* are included is covered) - a documented residual gap, see
`core.fingerprint.fingerprint_model_spec`'s docstring.

## Project report

The report's "Outcomes" section (`core.report._outcomes_section`) lists the full catalogue via
`resolve_outcome_definitions` and states plainly how many outcomes are Family History (modelled) vs.
DNA (captured, not yet modelled) - available at any point in the workflow, like every other report
section.

## Synthetic demo data

`ancestry_mmm/sample_data/generate_sample_data.py` generates `DNA_Kit_New_Customer` and
`DNA_Kit_Existing_FH_Customer` weekly count columns per market, driven by DNA-targeted media
response, seasonality (DNA kits are a strong gifting item - Christmas/New Year dominates more here
than in the FH outcomes), promotion, and kit price - a distinct synthetic series from the existing
`GSA_DNA_CrossSell` Family History signup metric, not a copy of it. This exists so the demo project
can exercise the split-outcome capture path end-to-end; it is not a causal simulation of DNA-to-FH
linkage (there isn't one yet - see the scope boundary above).
