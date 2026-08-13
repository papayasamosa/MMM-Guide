"""Canonical-calendar and mixed-frequency alignment contracts
(REQ-COVERAGE-001 S4, Work Package C).

Completes the *architecture* needed for approved mixed-frequency
transformations, without inventing an unapproved statistical conversion
method. REQ-COVERAGE-001 S4 authorises variable-class-specific conversion
semantics but does not approve one concrete method for any variable class
(`docs/approved_requirements/REQ-COVERAGE-001.md`, "Out of scope"): "Any
specific imputation formula, interpolation kernel, or default fill method
not named in S4" remains unapproved. This module therefore defines:

- ``AlignmentSpecification``: the versioned, typed decision record S4
  requires (source frequency, target frequency, method, parameters, market
  scope, effective period, publication/release timing, reconciliation rule,
  support boundary) - distinct from a generic fill operation.
- a conversion-method registry/protocol (``register_conversion_method``/
  ``resolve_conversion_method``) that starts genuinely empty - no method is
  registered for any variable class, so every alignment request today
  resolves to an explicit ``unsupported_no_approved_method`` result, never a
  fabricated series. A future, separately-approved requirement (the brief's
  Work Package D) registers a concrete method once one is approved; this
  module does not anticipate what that method will be.
- leakage (publication-lag), definition-break, and support-boundary checks
  that operate on already-known inputs, independent of which (if any)
  method is eventually approved.
- ``resolve_canonical_calendar``: an explicit calendar built from governed
  configuration the caller supplies, never inferred from "whichever source
  has the shortest history". No governed project-calendar configuration
  object exists elsewhere in this repository today (`core.market_config.
  MarketSpecConfig` has no `project_start`/`project_end`/target-frequency
  field) - this function does not invent one. A caller without an explicit
  governed calendar decision gets ``CalendarResolutionRequiredError``,
  never a silently-inferred calendar from raw source intersection.

Deliberately NOT done here (REQ-COVERAGE-001 S4/"Out of scope", and this
brief's own Work Package C/D boundary):

- No conversion method (interpolation, allocation, forward-fill, ...) is
  implemented for any variable class.
- No conversion is wired into `data.pipeline.join_sources`/
  `join_sources_with_diagnostics` or the exploratory Transform Pipeline -
  those keep working exactly as before (explicit join mode + join-loss
  diagnostics, PR #157). The official-preparation boundary may call the
  read-only `assess_official_preparation` service below: while the registry
  is empty it returns an actionable decision-required result and never
  changes the native source or exploratory frame.
- No default project-calendar source (e.g. "whichever source has the
  longest/shortest history") is chosen - REQ-COVERAGE-001 S1's "never
  truncate to the narrowest common window" applies here too.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Dict, Optional, Tuple

import pandas as pd

from .coverage import (
    VARIABLE_CLASSES,
    DefinitionBreak,
    VariableCoverageMatrix,
    VariableCoverageRecord,
    _FREQUENCY_TO_PANDAS_ALIAS,
    official_fit_blocking_issues,
)

# --- Conversion-method registry (starts empty - see module docstring) -----


@dataclass(frozen=True)
class ConversionMethodSpec:
    """A registered, approved conversion method for one variable class.

    ``approved`` must be an explicit, attributed decision (mirrors
    `core.coverage.DefinitionBreak.bridge_treatment_approved`'s
    approval-requires-attribution pattern) - a method can be *registered*
    (so its shape/parameters are documented) without yet being *approved*
    for official use; `resolve_conversion_method` only ever returns a
    method where both are true.
    """

    method_id: str
    version: int
    variable_class: str
    description: str
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.method_id or not self.description:
            raise ValueError("method_id and description are required")
        if self.variable_class not in VARIABLE_CLASSES:
            raise ValueError(
                f"invalid variable_class {self.variable_class!r}; "
                f"must be one of {VARIABLE_CLASSES}"
            )
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if self.approved and not (self.approved_by and self.approved_at):
            raise ValueError(
                "an approved conversion method requires approved_by and approved_at"
            )

    def to_dict(self) -> dict:
        return asdict(self)


# evaluator_id-style registry (mirrors core.validation_policy._EVALUATOR_
# REGISTRY / register_evaluator): (variable_class, method_id) -> spec.
# Genuinely empty - no entry point in this module registers anything.
# Work Package D registers a concrete method here only once a modelling
# decision approves one; this module never does so itself.
_METHOD_REGISTRY: Dict[Tuple[str, str], ConversionMethodSpec] = {}


# Decision-support vocabulary for the official-preparation UI. This is not a
# method registry and must not be read as selecting a default. It is
# deliberately exhaustive over the closed variable-class vocabulary so an
# analyst can see exactly what still needs approval.
FREQUENCY_METHOD_DECISIONS_REQUIRED = {
    "flow_count": (
        "Select an approved flow/count conversion method (or explicitly keep "
        "the variable at native cadence).",
        "Define aggregation/reconciliation, publication-lag, support-boundary, "
        "and parameter rules.",
        "Define leakage, source-definition-break, and validation evidence for "
        "the selected method.",
    ),
    "stock_level": (
        "Select an approved stock/level conversion method (or explicitly keep "
        "the variable at native cadence).",
        "Define the level-preservation/reconciliation rule and boundary behaviour.",
        "Define publication-lag, definition-break, leakage, and validation "
        "evidence for the selected method.",
    ),
    "rate_index": (
        "Select an approved rate/index conversion method (or explicitly keep "
        "the variable at native cadence).",
        "Define the weighting/aggregation rule and support boundary.",
        "Define publication-lag, definition-break, leakage, and validation "
        "evidence for the selected method.",
    ),
    "survey_measurement": (
        "Select an approved survey/measurement treatment (native cadence, "
        "step repetition, or another governed method).",
        "Define release timing, uncertainty treatment, support boundary, and "
        "methodology-break handling.",
        "Define leakage and validation evidence for historical reconstruction "
        "and any official scenario use.",
    ),
    "event_flag": (
        "Select an approved event/flag treatment (full-period overlap, "
        "exact-date sub-period, native cadence, or another governed method).",
        "Define event-boundary and partial-period semantics.",
        "Define publication timing, definition-break handling, and validation "
        "evidence.",
    ),
}


def register_conversion_method(
    spec: ConversionMethodSpec,
) -> None:
    """Register a conversion method spec. Never called by this module
    itself - reserved for a future, separately-approved dependent package
    (this brief's Work Package D) to call once a method is approved."""
    _METHOD_REGISTRY[(spec.variable_class, spec.method_id)] = spec


def resolve_conversion_method(
    variable_class: str, method_id: Optional[str] = None
) -> Optional[ConversionMethodSpec]:
    """The approved method for ``variable_class`` (optionally a specific
    ``method_id``), or ``None`` if none is registered/approved. Never
    guesses a default method across variable classes (REQ-COVERAGE-001 S4:
    "a single default method must never be applied across classes")."""
    if method_id is not None:
        spec = _METHOD_REGISTRY.get((variable_class, method_id))
        return spec if spec is not None and spec.approved else None
    for (vc, _mid), spec in _METHOD_REGISTRY.items():
        if vc == variable_class and spec.approved:
            return spec
    return None


def registered_method_count() -> int:
    """Test/diagnostic helper - how many methods are currently registered
    (approved or not), across every variable class."""
    return len(_METHOD_REGISTRY)


# --- AlignmentSpecification (REQ-COVERAGE-001 S4's typed decision record) -


@dataclass(frozen=True)
class AlignmentSpecification:
    """The versioned, typed frequency-conversion decision record S4
    requires - distinct from a generic fill operation. Describing a
    conversion request does not itself perform one; `evaluate_alignment_
    request` below is the only thing that resolves a specification to a
    result, and it never fabricates data for an unsupported request."""

    variable_id: str
    source_id: str
    source_version: int
    market: str
    native_frequency: str
    target_frequency: str
    variable_class: str
    publication_lag_periods: int = 0
    method_id: Optional[str] = None
    # The version of *this decision*, distinct from `source_version` (which
    # identifies the input source, not the alignment decision made about
    # it) - review finding: without this, two materially different
    # conversions of the same method_id (different parameters, different
    # effective period) would be indistinguishable in a persisted record.
    decision_version: int = 1
    # Method-specific configuration (e.g. an allocation weighting scheme's
    # parameters) - REQ-COVERAGE-001 S4 lists "parameters" as part of the
    # required decision record, distinct from the method identity itself.
    parameters: Dict[str, object] = field(default_factory=dict)
    reconciliation_rule: str = ""
    # The period *this specific alignment decision* applies to - distinct
    # from support_start/support_end below, which describe the underlying
    # variable's own observed/supported window (REQ-COVERAGE-001 S4 lists
    # "effective period" and "support boundary" as separate required
    # fields). Mirrors `core.search_objects`' effective-period convention
    # for governed, versioned decisions.
    effective_start: Optional[str] = None
    effective_end: Optional[str] = None
    support_start: Optional[str] = None
    support_end: Optional[str] = None
    definition_breaks: Tuple[DefinitionBreak, ...] = ()

    def __post_init__(self) -> None:
        if not self.variable_id or not self.source_id:
            raise ValueError("variable_id and source_id are required")
        if not self.market:
            raise ValueError("market is required; use '*' for all markets")
        if not self.native_frequency or not self.target_frequency:
            raise ValueError("native_frequency and target_frequency are required")
        if self.variable_class not in VARIABLE_CLASSES:
            raise ValueError(
                f"invalid variable_class {self.variable_class!r}; "
                f"must be one of {VARIABLE_CLASSES}"
            )
        if self.publication_lag_periods < 0:
            raise ValueError("publication_lag_periods must be >= 0")
        if self.decision_version < 1:
            raise ValueError("decision_version must be >= 1")
        for label, start, end in (
            ("support", self.support_start, self.support_end),
            ("effective", self.effective_start, self.effective_end),
        ):
            if start and end and date.fromisoformat(start) > date.fromisoformat(end):
                raise ValueError(f"{label}_start must not be after {label}_end")

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "definition_breaks"},
            "definition_breaks": [b.to_dict() for b in self.definition_breaks],
        }


