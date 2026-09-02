"""Application-layer glue for `REQ-DATASUPPORT-001` / Decision 17's
consolidated per-channel data-support classification.

`core.data_support_classification.assemble_data_support_evidence` never
reads a session-state key or another module's report directly - by
design, every source is caller-supplied (see that module's own
docstring). This module is the one place that actually reads the three
real diagnostic sources already computed elsewhere in the app -
`core.prefit_identifiability` (via `pages/04_Model_Config.py`'s
`"prefit_identifiability"` session-state key), `core.
identification_diagnostics` (via the canonical `DiagnosticsService`
artefact's `identification` section, already rendered on
`pages/06_Diagnostics.py`'s "Identification & collinearity" tab), and
`core.coverage` (via the `"variable_coverage_matrix"` session-state key) -
and maps each one's already-computed output onto one channel's evidence
bundle. No source is recomputed here; each is read exactly once, from
the same canonical location its own existing display already reads from.

Severity judgement (Decision 17's "no universal numeric rule ... unless
evidence actually supports it") is populated for exactly one of the
twelve dimensions - `ability_to_identify_adstock_saturation_parameters` -
because that is the only one of the three-plus-one sources with an
already-approved threshold policy behind it
(`core.prefit_identifiability.SupportThresholdPolicy`, expressed through
its own `review_recommendation.review_status` vocabulary: `"ready"` /
`"review_recommended"` / `"blocked"`). The other eleven dimensions are
never assigned a severity here: none of today's sources carries an
approved threshold for them, so per Decision 17 they stay
`SEVERITY_NOT_AVAILABLE` and are shown as evidence without contributing
to the rolled-up verdict. This mirrors `06_Diagnostics.py`'s own existing
treatment of `core.identification_diagnostics` flags, which are
explicitly "analyst-review evidence, not a validation-policy gate" and
are deliberately never escalated into a severity judgement either.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, cast

from ancestry_mmm.core.coverage import UNRESOLVED_BLOCKING_STATES
from ancestry_mmm.core.data_support_classification import (
    DATA_SUPPORT_SUFFICIENT,
    DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY,
    DataSupportClassification,
    DataSupportEvidence,
    assemble_data_support_evidence,
    classify_data_support,
    preview_data_support_state,
)

# The only severity mapping this service makes: `core.prefit_
# identifiability`'s own already-approved `review_status` vocabulary,
# reused verbatim - never a new numeric cutoff invented here.
REVIEW_STATUS_TO_SEVERITY: Dict[str, str] = {
    "ready": "no_concern",
    "review_recommended": "moderate_concern",
    "blocked": "severe_concern",
}


def _find_prefit_row(
    prefit_report: Optional[Mapping[str, Any]], channel: str
) -> Optional[Mapping[str, Any]]:
    if not prefit_report:
        return None
    support_section = prefit_report.get("support_identifiability") or {}
    for row in support_section.get("rows") or []:
        if row.get("channel") == channel:
            return cast(Mapping[str, Any], row)
    return None


def _channel_collinearity_evidence(
    identification_payload: Optional[Mapping[str, Any]], channel: str
) -> Optional[Dict[str, Any]]:
    """Adapt `core.identification_diagnostics`'s whole-model
    `correlation_matrix` (channel x channel) and `flags` list (each keyed
    by a `"channel"` field that is sometimes a single channel and
    sometimes a combined `"'a' / 'b'"` pair string, e.g. from a
    high-correlation-pair flag) down to this one channel's evidence.
    Returns None when the identification artefact has nothing to say
    about this specific channel, rather than an empty-but-present dict."""
    if not identification_payload:
        return None
    correlation_matrix = identification_payload.get("correlation_matrix") or {}
    row = correlation_matrix.get(channel)
    max_abs_correlation: Optional[float] = None
    if isinstance(row, Mapping):
        others = [
            abs(v)
            for other_channel, v in row.items()
            if other_channel != channel and isinstance(v, (int, float))
        ]
        if others:
            max_abs_correlation = max(others)
    flagged_messages = [
        str(flag.get("message"))
        for flag in identification_payload.get("flags") or []
        if channel in str(flag.get("channel", ""))
    ]
    if max_abs_correlation is None and not flagged_messages:
        return None
    return {
        "max_abs_correlation_with_other_channels": max_abs_correlation,
        "flagged_messages": flagged_messages,
    }


def _channel_missingness_summary(
    coverage_matrix_dict: Optional[Mapping[str, Any]], channel: str
) -> Optional[Dict[str, Any]]:
    """Adapt `core.coverage`'s `VariableCoverageMatrix.to_dict()` shape
    (a list of per-variable `VariableCoverageRecord` dicts, each carrying
    its own `coverage_segments` list with a `"state"` per segment) down to
    a simple unresolved-vs-total segment count for this one channel.
    Returns None when the coverage matrix has no record at all for this
    channel, rather than a misleading `0 unresolved of 0`."""
    if not coverage_matrix_dict:
        return None
    matching_records = [
        record
        for record in coverage_matrix_dict.get("records") or []
        if record.get("variable_id") == channel
    ]
    if not matching_records:
        return None
    total_segments = 0
    unresolved_segments = 0
    for record in matching_records:
        for segment in record.get("coverage_segments") or []:
            total_segments += 1
            if segment.get("state") in UNRESOLVED_BLOCKING_STATES:
                unresolved_segments += 1
    if total_segments == 0:
        return None
    return {
        "unresolved_segments": unresolved_segments,
        "total_segments": total_segments,
    }


def assemble_channel_data_support_evidence(
    channel: str,
    *,
    prefit_report: Optional[Mapping[str, Any]] = None,
    identification_payload: Optional[Mapping[str, Any]] = None,
    coverage_matrix_dict: Optional[Mapping[str, Any]] = None,
) -> DataSupportEvidence:
    """Assemble one channel's twelve-dimension evidence bundle from the
    three real diagnostic sources already computed elsewhere in this app.
    `prefit_report` is the session-state `"prefit_identifiability"` dict
    computed on `pages/04_Model_Config.py`; `identification_payload` is
    the canonical `diag_artefact.identification.payload` dict already
    rendered on `pages/06_Diagnostics.py`'s "Identification & collinearity"
    tab; `coverage_matrix_dict` is the session-state
    `"variable_coverage_matrix"` dict. Any (or all) may be `None` - every
    dimension this leaves unreachable is recorded as explicitly
    unavailable, never silently defaulted."""
    prefit_row = _find_prefit_row(prefit_report, channel)
    severity_by_dimension: Dict[str, str] = {}
    if prefit_row is not None:
        review_status = (prefit_row.get("review_recommendation") or {}).get(
            "review_status"
        )
        severity = REVIEW_STATUS_TO_SEVERITY.get(str(review_status))
        if severity is not None:
            severity_by_dimension[DIMENSION_ADSTOCK_SATURATION_IDENTIFIABILITY] = (
                severity
            )
    return assemble_data_support_evidence(
        channel,
        prefit_support_row=prefit_row,
        coverage_missingness=_channel_missingness_summary(
            coverage_matrix_dict, channel
        ),
        collinearity_evidence=_channel_collinearity_evidence(
            identification_payload, channel
        ),
        severity_by_dimension=severity_by_dimension,
    )


def preview_channel_data_support_state(
    evidence: DataSupportEvidence,
) -> Tuple[str, Tuple[str, ...]]:
    """Read-only `(state, reasons)` preview - see `core.
    data_support_classification.preview_data_support_state`. Lets a caller
    (the Diagnostics page) decide whether an analyst-selected governed
    response is required before attempting to construct the classification
    object, instead of relying on catching the module's fail-closed
    `ValueError`."""
    return preview_data_support_state(evidence)


def classify_channel_data_support(
    evidence: DataSupportEvidence,
    *,
    governed_response: Optional[str] = None,
) -> DataSupportClassification:
    """Thin passthrough to `core.data_support_classification.
    classify_data_support` - kept here only so the page imports one
    application-layer module for this feature, mirroring every other
    diagnostic section on `pages/06_Diagnostics.py`."""
    return classify_data_support(evidence, governed_response=governed_response)


def assemble_project_data_support_overview(
    channels: Sequence[str],
    *,
    prefit_report: Optional[Mapping[str, Any]] = None,
    identification_payload: Optional[Mapping[str, Any]] = None,
    coverage_matrix_dict: Optional[Mapping[str, Any]] = None,
    governed_response_by_channel: Optional[Mapping[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Build one evidence+state(+classification) overview row per channel,
    in the shape `pages/06_Diagnostics.py` renders directly. Each row is
    `{"channel", "evidence", "state", "reasons", "needs_governed_response",
    "classification"}` - `classification` is `None` exactly when `state`
    is non-sufficient and `governed_response_by_channel` does not yet
    carry an explicit choice for this channel (Requirement 3's fail-closed
    behaviour, surfaced to the caller rather than raised)."""
    governed_response_by_channel = dict(governed_response_by_channel or {})
    overview: List[Dict[str, Any]] = []
    for channel in channels:
        evidence = assemble_channel_data_support_evidence(
            channel,
            prefit_report=prefit_report,
            identification_payload=identification_payload,
            coverage_matrix_dict=coverage_matrix_dict,
        )
        state, reasons = preview_channel_data_support_state(evidence)
        needs_governed_response = state != DATA_SUPPORT_SUFFICIENT
        classification: Optional[DataSupportClassification] = None
        chosen_response = governed_response_by_channel.get(channel)
        if not needs_governed_response:
            classification = classify_channel_data_support(evidence)
        elif chosen_response:
            classification = classify_channel_data_support(
                evidence, governed_response=chosen_response
            )
        overview.append(
            {
                "channel": channel,
                "evidence": evidence,
                "state": state,
                "reasons": reasons,
                "needs_governed_response": needs_governed_response,
                "classification": classification,
            }
        )
    return overview
