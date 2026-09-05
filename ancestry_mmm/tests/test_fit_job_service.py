from __future__ import annotations

import json
import os
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from ancestry_mmm.application.fit_job_service import (
    FitJobProgress,
    FitJobStore,
    FitJobSubmission,
    LocalFitJobBackend,
    canonical_project_id,
    process_is_alive,
)
from ancestry_mmm.core.fingerprint import fingerprint_candidate_a_fit_inputs
from ancestry_mmm.core.google_trends_anchor import (
    GoogleTrendsAnchorFitInputs,
    GoogleTrendsAnchorObservation,
    GoogleTrendsQuerySetDefinition,
)
from ancestry_mmm.core.search_capacity import (
    CandidateASearchFitInputs,
    SearchCandidateASpec,
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


def test_submit_preserves_worker_state_when_worker_wins_pid_race(tmp_path: Path):
    class FakeProcess:
        pid = 12345

    store = FitJobStore(tmp_path, "test-project")

    def fake_popen(command, **kwargs):
        job_id = Path(command[-1]).name
        store.transition(job_id, "running", message="worker started")
        return FakeProcess()

    backend = LocalFitJobBackend(store, popen_factory=fake_popen)
    record = backend.submit(_submission())

    assert record.status == "running"
    assert record.pid == 12345
    assert record.process_start_time

    succeeded = store.transition(record.job_id, "succeeded", message="done")
    restored = store.get(record.job_id)
    assert succeeded.status == "succeeded"
    assert restored.status == "succeeded"
    assert restored.error_summary == ""


def test_request_cancel_does_not_overwrite_worker_success(tmp_path: Path, monkeypatch):
    """Cancellation metadata is a locked read/modify/write operation.

    The worker is deliberately started after the cancellation path has read
    the record. It must wait for that same record lock, then observe the
    cancel-requested state and complete without a stale cancellation write
    reverting its terminal success.
    """

    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    store.transition(record.job_id, "running")
    original_get = store.get
    worker_started = threading.Event()
    worker_holder = []

    def worker() -> None:
        store.transition(record.job_id, "succeeded", message="worker completed")

    def get_with_worker_race(job_id: str):
        current = original_get(job_id)
        if not worker_started.is_set():
            worker_started.set()
            thread = threading.Thread(target=worker)
            worker_holder.append(thread)
            thread.start()
        return current

    monkeypatch.setattr(store, "get", get_with_worker_race)
    cancelled = store.request_cancel(record.job_id, "stop this run")
    worker_holder[0].join(timeout=5)

    assert not worker_holder[0].is_alive()
    assert cancelled.status == "cancel_requested"
    restored = store.get(record.job_id)
    assert restored.status == "succeeded"
    assert restored.cancellation_reason == "stop this run"
    assert restored.error_summary == ""


def test_reconcile_rechecks_terminal_state_before_marking_worker_orphaned(
    tmp_path: Path, monkeypatch
):
    store = FitJobStore(tmp_path, "project")
    record = store.create(_submission(project_id="project"))
    store.transition(record.job_id, "running")
    stale = store.get(record.job_id)
    original_list = store.list

    def list_then_worker_finishes(*, statuses=None):
        original_list(statuses=statuses)
        store.transition(record.job_id, "succeeded")
        return [stale]

    monkeypatch.setattr(store, "list", list_then_worker_finishes)
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service.process_is_alive", lambda pid: False
    )

    assert store.reconcile() == []
    assert store.get(record.job_id).status == "succeeded"


def test_reconcile_does_not_orphan_queued_job_before_pid_is_recorded(
    tmp_path: Path, monkeypatch
):
    """A second session must not win the create/Popen/PID hand-off race."""

    store = FitJobStore(tmp_path, "project")
    record = store.create(_submission(project_id="project"))
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service.process_is_alive", lambda pid: False
    )

    assert store.reconcile() == []
    assert store.get(record.job_id).status == "queued"


def test_reconcile_orphans_queued_job_after_pid_hand_off_if_process_is_dead(
    tmp_path: Path, monkeypatch
):
    """A completed launcher hand-off must still participate in liveness checks."""

    store = FitJobStore(tmp_path, "project")
    record = store.create(_submission(project_id="project"))
    store.update_process_metadata(
        record.job_id, pid=12345, process_start_time="started"
    )
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service.process_is_alive", lambda pid: False
    )

    recovered = store.reconcile()

    assert any(item.job_id == record.job_id for item in recovered)
    assert store.get(record.job_id).status == "orphaned"


def test_reconcile_expires_a_pidless_queued_launch_after_grace_period(tmp_path: Path):
    store = FitJobStore(tmp_path, "project")
    record = store.create(_submission(project_id="project"))
    record.created_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    store.save(record)

    recovered = store.reconcile()

    assert any(item.job_id == record.job_id for item in recovered)
    assert store.get(record.job_id).status == "orphaned"


