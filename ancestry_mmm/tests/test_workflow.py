"""Tests for the workflow page registry (ancestry_mmm.utils.workflow) - the
single source of truth for sidebar labels, step numbering and next-step
routing shared by every page.
"""

from pathlib import Path

from ancestry_mmm.utils.workflow import (
    HOME_KEY,
    NAV_GROUPS,
    TOTAL_STEPS,
    WORKFLOW_STEPS,
    get_step,
    home_workflow_lines,
    nav_groups,
    next_step_key,
    sidebar_entries,
    step_number,
)

EXPECTED_LABELS = [
    "Home",
    "Data Upload",
    "Transform Pipeline",
    "Data Coverage",
    "Structure: Segments & Markets",
    "Causal Graph",
    "Channel & Media Units",
    "Market Descriptors",
    "Model Configuration",
    "Model Training",
    "Compare Models",
    "Diagnostics",
    "Results & Curve Bank",
    "Official Curve Generation",
    "Scenario Planner",
    "Project Export & Recovery",
]


class TestSidebarEntries:
    def test_labels_match_the_required_sidebar_order(self):
        assert [e["label"] for e in sidebar_entries()] == EXPECTED_LABELS

    def test_home_is_first_and_points_at_app_py(self):
        entries = sidebar_entries()
        assert entries[0]["key"] == HOME_KEY
        assert entries[0]["path"] == "app.py"

    def test_every_entry_has_a_page_link_target(self):
        for entry in sidebar_entries():
            assert entry["path"]

    def test_every_page_link_target_exists_on_disk(self):
        # Guards against navigation breaking silently if a page is ever renamed
        # without updating the registry `path` alongside it.
        app_root = Path(__file__).resolve().parents[1]
        for entry in sidebar_entries():
            assert (app_root / entry["path"]).is_file(), (
                f"missing page file for {entry['key']}: {entry['path']}"
            )


class TestWorkflowStepMetadata:
    def test_total_steps_is_fifteen(self):
        assert TOTAL_STEPS == 15
        assert len(WORKFLOW_STEPS) == 15

    def test_every_step_has_required_fields(self):
        for step in WORKFLOW_STEPS:
            assert step["key"]
            assert step["label"]
            assert step["path"].startswith("pages/")
            assert step["title"]
            assert step["purpose"]
            assert step["steps"], f"{step['key']} has no numbered steps"

    def test_step_numbers_are_1_indexed_and_sequential(self):
        for i, step in enumerate(WORKFLOW_STEPS, start=1):
            assert step_number(step["key"]) == i

    def test_home_has_no_step_number(self):
        assert step_number(HOME_KEY) is None

    def test_unknown_key_has_no_step_number(self):
        assert step_number("not_a_real_page") is None

    def test_get_step_returns_home_metadata(self):
        home = get_step(HOME_KEY)
        assert home["label"] == "Home"
        assert home["path"] == "app.py"

    def test_get_step_unknown_key_returns_none(self):
        assert get_step("not_a_real_page") is None


class TestHomeWorkflowLines:
    """app.py's Home page renders `home_workflow_lines()` directly (no
    separately hand-maintained list) - see git history for the bug this
    replaced: a hardcoded 9-line Home summary that silently fell out of sync
    once the workflow grew to 12 steps, missing Channel & Media Units,
    Market Descriptors and Compare Models entirely."""

    def test_returns_one_line_per_workflow_step(self):
        assert len(home_workflow_lines()) == TOTAL_STEPS == len(WORKFLOW_STEPS)

    def test_lines_are_numbered_1_indexed_in_step_order(self):
        lines = home_workflow_lines()
        for i, step in enumerate(WORKFLOW_STEPS, start=1):
            assert lines[i - 1].startswith(f"{i}. **{step['label']}**")

    def test_every_step_label_appears_exactly_once(self):
        lines = home_workflow_lines()
        for step in WORKFLOW_STEPS:
            assert sum(step["label"] in line for line in lines) == 1

    def test_adding_a_step_to_the_registry_changes_the_rendered_lines(
        self, monkeypatch
    ):
        # Regression guard for the exact bug fixed: a hardcoded Home-page
        # list silently fell out of sync once the workflow grew past 9
        # steps. Proves home_workflow_lines() tracks WORKFLOW_STEPS live -
        # mutating the registry changes the output with no other code
        # change, which a hardcoded list could never do.
        import ancestry_mmm.utils.workflow as workflow_module

        extra_step = {
            "key": "extra",
            "label": "Extra Step",
            "path": "pages/99_Extra.py",
            "purpose": "A test-only step.",
        }
        patched = WORKFLOW_STEPS + [extra_step]
        monkeypatch.setattr(workflow_module, "WORKFLOW_STEPS", patched)

        lines = workflow_module.home_workflow_lines()
        assert len(lines) == len(WORKFLOW_STEPS) + 1
        assert (
            lines[-1]
            == f"{len(WORKFLOW_STEPS) + 1}. **Extra Step** - A test-only step."
        )


