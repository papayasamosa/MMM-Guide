"""Governed pre-fit run identity and consolidated readiness (`REQ-PREFIT-001`).

`core.prefit_identifiability` and `core.prefit_screening` each produce their
own evidence report. Before this module existed, nothing combined them: the
identifiability report used the approved three-state vocabulary
(``ready``/``review_recommended``/``blocked``) at its own top level, while the
screening report exposed a *different* vocabulary (``status: "computed"``,
plus a separate ``submission_gate`` field with values such as
``"blocked_pending_analyst_rationale"``), and submission logic in
``pages/05_Model_Training.py`` re-derived its own blocking decision by
inspecting scattered sub-fields from both dicts independently. That is
exactly the "competing top-level vocabularies" defect ``REQ-PREFIT-001``'s
review requires fixing: this module is the single place a caller consults
for pre-fit-run readiness.

This module also creates the durable, versioned pre-fit *run* identity that
was previously missing: :class:`PrefitRun` binds the two evidence reports
together with every fingerprint, the fold-reconstruction tier, and the
consolidated readiness state, and is persisted through the existing project
export/import mechanism (``core.persistence`` - see ``resolve_imported_
prefit_runs``), never a loose Streamlit session-state dictionary.

Nothing in this module fits a model, selects a channel, or mutates a causal
graph, transform, or prior. It only reads and consolidates evidence that
``core.prefit_identifiability``/``core.prefit_screening`` already computed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

import pandas as pd

PREFIT_RUN_SCHEMA_VERSION = 1

# The exact three-state vocabulary REQ-PREFIT-001 requires. Every consumer of
# pre-fit readiness - the consolidated PrefitRun.readiness field, and every
# individual evidence report's own top-level readiness field - must use one
# of these three values and nothing else. `review_recommended` requires
# retained analyst rationale before official submission; `blocked` is never
# overridable by rationale alone.
READY = "ready"
REVIEW_RECOMMENDED = "review_recommended"
BLOCKED = "blocked"
PREFIT_READINESS_STATES = (READY, REVIEW_RECOMMENDED, BLOCKED)

# Fold-reconstruction tier vocabulary (finding 3). A screen that only splits
# an already-prepared model frame by date is materially weaker leakage-safe
# evidence than one that reconstructs each fold from raw sources governed by
# their own upload-timing/point-in-time cutoff (`application.
# fold_refit_service.run_leakage_safe_fold_refit_from_sources`,
# `core.validation_folds`). A run must record which tier it actually used;
# it must never claim the stronger tier merely because both exist somewhere
# in the repository.
POINT_IN_TIME_SOURCE_RECONSTRUCTION = "point_in_time_source_reconstruction"
PREPARED_FRAME_ONLY = "prepared_frame_only"
CANNOT_VERIFY = "cannot_verify"
RECONSTRUCTION_TIERS = (
    POINT_IN_TIME_SOURCE_RECONSTRUCTION,
    PREPARED_FRAME_ONLY,
    CANNOT_VERIFY,
)


def _json_fingerprint(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _require_readiness(value: Any, *, field_name: str) -> str:
    text = str(value)
    if text not in PREFIT_READINESS_STATES:
        raise ValueError(
            f"{field_name} must be one of {PREFIT_READINESS_STATES!r}, got {value!r}"
        )
    return text


def consolidate_prefit_readiness(
    *,
    identifiability_readiness: str,
    screening_readiness: str,
    prior_predictive_readiness: str | None = None,
    analyst_rationale_retained: bool = False,
) -> dict[str, Any]:
    """Return the one governed pre-fit-run readiness state and why.

    Every input must already be one of ``READY``/``REVIEW_RECOMMENDED``/
    ``BLOCKED`` - each evidence report is responsible for classifying its own
    evidence into this vocabulary (fixing the vocabulary at the *source*,
    not translating a fourth vocabulary here). ``prior_predictive_readiness``
    is optional because a run may not have reached that stage yet; a missing
    prior-predictive review can never resolve to ``ready`` on its own.

    Rules, in order:

    1. Any component ``blocked`` -> the run is ``blocked``. Never overridable
       by analyst rationale.
    2. Any component ``review_recommended``, or prior-predictive not yet
       run, or missing retained analyst rationale -> ``review_recommended``.
       ``REQ-PREFIT-001`` requires retained analyst rationale before
       ``review_recommended`` may support official submission, so a
       component that is individually ``ready`` still keeps the run at
       ``review_recommended`` until rationale is retained.
    3. Otherwise (every component ``ready`` and rationale retained, where
       required) -> ``ready``.
    """

    components = {
        "identifiability": _require_readiness(
            identifiability_readiness, field_name="identifiability_readiness"
        ),
        "screening": _require_readiness(
            screening_readiness, field_name="screening_readiness"
        ),
    }
    if prior_predictive_readiness is not None:
        components["prior_predictive"] = _require_readiness(
            prior_predictive_readiness, field_name="prior_predictive_readiness"
        )

    reasons: list[str] = []
    if any(value == BLOCKED for value in components.values()):
        readiness = BLOCKED
        reasons.extend(
            f"{name} is blocked"
            for name, value in components.items()
            if value == BLOCKED
        )
    else:
        needs_review = [
            name for name, value in components.items() if value == REVIEW_RECOMMENDED
        ]
        if "prior_predictive" not in components:
            needs_review.append("prior_predictive (not yet run)")
        if needs_review:
            readiness = REVIEW_RECOMMENDED
            reasons.extend(f"{name} requires review" for name in needs_review)
        elif not analyst_rationale_retained:
            readiness = REVIEW_RECOMMENDED
            reasons.append(
                "every evidence component is ready, but retained analyst "
                "rationale is required before review_recommended/ready "
                "evidence may support official submission"
            )
        else:
            readiness = READY

    return {
        "readiness": readiness,
        "components": components,
        "analyst_rationale_retained": bool(analyst_rationale_retained),
        "reasons": reasons,
        "diagnostic_only": True,
    }


@dataclass(frozen=True)
class PrefitRun:
    """A durable, versioned pre-fit diagnostic run bound to one candidate
    model specification.

    Persisted through ``core.persistence`` (``config/prefit_runs.json``),
    exactly like ``core.experiments.ExperimentRecord`` and ``core.
    named_events`` records - never a second, ad hoc persistence mechanism.
    """

    schema_version: int
    run_id: str
    product: str
    model_name: str
    generated_at: str

    candidate_spec_fingerprint: str
    prepared_frame_fingerprint: str
    causal_graph_fingerprint: str
    transform_config_fingerprint: str

    fold_policy_version: str
    fold_manifest: tuple[Mapping[str, Any], ...]
    reconstruction_tier: str

    surrogate_method_version: str
    screen_grid_version: str
    support_threshold_policy_version: str
    prior_predictive_threshold_policy_version: str | None

    identifiability_report: Mapping[str, Any]
    screening_report: Mapping[str, Any]

    readiness: str
    readiness_detail: Mapping[str, Any]
    analyst_review: Mapping[str, Any]

    diagnostic_only: bool = True
    channel_selection_rule: bool = False
    model_mutation_applied: bool = False
    official_eligibility: bool = False
    downstream_use_restrictions: tuple[str, ...] = field(
        default_factory=lambda: (
            "not_official_attribution",
            "not_official_cpa_roi",
            "not_response_curve_approval",
            "not_planning_eligible",
            "not_optimisation_eligible",
        )
    )

    def __post_init__(self) -> None:
        if self.schema_version != PREFIT_RUN_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {PREFIT_RUN_SCHEMA_VERSION}, got "
                f"{self.schema_version!r}"
            )
        _require_readiness(self.readiness, field_name="readiness")
        if self.reconstruction_tier not in RECONSTRUCTION_TIERS:
            raise ValueError(
                f"reconstruction_tier must be one of {RECONSTRUCTION_TIERS!r}, "
                f"got {self.reconstruction_tier!r}"
            )
        if self.readiness == READY and not self.analyst_review.get(
            "rationale_retained"
        ):
            raise ValueError(
                "a PrefitRun cannot be constructed with readiness=ready "
                "unless analyst_review['rationale_retained'] is True - "
                "review_recommended/blocked must never be silently promoted"
            )

    def fingerprints(self) -> dict[str, str]:
        return {
            "candidate_spec_fingerprint": self.candidate_spec_fingerprint,
            "prepared_frame_fingerprint": self.prepared_frame_fingerprint,
            "causal_graph_fingerprint": self.causal_graph_fingerprint,
            "transform_config_fingerprint": self.transform_config_fingerprint,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fold_manifest"] = [dict(entry) for entry in self.fold_manifest]
        payload["downstream_use_restrictions"] = list(self.downstream_use_restrictions)
        payload["identifiability_report"] = dict(self.identifiability_report)
        payload["screening_report"] = dict(self.screening_report)
        payload["readiness_detail"] = dict(self.readiness_detail)
        payload["analyst_review"] = dict(self.analyst_review)
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PrefitRun":
        data = dict(payload)
        data["fold_manifest"] = tuple(
            dict(entry) for entry in data.get("fold_manifest") or ()
        )
        data["downstream_use_restrictions"] = tuple(
            data.get("downstream_use_restrictions") or ()
        )
        return cls(**data)


def build_run_id(fingerprints: Mapping[str, str], *, generated_at: str) -> str:
    """A deterministic run identity from the bound fingerprints and timestamp.

    Deterministic given the same inputs (matching this codebase's existing
    fingerprint philosophy - see ``core.fingerprint``), rather than a
    process-random UUID, so the same run rebuilt from the same evidence in a
    test never produces a spurious new identity.
    """

    return _json_fingerprint(
        {"fingerprints": dict(fingerprints), "generated_at": generated_at}
    )


def build_prefit_run(
    *,
    product: str,
    model_name: str,
    identifiability_report: Mapping[str, Any],
    screening_report: Mapping[str, Any],
    reconstruction_tier: str | None = None,
    fold_policy_version: str,
    support_threshold_policy_version: str,
    prior_predictive_threshold_policy_version: str | None = None,
    analyst_rationale_retained: bool | None = None,
    generated_at: str | None = None,
) -> PrefitRun:
    """Assemble a durable :class:`PrefitRun` from the two evidence reports.

    Neither report is mutated. ``identifiability_report`` and
    ``screening_report`` must already have been built by ``core.
    prefit_identifiability.build_prefit_identifiability_report`` and
    ``core.prefit_screening.build_prefit_screening_report`` respectively -
    this function only reads and consolidates their existing readiness
    fields; it never recomputes evidence.
    """

    if reconstruction_tier is None:
        reconstruction_tier = str(
            screening_report.get("reconstruction_tier", CANNOT_VERIFY)
        )

    fingerprints = dict(identifiability_report.get("fingerprints") or {})
    prior_predictive = identifiability_report.get("prior_predictive") or {}
    prior_predictive_readiness = prior_predictive.get("review_status")
    if prior_predictive_readiness not in PREFIT_READINESS_STATES:
        prior_predictive_readiness = None

    screening_analyst_review = dict(screening_report.get("analyst_review") or {})
    rationale_retained = (
        bool(screening_analyst_review.get("rationale_retained"))
        if analyst_rationale_retained is None
        else bool(analyst_rationale_retained)
    )

    screening_readiness = str(
        screening_report.get("review_status") or screening_report.get("status")
    )
    # The screening report is built with the identifiability report's own
    # fingerprints passed in as an explicit input (see application.
    # prefit_screening_service.run_prefit_screen's `fingerprints` kwarg,
    # wired from the identifiability report by the caller). If the screen
    # was bound to a *different* candidate's fingerprints - e.g. the
    # identifiability review was rerun after a config change but the
    # screen was not - the two evidence reports no longer describe the
    # same candidate and the run must be blocked, never silently
    # consolidated as though they matched.
    screening_fingerprints = dict(screening_report.get("fingerprints") or {})
    if screening_fingerprints and screening_fingerprints != fingerprints:
        screening_readiness = BLOCKED

    detail = consolidate_prefit_readiness(
        identifiability_readiness=str(
            identifiability_report.get("review_status")
            or identifiability_report.get("status")
        ),
        screening_readiness=screening_readiness,
        prior_predictive_readiness=prior_predictive_readiness,
        analyst_rationale_retained=rationale_retained,
    )
    if screening_fingerprints and screening_fingerprints != fingerprints:
        detail = dict(detail)
        detail["reasons"] = [
            *detail["reasons"],
            "screening evidence is bound to different fingerprints than the "
            "identifiability review - rerun the deterministic pre-fit screen",
        ]

    generated_at = generated_at or pd.Timestamp.now(tz="UTC").isoformat()
    fold_manifest = tuple(dict(entry) for entry in screening_report.get("folds") or ())

    return PrefitRun(
        schema_version=PREFIT_RUN_SCHEMA_VERSION,
        run_id=build_run_id(fingerprints, generated_at=generated_at),
        product=str(product),
        model_name=str(model_name),
        generated_at=generated_at,
        candidate_spec_fingerprint=str(
            fingerprints.get("candidate_spec_fingerprint", "")
        ),
        prepared_frame_fingerprint=str(
            fingerprints.get("prepared_frame_fingerprint", "")
        ),
        causal_graph_fingerprint=str(fingerprints.get("causal_graph_fingerprint", "")),
        transform_config_fingerprint=str(
            fingerprints.get("transform_config_fingerprint", "")
        ),
        fold_policy_version=str(fold_policy_version),
        fold_manifest=fold_manifest,
        reconstruction_tier=_require_reconstruction_tier(reconstruction_tier),
        surrogate_method_version=str(
            screening_report.get("diagnostic_version", "unknown")
        ),
        screen_grid_version=str(screening_report.get("screen_grid_version", "unknown")),
        support_threshold_policy_version=str(support_threshold_policy_version),
        prior_predictive_threshold_policy_version=(
            str(prior_predictive_threshold_policy_version)
            if prior_predictive_threshold_policy_version is not None
            else None
        ),
        identifiability_report=identifiability_report,
        screening_report=screening_report,
        readiness=detail["readiness"],
        readiness_detail=detail,
        analyst_review=screening_analyst_review
        or {
            "status": "not_available",
            "rationale": None,
            "rationale_retained": False,
        },
    )


def _require_reconstruction_tier(value: str) -> str:
    text = str(value)
    if text not in RECONSTRUCTION_TIERS:
        raise ValueError(
            f"reconstruction_tier must be one of {RECONSTRUCTION_TIERS!r}, got {value!r}"
        )
    return text


def prefit_run_is_stale(
    run: PrefitRun | Mapping[str, Any], current_fingerprints: Mapping[str, str]
) -> dict[str, Any]:
    """Compare a persisted/session run's bound fingerprints with current ones.

    Reuses the exact same comparison semantics as ``core.
    prefit_identifiability.prefit_diagnostic_freshness`` - a PrefitRun is
    stale under precisely the same rule its component reports already use.
    """

    recorded: dict[str, str]
    if isinstance(run, PrefitRun):
        recorded = run.fingerprints()
    else:
        payload = dict(run)
        recorded = {
            key: str(payload[key]) if key in payload else ""
            for key in (
                "candidate_spec_fingerprint",
                "prepared_frame_fingerprint",
                "causal_graph_fingerprint",
                "transform_config_fingerprint",
            )
        }
    keys = set(recorded) | set(current_fingerprints)
    mismatches = {
        key: {"recorded": recorded.get(key), "current": current_fingerprints.get(key)}
        for key in sorted(keys)
        if recorded.get(key) != current_fingerprints.get(key)
    }
    return {
        "status": "stale" if mismatches else "current",
        "stale": bool(mismatches),
        "mismatches": mismatches,
    }


def official_submission_allowed(run: PrefitRun | Mapping[str, Any]) -> tuple[bool, str]:
    """The single governed answer to "can this run support official
    submission right now". Returns ``(allowed, reason)``.

    ``blocked`` is never overridable. ``review_recommended`` requires
    retained analyst rationale (already enforced by ``PrefitRun.
    __post_init__`` for the ``ready`` case, checked again here explicitly so
    a caller holding a raw dict - e.g. reloaded from session state or an
    imported project bundle - gets the same fail-closed answer without first
    reconstructing a ``PrefitRun``).
    """

    if isinstance(run, PrefitRun):
        payload = run.to_dict()
    else:
        payload = dict(run)
    readiness = payload.get("readiness")
    if readiness == BLOCKED:
        return False, "pre-fit readiness is blocked"
    if readiness == READY:
        return True, "pre-fit readiness is ready"
    if readiness == REVIEW_RECOMMENDED:
        analyst_review = dict(payload.get("analyst_review") or {})
        if analyst_review.get("rationale_retained"):
            return True, "review_recommended with retained analyst rationale"
        return False, "review_recommended requires retained analyst rationale"
    return False, f"unrecognised readiness state {readiness!r}"