def test_process_is_alive_rejects_a_posix_zombie(monkeypatch):
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service._posix_process_state",
        lambda pid: "Z",
    )
    monkeypatch.setattr(
        "ancestry_mmm.application.fit_job_service.os.kill",
        lambda pid, signal: None,
    )

    assert process_is_alive(12345) is False


@pytest.fixture
def candidate_a_fit_inputs() -> CandidateASearchFitInputs:
    query_set = GoogleTrendsQuerySetDefinition(
        query_set_id="uk-brand-v1",
        branded_terms=("Ancestry",),
        geography="GB",
        time_range_start="2026-01-05",
        time_range_end="2026-01-12",
    )
    anchor = GoogleTrendsAnchorFitInputs(
        query_set=query_set,
        observations=(
            GoogleTrendsAnchorObservation(
                query_set_id="uk-brand-v1",
                week="2026-01-05",
                raw_index=40.0,
                anchor_value=0.4,
            ),
            GoogleTrendsAnchorObservation(
                query_set_id="uk-brand-v1",
                week="2026-01-12",
                raw_index=60.0,
                anchor_value=0.6,
            ),
        ),
        model_weeks=("2026-01-05", "2026-01-12"),
    )
    spec = SearchCandidateASpec(
        outcome_definition_id="fh_new",
        outcome_definition_version="1",
        outcome_definition_fingerprint="outcome-fp",
        market_scope="UK",
        demand_object_id="search-demand",
        paid_spend_object_id="paid-spend",
        paid_delivery_object_id="paid-delivery",
        paid_cap_object_id="paid-cap",
        organic_capture_object_id="organic",
        direct_navigation_object_id="direct",
    )
    return CandidateASearchFitInputs(
        spec=spec,
        demand_channel_names=["TV"],
        paid_search_delivery=np.asarray([1.0, 2.0]),
        paid_search_cap=np.asarray([3.0, 4.0]),
        organic_search_capture=np.asarray([5.0, 6.0]),
        direct_navigation_capture=np.asarray([7.0, 8.0]),
        search_objects=[
            {
                "search_object_id": "paid-delivery",
                "search_role": "paid_delivery",
                "source_column": "paid_delivery",
                "model_input_column": "PaidSearch",
                "market": "UK",
                "unit": "exposure_count",
            }
        ],
        google_trends_anchor=anchor,
    )


def _write_succeeded_artifact(store, record, monkeypatch):
    store.transition(record.job_id, "running")
    result_path = Path(record.result_artifact_location)
    result_path.write_bytes(b"test artifact")
    result_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "job_id": record.job_id,
                "data_fingerprint": record.data_fingerprint,
                "model_spec_fingerprint": record.model_spec_fingerprint,
                "fit_input_fingerprints": record.fit_input_fingerprints,
                "meta": {
                    "markets": ["UK"],
                    "outcome_ids": ["outcome"],
                    "channels": ["channel"],
                    "dna_channels": [],
                    "dna_channel_idx": [],
                    "non_dna_idx": [0],
                    "dna_outcome_id": "outcome",
                    "dna_lag_weeks": 0,
                    "unpooled_markets": [],
                    "control_names": [],
                },
            }
        ),
        encoding="utf-8",
    )
    store.transition(record.job_id, "succeeded")
    monkeypatch.setattr(
        "arviz.from_netcdf",
        lambda path: SimpleNamespace(posterior=object()),
    )


def test_candidate_a_fit_boundary_is_adoptable_when_unchanged(
    tmp_path: Path, candidate_a_fit_inputs, monkeypatch
):
    fit_fingerprint = fingerprint_candidate_a_fit_inputs(candidate_a_fit_inputs)
    submission = replace(
        _submission(),
        fit_input_fingerprints={"candidate_a": fit_fingerprint},
    )
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(submission)
    _write_succeeded_artifact(store, record, monkeypatch)

    _trace, _meta, restored = LocalFitJobBackend(store).load_succeeded_fit(
        record.job_id,
        expected_fit_input_fingerprints={"candidate_a": fit_fingerprint},
    )
    assert restored.status == "succeeded"


def test_candidate_a_fingerprint_is_canonical_across_equivalent_serializations(
    candidate_a_fit_inputs,
):
    payload = candidate_a_fit_inputs.to_dict()
    reordered_payload = {key: payload[key] for key in reversed(tuple(payload))}

    assert fingerprint_candidate_a_fit_inputs(candidate_a_fit_inputs) == (
        fingerprint_candidate_a_fit_inputs(reordered_payload)
    )
    assert fingerprint_candidate_a_fit_inputs(candidate_a_fit_inputs) == (
        fingerprint_candidate_a_fit_inputs(CandidateASearchFitInputs.from_dict(payload))
    )


