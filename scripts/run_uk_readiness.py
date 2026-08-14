"""Run the local-only synthetic or user-supplied UK readiness harness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ancestry_mmm.application.uk_readiness import (  # noqa: E402
    DEFAULT_READINESS_OUTPUT_DIR,
    ReadinessInputError,
    run_uk_readiness,
)


def _source(value: str) -> tuple[str, Path]:
    try:
        domain, path = value.split("=", 1)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "source must be DOMAIN=PATH, for example outcomes=D:/data/outcomes.xlsx"
        ) from exc
    if not domain or not path:
        raise argparse.ArgumentTypeError("source must include a domain and path")
    return domain, Path(path)


def _synthetic_lifecycle_builder(bundle_path: Path) -> Path:
    from ancestry_mmm.tests.support.lifecycle_fixture import (
        build_lifecycle_project_bundle,
    )

    return build_lifecycle_project_bundle(bundle_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a local-only UK readiness check. The report contains metadata, "
            "counts, fingerprints, timings, and governance decisions; it does "
            "not print source rows."
        )
    )
    parser.add_argument(
        "--source",
        action="append",
        type=_source,
        default=[],
        help="Standard workbook as DOMAIN=PATH; may be repeated for physical packs.",
    )
    parser.add_argument(
        "--bundle", type=Path, help="Previously exported project bundle."
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Use repository-generated source workbooks and deterministic lifecycle evidence.",
    )
    parser.add_argument(
        "--synthetic-case",
        choices=("pass", "mixed_frequency", "coverage_gap"),
        default="pass",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_READINESS_OUTPUT_DIR,
        help="D-drive output directory; defaults to D:/Ancestry-MMM/test-artifacts/uk-readiness.",
    )
    parser.add_argument("--governed-start")
    parser.add_argument("--governed-end")
    parser.add_argument("--governed-frequency", default="weekly")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = run_uk_readiness(
            source_paths=args.source,
            bundle_path=args.bundle,
            synthetic_case=args.synthetic_case if args.synthetic else None,
            output_dir=args.output_dir,
            governed_start=args.governed_start,
            governed_end=args.governed_end,
            governed_frequency=args.governed_frequency,
            lifecycle_bundle_builder=(
                _synthetic_lifecycle_builder if args.synthetic else None
            ),
        )
    except (ReadinessInputError, OSError, ValueError) as exc:
        print(f"UK readiness failed before a report could be written: {exc}")
        return 1
    print(f"UK readiness status: {report.status}")
    for stage in report.stages:
        print(f"- {stage.name}: {stage.status} ({stage.elapsed_seconds:.3f}s)")
    print(f"Report: {report.report_path}")
    return 0 if report.status == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
