"""Work Package 0 (`Media-Mix-Lab: Coding LLM Next Steps After PR #253`):
anti-drift checks for current-state documentation.

These are deliberately narrow, literal checks against specific claims known
to have drifted after PRs #250-#253 (mixed-frequency executor, Candidate A
Search engine capability). They are not a general prose-consistency checker
and must not be treated as a competing requirements authority - they only
catch a status file re-asserting a claim already proven false by the code
or by another status file.

When a future PR resolves a real gap (e.g. Candidate A production
integration), update the "current" markers here in the same PR rather than
weakening or deleting the assertion.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README = REPO_ROOT / "README.md"
REPO_REVIEW = REPO_ROOT / "REPO_REVIEW_AND_NEXT_STEPS.md"
FREQUENCY_DECISION = REPO_ROOT / "docs" / "decision_required_frequency_methods.md"
SPEC_AUTHORITY = REPO_ROOT / "docs" / "specification_authority.md"

STATUS_DOCS = [README, REPO_REVIEW]

# Literal phrasing that has previously appeared in status docs claiming
# mixed-frequency execution does not exist. The executor has existed since
# PR #250 (docs/mixed_frequency_alignment_wp1.md); these phrases must not
# come back into a "current state" document without a corresponding fix.
STALE_MIXED_FREQUENCY_PHRASES = [
    "executable frequency conversion for non-native-cadence sources, the",
    "conversion-method registry remains empty",
    "registry remains empty. No interpolation, allocation,",
]

# Literal phrasing that has previously appeared claiming capacity-constrained
# Search modelling is wholly absent. The Candidate A engine capability has
# existed since PR #253 (ancestry_mmm/core/search_capacity.py); these must
# not reappear unqualified.
STALE_SEARCH_ABSENT_PHRASES = [
    "capacity-constrained Search model, and Chronos-2 integration are\n  not yet implemented",
    "capacity-constrained Search model, and Chronos-2 integration are not yet implemented",
]

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_mixed_frequency_execution_not_claimed_absent():
    """A status doc must not simultaneously be reachable from this test
    suite (i.e. describe current behaviour) while asserting the executor
    does not exist - it has, since PR #250."""
    for doc in STATUS_DOCS:
        text = _read(doc)
        for phrase in STALE_MIXED_FREQUENCY_PHRASES:
            assert phrase not in text, (
                f"{doc.name} contains stale claim that mixed-frequency "
                f"execution is unimplemented: {phrase!r}. The governed "
                "executor has existed since PR #250 "
                "(docs/mixed_frequency_alignment_wp1.md) - update the "
                "status doc instead of reintroducing this claim."
            )


def test_candidate_a_search_engine_not_claimed_wholly_absent():
    """A status doc must not claim capacity-constrained Search modelling is
    wholly absent - the Candidate A engine capability has existed since
    PR #253, even though it is not yet integrated into the ordinary fit
    workflow. The two facts must be stated separately, never collapsed into
    one blanket 'not implemented' claim."""
    for doc in STATUS_DOCS:
        text = _read(doc)
        for phrase in STALE_SEARCH_ABSENT_PHRASES:
            assert phrase not in text, (
                f"{doc.name} contains stale claim that Search capacity "
                f"modelling is wholly absent: {phrase!r}. "
                "ancestry_mmm/core/search_capacity.py (REQ-SEARCH-002) has "
                "existed since PR #253 as engine capability, even though "
                "it is not yet integrated into Model Training - state that "
                "distinction, not a blanket absence."
            )


def test_repo_review_documents_candidate_a_integration_gap():
    """REPO_REVIEW_AND_NEXT_STEPS.md must distinguish the Candidate A engine
    capability existing from it being integrated into the ordinary fit
    workflow - collapsing the two into a single claim is exactly the drift
    this work package exists to prevent."""
    text = _read(REPO_REVIEW)
    assert "search_capacity.py" in text, (
        "REPO_REVIEW_AND_NEXT_STEPS.md must reference the implemented "
        "Candidate A engine module."
    )
    assert (
        "not yet implemented" in text.lower() or "not yet integrated" in text.lower()
    ), (
        "REPO_REVIEW_AND_NEXT_STEPS.md must state that full integration "
        "with the ordinary MMM fit workflow is not yet implemented."
    )


CURRENT_MAIN_FIELD_RE = re.compile(
    r"current\s*`?main`?\s*(reviewed|sha|is)", re.IGNORECASE
)


def test_repo_review_does_not_use_a_necessarily_drifting_current_main_field():
    """A version-controlled status file must never assert "this SHA is
    current `main`": a branch cannot know the future squash-merge commit
    SHA that will become `main`, so that field is guaranteed to go stale
    the moment the next PR merges (exactly what happened - an earlier
    revision claimed PR #261's merge commit as "current `main`" while
    PR #262 was already merged on top of it, see docs/decision_log.md and
    the Work Package 2 entry that replaced this convention).

    The replacement convention is a "Repository state through merged PR
    #<N>" milestone marker plus explicitly historical/superseded SHAs -
    never a field claiming to be the live current SHA."""
    text = _read(REPO_REVIEW)
    assert not CURRENT_MAIN_FIELD_RE.search(text), (
        "REPO_REVIEW_AND_NEXT_STEPS.md contains a 'current main' SHA field "
        "again - this convention was deliberately removed because it "
        "necessarily drifts on every subsequent merge. Use a "
        "'Repository state through merged PR #<N>' milestone marker "
        "instead, and resolve the actual live origin/main SHA from GitHub, "
        "never from this file."
    )
    assert re.search(r"Repository state through merged PR #\d+", text), (
        "REPO_REVIEW_AND_NEXT_STEPS.md must state its baseline as "
        "'Repository state through merged PR #<N>', not a live SHA field."
    )


