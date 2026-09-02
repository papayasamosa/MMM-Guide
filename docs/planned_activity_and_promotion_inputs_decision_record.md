# Decision record: planned marketing activity and promotion-period future inputs (Decision 14)

**Resolves:** the genuine, evidenced gap this session's investigation
found between Decision 14's approved text ("The analyst *should*
continue to supply: planned marketing activity, promotion periods, and
explicit governed overrides" - `REQ-FUTURE-001`'s 2026-08-30 addendum)
and the repository's actual current capability. No prior REQ record
names this gap; this record introduces `REQ-PLANACT-001` to reconcile
it, following this project's standard "read PRD/business decision text,
confirm no reservation, write REQ + decision record + implement + test"
discipline used for every prior Phase A/B/C/D/E item.

## Investigation findings

- **Planned marketing activity**: already fully satisfied by the
  existing spend-by-week plan (`core.optimization`'s spend plan,
  `pages/08_Scenario_Planner.py`'s manual tab) - an analyst already
  enters exactly this, in exactly the structured, explicit form Decision
  14 asks for. No new mechanism was needed here; this record adds only a
  lightweight, disclosure-only `PlannedActivity` record so a scenario's
  audit trail can name *which* scheduled activity a given week's spend
  corresponds to, never inferred from spend values or channel names.
- **Promotion periods**: genuinely missing a structured input.
  `core.planning.future_context.build_future_context`'s `promo_future`
  parameter already exists and is already always analyst-supplied
  (never the `hold_last_observed` relaxation available to exogenous
  controls - `REQ-SCEN-002`), but it is a raw `{outcome_id: {week_label:
  value}}` mapping: an analyst wanting to declare "a promotion runs from
  week X to week Y" must construct a per-week value by hand for every
  week in the plan window.

## Decision

Build the structured input `build_future_context` itself is missing,
without modifying it: `core.planning.planned_activity.PromotionPeriod`
(start week, end week, per-outcome intensity) plus `materialize_promo_
future`, a deterministic function producing the exact `promo_future`
shape `build_future_context` requires. Verified by a real end-to-end
test that constructs a `PromotionPeriod`, materialises it, and passes
the result into the actual, unmodified `build_future_context` - proving
genuine wiring, not a parallel unused contract.

**Overlap policy** (two promotion periods covering the same
outcome/week): `"sum"` is the default, with `"max"` and `"reject_
overlap"` also available via an explicit parameter. This is a disclosed
implementation default, not an invented business rule - no PRD or
business-decision text specifies overlap semantics, so this record does
not assert one as approved policy; a caller wanting different semantics
passes a different `overlap_policy` value.

`PlannedActivityAndPromotionInputs` is a governed, versioned, fingerprint-
bearing bundle of both record types, mirroring `core.planning.future_
assumption_bundle.FutureAssumptionBundle`'s lineage pattern - built as a
standalone sibling, not a modification to that module (which this record
leaves completely untouched, consistent with its own "not chosen by the
coding agent" bundle-architecture history already resolved separately).

## What this record does not do

- Modify `core.planning.future_context` or `core.planning.future_
  assumption_bundle` - both remain completely unchanged.
- Wire `PlannedActivity`/`PromotionPeriod` into `pages/08_Scenario_
  Planner.py`'s UI - a future integration pass, consistent with this
  project's established discipline throughout Phase C/D/E.
- Invent a value for any promotion's intensity or any activity's
  business effect - both are always caller-supplied.

## Verification

`ancestry_mmm/tests/test_planned_activity.py` (15 tests) - all passing,
including `TestMaterializePromoFutureIntegratesWithBuildFutureContext`,
a real end-to-end call into the unmodified, production `build_future_
context`.
