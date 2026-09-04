"""Durable local fit-job orchestration.

The Streamlit process is intentionally only a client of this module.  A fit
submission is a small, immutable snapshot plus a JSON job record; sampling is
performed by :mod:`ancestry_mmm.application.fit_job_worker` in a separate
Python process.  This keeps a browser refresh, Streamlit rerun, or session
loss from changing the identity or state of a fit.

The worker is deliberately thin: it calls the existing
``build_model_for_spec`` service and the existing ``core.models.fit_model``
function.  No model algebra belongs in this orchestration layer.
"""

from __future__ import annotations

import json
import os
import pickle
import re
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Iterator,
    List,
    Mapping,
    Optional,
    cast,
)


FIT_JOB_SCHEMA_VERSION = 1
JOB_STATES = (
    "queued",
    "running",
    "succeeded",
    "failed",
    "cancel_requested",
    "cancelled",
    "orphaned",
)
ACTIVE_JOB_STATES = {"queued", "running", "cancel_requested"}
TERMINAL_JOB_STATES = {"succeeded", "failed", "cancelled", "orphaned"}
_ALLOWED_TRANSITIONS = {
    "queued": {"running", "cancel_requested", "cancelled", "orphaned", "failed"},
    "running": {"succeeded", "failed", "cancel_requested", "cancelled", "orphaned"},
    "cancel_requested": {"cancelled", "failed", "orphaned", "succeeded"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "orphaned": set(),
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


def canonical_project_id(project_name: str) -> str:
    """Return the stable filesystem/job identifier for a display name.

    Project names are user-facing values and may contain whitespace or
    punctuation.  Durable storage uses this one canonical representation;
    the original value can still be retained on the job record for display.
    """

    if not isinstance(project_name, str):
        raise TypeError("project_name must be a string")
    return _SAFE_NAME.sub("_", project_name).strip("._") or "default"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    os.replace(temporary, path)


@dataclass
class FitJobProgress:
    phase: str = "queued"
    completed_steps: int = 0
    total_steps: int = 0
    chain: Optional[int] = None
    draw_idx: Optional[int] = None
    tuning: Optional[bool] = None
    divergences: int = 0
    max_treedepth_hits: int = 0
    tree_depth: Optional[float] = None
    tree_size: Optional[float] = None
    step_size: Optional[float] = None
    started_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "FitJobProgress":
        value = value or {}
        known = set(cls.__dataclass_fields__)
        return cls(**{key: value[key] for key in known if key in value})


@dataclass
class FitJobRecord:
    job_id: str
    project_id: str
    status: str
    created_at: str
    engine: str
    model_type: str
    sampler_settings: Dict[str, Any]
    random_seed: Optional[int]
    data_fingerprint: str
    model_spec_fingerprint: str
    fit_input_fingerprints: Dict[str, str]
    project_run_id: Optional[str]
    schema_version: int = FIT_JOB_SCHEMA_VERSION
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    pid: Optional[int] = None
    process_start_time: Optional[str] = None
    progress: FitJobProgress = field(default_factory=FitJobProgress)
    job_spec_location: str = ""
    result_artifact_location: str = ""
    log_location: str = ""
    error_summary: str = ""
    cancellation_requested_at: Optional[str] = None
    cancellation_reason: str = ""
    cancelled_at: Optional[str] = None
    adopted_at: Optional[str] = None
    adopted_model_run_id: Optional[str] = None
    project_display_name: str = ""

    def __post_init__(self) -> None:
        if self.status not in JOB_STATES:
            raise ValueError(f"Unknown fit-job state: {self.status}")
        if not self.job_id or not self.project_id:
            raise ValueError("Fit jobs require job_id and project_id.")
        if isinstance(self.progress, dict):
            self.progress = FitJobProgress.from_dict(self.progress)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["progress"] = self.progress.to_dict()
        return payload

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FitJobRecord":
        payload = dict(value)
        payload["progress"] = FitJobProgress.from_dict(payload.get("progress"))
        known = set(cls.__dataclass_fields__)
        return cls(**{key: payload[key] for key in known if key in payload})


@dataclass(frozen=True)
class FitJobSubmission:
    """Serializable identity and payload for one proposed fit."""

    project_id: str
    engine: str
    model_type: str
    sampler_settings: Mapping[str, Any]
    random_seed: Optional[int]
    data_fingerprint: str
    model_spec_fingerprint: str
    fit_input_fingerprints: Mapping[str, str]
    build_kwargs: Mapping[str, Any]
    project_run_id: Optional[str] = None
    project_display_name: Optional[str] = None


class FitJobStore:
    """Filesystem-backed JSON store for a project-scoped fit queue."""

    def __init__(self, root: Path | str | None = None, project_id: str = "default"):
        configured_root = os.environ.get("ANCESTRY_MMM_FIT_JOB_ROOT")
        self.root = Path(
            root or configured_root or Path(__file__).resolve().parents[1] / ".fit_jobs"
        )
        self.project_id = canonical_project_id(project_id)
        self.project_root = self.root / self.project_id
        self.project_root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def for_job_dir(cls, job_dir: Path | str) -> "FitJobStore":
        directory = Path(job_dir).resolve()
        return cls(directory.parents[1], directory.parent.name)

    def job_dir(self, job_id: str) -> Path:
        safe_id = _SAFE_NAME.sub("_", job_id)
        if safe_id != job_id or not safe_id:
            raise ValueError("Invalid fit job id.")
        return self.project_root / job_id

    def _record_path(self, job_id: str) -> Path:
        return self.job_dir(job_id) / "job.json"

    @contextmanager
    def _record_lock(self, job_id: str) -> Iterator[None]:
        """Lock one job record across the parent and worker processes.

        JSON replacement is atomic, but a read/modify/write sequence is not.
        The worker and the launcher therefore use a small per-job advisory
        lock whenever they update the persisted record.  The lock file is
        deliberately separate from ``job.json`` so replacing the JSON cannot
        invalidate the lock held by another process.
        """

        lock_path = self.job_dir(job_id) / ".record.lock"
        with lock_path.open("a+b") as handle:
            if lock_path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                getattr(msvcrt, "locking")(
                    handle.fileno(), getattr(msvcrt, "LK_LOCK"), 1
                )
            else:
                import fcntl

                getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_EX"))
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    getattr(msvcrt, "locking")(
                        handle.fileno(), getattr(msvcrt, "LK_UNLCK"), 1
                    )
                else:
                    import fcntl

                    getattr(fcntl, "flock")(handle.fileno(), getattr(fcntl, "LOCK_UN"))

    def _save_unlocked(self, record: FitJobRecord) -> FitJobRecord:
        _atomic_json(self._record_path(record.job_id), record.to_dict())
        return record

    def get(self, job_id: str) -> FitJobRecord:
        path = self._record_path(job_id)
        if not path.exists():
            raise FileNotFoundError(f"Fit job does not exist: {job_id}")
        return FitJobRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list(self, *, statuses: Optional[Iterable[str]] = None) -> list[FitJobRecord]:
        wanted = set(statuses or JOB_STATES)
        records: list[FitJobRecord] = []
        for path in self.project_root.glob("*/job.json"):
            try:
                record = FitJobRecord.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if record.status in wanted:
                records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)

    def create(self, submission: FitJobSubmission) -> FitJobRecord:
        if canonical_project_id(submission.project_id) != self.project_id:
            raise ValueError("FitJobStore project_id does not match submission.")
        job_id = str(uuid.uuid4())
        directory = self.job_dir(job_id)
        directory.mkdir(parents=True, exist_ok=False)
        payload_path = directory / "input_payload.pkl"
        temporary_payload = directory / f".{payload_path.name}.{uuid.uuid4().hex}.tmp"
        with temporary_payload.open("wb") as handle:
            pickle.dump(
                dict(submission.build_kwargs), handle, protocol=pickle.HIGHEST_PROTOCOL
            )
        os.replace(temporary_payload, payload_path)
        record = FitJobRecord(
            job_id=job_id,
            project_id=self.project_id,
            status="queued",
            created_at=utc_now(),
            engine=submission.engine,
            model_type=submission.model_type,
            sampler_settings=dict(submission.sampler_settings),
            random_seed=submission.random_seed,
            data_fingerprint=submission.data_fingerprint,
            model_spec_fingerprint=submission.model_spec_fingerprint,
            fit_input_fingerprints=dict(submission.fit_input_fingerprints),
            project_run_id=submission.project_run_id,
            job_spec_location=str(payload_path),
            result_artifact_location=str(directory / "result.nc"),
            log_location=str(directory / "worker.log"),
            progress=FitJobProgress(
                total_steps=(
                    int(submission.sampler_settings.get("draws", 0))
                    + int(submission.sampler_settings.get("tune", 0))
                )
                * int(submission.sampler_settings.get("chains", 1)),
            ),
            project_display_name=submission.project_display_name
            or submission.project_id,
        )
        _atomic_json(directory / "job.json", record.to_dict())
        _atomic_json(
            directory / "job_spec.json",
            {
                "schema_version": FIT_JOB_SCHEMA_VERSION,
                "job_id": job_id,
                "payload_location": str(payload_path),
                "sampler_settings": dict(submission.sampler_settings),
            },
        )
        return record

    def save(self, record: FitJobRecord) -> FitJobRecord:
        with self._record_lock(record.job_id):
            return self._save_unlocked(record)

    def transition(
        self, job_id: str, status: str, *, message: str = ""
    ) -> FitJobRecord:
        if status not in JOB_STATES:
            raise ValueError(f"Unknown fit-job state: {status}")
        with self._record_lock(job_id):
            record = self.get(job_id)
            if (
                status != record.status
                and status not in _ALLOWED_TRANSITIONS[record.status]
            ):
                raise ValueError(
                    f"Invalid fit-job transition {record.status} -> {status}."
                )
            now = utc_now()
            record.status = status
            if status == "running" and record.started_at is None:
                record.started_at = now
                record.progress.started_at = now
            if status in TERMINAL_JOB_STATES:
                record.finished_at = now
            if status == "cancel_requested":
                record.cancellation_requested_at = (
                    record.cancellation_requested_at or now
                )
            if status == "cancelled":
                record.cancelled_at = now
            if message:
                record.progress.message = message
                if status in {"failed", "orphaned"}:
                    record.error_summary = message
            record.progress.last_updated_at = now
            return self._save_unlocked(record)

    def update_progress(self, job_id: str, **updates: Any) -> FitJobRecord:
        with self._record_lock(job_id):
            record = self.get(job_id)
            for key, value in updates.items():
                if key not in FitJobProgress.__dataclass_fields__:
                    raise ValueError(f"Unknown fit progress field: {key}")
                setattr(record.progress, key, value)
            record.progress.last_updated_at = utc_now()
            return self._save_unlocked(record)

    def update_process_metadata(
        self,
        job_id: str,
        *,
        pid: int,
        process_start_time: Optional[str] = None,
    ) -> FitJobRecord:
        """Record launcher metadata without overwriting worker state.

        The record is reloaded while holding the same lock used by worker
        transitions and progress updates.  This makes the post-launch PID
        write a targeted update of the latest record rather than a save of the
        queued object returned by ``create``.
        """

        with self._record_lock(job_id):
            record = self.get(job_id)
            record.pid = int(pid)
            record.process_start_time = process_start_time or utc_now()
            return self._save_unlocked(record)

    def append_log(self, job_id: str, message: str) -> None:
        record = self.get(job_id)
        path = Path(record.log_location)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{utc_now()}] {message.rstrip()}\n")

    def request_cancel(
        self, job_id: str, reason: str = "Cancellation requested by analyst."
    ) -> FitJobRecord:
        with self._record_lock(job_id):
            record = self.get(job_id)
            if record.status not in {"queued", "running", "cancel_requested"}:
                return record
            marker = self.job_dir(job_id) / "cancel.request"
            marker.write_text(reason, encoding="utf-8")
            now = utc_now()
            record.cancellation_reason = reason
            if record.status != "cancel_requested":
                record.status = "cancel_requested"
                record.cancellation_requested_at = (
                    record.cancellation_requested_at or now
                )
            record.progress.message = reason
            record.progress.last_updated_at = now
            return self._save_unlocked(record)

    def cancellation_requested(self, job_id: str) -> bool:
        return (self.job_dir(job_id) / "cancel.request").exists()

    def load_build_kwargs(self, job_id: str) -> dict[str, Any]:
        record = self.get(job_id)
        with Path(record.job_spec_location).open("rb") as handle:
            return cast(dict[str, Any], pickle.load(handle))

    def mark_adopted(self, job_id: str, model_run_id: str) -> FitJobRecord:
        with self._record_lock(job_id):
            record = self.get(job_id)
            if record.status != "succeeded":
                raise ValueError("Only a succeeded fit job can be adopted.")
            record.adopted_at = utc_now()
            record.adopted_model_run_id = model_run_id
            return self._save_unlocked(record)

    def reconcile(self) -> List[FitJobRecord]:
        changed: List[FitJobRecord] = []
        for record in self.list(statuses=ACTIVE_JOB_STATES):
            alive = record.pid is not None and process_is_alive(record.pid)
            if alive:
                continue
            if record.status == "cancel_requested" or self.cancellation_requested(
                record.job_id
            ):
                changed.append(
                    self.transition(
                        record.job_id,
                        "cancelled",
                        message="Worker is no longer running after cancellation.",
                    )
                )
            else:
                changed.append(
                    self.transition(
                        record.job_id,
                        "orphaned",
                        message="Fit worker is no longer running and produced no terminal result.",
                    )
                )
        return changed


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


