"""WP2.8 item 2 (analyst-directed, 2026-08-25): retain the analyst's
review rationale for the current UK historical Model A candidate against
the exact fingerprints already bound to WP2.7's governed pre-fit
evidence, using the existing, purpose-built governed mechanism
(`core.prefit_screening.record_prefit_analyst_review` +
`core.prefit_run.build_prefit_run`) - no new retention mechanism is
invented here.

This reads WP2.7's already-produced governed pre-fit evidence
(`D:\\Ancestry-MMM\\test-artifacts\\historical-model-a-wp2-7-prefit-rerun-
20260825\\prefit_run_{model}.json`) and does not recompute or mutate any
evidence component - it only attaches the retained rationale text to the
existing screening report and rebuilds the consolidated `PrefitRun`
record so `readiness`/`analyst_review` reflect the real review. Per
REQ-PREFIT-001 and `core.prefit_run.consolidate_prefit_readiness`, this
does not (and must not) promote readiness to `ready` on its own - the
run stays `review_recommended` because the underlying evidence
components were themselves classified `review_recommended`, exactly as
intended.

A caveat this script surfaces rather than hides: `candidate_spec_
fingerprint`, `prepared_frame_fingerprint`, and `causal_graph_
fingerprint` in this evidence chain are all `sha256("null")` -
`scripts/run_uk_prefit_governance.py` (used for every governed pre-fit
run since WP2) never passes `candidate_spec`/`prepared_frame`/
`causal_graph` through to `core.prefit_identifiability.
build_prefit_fingerprints`, so those three fingerprints are computed
from `None`, not real content. Only `transform_config_fingerprint` is
content-derived in this chain. This is a pre-existing gap, not
introduced or fixed by this script - flagged here so retaining
rationale "against the exact fingerprints" is not read as more specific
than it actually is.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(REPO_ROOT))

from ancestry_mmm.core.prefit_run import (  # noqa: E402
    PrefitRun,
    build_prefit_run,
    official_submission_allowed,
)
from ancestry_mmm.core.prefit_screening import record_prefit_analyst_review  # noqa: E402

SOURCE_EVIDENCE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-7-prefit-rerun-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-8-analyst-rationale-20260825"
)
NULL_HASH = "74234e98afe7498fb5daf1f36ac2d78acc339464f950703b8c019892f982b90b"

ANALYST_RATIONALE = (
    "The analyst reviewed the deterministic pre-fit, prior-predictive and "
    "short Bayesian screen evidence for the current UK historical Model A "
    "candidate. The previously material control-prior pathology has been "
    "resolved under REQ-CONTROL-001 using governed standardisation and "
    "Normal(0, 0.20). Prior-predictive draws are finite with no clipping "
    "attributable to the control. The remaining broad prior-predictive "
    "behaviour, including seasonality, is retained for posterior "
    "evaluation rather than pre-emptively tightened. The short NUTS "
    "screen showed zero divergences, no maximum-tree-depth hits and "
    "acceptable BFMI for both Family History and DNA, representing a "
    "material improvement over the previous failed geometry. Hill/"
    "adstock parameters remain identification-sensitive and will be "
    "evaluated using the full posterior and post-fit validation rather "
    "than changed from short-screen evidence alone. The candidate is "
    "therefore approved to proceed to the governed full posterior for "
    "this historical non-production exercise."
)


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


def _retain_for_model(model_name: str, output_dir: Path) -> dict[str, Any]:
    source_path = SOURCE_EVIDENCE_DIR / f"prefit_run_{model_name}.json"
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    run = PrefitRun.from_dict(payload)

    updated_screening_report = record_prefit_analyst_review(
        run.screening_report, rationale=ANALYST_RATIONALE
    )

    updated_run = build_prefit_run(
        product="Family History" if model_name == "family_history" else "DNA",
        model_name=model_name,
        identifiability_report=run.identifiability_report,
        screening_report=updated_screening_report,
        reconstruction_tier=run.reconstruction_tier,
        fold_policy_version=run.fold_policy_version,
        support_threshold_policy_version=run.support_threshold_policy_version,
        prior_predictive_threshold_policy_version=(
            run.prior_predictive_threshold_policy_version
        ),
        generated_at=run.generated_at,
    )

    fingerprints = updated_run.fingerprints()
    null_hash_fields = [
        name for name, value in fingerprints.items() if value == NULL_HASH
    ]

    allowed, reason = official_submission_allowed(updated_run)

    result = {
        "model_name": model_name,
        "source_evidence_path": str(source_path),
        "fingerprints": fingerprints,
        "fingerprint_caveat": (
            f"{', '.join(null_hash_fields)} are sha256('null') - a "
            "pre-existing gap in scripts/run_uk_prefit_governance.py's "
            "call chain (candidate_spec/prepared_frame/causal_graph were "
            "never passed through), not introduced or fixed by this "
            "script. transform_config_fingerprint is the one "
            "content-derived fingerprint in this chain."
            if null_hash_fields
            else "no null-hash fingerprints found"
        ),
        "readiness_before": payload.get("readiness"),
        "readiness_after": updated_run.readiness,
        "analyst_review": dict(updated_run.analyst_review),
        "official_submission_allowed": {"allowed": allowed, "reason": reason},
        "run_id": updated_run.run_id,
    }
    _write_json(
        output_dir / f"prefit_run_with_analyst_review_{model_name}.json",
        updated_run.to_dict(),
    )
    _write_json(output_dir / f"wp2_8_rationale_retention_{model_name}.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    for model_name in ("family_history", "dna_kit"):
        result = _retain_for_model(model_name, args.output_dir)
        print(
            f"{model_name}: readiness={result['readiness_after']} "
            f"official_submission_allowed={result['official_submission_allowed']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
