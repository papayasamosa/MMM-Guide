"""Write the local, untracked UK Search-spend coverage resolution package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from ancestry_mmm.core.search_preparation import (
    product_search_bindings,
    resolve_product_search_spend_coverage,
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--approved-pack-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-start", default="2023-01-01")
    parser.add_argument("--target-end", default="2025-06-29")
    return parser.parse_args()


def main() -> int:
    args = _args()
    target_dates = pd.date_range(args.target_start, args.target_end, freq="7D")
    raw_path = args.source_dir / "activity_data.xlsx"
    approved_path = (
        args.approved_pack_dir
        / "activity_data_approved_metadata_and_structural_zeros.xlsx"
    )
    raw = pd.read_excel(raw_path, sheet_name="activity_data")
    approved = pd.read_excel(approved_path, sheet_name="activity_data")
    products: list[dict] = []
    for binding in product_search_bindings():
        prepared, approved_resolution = resolve_product_search_spend_coverage(
            approved,
            target_dates,
            binding,
            structural_zero_dates=(),
        )
        _, raw_resolution = resolve_product_search_spend_coverage(
            raw,
            target_dates,
            binding,
            structural_zero_dates=(),
        )
        products.append(
            {
                "product": binding.product,
                "product_label": binding.product_label,
                "source_activity_id": binding.source_activity_id,
                "spend_object_id": binding.spend_object_id,
                "delivery_object_id": binding.delivery_object_id,
                "source_mapping": {
                    "spend_column": binding.spend_source_column,
                    "delivery_column": binding.delivery_source_column,
                    "currency": binding.currency,
                    "source": binding.source,
                },
                "raw_source_resolution": raw_resolution.to_dict(),
                "approved_pack_resolution": approved_resolution.to_dict(),
                "clicks_zero_does_not_resolve_spend": True,
                "official_fit_eligible": False,
            }
        )
    report = {
        "schema_version": 1,
        "status": "unresolved",
        "target_window": {
            "start": args.target_start,
            "end": args.target_end,
            "frequency": "weekly Sunday-Saturday periods",
        },
        "source_files": {
            "raw_activity": str(raw_path),
            "approved_activity_pack": str(approved_path),
        },
        "zero_fill_policy": (
            "Only explicit structural-zero evidence may resolve missing Search spend. "
            "Zero clicks, absent rows, and the end of a source series are not evidence."
        ),
        "products": products,
        "blocking_reason": (
            "Both FH and DNA approved-pack Search spend series remain unresolved "
            "after 2025-04-06; the approved pack supplies zero-click rows but no "
            "source-supported zero-spend evidence for those weeks."
        ),
        "fit_action": "stop affected Search-mediated fit; do not fabricate or shorten the target window",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "search-spend-coverage-resolution.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# UK Search-spend coverage resolution",
        "",
        "Status: **unresolved — Search-mediated fit blocked**.",
        "",
        f"Target window: `{args.target_start}` through `{args.target_end}` (canonical weekly periods).",
        "",
        "The approved pack contains zero-click rows after the supplied Search spend ends, but it does not establish that spend was zero. Those weeks remain missing; no interpolation or zero-fill was performed.",
        "",
        "| Product | Raw unresolved weeks | Approved-pack unresolved weeks | First unresolved approved-pack week |",
        "|---|---:|---:|---|",
    ]
    for item in products:
        raw_resolution = item["raw_source_resolution"]
        approved_resolution = item["approved_pack_resolution"]
        first = (approved_resolution["unresolved_dates"] or ["none"])[0]
        lines.append(
            f"| {item['product_label']} | {len(raw_resolution['unresolved_dates'])} | {len(approved_resolution['unresolved_dates'])} | {first} |"
        )
    lines.extend(
        [
            "",
            "Required next action: obtain governed FH and DNA account inactivity/zero-spend evidence or retain the Search mediator as diagnostic-only. The canonical target window must not be shortened to hide the gap.",
        ]
    )
    (args.output_dir / "search-spend-coverage-resolution.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