# --- Checks (operate on already-known inputs; no method required) ---------


def check_publication_leakage(
    *,
    reconstructed_period_end: str,
    as_of: str,
    native_frequency: str,
    publication_lag_periods: int,
) -> bool:
    """REQ-COVERAGE-001 S4: "a historical transformation may only use
    information that was actually available as of the reconstructed
    period ... no forward-filling backward into pre-publication history."

    Returns ``True`` if using this variable to reconstruct
    ``reconstructed_period_end`` as of ``as_of`` would leak future
    information - i.e. the value would not actually have been published
    yet, given ``publication_lag_periods`` full periods of
    ``native_frequency`` must elapse after ``reconstructed_period_end``
    before the value is available (review finding: an earlier version of
    this function accepted ``publication_lag_periods`` but never actually
    used it, always comparing against the bare period end - silently
    admitting values before their governed release date).

    Reuses the same native-frequency alias mapping `core.coverage.
    build_coverage_matrix_from_frame` already uses for its own expected-
    calendar construction, and the same `pd.date_range`-based step
    counting, rather than inventing separate offset arithmetic. An
    unrecognised/irregular ``native_frequency`` has no fixed step to
    advance by - this fails closed (reports leakage) rather than assuming
    the lag has already elapsed.
    """
    period_end = pd.Timestamp(reconstructed_period_end)
    as_of_ts = pd.Timestamp(as_of)
    if publication_lag_periods <= 0:
        return bool(as_of_ts < period_end)
    alias = _FREQUENCY_TO_PANDAS_ALIAS.get(native_frequency.strip().lower())
    if alias is None:
        return True
    schedule = pd.date_range(
        start=period_end, periods=publication_lag_periods + 1, freq=alias
    )
    available_from = schedule[-1]
    return bool(as_of_ts < available_from)


