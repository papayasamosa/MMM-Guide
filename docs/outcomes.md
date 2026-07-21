# Outcome Schema

Design record for `core.outcomes` - the generalised outcome catalogue that lets the tool describe
*what's being measured* (product, segment, metric, source column, value weight) as explicit
dimensions, rather than assuming every measurable outcome is a Family History segment.

## Why this exists

Before this schema, "outcome" meant exactly one thing: an entry in `ModelSpec.segment_outcomes`,
implicitly a Family History GSA column. That's correct for what the fitted model predicts today, but
it can't represent DNA kit purchases - a genuinely different business outcome (a product sale, not a
Family History signup) with its own economics. `core.outcomes.OutcomeDefinition` adds an explicit
`product` dimension (`"Family History"` or `"DNA"`) alongside `segment`, `metric`, `column`, and an
optional `value_weight`, so the catalogue can describe both without forcing DNA data into a shape
built for FH segments.

## Scope boundary: captured, not modelled

**This is a data-capture and persistence layer, not a modelling change.** `ModelSpec` and the fitted
model are completely unchanged - a project's actual joint FH model still fits exactly the segments in
`ModelSpec.segment_outcomes`, exactly as before. DNA outcomes mapped through this schema are stored
and shown, but nothing in `core.hierarchical_model`, `core.market_specific_model`,
`core.predict`, or `core.market_specific_predict` reads them.

`core.outcomes.outcome_is_modelled(outcome)` is the single source of truth for this boundary -
`True` only for a `"Family History"`-product outcome. Every place the outcome catalogue reaches the
UI (Structure page, project report) shows a `modelled_today` column or an explicit caption built from
this function, rather than letting a DNA row imply it's already influencing planning outputs. DNA
response equations, and the causal linkage between DNA kit sales and FH cross-sell (so the same
effect isn't counted twice), are a separate, later piece of work - see `docs/decision_log.md` for
where this fits in the overall sequencing.

## The schema

```python
OutcomeDefinition(
    outcome_id="fh_new",
    product="Family History",
    segment="New",
    metric="GSA",
    column="GSA_New",
    value_weight=180.0,   # LTV - optional
)

OutcomeDefinition(
    outcome_id="dna_new_kit",
    product="DNA",
    segment="New Customer",
    metric="Kit sale",
    column="DNA_Kit_New_Customer",
    value_weight=90.0,    # value per kit - optional
)
```

`product` is one of `core.outcomes.FAMILY_HISTORY` / `core.outcomes.DNA`. DNA `segment` is one of
`DNA_SEGMENT_NEW` ("New Customer"), `DNA_SEGMENT_EXISTING_FH` ("Existing FH Customer"), or
`DNA_SEGMENT_COMBINED` ("Combined") - see below.

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
catalogue table (`outcomes_to_dataframe`) with the `modelled_today` column, so what's captured vs.
what's actually driving the fitted model is never left for the analyst to infer.

This is deliberately part of the existing Structure page, not a new workflow step - it's additional,
optional data capture alongside the FH segment mapping already there, not a new stage in the guided
workflow.

## Persistence

`config/outcome_definitions.json` in the project bundle (`core.persistence.export_project` /
`import_project`), following the same "absent means legacy, not corrupt" convention as
`market_spec_config.json` and `model_type.json`: a bundle exported before this schema existed simply
has no such file, `import_project` reports `outcome_definitions: None`, and every downstream reader
calls `resolve_outcome_definitions` rather than assuming the key is populated.

**Not part of the model-specification fingerprint.** Per the same descriptive/model-relevant boundary
`core.fingerprint` already draws for market descriptors, the outcome catalogue doesn't feed any
calculation today, so mapping or editing a DNA outcome does not invalidate an existing model approval.
If DNA outcomes become model-relevant once DNA response equations exist, that's the point at which
they join the fingerprint - the same "adding a genuinely model-relevant field is an intentional
breaking change" pattern used throughout `core.fingerprint`.

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
