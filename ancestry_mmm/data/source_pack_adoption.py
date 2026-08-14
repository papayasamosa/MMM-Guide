"""Durable adoption of canonical non-Outcomes source-pack semantics.

Workbook parsing and canonicalisation live in :mod:`ancestry_mmm.data.templates`.
This module is the application-independent boundary that combines multiple
physical workbooks under one logical domain and records what downstream
meaning is, and is not, approved by the existing contracts.

It deliberately does not create OutcomeApproval, CalibrationRecord,
MediaInputSpec, or ChannelMediaUnitConfig objects automatically. Those are
separate governed registries with their own review and identity rules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

import pandas as pd

from ancestry_mmm.core.activities import ActivityDefinition
from ancestry_mmm.core.coverage import (
    DOMAIN_ACTIVITY_AND_MEDIA,
    DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
    DOMAIN_EXPERIMENT_EVIDENCE,
    DOMAIN_OUTCOMES,
)

from .templates import CanonicalSourceBundle


@dataclass(frozen=True)
class SourceDomainSemanticStatus:
    """User-facing and portable adoption evidence for one workbook lineage."""

    source_id: str
    logical_domain: str
    schema_version: str | None
    status: str
    table_ids: tuple[str, ...]
    adopted_objects: tuple[str, ...] = ()
    unsupported_mappings: tuple[str, ...] = ()
    next_action: str = ""
    details: tuple[dict[str, object], ...] = ()

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["table_ids"] = list(self.table_ids)
        payload["adopted_objects"] = list(self.adopted_objects)
        payload["unsupported_mappings"] = list(self.unsupported_mappings)
        payload["details"] = [dict(item) for item in self.details]
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "SourceDomainSemanticStatus":
        payload: dict[str, Any] = dict(value)
        for key in ("table_ids", "adopted_objects", "unsupported_mappings"):
            payload[key] = tuple(payload.get(key) or ())
        payload["details"] = tuple(
            dict(item) for item in (payload.get("details") or ())
        )
        return cls(**payload)


@dataclass(frozen=True)
class SourcePackAdoption:
    """Combined canonical state after adopting one source workbook."""

    activity_definitions: tuple[ActivityDefinition, ...]
    activity_model_input: pd.DataFrame | None
    outcome_data: pd.DataFrame | None
    context_data: pd.DataFrame | None
    context_variable_metadata: tuple[dict[str, object], ...]
    semantic_statuses: tuple[SourceDomainSemanticStatus, ...]
    experiment_evidence: pd.DataFrame | None = None


def _merge_wide_frames(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame | None,
    *,
    label: str,
) -> pd.DataFrame | None:
    if incoming is None or incoming.empty:
        return existing
    if existing is None or existing.empty:
        return incoming.copy()
    keys = ["period_start", "market"]
    for name, frame in (("existing", existing), ("incoming", incoming)):
        if not set(keys).issubset(frame.columns):
            raise ValueError(f"{label} {name} frame is missing source keys")
        if frame.duplicated(keys, keep=False).any():
            raise ValueError(
                f"{label} {name} frame has duplicate period/market rows; "
                "source-pack adoption does not aggregate them"
            )
    left = existing.copy()
    right = incoming.copy()
    left["period_start"] = pd.to_datetime(left["period_start"])
    right["period_start"] = pd.to_datetime(right["period_start"])
    value_columns = sorted(set(left.columns).intersection(right.columns) - set(keys))
    overlap = left.merge(right, on=keys, how="outer", suffixes=("__left", "__right"))
    for column in value_columns:
        left_column = f"{column}__left"
        right_column = f"{column}__right"
        both = overlap[left_column].notna() & overlap[right_column].notna()
        if (overlap.loc[both, left_column] != overlap.loc[both, right_column]).any():
            raise ValueError(
                f"{label} has conflicting values for shared column {column!r}; "
                "review the physical source packs before adoption"
            )
        overlap[column] = overlap[left_column].combine_first(overlap[right_column])
        overlap = overlap.drop(columns=[left_column, right_column])
    return overlap[[*keys, *sorted(set(overlap.columns) - set(keys))]].sort_values(keys)


def _merge_activity_definitions(
    existing: Sequence[ActivityDefinition],
    incoming: Sequence[ActivityDefinition],
) -> tuple[ActivityDefinition, ...]:
    by_key = {(item.market, item.activity_id): item for item in existing}
    for item in incoming:
        key = (item.market, item.activity_id)
        prior = by_key.get(key)
        if prior is not None and prior.to_dict() != item.to_dict():
            raise ValueError(
                f"activity definition {key!r} conflicts with an already adopted "
                "source pack"
            )
        by_key[key] = item
    return tuple(by_key[key] for key in sorted(by_key))


def _merge_experiment_evidence(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame | None,
) -> pd.DataFrame | None:
    if incoming is None or incoming.empty:
        return existing
    if existing is None or existing.empty:
        return incoming.copy()
    combined = pd.concat([existing, incoming], ignore_index=True)
    if "experiment_id" in combined.columns:
        duplicated = combined.duplicated("experiment_id", keep=False)
        if duplicated.any():
            raise ValueError(
                "experiment evidence packs overlap an experiment_id; review the "
                "physical source packs before adoption"
            )
    return combined.reset_index(drop=True)


def _activity_status(bundle: CanonicalSourceBundle) -> SourceDomainSemanticStatus:
    missing_physical_fields = []
    if not bundle.activity_semantic_mappings:
        missing_physical_fields.append("activity semantic mapping rows")
    else:
        for field in ("spend_column", "response_unit_column", "currency"):
            if any(not item.get(field) for item in bundle.activity_semantic_mappings):
                missing_physical_fields.append(field)
    return SourceDomainSemanticStatus(
        source_id=bundle.manifest.source_id,
        logical_domain=DOMAIN_ACTIVITY_AND_MEDIA,
        schema_version=bundle.manifest.template_schema_version,
        status=(
            "adopted_with_physical_mapping_review"
            if missing_physical_fields
            else "adopted_ready_for_mapping_review"
        ),
        table_ids=bundle.manifest.table_ids,
        adopted_objects=("ActivityDefinition", "model_input_frame"),
        unsupported_mappings=tuple(
            f"{field}: configure through the existing market/channel media-unit "
            "or cost-mapping contract; the source upload does not apply it automatically"
            for field in missing_physical_fields
        ),
        next_action=(
            "Review Activity Mapping and configure physical delivery, currency, "
            "and cost mappings where the source supports them."
        ),
        details=bundle.activity_semantic_mappings,
    )


def _context_status(bundle: CanonicalSourceBundle) -> SourceDomainSemanticStatus:
    required_metadata = (
        "source",
        "scope",
        "effective_from",
        "effective_to",
    )
    missing = tuple(
        field
        for field in required_metadata
        if not bundle.context_variable_metadata
        or any(not item.get(field) for item in bundle.context_variable_metadata)
    )
    return SourceDomainSemanticStatus(
        source_id=bundle.manifest.source_id,
        logical_domain=DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS,
        schema_version=bundle.manifest.template_schema_version,
        status="adopted_with_metadata_review" if missing else "adopted",
        table_ids=bundle.manifest.table_ids,
        adopted_objects=("native_context_data", "context_variable_metadata"),
        unsupported_mappings=tuple(
            f"{field}: metadata is not complete for every supplied context variable"
            for field in missing
        ),
        next_action=(
            "Review source, scope, and effective period metadata. A context role "
            "is not automatically added as a model control."
        ),
        details=bundle.context_variable_metadata,
    )


def _status_for_bundle(bundle: CanonicalSourceBundle) -> SourceDomainSemanticStatus:
    domain = bundle.manifest.logical_domain
    if domain == DOMAIN_ACTIVITY_AND_MEDIA:
        return _activity_status(bundle)
    if domain == DOMAIN_CONTEXT_AND_EXTERNAL_FACTORS:
        return _context_status(bundle)
    if domain == DOMAIN_EXPERIMENT_EVIDENCE:
        return SourceDomainSemanticStatus(
            source_id=bundle.manifest.source_id,
            logical_domain=DOMAIN_EXPERIMENT_EVIDENCE,
            schema_version=bundle.manifest.template_schema_version,
            status="source_evidence_only",
            table_ids=bundle.manifest.table_ids,
            adopted_objects=("governed_source_evidence",),
            unsupported_mappings=(
                "No approved experiment-evidence ingestion registry exists; "
                "the upload does not create CalibrationRecord or alter model fit.",
            ),
            next_action=(
                "Review the retained evidence separately and use an approved "
                "calibration workflow if one is later registered."
            ),
            details=tuple(
                dict(row)
                for row in (
                    bundle.experiment_evidence.to_dict(orient="records")
                    if bundle.experiment_evidence is not None
                    else ()
                )
            ),
        )
    return SourceDomainSemanticStatus(
        source_id=bundle.manifest.source_id,
        logical_domain=DOMAIN_OUTCOMES,
        schema_version=bundle.manifest.template_schema_version,
        status="outcome_catalogue_reviewed_separately",
        table_ids=bundle.manifest.table_ids,
        adopted_objects=("OutcomeDefinition", "OutcomeGroupDefinition"),
        next_action="Review and approve outcome definitions through Outcome Governance.",
    )


def adopt_standard_source_bundle(
    bundle: CanonicalSourceBundle,
    *,
    activity_definitions: Sequence[ActivityDefinition] = (),
    activity_model_input: pd.DataFrame | None = None,
    outcome_data: pd.DataFrame | None = None,
    context_data: pd.DataFrame | None = None,
    context_variable_metadata: Sequence[Mapping[str, object]] = (),
    experiment_evidence: pd.DataFrame | None = None,
    semantic_statuses: Sequence[SourceDomainSemanticStatus | Mapping[str, object]] = (),
) -> SourcePackAdoption:
    """Adopt one canonical workbook while preserving explicit review states."""

    statuses = [
        item
        if isinstance(item, SourceDomainSemanticStatus)
        else SourceDomainSemanticStatus.from_dict(item)
        for item in semantic_statuses
        if str(item.get("source_id") if isinstance(item, Mapping) else item.source_id)
        != bundle.manifest.source_id
    ]
    statuses.append(_status_for_bundle(bundle))
    combined_activities = _merge_activity_definitions(
        activity_definitions,
        bundle.activity_definitions,
    )
    combined_activity_frame = _merge_wide_frames(
        activity_model_input,
        bundle.model_input_media,
        label="activity model-input",
    )
    combined_outcomes = _merge_wide_frames(
        outcome_data,
        bundle.outcomes,
        label="outcome source",
    )
    combined_context = _merge_wide_frames(
        context_data,
        bundle.model_input_context,
        label="context model-input",
    )
    metadata = list(context_variable_metadata)
    metadata.extend(bundle.context_variable_metadata)
    by_variable: dict[str, dict[str, object]] = {}
    for item in metadata:
        variable_id = str(item.get("variable_id") or "")
        prior = by_variable.get(variable_id)
        if prior is not None and prior != dict(item):
            raise ValueError(
                f"context metadata for variable {variable_id!r} conflicts across "
                "source packs"
            )
        by_variable[variable_id] = dict(item)
    return SourcePackAdoption(
        activity_definitions=combined_activities,
        activity_model_input=combined_activity_frame,
        outcome_data=combined_outcomes,
        context_data=combined_context,
        context_variable_metadata=tuple(
            by_variable[key] for key in sorted(by_variable) if key
        ),
        semantic_statuses=tuple(
            sorted(statuses, key=lambda item: (item.logical_domain, item.source_id))
        ),
        experiment_evidence=_merge_experiment_evidence(
            experiment_evidence,
            bundle.experiment_evidence,
        ),
    )


def adopted_model_input_sources(
    *,
    outcome_data: pd.DataFrame | None,
    activity_model_input: pd.DataFrame | None,
    context_model_input: pd.DataFrame | None,
    context_variable_metadata: Sequence[Mapping[str, object]],
) -> dict[str, pd.DataFrame] | None:
    """Return adopted source frames eligible for the current native-weekly path.

    A mixed/native non-weekly context is reported as an unsupported source
    state. It is never repeated, interpolated, or silently omitted from the
    official frame.
    """

    frames = {
        name: frame
        for name, frame in (
            ("standard_outcomes", outcome_data),
            ("standard_activity", activity_model_input),
            ("standard_context", context_model_input),
        )
        if frame is not None
    }
    if not frames:
        return None
    frequencies = {
        str(item.get("native_frequency") or "").strip().lower()
        for item in context_variable_metadata
        if item.get("native_frequency")
    }
    if frequencies and frequencies != {"weekly"}:
        raise ValueError(
            "The adopted context source includes non-weekly native frequency "
            f"({', '.join(sorted(frequencies))}); no approved official "
            "conversion method is registered."
        )
    return frames


def adopted_model_input_frame(
    *,
    outcome_data: pd.DataFrame | None,
    activity_model_input: pd.DataFrame | None,
    context_model_input: pd.DataFrame | None,
) -> pd.DataFrame | None:
    """Build an exploratory outer join from adopted canonical frames.

    This is only a UI/model-structure convenience frame.  It preserves the
    native rows and missingness and is not the official preparation gate;
    :func:`adopted_model_input_sources` remains the stricter weekly eligibility
    boundary used by official preparation.
    """

    frames = [
        ("standard_outcomes", outcome_data),
        ("standard_activity", activity_model_input),
        ("standard_context", context_model_input),
    ]
    combined: pd.DataFrame | None = None
    for label, frame in frames:
        combined = _merge_wide_frames(
            combined,
            frame,
            label=f"{label} exploratory model-input",
        )
    return combined


__all__ = [
    "SourceDomainSemanticStatus",
    "SourcePackAdoption",
    "adopt_standard_source_bundle",
    "adopted_model_input_sources",
    "adopted_model_input_frame",
]