class LocalFitJobBackend:
    """Submit and control local worker processes without retaining UI state."""

    def __init__(
        self,
        store: FitJobStore,
        *,
        popen_factory: Callable[..., Any] = subprocess.Popen,
        worker_cwd: Optional[Path | str] = None,
    ):
        self.store = store
        self.popen_factory = popen_factory
        self.worker_cwd = Path(worker_cwd or Path(__file__).resolve().parents[2])

    def submit(self, submission: FitJobSubmission) -> FitJobRecord:
        record = self.store.create(submission)
        log_handle = Path(record.log_location).open("a", encoding="utf-8")
        command = [
            sys.executable,
            "-m",
            "ancestry_mmm.application.fit_job_worker",
            "--job-dir",
            str(self.store.job_dir(record.job_id)),
        ]
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        try:
            process = self.popen_factory(
                command,
                cwd=str(self.worker_cwd),
                env=environment,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            summary = f"Worker launch failed: {type(exc).__name__}: {exc}"
            self.store.append_log(record.job_id, summary)
            self.store.transition(record.job_id, "failed", message=summary)
            raise
        finally:
            log_handle.close()
        return self.store.update_process_metadata(
            record.job_id,
            pid=int(process.pid),
            process_start_time=utc_now(),
        )

    def reconcile_active_jobs(self) -> list[FitJobRecord]:
        return self.store.reconcile()

    def cancel(
        self, job_id: str, reason: str = "Cancellation requested by analyst."
    ) -> FitJobRecord:
        return self.store.request_cancel(job_id, reason)

    def load_succeeded_fit(
        self,
        job_id: str,
        *,
        expected_data_fingerprint: Optional[str] = None,
        expected_model_spec_fingerprint: Optional[str] = None,
        expected_fit_input_fingerprints: Optional[Mapping[str, str]] = None,
    ) -> tuple[Any, Any, FitJobRecord]:
        """Load a completed artifact only when its persisted identity matches.

        The caller adopts the returned model metadata and posterior atomically
        in its own project state.  Existing state is not touched when any
        identity or artifact check fails.
        """
        import arviz as az

        record = self.store.get(job_id)
        if record.status != "succeeded":
            raise ValueError("Only a succeeded fit job can be loaded.")
        checks = (
            (expected_data_fingerprint, record.data_fingerprint, "data fingerprint"),
            (
                expected_model_spec_fingerprint,
                record.model_spec_fingerprint,
                "model-spec fingerprint",
            ),
        )
        for expected, actual, label in checks:
            if expected is not None and expected != actual:
                raise ValueError(
                    f"Fit artifact {label} does not match the current project."
                )
        if (
            expected_fit_input_fingerprints is not None
            and dict(expected_fit_input_fingerprints) != record.fit_input_fingerprints
        ):
            raise ValueError(
                "Fit artifact input fingerprints do not match the current project."
            )
        result_path = Path(record.result_artifact_location)
        result_json = result_path.with_suffix(".json")
        if not result_path.exists() or not result_json.exists():
            raise ValueError(
                "Succeeded fit job is missing its validated artifact metadata."
            )
        metadata = json.loads(result_json.read_text(encoding="utf-8"))
        if metadata.get("job_id") != job_id:
            raise ValueError("Fit artifact job identity is inconsistent.")
        for key in ("data_fingerprint", "model_spec_fingerprint"):
            if metadata.get(key) != getattr(record, key):
                raise ValueError(f"Fit artifact {key} does not match the job record.")
        if (
            dict(metadata.get("fit_input_fingerprints") or {})
            != record.fit_input_fingerprints
        ):
            raise ValueError(
                "Fit artifact input fingerprints do not match the job record."
            )
        trace = az.from_netcdf(result_path)
        if not hasattr(trace, "posterior"):
            raise ValueError("Fit artifact has no posterior group.")
        from ancestry_mmm.core.hierarchical_model import FHModelMeta
        from ancestry_mmm.core.outcomes import OutcomeDefinition
        from ancestry_mmm.core.pathways import MediaOutcomePathway

        meta_payload = dict(metadata.get("meta") or {})
        if meta_payload.get("outcome_catalogue_at_fit"):
            meta_payload["outcome_catalogue_at_fit"] = [
                OutcomeDefinition.from_dict(item) if isinstance(item, Mapping) else item
                for item in meta_payload["outcome_catalogue_at_fit"]
            ]
        if meta_payload.get("pathway_catalogue_at_fit"):
            meta_payload["pathway_catalogue_at_fit"] = [
                MediaOutcomePathway.from_dict(dict(item))
                if isinstance(item, Mapping)
                else item
                for item in meta_payload["pathway_catalogue_at_fit"]
            ]
        meta = FHModelMeta(**meta_payload)
        return trace, meta, record


__all__ = [
    "ACTIVE_JOB_STATES",
    "FIT_JOB_SCHEMA_VERSION",
    "FitJobProgress",
    "FitJobRecord",
    "FitJobStore",
    "FitJobSubmission",
    "JOB_STATES",
    "LocalFitJobBackend",
    "canonical_project_id",
    "process_is_alive",
    "utc_now",
]
