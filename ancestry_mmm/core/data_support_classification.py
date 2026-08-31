"""Consolidated per-channel data-support classification (`REQ-DATASUPPORT-001`;
Decision 17 of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief).

See `docs/data_support_classification_decision_record.md` for the full
decision record. Summary:

`REQ-DATASUPPORT-001` is a target-state consolidation contract: a
channel's data support must be classified into one of three practical
states (sufficient to attempt estimation / weak-support-limited / not
sufficient for a separate coefficient), drawing on evidence already
computed - in part - by three separate, unconsolidated modules
(`core.prefit_identifiability`'s four-tier whole-frame support status,
`core.coverage`'s missingness vocabulary, `core.identification_
diagnostics`'s collinearity assessment), plus `core.fold_data_support`'s
per-fold support diagnostic (a fourth relevant, pre-existing source this
record's own text does not name but which computes several of the same
Decision 17 evidence dimensions - a factual gap in the REQ record's own
text, recorded and reconciled by the decision record, not silently
corrected in place).

This module explicitly does **not** invent any numeric threshold or
severity judgement - Decision 17's own instruction, and `REQ-DATASUPPORT-
001` Requirement 2's "no universal numeric rule ... unless evidence
actually supports it." Two genuinely different things are kept separate
throughout:

1. **Evidence assembly** (`assemble_data_support_evidence`): real
   integration work - reading each existing module's own already-computed
   output and mapping it onto Decision 17's twelve named evidence
   dimensions. This is the "precise module/function consolidation
   architecture" `REQ-DATASUPPORT-001` explicitly defers to Phase B/C/E
   implementation (not a business fact, not Finance-FX-like external
   data - an implementation choice this module makes and documents).
2. **Severity judgement** (`severity_by_dimension`): always caller-
   supplied, never computed by this module from a numeric cutoff. A raw
   evidence value can be assembled (e.g. "14 non-zero weeks observed")
   without this module ever deciding whether 14 is concerning - that
   judgement is supplied explicitly by the caller (today, most naturally
   sourced from an analyst's own read of the assembled evidence, or from
   whatever threshold policy a future decision approves) and is always
   disclosed alongside the raw value it was made about, never replacing
   it.

`classify_data_support`'s default combination rule (worst-dimension-wins:
any severe-concern dimension makes the channel `not_sufficient`; any
moderate-concern dimension with no severe dimension makes it `weak`; no
concern anywhere makes it `sufficient`) is a **structural, non-numeric**
default - not a business threshold - offered as a transparent, documented,
fully overridable convention (`combination_policy` accepts a caller-
supplied callable). `REQ-DATASUPPORT-001` explicitly excludes "the exact
weighting or combination rule across dimensions" from its own approval;
this default is disclosed, not asserted as approved policy.

Every non-`sufficient` classification requires an explicit, closed-
vocabulary governed response (Requirement 3) - construction fails closed
if one is missing, mirroring `core.capacity.CapHitClassification`'s
"never a bare categorical label" and `core.calibration_comparison`'s
"never a silent drop" discipline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

DATA_SUPPORT_CLASSIFICATION_VERSION = "data-support-classification-v1"

# --- Requirement 1: the twelve named evidence dimensions (Decision 17's own
# list, verbatim) -------------------------------------------------------

DIMENSION_TOTAL_OBSERVED_WEEKS = "total_observed_weeks"
DIMENSION_NON_ZERO_ACTIVE_WEEKS = "non_zero_active_weeks"
DIMENSION_SEPARATE_ACTIVITY_PERIODS = "number_of_separate_activity_periods"
DIMENSION_SPEND_EXPOSURE_VARIATION = "spend_exposure_variation"
DIMENSION_LONG_RUNS_OF_ZEROS = "long_runs_of_zeros"
DIMENSION_MISSINGNESS = "missingness"
DIMENSION_COLLINEARITY = "collinearity_with_other_channels"
DIMENSION_CORRELATION_WITH_TREND_SEASONALITY = "correlation_with_trend_seasonality"
DIMENSION_MARKET_COVERAGE = "market_coverage"
DIMENSION_SEGMENT_COVERAGE = "segment_coverage"
DIMENSION_CHANGES_IN_SCALE = "changes_in_scale"
DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY = (
    "ability_to_identify_adstock_saturation_parameters"
)

EVIDENCE_DIMENSIONS = (
    DIMENSION_TOTAL_OBSERVED_WEEKS,
    DIMENSION_NON_ZERO_ACTIVE_WEEKS,
    DIMENSION_SEPARATE_ACTIVITY_PERIODS,
    DIMENSION_SPEND_EXPOSURE_VARIATION,
    DIMENSION_LONG_RUNS_OF_ZEROS,
    DIMENSION_MISSINGNESS,
    DIMENSION_COLLINEARITY,
    DIMENSION_CORRELATION_WITH_TREND_SEASONALITY,
    DIMENSION_MARKET_COVERAGE,
    DIMENSION_SEGMENT_COVERAGE,
    DIMENSION_CHANGES_IN_SCALE,
    DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY,
)

# --- The three-state classification (Requirement 1) ---------------------

DATA_SUPPORT_SUFFICIENT = "sufficient_to_attempt_estimation"
DATA_SUPPORT_WEAK = "weak_support_limited"
DATA_SUPPORT_NOT_SUFFICIENT = "not_sufficient_for_separate_coefficient"

DATA_SUPPORT_STATES = (
    DATA_SUPPORT_SUFFICIENT,
    DATA_SUPPORT_WEAK,
    DATA_SUPPORT_NOT_SUFFICIENT,
)

# --- Governed responses to weak/insufficient support (Requirement 3) ----

GOVERNED_RESPONSE_GROUP_INTO_HIGHER_LEVEL_CHANNEL = "group_into_higher_level_channel"
GOVERNED_RESPONSE_STRONGER_REGULARISATION = "stronger_regularisation"
GOVERNED_RESPONSE_PARTIAL_POOLING = "partial_pooling"
GOVERNED_RESPONSE_EXCLUDE_RETAIN_IN_AGGREGATE = "exclude_retain_in_aggregate"

GOVERNED_RESPONSES = (
    GOVERNED_RESPONSE_GROUP_INTO_HIGHER_LEVEL_CHANNEL,
    GOVERNED_RESPONSE_STRONGER_REGULARISATION,
    GOVERNED_RESPONSE_PARTIAL_POOLING,
    GOVERNED_RESPONSE_EXCLUDE_RETAIN_IN_AGGREGATE,
)

# --- Per-dimension severity vocabulary (always caller-supplied; never
# computed by this module from a numeric cutoff) -------------------------

SEVERITY_NO_CONCERN = "no_concern"
SEVERITY_MODERATE_CONCERN = "moderate_concern"
SEVERITY_SEVERE_CONCERN = "severe_concern"
SEVERITY_NOT_AVAILABLE = "not_available"
SEVERITY_NOT_APPLICABLE = "not_applicable"

SEVERITY_VALUES = (
    SEVERITY_NO_CONCERN,
    SEVERITY_MODERATE_CONCERN,
    SEVERITY_SEVERE_CONCERN,
    SEVERITY_NOT_AVAILABLE,
    SEVERITY_NOT_APPLICABLE,
)


@dataclass(frozen=True)
class EvidenceDimensionRecord:
    """One evidence dimension's raw value and (always caller-supplied)
    severity judgement - the two are recorded separately so a value can be
    known without this module ever deciding whether it is concerning."""

    dimension: str
    available: bool
    value: Any
    source_module: str
    severity: str = SEVERITY_NOT_AVAILABLE

    def __post_init__(self) -> None:
        if self.dimension not in EVIDENCE_DIMENSIONS:
            raise ValueError(
                f"EvidenceDimensionRecord: unknown dimension {self.dimension!r}; "
                f"must be one of {EVIDENCE_DIMENSIONS}"
            )
        if self.severity not in SEVERITY_VALUES:
            raise ValueError(
                f"EvidenceDimensionRecord: unknown severity {self.severity!r}; "
                f"must be one of {SEVERITY_VALUES}"
            )
        if not self.available and self.severity not in (
            SEVERITY_NOT_AVAILABLE,
            SEVERITY_NOT_APPLICABLE,
        ):
            raise ValueError(
                f"EvidenceDimensionRecord({self.dimension!r}): a severity judgement "
                "cannot be recorded for evidence that was never available"
            )

    def to_dict(self) -> dict:
        return {
            "dimension": self.dimension,
            "available": self.available,
            "value": self.value,
            "source_module": self.source_module,
            "severity": self.severity,
        }


@dataclass(frozen=True)
class DataSupportEvidence:
    """All twelve evidence dimensions for one channel - always exactly
    twelve records, one per `EVIDENCE_DIMENSIONS` entry, so a dimension
    with nothing to say is explicit (`available=False`), never silently
    omitted."""

    channel: str
    dimension_records: Tuple[EvidenceDimensionRecord, ...]

    def __post_init__(self) -> None:
        present = {r.dimension for r in self.dimension_records}
        missing = set(EVIDENCE_DIMENSIONS) - present
        if missing:
            raise ValueError(
                f"DataSupportEvidence for {self.channel!r} is missing dimension "
                f"record(s): {sorted(missing)} - every one of the twelve named "
                "dimensions must be represented, even as available=False"
            )
        duplicates = [
            d
            for d in present
            if sum(1 for r in self.dimension_records if r.dimension == d) > 1
        ]
        if duplicates:
            raise ValueError(
                f"DataSupportEvidence for {self.channel!r} has duplicate dimension "
                f"record(s): {sorted(duplicates)}"
            )

    def by_dimension(self) -> Dict[str, EvidenceDimensionRecord]:
        return {r.dimension: r for r in self.dimension_records}

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "dimension_records": [r.to_dict() for r in self.dimension_records],
        }


def _record(
    dimension: str,
    *,
    value: Any,
    source_module: str,
    severity: str = SEVERITY_NOT_AVAILABLE,
) -> EvidenceDimensionRecord:
    available = value is not None
    return EvidenceDimensionRecord(
        dimension=dimension,
        available=available,
        value=value,
        source_module=source_module if available else "not_available",
        severity=severity
        if available
        else (
            SEVERITY_NOT_APPLICABLE
            if severity == SEVERITY_NOT_APPLICABLE
            else SEVERITY_NOT_AVAILABLE
        ),
    )


def assemble_data_support_evidence(
    channel: str,
    *,
    prefit_support_row: Optional[Mapping[str, Any]] = None,
    coverage_missingness: Optional[Any] = None,
    collinearity_evidence: Optional[Mapping[str, Any]] = None,
    fold_support: Optional[Any] = None,
    market_coverage_count: Optional[int] = None,
    segment_coverage_count: Optional[int] = None,
    severity_by_dimension: Optional[Mapping[str, str]] = None,
) -> DataSupportEvidence:
    """Assemble one channel's twelve-dimension evidence bundle from
    whichever existing diagnostic modules' outputs the caller supplies.

    Every argument is optional and independently sourced - this function
    never fits a model, recomputes raw data, or invents a value that was
    not present in a supplied source. `prefit_support_row` is one row
    (dict-like) from `core.prefit_identifiability.compute_channel_support_
    diagnostics`'s `"rows"` list. `coverage_missingness` is a `core.
    coverage.VariableCoverageRecord`-shaped object (or a plain mapping
    with an equivalent `missing_weeks`/`total_weeks` shape). `collinearity_
    evidence` is a mapping produced by the caller from `core.
    identification_diagnostics` (e.g. `{"max_correlation_with_other_channels":
    ..., "vif": ...}` - this function does not call `core.
    identification_diagnostics` itself, since that module needs the full
    design matrix, not a per-channel row). `fold_support` is a `core.
    fold_data_support.VariableSupportDiagnostic` for this channel, when
    per-fold (rather than whole-frame) evidence is the more relevant
    source. `severity_by_dimension`, if supplied, assigns a caller's own
    concern judgement to specific dimensions - never invented here.
    """
    severity_by_dimension = dict(severity_by_dimension or {})

    def sev(dimension: str) -> str:
        return severity_by_dimension.get(dimension, SEVERITY_NOT_AVAILABLE)

    prefit = dict(prefit_support_row or {})
    fold = fold_support

    total_weeks = prefit.get("target_weeks")
    if total_weeks is None and fold is not None:
        total_weeks = getattr(fold, "n_train_weeks", None)

    active_weeks = prefit.get("positive_weeks")
    if active_weeks is None and fold is not None:
        active_weeks = getattr(fold, "n_active_weeks", None)

    long_zero_run = prefit.get("longest_zero_run")

    spend_variation = None
    if prefit.get("effective_adstock_cv") is not None:
        spend_variation = prefit["effective_adstock_cv"]
    elif fold is not None and getattr(fold, "variance", None) is not None:
        spend_variation = getattr(fold, "variance")

    missingness_value = None
    if coverage_missingness is not None:
        missingness_value = coverage_missingness
    elif fold is not None:
        missingness_value = getattr(fold, "n_missing_weeks", None)

    collinearity_value = None
    if collinearity_evidence:
        collinearity_value = dict(collinearity_evidence)

    adstock_saturation_value = prefit.get("support_status")

    records = [
        _record(
            DIMENSION_TOTAL_OBSERVED_WEEKS,
            value=total_weeks,
            source_module=(
                "core.prefit_identifiability"
                if prefit.get("target_weeks") is not None
                else "core.fold_data_support"
            ),
            severity=sev(DIMENSION_TOTAL_OBSERVED_WEEKS),
        ),
        _record(
            DIMENSION_NON_ZERO_ACTIVE_WEEKS,
            value=active_weeks,
            source_module=(
                "core.prefit_identifiability"
                if prefit.get("positive_weeks") is not None
                else "core.fold_data_support"
            ),
            severity=sev(DIMENSION_NON_ZERO_ACTIVE_WEEKS),
        ),
        _record(
            DIMENSION_SEPARATE_ACTIVITY_PERIODS,
            value=None,  # not computed by any existing module today
            source_module="not_available",
            severity=sev(DIMENSION_SEPARATE_ACTIVITY_PERIODS),
        ),
        _record(
            DIMENSION_SPEND_EXPOSURE_VARIATION,
            value=spend_variation,
            source_module=(
                "core.prefit_identifiability"
                if prefit.get("effective_adstock_cv") is not None
                else "core.fold_data_support"
            ),
            severity=sev(DIMENSION_SPEND_EXPOSURE_VARIATION),
        ),
        _record(
            DIMENSION_LONG_RUNS_OF_ZEROS,
            value=long_zero_run,
            source_module="core.prefit_identifiability",
            severity=sev(DIMENSION_LONG_RUNS_OF_ZEROS),
        ),
        _record(
            DIMENSION_MISSINGNESS,
            value=missingness_value,
            source_module=(
                "core.coverage"
                if coverage_missingness is not None
                else "core.fold_data_support"
            ),
            severity=sev(DIMENSION_MISSINGNESS),
        ),
        _record(
            DIMENSION_COLLINEARITY,
            value=collinearity_value,
            source_module="core.identification_diagnostics",
            severity=sev(DIMENSION_COLLINEARITY),
        ),
        _record(
            DIMENSION_CORRELATION_WITH_TREND_SEASONALITY,
            value=None,  # not computed per-channel by any existing module today
            source_module="not_available",
            severity=sev(DIMENSION_CORRELATION_WITH_TREND_SEASONALITY),
        ),
        _record(
            DIMENSION_MARKET_COVERAGE,
            value=market_coverage_count,
            source_module="core.market_data_capability"
            if market_coverage_count is not None
            else "not_available",
            severity=sev(DIMENSION_MARKET_COVERAGE),
        ),
        _record(
            DIMENSION_SEGMENT_COVERAGE,
            value=segment_coverage_count,
            source_module="core.coverage"
            if segment_coverage_count is not None
            else "not_available",
            severity=sev(DIMENSION_SEGMENT_COVERAGE),
        ),
        _record(
            DIMENSION_CHANGES_IN_SCALE,
            value=prefit.get("positive_max_to_median"),
            source_module="core.prefit_identifiability",
            severity=sev(DIMENSION_CHANGES_IN_SCALE),
        ),
        _record(
            DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY,
            value=adstock_saturation_value,
            source_module="core.prefit_identifiability",
            severity=sev(DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY),
        ),
    ]
    return DataSupportEvidence(channel=channel, dimension_records=tuple(records))


def _default_combination_policy(
    evidence: DataSupportEvidence,
) -> Tuple[str, Tuple[str, ...]]:
    """Worst-dimension-wins: a documented, non-numeric structural default,
    never an approved business threshold. See module docstring."""
    severe = [
        r.dimension
        for r in evidence.dimension_records
        if r.severity == SEVERITY_SEVERE_CONCERN
    ]
    if severe:
        return DATA_SUPPORT_NOT_SUFFICIENT, tuple(severe)
    moderate = [
        r.dimension
        for r in evidence.dimension_records
        if r.severity == SEVERITY_MODERATE_CONCERN
    ]
    if moderate:
        return DATA_SUPPORT_WEAK, tuple(moderate)
    return DATA_SUPPORT_SUFFICIENT, ()


@dataclass(frozen=True)
class DataSupportClassification:
    """The consolidated per-channel verdict (Requirement 1), always
    carrying the evidence it was derived from (Requirement 4) and,
    whenever support is not sufficient, an explicit governed response
    (Requirement 3) - construction fails closed if one is missing."""

    channel: str
    state: str
    reasons: Tuple[str, ...]
    evidence: DataSupportEvidence
    governed_response: Optional[str] = None
    combination_policy_name: str = "worst_dimension_wins_default"
    version: str = DATA_SUPPORT_CLASSIFICATION_VERSION

    def __post_init__(self) -> None:
        if self.state not in DATA_SUPPORT_STATES:
            raise ValueError(
                f"DataSupportClassification: unknown state {self.state!r}; "
                f"must be one of {DATA_SUPPORT_STATES}"
            )
        if self.state != DATA_SUPPORT_SUFFICIENT:
            if not self.reasons:
                raise ValueError(
                    "DataSupportClassification: a non-sufficient state must cite "
                    "the specific evidence dimension(s) that triggered it "
                    "(Requirement 4) - never an unexplained categorical status"
                )
            if self.governed_response not in GOVERNED_RESPONSES:
                raise ValueError(
                    "DataSupportClassification: a non-sufficient state requires an "
                    f"explicit governed_response in {GOVERNED_RESPONSES} - never a "
                    "silent drop and never an unexplained block (Requirement 3)"
                )
        elif self.governed_response is not None:
            raise ValueError(
                "DataSupportClassification: a sufficient state must not carry a "
                "governed_response - there is nothing to respond to"
            )

    def to_dict(self) -> dict:
        return {
            "channel": self.channel,
            "state": self.state,
            "reasons": list(self.reasons),
            "evidence": self.evidence.to_dict(),
            "governed_response": self.governed_response,
            "combination_policy_name": self.combination_policy_name,
            "version": self.version,
        }


def preview_data_support_state(
    evidence: DataSupportEvidence,
    *,
    combination_policy: Optional[
        Callable[[DataSupportEvidence], Tuple[str, Tuple[str, ...]]]
    ] = None,
) -> Tuple[str, Tuple[str, ...]]:
    """Read-only preview of the `(state, reasons)` `classify_data_support`
    would compute, without constructing a `DataSupportClassification` -
    which fails closed (raises) when the state is non-sufficient and no
    `governed_response` has been supplied yet (Requirement 3). A caller
    that needs to know *whether* an explicit governed response will be
    required - e.g. a UI deciding whether to show the response selector at
    all - before an analyst has chosen one calls this first; it always
    uses the same policy function `classify_data_support` uses (the
    default worst-dimension-wins rule, or a caller-supplied
    `combination_policy`), never a separately re-derived rule."""
    policy = combination_policy or _default_combination_policy
    return policy(evidence)


def classify_data_support(
    evidence: DataSupportEvidence,
    *,
    governed_response: Optional[str] = None,
    combination_policy: Optional[
        Callable[[DataSupportEvidence], Tuple[str, Tuple[str, ...]]]
    ] = None,
    combination_policy_name: Optional[str] = None,
) -> DataSupportClassification:
    """Roll up one channel's assembled evidence into the closed three-state
    verdict. `combination_policy` may replace the default worst-dimension-
    wins rule with a caller-supplied one - `REQ-DATASUPPORT-001` explicitly
    does not approve one combination rule over another, so this default is
    disclosed as a convention, not asserted as approved policy."""
    policy = combination_policy or _default_combination_policy
    policy_name = combination_policy_name or (
        "worst_dimension_wins_default"
        if combination_policy is None
        else "caller_supplied"
    )
    state, reasons = policy(evidence)
    return DataSupportClassification(
        channel=evidence.channel,
        state=state,
        reasons=reasons,
        evidence=evidence,
        governed_response=governed_response,
        combination_policy_name=policy_name,
    )
