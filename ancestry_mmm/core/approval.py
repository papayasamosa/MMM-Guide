"""
Explicit model-approval gate.

The guide this build follows is explicit: "A high R-squared must not
automatically mean the model is accepted... Only an approved model should
populate the official curve bank and planning defaults." Before this
module existed, any trained model - converged or not - could be saved to
the curve bank and used for scenario planning with no approval step at
all.

ModelApproval is a small, explicit record of that decision (who approved
it, when, and what they reviewed). The gate itself lives where it has
teeth: core.curve_bank.make_entry requires an ModelApproval instance as a
non-optional argument, so it is not structurally possible to write a curve
bank entry without one. Pages additionally gate scenario planning on the
same object being present in session state (see pages/08_Scenario_Planner.py).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import List


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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelApproval":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
