"""WP2.10 items 4/5 (analyst-directed, 2026-08-25): fit a separate,
single-outcome "Overall" challenger model for Family History
(`FH Overall = FH New + FH DNA Cross-sell + FH Winback`) and/or DNA
(`DNA Overall = DNA New Customer + DNA Existing FH Customer`), summed at
each week before modelling - a diagnostic/robustness challenger, not a
replacement for the segment-level Model A candidates.

Reuses the exact governed production pipeline for everything except the
outcome dimension: `scripts/run_uk_production_fit.py`'s own `run(...,
fit_enabled=False, frame_callback=...)` builds the real segment frame/spec
first (official preparation readiness gate already enforced), which
supplies the real joined dataframe (`frame["df"]`, every raw source
column present - `data.preprocessor.prepare_fh_modeling_frame` never
drops columns, only adds derived arrays), the real per-outcome source
columns (`frame["outcomes"]`), the real `net_billthrough_metadata`
(itself already a single non-outcome-specific value in production - see
`_fit_one`'s own call), and the real activity bundle (via `runner.
_load_pack`) needed to replay `runner._add_history`'s pre-window
carry-in exactly. The one new step is summing the constituent raw source
columns into a single new column and building a new single-entry
`OutcomeDefinition`/`ModelSpec` around it - "before modelling" per the
brief, at the raw weekly level, not a post-fit aggregation.

Outcome hierarchy: with exactly one outcome there is nothing to
hierarchically pool across, mirroring `core.market_specific_model.
build_fh_market_specific_model`'s own existing "requires at least 2
markets - partial pooling across a single market is meaningless"
precedent for the market dimension. This uses the existing, already-
gated `prior_config["pooled_beta_reference"]` diagnostic switch (already
present in `core.hierarchical_model.build_fh_hierarchical_model`,
predating this work package) to deterministically zero `sigma_pool`/
`z_offset` rather than leaving them as genuinely unidentifiable free
parameters with only one outcome group - no new model algebra.

DNA-halo pathway routing (an explicit, disclosed assumption, not hidden):
- FH Overall keeps `dna_outcome_id="fh_overall_challenger"` with
  `direct_dna_outcome_ids=None` (defaults to `[dna_outcome_id]`) - the
  exact dual direct+halo treatment the segment model's FH DNA Cross-sell
  outcome alone received, since Cross-sell was the only constituent
  outcome with a real DNA-media causal pathway in the segment model.
- DNA Overall keeps `direct_dna_outcome_ids=["dna_overall_challenger"]`
  (the segment DNA model already gives every DNA outcome full direct
  treatment - `direct_dna_outcome_ids=list(frame["outcome_ids"])` in
  `_fit_one`), so the merged outcome gets the same full-direct treatment.

Sampler configuration: `chains=4, draws=2000, tune=1000, target_accept=
0.90` - the currently *approved* Model A default (0.95 remains only
"provisionally preferred" for Family History pending the remaining-
divergence attribution check, not yet the governed default) - the
closest existing governed configuration, not an invented one.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.application.prefit_identifiability_service import (  # noqa: E402
    review_prefit_identifiability,
)
from ancestry_mmm.application.prefit_screening_service import run_prefit_screen  # noqa: E402
from ancestry_mmm.core.diagnostics import prior_predictive_summary  # noqa: E402
from ancestry_mmm.core.models import compute_model_diagnostics, fit_model  # noqa: E402
from ancestry_mmm.core.outcomes import OutcomeDefinition  # noqa: E402
from ancestry_mmm.core.prefit_identifiability import SUPPORT_THRESHOLD_VERSION  # noqa: E402
from ancestry_mmm.core.prefit_run import build_prefit_run  # noqa: E402
from ancestry_mmm.core.prefit_screening import PREFIT_FOLD_POLICY_VERSION  # noqa: E402
from ancestry_mmm.data.preprocessor import prepare_fh_modeling_frame  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-10-overall-challenger-20260825"
)

CHALLENGER_CONFIG = {
    "fh": {
        "model_name": "family_history",
        "challenger_name": "fh_overall_challenger",
        "product": "Family History",
        "outcome_id": "fh_overall_challenger",
        "segment": "Overall",
    },
    "dna": {
        "model_name": "dna_kit",
        "challenger_name": "dna_overall_challenger",
        "product": "DNA",
        "outcome_id": "dna_overall_challenger",
        "segment": "Overall",
    },
}


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


def _build_overall_frame(
    runner,
    pack,
    key: str,
    segment_frame: dict[str, Any],
    segment_spec,
    governed_start: str,
) -> tuple[dict[str, Any], Any, OutcomeDefinition]:
    cfg = CHALLENGER_CONFIG[key]
    outcomes: list[OutcomeDefinition] = list(segment_frame["outcomes"])
    source_columns = [o.source_column for o in outcomes]

    df = segment_frame["df"].copy()
    combined_col = f"{cfg['challenger_name']}_raw"
    df[combined_col] = df[source_columns].sum(axis=1)

    metric_key = outcomes[0].metric_key
    synthetic_outcome = OutcomeDefinition(
        outcome_id=cfg["outcome_id"],
        product=cfg["product"],
        segment=cfg["segment"],
        metric=outcomes[0].metric,
        source_column=combined_col,
        metric_key=metric_key,
        role="primary",
        included_in_fit=True,
        definition_version="wp2.10-challenger-1.0",
        event_definition=(
            f"Sum of constituent segment outcomes ({', '.join(o.outcome_id for o in outcomes)}) "
            "at each week, before modelling - WP2.10 items 4/5 diagnostic/robustness challenger."
        ),
    )

    new_spec = dataclasses.replace(
        segment_spec,
        segment_outcomes={cfg["segment"]: combined_col},
    )

    frame = prepare_fh_modeling_frame(
        df,
        new_spec,
        outcomes=[synthetic_outcome],
        activity_definitions=segment_frame.get("activity_definitions"),
        net_billthrough_metadata=segment_frame.get("net_billthrough_metadata"),
    )
    frame["preparation_mode"] = "wp2_10_overall_challenger"
    runner._add_history(
        frame,
        pack.activity_bundle.model_input_media,
        new_spec,
        governed_start=governed_start,
    )
    return frame, new_spec, synthetic_outcome


def _prefit_evidence(
    key: str,
    frame: dict[str, Any],
    spec,
    synthetic_outcome: OutcomeDefinition,
    prior_config: dict[str, Any],
    governed_start: str,
    governed_end: str,
    output_dir: Path,
) -> dict[str, Any]:
    cfg = CHALLENGER_CONFIG[key]

    identifiability_report = review_prefit_identifiability(
        frame["df"],
        frame["channels"],
        product=cfg["product"],
        model_name=cfg["challenger_name"],
        date_col=spec.date_col,
        market_col=spec.market_col,
        target_start=governed_start,
        target_end=governed_end,
        transform_config=prior_config,
        candidate_spec=spec,
        prepared_frame=frame,
        causal_graph=None,
    )
    screening_report = run_prefit_screen(
        frame,
        transform_config=prior_config,
        fingerprints=identifiability_report.get("fingerprints", {}),
    )

    dna_outcome_id = cfg["outcome_id"] if key == "fh" else None
    direct_dna_outcome_ids = [cfg["outcome_id"]] if key == "dna" else None
    proposed = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=dna_outcome_id,
        prior_config=prior_config,
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=None,
        search_objects=(),
    )
    prior_predictive_payload = prior_predictive_summary(
        proposed.model,
        frame,
        proposed.meta,
        n_samples=500,
        random_seed=20261010,
    )
    identifiability_report = dict(identifiability_report)
    identifiability_report["prior_predictive"] = prior_predictive_payload.get(
        "plausibility"
    )

    run = build_prefit_run(
        product=cfg["product"],
        model_name=cfg["challenger_name"],
        identifiability_report=identifiability_report,
        screening_report=screening_report,
        fold_policy_version=PREFIT_FOLD_POLICY_VERSION,
        support_threshold_policy_version=SUPPORT_THRESHOLD_VERSION,
        analyst_rationale_retained=False,
    )
    payload = run.to_dict()
    _write_json(output_dir / f"prefit_run_{cfg['challenger_name']}.json", payload)
    return payload


def _fit_challenger(
    key: str,
    frame: dict[str, Any],
    spec,
    prior_config: dict[str, Any],
    output_dir: Path,
    seed: int,
    draws: int,
    tune: int,
    chains: int,
    target_accept: float,
) -> dict[str, Any]:
    cfg = CHALLENGER_CONFIG[key]
    dna_outcome_id = cfg["outcome_id"] if key == "fh" else None
    direct_dna_outcome_ids = [cfg["outcome_id"]] if key == "dna" else None

    started = time.perf_counter()
    model_result = build_model_for_spec(
        frame=frame,
        model_spec=spec,
        model_type="shared",
        dna_lag_weeks=4,
        dna_outcome_id=dna_outcome_id,
        prior_config=dict(prior_config),
        direct_dna_outcome_ids=direct_dna_outcome_ids,
        causal_graph=None,
        search_objects=(),
    )
    trace = fit_model(
        model_result.model,
        draws=draws,
        tune=tune,
        chains=chains,
        target_accept=target_accept,
        random_seed=seed,
        cores=1,
    )
    model_dir = output_dir / cfg["challenger_name"]
    model_dir.mkdir(parents=True, exist_ok=True)
    trace_path = model_dir / "posterior.nc"
    trace.to_netcdf(trace_path)
    diagnostics = compute_model_diagnostics(trace)
    report = {
        "status": "fit_completed",
        "model_name": cfg["challenger_name"],
        "model_type": "single_outcome_overall_challenger",
        "dna_outcome_id_used": dna_outcome_id,
        "direct_dna_outcome_ids_used": direct_dna_outcome_ids,
        "prior_config": dict(prior_config),
        "sampler_config": {
            "draws": draws,
            "tune": tune,
            "chains": chains,
            "target_accept": target_accept,
        },
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "observations": int(frame["X_media"].shape[0]),
        "channels": list(frame["channels"]),
        "outcome_ids": list(frame["outcome_ids"]),
        "history_rows": int(np.asarray(frame["X_media_history"]).shape[0]),
        "trace_path": str(trace_path),
        "convergence": diagnostics,
    }
    _write_json(
        output_dir / f"wp2_10_challenger_fit_report_{cfg['challenger_name']}.json",
        report,
    )
    return report


def main(argv: list[str] | None = None) -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=runner.DEFAULT_PACK_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--product", choices=["fh", "dna"], required=True)
    parser.add_argument("--seed", type=int, default=20261010)
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--tune", type=int, default=1000)
    parser.add_argument("--chains", type=int, default=4)
    parser.add_argument("--target-accept", type=float, default=0.9)
    parser.add_argument("--governed-start", default=runner.COMMON_WINDOW_START)
    parser.add_argument("--governed-end", default=runner.COMMON_WINDOW_END)
    parser.add_argument(
        "--prefit-only",
        action="store_true",
        help="Build the frame and run governed pre-fit evidence only; skip the full NUTS fit.",
    )
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    cfg = CHALLENGER_CONFIG[args.product]
    prior_config: dict[str, Any] = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)
    prior_config["pooled_beta_reference"] = True

    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=args.pack_dir,
        output_dir=args.output_dir / "official_preparation",
        draws=args.draws,
        tune=args.tune,
        chains=args.chains,
        target_accept=args.target_accept,
        seed=args.seed,
        fit_enabled=False,
        only_model=cfg["model_name"],
        governed_start=args.governed_start,
        governed_end=args.governed_end,
        prior_config=runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG,
        frame_callback=_capture,
    )
    segment_frame, segment_spec = captured[cfg["model_name"]]
    pack = runner._load_pack(args.pack_dir)

    overall_frame, overall_spec, synthetic_outcome = _build_overall_frame(
        runner, pack, args.product, segment_frame, segment_spec, args.governed_start
    )
    print(
        f"{cfg['challenger_name']}: built frame with outcome_ids="
        f"{overall_frame['outcome_ids']}, n_obs={overall_frame['X_media'].shape[0]}, "
        f"history_rows={np.asarray(overall_frame['X_media_history']).shape[0]}"
    )

    prefit_payload = _prefit_evidence(
        args.product,
        overall_frame,
        overall_spec,
        synthetic_outcome,
        prior_config,
        args.governed_start,
        args.governed_end,
        args.output_dir,
    )
    print(f"{cfg['challenger_name']}: prefit readiness={prefit_payload['readiness']}")

    if args.prefit_only:
        return 0

    fit_report = _fit_challenger(
        args.product,
        overall_frame,
        overall_spec,
        prior_config,
        args.output_dir,
        args.seed,
        args.draws,
        args.tune,
        args.chains,
        args.target_accept,
    )
    print(
        f"{cfg['challenger_name']}: fit_completed rhat_max="
        f"{fit_report['convergence']['rhat_max']:.4f} "
        f"ess_min={fit_report['convergence']['ess_min']:.1f} "
        f"divergences={fit_report['convergence']['divergences']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
