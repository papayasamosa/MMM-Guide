"""Regression coverage for ancestry_mmm.application.fit_job_worker.run_job.

Focuses on the worker's own startup PID/status update - the only remaining
unlocked read-then-blind-save in the durable fit-job lifecycle (Codex review
5121* thread on PR #351, e580f2b7).
"""

from __future__ import annotations

import os
from pathlib import Path

from ancestry_mmm.application.fit_job_service import FitJobStore, FitJobSubmission
from ancestry_mmm.application.fit_job_worker import run_job


def _submission(project_id: str = "worker-test-project") -> FitJobSubmission:
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


def test_worker_startup_update_preserves_a_racing_launcher_identity_write(
    tmp_path: Path, monkeypatch
):
    """Forces the exact race the review flagged:

    1. The worker reads the job record (no PID/identity token yet).
    2. The launcher wins the race and records PID + process_identity_token
       in the gap between that read and the worker's own update.
    3. The worker performs its startup PID/status ("running") update.
    4. The persisted record is reloaded.

    Before the fix, step 3 was a blind ``store.save()`` of the worker's
    stale step-1 snapshot, which clobbered the launcher's step-2 write back
    to ``None``. The fixed worker instead uses the same targeted, locked
    ``update_process_metadata`` read-modify-write the launcher itself uses.
    """

    launcher_store = FitJobStore(tmp_path, "worker-test-project")
    record = launcher_store.create(_submission())

    original_get = FitJobStore.get
    read_count = {"n": 0}

    def racing_get(self, job_id):
        result = original_get(self, job_id)
        read_count["n"] += 1
        if read_count["n"] == 1:
            # The worker's very first read (inside run_job) just happened.
            # Simulate the launcher winning the race right after it, before
            # the worker performs its own update.
            launcher_store.update_process_metadata(job_id, pid=os.getpid())
        return result

    monkeypatch.setattr(FitJobStore, "get", racing_get)

    running_snapshot = {}
    original_transition = FitJobStore.transition

    def spying_transition(self, job_id, status, **kwargs):
        result = original_transition(self, job_id, status, **kwargs)
        if status == "running":
            running_snapshot["record"] = result
        return result

    monkeypatch.setattr(FitJobStore, "transition", spying_transition)

    def _stop_before_a_real_fit(**kwargs):
        raise RuntimeError("stop before a real fit for this race regression")

    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_worker.build_model_for_spec",
        _stop_before_a_real_fit,
    )

    exit_code = run_job(launcher_store.job_dir(record.job_id))

    assert exit_code == 1, "the injected build failure should mark the job failed"
    assert "record" in running_snapshot, "worker never reached the running transition"
    running_record = running_snapshot["record"]

    # Status advanced correctly to running, and PID/identity metadata the
    # launcher wrote concurrently survived the worker's own update.
    assert running_record.status == "running"
    assert running_record.pid == os.getpid()
    assert running_record.process_identity_token, (
        "the launcher's concurrently-written identity token must survive "
        "the worker's own startup update, not be clobbered back to None"
    )

    # The worker's later writes (progress/terminal transition) must not
    # have clobbered it either.
    final_record = launcher_store.get(record.job_id)
    assert final_record.status == "failed"
    assert final_record.process_identity_token == running_record.process_identity_token

    # The preserved token is not merely present but functionally correct
    # for PID-reuse detection: process_is_alive must still recognise the
    # real live process by it, and reject an unrelated process reusing the
    # same PID.
    from ancestry_mmm.application.fit_job_service import process_is_alive

    assert process_is_alive(os.getpid(), final_record.process_identity_token) is True
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service._capture_process_identity_token",
        lambda pid: "unrelated-process-token",
    )
    assert process_is_alive(os.getpid(), final_record.process_identity_token) is False
