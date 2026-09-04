"""Framework-independent migration-review state transitions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


def migration_review_after_fit_adoption(
    previous: Mapping[str, Any] | None,
    replacement_model_run_id: str | None,
) -> dict[str, Any] | None:
    """Record the audit state created by adopting a durable fit.

    A migrated project starts in ``reviewed_refit_required``.  Adopting its
    replacement fit completes that review while retaining the reviewer,
    migration summary, and source-run fields. Projects without a migration
    review, or whose migration review is already complete, retain their
    existing value. Ordinary fit adoption must not invent a migration
    obligation.
    """

    now = datetime.now(timezone.utc).isoformat()
    if (
        isinstance(previous, Mapping)
        and previous.get("migration_review_status") == "reviewed_refit_required"
    ):
        result = dict(previous)
        result.update(
            {
                "migration_review_status": "refit_completed",
                "refit_completed_at": now,
                "replacement_model_run_id": replacement_model_run_id,
            }
        )
        return result
    if isinstance(previous, Mapping):
        return dict(previous)
    return previous
