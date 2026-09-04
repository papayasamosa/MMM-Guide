from __future__ import annotations

import os
from pathlib import Path

import pytest

from ancestry_mmm.application.fit_job_service import (
    FitJobProgress,
    FitJobStore,
    FitJobSubmission,
    LocalFitJobBackend,
)


def _submission(project_id: str = "test-project") -> FitJobSubmission:
    return FitJobSubmission(
        project_id=project_id,
        engine="pymc",
        model_type="shared",
        sampler_settings={"draws": 4, "tune": 2, "chains": 1, "target_accept": 0.9},
        random_seed=42,
        data_fingerprint="data-fp",
        model_spec_fingerprint="spec-fp",
        fit_input_fingerprints={"seo": "seo-fp"},
        build_kwargs={"frame": {"values": [1, 2]}, "model_spec": {"x": 1}},
        project_run_id="run-1",
    )


def test_fit_job_record_round_trip_and_progress(tmp_path: Path):
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    restored = store.get(record.job_id)

    assert restored.status == "queued"
    assert restored.random_seed == 42
    assert restored.progress.total_steps == 6
    store.update_progress(
        record.job_id, phase="sampling", completed_steps=3, divergences=1
    )
    assert store.get(record.job_id).progress == FitJobProgress(
        phase="sampling",
        completed_steps=3,
        total_steps=6,
        divergences=1,
        last_updated_at=store.get(record.job_id).progress.last_updated_at,
    )


def test_transitions_cancellation_and_orphan_recovery(tmp_path: Path):
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    store.transition(record.job_id, "running")
    store.request_cancel(record.job_id, "stop this run")
    assert store.get(record.job_id).status == "cancel_requested"
    store.reconcile()
    assert store.get(record.job_id).status == "cancelled"

    orphan = store.create(_submission())
    orphan.pid = 2**31 - 1
    store.save(orphan)
    store.transition(orphan.job_id, "running")
    recovered = store.reconcile()
    assert any(
        item.job_id == orphan.job_id and item.status == "orphaned" for item in recovered
    )


def test_submit_launches_a_separate_worker_command_and_persists_pid(tmp_path: Path):
    calls = []

    class FakeProcess:
        pid = 12345

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return FakeProcess()

    store = FitJobStore(tmp_path, "test-project")
    backend = LocalFitJobBackend(store, popen_factory=fake_popen)
    record = backend.submit(_submission())

    assert record.pid == 12345
    assert calls[0][0][0] == os.sys.executable
    assert "ancestry_mmm.application.fit_job_worker" in calls[0][0]
    assert Path(record.job_spec_location).exists()
    assert store.load_build_kwargs(record.job_id)["frame"] == {"values": [1, 2]}


def test_adoption_identity_mismatch_does_not_load_artifact(tmp_path: Path):
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    backend = LocalFitJobBackend(store, popen_factory=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="data fingerprint"):
        backend.load_succeeded_fit(record.job_id, expected_data_fingerprint="different")