def check_definition_break_crossing(
    *,
    period_start: str,
    period_end: str,
    definition_breaks: Tuple[DefinitionBreak, ...],
) -> Optional[DefinitionBreak]:
    """REQ-COVERAGE-001 S4: "interpolation must not cross a declared
    source-definition break unless an approved bridge treatment explicitly
    allows it." Returns the first blocking break (a break inside
    ``[period_start, period_end]`` whose bridge is not approved), or
    ``None`` if no break blocks this period."""
    start = date.fromisoformat(period_start)
    end = date.fromisoformat(period_end)
    for brk in definition_breaks:
        if brk.bridge_treatment_approved:
            continue
        break_date = date.fromisoformat(brk.break_date)
        if start <= break_date <= end:
            return brk
    return None


def check_support_boundary(
    *, period: str, support_start: Optional[str], support_end: Optional[str]
) -> bool:
    """REQ-COVERAGE-001 S1: "a partial-window variable retains explicit
    support limits - its unsupported history is not backfilled." Returns
    ``True`` iff ``period`` falls within the declared support window
    (``True`` when either bound is ``None`` - no declared boundary is not
    itself a violation, distinct from a period genuinely outside a
    declared boundary)."""
    period_date = date.fromisoformat(period)
    if support_start and period_date < date.fromisoformat(support_start):
        return False
    if support_end and period_date > date.fromisoformat(support_end):
        return False
    return True


