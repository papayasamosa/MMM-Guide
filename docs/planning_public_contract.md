# Planning Public Contract

**Generated:** 28 July 2026  
**Purpose:** Document every public class exported from `core.optimization` and `core.planning` to ensure contract equivalence during the PR 51A consolidation.

## OutcomeValueMapping

### Fields

| Field | Type | Default | Active (optimization.py) | Extracted (planning/value.py) | Resolved |
|---|---|---|---|---|---|
| `value_by_outcome_id` | `Mapping[str, float]` | required | ✓ | ✓ (but weaker validation) | Must use active |
| `currency_by_outcome_id` | `Mapping[str, str]` | required | ✓ | ✓ | Must match |
| `mapping_id` | `str` | `"default"` | ✓ | ✓ | Same |
| `mapping_fingerprint` | `str` | `""` | ✓ | ✓ (silently overwritten) | Must raise on mismatch |
| `source` | `str` | `"outcome_catalogue"` | ✓ | ✓ | Same |

### Validation (active)
- Rejects `None`, NaN, +inf, -inf (`not np.isfinite(val)`)
- Rejects negative values
- Validates 3-letter uppercase ISO currency
- Rejects caller-supplied fingerprint mismatch (raises `ValueError`)
- `fingerprint` is a **property** (always recalculated)
- `_calculate_fingerprint()` is private method

### Methods (active)
- `fingerprint` (property) — authoritative fingerprint
- `to_dict()` — serialisation
- `from_dict(d)` — deserialisation
- `from_legacy_segment_ltv(segment_by_outcome_id, segment_ltv, currency, *, outcome_ids)` — strict class method adapter

### Methods (extracted)
- `_compute_fingerprint()` — different name
- `to_dict()` — present
- `from_dict(d)` — present
- `legacy_segment_ltv_to_value_mapping(...)` — free function, not class method; defaults missing values to 0.0

## CurrencyContext

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `market_reporting_currency` | `str` | `""` | ✓ | ✓ | Same |
| `value_currency` | `str \| None` | `None` | ✓ | ✓ | Same |
| `group_reporting_currency` | `str \| None` | `None` | ✓ | ✓ | Same |
| `model_currency` | `str \| None` | `None` | ✓ | ✓ | Same |
| `historical_fx_rate_set_id` | `str \| None` | `None` | ✓ | ✓ | Same |
| `historical_fx_rate_set_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `future_fx_assumption_id` | `str \| None` | `None` | ✓ | ✓ | Same |
| `future_fx_assumption_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |

### Validation (active)
- ISO three-letter uppercase code validation
- `fingerprint()` method

Both versions appear equivalent.

## PlanningObjective

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `estimand` | `str` | `"incremental_outcome"` | ✓ | ✓ | Same |
| `metric_key` | `str` | `""` | ✓ | ✓ | Same |
| `target_outcome_ids` | `Tuple[str, ...]` | `()` | ✓ | ✓ | Same |
| `value_currency` | `Optional[str]` | `None` | ✓ | **MISSING** | Must add |
| `spend_scope` | `str` | `"cost_bearing_decisions"` | ✓ | **MISSING** | Must add |
| `activity_scope` | `str` | `"optimisable_interventions"` | ✓ | **MISSING** | Must add |
| `counterfactual_policy_fingerprint` | `Optional[str]` | `None` | ✓ | **MISSING** | Must add |
| `schema_version` | `int` | `3` | ✓ | **MISSING** | Must add |
| `weight_by_outcome_id` | `Optional[Mapping]` | **MISSING** | **EXTRA** | ✓ | Must remove from extracted |

### Methods (active)
- `to_dict()` — uses `asdict`
- `from_dict(d)` — handles list→tuple migration for `target_outcome_ids`
- `is_valid_for_official_planning` (property)
- `planning_objective_from_legacy()` — free function for legacy migration

### Methods (extracted)
- `to_dict()` — different format (manual dict)
- `from_dict(d)` — present
- `fingerprint()` — extra method not in active
- `is_valid_for_official_planning` (property)

### Validation (active)
- `estimand` must be in `PLANNING_ESTIMANDS`
- `incremental_value` requires `value_currency`
- Rejects duplicate `target_outcome_ids`

