"""WP2.9 item 1 follow-on (analyst-directed, 2026-08-25): re-retain the
analyst's existing rationale against the *corrected* pre-fit evidence
identity, now that `scripts/run_uk_prefit_governance.py`'s fingerprint
plumbing defect is fixed (PR #313).

WP2.8's rationale retention (`scripts/run_uk_wp2_8_retain_analyst_
rationale.py`) was bound to fingerprints where `candidate_spec_
fingerprint`/`prepared_frame_fingerprint` were both `sha256("null")` -
not a real identity binding, even though the analyst's stated reasoning
did not depend on that defect. The rationale text itself is unchanged
(the analyst's review of the control-prior fix, prior-predictive
evidence, and short screen did not change) - only the evidence identity
it is bound to is now real. This script re-runs the exact same governed
mechanism (`core.prefit_screening.record_prefit_analyst_review` +
`core.prefit_run.build_prefit_run`) against `scripts/run_uk_wp2_9_
retain_analyst_rationale.py`'s own freshly regenerated pre-fit evidence
(`D:\\Ancestry-MMM\\test-artifacts\\historical-model-a-wp2-9-prefit-rerun-
20260825\\prefit_run_{model}.json`, produced by the now-fixed `run_uk_
prefit_governance.py`), never a second retention mechanism.
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

from ancestry_mmm.core.prefit_identifiability import NULL_FINGERPRINT  # noqa: E402
from ancestry_mmm.core.prefit_run import (  # noqa: E402
    PrefitRun,
    build_prefit_run,
    official_submission_allowed,
)
from ancestry_mmm.core.prefit_screening import record_prefit_analyst_review  # noqa: E402

SOURCE_EVIDENCE_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-prefit-rerun-20260825"
)
DEFAULT_OUTPUT_DIR = Path(
    r"D:\Ancestry-MMM\test-artifacts\historical-model-a-wp2-9-analyst-rationale-20260825"
)

# Unchanged from WP2.8 - the analyst's stated reasoning did not depend on
# the fingerprint defect and has not been revisited; only the identity
# binding this rationale is retained against has changed.
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
        name for name, value in fingerprints.items() if value == NULL_FINGERPRINT
    ]

    allowed, reason = official_submission_allowed(updated_run)

    result = {
        "model_name": model_name,
        "source_evidence_path": str(source_path),
        "fingerprints": fingerprints,
        "fingerprint_caveat": (
            f"{', '.join(null_hash_fields)} legitimately resolve to the "
            "null/placeholder fingerprint (no explicit causal graph "
            "override for this candidate - see core.prefit_identifiability"
            ".NULL_FINGERPRINT's docstring), not a plumbing defect - "
            "candidate_spec_fingerprint and prepared_frame_fingerprint are "
            "now real and content-derived (PR #313)."
            if null_hash_fields
            else "no null-hash fingerprints found"
        ),
        "readiness_before": payload.get("readiness"),
        "readiness_after": updated_run.readiness,
        "analyst_review": dict(updated_run.analyst_review),
        "official_submission_allowed": {"allowed": allowed, "reason": reason},
        "run_id": updated_run.run_id,
        "supersedes": (
            "D:\\Ancestry-MMM\\test-artifacts\\historical-model-a-wp2-8-"
            f"analyst-rationale-20260825\\prefit_run_with_analyst_review_{model_name}.json"
            " (bound to a null-hash candidate_spec_fingerprint/prepared_frame_fingerprint)"
        ),
    }
    _write_json(
        output_dir / f"prefit_run_with_analyst_review_{model_name}.json",
        updated_run.to_dict(),
    )
    _write_json(output_dir / f"wp2_9_rationale_retention_{model_name}.json", result)
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