# --- Alignment-request evaluation (never fabricates data) -----------------


ALIGNMENT_STATUSES = (
    "unsupported_no_approved_method",
    "unsupported_definition_break",
    "unsupported_leakage",
    "method_available",
)

# The only statuses that represent a genuinely usable outcome. Review
# finding: an earlier version hardcoded `AlignmentResult.supported` to
# always be `False`, so even the (then-unreachable) "a method was found"
# branch still reported unsupported - the extension point this module
# promises ("register a method, nothing else needs to change") was not
# actually honoured. `supported` is now derived from `status`, so the two
# can never disagree.
_SUPPORTED_STATUSES = frozenset({"method_available"})


@dataclass(frozen=True)
class AlignmentResult:
    """A deterministic report of whether ``spec`` can be officially
    resolved today (mirrors `core.market_data_capability.
    EngineCapabilityResult`'s shape for the same reason: never silently
    drop, approximate, or mask what cannot be officially converted; always
    name the specific reason).

    ``status="method_available"`` means an approved conversion method is
    registered for ``spec.variable_class`` and no known blocker (a
    definition break, or - when checkable - publication leakage) applies.
    It does NOT mean data has actually been converted: this module reports
    feasibility only, never executes a conversion - a dependent execution
    service (this brief's Work Package D and beyond) performs that,
    reading the resolved `ConversionMethodSpec` this result implies via
    `resolve_conversion_method`.
    """

    spec: AlignmentSpecification
    status: str
    reason: str

    def __post_init__(self) -> None:
        if self.status not in ALIGNMENT_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; must be one of {ALIGNMENT_STATUSES}"
            )

    @property
    def supported(self) -> bool:
        return self.status in _SUPPORTED_STATUSES

    def to_dict(self) -> dict:
        return {
            "spec": self.spec.to_dict(),
            "status": self.status,
            "reason": self.reason,
            "supported": self.supported,
        }


def evaluate_alignment_request(
    spec: AlignmentSpecification,
    *,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    as_of: Optional[str] = None,
) -> AlignmentResult:
    """Resolve ``spec`` against the current method registry and, when
    enough information is supplied, the definition-break and
    publication-leakage checks.

    In production, this returns ``unsupported_no_approved_method`` for
    every request today - see module docstring: no conversion method is
    approved for any variable class yet, so `resolve_conversion_method`
    never returns one there. Unlike an earlier version of this function,
    that is a live consequence of the registry being empty, not a
    hardcoded fallback: once a dependent, separately-approved package
    calls `register_conversion_method` with `approved=True`, this
    function's own logic already returns ``status="method_available"``
    for a matching request without needing to be rewritten.

    Checks run in this order, each capable of blocking independently of
    whether a method is ever approved: a definition break inside
    ``[period_start, period_end]`` (only checked when both are supplied);
    publication leakage as of ``as_of`` (only checked when ``as_of`` and
    ``period_end`` are both supplied); finally, method resolution.
    """
    if period_start is not None and period_end is not None:
        blocking_break = check_definition_break_crossing(
            period_start=period_start,
            period_end=period_end,
            definition_breaks=spec.definition_breaks,
        )
        if blocking_break is not None:
            return AlignmentResult(
                spec=spec,
                status="unsupported_definition_break",
                reason=(
                    f"A source-definition break on {blocking_break.break_date} "
                    f"falls inside [{period_start}, {period_end}] without an "
                    "approved bridge treatment (REQ-COVERAGE-001 S4)."
                ),
            )

    if period_end is not None and as_of is not None:
        leaks = check_publication_leakage(
            reconstructed_period_end=period_end,
            as_of=as_of,
            native_frequency=spec.native_frequency,
            publication_lag_periods=spec.publication_lag_periods,
        )
        if leaks:
            return AlignmentResult(
                spec=spec,
                status="unsupported_leakage",
                reason=(
                    f"Reconstructing the period ending {period_end} as of "
                    f"{as_of} would use information not yet published given "
                    f"{spec.publication_lag_periods} period(s) of publication "
                    "lag at this variable's native frequency "
                    f"({spec.native_frequency!r}) (REQ-COVERAGE-001 S4)."
                ),
            )

    method = resolve_conversion_method(spec.variable_class, spec.method_id)
    if method is None:
        return AlignmentResult(
            spec=spec,
            status="unsupported_no_approved_method",
            reason=(
                f"No approved conversion method is registered for variable "
                f"class {spec.variable_class!r} "
                f"({spec.native_frequency!r} -> {spec.target_frequency!r}). "
                "REQ-COVERAGE-001 S4 does not approve any specific method; "
                "a separately-approved modelling/statistics decision is "
                "required before this alignment can be resolved officially."
            ),
        )
    return AlignmentResult(
        spec=spec,
        status="method_available",
        reason=(
            f"Approved method {method.method_id!r} v{method.version} is "
            f"registered for variable class {spec.variable_class!r}. This "
            "module reports feasibility only - it does not execute the "
            "conversion; a dependent execution service performs that."
        ),
    )


