from ancestry_mmm.application.migration_review_service import (
    migration_review_after_fit_adoption,
)


def test_replacement_fit_completes_migration_review_without_dropping_audit_fields():
    previous = {
        "migration_review_status": "reviewed_refit_required",
        "migration_reviewed_by": "Migration Reviewer",
        "migration_reviewed_at": "2026-07-23T12:00:00+00:00",
        "migration_review_note": "Reclassified and refitted.",
        "migrated_from_model_run_id": "legacy-run",
        "migration_change_summary": {"component_type_changes": [{"channel": "TV"}]},
        "model_invalidated": True,
        "replacement_model_run_id": None,
    }

    updated = migration_review_after_fit_adoption(previous, "replacement-run")

    assert updated["migration_review_status"] == "refit_completed"
    assert updated["replacement_model_run_id"] == "replacement-run"
    assert updated["migration_reviewed_by"] == "Migration Reviewer"
    assert updated["migration_reviewed_at"] == "2026-07-23T12:00:00+00:00"
    assert updated["migration_review_note"] == "Reclassified and refitted."
    assert updated["migrated_from_model_run_id"] == "legacy-run"
    assert updated["migration_change_summary"] == {
        "component_type_changes": [{"channel": "TV"}]
    }
    assert updated["model_invalidated"] is True
    assert updated["refit_completed_at"]
