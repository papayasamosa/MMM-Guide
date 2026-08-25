"""WP2.10 item 3, first step (analyst-directed, 2026-08-25): before
considering any dynamic-baseline mechanism, check whether the largest
residual weeks (WP2.9: FH New/Winback r=0.77, DNA New/Existing r=0.96)
correspond to governed context already present in the UK source pack -
the calendar `events` sheet and every context `variable_id` in the
variable dictionary (most of which are `role="diagnostic"` - present in
the pack but not currently wired into the model as controls).

Diagnostic-only correlation check: does NOT add any variable to the
model, and does not imply any of these context series is causally safe
to control for (several are explicitly documented in the pack's own
`variable_dictionary` notes as potentially downstream of media or not yet
causally reviewed). Monthly/irregular context series are aligned to the
weekly model grid by as-of (forward-fill) join for this diagnostic check
only - not the governed frequency-alignment pipeline
(`core.frequency_alignment`), which this script does not invoke, since
no production control is being added.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.predict import extract_posterior_params, predict_mu  # noqa: E402

DEFAULT_TRACE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-full-posterior-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-temporal-context-check-20260825"
)
CONTEXT_PACK_PATH = Path(
    r"D:\Ancestry-MMM\test-artifacts\uk-readiness\approved-uk-packs-20260820-v3"
    r"\context_and_external_factors_data_native_preserved.xlsx"
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _json_default(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )


def _weekly_context_matrix(dates: pd.DatetimeIndex) -> pd.DataFrame:
    """As-of (forward-filled) weekly alignment of every context variable_id
    in the pack, for this diagnostic correlation check only."""
    context = pd.read_excel(CONTEXT_PACK_PATH, sheet_name="context_data")
    context["period_start"] = pd.to_datetime(context["period_start"])
    context = context[context["market"] == "UK"]
    out = pd.DataFrame({"date": dates})
    for variable_id, group in context.groupby("variable_id"):
        series = group.sort_values("period_start").set_index("period_start")["value"]
        merged = pd.merge_asof(
            out[["date"]].sort_values("date"),
            series.rename(variable_id)
            .reset_index()
            .rename(columns={"period_start": "date"}),
            on="date",
            direction="backward",
        )
        out[variable_id] = merged[variable_id].to_numpy()
    return out.set_index("date")


def _events_near_dates(
    dates: list[str], window_days: int = 3
) -> dict[str, list[dict[str, Any]]]:
    events = pd.read_excel(CONTEXT_PACK_PATH, sheet_name="events")
    events["start_date"] = pd.to_datetime(events["start_date"])
    events["end_date"] = pd.to_datetime(events["end_date"])
    out: dict[str, list[dict[str, Any]]] = {}
    for date_str in dates:
        d = pd.Timestamp(date_str)
        window_start, window_end = (
            d - pd.Timedelta(days=window_days),
            d + pd.Timedelta(days=7 + window_days),
        )
        nearby = events[
            (events["end_date"] >= window_start) & (events["start_date"] <= window_end)
        ]
        out[date_str] = nearby[
            ["event_id", "event_name", "start_date", "end_date"]
        ].to_dict(orient="records")
    return out


def _residual_context_correlation(
    frame: dict[str, Any], meta: Any, params: Any, context_matrix: pd.DataFrame
) -> dict[str, Any]:
    Y = np.asarray(frame["Y"], dtype=float)
    mu = predict_mu(frame, meta, params)
    outcome_ids = list(frame["outcome_ids"])
    result: dict[str, Any] = {}
    for o_idx, oid in enumerate(outcome_ids):
        residual = Y[:, o_idx] - mu[:, o_idx]
        rows = []
        for col in context_matrix.columns:
            values = context_matrix[col].to_numpy(dtype=float)
            valid = np.isfinite(values) & np.isfinite(residual)
            if valid.sum() < 10 or np.std(values[valid]) == 0:
                continue
            corr = float(np.corrcoef(residual[valid], values[valid])[0, 1])
            rows.append({"variable_id": col, "correlation": corr})
        rows.sort(key=lambda r: abs(r["correlation"]), reverse=True)
        result[oid] = rows[:10]
    return result


def _evaluate_model(
    model_name: str,
    frame: dict[str, Any],
    spec: Any,
    prior_config: dict[str, Any],
    trace_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    import arviz as az

    posterior = az.from_netcdf(trace_dir / model_name / "posterior.nc")
    proposed = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=(
            list(frame["outcome_ids"]) if model_name == "dna_kit" else None
        ),
        causal_graph=None,
        search_objects=(),
    )
    params = extract_posterior_params(posterior, proposed.meta)

    dates = pd.to_datetime(frame["dates"])
    context_matrix = _weekly_context_matrix(dates)
    correlation = _residual_context_correlation(
        frame, proposed.meta, params, context_matrix
    )

    # Cross-reference the actual largest-residual weeks already identified
    # in WP2.9's fit diagnostics (re-derived here directly rather than
    # re-reading that JSON, so this script is self-contained).
    Y = np.asarray(frame["Y"], dtype=float)
    mu = predict_mu(frame, proposed.meta, params)
    outcome_ids = list(frame["outcome_ids"])
    date_strs = [str(d)[:10] for d in dates]
    events_by_outcome: dict[str, Any] = {}
    for o_idx, oid in enumerate(outcome_ids):
        residual = Y[:, o_idx] - mu[:, o_idx]
        order = np.argsort(residual)
        top_weeks = [date_strs[i] for i in order[-5:]]
        bottom_weeks = [date_strs[i] for i in order[:5]]
        events_by_outcome[oid] = {
            "largest_positive_residual_weeks": top_weeks,
            "largest_positive_residual_nearby_events": _events_near_dates(top_weeks),
            "largest_negative_residual_weeks": bottom_weeks,
            "largest_negative_residual_nearby_events": _events_near_dates(bottom_weeks),
        }

    result = {
        "model_name": model_name,
        "context_variables_checked": list(context_matrix.columns),
        "top_context_correlations_by_outcome": correlation,
        "events_near_largest_residual_weeks": events_by_outcome,
    }
    _write_json(output_dir / f"wp2_10_temporal_context_check_{model_name}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir / "official_preparation",
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=args.seed,
        fit_enabled=False,
        only_model=args.only_model,
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config=prior_config,
        frame_callback=_capture,
    )

    for model_name, (frame, spec) in captured.items():
        result = _evaluate_model(
            model_name, frame, spec, prior_config, args.trace_dir, args.output_dir
        )
        print(
            f"{model_name}: checked {len(result['context_variables_checked'])} context variables"
        )
        for oid, rows in result["top_context_correlations_by_outcome"].items():
            top = rows[0] if rows else None
            print(f"  {oid}: top context correlation = {top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
