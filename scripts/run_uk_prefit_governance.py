"""Run the governed WP2 pre-fit evidence sequence against the real UK source
pack (`REQ-PREFIT-001`, `core.prefit_identifiability`/`core.prefit_screening`/
`core.prefit_run`).

This reuses `scripts/run_uk_production_fit.py`'s exact governed data pipeline
(source loading, product-specific channel/outcome resolution, official
preparation readiness gate, `prepare_fh_modeling_frame`) via its
``frame_callback`` extension point, in ``--prepare-only`` (no-sampling) mode,
so no second implementation of that pipeline exists here. For each governed
model (family_history, dna_kit) it then runs:

    static readiness (already enforced by run_uk_production_fit's gate)
    -> deterministic channel-support/prior-predictive-scale identifiability
    -> leakage-safe deterministic surrogate screening
    -> a real (lightweight, no NUTS) prior-predictive sample
    -> one consolidated PrefitRun (ready/review_recommended/blocked)

and writes a compact, aggregate-only evidence summary (no raw source rows)
to a D-drive output directory. Analyst rationale is never fabricated by this
script - a run that would otherwise be ``ready`` is left at
``review_recommended`` pending a real human analyst review, per
`REQ-PREFIT-001`.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.application.prefit_identifiability_service import (  # noqa: E402
    review_prefit_identifiability,
)
from ancestry_mmm.application.prefit_screening_service import run_prefit_screen  # noqa: E402
from ancestry_mmm.core.diagnostics import prior_predictive_summary  # noqa: E402
from ancestry_mmm.core.prefit_identifiability import SUPPORT_THRESHOLD_VERSION  # noqa: E402
from ancestry_mmm.core.prefit_run import build_prefit_run  # noqa: E402
from ancestry_mmm.core.prefit_screening import PREFIT_FOLD_POLICY_VERSION  # noqa: E402
from ancestry_mmm.core.schema import ModelSpec  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-prefit-governance-20260824"
)


def _load_runner(repo_root: Path):
    path = repo_root / "scripts" / "run_uk_production_fit.py"
    spec = importlib.util.spec_from_file_location("uk_production_fit_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load production runner from {path}")
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


def _governed_units(frame: dict[str, Any]) -> dict[str, str]:
    units: dict[str, str] = {}
    for spec_entry in frame.get("media_input_specs") or ():
        if isinstance(spec_entry, dict):
            channel = spec_entry.get("channel") or spec_entry.get("channel_id")
            unit = spec_entry.get("unit") or spec_entry.get("model_input_unit")
            if channel and unit:
                units[str(channel)] = str(unit)
    return units


def _build_prefit_evidence(
    *,
    runner,
    model_name: str,
    frame: dict[str, Any],
    spec: ModelSpec,
    prior_config: dict[str, Any],
    governed_start: str,
    governed_end: str,
    n_prior_samples: int,
    seed: int,
    component_var_names: list[str] | None = None,
) -> dict[str, Any]:
    product = "Family History" if model_name == "family_history" else "DNA"

    identifiability_report = review_prefit_identifiability(
        frame["df"],
        frame["channels"],
        product=product,
        model_name=model_name,
        date_col=spec.date_col,
        market_col=spec.market_col,
        target_start=governed_start,
        target_end=governed_end,
        units=_governed_units(frame),
        transform_config=prior_config,
    )

    screening_report = run_prefit_screen(
        frame,
        transform_config=prior_config,
        fingerprints=identifiability_report.get("fingerprints", {}),
    )

    prior_predictive_error: str | None = None
    prior_predictive_payload: dict[str, Any] | None = None
    try:
        proposed = build_model_for_spec(
            frame=frame,
            model_spec=spec,
            model_type="shared",
            dna_lag_weeks=4,
            dna_outcome_id=spec.fh_dna_cross_sell_outcome_id,
            prior_config=prior_config,
            direct_dna_outcome_ids=(
                [oid for oid in frame["outcome_ids"]]
                if model_name == "dna_kit"
                else None
            ),
            causal_graph=None,
            search_objects=(),
        )
        prior_predictive_payload = prior_predictive_summary(
            proposed.model,
            frame,
            proposed.meta,
            n_samples=n_prior_samples,
            random_seed=seed,
            component_var_names=component_var_names,
        )
    except Exception as exc:  # noqa: BLE001 - recorded as review evidence, not raised
        prior_predictive_error = f"{type(exc).__name__}: {exc}"

    prior_predictive_plausibility = None
    if prior_predictive_payload is not None:
        prior_predictive_plausibility = prior_predictive_payload.get("plausibility")
    if prior_predictive_plausibility is None:
        prior_predictive_plausibility = {
            "status": "failed" if prior_predictive_error else "not_run",
            "review_status": "blocked" if prior_predictive_error else "not_run",
            "error": prior_predictive_error,
            "diagnostic_only": True,
        }

    identifiability_report = dict(identifiability_report)
    identifiability_report["prior_predictive"] = prior_predictive_plausibility

    run = build_prefit_run(
        product=product,
        model_name=model_name,
        identifiability_report=identifiability_report,
        screening_report=screening_report,
        fold_policy_version=PREFIT_FOLD_POLICY_VERSION,
        support_threshold_policy_version=SUPPORT_THRESHOLD_VERSION,
        # No human analyst has reviewed this run; this script must never
        # fabricate rationale on their behalf. A run that would otherwise
        # be `ready` is therefore left at `review_recommended`.
        analyst_rationale_retained=False,
    )
    return run.to_dict()


def _markdown_summary(runs: dict[str, dict[str, Any]]) -> str:
    lines = [
        "# UK Model A governed pre-fit evidence (WP2)",
        "",
        "Diagnostic preparation evidence only. No channel was removed, no "
        "causal role was changed, no prior was tightened, and no model was "
        "fitted or approved by this run.",
        "",
    ]
    for model_name, run in runs.items():
        lines.append(f"## {model_name}")
        lines.append("")
        lines.append(f"- Readiness: **{run['readiness']}**")
        lines.append(f"- Reconstruction tier: {run['reconstruction_tier']}")
        lines.append(
            "- Components: "
            + ", ".join(
                f"{k}={v}" for k, v in run["readiness_detail"]["components"].items()
            )
        )
        if run["readiness_detail"]["reasons"]:
            lines.append("- Reasons: " + "; ".join(run["readiness_detail"]["reasons"]))
        support_rows = run["identifiability_report"]["support_identifiability"]["rows"]
        weak_channels = [
            row["channel"]
            for row in support_rows
            if row["support_status"] in {"weak", "very_weak"}
        ]
        if weak_channels:
            lines.append(
                f"- Weak/very-weak support ({len(weak_channels)}/{len(support_rows)} "
                f"channels): {', '.join(weak_channels)}"
            )
        prior_pred = run["identifiability_report"]["prior_predictive"]
        lines.append(
            f"- Prior-predictive: status={prior_pred.get('status')}, "
            f"review_status={prior_pred.get('review_status')}"
        )
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    runner = _load_runner(Path(__file__).resolve().parents[1])
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--only-model", choices=["family_history", "dna_kit"])
    parser.add_argument("--n-prior-samples", type=int, default=500)
    parser.add_argument("--seed", type=int, default=20260824)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    parser.add_argument(
        "--prior-config",
        type=Path,
        help=(
            "Optional JSON object of approved diagnostic/fit prior "
            "overrides. Defaults to "
            "runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG (REQ-CONTROL-001) - "
            "this pre-fit evidence run must reflect the same prior the "
            "production fit actually uses, not a stale {} default."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    runner = _load_runner(repo_root)
    parser = build_parser()
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prior_config: dict[str, Any] = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    if args.prior_config is not None:
        payload = json.loads(args.prior_config.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("--prior-config must contain a JSON object.")
        prior_config = payload

    captured: dict[str, tuple[dict[str, Any], ModelSpec]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: ModelSpec) -> None:
        captured[model_name] = (frame, spec)

    preparation_report = runner.run(
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
    _write_json(
        args.output_dir / "official_preparation_report.json", preparation_report
    )

    runs: dict[str, dict[str, Any]] = {}
    for model_name, (frame, spec) in captured.items():
        run_payload = _build_prefit_evidence(
            runner=runner,
            model_name=model_name,
            frame=frame,
            spec=spec,
            prior_config=prior_config,
            governed_start=args.governed_start,
            governed_end=args.governed_end,
            n_prior_samples=args.n_prior_samples,
            seed=args.seed,
        )
        runs[model_name] = run_payload
        _write_json(args.output_dir / f"prefit_run_{model_name}.json", run_payload)

    _write_json(
        args.output_dir / "prefit_governance_summary.json",
        {
            "status": "prefit_evidence_only",
            "runs": {name: run["readiness"] for name, run in runs.items()},
        },
    )
    (args.output_dir / "prefit_governance_summary.md").write_text(
        _markdown_summary(runs), encoding="utf-8"
    )
    print(f"Wrote governed pre-fit evidence to {args.output_dir}")
    for model_name, run in runs.items():
        print(f"  {model_name}: readiness={run['readiness']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