# --- Canonical calendar (REQ-COVERAGE-001 S4: never an implicit inner-join
# intersection) -------------------------------------------------------------


class CalendarResolutionRequiredError(Exception):
    """Raised when no governed project-calendar configuration was supplied.
    Never caught internally and silently resolved to a guessed default -
    REQ-COVERAGE-001 S1 forbids inferring a calendar "from whichever source
    has the shortest history"; this repository currently has no governed
    project-calendar configuration object at all (`core.market_config.
    MarketSpecConfig` has no `project_start`/`project_end`/target-frequency
    field), so raising here is the honest, fail-closed outcome pending that
    decision - not a defect in this function."""


@dataclass(frozen=True)
class CanonicalCalendar:
    """An explicit, versioned project calendar - the resolved answer to
    "what dates does this project's model window actually cover", built
    from governed configuration rather than implicit source intersection.
    """

    start: str
    end: str
    frequency: str

    def __post_init__(self) -> None:
        if not self.start or not self.end or not self.frequency:
            raise ValueError("start, end and frequency are required")
        if date.fromisoformat(self.start) > date.fromisoformat(self.end):
            raise ValueError("start must not be after end")

    def to_dict(self) -> dict:
        return asdict(self)


def resolve_canonical_calendar(
    *,
    governed_start: Optional[str],
    governed_end: Optional[str],
    governed_frequency: Optional[str],
) -> CanonicalCalendar:
    """Build the project's canonical calendar from explicitly governed
    configuration - never inferred from raw source data.

    Every parameter is a keyword-only, explicitly governed decision the
    caller must already have (this module invents none of them): where
    that governed decision should actually live (a new `MarketSpecConfig`
    field, a project-level setting, or elsewhere) is itself an unresolved
    product/architecture decision this record does not invent - see the
    module docstring. Missing any of the three raises
    `CalendarResolutionRequiredError` naming exactly what is missing,
    rather than falling back to whichever source happens to have the
    shortest or longest history.
    """
    missing = [
        name
        for name, value in (
            ("governed_start", governed_start),
            ("governed_end", governed_end),
            ("governed_frequency", governed_frequency),
        )
        if not value
    ]
    if missing:
        raise CalendarResolutionRequiredError(
            "Cannot resolve a canonical calendar: no governed project-"
            f"calendar configuration is available for: {missing}. "
            "REQ-COVERAGE-001 S1 forbids inferring a calendar from raw "
            "source intersection (e.g. an inner join's date range) - "
            "this requires an explicit, separately-approved decision "
            "for where a project's governed start/end/frequency comes "
            "from (see docs/approved_requirements/REQ-COVERAGE-001.md "
            "S4 and this repository's Work Package C record)."
        )
    assert governed_start is not None
    assert governed_end is not None
    assert governed_frequency is not None
    return CanonicalCalendar(
        start=governed_start, end=governed_end, frequency=governed_frequency
    )


