"""WP2.6 item 4 (analyst-directed, 2026-08-24): identify the circulation
observation responsible for the ~106x positive max/median ratio WP2.5
flagged, using the local approved UK source pack only.

Writes a D-drive-only report (week/date, value, surrounding weeks,
source/version metadata, and whether the pattern is consistent with a
unit/aggregation/duplicate/mapping issue) - never committed to Git, never
printed to a repository-tracked file. This script does not edit any
source value; if a data defect is evident, it is reported for a data
owner to remediate, not silently corrected here.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-6-circulation-check-20260824"
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


def main() -> int:
    gov = _load_module(
        "uk_prefit_governance", REPO_ROOT / "scripts" / "run_uk_prefit_governance.py"
    )
    runner = gov._load_runner(REPO_ROOT)
    output_dir = DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    pack = runner._load_pack(runner.DEFAULT_PACK_DIR)
    media_df: pd.DataFrame = pack.activity_bundle.model_input_media

    circulation_columns = [c for c in media_df.columns if "circulation" in c.lower()]
    if not circulation_columns:
        print("No column matching 'circulation' found in model_input_media.")
        return 1

    date_col = next(
        (c for c in media_df.columns if c.lower() in {"date", "period_start", "week"}),
        None,
    )
    market_col = next((c for c in media_df.columns if c.lower() == "market"), None)

    report: dict[str, Any] = {"columns_checked": circulation_columns, "series": []}
    for column in circulation_columns:
        series = media_df[column].astype(float)
        positive = series[series > 0]
        if positive.empty:
            continue
        median = float(positive.median())
        max_value = float(positive.max())
        max_idx = positive.idxmax()
        window = range(max(0, max_idx - 3), min(len(media_df), max_idx + 4))
        surrounding = []
        for i in window:
            row: dict[str, Any] = {"row_index": int(i), "value": float(series.iloc[i])}
            if date_col:
                row["date"] = str(media_df.iloc[i][date_col])
            if market_col:
                row["market"] = str(media_df.iloc[i][market_col])
            surrounding.append(row)
        report["series"].append(
            {
                "column": column,
                "positive_median": median,
                "positive_max": max_value,
                "max_to_median_ratio": max_value / median if median > 0 else None,
                "peak_row": surrounding[
                    [s["row_index"] for s in surrounding].index(int(max_idx))
                ],
                "surrounding_weeks": surrounding,
                "n_positive_weeks": int(positive.size),
                "n_distinct_positive_values": int(positive.nunique()),
                "duplicate_value_check": {
                    "value_appears_n_times": int((series == max_value).sum()),
                },
            }
        )

    report["source_evidence"] = list(pack.source_evidence)

    output_path = output_dir / "circulation_check.json"
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=_json_default),
        encoding="utf-8",
    )
    print(f"Wrote circulation raw-data check to {output_path}")
    for series in report["series"]:
        print(
            f"  {series['column']}: ratio={series['max_to_median_ratio']:.1f}, "
            f"peak_row={series['peak_row']['row_index']}, "
            f"appears_n_times={series['duplicate_value_check']['value_appears_n_times']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
