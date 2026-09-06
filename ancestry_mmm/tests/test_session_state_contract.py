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


_LEGACY_MIGRATION_SCRIPT = """
from ancestry_mmm.utils.session_state import curve_artifact_store_dir, curve_bank_dir
import streamlit as st

st.session_state["_artifact_dir"] = str(curve_artifact_store_dir())
st.session_state["_bank_dir"] = str(curve_bank_dir())
"""


class TestCurveStorageDirsMigrateLegacyProjectDirectories:
    """Regression for review PRRT_kwDOTd28Js6fnFam: an existing project's
    curve stores under the pre-canonical-project-ID literal display-name
    directory must be migrated into the canonical directory, not silently
    abandoned - otherwise a project's exploratory/official curve stores
    appear empty after upgrading even though the artifacts remain on disk."""

    def _resolved_dirs(self, monkeypatch, tmp_path, project_name):
        import ancestry_mmm.utils.session_state as ss

        artifact_root = tmp_path / "artifact-root"
        bank_root = tmp_path / "bank-root"
        monkeypatch.setattr(ss, "CURVE_ARTIFACT_ROOT", artifact_root)
        monkeypatch.setattr(ss, "CURVE_BANK_ROOT", bank_root)
        at = AppTest.from_string(_LEGACY_MIGRATION_SCRIPT, default_timeout=30)
        at.session_state["project_name"] = project_name
        at.run()
        assert not at.exception, f"resolving curve dirs raised: {at.exception}"
        return at, artifact_root, bank_root

    def test_existing_safe_name_with_spaces_migrates_and_loses_no_artifacts(
        self, monkeypatch, tmp_path
    ):
        from pathlib import Path

        from ancestry_mmm.application.fit_job_service import canonical_project_id

        project_name = "UK Production 2026"
        artifact_root = tmp_path / "artifact-root"
        bank_root = tmp_path / "bank-root"
        legacy_artifact_dir = artifact_root / project_name
        legacy_artifact_dir.mkdir(parents=True)
        (legacy_artifact_dir / "artifact.txt").write_text(
            "official curve payload", encoding="utf-8"
        )
        legacy_bank_dir = bank_root / project_name
        legacy_bank_dir.mkdir(parents=True)
        (legacy_bank_dir / "entry.json").write_text(
            '{"curve": "bank"}', encoding="utf-8"
        )

        at, artifact_root, bank_root = self._resolved_dirs(
            monkeypatch, tmp_path, project_name
        )

        canonical_name = canonical_project_id(project_name)
        expected_artifact_dir = artifact_root / canonical_name
        expected_bank_dir = bank_root / canonical_name
        # The canonical store is now what is used.
        assert Path(at.session_state["_artifact_dir"]) == expected_artifact_dir
        assert Path(at.session_state["_bank_dir"]) == expected_bank_dir
        # No artifacts were lost - they moved to the canonical directory.
        assert not legacy_artifact_dir.exists()
        assert not legacy_bank_dir.exists()
        assert (expected_artifact_dir / "artifact.txt").read_text(
            encoding="utf-8"
        ) == "official curve payload"
        assert (expected_bank_dir / "entry.json").read_text(
            encoding="utf-8"
        ) == '{"curve": "bank"}'

    def test_subsequent_load_does_not_repeat_migration(self, monkeypatch, tmp_path):
        project_name = "UK Production 2026"
        artifact_root = tmp_path / "artifact-root"
        legacy_dir = artifact_root / project_name
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "artifact.txt").write_text("payload", encoding="utf-8")

        at_first, artifact_root, _ = self._resolved_dirs(
            monkeypatch, tmp_path, project_name
        )
        at_second, artifact_root, _ = self._resolved_dirs(
            monkeypatch, tmp_path, project_name
        )

        assert (
            at_first.session_state["_artifact_dir"]
            == at_second.session_state["_artifact_dir"]
        )
        from pathlib import Path

        resolved_dir = Path(at_second.session_state["_artifact_dir"])
        assert resolved_dir.is_dir()
        assert (resolved_dir / "artifact.txt").read_text(encoding="utf-8") == "payload"

    def test_path_traversal_project_name_cannot_reach_a_legacy_directory_outside_root(
        self, monkeypatch, tmp_path
    ):
        outside_marker = tmp_path.parent / "outside-canary-session-state"
        outside_marker.mkdir(exist_ok=True)
        (outside_marker / "do-not-touch.txt").write_text("safe", encoding="utf-8")

        at, artifact_root, _ = self._resolved_dirs(
            monkeypatch, tmp_path, "../../outside-canary-session-state"
        )

        assert (outside_marker / "do-not-touch.txt").exists()
        from pathlib import Path

        artifact_dir = Path(at.session_state["_artifact_dir"]).resolve()
        assert artifact_root.resolve() in artifact_dir.parents or (
            artifact_dir == artifact_root.resolve()
        )

    def test_both_legacy_and_canonical_populated_fails_closed(
        self, monkeypatch, tmp_path
    ):
        from ancestry_mmm.application.fit_job_service import canonical_project_id

        project_name = "UK Production 2026"
        artifact_root = tmp_path / "artifact-root"
        legacy_dir = artifact_root / project_name
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "legacy.txt").write_text("legacy payload", encoding="utf-8")
        canonical_dir = artifact_root / canonical_project_id(project_name)
        canonical_dir.mkdir(parents=True)
        (canonical_dir / "canonical.txt").write_text(
            "canonical payload", encoding="utf-8"
        )

        at, artifact_root, _ = self._resolved_dirs(monkeypatch, tmp_path, project_name)

        # Both directories remain exactly as they were - no merge, no loss.
        assert (legacy_dir / "legacy.txt").exists()
        assert (canonical_dir / "canonical.txt").exists()
        assert not (canonical_dir / "legacy.txt").exists()
        from pathlib import Path

        assert Path(at.session_state["_artifact_dir"]) == canonical_dir