def test_repo_review_historical_shas_are_labelled():
    """Every 40-hex SHA mentioned in the file must be explicitly labelled
    historical/superseded (or as a specific merge commit for a milestone
    PR) in the same paragraph - never left looking like unlabelled current
    state."""
    text = _read(REPO_REVIEW)
    paragraphs = text.split("\n\n")
    for paragraph in paragraphs:
        for sha in SHA_RE.findall(paragraph):
            lowered = paragraph.lower()
            assert (
                "historical" in lowered
                or "superseded" in lowered
                or "merge commit" in lowered
            ), (
                f"REPO_REVIEW_AND_NEXT_STEPS.md mentions SHA {sha} without "
                "labelling it historical/superseded/as a specific merge "
                "commit in the same paragraph - a status file must not "
                "leave a bare SHA looking like unlabelled current state."
            )


def test_frequency_decision_doc_reflects_approved_wp1_catalogue():
    """The frequency-methods decision-required doc must not claim the
    conversion registry is empty - the WP1 catalogue has been approved and
    registered since PR #250."""
    text = _read(FREQUENCY_DECISION)
    assert "registry remains empty" not in text, (
        "docs/decision_required_frequency_methods.md still claims the "
        "conversion-method registry is empty; the WP1 catalogue "
        "(calendar_overlap_allocation / release_aware_locf / "
        "native_cadence_only / calendar_event_alignment) has been approved "
        "and registered since PR #250 "
        "(ancestry_mmm/core/frequency_conversion.py:ensure_approved_frequency_methods)."
    )
    assert "approved and registered" in text or "is approved" in text, (
        "docs/decision_required_frequency_methods.md must state that the "
        "WP1 method catalogue is approved for official use."
    )


# Literal phrasing that has previously appeared in docs/specification_authority.md
# claiming the mixed-frequency conversion-method registry is empty as a
# blanket, current-state fact. The WP1 catalogue has been approved and
# registered since PR #250 (docs/decision_required_frequency_methods.md,
# core.frequency_conversion.ensure_approved_frequency_methods) - a bare
# "registry is currently empty"/"registry above is therefore still empty"
# claim is stale unless scoped to "outside the WP1 catalogue".
STALE_SPEC_AUTHORITY_REGISTRY_EMPTY_PHRASES = [
    "the conversion-method registry is currently empty",
    "the conversion-method registry above is therefore still empty",
]


def test_spec_authority_frequency_registry_not_claimed_empty():
    """docs/specification_authority.md must not claim the mixed-frequency
    conversion-method registry is empty - the WP1 catalogue has been
    approved and registered since PR #250, the same fact
    test_frequency_decision_doc_reflects_approved_wp1_catalogue enforces
    for docs/decision_required_frequency_methods.md. A repository authority
    doc and its own dependent decision doc must not disagree about whether
    a registered method catalogue exists."""
    text = _read(SPEC_AUTHORITY)
    for phrase in STALE_SPEC_AUTHORITY_REGISTRY_EMPTY_PHRASES:
        assert phrase not in text, (
            f"docs/specification_authority.md contains stale claim: "
            f"{phrase!r}. The WP1 catalogue (six method/variable-class "
            "registrations) has been approved and registered since PR #250 "
            "(docs/decision_required_frequency_methods.md, "
            "core.frequency_conversion.ensure_approved_frequency_methods) "
            "and executes via core.official_preparation - update the "
            "authority doc instead of reintroducing this claim."
        )


def test_spec_authority_references_req_search_002():
    """docs/specification_authority.md must reference REQ-SEARCH-002 (the
    approved, implemented Candidate A Search mediation/capacity engine
    record) in its 'approved requirement records already implemented'
    section - the record has existed and been indexed since 2026-08-15, and
    an authority doc that never mentions it while still asserting 'no
    approved requirement/decision yet' for Search demand/capacity
    mathematics is exactly the kind of drift this file exists to prevent."""
    text = _read(SPEC_AUTHORITY)
    assert "REQ-SEARCH-002" in text, (
        "docs/specification_authority.md must reference REQ-SEARCH-002 "
        "(docs/approved_requirements/REQ-SEARCH-002.md), approved "
        "2026-08-15 and indexed in docs/approved_requirements/index.json."
    )


def test_readme_does_not_claim_candidate_a_wholly_unwired_from_diagnostics():
    """README.md must not claim Candidate A is wholly unwired from
    Diagnostics - a dedicated 'Candidate A Search' Diagnostics tab
    (DiagnosticsArtefact.search_capacity, schema v7) has existed since
    PR #257 (WP3). README may still correctly state Candidate A is not
    wired into Results, official curves, or the Scenario Planner - those
    remain true - but 'Diagnostics' must not appear in that same negative
    list without qualification."""
    text = _read(README)
    assert "not yet wired into Diagnostics" not in text, (
        "README.md claims Candidate A is 'not yet wired into Diagnostics' - "
        "false since PR #257 added a dedicated 'Candidate A Search' "
        "Diagnostics tab (pages/06_Diagnostics.py, "
        "DiagnosticsArtefact.search_capacity). State the Results/official-"
        "curves/Scenario-Planner gap separately from Diagnostics."
    )