## ResolvedOutcomeAuthorisation

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `outcome_id` | `str` | required | ✓ | ✓ | Same |
| `requested_use` | `str` | required | ✓ | ✓ | Same |
| `approval_id` | `str` | required | ✓ | ✓ | Same |
| `definition_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `market` | `Optional[str]` | `None` | ✓ | ✓ | Same |
| `product` | `Optional[str]` | `None` | ✓ | ✓ | Same |
| `segment` | `Optional[str]` | `None` | ✓ | ✓ | Same |
| `nbt_completeness_fingerprint` | `Optional[str]` | `None` | ✓ | ✓ | Same |

Both versions appear equivalent.

## ResolvedPlanningGovernance

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `governance_mode` | `str` | required | ✓ | ✓ | Same |
| `operation` | `str` | required | ✓ | ✓ | Same |
| `objective_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `model_run_id` | `str` | required | ✓ | ✓ | Same |
| `data_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `model_spec_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `posterior_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `market` | `str` | required | ✓ | ✓ | Same |
| `authorisations` | `Tuple[ResolvedOutcomeAuthorisation, ...]` | required | ✓ | ✓ | Same |
| `model_approval_fingerprint` | `str` | `""` | ✓ | ✓ | Same |
| `target_outcome_ids` | `Tuple[str, ...]` | `()` | ✓ | ✓ | Same |

Both versions appear equivalent.

## ScenarioGovernanceDependencies

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `model_run_id` | `str` | required | ✓ | ✓ | Same |
| `model_approval_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `data_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `model_spec_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `posterior_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `planning_objective_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `outcome_authorisations` | `tuple[...]` | required | ✓ | ✓ | Same |
| `value_mapping_id` | `str \| None` | `None` | ✓ | ✓ | Same |
| `value_mapping_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `currency_context_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `historical_fx_rate_set_id` | `str \| None` | `None` | ✓ | ✓ | Same |
| `historical_fx_rate_set_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `future_fx_assumption_id` | `str \| None` | `None` | ✓ | ✓ | Same |
| `future_fx_assumption_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `activity_definitions_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `cost_mapping_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `counterfactual_policy_fingerprint` | `str` | `""` | ✓ | ✓ | Same |
| `nbt_completeness_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |

Both versions appear equivalent.

## ScenarioEvaluationResult

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `predicted` | `pd.DataFrame` | required | ✓ | ✓ | Same |
| `planning_objective` | `PlanningObjective \| None` | required | ✓ | ✓ (string fwd ref) | Same |
| `governance_mode` | `str` | required | ✓ | ✓ | Same |
| `artefact_kind` | `str` | required | ✓ | ✓ | Same |
| `resolved_governance` | `ResolvedPlanningGovernance \| None` | `None` | ✓ | ✓ | Same |
| `governance_dependencies` | `ScenarioGovernanceDependencies \| None` | `None` | ✓ | ✓ | Same |
| `activity_definitions_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `cost_mapping_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `counterfactual_policy_fingerprint` | `str` | `""` | ✓ | ✓ | Same |
| `economics_coverage` | `dict \| None` | `None` | ✓ | ✓ | Same |

Both versions appear equivalent.

## ScenarioValidationContext

### Fields

| Field | Type | Default | Active | Extracted | Resolved |
|---|---|---|---|---|---|
| `model_run_id` | `str` | required | ✓ | ✓ | Same |
| `model_approval_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `data_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `model_spec_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `posterior_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `planning_objective` | `PlanningObjective` | required | ✓ | ✓ | Same |
| `outcome_definitions` | `tuple` | required | ✓ | ✓ | Same |
| `outcome_approvals` | `tuple` | required | ✓ | ✓ | Same |
| `counterfactual_fingerprint` | `str` | required | ✓ | ✓ | Same |
| `value_mapping_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `currency_context_fingerprint` | `str \| None` | `None` | ✓ | ✓ | Same |
| `activity_fingerprint` | `Optional[str]` | `None` | ✓ | ✓ | Same |
| `cost_fingerprint` | `Optional[str]` | `None` | ✓ | ✓ | Same |
| `nbt_completeness_metadata` | `Optional[dict]` | `None` | ✓ | ✓ | Same |

Both versions appear equivalent.

## ScenarioDependencyIssue

### Fields (active)
- `artefact_id: str`
- `issue_type: str`
- `detail: str`
- `dependency_type: str`
- `reason_code: str`

### Fields (extracted)
- `category: str`
- `field: str`
- `message: str`
- `severity: str = "error"`

**COMPLETELY DIFFERENT SCHEMA** — must use active version.
