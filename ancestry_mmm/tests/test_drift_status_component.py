"""Tests for components.ui.render_drift_status (PR E.2 requirement #10 -
"make drift status first-class in the UI").

Calls the function directly and monkeypatches the handful of `st.*` calls
it makes, rather than going through `AppTest` - `outcomes_drift_dataframe`'s
DataFrame construction has proven flaky (segfault/hang) under AppTest's
threaded script runner in this environment (a pandas/pyarrow-in-a-thread
issue, unrelated to this function's own logic), so this is the reliable
way to verify its behaviour."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from ancestry_mmm.components import ui as ui_module
from ancestry_mmm.core.outcomes import FAMILY_HISTORY, METRIC_GSA, METRIC_SIGNUP, OutcomeDefinition


def _outcome(**overrides):
    base = dict(outcome_id="fh_new", product=FAMILY_HISTORY, segment="New", metric=METRIC_GSA, source_column="col_a")
    base.update(overrides)
    return OutcomeDefinition(**base)


def _patch_streamlit(monkeypatch):
    calls = {"warning": [], "error": [], "info": []}
    monkeypatch.setattr(ui_module.st, "warning", lambda msg: calls["warning"].append(msg))
    monkeypatch.setattr(ui_module.st, "error", lambda msg: calls["error"].append(msg))
    monkeypatch.setattr(ui_module.st, "info", lambda msg: calls["info"].append(msg))
    expander_cm = MagicMock()
    expander_cm.__enter__ = MagicMock(return_value=None)
    expander_cm.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(ui_module.st, "expander", lambda *a, **k: expander_cm)
    monkeypatch.setattr(ui_module.st, "dataframe", lambda *a, **k: None)
    return calls


def test_no_model_meta_renders_nothing(monkeypatch):
    calls = _patch_streamlit(monkeypatch)
    had_drift = ui_module.render_drift_status([_outcome()], None)
    assert had_drift is False
    assert calls == {"warning": [], "error": [], "info": []}


def test_unchanged_catalogue_renders_nothing(monkeypatch):
    calls = _patch_streamlit(monkeypatch)
    outcomes = [_outcome()]
    model_meta = SimpleNamespace(outcome_catalogue_at_fit=[_outcome()])
    had_drift = ui_module.render_drift_status(outcomes, model_meta)
    assert had_drift is False
    assert calls == {"warning": [], "error": [], "info": []}


def test_calculation_relevant_drift_shows_warning_by_default(monkeypatch):
    calls = _patch_streamlit(monkeypatch)
    outcomes = [_outcome(metric=METRIC_SIGNUP)]
    model_meta = SimpleNamespace(outcome_catalogue_at_fit=[_outcome(metric=METRIC_GSA)])
    had_drift = ui_module.render_drift_status(outcomes, model_meta)
    assert had_drift is True
    assert len(calls["warning"]) == 1
    assert "fh_new" in calls["warning"][0]
    assert "Changed since fit" in calls["warning"][0]
    assert calls["error"] == []

def test_calculation_relevant_drift_shows_error_when_blocking(monkeypatch):
    calls = _patch_streamlit(monkeypatch)
    outcomes = [_outcome(metric=METRIC_SIGNUP)]
    model_meta = SimpleNamespace(outcome_catalogue_at_fit=[_outcome(metric=METRIC_GSA)])
    had_drift = ui_module.render_drift_status(outcomes, model_meta, blocking=True)
    assert had_drift is True
    assert len(calls["error"]) == 1
    assert calls["warning"] == []


def test_new_since_fit_is_informational_not_blocking(monkeypatch):
    calls = _patch_streamlit(monkeypatch)
    outcomes = [_outcome(outcome_id="a"), _outcome(outcome_id="new_one")]
    model_meta = SimpleNamespace(outcome_catalogue_at_fit=[_outcome(outcome_id="a")])
    had_drift = ui_module.render_drift_status(outcomes, model_meta)
    assert had_drift is False
    assert calls["info"] != [] or (calls["warning"] == [] and calls["error"] == [])
