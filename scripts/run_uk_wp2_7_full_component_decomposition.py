"""WP2.7 item 4 (analyst-directed, 2026-08-25): with REQ-CONTROL-001's
control-prior fix now the production default, decompose the remaining
wide prior-predictive tail across every additive log-linear-predictor
component to identify which one now dominates - the analyst explicitly
asked for this to be reported for review, not silently used to justify
tightening any other prior. Prior-predictive sampling only.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.application.model_fit_service import build_model_for_spec  # noqa: E402
from ancestry_mmm.core.diagnostics import prior_predictive_summary  # noqa: E402

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-full-component-decomposition-20260825"
)
COMPONENT_VAR_NAMES = [
    "eta_market",
    "eta_trend",
    "eta_season",
    "eta_channels",
    "eta_promo",
    "eta_controls",
    "mu",
]


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


def main() -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    output_dir = DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    prior_config = dict(runner.APPROVED_UK_MODEL_A_PRIOR_CONFIG)

    captured: dict[str, tuple[dict[str, Any], Any]] = {}

    def _capture(model_name: str, frame: dict[str, Any], spec: Any) -> None:
        captured[model_name] = (frame, spec)

    runner.run(
        pack_dir=runner.DEFAULT_PACK_DIR,
        output_dir=output_dir / "official_preparation",
        draws=2000,
        tune=1000,
        chains=4,
        target_accept=0.9,
        seed=20260825,
        fit_enabled=False,
        only_model=None,
        governed_start=runner.COMMON_WINDOW_START,
        governed_end=runner.COMMON_WINDOW_END,
        prior_config=prior_config,
        frame_callback=_capture,
    )

    for model_name, (frame, spec) in captured.items():
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
        result = prior_predictive_summary(
            proposed.model,
            frame,
            proposed.meta,
            n_samples=2000,
            random_seed=20260825,
            component_var_names=COMPONENT_VAR_NAMES,
        )
        components = (result["plausibility"].get("component_decomposition") or {}).get(
            "components", {}
        )
        summary = {
            name: {
                "q05": comp["q05"],
                "median": comp["median"],
                "q95": comp["q95"],
                "abs_q95": max(abs(comp["q05"]), abs(comp["q95"])),
            }
            for name, comp in components.items()
            if comp is not None
        }
        ranked = sorted(summary.items(), key=lambda kv: kv[1]["abs_q95"], reverse=True)
        _write_json(
            output_dir / f"wp2_7_component_decomposition_{model_name}.json",
            {"components": summary, "ranked_by_abs_q95": [name for name, _ in ranked]},
        )
        print(
            f"{model_name}: dominant component by |q95| = {ranked[0][0] if ranked else 'n/a'}"
        )
        for name, comp in ranked:
            print(
                f"  {name}: q05={comp['q05']:.3f} median={comp['median']:.3f} q95={comp['q95']:.3f}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
