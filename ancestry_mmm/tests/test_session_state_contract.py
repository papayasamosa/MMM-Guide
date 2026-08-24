"""Tests for the centralised session-state contract (PR 82B).

Before this fix, ``diagnostics_artefact``, ``diag_result``,
``validation_policy``, ``validation_results``, ``approval_readiness`` and
``validation_service_result`` were read/written throughout
``pages/06_Diagnostics.py`` via ``get_state()``/``set_state()`` but never
declared in ``init_session_state()``'s defaults, and the first five were
never cleared by ``clear_model_state()`` on retrain - so a retrained model
could keep displaying (and letting readiness/approval trust) diagnostics and
validation evidence computed for the previous fit.

Uses ``AppTest.from_string()`` to exercise the real
``init_session_state()``/``clear_model_state()`` functions against a real
``st.session_state``, without needing a full page.
"""

from streamlit.testing.v1 import AppTest

_MODEL_DERIVED_DIAGNOSTIC_VALIDATION_KEYS = [
    "diagnostics_artefact",
    "diag_result",
    "validation_results",
    "approval_readiness",
    "validation_service_result",
    "prefit_identifiability",
    "prefit_screening",
]

_INIT_SCRIPT = """
from ancestry_mmm.utils.session_state import init_session_state
init_session_state()
"""

_CLEAR_SCRIPT = """
from ancestry_mmm.utils.session_state import clear_model_state
clear_model_state()
"""


class TestInitSessionStateIncludesEvidenceKeys:
    def test_all_new_keys_are_centrally_initialised(self):
        at = AppTest.from_string(_INIT_SCRIPT)
        at.run()
        assert not at.exception, f"init raised: {at.exception}"
        for key in [*_MODEL_DERIVED_DIAGNOSTIC_VALIDATION_KEYS, "validation_policy"]:
            assert key in at.session_state, f"{key!r} not initialised"
            assert at.session_state[key] is None

    def test_does_not_overwrite_an_already_set_key(self):
        """init_session_state() must only fill in missing keys, never reset
        a key a page has already populated this session (matches its
        existing behaviour for every other default)."""
        at = AppTest.from_string(_INIT_SCRIPT)
        at.session_state["approval_readiness"] = {"overall_ready": True}
        at.run()
        assert not at.exception, f"init raised: {at.exception}"
        assert at.session_state["approval_readiness"] == {"overall_ready": True}


class TestClearModelStateClearsDiagnosticAndValidationEvidence:
    def test_clears_all_model_derived_diagnostic_and_validation_keys(self):
        at = AppTest.from_string(_CLEAR_SCRIPT)
        for key in _MODEL_DERIVED_DIAGNOSTIC_VALIDATION_KEYS:
            at.session_state[key] = "stale-value-from-previous-fit"
        at.run()
        assert not at.exception, f"clear raised: {at.exception}"
        for key in _MODEL_DERIVED_DIAGNOSTIC_VALIDATION_KEYS:
            assert at.session_state[key] is None, f"{key!r} was not cleared"

    def test_does_not_clear_validation_policy(self):
        """validation_policy is project-level configuration, not derived
        from any particular model fit - retraining must not silently wipe
        out the configured policy."""
        at = AppTest.from_string(_CLEAR_SCRIPT)
        at.session_state["validation_policy"] = {"policy_id": "keep-me"}
        at.run()
        assert not at.exception, f"clear raised: {at.exception}"
        assert at.session_state["validation_policy"] == {"policy_id": "keep-me"}

    def test_still_clears_model_approval_and_run_id(self):
        """Regression guard: the pre-existing clear behaviour (model
        approval and run id reset on retrain) must survive alongside the
        new diagnostic/validation keys."""
        at = AppTest.from_string(_CLEAR_SCRIPT)
        at.session_state["model_approval"] = {"approved_by": "Someone"}
        at.session_state["model_run_id"] = "run-old"
        at.run()
        assert not at.exception, f"clear raised: {at.exception}"
        assert at.session_state["model_approval"] is None
        assert at.session_state["model_run_id"] is None
