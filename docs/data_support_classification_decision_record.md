# Decision record: consolidated per-channel data-support classification (Decision 17)

**Resolves:** `REQ-DATASUPPORT-001`'s own deferred "precise module/
function consolidation architecture" question. Does **not** resolve, and
does not attempt to resolve: any concrete numeric threshold for any
evidence dimension, or the exact weighting/combination rule across
dimensions when they disagree - both explicitly excluded by the record
and never invented here.

## Context

Three modules each compute part of the evidence Decision 17 lists:
`core.prefit_identifiability` (whole-frame four-tier support status),
`core.coverage` (missingness vocabulary), `core.identification_
diagnostics` (collinearity). Repository audit for this record found a
**fourth**, pre-existing relevant source `REQ-DATASUPPORT-001`'s own
text does not name: `core.fold_data_support` (per-fold support
diagnostics, added 2026-08-26, whose own `SupportThresholds` dataclass -
not `core.prefit_identifiability.SupportThresholdPolicy`, a materially
different class the REQ record's "Capability status" section appears to
have conflated it with - defaults every field to `None`, matching the
REQ text's description of "fields already deliberately default to
None"). This record uses the real, correctly-attributed module.

## Decisions made

1. **Evidence assembly and severity judgement are two separate steps**,
   never merged. `assemble_data_support_evidence` performs the real
   integration work Decision 17 asks for - reading each existing
   module's already-computed output and mapping it onto the twelve
   named dimensions - but never converts a raw value (e.g. "14 non-zero
   weeks") into a concern judgement on its own. `severity_by_dimension`
   is always caller-supplied. This mirrors `core.prefit_identifiability.
   PriorPredictiveThresholdPolicy`'s own "no instance used by default"
   discipline and `core.fold_data_support.SupportThresholds`'s "every
   field optional, no built-in default instance" discipline exactly.
2. **All twelve dimensions are always represented**, even when nothing
   is available (`available=False`, `severity="not_available"`) - two
   dimensions (`number_of_separate_activity_periods`, `correlation_
   with_trend_seasonality`) have no existing computing module at all
   today, and are recorded as such rather than silently omitted.
3. **The three-state rollup's default combination rule is worst-
   dimension-wins** (any severe-concern dimension forces `not_
   sufficient`; any moderate-concern dimension with none severe forces
   `weak`; otherwise `sufficient`) - a disclosed **structural**
   convention, not a numeric threshold and not asserted as approved
   business policy. `classify_data_support` accepts a caller-supplied
   `combination_policy` callable to replace it entirely, since `REQ-
   DATASUPPORT-001` explicitly excludes approving one combination rule
   over another.
4. **A non-sufficient classification always requires an explicit,
   closed-vocabulary governed response** (group into a higher-level
   channel / stronger regularisation / partial pooling / exclude but
   retain in aggregate) - construction fails closed if one is missing,
   mirroring `core.capacity.CapHitClassification`'s "never a bare
   categorical label" discipline (Requirement 3).
5. **Reasons are always the specific triggering dimension(s)**, never an
   unexplained categorical status (Requirement 4) - enforced structurally
   (a non-sufficient state without `reasons` raises).

## What this record does not do

- Modify `core.prefit_identifiability`, `core.coverage`, `core.
  identification_diagnostics`, or `core.fold_data_support` - all four
  remain read-only references, exactly as `REQ-DATASUPPORT-001`'s own
  "Affected modules" section names them.
- Compute any severity judgement from a number - every severity value in
  every test and example is caller-supplied, illustrating the contract
  rather than asserting an approved cutoff.
- Wire this classification into `pages/06_Diagnostics.py`, the fitting
  pipeline, or the optimiser - a future integration pass.

## Verification

`ancestry_mmm/tests/test_data_support_classification.py` (13 tests) -
all passing, including a regression test proving severity is never
invented merely because a raw value happens to be available.
