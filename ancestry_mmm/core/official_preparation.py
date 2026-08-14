"""Official preparation contracts for the current rectangular model path.

This module is deliberately small and framework-independent.  It joins the
native source tables on their governed union of keys, applies only deterministic
non-missingness pipeline steps, and reports which source-backed variables the
compiled model actually consumes.  It does not fill, interpolate, allocate,
drop, or infer missing values.

The existing Transform Pipeline remains an exploratory utility.  The official
path calls :func:`prepare_canonical_native_frame` explicitly so an old inner
join cannot become the official model input by accident.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

import pandas as pd

from .activities import ActivityDefinition
from .coverage import VariableCoverageMatrix, VariableCoverageRecord
from .market_data_capability import (
    EngineCapabilityResult,
    check_market_channel_capability,
)
from .outcomes import OutcomeDefinition, included_outcomes
from .schema import ModelSpec
from .search_objects import (
    SearchObjectDefinition,
    current_search_object_versions,
)


OFFICIAL_ALLOWED_PIPELINE_OPS = frozenset(
    {
        "rename_column",
        "cast_type",
        "calculated_column",
        "lag_variable",
        "event_flag",
        "promotion_event",
    }
)
OFFICIAL_REJECTED_PIPELINE_OPS = frozenset({"fill_missing", "drop_columns"})


@dataclass(frozen=True)
class ConsumedVariable:
    """One source-backed variable consumed by the current model proposal."""

    variable_id: str
    roles: tuple[str, ...]
    source_columns: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GeneratedTerm:
    """A deterministic model term that is not a source coverage record."""

    variable_id: str
    origin: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class VariableCapability:
    variable_id: str
    roles: tuple[str, ...]
    status: str
    issues: tuple[str, ...] = ()
    markets_with_records: tuple[str, ...] = ()

    @property
    def supported(self) -> bool:
        return self.status == "supported"

    def to_dict(self) -> dict:
        return {
            "variable_id": self.variable_id,
            "roles": list(self.roles),
            "status": self.status,
            "supported": self.supported,
            "issues": list(self.issues),
            "markets_with_records": list(self.markets_with_records),
        }


@dataclass(frozen=True)
class OfficialCapabilityReport:
    """Coverage and engine evidence for exactly the variables used by a fit."""

    engine: EngineCapabilityResult
    consumed_variables: tuple[VariableCapability, ...]
    generated_terms: tuple[GeneratedTerm, ...]
    coverage_matrix_fingerprint: Optional[str]

    @property
    def supported(self) -> bool:
        return self.engine.supported and all(
            item.supported for item in self.consumed_variables
        )

    @property
    def blocking_issues(self) -> tuple[str, ...]:
        variable_issues = tuple(
            f"{item.variable_id}: {issue}"
            for item in self.consumed_variables
            for issue in item.issues
        )
        engine_issues = tuple(
            f"{issue.market} / {issue.channel}: {issue.reason}"
            for issue in self.engine.issues
        )
        return variable_issues + engine_issues

    def to_dict(self) -> dict:
        return {
            "engine": self.engine.to_dict(),
            "supported": self.supported,
            "blocking_issues": list(self.blocking_issues),
            "consumed_variables": [item.to_dict() for item in self.consumed_variables],
            "generated_terms": [item.to_dict() for item in self.generated_terms],
            "coverage_matrix_fingerprint": self.coverage_matrix_fingerprint,
        }


@dataclass(frozen=True)
class CanonicalNativeFrame:
    """The official native-frequency frame and its auditable join evidence."""

    frame: pd.DataFrame
    join_diagnostics: dict
    union_periods: tuple[str, ...]
    pipeline_ops: tuple[str, ...] = ()


def _as_activity(value: ActivityDefinition | Mapping[str, Any]) -> ActivityDefinition:
    return (
        value
        if isinstance(value, ActivityDefinition)
        else ActivityDefinition.from_dict(value)
    )


def _as_outcome(value: OutcomeDefinition | Mapping[str, Any]) -> OutcomeDefinition:
    return (
        value
        if isinstance(value, OutcomeDefinition)
        else OutcomeDefinition.from_dict(value)
    )


def _as_search(
    value: SearchObjectDefinition | Mapping[str, Any],
) -> SearchObjectDefinition:
    return (
        value
        if isinstance(value, SearchObjectDefinition)
        else SearchObjectDefinition.from_dict(value)
    )


def _generated_pipeline_columns(
    pipeline_steps: Iterable[Mapping[str, Any]],
) -> set[str]:
    generated: set[str] = set()
    for step in pipeline_steps:
        op = str(step.get("op", ""))
        params = step.get("params") or {}
        if op in {"calculated_column", "lag_variable", "event_flag"}:
            column = params.get("new_column")
            if column:
                generated.add(str(column))
        elif op == "promotion_event":
            event = params.get("event") or {}
            segment = event.get("segment")
            if segment:
                generated.add(
                    f"{params.get('column_prefix', '_promo_event_')}{segment}"
                )
    return generated


def collect_consumed_variables(
    spec: ModelSpec,
    outcomes: Sequence[OutcomeDefinition | Mapping[str, Any]],
    *,
    activity_definitions: Sequence[ActivityDefinition | Mapping[str, Any]] = (),
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
    pipeline_steps: Sequence[Mapping[str, Any]] = (),
) -> tuple[tuple[ConsumedVariable, ...], tuple[GeneratedTerm, ...]]:
    """Resolve the source-backed columns used by the current fit proposal.

    Resolution is exact and schema-driven.  It never uses substring matching
    on labels such as ``Search`` or ``DNA``.  Fourier and trend terms, plus
    deterministic columns declared by the pipeline, are reported separately
    and do not require a source coverage record.
    """

    generated_columns = _generated_pipeline_columns(pipeline_steps)
    variables: dict[str, dict[str, set[str]]] = {}

    def add(variable_id: str, role: str, source_column: str | None = None) -> None:
        if not variable_id or variable_id in generated_columns:
            return
        item = variables.setdefault(variable_id, {"roles": set(), "sources": set()})
        item["roles"].add(role)
        if source_column:
            item["sources"].add(source_column)

    fit_outcomes = included_outcomes([_as_outcome(item) for item in outcomes])
    outcome_by_id = {outcome.outcome_id: outcome for outcome in fit_outcomes}
    for outcome in fit_outcomes:
        add(outcome.source_column, "outcome", outcome.source_column)

    activity_by_input: dict[str, list[ActivityDefinition]] = {}
    for raw_activity in activity_definitions:
        activity = _as_activity(raw_activity)
        activity_by_input.setdefault(activity.resolved_model_input_column, []).append(
            activity
        )
    for channel in spec.channels:
        activities = activity_by_input.get(channel, [])
        if activities:
            for activity in activities:
                add(channel, "media", activity.source)
        else:
            add(channel, "media", channel)

    control_columns: list[str] = list(spec.control_cols)
    for columns in spec.product_control_cols.values():
        control_columns.extend(columns)
    for columns in spec.segment_control_cols.values():
        control_columns.extend(columns)
    for columns in spec.outcome_control_cols.values():
        control_columns.extend(columns)
    for column in dict.fromkeys(control_columns):
        add(column, "control", column)

    for outcome_id, outcome in outcome_by_id.items():
        promo_column = (spec.outcome_promo_cols or {}).get(outcome_id) or (
            spec.promo_cols or {}
        ).get(outcome.segment)
        if promo_column:
            add(promo_column, "promotion", promo_column)

    for raw_search in current_search_object_versions(search_objects):
        if (
            raw_search.model_input_column
            and raw_search.model_input_column in spec.channels
        ):
            add(raw_search.model_input_column, "search", raw_search.source_column)

    consumed = tuple(
        ConsumedVariable(
            variable_id=variable_id,
            roles=tuple(sorted(values["roles"])),
            source_columns=tuple(sorted(values["sources"])),
        )
        for variable_id, values in sorted(variables.items())
    )
    generated = tuple(
        GeneratedTerm(variable_id=column, origin="transform_pipeline")
        for column in sorted(generated_columns)
    ) + (
        GeneratedTerm(variable_id="fourier", origin="calendar seasonality"),
        GeneratedTerm(
            variable_id="trend", origin="market-relative deterministic trend"
        ),
    )
    return consumed, generated


def build_official_capability_report(
    spec: ModelSpec,
    outcomes: Sequence[OutcomeDefinition | Mapping[str, Any]],
    coverage_matrix: Optional[VariableCoverageMatrix],
    *,
    activity_definitions: Sequence[ActivityDefinition | Mapping[str, Any]] = (),
    search_objects: Sequence[SearchObjectDefinition | Mapping[str, Any]] = (),
    pipeline_steps: Sequence[Mapping[str, Any]] = (),
) -> OfficialCapabilityReport:
    """Build capability evidence for every source-backed consumed variable.

    Gaps on variables not consumed by this proposal are deliberately ignored.
    A missing record, unresolved coverage, or non-observed treatment on a
    consumed variable is a blocking issue.  The existing rectangular
    market-by-media check is retained as an engine-specific sub-report.
    """

    consumed, generated = collect_consumed_variables(
        spec,
        outcomes,
        activity_definitions=activity_definitions,
        search_objects=search_objects,
        pipeline_steps=pipeline_steps,
    )
    engine = check_market_channel_capability(
        spec.markets, spec.channels, coverage_matrix
    )
    by_variable_market: dict[tuple[str, str], list[VariableCoverageRecord]] = {}
    if coverage_matrix is not None:
        for record in coverage_matrix.records:
            by_variable_market.setdefault(
                (record.variable_id, record.market), []
            ).append(record)

    capabilities: list[VariableCapability] = []
    for variable in consumed:
        issues: list[str] = []
        markets_with_records: list[str] = []
        for market in spec.markets:
            records = list(by_variable_market.get((variable.variable_id, market), []))
            records.extend(by_variable_market.get((variable.variable_id, "*"), []))
            if not records:
                issues.append(
                    f"no coverage record for consumed {','.join(variable.roles)} "
                    f"variable in market {market!r}"
                )
                continue
            markets_with_records.append(market)
            if any(record.is_officially_unresolved for record in records):
                issues.append(
                    f"unresolved unknown/missing_expected coverage in market {market!r}"
                )
        status = "supported" if not issues else "unsupported"
        capabilities.append(
            VariableCapability(
                variable_id=variable.variable_id,
                roles=variable.roles,
                status=status,
                issues=tuple(issues),
                markets_with_records=tuple(markets_with_records),
            )
        )

    return OfficialCapabilityReport(
        engine=engine,
        consumed_variables=tuple(capabilities),
        generated_terms=generated,
        coverage_matrix_fingerprint=(
            coverage_matrix.fingerprint() if coverage_matrix is not None else None
        ),
    )


class OfficialPreparationDataError(ValueError):
    """Raised when the official native-frequency path cannot be used safely."""


def prepare_canonical_native_frame(
    sources: Mapping[str, pd.DataFrame],
    *,
    date_col: str,
    market_col: Optional[str],
    governed_start: str,
    governed_end: str,
    governed_frequency: str,
    pipeline_steps: Sequence[Mapping[str, Any]] = (),
) -> CanonicalNativeFrame:
    """Prepare an official frame from already-canonical native source tables.

    The join is explicitly an outer join over the union of source keys and is
    clipped only to the explicitly governed project window.  It never uses an
    inner intersection and never fills or drops missing observations.  This
    function is intentionally limited to a weekly target; the mixed-frequency
    assessor must resolve any other target through an approved method first.
    """

    if governed_frequency.strip().lower() != "weekly":
        raise OfficialPreparationDataError(
            "The current official native path only supports an explicitly "
            "governed weekly calendar; other frequencies require a separate "
            "approved preparation method."
        )
    if not sources:
        raise OfficialPreparationDataError("At least one source is required.")

    start = pd.Timestamp(governed_start)
    end = pd.Timestamp(governed_end)
    if start > end:
        raise OfficialPreparationDataError(
            "governed_start must not be after governed_end"
        )

    prepared_sources: dict[str, pd.DataFrame] = {}
    for source_id, source in sources.items():
        if date_col not in source.columns:
            raise OfficialPreparationDataError(
                f"Source {source_id!r} has no governed date column {date_col!r}."
            )
        if market_col and market_col not in source.columns:
            raise OfficialPreparationDataError(
                f"Source {source_id!r} has no governed market column {market_col!r}."
            )
        typed = source.copy()
        typed[date_col] = pd.to_datetime(typed[date_col])
        typed = typed[(typed[date_col] >= start) & (typed[date_col] <= end)]
        prepared_sources[str(source_id)] = typed

    # Local imports keep the data pipeline independent from this governance
    # module while reusing its audited diagnostics shape.
    from ancestry_mmm.data.pipeline import join_sources_with_diagnostics

    try:
        joined, diagnostics = join_sources_with_diagnostics(
            prepared_sources,
            date_col=date_col,
            market_col=market_col,
            how="outer",
        )
    except ValueError as exc:
        raise OfficialPreparationDataError(str(exc)) from exc

    # Materialise the explicitly governed weekly key grid so a week absent
    # from every source is still represented as missing.  This adds no values
    # and does not classify the gap; it makes the governed support boundary
    # visible to coverage review instead of allowing an all-source omission
    # to disappear from the frame.
    governed_dates = pd.date_range(start=start, end=end, freq="7D")
    if market_col:
        markets = sorted(
            {
                value
                for source in prepared_sources.values()
                for value in source[market_col].dropna().unique()
            },
            key=str,
        )
        if markets:
            key_grid = pd.MultiIndex.from_product(
                [governed_dates, markets], names=[date_col, market_col]
            ).to_frame(index=False)
        else:
            key_grid = pd.DataFrame(columns=[date_col, market_col])
    else:
        key_grid = pd.DataFrame({date_col: governed_dates})
    if not key_grid.empty:
        joined = key_grid.merge(
            joined,
            on=[date_col] + ([market_col] if market_col else []),
            how="left",
            sort=True,
        )

    for raw_step in pipeline_steps:
        op = str(raw_step.get("op", ""))
        if op in OFFICIAL_REJECTED_PIPELINE_OPS:
            raise OfficialPreparationDataError(
                f"Transform operation {op!r} is exploratory-only and cannot "
                "be consumed by official preparation. Missingness remains "
                "missing until an approved treatment exists."
            )
        if op not in OFFICIAL_ALLOWED_PIPELINE_OPS:
            raise OfficialPreparationDataError(
                f"Transform operation {op!r} is not approved for the official "
                "native-frequency path."
            )

    if pipeline_steps:
        from ancestry_mmm.data.pipeline import apply_pipeline, pipeline_from_json

        joined = apply_pipeline(
            joined, pipeline_from_json([dict(step) for step in pipeline_steps])
        )

    union_periods = tuple(
        sorted(
            pd.to_datetime(joined[date_col]).dropna().dt.strftime("%Y-%m-%d").unique()
        )
    )
    return CanonicalNativeFrame(
        frame=joined,
        join_diagnostics=diagnostics.to_dict(),
        union_periods=union_periods,
        pipeline_ops=tuple(str(step.get("op", "")) for step in pipeline_steps),
    )
