import time

from ancestry_mmm.core.approval import ModelApproval


def test_approved_at_defaults_to_now():
    before = time.time()
    approval = ModelApproval(approved_by="Jane Analyst")
    after = time.time()
    assert before <= approval.approved_at <= after


def test_to_dict_from_dict_roundtrip():
    approval = ModelApproval(
        approved_by="Jane Analyst",
        run_label="uk-v3",
        notes="Converged cleanly, ROI plausible.",
        known_limitations="Direct Mail curve is weakly identified (low spend variation).",
        diagnostics_accepted=["convergence", "in_sample_fit", "ppc_coverage"],
    )
    restored = ModelApproval.from_dict(approval.to_dict())
    assert restored == approval


def test_from_dict_ignores_unknown_keys():
    d = ModelApproval(approved_by="Jane Analyst").to_dict()
    d["future_field"] = "should be ignored"
    restored = ModelApproval.from_dict(d)
    assert restored.approved_by == "Jane Analyst"
