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


_CURVE_DIR_SCRIPT = """
from ancestry_mmm.utils.config import CURVE_ARTIFACT_ROOT, CURVE_BANK_ROOT
from ancestry_mmm.utils.session_state import curve_artifact_store_dir, curve_bank_dir
import streamlit as st

st.session_state["_artifact_dir"] = str(curve_artifact_store_dir())
st.session_state["_bank_dir"] = str(curve_bank_dir())
st.session_state["_artifact_root"] = str(CURVE_ARTIFACT_ROOT)
st.session_state["_bank_root"] = str(CURVE_BANK_ROOT)
"""


class TestCurveStorageDirsRejectPathTraversalInProjectName:
    """Regression for review 5121* (PRRT_kwDOTd28Js6fkIJk): an imported
    bundle's untrusted display name is installed as `project_name` and must
    never be usable as a raw filesystem path component when deriving the
    curve bank / official curve artifact storage directories - those must
    always resolve to a single safe component under the intended root,
    however adversarial the display name is."""

    def _resolved_dirs(self, project_name):
        at = AppTest.from_string(_CURVE_DIR_SCRIPT, default_timeout=30)
        at.session_state["project_name"] = project_name
        at.run()
        assert not at.exception, f"resolving curve dirs raised: {at.exception}"
        return at

    def _assert_stays_under_root(self, at):
        from pathlib import Path

        artifact_root = Path(at.session_state["_artifact_root"]).resolve()
        bank_root = Path(at.session_state["_bank_root"]).resolve()
        artifact_dir = Path(at.session_state["_artifact_dir"]).resolve()
        bank_dir = Path(at.session_state["_bank_dir"]).resolve()
        assert artifact_dir == artifact_root or artifact_root in artifact_dir.parents
        assert bank_dir == bank_root or bank_root in bank_dir.parents
        # Exactly one path segment was added under the root - a traversal
        # attempt must not be able to add extra ".." segments back out.
        assert len(artifact_dir.relative_to(artifact_root).parts) == 1
        assert len(bank_dir.relative_to(bank_root).parts) == 1

    def test_posix_style_traversal_stays_under_root(self):
        at = self._resolved_dirs("../../target")
        self._assert_stays_under_root(at)

    def test_windows_style_traversal_stays_under_root(self):
        at = self._resolved_dirs("..\\..\\target")
        self._assert_stays_under_root(at)

    def test_absolute_posix_path_stays_under_root(self):
        at = self._resolved_dirs("/etc/passwd")
        self._assert_stays_under_root(at)

    def test_absolute_windows_path_stays_under_root(self):
        at = self._resolved_dirs("C:\\Windows\\System32")
        self._assert_stays_under_root(at)

    def test_bare_dotdot_stays_under_root(self):
        at = self._resolved_dirs("..")
        self._assert_stays_under_root(at)

    def test_normal_name_with_spaces_and_punctuation_still_resolves_deterministically(
        self,
    ):
        """Non-regression: an ordinary human-readable project name (the
        common case) must keep resolving to a stable directory derived the
        same way durable fit-job storage already canonicalises it, not
        break or start colliding with an unrelated project."""
        from pathlib import Path

        from ancestry_mmm.application.fit_job_service import canonical_project_id

        name = "UK Production 2026 (v2)!"
        at = self._resolved_dirs(name)
        self._assert_stays_under_root(at)
        artifact_root = Path(at.session_state["_artifact_root"]).resolve()
        artifact_dir = Path(at.session_state["_artifact_dir"]).resolve()
        assert artifact_dir.relative_to(artifact_root).parts[0] == canonical_project_id(
            name
        )

    def test_already_safe_name_keeps_its_existing_readable_directory(self):
        """A name with no character canonical_project_id needs to touch
        (matches fit-job storage's own contract) must keep resolving to its
        existing plain directory, so storage built before this fix for such
        a project remains addressable without a migration."""
        from pathlib import Path

        at = self._resolved_dirs("ancestry-fh-uk")
        self._assert_stays_under_root(at)
        artifact_root = Path(at.session_state["_artifact_root"]).resolve()
        artifact_dir = Path(at.session_state["_artifact_dir"]).resolve()
        assert artifact_dir.relative_to(artifact_root).parts[0] == "ancestry-fh-uk"
