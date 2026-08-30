"""Governed future-assumption bundle (`REQ-FUTURE-001`; Decision 14
continuation of the "Post-UI/UX Implementation Instructions: Approved
Business Decisions" brief).

See `docs/future_assumption_bundle_architecture_decision_record.md` for
the full options-considered decision record (why the B1 bundle schema,
M3 materiality policy, and F1 forecaster-integration policy were
chosen).

Summary (see the decision record for full reasoning):

1. Bundle schema: B1, a thin named wrapper
   (`FutureAssumptionBundle`) around existing `core.planning.
   future_context.FutureContextResult`s, keyed by a caller-chosen string
   (typically market, or market+scenario) - `core.planning.
   future_context` itself is completely unchanged.
2. Materiality policy: M3, disclosed ungraded evidence only - no
   materiality score or blocking/non-blocking verdict field anywhere in
   this module, matching `core.calibration_comparison`'s own
   already-established precedent exactly.
3. External-forecaster integration policy: F1, no production
   integration now - a bundle's future path for any control remains
   either an explicit analyst-supplied series or an exploratory
   `hold_last_observed` assumption, exactly as `core.planning.
   future_context` already supports.

This module does not modify `core.planning.future_context`,
`core.persistence`, or any `pages/*.py` UI - it is additive, standalone,
and read-only with respect to `FutureContextResult`.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, Mapping, Tuple

from .future_context import (
    EXPLICIT_ASSUMPTION,
    HOLD_LAST_OBSERVED_ASSUMPTION,
    FutureContextResult,
)

FUTURE_ASSUMPTION_BUNDLE_SCHEMA_VERSION = 1

FUTURE_ASSUMPTION_BUNDLE_MATERIALITY_POLICY = "M3_disclosed_ungraded_evidence_only"
EXTERNAL_FORECASTER_INTEGRATION_POLICY = "F1_no_production_integration"


@dataclass(frozen=True)
class FutureAssumptionBundle:
    """A named, versioned collection of `FutureContextResult`s (decision
    B1). `context_by_key` is keyed by whatever the caller uses to
    distinguish contexts within one bundle - typically a market name, or
    a `market::scenario_id` composite; this module has no domain
    knowledge of what the key should mean beyond uniqueness.

    `bundle_id`/`bundle_version` is the lineage/version identity,
    mirroring `core.search_objects`/`core.experiments`/`core.capacity`'s
    established immutability pattern exactly.
    """

    bundle_id: str
    bundle_version: int
    context_by_key: Mapping[str, FutureContextResult]
    owner: str = ""
    notes: str = ""
    schema_version: int = FUTURE_ASSUMPTION_BUNDLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.bundle_id:
            raise ValueError("FutureAssumptionBundle requires a bundle_id.")
        if self.bundle_version < 1:
            raise ValueError("FutureAssumptionBundle.bundle_version must be >= 1.")
        if not self.context_by_key:
            raise ValueError(
                "FutureAssumptionBundle requires at least one context - an "
                "empty bundle is not a governed collection of anything."
            )

    @property
    def is_decision_ready(self) -> bool:
        """`False` whenever any wrapped context is not decision-ready
        (i.e. used an exploratory `hold_last_observed` assumption for at
        least one control) - the logical AND of every wrapped
        `FutureContextResult.is_decision_ready`, generalising that
        record's own existing rule across every context this bundle
        wraps."""
        return all(
            context.is_decision_ready for context in self.context_by_key.values()
        )

    def fingerprint(self) -> str:
        """A bundle's fingerprint is built from every wrapped context's
        OWN existing fingerprint - never a re-hash of that context's raw
        content, which `FutureContextResult.fingerprint()` already
        computes and owns."""
        import hashlib
        import json

        payload = {
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "context_fingerprints": {
                key: context.fingerprint()
                for key, context in sorted(self.context_by_key.items())
            },
            "schema_version": self.schema_version,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "bundle_version": self.bundle_version,
            "context_keys": sorted(self.context_by_key.keys()),
            "owner": self.owner,
            "notes": self.notes,
            "schema_version": self.schema_version,
            "is_decision_ready": self.is_decision_ready,
            "fingerprint": self.fingerprint(),
        }


def new_bundle_version(
    bundle: FutureAssumptionBundle, **changes: Any
) -> FutureAssumptionBundle:
    """Apply an edit to a registered bundle as a new version - never an
    in-place mutation of history. Mirrors `core.search_objects.new_
    search_object_version`/`core.experiments.new_experiment_version`/
    `core.capacity.new_capacity_limit_version` exactly."""
    for locked_field in ("bundle_id", "bundle_version"):
        if locked_field in changes:
            raise ValueError(
                f"{locked_field!r} is lineage/version identity and cannot "
                "be set via new_bundle_version."
            )
    return replace(bundle, bundle_version=bundle.bundle_version + 1, **changes)


def current_bundle_versions(
    bundles: Iterable[FutureAssumptionBundle],
) -> Tuple[FutureAssumptionBundle, ...]:
    """Resolve, per `bundle_id` lineage, the current (highest
    `bundle_version`) bundle."""
    latest: Dict[str, FutureAssumptionBundle] = {}
    for bundle in bundles:
        current = latest.get(bundle.bundle_id)
        if current is None or bundle.bundle_version > current.bundle_version:
            latest[bundle.bundle_id] = bundle
    return tuple(latest.values())


@dataclass(frozen=True)
class BundleControlProvenanceSummary:
    """A flat, deduplicated view of control provenance across every
    context a bundle wraps (decision 14's own "users should provide
    things they actually control... everything else should come from
    governed defaults" framing, applied at the bundle level). Never a
    materiality score or verdict - purely a disclosed count/listing
    (decision M3)."""

    analyst_supplied_control_names: Tuple[str, ...]
    exploratory_hold_last_observed_control_names: Tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def summarise_bundle_control_provenance(
    bundle: FutureAssumptionBundle,
) -> BundleControlProvenanceSummary:
    """Aggregate every wrapped context's `control_assumptions` into one
    bundle-level provenance summary - which controls, anywhere in the
    bundle, were analyst-supplied (`EXPLICIT_ASSUMPTION`) versus
    exploratory-only (`HOLD_LAST_OBSERVED_ASSUMPTION`). A control name
    appearing under both categories in different contexts is reported in
    both sets - this function does not collapse or average across
    contexts, it only deduplicates within each category."""
    analyst_supplied: set = set()
    exploratory: set = set()
    for context in bundle.context_by_key.values():
        for assumption in context.control_assumptions:
            if assumption.assumption == EXPLICIT_ASSUMPTION:
                analyst_supplied.add(assumption.name)
            elif assumption.assumption == HOLD_LAST_OBSERVED_ASSUMPTION:
                exploratory.add(assumption.name)
    return BundleControlProvenanceSummary(
        analyst_supplied_control_names=tuple(sorted(analyst_supplied)),
        exploratory_hold_last_observed_control_names=tuple(sorted(exploratory)),
    )