class TestNavGroups:
    """Phase 1 UI overhaul (docs/decision_log.md): NAV_GROUPS is a purely
    visual grouping of the same WORKFLOW_STEPS/HOME_KEY keys for the sidebar
    - it must never invent a key, drop a page, duplicate one across groups,
    or change any route/label sidebar_entries() already governs."""

    def _all_registry_keys(self):
        return {HOME_KEY} | {step["key"] for step in WORKFLOW_STEPS}

    def test_every_nav_group_key_exists_in_the_registry(self):
        registry_keys = self._all_registry_keys()
        for group in NAV_GROUPS:
            for key in group["keys"]:
                assert key in registry_keys, (
                    f"unknown key {key!r} in group {group['label']!r}"
                )

    def test_every_registry_key_appears_in_exactly_one_group(self):
        registry_keys = self._all_registry_keys()
        seen = []
        for group in NAV_GROUPS:
            seen.extend(group["keys"])
        assert sorted(seen) == sorted(registry_keys), (
            "nav groups must cover every page exactly once"
        )
        assert len(seen) == len(set(seen)), (
            "no page may appear in more than one nav group"
        )

    def test_group_labels_are_non_empty_and_unique(self):
        labels = [g["label"] for g in NAV_GROUPS]
        assert all(labels)
        assert len(labels) == len(set(labels))

    def test_home_is_alone_in_the_first_group(self):
        assert NAV_GROUPS[0]["keys"] == [HOME_KEY]

    def test_nav_groups_resolves_keys_to_full_step_metadata(self):
        resolved = nav_groups()
        assert len(resolved) == len(NAV_GROUPS)
        for group, resolved_group in zip(NAV_GROUPS, resolved):
            assert resolved_group["label"] == group["label"]
            assert len(resolved_group["entries"]) == len(group["keys"])
            for key, entry in zip(group["keys"], resolved_group["entries"]):
                assert entry["key"] == key
                assert entry == get_step(key)


class TestNextStepMapping:
    def test_data_upload_leads_to_transform_pipeline(self):
        assert next_step_key("data_upload") == "transform_pipeline"

    def test_chain_covers_the_whole_workflow_in_order(self):
        keys = [step["key"] for step in WORKFLOW_STEPS]
        chained = [keys[0]]
        current = keys[0]
        while True:
            nxt = next_step_key(current)
            if nxt is None:
                break
            chained.append(nxt)
            current = nxt
        assert chained == keys

    def test_last_step_has_no_next(self):
        last_key = WORKFLOW_STEPS[-1]["key"]
        assert next_step_key(last_key) is None

    def test_unknown_key_has_no_next(self):
        assert next_step_key("not_a_real_page") is None


class TestProhibitedTerminology:
    """PR 1: No current user-facing page or workflow label may expose
    vendor-handover terminology (handover, post-handover, inherits,
    training completion, competency, handover readiness) in its
    current-purpose display."""

    PROHIBITED_TERMS = [
        "handover",
        "post-handover",
        "inherits",
        "training completion",
        "competency",
        "handover readiness",
    ]

    def test_no_workflow_label_contains_handover_terminology(self):
        for step in WORKFLOW_STEPS:
            for field in ("label", "title", "purpose"):
                val = step.get(field, "")
                for term in self.PROHIBITED_TERMS:
                    assert term.lower() not in val.lower(), (
                        f"Prohibited term '{term}' found in workflow step "
                        f"'{step['key']}' field '{field}': '{val}'"
                    )

    def test_no_workflow_next_field_contains_handover_terminology(self):
        for step in WORKFLOW_STEPS:
            val = step.get("next", "")
            for term in self.PROHIBITED_TERMS:
                assert term.lower() not in val.lower(), (
                    f"Prohibited term '{term}' found in workflow step "
                    f"'{step['key']}' field 'next': '{val}'"
                )
