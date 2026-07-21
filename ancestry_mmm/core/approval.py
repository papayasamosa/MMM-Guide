"""
Explicit model-approval gate, bound to the exact fitted model it was
granted for.

The guide this build follows is explicit: "A high R-squared must not
automatically mean the model is accepted... Only an approved model should
populate the official curve bank and planning defaults." An approval that
merely *exists* is not enough on its own: if the model is retrained, the
data changes, the specification (structure or priors) changes, or the
posterior is recalculated, an approval granted for the *previous* model run
must stop being valid for the new one, even though a `ModelApproval` object
is still sitting in session state.

ModelApproval therefore records not just who approved a model and what they
reviewed, but the exact model run's identity: `model_run_id` (a fresh UUID
minted on every fit - see pages/05_Model_Training.py) plus SHA-256
fingerprints of the modelling data, the model specification (structure +
priors), and the fitted posterior (see core.fingerprint). Two model runs
with byte-identical inputs can still be distinguished by `model_run_id`;
everything else is content-addressed.

The gate has teeth at the core API level, not just in the Streamlit
interface: core.curve_bank.make_entries and core.optimization.evaluate_scenario
/optimize_scenario call require_matching_approval() themselves, so calling
them directly - bypassing whatever a Streamlit page's own checks do - still
requires a valid, matching approval.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import List, Optional


class ApprovalMismatchError(RuntimeError):
    """
    Raised when an approval is missing, legacy (predates model-binding), or
    does not match the model run it is being used to authorise.
    """


@dataclass
class ModelApproval:
    approved_by: str
    approved_at: float = field(default_factory=time.time)
    run_label: str = ""
    notes: str = ""
    known_limitations: str = ""
    # Which scorecard sections the approver reviewed before signing off,
    # e.g. ["convergence", "in_sample_fit", "ppc_coverage", "plausibility_flags"].
    diagnostics_accepted: List[str] = field(default_factory=list)

    # Model-binding identity: which exact fitted model this approval covers.
    # Empty strings (the default) mean "unbound" - either a legacy approval
    # created before this field existed, or one built without the current
    # model artefacts available. matches_current_model() treats an unbound
    # approval as never matching, regardless of what it's compared against.
    model_run_id: str = ""
    data_fingerprint: str = ""
    model_spec_fingerprint: str = ""
    posterior_fingerprint: str = ""

    def is_model_bound(self) -> bool:
        return bool(
            self.model_run_id and self.data_fingerprint
            and self.model_spec_fingerprint and self.posterior_fingerprint
        )

    def matches_current_model(
        self,
        *,
        model_run_id: str,
        data_fingerprint: str,
        model_spec_fingerprint: str,
        posterior_fingerprint: str,
    ) -> bool:
        """
        True only if every identifier is present on both sides and they all
        match exactly. False whenever any identifier is missing (on this
        approval or on the "current" side passed in) - including a legacy
        approval with no model-binding fields at all, which must never be
        treated as valid merely because a ModelApproval object exists.
        """
        if not self.is_model_bound():
            return False
        if not (model_run_id and data_fingerprint and model_spec_fingerprint and posterior_fingerprint):
            return False
        return (
            self.model_run_id == model_run_id
            and self.data_fingerprint == data_fingerprint
            and self.model_spec_fingerprint == model_spec_fingerprint
            and self.posterior_fingerprint == posterior_fingerprint
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelApproval":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


def require_matching_approval(
    approval: Optional[ModelApproval],
    *,
    model_run_id: str,
    data_fingerprint: str,
    model_spec_fingerprint: str,
    posterior_fingerprint: str,
) -> ModelApproval:
    """
    Raise ApprovalMismatchError unless `approval` is a ModelApproval that is
    model-bound and matches the given current identifiers; otherwise return
    it unchanged. Shared by core.curve_bank.make_entries and
    core.optimization.evaluate_scenario/optimize_scenario so the check can't
    be skipped by calling those functions directly instead of going through
    a Streamlit page's own (weaker, UI-only) checks.
    """
    if not isinstance(approval, ModelApproval):
        raise ApprovalMismatchError("No approval was provided for this model.")
    if not approval.is_model_bound():
        raise ApprovalMismatchError(
            "This approval predates model-bound approval (no run/fingerprint identifiers "
            "recorded) and cannot be treated as valid for the current model. Re-approve after review."
        )
    if not approval.matches_current_model(
        model_run_id=model_run_id,
        data_fingerprint=data_fingerprint,
        model_spec_fingerprint=model_spec_fingerprint,
        posterior_fingerprint=posterior_fingerprint,
    ):
        raise ApprovalMismatchError(
            "This approval does not match the current fitted model - the data, "
            "specification, posterior, or model run have changed since it was approved. "
            "Re-approve after review."
        )
    return approval