@pytest.mark.parametrize(
    "field",
    [
        "paid_search_delivery",
        "paid_search_cap",
        "organic_search_capture",
        "direct_navigation_capture",
    ],
)
def test_candidate_a_search_observation_changes_fail_closed(
    tmp_path: Path, candidate_a_fit_inputs, field
):
    original_fingerprint = fingerprint_candidate_a_fit_inputs(candidate_a_fit_inputs)
    submission = replace(
        _submission(),
        fit_input_fingerprints={"candidate_a": original_fingerprint},
    )
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(submission)
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    changed_values = getattr(candidate_a_fit_inputs, field).copy()
    changed_values[0] += 0.25
    changed_inputs = replace(candidate_a_fit_inputs, **{field: changed_values})

    with pytest.raises(ValueError, match="input fingerprints"):
        LocalFitJobBackend(store).load_succeeded_fit(
            record.job_id,
            expected_fit_input_fingerprints={
                "candidate_a": fingerprint_candidate_a_fit_inputs(changed_inputs)
            },
        )


def test_candidate_a_google_trends_anchor_change_fails_closed(
    tmp_path: Path, candidate_a_fit_inputs
):
    original_fingerprint = fingerprint_candidate_a_fit_inputs(candidate_a_fit_inputs)
    submission = replace(
        _submission(),
        fit_input_fingerprints={"candidate_a": original_fingerprint},
    )
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(submission)
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    anchor = candidate_a_fit_inputs.google_trends_anchor
    assert anchor is not None
    changed_observation = replace(
        anchor.observations[0], raw_index=41.0, anchor_value=0.41
    )
    changed_anchor = replace(
        anchor,
        observations=(changed_observation, *anchor.observations[1:]),
    )
    changed_inputs = replace(
        candidate_a_fit_inputs, google_trends_anchor=changed_anchor
    )

    with pytest.raises(ValueError, match="input fingerprints"):
        LocalFitJobBackend(store).load_succeeded_fit(
            record.job_id,
            expected_fit_input_fingerprints={
                "candidate_a": fingerprint_candidate_a_fit_inputs(changed_inputs)
            },
        )


def test_ordinary_fit_adoption_keeps_its_existing_input_boundary(
    tmp_path: Path, monkeypatch
):
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    _write_succeeded_artifact(store, record, monkeypatch)

    _trace, _meta, restored = LocalFitJobBackend(store).load_succeeded_fit(
        record.job_id,
        expected_fit_input_fingerprints={"seo": "seo-fp"},
    )
    assert restored.status == "succeeded"


@pytest.mark.parametrize(
    "display_name",
    [
        "UK Production 2026",
        "UK-Production 2026",
        "UK/Production: 2026!",
        "UK   Production    2026",
    ],
)
def test_human_project_names_use_one_canonical_durable_job_id(
    tmp_path: Path, display_name: str
):
    class FakeProcess:
        pid = os.getpid()

    store = FitJobStore(tmp_path, display_name)
    backend = LocalFitJobBackend(
        store, popen_factory=lambda *args, **kwargs: FakeProcess()
    )
    record = backend.submit(
        replace(_submission(display_name), project_display_name=display_name)
    )

    expected_id = canonical_project_id(display_name)
    assert expected_id
    assert store.project_id == expected_id
    assert record.project_id == expected_id
    assert record.project_display_name == display_name

    recovered_store = FitJobStore(tmp_path, display_name)
    recovered = recovered_store.get(record.job_id)
    assert recovered.status == "queued"
    assert recovered.project_display_name == display_name


def test_distinct_human_names_cannot_share_a_canonical_project_id():
    names = (
        "UK Production 2026",
        "UK/Production: 2026!",
        "UK   Production    2026",
    )
    assert len({canonical_project_id(name) for name in names}) == len(names)


def test_project_recovery_uses_the_explicit_human_name_not_a_global_latest_job(
    tmp_path: Path,
):
    first = FitJobStore(tmp_path, "first project")
    first_record = first.create(
        replace(_submission("first project"), project_display_name="first project")
    )
    second = FitJobStore(tmp_path, "second project")
    second_record = second.create(
        replace(_submission("second project"), project_display_name="second project")
    )

    assert first.project_id != second.project_id
    assert first.get(first_record.job_id).project_display_name == "first project"
    assert second.get(second_record.job_id).project_display_name == "second project"


def test_adoption_identity_mismatch_does_not_load_artifact(tmp_path: Path):
    store = FitJobStore(tmp_path, "test-project")
    record = store.create(_submission())
    store.transition(record.job_id, "running")
    store.transition(record.job_id, "succeeded")
    backend = LocalFitJobBackend(store, popen_factory=lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="data fingerprint"):
        backend.load_succeeded_fit(record.job_id, expected_data_fingerprint="different")
