"""Separate-process worker for durable local model fits."""

from __future__ import annotations

import argparse
import json
import os
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Any

import arviz as az

from ancestry_mmm.application.fit_job_service import FitJobStore, utc_now
from ancestry_mmm.application.model_fit_service import build_model_for_spec
from ancestry_mmm.core.models import fit_model


class _CancellationRequested(RuntimeError):
    pass


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, default=_json_default), encoding="utf-8"
    )
    os.replace(temporary, path)


def run_job(job_dir: Path | str) -> int:
    store = FitJobStore.for_job_dir(job_dir)
    job_id = Path(job_dir).name
    record = store.get(job_id)
    if record.status == "cancel_requested" or store.cancellation_requested(job_id):
        store.transition(
            job_id,
            "cancelled",
            message="Cancellation was requested before sampling started.",
        )
        return 0
    # Targeted locked read-modify-write, not a blind save of the `record`
    # object read above: the launcher's own update_process_metadata() call
    # (recording pid/process_start_time/process_identity_token) can land in
    # the gap between that read and a save here. A save of this now-stale
    # in-memory snapshot would silently clobber process_identity_token back
    # to None, defeating the PID-reuse check reconciliation relies on. Both
    # the worker and the launcher target the *same* pid, so whichever of
    # the two calls this races against writes second, the persisted
    # identity token is identical either way - the fix is safety against
    # clobbering unrelated concurrently-written fields, not a fresh value.
    store.update_process_metadata(job_id, pid=os.getpid(), process_start_time=utc_now())
    store.transition(job_id, "running", message="Worker started.")
    try:
        build_kwargs = store.load_build_kwargs(job_id)
        if store.cancellation_requested(job_id):
            raise _CancellationRequested
        built = build_model_for_spec(**build_kwargs)
        settings = dict(record.sampler_settings)

        def stats_callback(stats: dict[str, Any]) -> None:
            if store.cancellation_requested(job_id):
                raise _CancellationRequested
            current = store.get(job_id)
            store.update_progress(
                job_id,
                phase="tuning" if stats.get("tuning") else "sampling",
                completed_steps=int(stats.get("completed", 0)),
                total_steps=int(stats.get("total", current.progress.total_steps)),
                chain=stats.get("chain"),
                draw_idx=stats.get("draw_idx"),
                tuning=bool(stats.get("tuning", False)),
                divergences=current.progress.divergences
                + int(bool(stats.get("diverging"))),
                max_treedepth_hits=current.progress.max_treedepth_hits
                + int(bool(stats.get("reached_max_treedepth"))),
                tree_depth=stats.get("tree_depth"),
                tree_size=stats.get("tree_size"),
                step_size=stats.get("step_size"),
            )

        trace = fit_model(
            built.model,
            draws=int(settings.get("draws", 1000)),
            tune=int(settings.get("tune", 1000)),
            chains=int(settings.get("chains", 2)),
            target_accept=float(settings.get("target_accept", 0.9)),
            random_seed=int(
                record.random_seed if record.random_seed is not None else 42
            ),
            progress_callback=None,
            stats_callback=stats_callback,
            cores=1,
        )
        if store.cancellation_requested(job_id):
            raise _CancellationRequested
        result_path = Path(record.result_artifact_location)
        temporary_result = result_path.with_name(f".{result_path.name}.tmp")
        trace.to_netcdf(str(temporary_result))
        # Validate the artifact before promoting the job to succeeded.
        validated = az.from_netcdf(temporary_result)
        if not hasattr(validated, "posterior"):
            raise RuntimeError("Fit artifact has no posterior group.")
        os.replace(temporary_result, result_path)
        _write_json_atomic(
            result_path.with_suffix(".json"),
            {
                "schema_version": 1,
                "job_id": job_id,
                "engine": record.engine,
                "model_type": record.model_type,
                "data_fingerprint": record.data_fingerprint,
                "model_spec_fingerprint": record.model_spec_fingerprint,
                "fit_input_fingerprints": record.fit_input_fingerprints,
                "project_run_id": record.project_run_id,
                "meta": asdict(built.meta),
                "candidate_a_readiness": (
                    asdict(built.candidate_a_readiness)
                    if built.candidate_a_readiness is not None
                    else None
                ),
            },
        )
        store.transition(
            job_id, "succeeded", message="Fit completed and artifact validated."
        )
        return 0
    except _CancellationRequested:
        store.transition(job_id, "cancelled", message="Sampling cancelled by analyst.")
        return 0
    except Exception as exc:  # worker failures are durable and visible to the UI
        summary = f"{type(exc).__name__}: {exc}"
        store.append_log(job_id, traceback.format_exc())
        store.transition(job_id, "failed", message=summary)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-dir", required=True)
    args = parser.parse_args()
    return run_job(Path(args.job_dir))


if __name__ == "__main__":
    raise SystemExit(main())