# --- Official-preparation boundary (WP6) ----------------------------------


OFFICIAL_PREPARATION_STATUSES = (
    "ready",
    "decision_required",
    "unsupported_no_approved_method",
    "unsupported_definition_break",
    "unsupported_leakage",
    "method_available",
)


@dataclass(frozen=True)
class OfficialPreparationResult:
    """A read-only official-preparation decision.

    This service deliberately does not mutate a frame. ``ready`` is only
    possible when a governed canonical calendar exists, coverage is not
    unresolved, and no frequency conversion is required. A future package
    may add a concrete, approved conversion executor; until then a
    mixed-frequency request is explicitly unsupported rather than being
    satisfied by an inner join or fill operation.
    """

    status: str
    reason: str
    canonical_calendar: Optional[CanonicalCalendar] = None
    alignment_results: Tuple[AlignmentResult, ...] = ()
    decisions_required: Tuple[str, ...] = ()
    conversion_variable_classes: Tuple[str, ...] = ()
    native_data_preserved: bool = True

    def __post_init__(self) -> None:
        if self.status not in OFFICIAL_PREPARATION_STATUSES:
            raise ValueError(
                f"invalid official-preparation status {self.status!r}; "
                f"must be one of {OFFICIAL_PREPARATION_STATUSES}"
            )

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "canonical_calendar": (
                self.canonical_calendar.to_dict()
                if self.canonical_calendar is not None
                else None
            ),
            "alignment_results": [r.to_dict() for r in self.alignment_results],
            "decisions_required": list(self.decisions_required),
            "conversion_variable_classes": list(self.conversion_variable_classes),
            "native_data_preserved": self.native_data_preserved,
            "ready": self.ready,
        }


def _alignment_spec_from_coverage_record(
    record: VariableCoverageRecord,
) -> AlignmentSpecification:
    """Translate the persisted coverage contract into an alignment request."""

    frequency = record.frequency
    return AlignmentSpecification(
        variable_id=record.variable_id,
        source_id=record.source_id,
        source_version=record.source_version,
        market=record.market,
        native_frequency=frequency.native_frequency,
        target_frequency=frequency.target_frequency,
        variable_class=frequency.variable_class,
        publication_lag_periods=frequency.publication_lag_periods,
        method_id=frequency.method or None,
        reconciliation_rule=frequency.reconciliation_rule,
        effective_start=record.effective_start,
        effective_end=record.effective_end,
        support_start=record.observed_start,
        support_end=record.observed_end,
        definition_breaks=record.definition_breaks,
    )


def assess_official_preparation(
    matrix: Optional[VariableCoverageMatrix],
    *,
    governed_start: Optional[str] = None,
    governed_end: Optional[str] = None,
    governed_frequency: Optional[str] = None,
    as_of: Optional[str] = None,
) -> OfficialPreparationResult:
    """Assess whether an official model frame may be prepared.

    The result is intentionally a governance/readiness report, not a
    transformation. Native-frequency rows and missingness are never changed.
    A mixed-frequency record is sent through ``evaluate_alignment_request``;
    with the currently empty registry this produces
    ``unsupported_no_approved_method``. The generic Transform Pipeline is
    therefore not an implicit fallback.

    ``governed_*`` are optional only so the caller can receive an actionable
    decision-required result. They are not inferred from source dates or an
    inner-join intersection.
    """

    if matrix is None:
        return OfficialPreparationResult(
            status="decision_required",
            reason=(
                "Build and review a versioned variable coverage matrix before "
                "official preparation; source rows and missingness remain "
                "native until then."
            ),
            decisions_required=(
                "Build a coverage matrix and explicitly review every variable "
                "before official preparation.",
                "Set the governed project calendar (start, end, and frequency); "
                "it must not be inferred from a source intersection.",
            ),
        )

    coverage_issues = tuple(official_fit_blocking_issues(matrix.records))
    if coverage_issues:
        return OfficialPreparationResult(
            status="decision_required",
            reason=(
                "Official preparation is blocked by unresolved coverage. "
                "Review and explicitly approve or exclude the affected "
                "coverage states on Data Coverage."
            ),
            decisions_required=coverage_issues
            + (
                "Set the governed project calendar (start, end, and frequency); "
                "it must not be inferred from a source intersection.",
            ),
        )

    try:
        calendar = resolve_canonical_calendar(
            governed_start=governed_start,
            governed_end=governed_end,
            governed_frequency=governed_frequency,
        )
    except CalendarResolutionRequiredError as exc:
        # Surface the more specific missing-method decision as soon as the
        # reviewed matrix proves that conversion is required. The calendar is
        # still a separate blocker, but hiding the variable-class method
        # choice behind it would make the UI less actionable.
        conversion_records = tuple(
            record
            for record in matrix.records
            if record.frequency.native_frequency.strip().lower()
            != record.frequency.target_frequency.strip().lower()
        )
        if conversion_records:
            conversion_classes = tuple(
                sorted(
                    {record.frequency.variable_class for record in conversion_records}
                )
            )
            preflight_results = tuple(
                evaluate_alignment_request(_alignment_spec_from_coverage_record(record))
                for record in conversion_records
            )
            if any(
                result.status == "unsupported_no_approved_method"
                for result in preflight_results
            ):
                decisions = tuple(
                    item
                    for variable_class in conversion_classes
                    for item in FREQUENCY_METHOD_DECISIONS_REQUIRED[variable_class]
                )
                return OfficialPreparationResult(
                    status="unsupported_no_approved_method",
                    reason=(
                        "Official preparation is blocked: "
                        + "; ".join(result.reason for result in preflight_results)
                        + f" Also: {exc}"
                    ),
                    alignment_results=preflight_results,
                    decisions_required=decisions
                    + (
                        "Set the governed project calendar (start, end, and "
                        "frequency); it must not be inferred from a source "
                        "intersection.",
                    ),
                    conversion_variable_classes=conversion_classes,
                )
        return OfficialPreparationResult(
            status="decision_required",
            reason=str(exc),
            decisions_required=(
                "Set the governed project calendar (start, end, and frequency); "
                "it must not be inferred from a source intersection.",
            ),
        )

    conversion_records = tuple(
        record
        for record in matrix.records
        if record.frequency.native_frequency.strip().lower()
        != record.frequency.target_frequency.strip().lower()
    )
    conversion_classes = tuple(
        sorted({record.frequency.variable_class for record in conversion_records})
    )
    if not conversion_records:
        return OfficialPreparationResult(
            status="ready",
            reason=(
                "Coverage is resolved and every reviewed variable is already "
                "at the governed target frequency. No frequency conversion is "
                "performed."
            ),
            canonical_calendar=calendar,
        )

    results = tuple(
        evaluate_alignment_request(
            _alignment_spec_from_coverage_record(record),
            period_start=calendar.start,
            period_end=calendar.end,
            as_of=as_of,
        )
        for record in conversion_records
    )
    blocking = tuple(result for result in results if not result.supported)
    if blocking:
        status = blocking[0].status
        if status not in {
            "unsupported_no_approved_method",
            "unsupported_definition_break",
            "unsupported_leakage",
        }:
            status = "decision_required"
        decisions = tuple(
            item
            for variable_class in conversion_classes
            for item in FREQUENCY_METHOD_DECISIONS_REQUIRED[variable_class]
        )
        return OfficialPreparationResult(
            status=status,
            reason=(
                "Official preparation is blocked: "
                + "; ".join(result.reason for result in blocking)
            ),
            canonical_calendar=calendar,
            alignment_results=results,
            decisions_required=decisions,
            conversion_variable_classes=conversion_classes,
        )

    # Feasibility is not execution. Until a separately-scoped executor is
    # supplied, do not allow a method registry entry by itself to create a
    # model frame from native-frequency inputs.
    return OfficialPreparationResult(
        status="method_available",
        reason=(
            "An approved conversion method is available, but this boundary "
            "does not execute conversions. Use the separately governed "
            "conversion executor before official preparation."
        ),
        canonical_calendar=calendar,
        alignment_results=results,
        decisions_required=(
            "Wire and validate the approved conversion executor before this "
            "request can produce an official model frame.",
        ),
        conversion_variable_classes=conversion_classes,
    )
